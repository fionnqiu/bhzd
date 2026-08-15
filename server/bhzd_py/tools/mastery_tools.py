"""mastery.update（write，确认门）（蓝图 §9 / PRD-06 §8.3）。

真正的更新公式（clamp 0..1、mastery_events 历史）在 B4 mastery.service
里实现；本工具只负责：预览（读出 old_score 与新分对照）与确认后调用。
"""

from __future__ import annotations

from typing import Any

from .registry import ToolContext, ToolSpec, emit_telemetry

_MASTERY_NOT_READY = "掌握度模块未就绪，请稍后再试"


def _mastery_service():
    try:
        from ..mastery import service  # B4，惰性导入
    except ImportError:
        return None
    return service


def _old_score(ctx: ToolContext, cap_id: str) -> float:
    row = ctx.db.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = ?",
        (ctx.user_row["id"], cap_id),
    ).fetchone()
    return float(row["score"]) if row else 0.0


def _preview_items(ctx: ToolContext) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for update in ctx.args.get("updates") or []:
        cap_id = update.get("cap_id")
        if not cap_id:
            continue
        items.append(
            {
                "cap_id": cap_id,
                "old_score": _old_score(ctx, cap_id),
                "new_score": update.get("new_score", update.get("score")),
                "source": ctx.args.get("source") or "exercise",
            }
        )
    return items


def mastery_preview(ctx: ToolContext) -> dict[str, Any]:
    items = _preview_items(ctx)
    if _mastery_service() is None:
        return {"error": _MASTERY_NOT_READY}
    if not items:
        return {"error": "没有需要更新的掌握度条目"}
    return {
        "action": "mastery.update",
        "summary": f"将更新 {len(items)} 项能力掌握度",
        "updates": items,
    }


def mastery_apply(ctx: ToolContext) -> dict[str, Any]:
    service = _mastery_service()
    if service is None:
        return {"error": _MASTERY_NOT_READY}
    items = _preview_items(ctx)
    if not items:
        return {"error": "没有需要更新的掌握度条目"}
    service.apply_updates(
        ctx.db,
        ctx.user_row["id"],
        items,
        source=ctx.args.get("source") or "exercise",
        ref_id=ctx.args.get("ref_id"),
    )
    for item in items:
        emit_telemetry(
            ctx.db,
            ctx.user_row["id"],
            "mastery_updated",
            {
                "cap_id": item["cap_id"],
                "old_score": item["old_score"],
                "new_score": item["new_score"],
                "source": item["source"],
            },
        )
    return {"updates": items, "applied": len(items)}


SPEC = ToolSpec(
    name="mastery.update",
    permission="write",
    auto_execute=False,
    description="确认后更新掌握度（clamp 0..1，写 mastery_events 历史）",
    preview=mastery_preview,
    apply=mastery_apply,
)
