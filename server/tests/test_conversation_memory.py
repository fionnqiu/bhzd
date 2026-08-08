"""Regression tests for private current-conversation vector memory."""

from __future__ import annotations

import asyncio
import uuid

from bhzd_py.agent import composer, conversation_memory, orchestrator
from bhzd_py.db import utc_now_iso

from _agent_helpers import insert_run, insert_user, make_db


def _insert_message(db, conversation_id: str, content: str) -> str:
    """Add a source message without indexing it to exercise upgrade backfill."""

    message_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, NULL, 'assistant', ?, ?)
        """,
        (message_id, conversation_id, content, utc_now_iso()),
    )
    db.commit()
    return message_id


def _insert_follow_up_run(db, user_id: str, conversation_id: str, input_text: str) -> str:
    """Create a later direct-chat run in the same conversation for integration coverage."""

    run_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text, created_at)
        VALUES (?, ?, ?, 'running', ?, ?)
        """,
        (run_id, conversation_id, user_id, input_text, utc_now_iso()),
    )
    db.commit()
    return run_id


def test_memory_backfill_is_scoped_to_one_user_and_conversation(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        first_user = insert_user(db, "first@test.local")
        second_user = insert_user(db, "second@test.local")
        _, first_conversation = insert_run(db, first_user, "开始第一段会话")
        _, second_conversation = insert_run(db, second_user, "开始第二段会话")
        _insert_message(db, first_conversation, "第一段会话的私有标记：蓝色灯塔")
        _insert_message(db, second_conversation, "第二段会话的私有标记：红色海岸")

        chunks = conversation_memory.retrieve_context(
            db,
            user_id=first_user,
            conversation_id=first_conversation,
            query="蓝色灯塔是什么？",
        )

        assert [chunk["content"] for chunk in chunks] == ["第一段会话的私有标记：蓝色灯塔"]
        indexed = db.execute(
            "SELECT user_id, conversation_id FROM conversation_memory_chunks ORDER BY rowid"
        ).fetchall()
        assert {(row["user_id"], row["conversation_id"]) for row in indexed} == {
            (first_user, first_conversation),
        }
    finally:
        db.close()


def test_memory_index_failure_does_not_block_a_persisted_message(tmp_db_path, monkeypatch):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        _, conversation_id = insert_run(db, user_id, "开始会话")
        message_id = _insert_message(db, conversation_id, "即使索引失败也必须保留这条消息")

        def _fail_embedding(_db, _texts):
            raise RuntimeError("embedding unavailable")

        monkeypatch.setattr(conversation_memory, "embed_chunks", _fail_embedding)
        conversation_memory.index_message(
            db,
            message_id=message_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=None,
            role="assistant",
            content="即使索引失败也必须保留这条消息",
            created_at=utc_now_iso(),
        )

        assert db.execute("SELECT content FROM messages WHERE id = ?", (message_id,)).fetchone()["content"]
        assert db.execute(
            "SELECT COUNT(*) AS count FROM conversation_memory_chunks"
        ).fetchone()["count"] == 0
    finally:
        db.close()


def test_memory_rows_cascade_when_source_messages_are_deleted(tmp_db_path):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        _, conversation_id = insert_run(db, user_id, "开始会话")
        message_id = _insert_message(db, conversation_id, "删除时必须同步清理")
        conversation_memory.index_message(
            db,
            message_id=message_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=None,
            role="assistant",
            content="删除时必须同步清理",
            created_at=utc_now_iso(),
        )
        assert db.execute(
            "SELECT COUNT(*) AS count FROM conversation_memory_chunks"
        ).fetchone()["count"] == 1

        db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        db.commit()

        assert db.execute(
            "SELECT COUNT(*) AS count FROM conversation_memory_chunks"
        ).fetchone()["count"] == 0
    finally:
        db.close()


def test_conversation_recall_injects_private_vector_memory(tmp_db_path, monkeypatch):
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        first_run, conversation_id = insert_run(db, user_id, "开始本次会话")
        db.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
            VALUES (?, ?, ?, 'assistant', ?, ?)
            """,
            (
                uuid.uuid4().hex,
                conversation_id,
                first_run,
                "你之前选择了语音标注方向。",
                utc_now_iso(),
            ),
        )
        db.commit()
        recall_run = _insert_follow_up_run(
            db, user_id, conversation_id, "你还记得之前我问过什么吗？"
        )

        class _FakeProviders:
            @staticmethod
            async def stream_deltas(messages, *, role):
                assert role == "primary"
                private_context = next(
                    message["content"]
                    for message in messages
                    if message["role"] == "system" and "私有历史片段" in message["content"]
                )
                assert "语音标注方向" in private_context
                assert messages[-1] == {
                    "role": "user", "content": "你还记得之前我问过什么吗？"
                }
                yield {"delta": "记得，你之前选择了语音标注方向。"}

        monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
        asyncio.run(orchestrator.execute_run(recall_run, tmp_db_path))

        assert db.execute(
            "SELECT COUNT(*) AS count FROM tool_calls WHERE run_id = ?", (recall_run,)
        ).fetchone()["count"] == 0
        assert db.execute(
            "SELECT content FROM messages WHERE run_id = ? AND role = 'assistant'", (recall_run,)
        ).fetchone()["content"] == "记得，你之前选择了语音标注方向。"
    finally:
        db.close()
