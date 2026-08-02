"""Confirmation-gate routes for durable Agent write operations.

The confirmation, tool call, plan and run form one state machine.  Routes keep
their durable transition and replayable SSE events in the same transaction so a
reconnecting cockpit never observes a terminal run without its terminal events.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..agent import events as agent_events
from ..agent.confirmation_state import (
    CANCELLED,
    CLAIMED,
    EXPIRED,
    EXPIRED_NOTICE,
    cancel_pending_confirmation,
    claim_confirmation_tool,
    expire_pending_confirmation,
    settle_waiting_plan_step,
)
from ..agent.orchestrator import continue_run, spawn
from ..config import get_config
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect
from ..errors import ApiError
from ..tools import registry
from ..tools.registry import ToolContext
from .runs import get_agent_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/confirmations", tags=["agent"])

_APPLY_FAILED_NOTICE = "确认的操作执行失败，请稍后重试"
_CANCELLED_NOTICE = "已取消，未做任何更改。"


class _EmptyBody(BaseModel):
    """Keep mutation payloads explicit while confirmation actions need no fields."""


def _load_confirmation(
    db: sqlite3.Connection, confirmation_id: str, user_id: str
) -> sqlite3.Row:
    """Load one owned confirmation without revealing another user's record."""

    row = db.execute(
        "SELECT * FROM pending_confirmations WHERE id = ?", (confirmation_id,)
    ).fetchone()
    if row is None or row["user_id"] != user_id:
        raise ApiError(404, "NOT_FOUND", "确认单不存在")
    return row


def _assert_pending(row: sqlite3.Row) -> None:
    """Reject repeated actions before attempting a cross-process state claim."""

    if row["status"] != "pending":
        raise ApiError(409, "CONFIRMATION_NOT_PENDING", "该确认单已被处理，请刷新页面")


def _raise_claim_conflict() -> None:
    """Return one safe response to a losing tab or a double click."""

    raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")


def _expire_or_raise(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Converge a due preview before returning its safe terminal response."""

    if expire_pending_confirmation(db, row):
        raise ApiError(410, "CONFIRMATION_EXPIRED", "确认已过期，请重新生成预览后再确认")
    latest = db.execute(
        "SELECT status FROM pending_confirmations WHERE id = ?", (row["id"],)
    ).fetchone()
    if latest is not None and latest["status"] == "expired":
        raise ApiError(410, "CONFIRMATION_EXPIRED", "确认已过期，请重新生成预览后再确认")
    _raise_claim_conflict()


def _assert_not_expired(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Handle an already-due row quickly; claims repeat this check atomically."""

    if row["expires_at"] <= utc_now_iso():
        _expire_or_raise(db, row)


def _persist_apply_failure(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    confirmation: sqlite3.Row,
    tool_call: sqlite3.Row,
) -> None:
    """Make a failed confirmed write terminal for tool, plan, run and SSE together.

    An apply implementation may have opened a SQLite transaction before raising.
    Its unfinished local work is rolled back before this terminal transaction so
    a failed apply cannot leave a waiting confirmation card or plan step behind.
    """

    db.rollback()
    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        tool_cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'failed', completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'running'
            """,
            (now, tool_call["id"], run["id"]),
        )
        plan_steps = settle_waiting_plan_step(db, run["id"], tool_call["id"], "failed")
        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations
            SET status = 'cancelled', resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, confirmation["id"]),
        )
        run_cursor = db.execute(
            """
            UPDATE agent_runs
            SET status = 'failed', error = ?, completed_at = ?
            WHERE id = ? AND status = 'waiting_confirmation'
            """,
            (_APPLY_FAILED_NOTICE, now, run["id"]),
        )
        if (
            tool_cursor.rowcount != 1
            or confirmation_cursor.rowcount != 1
            or run_cursor.rowcount != 1
        ):
            db.rollback()
            raise RuntimeError("confirmation apply failure lost its terminal state claim")

        # Deferred commits make this event sequence visible with the terminal
        # rows, eliminating the SSE stream.end window between state and events.
        agent_events.emit(
            db,
            run["id"],
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": tool_call["id"],
                "tool": confirmation["action_type"],
                "status": "failed",
                "duration_ms": 0,
                "is_write": 1,
                "result": {"error": _APPLY_FAILED_NOTICE},
            },
            commit=False,
        )
        if plan_steps is not None:
            agent_events.emit(
                db,
                run["id"],
                agent_events.PLAN_UPDATED,
                {"steps": plan_steps},
                commit=False,
            )
        agent_events.emit(
            db,
            run["id"],
            agent_events.RUN_FAILED,
            {"error": _APPLY_FAILED_NOTICE},
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.post("/{confirmation_id}/confirm")
async def confirm(
    confirmation_id: str,
    _body: _EmptyBody | None = None,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Apply one pre-deadline write exactly once, then resume the paused run."""

    row = _load_confirmation(db, confirmation_id, current.user["id"])
    _assert_pending(row)
    _assert_not_expired(db, row)

    tool_call = db.execute(
        "SELECT * FROM tool_calls WHERE id = ?", (row["tool_call_id"],)
    ).fetchone()
    run = db.execute(
        "SELECT * FROM agent_runs WHERE id = ?", (row["run_id"],)
    ).fetchone()
    if tool_call is None or run is None:
        raise ApiError(500, "INTERNAL_ERROR", "确认单数据异常，请重新发起操作")

    try:
        spec = registry.get(row["action_type"])
    except KeyError:
        raise ApiError(500, "INTERNAL_ERROR", "操作对应的工具未注册")
    if spec.apply is None:
        raise ApiError(500, "INTERNAL_ERROR", "该操作不支持确认执行")

    claim = claim_confirmation_tool(db, row)
    if claim == EXPIRED:
        # The route's quick check may have happened before the deadline.  The
        # transactional claim is authoritative because it binds time to state.
        _expire_or_raise(db, row)
    if claim != CLAIMED:
        _raise_claim_conflict()

    try:
        args = json.loads(tool_call["args_json"] or "{}")
    except json.JSONDecodeError:
        args = {}
    conversation = db.execute(
        "SELECT * FROM conversations WHERE id = ?", (run["conversation_id"],)
    ).fetchone()
    ctx = ToolContext(
        db=db,
        config=get_config(),
        user_row=current.user,
        run_row=run,
        conversation_row=conversation,
        args=args,
    )

    started = time.perf_counter()
    try:
        result = spec.apply(ctx)
    except Exception:
        logger.exception("确认执行 %s 失败", row["action_type"])
        try:
            _persist_apply_failure(
                db, run=run, confirmation=row, tool_call=tool_call
            )
        except Exception:
            # Preserve the original user-safe error while recording a durable
            # server-side trace if an unexpected database fault blocks cleanup.
            logger.exception("确认失败后的终态收敛失败")
        raise ApiError(500, "INTERNAL_ERROR", _APPLY_FAILED_NOTICE)

    duration_ms = int((time.perf_counter() - started) * 1000)
    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations
            SET status = 'confirmed', resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, row["id"]),
        )
        tool_cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'completed', result_json = ?, duration_ms = ?, completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'running'
            """,
            (
                json.dumps(result, ensure_ascii=False, default=str),
                duration_ms,
                now,
                tool_call["id"],
                run["id"],
            ),
        )
        if confirmation_cursor.rowcount != 1 or tool_cursor.rowcount != 1:
            db.rollback()
            _raise_claim_conflict()
        agent_events.emit(
            db,
            run["id"],
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": tool_call["id"],
                "tool": row["action_type"],
                "status": "completed",
                "duration_ms": duration_ms,
                "is_write": 1,
                "result": result,
            },
            commit=False,
        )
        db.commit()
    except ApiError:
        raise
    except Exception:
        db.rollback()
        logger.exception("确认成功后的状态持久化失败")
        raise ApiError(500, "INTERNAL_ERROR", _APPLY_FAILED_NOTICE)

    spawn(continue_run(run["id"], get_config().resolved_database_path))
    return {"status": "confirmed", "result": result}


@router.post("/{confirmation_id}/expire")
async def expire(
    confirmation_id: str,
    _body: _EmptyBody | None = None,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Resolve a due preview without executing its write operation."""

    row = _load_confirmation(db, confirmation_id, current.user["id"])
    if row["status"] == "expired":
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    _assert_pending(row)
    if row["expires_at"] > utc_now_iso():
        raise ApiError(409, "CONFIRMATION_NOT_EXPIRED", "确认单尚未过期")
    if expire_pending_confirmation(db, row):
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    latest = db.execute(
        "SELECT status FROM pending_confirmations WHERE id = ?", (row["id"],)
    ).fetchone()
    if latest is not None and latest["status"] == "expired":
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    _raise_claim_conflict()


@router.post("/{confirmation_id}/cancel")
async def cancel(
    confirmation_id: str,
    _body: _EmptyBody | None = None,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Cancel one valid preview without applying its write action."""

    row = _load_confirmation(db, confirmation_id, current.user["id"])
    _assert_pending(row)
    _assert_not_expired(db, row)
    outcome = cancel_pending_confirmation(db, row, _CANCELLED_NOTICE)
    if outcome == EXPIRED:
        _expire_or_raise(db, row)
    if outcome != CANCELLED:
        _raise_claim_conflict()
    return {"status": "cancelled"}
