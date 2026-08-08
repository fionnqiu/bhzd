"""Bounded, opt-in cleanup for append-only operational tables.

The product accumulates stream, audit, telemetry, and recall data indefinitely.
This module makes the retention policy explicit while deliberately keeping it
disabled by default: deployments must opt in with ``BHZD_RETENTION_ENABLED``
after checking their own legal and teaching-record requirements.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class RetentionRule:
    """A static table and its agreed maximum age in days.

    Table names remain code-owned rather than configuration values so retention
    cannot become an arbitrary SQL execution surface through an environment
    variable.  All currently targeted tables share the ``created_at`` column.
    """

    table: str
    days: int


# These defaults prioritize operational privacy and bounded storage while
# retaining audit trails and learning history longer than transient events.
DEFAULT_RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule("login_attempts", 90),
    RetentionRule("agent_events", 90),
    RetentionRule("analytics_events", 180),
    RetentionRule("recall_logs", 180),
    RetentionRule("tool_calls", 180),
    RetentionRule("audit_logs", 365),
    RetentionRule("mastery_events", 730),
)


def _prune_tool_call_batch(
    conn: sqlite3.Connection, *, cutoff: str, batch_size: int
) -> int:
    """Remove one old tool-call batch without orphaning confirmation records.

    ``pending_confirmations.tool_call_id`` is a non-cascading foreign key.
    Resolved confirmations therefore follow their expired tool-call audit
    record, while an unresolved confirmation keeps its tool call regardless of
    age so an operator never loses an actionable preview.
    """
    rows = conn.execute(
        """
        SELECT tc.id
        FROM tool_calls AS tc
        WHERE tc.created_at < ?
          AND NOT EXISTS (
            SELECT 1
            FROM pending_confirmations AS pc
            WHERE pc.tool_call_id = tc.id AND pc.status = 'pending'
          )
        ORDER BY tc.created_at, tc.rowid
        LIMIT ?
        """,
        (cutoff, batch_size),
    ).fetchall()
    tool_call_ids = [row["id"] for row in rows]
    if not tool_call_ids:
        return 0

    placeholders = ", ".join("?" for _ in tool_call_ids)
    # Delete resolved child rows first because the historical schema correctly
    # forbids dangling confirmations and intentionally has no ON DELETE CASCADE.
    conn.execute(
        f"DELETE FROM pending_confirmations WHERE tool_call_id IN ({placeholders})",
        tool_call_ids,
    )
    deleted = conn.execute(
        f"DELETE FROM tool_calls WHERE id IN ({placeholders})", tool_call_ids
    )
    return max(deleted.rowcount, 0)


def prune_expired_records(
    conn: sqlite3.Connection,
    *,
    batch_size: int,
    now: datetime | None = None,
    rules: tuple[RetentionRule, ...] = DEFAULT_RETENTION_RULES,
) -> dict[str, int]:
    """Delete at most one small, old-record batch per configured table.

    One batch prevents a startup cleanup from monopolizing SQLite's write lock.
    Repeated enabled startups progressively converge toward the policy, while a
    separate maintenance window can still handle a deliberate ``VACUUM``.
    """
    cutoff_now = now or datetime.now(timezone.utc)
    deleted: dict[str, int] = {}
    for rule in rules:
        cutoff = (cutoff_now - timedelta(days=rule.days)).isoformat()
        if rule.table == "tool_calls":
            # Tool calls own confirmation records, so their bounded cleanup
            # requires a small ordered child/parent transaction instead of the
            # generic single-table delete used by independent event tables.
            deleted[rule.table] = _prune_tool_call_batch(
                conn, cutoff=cutoff, batch_size=batch_size
            )
            continue
        cursor = conn.execute(
            f"""
            DELETE FROM {rule.table}
            WHERE rowid IN (
              SELECT rowid FROM {rule.table}
              WHERE created_at < ?
              ORDER BY created_at
              LIMIT ?
            )
            """,
            (cutoff, batch_size),
        )
        deleted[rule.table] = max(cursor.rowcount, 0)
    conn.commit()
    return deleted
