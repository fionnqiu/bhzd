"""LLM 合成 + 模板降级合成（PRD-06 §11.1 降级路径 / 蓝图 §10.5）。

两条合成路径：
- LLM 可用（B1 providers 就绪且配置）：compose_text / stream_text 流式合成；
- 不可用（未配置、主备均失败）：template_* 系列只做**确定性中文渲染**，
  把工具结果原样组织给学生，绝不编造内容（蓝图 §1 无 LLM 降级决策）。

providers 一律函数内惰性导入：B1 未落地时本模块仍可导入，所有 LLM
入口安静降级（返回 None / 空迭代）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from . import prompts

logger = logging.getLogger(__name__)

@dataclass
class UsageCapture:
    """Carry one composition call's usage without sharing state across runs.

    ``compose_text`` and ``stream_text`` keep their text-only public return
    contracts.  The optional capture gives the orchestrator a request-local
    side channel, which is safe when multiple background runs compose at once.
    """

    value: dict[str, Any] | None = None

    def clear(self) -> None:
        """Discard a previous attempt before a new provider call starts."""

        self.value = None

    def record(self, result: dict[str, Any]) -> None:
        """Keep only the provider fields persisted on the owning agent run."""

        self.value = {
            "model": result.get("model"),
            "usage": result.get("usage"),
            "provider_id": result.get("provider_id"),
        }


def _providers():
    """惰性导入 B1 providers；未就绪返回 None（离线降级的前提）。"""
    try:
        from . import providers  # type: ignore
    except ImportError:
        return None
    return providers


async def compose_text(
    messages: list[dict], *, usage_capture: UsageCapture | None = None
) -> str | None:
    """非流式合成：主模型失败回退备用模型（PRD-06 §11.1），均失败返回 None。

    ``usage_capture`` is deliberately optional so existing callers that only
    need text remain source-compatible.
    """

    if usage_capture is not None:
        usage_capture.clear()
    providers = _providers()
    if providers is None:
        return None
    for role in ("primary", "fallback"):
        try:
            result = await providers.complete(messages, role=role)
        except Exception:
            logger.warning("LLM 合成失败（role=%s），尝试下一档", role, exc_info=True)
            continue
        if result and result.get("text"):
            if usage_capture is not None:
                usage_capture.record(result)
            return str(result["text"])
    return None


async def stream_text(
    messages: list[dict], *, usage_capture: UsageCapture | None = None
) -> AsyncIterator[str]:
    """流式合成：逐段产出文本增量；任何失败都安静结束（调用方走模板降级）。

    Usage is attached to the capture belonging to this iterator's caller,
    rather than a module global that another concurrent run could overwrite.
    """

    if usage_capture is not None:
        usage_capture.clear()
    providers = _providers()
    if providers is None:
        return
    for role in ("primary", "fallback"):
        produced = False
        try:
            async for event in providers.stream_deltas(messages, role=role):
                if event.get("delta"):
                    produced = True
                    yield str(event["delta"])
                elif event.get("done") is not None or "done" in event:
                    if usage_capture is not None:
                        usage_capture.record(event)
        except Exception:
            logger.warning("LLM 流式合成失败（role=%s）", role, exc_info=True)
            return  # 已经吐出部分内容，不能再换角色重流，交给调用方补模板
        if produced:
            return
    return


# ---------------------------------------------------------------------------
# 模板降级合成（确定性，离线可用；只渲染工具结果，不发明内容）
# ---------------------------------------------------------------------------

def _short_json(value: Any, limit: int = 200) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def template_tool_summary(tool_name: str, result: Any) -> str:
    """把单个工具结果渲染成一行/一段中文摘要（执行轨迹与降级回答共用）。"""
    if not isinstance(result, dict):
        return f"{tool_name} 执行完成：{_short_json(result)}"
    if result.get("error"):
        return f"{tool_name} 未能完成：{result['error']}"

    if tool_name == "course.search":
        units = result.get("units") or []
        if not units:
            return "课程检索：没有找到匹配的教学单元。"
        lines = [f"课程检索：找到 {len(units)} 个教学单元："]
        for i, u in enumerate(units, 1):
            lines.append(
                f"{i}. {u.get('title', u.get('unit_id'))}"
                f"（{u.get('modality', '-')}，约 {u.get('est_minutes', '-')} 分钟）"
            )
        return "\n".join(lines)

    if tool_name == "graph.reason":
        nodes = result.get("nodes") or []
        if not nodes:
            return f"图谱推理完成：{_short_json(result)}"
        names = "、".join(str(n.get("label") or n.get("id")) for n in nodes[:6])
        return f"图谱定位到 {len(nodes)} 个相关节点：{names}"

    if tool_name == "task.preview":
        card = result.get("card") or result
        steps = card.get("steps") or []
        lines = [f"任务卡预览：{card.get('title', '未命名任务')}"]
        if card.get("goal"):
            lines.append(f"目标：{card['goal']}")
        for i, s in enumerate(steps, 1):
            title = s.get("title") if isinstance(s, dict) else str(s)
            lines.append(f"步骤{i}：{title}")
        if card.get("est_minutes"):
            lines.append(f"预计时长：约 {card['est_minutes']} 分钟")
        return "\n".join(lines)

    if tool_name == "task.create":
        return f"已创建学习任务：{result.get('title', result.get('task_id', ''))}"

    if tool_name == "diagnostic.preview":
        count = result.get("error_count")
        if count is None:
            return f"诊断预览完成：{_short_json(result)}"
        return f"诊断完成：发现 {count} 个问题，详情见诊断报告。"

    if tool_name == "diagnostic.save_summary":
        return "诊断摘要与掌握度更新已保存。"

    if tool_name == "mastery.update":
        updates = result.get("updates") or []
        return f"掌握度已更新（{len(updates)} 项）。"

    if tool_name == "rag.search":
        hits = result.get("hits") or []
        return f"资料召回完成：命中 {len(hits)} 条切片。"

    if tool_name == "rag.answer":
        answer = result.get("answer")
        if answer:
            return str(answer)
        if result.get("refused"):
            return "现有资料不足以回答该问题，已按规则拒答。"
        return f"问答完成：{_short_json(result)}"

    if tool_name == "rag.preview_upload":
        warnings = result.get("warnings") or []
        base = "上传预检通过。" if result.get("ok") else "上传预检未通过。"
        return base + ("注意：" + "；".join(map(str, warnings)) if warnings else "")

    return f"{tool_name} 执行完成。"


def template_plan_summary(plan: dict[str, Any], tool_results: dict[str, Any]) -> str:
    """整轮运行的降级总结：列步骤结果，不生成自然语言发挥（PRD-06 §11.1）。

    plan: {"steps":[{id,title,status,tool?}]}；tool_results: {step_id: result}。
    """
    steps = plan.get("steps") or []
    lines: list[str] = []
    for step in steps:
        status = step.get("status")
        mark = {"completed": "✓", "failed": "✗", "cancelled": "－"}.get(status, "·")
        lines.append(f"{mark} {step.get('title', step.get('id'))}")
        result = tool_results.get(step.get("id"))
        if result is not None and step.get("tool"):
            lines.append(template_tool_summary(step["tool"], result))
    if not lines:
        return "本轮没有执行任何步骤。"
    return "\n".join(lines)


def build_compose_messages(user_input: str, tool_results: dict[str, Any]) -> list[dict]:
    """组装发给 LLM 的消息：系统提示 + 用户目标 + 工具结果原文（JSON）。"""
    context = json.dumps(tool_results, ensure_ascii=False, default=str)
    return [
        {"role": "system", "content": prompts.COMPOSE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"学生的学习目标/问题：{user_input}\n\n"
                f"以下是工具返回的原始结果（你的回答只能基于这些内容）：\n{context}"
            ),
        },
    ]
