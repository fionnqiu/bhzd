"""Retention policy tests: cleanup is bounded and never enabled by default."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from _agent_helpers import insert_run, insert_user
from bhzd_py.config import AppConfig
from bhzd_py.db import apply_migrations, connect
from bhzd_py.retention import RetentionRule, prune_expired_records


def test_retention_default_is_opt_in():
    """A normal configuration upgrade must not remove existing records by itself."""
    assert AppConfig().retention_enabled is False


def test_prune_expired_records_respects_each_table_batch_limit(tmp_db_path):
    """Repeated maintenance runs converge without holding SQLite's write lock too long."""
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        conn.executemany(
            "INSERT INTO login_attempts (email, ip, success, created_at) VALUES (?, ?, ?, ?)",
            [
                ("old-1@example.test", "127.0.0.1", 0, "2025-01-01T00:00:00+00:00"),
                ("old-2@example.test", "127.0.0.1", 0, "2025-01-02T00:00:00+00:00"),
                ("new@example.test", "127.0.0.1", 1, "2026-08-01T00:00:00+00:00"),
            ],
        )
        conn.commit()
        rule = (RetentionRule("login_attempts", 90),)
        now = datetime(2026, 8, 2, tzinfo=timezone.utc)

        first = prune_expired_records(conn, batch_size=1, now=now, rules=rule)
        assert first == {"login_attempts": 1}
        assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 2

        second = prune_expired_records(conn, batch_size=1, now=now, rules=rule)
        assert second == {"login_attempts": 1}
        rows = conn.execute("SELECT email FROM login_attempts").fetchall()
        assert [row["email"] for row in rows] == ["new@example.test"]
    finally:
        conn.close()


def test_prune_tool_calls_preserves_live_confirmation_and_removes_resolved_history(tmp_db_path):
    """Retention must satisfy confirmation FKs without deleting an actionable gate."""
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        user_id = insert_user(conn, "retention@test.local")
        resolved_run_id, _ = insert_run(conn, user_id, "resolved confirmation", status="completed")
        live_run_id, _ = insert_run(conn, user_id, "live confirmation", status="waiting_confirmation")
        resolved_tool_id, live_tool_id = uuid.uuid4().hex, uuid.uuid4().hex
        resolved_confirmation_id, live_confirmation_id = uuid.uuid4().hex, uuid.uuid4().hex
        old = "2025-01-01T00:00:00+00:00"

        conn.executemany(
            """
            INSERT INTO tool_calls
              (id, run_id, tool_name, permission, status, args_json, is_write, created_at)
            VALUES (?, ?, 'task.create', 'write', ?, '{}', 1, ?)
            """,
            [
                (resolved_tool_id, resolved_run_id, "completed", old),
                (live_tool_id, live_run_id, "awaiting_confirmation", old),
            ],
        )
        conn.executemany(
            """
            INSERT INTO pending_confirmations
              (id, run_id, user_id, tool_call_id, action_type, preview_json,
               status, expires_at, created_at, resolved_at)
            VALUES (?, ?, ?, ?, 'task.create', '{}', ?, ?, ?, ?)
            """,
            [
                (
                    resolved_confirmation_id,
                    resolved_run_id,
                    user_id,
                    resolved_tool_id,
                    "confirmed",
                    old,
                    old,
                    old,
                ),
                (
                    live_confirmation_id,
                    live_run_id,
                    user_id,
                    live_tool_id,
                    "pending",
                    "2027-01-01T00:00:00+00:00",
                    old,
                    None,
                ),
            ],
        )
        conn.commit()

        deleted = prune_expired_records(
            conn,
            batch_size=10,
            now=datetime(2026, 8, 2, tzinfo=timezone.utc),
            rules=(RetentionRule("tool_calls", 180),),
        )

        assert deleted == {"tool_calls": 1}
        assert conn.execute("SELECT 1 FROM tool_calls WHERE id = ?", (resolved_tool_id,)).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM pending_confirmations WHERE id = ?", (resolved_confirmation_id,)
        ).fetchone() is None
        assert conn.execute("SELECT 1 FROM tool_calls WHERE id = ?", (live_tool_id,)).fetchone()
        assert conn.execute(
            "SELECT 1 FROM pending_confirmations WHERE id = ?", (live_confirmation_id,)
        ).fetchone()
    finally:
        conn.close()
