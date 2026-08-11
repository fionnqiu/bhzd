"""Focused coverage for private cross-session layered memory."""

from __future__ import annotations

import sqlite3
import time
import uuid

from bhzd_py.agent import conversation_memory, orchestrator
from bhzd_py.config import reset_config_cache
from bhzd_py.db import utc_now_iso

from _agent_helpers import insert_run, insert_user, make_db


def _insert_message(
    db: sqlite3.Connection,
    conversation_id: str,
    run_id: str,
    role: str,
    content: str,
) -> str:
    message_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, conversation_id, run_id, role, content, utc_now_iso()),
    )
    db.commit()
    return message_id


def _capture_turn(
    db: sqlite3.Connection,
    user_id: str,
    conversation_id: str,
    run_id: str,
    user_text: str,
    assistant_text: str,
) -> tuple[str, str]:
    user_message = _insert_message(db, conversation_id, run_id, "user", user_text)
    assistant_message = _insert_message(
        db, conversation_id, run_id, "assistant", assistant_text
    )
    conversation_memory.capture_completed_response(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        run_id=run_id,
    )
    return user_message, assistant_message


def test_layered_recall_crosses_conversations_but_not_users(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        first_user = insert_user(db, "layered-first@test.local")
        second_user = insert_user(db, "layered-second@test.local")
        first_run, first_conversation = insert_run(db, first_user, "first task")
        _capture_turn(
            db,
            first_user,
            first_conversation,
            first_run,
            "I am tracking the nebula project for biology.",
            "The learner selected a nebula study plan.",
        )
        second_run, second_conversation = insert_run(db, first_user, "follow up")
        own_context = conversation_memory.retrieve_context(
            db,
            user_id=first_user,
            conversation_id=second_conversation,
            query="What do I know about the nebula project?",
        )
        assert any("nebula" in item["content"].lower() for item in own_context)

        other_run, other_conversation = insert_run(db, second_user, "other task")
        _capture_turn(
            db,
            second_user,
            other_conversation,
            other_run,
            "I am tracking the nebula project for another learner.",
            "The other learner selected a separate plan.",
        )
        isolated_context = conversation_memory.retrieve_context(
            db,
            user_id=first_user,
            conversation_id=second_conversation,
            query="another learner nebula project",
        )
        assert all("another learner" not in item["content"] for item in isolated_context)
        assert second_run != other_run
    finally:
        db.close()


def test_preferences_dedupe_and_supersede_with_provenance(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-preference@test.local")
        first_run, first_conversation = insert_run(db, user_id, "style one")
        _, first_assistant = _capture_turn(
            db,
            user_id,
            first_conversation,
            first_run,
            "I prefer concise answers.",
            "I will keep the answer concise.",
        )
        # Replaying the same completed run must not create a duplicate active item.
        conversation_memory.capture_completed_response(
            db,
            user_id=user_id,
            conversation_id=first_conversation,
            run_id=first_run,
        )
        second_run, second_conversation = insert_run(db, user_id, "style two")
        _capture_turn(
            db,
            user_id,
            second_conversation,
            second_run,
            "I prefer detailed step by step answers.",
            "I will provide detailed steps.",
        )
        # A delayed replay of the earlier run must not overwrite the newer
        # explicit preference simply because its worker happens to finish last.
        conversation_memory.capture_completed_response(
            db,
            user_id=user_id,
            conversation_id=first_conversation,
            run_id=first_run,
        )

        active_preferences = db.execute(
            """
            SELECT layer, content FROM private_memory_items
            WHERE user_id = ? AND kind IN ('preference', 'profile') AND status = 'active'
            ORDER BY layer
            """,
            (user_id,),
        ).fetchall()
        assert len(active_preferences) == 2
        assert all("detailed" in row["content"].lower() for row in active_preferences)
        assert db.execute(
            """
            SELECT COUNT(*) AS count FROM private_memory_items
            WHERE user_id = ? AND layer = 'l1' AND kind = 'preference'
            """,
            (user_id,),
        ).fetchone()["count"] == 2
        assert db.execute(
            """
            SELECT COUNT(*) AS count FROM private_memory_sources
            WHERE message_id = ?
            """,
            (first_assistant,),
        ).fetchone()["count"] >= 1
    finally:
        db.close()


def test_source_deletion_erases_derived_items_and_fts_rows(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-delete@test.local")
        run_id, conversation_id = insert_run(db, user_id, "delete source")
        _, assistant_message = _capture_turn(
            db,
            user_id,
            conversation_id,
            run_id,
            "The source must disappear with the task.",
            "The task summary is derived from the source.",
        )
        assert db.execute(
            "SELECT COUNT(*) AS count FROM private_memory_sources WHERE message_id = ?",
            (assistant_message,),
        ).fetchone()["count"] >= 1

        db.execute("DELETE FROM messages WHERE id = ?", (assistant_message,))
        db.commit()

        assert db.execute(
            "SELECT COUNT(*) AS count FROM private_memory_sources WHERE message_id = ?",
            (assistant_message,),
        ).fetchone()["count"] == 0
        assert db.execute(
            """
            SELECT COUNT(*) AS count
            FROM private_memory_items AS item
            JOIN private_memory_sources AS source ON source.memory_id = item.id
            WHERE source.message_id = ?
            """,
            (assistant_message,),
        ).fetchone()["count"] == 0
        assert db.execute(
            "SELECT COUNT(*) AS count FROM private_memory_fts WHERE content MATCH 'summary'"
        ).fetchone()["count"] == 0
    finally:
        db.close()


def test_keyword_recall_survives_embedding_failure(tmp_db_path, monkeypatch):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-keyword@test.local")
        run_id, conversation_id = insert_run(db, user_id, "keyword source")
        _capture_turn(
            db,
            user_id,
            conversation_id,
            run_id,
            "The aurora marker is useful for this lesson.",
            "The aurora marker was saved as a private note.",
        )
        query_run, query_conversation = insert_run(db, user_id, "keyword follow up")

        def fail_embedding(*_args, **_kwargs):
            raise RuntimeError("embedding provider unavailable")

        monkeypatch.setattr(conversation_memory, "embed_chunks", fail_embedding)
        context = conversation_memory.retrieve_context(
            db,
            user_id=user_id,
            conversation_id=query_conversation,
            query="aurora marker",
        )
        assert any("aurora marker" in item["content"].lower() for item in context)
        assert query_run
    finally:
        db.close()


def test_capture_failure_is_best_effort_and_source_remains(tmp_db_path, monkeypatch):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-failure@test.local")
        run_id, conversation_id = insert_run(db, user_id, "failure source")
        user_message, assistant_message = _capture_turn(
            db,
            user_id,
            conversation_id,
            run_id,
            "This source will remain durable.",
            "The derivative index is allowed to fail.",
        )
        db.execute("DELETE FROM private_memory_items")
        db.commit()

        def fail_embedding(*_args, **_kwargs):
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(conversation_memory, "embed_chunks", fail_embedding)
        assert (
            conversation_memory.capture_completed_response(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run_id,
            )
            == 0
        )
        assert db.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE id IN (?, ?)",
            (user_message, assistant_message),
        ).fetchone()["count"] == 2
        assert db.execute(
            "SELECT COUNT(*) AS count FROM private_memory_items"
        ).fetchone()["count"] == 0
    finally:
        db.close()


def test_sensitive_or_internal_text_never_enters_durable_layers(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-sensitive@test.local")
        run_id, conversation_id = insert_run(db, user_id, "sensitive source")
        _capture_turn(
            db,
            user_id,
            conversation_id,
            run_id,
            "password: never retain this value",
            "<think>internal reasoning</think> tool_call arguments are private",
        )
        assert db.execute(
            "SELECT COUNT(*) AS count FROM private_memory_items"
        ).fetchone()["count"] == 0
        structured_run, structured_conversation = insert_run(db, user_id, "tool payload")
        _capture_turn(
            db,
            user_id,
            structured_conversation,
            structured_run,
            "This harmless task has a private tool response.",
            '{"tool_name":"private_lookup","args":{"query":"retain nothing"}}',
        )
        assert db.execute(
            """
            SELECT COUNT(*) AS count FROM private_memory_items
            WHERE content LIKE '%private_lookup%' OR content LIKE '%retain nothing%'
            """
        ).fetchone()["count"] == 0
    finally:
        db.close()


def test_l0_memory_sanitizes_reasoning_and_rejects_tool_payloads(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "l0-sensitive@test.local")
        run_id, conversation_id = insert_run(db, user_id, "l0 sensitive")
        visible_message = _insert_message(
            db,
            conversation_id,
            run_id,
            "assistant",
            "Visible study marker <analysis>private <think>plan</think> notes</analysis> final.",
        )
        conversation_memory.index_message(
            db,
            message_id=visible_message,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            role="assistant",
            content="Visible study marker <analysis>private <think>plan</think> notes</analysis> final.",
            created_at=utc_now_iso(),
        )
        stored = db.execute(
            "SELECT content FROM conversation_memory_chunks WHERE message_id = ?",
            (visible_message,),
        ).fetchone()
        assert stored["content"] == "Visible study marker final."
        assert conversation_memory.format_context(
            [
                {"role": "assistant", "content": "Visible <think>private</think> final."},
                {"role": "memory", "content": "Authorization: Bearer do-not-return"},
            ]
        ) == "assistant: Visible final."

        tool_message = _insert_message(
            db,
            conversation_id,
            run_id,
            "assistant",
            '{"tool_name":"private_lookup","arguments":{"query":"secret"}}',
        )
        conversation_memory.index_message(
            db,
            message_id=tool_message,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            role="assistant",
            content='{"tool_name":"private_lookup","arguments":{"query":"secret"}}',
            created_at=utc_now_iso(),
        )
        assert db.execute(
            "SELECT 1 FROM conversation_memory_chunks WHERE message_id = ?",
            (tool_message,),
        ).fetchone() is None

        for unsafe_content in (
            "Authorization: Bearer raw-access-token",
            "api_key=sk-live-abcdefghijklmnopqrstuv",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsZWFybmVyIn0.signaturepayload",
        ):
            unsafe_message = _insert_message(
                db,
                conversation_id,
                run_id,
                "assistant",
                unsafe_content,
            )
            conversation_memory.index_message(
                db,
                message_id=unsafe_message,
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run_id,
                role="assistant",
                content=unsafe_content,
                created_at=utc_now_iso(),
            )
            assert db.execute(
                "SELECT 1 FROM conversation_memory_chunks WHERE message_id = ?",
                (unsafe_message,),
            ).fetchone() is None
    finally:
        db.close()


def test_memory_keeps_token_lesson_vocabulary_but_rejects_assigned_token_values():
    """Avoid sacrificing ordinary NLP lessons while retaining secret value protection."""

    lesson = "Token classification is a core NLP annotation skill."
    assert conversation_memory._safe_memory_text(lesson) == lesson
    assert conversation_memory._safe_memory_text("token: do-not-store-this-value") is None


def test_retrieval_filters_legacy_dirty_l0_and_layered_rows(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "legacy-sensitive@test.local")
        run_id, conversation_id = insert_run(db, user_id, "legacy l0")
        message_id = _insert_message(
            db,
            conversation_id,
            run_id,
            "assistant",
            "legacy marker",
        )
        conversation_memory.index_message(
            db,
            message_id=message_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            role="assistant",
            content="legacy marker",
            created_at=utc_now_iso(),
        )
        # Simulate a row written before the privacy gate.  Its vector still
        # matches the query, so the assertion proves filtering occurs after
        # candidate scoring rather than only relying on FTS metadata.
        db.execute(
            "UPDATE conversation_memory_chunks SET content = ? WHERE message_id = ?",
            ("legacy marker password=do-not-return", message_id),
        )
        db.commit()
        assert not any(
            "do-not-return" in item["content"]
            for item in conversation_memory.retrieve_context(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                query="legacy marker",
            )
        )

        layered_run, layered_conversation = insert_run(db, user_id, "legacy layered")
        _capture_turn(
            db,
            user_id,
            layered_conversation,
            layered_run,
            "The layered marker remains useful.",
            "The layered marker has a durable outcome.",
        )
        layered_id = db.execute(
            "SELECT id FROM private_memory_items WHERE user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()["id"]
        db.execute(
            "UPDATE private_memory_items SET content = ? WHERE id = ?",
            ('{"tool_name":"legacy_lookup","args":{"token":"do-not-return"}}', layered_id),
        )
        db.commit()
        assert not any(
            "do-not-return" in item["content"]
            for item in conversation_memory.retrieve_context(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                query="legacy lookup durable outcome",
            )
        )
    finally:
        db.close()


def test_layered_recall_is_hard_bounded(tmp_db_path, monkeypatch):
    monkeypatch.setenv("BHZD_PRIVATE_MEMORY_TOP_K", "2")
    monkeypatch.setenv("BHZD_PRIVATE_MEMORY_CONTEXT_CHAR_LIMIT", "256")
    reset_config_cache()
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-bound@test.local")
        for index in range(6):
            run_id, conversation_id = insert_run(db, user_id, f"bound source {index}")
            _capture_turn(
                db,
                user_id,
                conversation_id,
                run_id,
                f"The comet marker {index} is retained for this bounded test.",
                f"The comet marker {index} has a separate outcome.",
            )
        _, query_conversation = insert_run(db, user_id, "bounded query")
        context = conversation_memory.retrieve_context(
            db,
            user_id=user_id,
            conversation_id=query_conversation,
            query="comet marker",
        )
        layered = [item for item in context if item["role"] == "memory"]
        assert len(layered) <= 2
        assert sum(len(item["content"]) for item in layered) <= 256
    finally:
        db.close()
        reset_config_cache()


def test_schedule_layered_capture_starts_a_daemon_worker(monkeypatch):
    started: list[dict] = []

    class FakeThread:
        daemon = False

        def __init__(self, *, target, args, name, daemon):
            started.append({"target": target, "args": args, "name": name, "daemon": daemon})

        def start(self):
            started[0]["started"] = True

    monkeypatch.setattr(conversation_memory.threading, "Thread", FakeThread)
    conversation_memory.schedule_layered_capture(
        database_path="E:/tmp/private-memory.sqlite",
        user_id="user-1",
        conversation_id="conversation-1",
        run_id="run-1",
    )
    assert started and started[0]["started"] is True
    assert started[0]["daemon"] is True
    assert started[0]["name"] == "bhzd-private-memory"


def test_assistant_persistence_queues_derivation_after_commit(tmp_db_path, monkeypatch):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-persist@test.local")
        run_id, conversation_id = insert_run(db, user_id, "persist assistant")
        queued: dict[str, str] = {}

        def record_queue(**kwargs):
            # The queued worker may only receive an ID that is already durable.
            assert db.execute(
                """
                SELECT 1 FROM messages
                WHERE conversation_id = ? AND run_id = ? AND role = 'assistant'
                """,
                (conversation_id, run_id),
            ).fetchone()
            queued.update(kwargs)

        monkeypatch.setattr(conversation_memory, "schedule_layered_capture", record_queue)
        assistant_message = orchestrator._persist_message(
            db,
            conversation_id,
            run_id,
            "assistant",
            "The durable assistant response can be summarized later.",
        )
        assert queued == {
            "database_path": tmp_db_path,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "run_id": run_id,
        }
        assert db.execute(
            "SELECT 1 FROM messages WHERE id = ?", (assistant_message,)
        ).fetchone()
    finally:
        db.close()


def test_background_worker_uses_the_actual_run_database(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "layered-worker@test.local")
        run_id, conversation_id = insert_run(db, user_id, "worker source")
        orchestrator._persist_message(
            db,
            conversation_id,
            run_id,
            "user",
            "The worker database must retain this cross-session marker.",
        )
        orchestrator._persist_message(
            db,
            conversation_id,
            run_id,
            "assistant",
            "The worker can summarize the durable marker after this reply.",
        )

        # The worker opens a fresh connection.  Poll the same configured file
        # briefly rather than depending on scheduler timing in an assertion.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM private_memory_items WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row["count"] > 0:
                break
            time.sleep(0.02)
        assert row["count"] > 0
        assert db.execute(
            """
            SELECT COUNT(*) AS count
            FROM private_memory_items
            WHERE user_id = ? AND content LIKE '%cross-session marker%'
            """,
            (user_id,),
        ).fetchone()["count"] > 0
    finally:
        db.close()
