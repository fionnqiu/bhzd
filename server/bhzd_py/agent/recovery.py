"""Startup recovery for durable Agent runs interrupted by a process restart.

The database is shared between HTTP requests and the process-level Agent worker.
After a process exits, a ``running`` row cannot resume because its worker no
longer exists.  Confirmation rows are different: an unexpired preview remains
actionable after restart and must not be failed merely because the app restarted.

This recovery rule assumes one application worker owns Agent execution for a
database.  Multi-instance deployments need an owner lease or heartbeat before a
new process can distinguish another instance's active run from a crashed one.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ..db import utc_now_iso
from . import events
from .confirmation_state import expire_pending_confirmation


INTERRUPTED_RUN_ERROR = "服务重启导致本次请求中断，请重新发起"


@dataclass(frozen=True)
class RecoverySummary:
    """Count the independent transitions made during one application startup."""

    failed_running: int = 0
    replayed_terminal: int = 0
    expired_confirmations: int = 0

    @property
    def total(self) -> int:
        """Return a concise count suitable for one startup log line."""

        return (
            self.failed_running
            + self.replayed_terminal
            + self.expired_confirmations
        )


def _failure_message_from_event(event: sqlite3.Row) -> str:
    """Reuse an already-persisted safe error without trusting malformed payloads."""

    try:
        payload = json.loads(event["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return INTERRUPTED_RUN_ERROR
    message = payload.get("error") if isinstance(payload, dict) else None
    return message if isinstance(message, str) and message else INTERRUPTED_RUN_ERROR


def _recover_running_run(db: sqlite3.Connection, run_id: str) -> str | None:
    """Close one crash-left ``running`` run while preserving an existing terminal SSE event.

    Normal execution persists a terminal event just before the terminal row.  A
    crash in that narrow gap has already told reconnecting clients the outcome;
    replaying the stored event's terminal state avoids emitting contradictory
    ``run.completed`` and ``run.failed`` events for one run.
    """

    try:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute(
            "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None or run["status"] != "running":
            db.rollback()
            return None

        terminal_event = db.execute(
            """
            SELECT event_type, payload_json
            FROM agent_events
            WHERE run_id = ? AND event_type IN (?, ?)
            ORDER BY seq DESC
            LIMIT 1
            """,
            (run_id, events.RUN_COMPLETED, events.RUN_FAILED),
        ).fetchone()
        now = utc_now_iso()
        if terminal_event is not None:
            if terminal_event["event_type"] == events.RUN_COMPLETED:
                db.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'completed', completed_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, run_id),
                )
            else:
                db.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'failed', error = ?, completed_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (_failure_message_from_event(terminal_event), now, run_id),
                )
            db.commit()
            return "replayed_terminal"

        # Keep the state row and its replayable terminal event in one immediate
        # transaction so SSE readers never see a failed run without run.failed.
        updated = db.execute(
            """
            UPDATE agent_runs
            SET status = 'failed', error = ?, completed_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (INTERRUPTED_RUN_ERROR, now, run_id),
        )
        if updated.rowcount != 1:
            db.rollback()
            return None
        events.emit(
            db,
            run_id,
            events.RUN_FAILED,
            {"error": INTERRUPTED_RUN_ERROR},
            commit=False,
        )
        db.commit()
        return "failed_running"
    except Exception:
        db.rollback()
        raise


def recover_interrupted_runs(db: sqlite3.Connection) -> RecoverySummary:
    """Recover only runs that cannot safely continue after startup.

    Due confirmation rows are routed through ``expire_pending_confirmation`` so
    the confirmation, tool, plan, message, and SSE state machine remains intact.
    Still-valid confirmations are intentionally left untouched for the user to
    confirm or cancel after reconnecting.
    """

    now = utc_now_iso()
    due_confirmations = db.execute(
        """
        SELECT confirmation.*
        FROM pending_confirmations AS confirmation
        JOIN agent_runs AS run ON run.id = confirmation.run_id
        WHERE confirmation.status = 'pending'
          AND confirmation.expires_at <= ?
          AND run.status = 'waiting_confirmation'
        ORDER BY confirmation.rowid ASC
        """,
        (now,),
    ).fetchall()
    expired_confirmations = sum(
        1
        for confirmation in due_confirmations
        if expire_pending_confirmation(db, confirmation)
    )

    running_ids = [
        row["id"]
        for row in db.execute(
            "SELECT id FROM agent_runs WHERE status = 'running' ORDER BY rowid ASC"
        ).fetchall()
    ]
    failed_running = 0
    replayed_terminal = 0
    for run_id in running_ids:
        outcome = _recover_running_run(db, run_id)
        if outcome == "failed_running":
            failed_running += 1
        elif outcome == "replayed_terminal":
            replayed_terminal += 1

    return RecoverySummary(
        failed_running=failed_running,
        replayed_terminal=replayed_terminal,
        expired_confirmations=expired_confirmations,
    )
