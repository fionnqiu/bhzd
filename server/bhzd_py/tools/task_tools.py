"""task.preview（read）与 task.create（write，确认门）（蓝图 §9）。

任务卡内容是**确定性组装**：标题/目标/步骤/评分规则来自参数与数据
（课程检索、图谱节点名），不由 LLM 生成——LLM 只负责在最终消息里
解释这张卡（PRD-06 §6.1：Agent 可生成任务卡预览，但不可编造规范）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from ..db import utc_now_iso
from .registry import ToolContext, ToolSpec, emit_telemetry

logger = logging.getLogger(__name__)

_DATA_TYPE_LABELS = {
    "text": "文本",
    "image": "图像",
    "audio": "语音",
    "video": "视频",
}


def _cap_names(cap_ids: list[str]) -> list[dict[str, str]]:
    """cap_id → 名称（graphx 惰性查询；未就绪时以 id 代名称，不阻断组卡）。"""
    try:
        from ..graphx import reason as gx_reason  # B4，惰性导入
    except ImportError:
        gx_reason = None
    named: list[dict[str, str]] = []
    for cap_id in cap_ids:
        label = cap_id
        if gx_reason is not None:
            try:
                detail = gx_reason.node_detail(cap_id)
                if isinstance(detail, dict) and detail.get("label"):
                    label = str(detail["label"])
            except Exception:
                logger.warning("能力节点 %s 查询失败，以 id 代名称", cap_id)
        named.append({"cap_id": cap_id, "name": label})
    return named


def build_task_card(args: dict[str, Any]) -> dict[str, Any]:
    """组装 TaskCard（不落库）。步骤至少 2 步（契约要求）。"""
    data_type = args.get("data_type")
    label = _DATA_TYPE_LABELS.get(data_type or "", "")
    title = args.get("title") or (f"{label}标注练习任务" if label else "标注练习任务")
    goal = args.get("goal") or "掌握该任务对应的标注规范并能独立完成练习"
    cap_ids = list(args.get("cap_ids") or [])
    steps = args.get("steps") or [
        {"title": "学习规范", "description": "阅读关联资料与教学单元，明确标注规则"},
        {"title": "完成练习", "description": "按规范完成一组标注练习样本"},
        {"title": "自查常见错误", "description": "对照评分规则自查并修正"},
    ]
    resources = args.get("resources") or []
    rubric = args.get("rubric") or {
        "full_score": 100,
        "rules": [
            {"rule": "标注结果符合规范定义", "score": 60},
            {"rule": "边界/字段完整无遗漏", "score": 40},
        ],
    }
    return {
        "title": title,
        "goal": goal,
        "data_type": data_type,
        "scenario_id": args.get("scenario_id"),
        "cap_ids": cap_ids,
        "cap_names": _cap_names(cap_ids),
        "steps": steps if len(steps) >= 2 else steps + [{"title": "完成练习", "description": "按规范完成练习"}],
        "resources": resources,
        "est_minutes": args.get("est_minutes") or 45,
        "rubric": rubric,
    }


def task_preview_handler(ctx: ToolContext) -> dict[str, Any]:
    card = build_task_card(ctx.args)
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_preview_created",
        {
            "data_type": card.get("data_type"),
            "scenario_id": card.get("scenario_id"),
            "cap_count": len(card.get("cap_ids") or []),
        },
    )
    return {"card": card}


def task_create_preview(ctx: ToolContext) -> dict[str, Any]:
    """确认门预览载荷：展示将创建的任务卡全文（PRD-06 §6.4：名称/目标/步骤/关联能力）。"""
    card = build_task_card(ctx.args)
    return {
        "action": "task.create",
        "summary": f"将创建学习任务「{card['title']}」",
        "card": card,
    }


def task_create_apply(ctx: ToolContext) -> dict[str, Any]:
    """确认后写 learning_tasks（source 默认 agent；状态 not_started）。"""
    card = build_task_card(ctx.args)
    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    counts_toward_mastery = 1 if ctx.args.get("counts_toward_mastery", True) else 0
    source = ctx.args.get("source") or "agent"
    if source not in ("agent", "preset", "teacher", "diagnostic"):
        source = "agent"
    ctx.db.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, goal, data_type, scenario_id, cap_ids_json,
           source, status, steps_json, resources_json, rubric_json,
           counts_toward_mastery, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            ctx.user_row["id"],
            card["title"],
            card["goal"],
            card.get("data_type"),
            card.get("scenario_id"),
            json.dumps(card["cap_ids"], ensure_ascii=False),
            source,
            json.dumps(card["steps"], ensure_ascii=False),
            json.dumps(card["resources"], ensure_ascii=False, default=str),
            json.dumps(card["rubric"], ensure_ascii=False),
            counts_toward_mastery,
            ctx.user_row["id"],
            now,
            now,
        ),
    )
    ctx.db.commit()
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_created",
        {"task_id": task_id, "source": source},
    )
    return {"task_id": task_id, "title": card["title"], "card": card}


PREVIEW_SPEC = ToolSpec(
    name="task.preview",
    permission="read",
    auto_execute=True,
    description="组装学习任务卡预览（不落库）",
    handler=task_preview_handler,
)

CREATE_SPEC = ToolSpec(
    name="task.create",
    permission="write",
    auto_execute=False,
    description="确认后创建学习任务（learning_tasks）",
    preview=task_create_preview,
    apply=task_create_apply,
)
