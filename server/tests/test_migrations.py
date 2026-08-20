"""迁移执行器测试：全新库顺序应用、重跑幂等、篡改拒绝。"""

from __future__ import annotations

import shutil

import pytest

from bhzd_py.db import MIGRATIONS_DIR, MigrationError, apply_migrations, connect

EXPECTED_MIGRATIONS = [
    "001_identity.sql", "002_org.sql", "003_agent.sql", "004_learning.sql",
    "005_rag.sql", "006_admin.sql", "007_recall_logs.sql",
    "008_learning_social.sql", "009_notifications.sql", "010_indexes.sql",
    "011_conversation_memory.sql", "012_private_layered_memory.sql",
    "013_teacher_agent_scope.sql", "014_admin_alert_ignores.sql",
    "015_message_attachments.sql", "016_remove_scenarios.sql",
    "017_provider_protocol_grader.sql", "018_task_learning_content.sql",
    "019_query_rewrite_setting.sql", "020_rag_sampling_settings.sql",
    "021_rag_eval_sets_and_retrieval.sql", "022_rag_reprocess_batches.sql",
    "023_remove_content_admin.sql", "024_task_content_generation_observability.sql",
    "025_task_grading_recovery.sql",
]

EXPECTED_TABLES = {
    "users", "user_credentials", "user_sessions", "admin_sessions", "login_attempts",
    "schools", "classes", "class_teachers", "class_enrollments",
    "conversations", "messages", "agent_runs", "agent_events", "tool_calls",
    "pending_confirmations", "learning_profiles", "mastery", "mastery_events",
    "learning_tasks", "task_attempts", "diagnostic_summaries", "analytics_events",
    "rag_documents", "rag_chunks", "rag_jobs", "rag_reprocess_batches", "source_ledgers", "review_records",
    "eval_cases", "eval_runs", "eval_sets", "rag_settings", "provider_configs", "audit_logs",
    "recall_logs",
    "favorites", "diagnostic_cache", "notifications",
    "conversation_memory_chunks", "private_memory_items", "private_memory_sources",
    "private_memory_fts", "admin_alert_ignores", "message_attachments",
    "task_knowledge_points", "task_exercises", "task_exercise_submissions",
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
        "layered private memory",
        "SELECT id FROM private_memory_items WHERE user_id = ? AND status = 'active' "
        "ORDER BY created_at DESC",
        ("user-1",),
        "idx_private_memory_scope_active",
    ),
    (
        "teacher agent conversations",
        "SELECT id FROM conversations WHERE user_id = ? AND agent_scope = 'teacher' "
        "AND class_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC",
        ("teacher-1", "class-1"),
        "idx_teacher_agent_conversations_owner_class",
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
        provider_columns = {
            row["name"]: row["type"]
            for row in conn.execute("PRAGMA table_info(provider_configs)")
        }
        assert "protocol" in provider_columns and "role" in provider_columns
        learning_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(learning_tasks)")
        }
        assert {
            "content_status",
            "content_generated_at",
            "content_generation_source",
            "content_failure_reason",
            "content_generation_message",
            "content_generation_retry_count",
            "content_last_attempt_at",
        } <= learning_columns
        submission_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(task_exercise_submissions)")
        }
        # 025 keeps each failed grading attempt and its bounded manual-review
        # handoff additive, so historical submissions remain readable.
        assert {
            "grade_failure_reason",
            "grade_retry_count",
            "grade_retry_limit",
            "retry_of_submission_id",
            "manual_review_required",
            "manual_reviewer_id",
            "manually_graded_at",
        } <= submission_columns
        defaults = {
            row["name"]: row["dflt_value"]
            for row in conn.execute("PRAGMA table_info(task_exercise_submissions)")
        }
        assert defaults["grade_retry_count"] == "0"
        assert defaults["grade_retry_limit"] == "2"
        assert defaults["manual_review_required"] == "0"
        recovery_indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idx_task_submissions_grade_recovery" in recovery_indexes
        rag_columns = {row["name"] for row in conn.execute("PRAGMA table_info(rag_settings)")}
        # Sampling controls are persisted independently of provider-specific
        # credentials so RAG tuning can be audited and replayed.
        assert {"query_rewrite_enabled", "temperature", "top_p"} <= rag_columns
        # The forward migration must expose the new role/protocol contract.
        conn.execute(
            "INSERT INTO provider_configs "
            "(id,name,protocol,base_url,model,api_key_encrypted,role,created_at,updated_at) "
            "VALUES ('migration-provider','test','responses','https://example.test/v1',"
            "'model','opaque','grader','now','now')"
        )
        conn.rollback()
        # 008 的 CSRF 稳定化列：两张会话表都应有可空的 csrf_token 列
        for table in ("user_sessions", "admin_sessions"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "csrf_token" in cols
        attachment_fk = conn.execute("PRAGMA foreign_key_list(message_attachments)").fetchall()
        # The history deletion route removes messages explicitly; this FK keeps
        # their retained previews from becoming durable orphaned private data.
        assert any(
            row["table"] == "messages" and row["on_delete"] == "CASCADE"
            for row in attachment_fk
        )
    finally:
        conn.close()


def test_teacher_agent_scope_rejects_unbound_teacher_rows(tmp_db_path):
    """013 must prevent a direct insert from bypassing class-scoped API checks."""

    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)
        now = "2026-08-09T00:00:00+00:00"
        conn.execute(
            """
            INSERT INTO users (id, email, name, role, status, created_at, updated_at)
            VALUES ('teacher-1', 'teacher-scope@test.local', '教师', 'teacher', 'active', ?, ?)
            """,
            (now, now),
        )
        with pytest.raises(Exception, match="invalid agent conversation scope"):
            conn.execute(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at, agent_scope)
                VALUES ('conversation-1', 'teacher-1', 'bad scope', ?, ?, 'teacher')
                """,
                (now, now),
            )
    finally:
        conn.close()


def test_provider_protocol_migration_preserves_legacy_row_data(tmp_path):
    """017 retires legacy protocols without losing provider metadata or secrets."""

    legacy_migrations = tmp_path / "provider_migrations"
    shutil.copytree(MIGRATIONS_DIR, legacy_migrations)
    (legacy_migrations / "017_provider_protocol_grader.sql").unlink()
    (legacy_migrations / "018_task_learning_content.sql").unlink()
    (legacy_migrations / "019_query_rewrite_setting.sql").unlink()
    # Keep this fixture anchored before the later RAG setting migrations; the
    # test is specifically exercising the pre-017 provider protocol boundary.
    (legacy_migrations / "020_rag_sampling_settings.sql").unlink()
    (legacy_migrations / "021_rag_eval_sets_and_retrieval.sql").unlink()
    (legacy_migrations / "022_rag_reprocess_batches.sql").unlink()
    (legacy_migrations / "023_remove_content_admin.sql").unlink()
    (legacy_migrations / "024_task_content_generation_observability.sql").unlink()
    (legacy_migrations / "025_task_grading_recovery.sql").unlink()
    database_path = str(tmp_path / "provider-migration.sqlite")
    conn = connect(database_path)
    try:
        assert apply_migrations(conn, migrations_dir=legacy_migrations)[-1] == "016_remove_scenarios.sql"
        original = {
            "id": "legacy-provider",
            "name": "legacy gateway",
            "protocol": "xunfei_spark",
            "base_url": "https://legacy.example.test",
            "model": "generalv3",
            "api_key_encrypted": "encrypted-key",
            "role": "fallback",
            "enabled": 1,
            "timeout_seconds": 17.5,
            "extra_json": '{"region":"cn"}',
            "last_test_json": '{"ok":true}',
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-02T00:00:00+00:00",
        }
        conn.execute(
            "INSERT INTO provider_configs "
            "(id, name, protocol, base_url, model, api_key_encrypted, role, enabled, "
            "timeout_seconds, extra_json, last_test_json, created_at, updated_at) "
            "VALUES (:id, :name, :protocol, :base_url, :model, :api_key_encrypted, :role, "
            ":enabled, :timeout_seconds, :extra_json, :last_test_json, :created_at, :updated_at)",
            original,
        )
        conn.commit()

        shutil.copy2(MIGRATIONS_DIR / "017_provider_protocol_grader.sql", legacy_migrations)
        assert apply_migrations(conn, migrations_dir=legacy_migrations) == [
            "017_provider_protocol_grader.sql"
        ]

        migrated = dict(
            conn.execute(
                "SELECT id, name, protocol, base_url, model, api_key_encrypted, role, enabled, "
                "timeout_seconds, extra_json, last_test_json, created_at, updated_at "
                "FROM provider_configs WHERE id = ?",
                (original["id"],),
            ).fetchone()
        )
        assert migrated == {**original, "protocol": "chat_completions", "enabled": 0}
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


def test_scenario_removal_migration_unifies_mastery_and_drops_business_columns(tmp_path):
    """016 removes only the business dimension and deterministically merges mastery rows."""

    legacy_migrations = tmp_path / "legacy_migrations"
    shutil.copytree(MIGRATIONS_DIR, legacy_migrations)
    (legacy_migrations / "016_remove_scenarios.sql").unlink()
    (legacy_migrations / "017_provider_protocol_grader.sql").unlink()
    (legacy_migrations / "018_task_learning_content.sql").unlink()
    (legacy_migrations / "019_query_rewrite_setting.sql").unlink()
    # The scenario migration test must stop at 015 so it can seed the legacy
    # scenario column layout before applying 016 in isolation.
    (legacy_migrations / "020_rag_sampling_settings.sql").unlink()
    (legacy_migrations / "021_rag_eval_sets_and_retrieval.sql").unlink()
    (legacy_migrations / "022_rag_reprocess_batches.sql").unlink()
    (legacy_migrations / "023_remove_content_admin.sql").unlink()
    (legacy_migrations / "024_task_content_generation_observability.sql").unlink()
    (legacy_migrations / "025_task_grading_recovery.sql").unlink()
    database_path = str(tmp_path / "scenario-removal.sqlite")
    conn = connect(database_path)
    try:
        assert apply_migrations(conn, migrations_dir=legacy_migrations)[-1] == "015_message_attachments.sql"
        now = "2026-08-15T00:00:00+00:00"
        conn.execute(
            "INSERT INTO users (id, email, name, role, status, created_at, updated_at) "
            "VALUES ('merge-user', 'merge@test.local', '合并测试', 'student', 'active', ?, ?)",
            (now, now),
        )
        conn.executemany(
            "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("merge-user", "cap-1", "SCN-LOW", 0.4, "old", "2026-08-14T00:00:00+00:00"),
                ("merge-user", "cap-1", "SCN-HIGH", 0.9, "high", "2026-08-13T00:00:00+00:00"),
                ("merge-user", "cap-1", "", 0.9, "latest", "2026-08-15T00:00:00+00:00"),
            ],
        )
        conn.commit()
        shutil.copy2(MIGRATIONS_DIR / "016_remove_scenarios.sql", legacy_migrations)
        applied = apply_migrations(conn, migrations_dir=legacy_migrations)
        assert applied == ["016_remove_scenarios.sql"]
        for table, column in (
            ("conversations", "scenario_id"),
            ("agent_runs", "scenario_id"),
            ("learning_tasks", "scenario_id"),
            ("diagnostic_summaries", "scenario_id"),
            ("rag_documents", "scenario_ids_json"),
            ("mastery_events", "scenario_id"),
        ):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert column not in columns
        mastery_columns = [row["name"] for row in conn.execute("PRAGMA table_info(mastery)")]
        assert mastery_columns == ["user_id", "cap_id", "score", "source", "updated_at"]
        merged = conn.execute(
            "SELECT score, source, updated_at FROM mastery WHERE user_id = ? AND cap_id = ?",
            ("merge-user", "cap-1"),
        ).fetchone()
        assert tuple(merged) == (0.9, "latest", "2026-08-15T00:00:00+00:00")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
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
