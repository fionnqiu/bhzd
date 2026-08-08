"""Durable confirmation lifecycle transitions shared by Agent routes.

The confirmation row, its tool call, and its run form one state machine.  Keeping
the expiration and claim transitions here prevents a route from resolving only
one of those records and leaving a run permanently waiting for user input.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from ..db import utc_now_iso
from . import events


EXPIRED_NOTICE = "预览已过期，未做任何修改，请重新发起操作。"


CLAIMED = "claimed"
EXPIRED = "expired"
CONFLICT = "conflict"
CANCELLED = "cancelled"


def _transition_outcome(
    db: sqlite3.Connection, confirmation: sqlite3.Row, now: str
) -> str:
    """Classify a lost conditional update without treating an active write as expired.

    A tool already marked ``running`` won its pre-deadline claim and must be
    allowed to finish.  Only a still-awaiting tool paired with a due pending
    confirmation is safe to converge through the expiry path.
    """

    latest = db.execute(
        "SELECT status, expires_at FROM pending_confirmations WHERE id = ?",
        (confirmation["id"],),
    ).fetchone()
    tool = db.execute(
        "SELECT status FROM tool_calls WHERE id = ? AND run_id = ?",
        (confirmation["tool_call_id"], confirmation["run_id"]),
    ).fetchone()
    if (
        latest is not None
        and latest["status"] == "pending"
        and latest["expires_at"] <= now
        and tool is not None
        and tool["status"] == "awaiting_confirmation"
    ):
        return EXPIRED
    return CONFLICT


def claim_confirmation_tool(db: sqlite3.Connection, confirmation: sqlite3.Row) -> str:
    """Claim a write only while its pending confirmation is still unexpired.

    The conditional update is deliberately inside ``BEGIN IMMEDIATE``.  It
    binds the deadline check to the durable ``tool_calls.running`` claim, so a
    request that crosses the deadline after route-level validation can never
    enter ``apply``.
    """

    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'running'
            WHERE id = ? AND run_id = ? AND status = 'awaiting_confirmation'
              AND EXISTS (
                SELECT 1
                FROM pending_confirmations
                WHERE id = ? AND run_id = ? AND tool_call_id = ?
                  AND status = 'pending' AND expires_at > ?
              )
              AND EXISTS (
                SELECT 1
                FROM agent_runs
                WHERE id = ? AND status = 'waiting_confirmation'
              )
            """,
            (
                confirmation["tool_call_id"],
                confirmation["run_id"],
                confirmation["id"],
                confirmation["run_id"],
                confirmation["tool_call_id"],
                now,
                confirmation["run_id"],
            ),
        )
        if cursor.rowcount == 1:
            db.commit()
            return CLAIMED
        outcome = _transition_outcome(db, confirmation, now)
        db.rollback()
        return outcome
    except Exception:
        db.rollback()
        raise


def settle_waiting_plan_step(
    db: sqlite3.Connection, run_id: str, tool_call_id: str, status: str
) -> list[dict[str, Any]] | None:
    """Persist the exact pending write step's terminal state for reconnecting UI.

    ``tool_calls`` is authoritative for execution, but the plan is the user
    facing progress record.  Updating both within the same transition avoids a
    reconnect rendering a stale waiting step after cancellation or apply failure.
    """

    if status not in {"cancelled", "failed"}:
        raise ValueError(f"unsupported confirmation plan status: {status}")

    run = db.execute(
        "SELECT plan_json FROM agent_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run is None or not run["plan_json"]:
        return None
    try:
        plan = json.loads(run["plan_json"])
    except json.JSONDecodeError:
        return None
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return None

    changed = False
    for step in steps:
        if (
            isinstance(step, dict)
            and step.get("tool_call_id") == tool_call_id
            and step.get("status") == "waiting"
        ):
            step["status"] = status
            changed = True
            break
    if not changed:
        return None
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(plan, ensure_ascii=False, default=str), run_id),
    )
    return [
        {
            "id": step.get("id"),
            "title": step.get("title"),
            "status": step.get("status"),
        }
        for step in steps
        if isinstance(step, dict)
    ]


def cancel_pending_confirmation(
    db: sqlite3.Connection, confirmation: sqlite3.Row, notice: str
) -> str:
    """Cancel one still-valid confirmation and publish its terminal sequence atomically.

    Cancellation does not have an ``apply`` phase, so every dependent record and
    its replayable SSE events can share one immediate transaction.  The same
    deadline predicate as confirmation prevents a stale cancel request from
    winning after the preview has expired.
    """

    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        tool_cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'cancelled', completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'awaiting_confirmation'
              AND EXISTS (
                SELECT 1
                FROM pending_confirmations
                WHERE id = ? AND run_id = ? AND tool_call_id = ?
                  AND status = 'pending' AND expires_at > ?
              )
              AND EXISTS (
                SELECT 1
                FROM agent_runs
                WHERE id = ? AND status = 'waiting_confirmation'
              )
            """,
            (
                now,
                confirmation["tool_call_id"],
                confirmation["run_id"],
                confirmation["id"],
                confirmation["run_id"],
                confirmation["tool_call_id"],
                now,
                confirmation["run_id"],
            ),
        )
        if tool_cursor.rowcount != 1:
            outcome = _transition_outcome(db, confirmation, now)
            db.rollback()
            return outcome

        plan_steps = settle_waiting_plan_step(
            db, confirmation["run_id"], confirmation["tool_call_id"], "cancelled"
        )
        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations
            SET status = 'cancelled', resolved_at = ?
            WHERE id = ? AND status = 'pending' AND expires_at > ?
            """,
            (now, confirmation["id"], now),
        )
        run_cursor = db.execute(
            """
            UPDATE agent_runs
            SET status = 'completed', completed_at = ?
            WHERE id = ? AND status = 'waiting_confirmation'
            """,
            (now, confirmation["run_id"]),
        )
        if confirmation_cursor.rowcount != 1 or run_cursor.rowcount != 1:
            db.rollback()
            return CONFLICT

        run = db.execute(
            "SELECT conversation_id FROM agent_runs WHERE id = ?",
            (confirmation["run_id"],),
        ).fetchone()
        if run is not None:
            db.execute(
                """
                INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (uuid.uuid4().hex, run["conversation_id"], confirmation["run_id"], notice, now),
            )

        # These INSERTs deliberately precede the commit.  Readers see either the
        # old waiting state or the complete terminal event sequence, never an
        # eventless terminal run that would make SSE send stream.end too early.
        events.emit(
            db,
            confirmation["run_id"],
            events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": confirmation["tool_call_id"],
                "tool": confirmation["action_type"],
                "status": "cancelled",
                "duration_ms": 0,
                "is_write": 1,
                "execution_kind": events.execution_kind(confirmation["action_type"]),
                "output_summary": "已取消，未执行写入",
                "result": {"cancelled": True},
            },
            commit=False,
        )
        if plan_steps is not None:
            events.emit(
                db,
                confirmation["run_id"],
                events.PLAN_UPDATED,
                {"steps": plan_steps},
                commit=False,
            )
        events.emit(
            db,
            confirmation["run_id"],
            events.RUN_COMPLETED,
            {"summary": notice},
            commit=False,
        )
        db.commit()
        return CANCELLED
    except Exception:
        db.rollback()
        raise


def expire_pending_confirmation(
    db: sqlite3.Connection, confirmation: sqlite3.Row
) -> bool:
    """Expire one due confirmation and close every dependent state exactly once.

    SQLite's immediate transaction serializes expiry against confirm/cancel claims.
    This matters at the deadline: a tool already claimed before expiry may finish,
    while a still-waiting tool is cancelled without ever executing its write.
    """

    plan_steps: list[dict[str, Any]] | None = None
    run_completed = False
    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        tool_cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'cancelled', completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'awaiting_confirmation'
            """,
            (now, confirmation["tool_call_id"], confirmation["run_id"]),
        )
        if tool_cursor.rowcount != 1:
            db.rollback()
            return False

        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations
            SET status = 'expired', resolved_at = ?
            WHERE id = ? AND status = 'pending' AND expires_at <= ?
            """,
            (now, confirmation["id"], now),
        )
        if confirmation_cursor.rowcount != 1:
            db.rollback()
            return False

        plan_steps = settle_waiting_plan_step(
            db, confirmation["run_id"], confirmation["tool_call_id"], "cancelled"
        )
        run_cursor = db.execute(
            """
            UPDATE agent_runs
            SET status = 'completed', completed_at = ?
            WHERE id = ? AND status = 'waiting_confirmation'
            """,
            (now, confirmation["run_id"]),
        )
        run_completed = run_cursor.rowcount == 1
        if run_completed:
            run = db.execute(
                "SELECT conversation_id FROM agent_runs WHERE id = ?",
                (confirmation["run_id"],),
            ).fetchone()
            if run is not None:
                db.execute(
                    """
                    INSERT INTO messages
                      (id, conversation_id, run_id, role, content, created_at)
                    VALUES (?, ?, ?, 'assistant', ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        run["conversation_id"],
                        confirmation["run_id"],
                        EXPIRED_NOTICE,
                        now,
                    ),
                )
        # Persist terminal events before committing terminal state.  A separate
        # SSE connection therefore observes the old waiting run or this entire
        # replayable sequence, never an eventless completed run.
        events.emit(
            db,
            confirmation["run_id"],
            events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": confirmation["tool_call_id"],
                "tool": confirmation["action_type"],
                "status": "cancelled",
                "duration_ms": 0,
                "is_write": 1,
                "execution_kind": events.execution_kind(confirmation["action_type"]),
                "output_summary": "预览已过期，未执行写入",
                "result": {"cancelled": True, "reason": "confirmation_expired"},
            },
            commit=False,
        )
        if plan_steps is not None:
            events.emit(
                db,
                confirmation["run_id"],
                events.PLAN_UPDATED,
                {"steps": plan_steps},
                commit=False,
            )
        if run_completed:
            events.emit(
                db,
                confirmation["run_id"],
                events.RUN_COMPLETED,
                {"summary": EXPIRED_NOTICE},
                commit=False,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return True
