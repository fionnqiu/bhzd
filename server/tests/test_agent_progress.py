"""Regression coverage for replayable agent activity and live provider output."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from bhzd_py.agent import composer, events, orchestrator
from bhzd_py.tools import rag_tools
from bhzd_py.tools.registry import ToolContext

from _agent_helpers import (
    fetch_events,
    insert_run,
    insert_user,
    install_stub_tools,
    make_db,
)


@pytest.fixture()
def db(tmp_db_path):
    conn = make_db(tmp_db_path)
    yield conn
    conn.close()


@pytest.fixture()
def user_id(db):
    return insert_user(db)


@pytest.fixture(autouse=True)
def _offline_composer(monkeypatch):
    """Keep non-stream tests independent from a machine-local provider setup."""

    monkeypatch.setattr(composer, "_providers", lambda: None)


def _progress_rows(rows: list[dict]) -> list[dict]:
    return [row["payload"] for row in rows if row["event_type"] == events.RUN_PROGRESS]


def test_emit_progress_preserves_an_optional_activity_id(db, user_id):
    """The public progress contract may carry one stable visible-lifecycle key."""

    run_id, _ = insert_run(db, user_id, "test")
    events.emit_progress(
        db,
        run_id,
        phase="synthesis",
        status="running",
        title="Generating response",
        activity_id="answer:stable",
    )

    payload = json.loads(events.list_events(db, run_id)[0]["payload_json"])
    assert payload["activity_id"] == "answer:stable"


def test_orchestrator_drops_model_understanding_progress(db, user_id):
    """Model interpretation must not enter the replayable learner event stream."""

    run_id, _ = insert_run(db, user_id, "test")
    orchestrator._emit_progress(
        db,
        run_id,
        phase="understanding",
        status="running",
        title="internal intent classification",
    )

    assert events.list_events(db, run_id) == []


def test_progress_events_are_replayable_safe_summaries(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    secret = "do-not-expose-this-input"
    run_id, _ = insert_run(db, user_id, f"什么是 NER 标注？{secret}")

    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    rows = fetch_events(tmp_db_path, run_id)
    progress = _progress_rows(rows)
    assert progress
    assert all({"phase", "status", "title"} <= payload.keys() for payload in progress)
    assert all(payload["phase"] != "understanding" for payload in progress)
    assert ("planning", "completed") in {
        (payload["phase"], payload["status"]) for payload in progress
    }
    assert ("retrieval", "completed") in {
        (payload["phase"], payload["status"]) for payload in progress
    }
    assert ("synthesis", "completed") in {
        (payload["phase"], payload["status"]) for payload in progress
    }

    # Only concrete planning and final-response lifecycles get stable visible
    # keys; retrieval/tool mechanics remain unkeyed transport events.
    visible = [payload for payload in progress if payload.get("activity_id")]
    assert [(payload["phase"], payload["status"]) for payload in visible] == [
        ("planning", "running"),
        ("planning", "completed"),
        ("synthesis", "running"),
        ("synthesis", "completed"),
    ]
    assert {payload["activity_id"] for payload in visible} == {
        f"planning:{run_id}",
        f"answer:{run_id}",
    }
    assert all(
        "activity_id" not in payload
        for payload in progress
        if payload["phase"] in {"retrieval", "tool"}
    )

    # Only structured activity metadata may enter run.progress.  The request
    # text and tool payloads remain outside this user-facing activity channel.
    serialized = json.dumps(progress, ensure_ascii=False)
    assert secret not in serialized
    assert '"args"' not in serialized
    assert '"result"' not in serialized

    replayed = events.list_events(db, run_id, after_seq=0)
    assert sum(row["event_type"] == events.RUN_PROGRESS for row in replayed) == len(progress)


@pytest.mark.parametrize("reported_latency", [None, -1, False])
def test_retrieval_events_do_not_persist_the_user_query(
    db, user_id, monkeypatch, reported_latency
):
    """RAG lifecycle frames are replayed, so they must not carry private input."""

    class _FakeRetriever:
        class RagFilters:
            def __init__(self, **kwargs):
                self.values = kwargs

        @staticmethod
        def retrieve(*_args, **_kwargs):
            # An adapter may not have timing data; the emitted contract remains numeric.
            return SimpleNamespace(
                hits=[], latency_ms=reported_latency, below_threshold=False
            )

    secret = "student-private-search"
    monkeypatch.setattr(rag_tools, "_retriever", lambda: _FakeRetriever)
    run_id, _ = insert_run(db, user_id, "test run")

    result = rag_tools.rag_search_handler(
        ToolContext(
            db=db,
            config=object(),
            user_row=None,
            run_row={"id": run_id},
            conversation_row=None,
            args={"query": secret},
        )
    )

    replayed = events.list_events(db, run_id)
    started = next(row for row in replayed if row["event_type"] == events.RAG_RETRIEVAL_STARTED)
    completed = next(row for row in replayed if row["event_type"] == events.RAG_RETRIEVAL_COMPLETED)
    assert json.loads(started["payload_json"]) == {}
    assert json.loads(completed["payload_json"])["latency_ms"] == 0
    assert result["latency_ms"] == 0


def test_direct_chat_persists_first_provider_delta_before_next_chunk(
    db, tmp_db_path, user_id, monkeypatch
):
    observed_deltas: list[list[str]] = []

    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            yield {"delta": "第一段"}
            observed_deltas.append(
                [
                    row["payload"]["delta"]
                    for row in fetch_events(tmp_db_path, run_id)
                    if row["event_type"] == events.MESSAGE_DELTA
                ]
            )
            yield {"delta": "第二段"}
            yield {
                "done": True,
                "model": "test-model",
                "provider_id": "test-provider",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conversation_id = insert_run(db, user_id, "你好")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    assert observed_deltas == [["第一段"]]
    messages = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conversation_id,),
    ).fetchall()
    assert [message["content"] for message in messages] == ["第一段第二段"]


def test_final_composition_persists_first_provider_delta_before_next_chunk(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    observed_deltas: list[list[str]] = []

    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            yield {"delta": "最终"}
            observed_deltas.append(
                [
                    row["payload"]["delta"]
                    for row in fetch_events(tmp_db_path, run_id)
                    if row["event_type"] == events.MESSAGE_DELTA
                ]
            )
            yield {"delta": "回答"}
            yield {
                "done": True,
                "model": "test-model",
                "provider_id": "test-provider",
                "usage": {"prompt_tokens": 2, "completion_tokens": 2},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conversation_id = insert_run(db, user_id, "什么是 NER 标注？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    assert observed_deltas == [["最终"]]
    messages = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conversation_id,),
    ).fetchall()
    assert [message["content"] for message in messages] == ["最终回答"]


def test_provider_delta_keeps_existing_forty_character_sse_limit(
    db, tmp_db_path, user_id, monkeypatch
):
    provider_chunk = "x" * 81

    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            yield {"delta": provider_chunk}
            yield {"done": True, "model": "test-model", "provider_id": "test-provider"}

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conversation_id = insert_run(db, user_id, "hello")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    deltas = [
        row["payload"]["delta"]
        for row in fetch_events(tmp_db_path, run_id)
        if row["event_type"] == events.MESSAGE_DELTA
    ]
    assert [len(delta) for delta in deltas] == [40, 40, 1]
    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conversation_id,),
    ).fetchone()
    assert message["content"] == provider_chunk
