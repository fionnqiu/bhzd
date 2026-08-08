"""迁移执行器测试：全新库顺序应用、重跑幂等、篡改拒绝。"""

from __future__ import annotations

import shutil

import pytest

from bhzd_py.db import MIGRATIONS_DIR, MigrationError, apply_migrations, connect

EXPECTED_MIGRATIONS = [
    "001_identity.sql", "002_org.sql", "003_agent.sql", "004_learning.sql",
    "005_rag.sql", "006_admin.sql", "007_recall_logs.sql",
    "008_learning_social.sql", "009_notifications.sql", "010_indexes.sql",
    "011_conversation_memory.sql",
]

EXPECTED_TABLES = {
    "users", "user_credentials", "user_sessions", "admin_sessions", "login_attempts",
    "schools", "classes", "class_teachers", "class_enrollments",
    "conversations", "messages", "agent_runs", "agent_events", "tool_calls",
    "pending_confirmations", "learning_profiles", "mastery", "mastery_events",
    "learning_tasks", "task_attempts", "diagnostic_summaries", "analytics_events",
    "rag_documents", "rag_chunks", "rag_jobs", "source_ledgers", "review_records",
    "eval_cases", "eval_runs", "rag_settings", "provider_configs", "audit_logs",
    "recall_logs",
    "favorites", "diagnostic_cache", "notifications",
    "conversation_memory_chunks",
}

# Each plan mirrors a production predicate and ordering requirement.  Checking the
# selected index, rather than merely its presence, catches accidental key-order drift.
INDEX_PLAN_CASES = (
    (
        "agent event replay",
        "SELECT seq FROM agent_events WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
        ("run-1", 0),
        "idx_agent_events_run_seq",
    ),
    (
        "conversation messages",
        "SELECT id, created_at FROM messages WHERE conversation_id = ? "
        "ORDER BY created_at ASC, rowid ASC",
        ("conversation-1",),
        "idx_messages_conversation_created",
    ),
    (
        "conversation list",
        "SELECT id FROM conversations WHERE user_id = ? AND deleted_at IS NULL "
        "ORDER BY updated_at DESC",
        ("user-1",),
        "idx_conversations_user_deleted_updated",
    ),
    (
        "conversation run history",
        "SELECT id FROM agent_runs WHERE conversation_id = ? ORDER BY rowid DESC",
        ("conversation-1",),
        "idx_agent_runs_conversation",
    ),
    (
        "run tool history",
        "SELECT id FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC, rowid ASC",
        ("run-1",),
        "idx_tool_calls_run_created",
    ),
    (
        "pending run confirmations",
        "SELECT id FROM pending_confirmations WHERE run_id = ? AND status = 'pending' "
        "ORDER BY created_at ASC",
        ("run-1",),
        "idx_pending_confirmations_run_status_created",
    ),
    (
        "student class tasks",
        "SELECT id FROM learning_tasks WHERE user_id = ? AND class_id = ?",
        ("user-1", "class-1"),
        "idx_learning_tasks_user_class",
    ),
    (
        "task attempts",
        "SELECT score FROM task_attempts WHERE task_id = ? "
        "ORDER BY attempt_number DESC LIMIT 1",
        ("task-1",),
        "idx_task_attempts_task_number",
    ),
    (
        "mastery history",
        "SELECT id FROM mastery_events WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 50",
        ("user-1",),
        "idx_mastery_events_user_created",
    ),
    (
        "document chunks",
        "SELECT id FROM rag_chunks WHERE document_id = ? ORDER BY chunk_index",
        ("document-1",),
        "idx_rag_chunks_document_index",
    ),
    (
        "document jobs",
        "SELECT id FROM rag_jobs WHERE document_id = ? "
        "ORDER BY created_at DESC, rowid DESC",
        ("document-1",),
        "idx_rag_jobs_document_created",
    ),
    (
        "private conversation memory",
        "SELECT role, content, embedding FROM conversation_memory_chunks "
        "WHERE user_id = ? AND conversation_id = ?",
        ("user-1", "conversation-1"),
        "idx_conversation_memory_scope_created",
    ),
    (
        "unfiltered audit log page",
        "SELECT id FROM audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (50, 0),
        "idx_audit_logs_created",
    ),
)


def test_fresh_database_applies_all_migrations(tmp_db_path):
    conn = connect(tmp_db_path)
    try:
        applied = apply_migrations(conn)
        assert applied == EXPECTED_MIGRATIONS
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert EXPECTED_TABLES <= tables
        # The ledger must retain a digest for every schema change, including indexes.
        rows = conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall()
        assert len(rows) == len(EXPECTED_MIGRATIONS)
        assert all(len(row["sha256"]) == 64 for row in rows)
        # 008 的 CSRF 稳定化列：两张会话表都应有可空的 csrf_token 列
        for table in ("user_sessions", "admin_sessions"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "csrf_token" in cols
    finally:
        conn.close()


def test_hot_path_indexes_match_production_query_plans(tmp_db_path):
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        index_names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
            )
        }
        expected_index_names = {case[3] for case in INDEX_PLAN_CASES}
        assert expected_index_names <= index_names

        for label, sql, params, index_name in INDEX_PLAN_CASES:
            details = [
                row["detail"]
                for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params)
            ]
            assert any(index_name in detail for detail in details), (
                f"{label} did not select {index_name}: {details}"
            )
    finally:
        conn.close()


def test_rerun_is_idempotent(tmp_db_path):
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        assert apply_migrations(conn) == []  # 第二次没有新迁移
    finally:
        conn.close()


def test_index_migration_recovers_if_ddl_committed_before_its_ledger_row(tmp_db_path):
    """Index DDL is safe to replay after an interruption in migration bookkeeping."""
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        # SQLite can commit schema DDL before the runner records its digest.
        # Simulate that narrow crash window without mutating any historical SQL.
        conn.execute("DELETE FROM schema_migrations WHERE name = '010_indexes.sql'")
        conn.commit()

        assert apply_migrations(conn) == ["010_indexes.sql"]
    finally:
        conn.close()


def test_tampered_migration_is_rejected(tmp_path):
    # 把迁移文件复制到临时目录再篡改，避免碰到仓库内的真实契约文件
    copied = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copied)
    conn = connect(str(tmp_path / "db.sqlite"))
    try:
        apply_migrations(conn, migrations_dir=copied)
        target = copied / "003_agent.sql"
        target.write_text(target.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8")
        with pytest.raises(MigrationError, match="003_agent.sql"):
            apply_migrations(conn, migrations_dir=copied)
    finally:
        conn.close()
