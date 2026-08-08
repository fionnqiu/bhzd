"""LLM-first chat and clarification regression tests."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from bhzd_py.agent import composer, events, orchestrator, prompts
from bhzd_py.db import utc_now_iso

from _agent_helpers import fetch_events, insert_run, insert_user, make_db


@pytest.fixture()
def db(tmp_db_path):
    conn = make_db(tmp_db_path)
    yield conn
    conn.close()


@pytest.fixture()
def user_id(db):
    return insert_user(db)


def _insert_follow_up_run(db, user_id: str, conversation_id: str, input_text: str) -> str:
    """Insert a later run in the same conversation without router side effects."""

    now = utc_now_iso()
    run_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO agent_runs
          (id, conversation_id, user_id, status, input_text, created_at)
        VALUES (?, ?, ?, 'running', ?, ?)
        """,
        (run_id, conversation_id, user_id, input_text, now),
    )
    db.commit()
    return run_id


def test_unknown_input_uses_llm_direct_chat(db, tmp_db_path, user_id, monkeypatch):
    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            assert messages[0]["role"] == "system"
            assert messages[-1]["role"] == "user"
            assert messages[-1]["content"] == "\u4f60\u597d"
            yield {"delta": "\u4f60\u597d\uff01"}
            yield {"delta": "\u6709\u4ec0\u4e48\u53ef\u4ee5\u5e2e\u4f60\uff1f"}
            yield {
                "done": True,
                "model": "model-a",
                "provider_id": "provider-a",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conv_id = insert_run(db, user_id, "\u4f60\u597d")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    run = db.execute(
        "SELECT status, provider_id, usage_json FROM agent_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert run["status"] == "completed"
    assert run["provider_id"] == "provider-a"
    assert json.loads(run["usage_json"]) == {
        "prompt_tokens": 2,
        "completion_tokens": 3,
    }

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert (
        message["content"] == "\u4f60\u597d\uff01\u6709\u4ec0\u4e48\u53ef\u4ee5\u5e2e\u4f60\uff1f"
    )

    rows = fetch_events(tmp_db_path, run_id)
    assert any(row["event_type"] == events.RUN_USAGE for row in rows)
    progress = [row["payload"] for row in rows if row["event_type"] == events.RUN_PROGRESS]
    visible = [payload for payload in progress if payload.get("activity_id")]
    # A direct chat turn has no verifiable execution plan, so it exposes only
    # response generation and never fabricates a model-thinking activity.
    assert all(payload["phase"] != "understanding" for payload in progress)
    assert [(payload["phase"], payload["status"]) for payload in visible] == [
        ("synthesis", "running"),
        ("synthesis", "completed"),
    ]
    assert {payload["activity_id"] for payload in visible} == {
        f"answer:{run_id}",
    }
    assert all(
        "activity_id" not in payload
        for payload in progress
        if payload["phase"] in {"tool", "retrieval", "system"}
    )


def test_identity_question_uses_direct_chat_without_rag_tools(
    db, tmp_db_path, user_id, monkeypatch
):
    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            assert role == "primary"
            assert messages[0]["content"] == prompts.CHAT_SYSTEM
            assert "Never guess or claim a specific provider" in messages[0]["content"]
            assert messages[-1] == {"role": "user", "content": "你是什么模型？"}
            yield {"delta": "我是标航智导的学习助手，当前会话无法确认底层模型版本。"}
            yield {
                "done": True,
                "model": "model-a",
                "provider_id": "provider-a",
                "usage": {"prompt_tokens": 4, "completion_tokens": 8},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conv_id = insert_run(db, user_id, "你是什么模型？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == "我是标航智导的学习助手，当前会话无法确认底层模型版本。"
    assert db.execute(
        "SELECT COUNT(*) AS count FROM tool_calls WHERE run_id = ?", (run_id,)
    ).fetchone()["count"] == 0

    event_types = [row["event_type"] for row in fetch_events(tmp_db_path, run_id)]
    assert events.PLAN_UPDATED not in event_types
    assert events.TOOL_CALL_REQUESTED not in event_types
    assert events.TOOL_CALL_COMPLETED not in event_types
    assert events.RAG_RETRIEVAL_STARTED not in event_types
    assert events.RAG_RETRIEVAL_COMPLETED not in event_types


def test_identity_question_uses_safe_local_reply_when_chat_models_fail(
    db, tmp_db_path, user_id, monkeypatch
):
    class _UnavailableProviders:
        @staticmethod
        async def stream_deltas(_messages, *, role):
            if False:
                yield {"role": role}

        @staticmethod
        async def complete(_messages, *, role):
            return None

    monkeypatch.setattr(composer, "_providers", lambda: _UnavailableProviders)
    run_id, conv_id = insert_run(db, user_id, "你是谁？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == prompts.IDENTITY_FALLBACK
    assert db.execute(
        "SELECT COUNT(*) AS count FROM tool_calls WHERE run_id = ?", (run_id,)
    ).fetchone()["count"] == 0


def test_incomplete_goal_uses_llm_clarification(db, tmp_db_path, user_id, monkeypatch):
    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            assert messages[-1]["content"] == "\u6211\u60f3\u5b66\u6807\u6ce8"
            yield {"delta": "\u4f60\u60f3\u5148\u5b66\u54ea\u79cd\u6807\u6ce8\uff1f"}
            yield {
                "done": True,
                "model": "model-a",
                "provider_id": "provider-a",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conv_id = insert_run(db, user_id, "\u6211\u60f3\u5b66\u6807\u6ce8")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    run = db.execute(
        "SELECT status, provider_id FROM agent_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert run["status"] == "completed"
    assert run["provider_id"] == "provider-a"

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == "\u4f60\u60f3\u5148\u5b66\u54ea\u79cd\u6807\u6ce8\uff1f"
    tool_count = db.execute(
        "SELECT COUNT(*) AS c FROM tool_calls WHERE run_id = ?", (run_id,)
    ).fetchone()["c"]
    assert tool_count == 0


def test_llm_follow_up_receives_previous_chat_history(db, tmp_db_path, user_id, monkeypatch):
    class _FakeProviders:
        calls = 0

        @classmethod
        async def stream_deltas(cls, messages, *, role):
            cls.calls += 1
            assert messages[0]["role"] == "system"
            if cls.calls == 1:
                assert len(messages) == 2
                assert messages[-1]["content"] == "\u6211\u60f3\u5b66\u6807\u6ce8"
                yield {"delta": "\u4f60\u60f3\u5148\u5b66\u54ea\u79cd\u6807\u6ce8\uff1f"}
            else:
                assert "assistant" in [m["role"] for m in messages]
                assert messages[-1]["content"] == "\u8bed\u97f3"
                yield {
                    "delta": "\u597d\u7684\uff0c\u8bed\u97f3\u6807\u6ce8\u5f88\u5408\u9002\u3002"
                }
            yield {
                "done": True,
                "model": "model-a",
                "provider_id": "provider-a",
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    first_run, conv_id = insert_run(db, user_id, "\u6211\u60f3\u5b66\u6807\u6ce8")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))

    second_run = _insert_follow_up_run(db, user_id, conv_id, "\u8bed\u97f3")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))

    messages = db.execute(
        """
        SELECT content FROM messages
        WHERE conversation_id = ? AND role = 'assistant'
        ORDER BY rowid ASC
        """,
        (conv_id,),
    ).fetchall()
    assert [m["content"] for m in messages] == [
        "\u4f60\u60f3\u5148\u5b66\u54ea\u79cd\u6807\u6ce8\uff1f",
        "\u597d\u7684\uff0c\u8bed\u97f3\u6807\u6ce8\u5f88\u5408\u9002\u3002",
    ]
