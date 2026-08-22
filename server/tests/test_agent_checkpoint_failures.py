"""Failure-boundary contracts for the durable LangGraph checkpoint sidecar."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bhzd_py.agent import events, graph_runtime

from _agent_helpers import insert_run, insert_user, make_db, open_db


def _run_status(db_path: str, run_id: str) -> tuple[str, str | None]:
    """Read only the business projection; checkpoint blobs stay opaque to callers."""

    db = open_db(db_path)
    try:
        row = db.execute(
            "SELECT status, error FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row is not None
        return row["status"], row["error"]
    finally:
        db.close()


def test_async_checkpoint_store_creates_sidecar_schema(tmp_db_path: str) -> None:
    """The first graph request initializes an isolated checkpoint database."""

    sidecar = Path(graph_runtime._checkpoint_path(tmp_db_path))
    assert not sidecar.exists()

    async def open_and_close() -> None:
        async with graph_runtime._async_checkpoint_store(tmp_db_path):
            pass

    asyncio.run(open_and_close())

    assert sidecar.exists()
    db = sqlite3.connect(sidecar)
    try:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        db.close()
    assert {"checkpoints", "writes"}.issubset(tables)


def test_resume_marks_running_run_failed_when_sidecar_is_missing(tmp_db_path: str) -> None:
    """A non-confirmation run cannot resume without its opaque checkpoint."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "解释一个概念", status="running")
    finally:
        db.close()

    asyncio.run(graph_runtime.resume_student_graph(run_id, tmp_db_path))

    status, error = _run_status(tmp_db_path, run_id)
    assert status == "failed"
    assert error == "处理本次请求时出现问题，请稍后重试"


def test_resume_keeps_waiting_confirmation_when_sidecar_is_missing(tmp_db_path: str) -> None:
    """A restart must not turn an actionable confirmation into a generic failure."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "创建一个练习", status="waiting_confirmation")
    finally:
        db.close()

    # No ``.langgraph`` file is created before resume.  The business confirmation
    # row is authoritative, so a missing opaque graph checkpoint must be benign.
    asyncio.run(graph_runtime.resume_student_graph(run_id, tmp_db_path))

    assert _run_status(tmp_db_path, run_id) == ("waiting_confirmation", None)
    db = open_db(tmp_db_path)
    try:
        assert db.execute(
            "SELECT COUNT(*) FROM agent_events WHERE run_id = ? AND event_type = ?",
            (run_id, events.RUN_FAILED),
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_run_marks_running_failed_when_checkpoint_store_cannot_open(
    tmp_db_path: str, monkeypatch
) -> None:
    """Sidecar setup errors converge a live business run to one safe terminal event."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "解释一个概念", status="running")
    finally:
        db.close()

    @asynccontextmanager
    async def unavailable_checkpoint(_db_path: str):
        # Simulate a locked/unavailable sidecar before the graph is compiled.
        raise RuntimeError("checkpoint unavailable")
        yield  # pragma: no cover - keeps this an async context manager

    monkeypatch.setattr(graph_runtime, "_async_checkpoint_store", unavailable_checkpoint)

    asyncio.run(graph_runtime.run_student_graph(run_id, tmp_db_path))

    status, error = _run_status(tmp_db_path, run_id)
    assert status == "failed"
    assert error == "处理本次请求时出现问题，请稍后重试"
    db = open_db(tmp_db_path)
    try:
        assert db.execute(
            "SELECT COUNT(*) FROM agent_events WHERE run_id = ? AND event_type = ?",
            (run_id, events.RUN_FAILED),
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_graph_state_returns_none_for_corrupt_checkpoint_blob(tmp_db_path: str) -> None:
    """Diagnostic state never exposes msgpack/SQLite decoding failures to callers."""

    graph_runtime._ensure_checkpoint_schema(tmp_db_path)
    sidecar = graph_runtime._checkpoint_path(tmp_db_path)
    db = sqlite3.connect(sidecar)
    try:
        # The blob is intentionally not a valid LangGraph serializer payload.
        db.execute(
            """
            INSERT INTO checkpoints
              (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata)
            VALUES (?, '', ?, 'msgpack', ?, '{}')
            """,
            ("corrupt-run", "00000000-0000-0000-0000-000000000001", b"not-msgpack"),
        )
        db.commit()
    finally:
        db.close()

    assert graph_runtime.graph_state(tmp_db_path, "corrupt-run", scope="student") is None


@pytest.mark.parametrize("status", ("completed", "failed", "cancelled"))
def test_mark_graph_failure_does_not_overwrite_terminal_run(
    tmp_db_path: str, status: str
) -> None:
    """A late checkpoint exception cannot rewrite an already terminal business row."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "已结束的请求", status=status)
    finally:
        db.close()

    graph_runtime._mark_graph_failure(run_id, tmp_db_path)

    assert _run_status(tmp_db_path, run_id) == (status, None)
    db = open_db(tmp_db_path)
    try:
        assert db.execute(
            "SELECT COUNT(*) FROM agent_events WHERE run_id = ? AND event_type = ?",
            (run_id, events.RUN_FAILED),
        ).fetchone()[0] == 0
    finally:
        db.close()
