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
    """流式合成：逐段产出文本增量；首档未输出时可切到备用模型。

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
            # A mid-answer provider switch would splice two models into one
            # response.  Before any visible chunk, however, the fallback role
            # can safely take over and still satisfy the primary/fallback contract.
            if produced:
                return
            continue
        if produced:
            return
    return


def _with_private_memory(
    messages: list[dict[str, str]], private_memory_context: str | None
) -> list[dict[str, str]]:
    """Add scoped conversation recall as internal context without exposing it as RAG evidence."""

    if not private_memory_context:
        return messages
    memory_instruction = {
        "role": "system",
        "content": (
            "以下内容仅是当前用户当前会话的私有历史片段，用于保持上下文一致。"
            "不要把它称为知识库资料或引用来源，也不要透露检索机制。\n\n"
            f"{private_memory_context}"
        ),
    }
    # Keep the route-specific system prompt first so its product constraints
    # remain higher priority than recalled user-authored text.
    return [messages[0], memory_instruction, *messages[1:]]


def build_direct_chat_messages(
    history: list[dict[str, str]], private_memory_context: str | None = None
) -> list[dict[str, str]]:
    """Prepend direct-chat rules and optional private memory to recent turns."""

    return _with_private_memory(
        [{"role": "system", "content": prompts.CHAT_SYSTEM}, *history],
        private_memory_context,
    )


async def stream_direct_chat_text(
    history: list[dict[str, str]],
    *,
    private_memory_context: str | None = None,
    usage_capture: UsageCapture | None = None,
) -> AsyncIterator[str]:
    """Yield direct-chat output as it arrives, then retain the old fallback path.

    The orchestrator owns SSE persistence, so this generator intentionally
    yields only text.  That lets each provider chunk reach the user promptly
    while still allowing the caller to persist one complete assistant message
    after the stream ends.
    """

    messages = build_direct_chat_messages(history, private_memory_context)
    produced = False
    async for delta in stream_text(messages, usage_capture=usage_capture):
        produced = True
        yield delta
    if produced:
        return

    # A provider may support ordinary completion but not streaming.  Preserve
    # that compatibility by exposing its finished text through the same
    # iterator; callers do not need a separate persistence path.
    text = await compose_text(messages, usage_capture=usage_capture)
    if text:
        yield text


async def direct_chat_text(
    history: list[dict[str, str]],
    *,
    private_memory_context: str | None = None,
    usage_capture: UsageCapture | None = None,
) -> str | None:
    """Stream a normal chat or clarification turn, then try non-stream fallback.

    The caller keeps the deterministic PRD question as the final offline path,
    so this helper returns None when no configured provider produced text.
    """

    streamed: list[str] = []
    async for delta in stream_direct_chat_text(
        history,
        private_memory_context=private_memory_context,
        usage_capture=usage_capture,
    ):
        streamed.append(delta)
    return "".join(streamed) if streamed else None


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


def _clip_summary_text(value: str, limit: int, *, preserve_lines: bool = False) -> str:
    """压缩摘要文本并尽量在句末截断，避免结果卡显示半截长段落。"""
    text = (
        "\n".join(" ".join(line.split()) for line in value.splitlines() if line.strip())
        if preserve_lines
        else " ".join(value.split())
    )
    if len(text) <= limit:
        return text
    punctuation = "。！？!?；;"
    boundary = max((text.rfind(mark, 0, limit) for mark in punctuation), default=-1)
    cutoff = boundary + 1 if boundary >= max(24, limit // 3) else limit
    return text[:cutoff].rstrip(" ，,、:：") + "..."


def compact_summary(text: str, *, max_lines: int = 3, max_chars: int = 220) -> str:
    """为结果摘要卡提取短结论，完整回答仍保留在 assistant 消息中。

    模板降级回答会同时包含步骤标记和工具明细；摘要卡只需要结论，
    因此过滤纯步骤标记并保留首尾少量内容。这个投影也适用于 LLM 长回答，
    避免把摘要卡变成第二份完整回答。
    """
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    detail_lines = [line for line in lines if line[:1] not in "✓✗×·"]
    if detail_lines:
        lines = detail_lines
    if len(lines) > max_lines:
        lines = [*lines[: max_lines - 1], lines[-1]]
    return _clip_summary_text("\n".join(lines), max_chars, preserve_lines=True)


def template_compact_tool_summary(tool_name: str, result: Any) -> str:
    """把工具结果归纳成一条可扫描的结论，不重复渲染详情卡内容。"""
    if not isinstance(result, dict):
        return "步骤已完成。"
    if result.get("error"):
        return f"本步骤未完成：{_clip_summary_text(str(result['error']), 72)}"

    if tool_name == "course.search":
        count = len(result.get("units") or [])
        return f"课程检索完成：找到 {count} 个相关教学单元。" if count else "未找到匹配的教学单元。"
    if tool_name == "graph.reason":
        count = len(result.get("nodes") or [])
        return f"知识图谱定位完成：找到 {count} 个相关节点。" if count else "未定位到相关知识节点。"
    if tool_name == "task.preview":
        card = result.get("card") or result
        title = card.get("title")
        return f"已生成学习任务「{title}」。" if title else "已生成学习任务。"
    if tool_name == "task.create":
        title = result.get("title")
        return f"已创建学习任务「{title}」。" if title else "学习任务已创建。"
    if tool_name == "diagnostic.preview":
        count = result.get("error_count")
        return f"诊断完成：发现 {count} 个问题。" if count is not None else "诊断已完成。"
    if tool_name == "diagnostic.save_summary":
        return "诊断摘要与掌握度已更新。"
    if tool_name == "mastery.update":
        return f"掌握度已更新 {len(result.get('updates') or [])} 项。"
    if tool_name == "rag.search":
        return f"资料检索完成：找到 {len(result.get('hits') or [])} 条相关内容。"
    if tool_name == "rag.answer":
        answer = result.get("answer")
        if answer:
            return compact_summary(str(answer), max_lines=1, max_chars=140)
        if result.get("refused"):
            return "现有资料不足，无法回答该问题。"
        return "资料问答已完成。"
    if tool_name == "rag.preview_upload":
        return "资料预检通过。" if result.get("ok") else "资料预检未通过。"
    return "步骤已完成。"


def template_compact_plan_summary(
    plan: dict[str, Any], tool_results: dict[str, Any], *, max_lines: int = 3
) -> str:
    """为无 Provider 的降级路径生成最多三条关键结论。"""
    items: list[str] = []
    for step in plan.get("steps") or []:
        title = str(step.get("title") or "步骤")
        if step.get("status") == "failed":
            item = f"{title}未完成。"
        elif step.get("id") in tool_results:
            item = template_compact_tool_summary(
                str(step.get("tool") or ""), tool_results[step["id"]]
            )
        else:
            item = f"{title}已完成。"
        if item not in items:
            items.append(item)
    if not items:
        return "本次处理已完成。"
    if len(items) > max_lines:
        items = [*items[: max_lines - 1], items[-1]]
    return compact_summary("\n".join(items), max_lines=max_lines)


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


def build_general_knowledge_messages(
    user_input: str, private_memory_context: str | None = None
) -> list[dict[str, str]]:
    """Build the RAG-insufficient fallback request without leaking tool payloads.

    The provider receives only the student's question.  In particular, it must
    not receive an empty retrieval result or a refusal message as pseudo-evidence,
    because that would invite it to present the answer as knowledge-base grounded.
    """

    return _with_private_memory([
        {"role": "system", "content": prompts.GENERAL_KNOWLEDGE_SYSTEM},
        {"role": "user", "content": f"学生的问题：{user_input}"},
    ], private_memory_context)
