"""Agent-facing wrappers for the bounded learning capability gateway."""

from __future__ import annotations

from typing import Any

from ..agent import learning_capabilities
from .registry import ToolContext, ToolSpec


def _run(ctx: ToolContext, capability: Any) -> dict[str, Any]:
    if not getattr(ctx.config, "agent_learning_auto_enabled", True):
        return {"error": "学习自动操作能力已关闭"}
    try:
        return capability(ctx.db, ctx.user_row, ctx.args, run_id=ctx.run_row["id"] if ctx.run_row else None)
    except learning_capabilities.LearningCapabilityError as exc:
        return {"error": str(exc)}
    except Exception:
        return {"error": "学习操作未完成，请稍后重试"}


def _create(ctx: ToolContext) -> dict[str, Any]:
    cards = ctx.args.get("cards")
    if isinstance(cards, list) and cards:
        created: list[dict[str, Any]] = []
        base_key = str(ctx.args.get("idempotency_key") or "")
        # Multi-stage cards must be all-or-nothing: a provider or validation
        # failure cannot leave only the first stage durable.
        ctx.db.execute("BEGIN IMMEDIATE")
        try:
            for index, card in enumerate(cards):
                if not isinstance(card, dict):
                    continue
                args = {**card, "idempotency_key": f"{base_key}:{index}"}
                result = learning_capabilities.auto_create_task(
                    ctx.db,
                    ctx.user_row,
                    args,
                    run_id=ctx.run_row["id"] if ctx.run_row else None,
                    commit=False,
                )
                created.append(result)
            ctx.db.commit()
        except Exception:
            ctx.db.rollback()
            raise
        return {"task_ids": [item["task_id"] for item in created if item.get("task_id")], "tasks": created, "count": len(created)}
    return _run(ctx, learning_capabilities.auto_create_task)


def _progress(ctx: ToolContext) -> dict[str, Any]:
    return _run(ctx, learning_capabilities.record_progress)


def _mastery(ctx: ToolContext) -> dict[str, Any]:
    return _run(ctx, learning_capabilities.sync_mastery)


def _review(ctx: ToolContext) -> dict[str, Any]:
    return _run(ctx, learning_capabilities.review_exercise)


# These actions are bounded to the learner's own rows; auto_execute marks that
# no generic confirmation payload is needed when the orchestrator supports
# trusted low-risk writes.  The gateway remains the authorization boundary.
TASK_AUTO_CREATE_SPEC = ToolSpec("learning.task.auto_create", "write", True, "在当前学生范围内自动创建学习任务", handler=_create)
PROGRESS_RECORD_SPEC = ToolSpec("learning.progress.record", "write", True, "记录当前学生任务进度", handler=_progress)
MASTERY_SYNC_SPEC = ToolSpec("learning.mastery.sync", "write", True, "根据已成功评分练习同步能力掌握度", handler=_mastery)
EXERCISE_REVIEW_SPEC = ToolSpec("learning.exercise.review", "write", True, "使用 grader 对完成练习评分并追加点评", handler=_review)

# Compatibility aliases for callers that use the concise capability names.
PROGRESS_SPEC = PROGRESS_RECORD_SPEC
MASTERY_SPEC = MASTERY_SYNC_SPEC
REVIEW_SPEC = EXERCISE_REVIEW_SPEC
