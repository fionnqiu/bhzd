"""Durable LangGraph runtime for learner and teacher Agent workflows.

LangGraph owns phase transitions and interruption/resume semantics. SQLite
business tables remain authoritative for plans, tool calls, confirmations and
SSE events; the SQLite checkpointer stores only opaque graph control state.
"""

from __future__ import annotations

import sqlite3
import logging
import threading
from contextlib import asynccontextmanager, contextmanager
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from . import events

logger = logging.getLogger(__name__)
_CHECKPOINT_SCHEMA_LOCK = threading.Lock()


Operation = Literal["execute", "resume"]


def _checkpoint_path(db_path: str) -> str:
    """Use a sidecar SQLite file so checkpoint writes never lock business SSE IO."""

    return f"{db_path}.langgraph"


def _ensure_checkpoint_schema(db_path: str) -> None:
    """Create the sidecar schema once, serializing concurrent first requests."""

    path = _checkpoint_path(db_path)
    with _CHECKPOINT_SCHEMA_LOCK:
        conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                  thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
                  checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT,
                  type TEXT, checkpoint BLOB, metadata BLOB,
                  PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
                CREATE TABLE IF NOT EXISTS writes (
                  thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
                  checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,
                  idx INTEGER NOT NULL, channel TEXT NOT NULL, type TEXT,
                  value BLOB,
                  PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()


class AgentGraphState(TypedDict, total=False):
    """Bounded routing metadata; user content stays in business tables."""

    run_id: str
    db_path: str
    operation: Operation
    route: str
    scope: Literal["student", "teacher"]
    resumed: bool
    completed: bool


@asynccontextmanager
async def _async_checkpoint_store(db_path: str):
    """Open an async SQLite saver; ``SqliteSaver`` cannot serve ``ainvoke``."""

    # LangGraph calls the checkpointer's async methods from ``ainvoke``.  The
    # synchronous saver intentionally raises there, so use the official async
    # saver while retaining a separate connection from business DB I/O.
    _ensure_checkpoint_schema(db_path)
    async with AsyncSqliteSaver.from_conn_string(_checkpoint_path(db_path)) as saver:
        yield saver


@contextmanager
def _checkpoint_store(db_path: str):
    """Open a synchronous saver for diagnostics and state inspection."""

    conn = sqlite3.connect(_checkpoint_path(db_path), timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    saver = SqliteSaver(conn)
    saver.setup()
    try:
        yield saver
    finally:
        conn.close()


def _student_graph():
    from .student_graph import build_student_graph

    return build_student_graph()


def _teacher_graph():
    from .teacher_graph import build_teacher_graph

    return build_teacher_graph()


def _mark_graph_failure(run_id: str, db_path: str) -> None:
    """Converge an unexpected node exception into the existing safe run state."""

    from ..db import connect, utc_now_iso

    db = connect(db_path)
    try:
        row = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        # A confirmation transaction is the durable write boundary.  Its
        # business rows must remain actionable/inspectable even when the opaque
        # graph sidecar is unavailable; failing that run would misreport a
        # confirmed or still-pending write as an orchestration failure.
        if row is None or row["status"] in {
            "completed",
            "failed",
            "cancelled",
            "waiting_confirmation",
        }:
            return
        message = "处理本次请求时出现问题，请稍后重试"
        db.execute(
            "UPDATE agent_runs SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (message, utc_now_iso(), run_id),
        )
        events.emit(db, run_id, events.RUN_FAILED, {"error": message})
    finally:
        db.close()


def _business_run_is_terminal(run_id: str, db_path: str) -> bool:
    """Treat the business run row as authoritative before touching a checkpoint."""

    from ..db import connect

    db = connect(db_path)
    try:
        row = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return row is None or row["status"] in {"completed", "failed", "cancelled"}
    finally:
        db.close()


def _business_run_status(run_id: str, db_path: str) -> str | None:
    """Read the authoritative business status before touching graph state."""

    from ..db import connect

    db = connect(db_path)
    try:
        row = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return row["status"] if row is not None else None
    finally:
        db.close()


async def _checkpoint_matches_run(graph: Any, run_id: str) -> bool:
    """Reject a missing/partial checkpoint without exposing graph internals."""

    # Resume graphs use ``AsyncSqliteSaver``; its synchronous ``get_state``
    # path intentionally raises on the event-loop thread.  Use LangGraph's
    # async inspection API so a valid confirmation checkpoint can continue.
    snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
    values = snapshot.values or {}
    return isinstance(values, dict) and values.get("run_id") == run_id


async def run_student_graph(
    run_id: str,
    db_path: str,
    *,
    operation: str = "execute",
    execute_runner: Callable[[str, str], Awaitable[None]] | None = None,
    continue_runner: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    """Run a new learner request from the graph START node."""

    # Keep the old focused test harness callable while production entry points
    # use the native graph below.  No business orchestrator supplies these
    # callbacks; they exist solely for compatibility tests during migration.
    if execute_runner is not None or continue_runner is not None:
        runner = continue_runner if operation in {"continue", "resume"} else execute_runner
        if runner is None:
            runner = execute_runner or continue_runner
        if runner is not None:
            await runner(run_id, db_path)
            return

    try:
        async with _async_checkpoint_store(db_path) as checkpointer:
            graph = _student_graph().compile(checkpointer=checkpointer)
            await graph.ainvoke(
                {"run_id": run_id, "db_path": db_path, "operation": "execute", "scope": "student"},
                config={"configurable": {"thread_id": run_id}},
            )
    except Exception:
        logger.exception("student LangGraph run failed: %s", run_id)
        _mark_graph_failure(run_id, db_path)


async def resume_student_graph(run_id: str, db_path: str) -> None:
    """Resume a paused learner graph after a confirmation transaction."""

    try:
        async with _async_checkpoint_store(db_path) as checkpointer:
            graph = _student_graph().compile(checkpointer=checkpointer)
            if _business_run_is_terminal(run_id, db_path):
                return
            if not await _checkpoint_matches_run(graph, run_id):
                # A waiting confirmation is still represented by durable
                # business rows.  Keep that state intact when its opaque graph
                # checkpoint is missing or corrupt so the API can report the
                # real confirmation outcome instead of manufacturing failure.
                if _business_run_status(run_id, db_path) == "waiting_confirmation":
                    logger.warning("student graph checkpoint missing for confirmation run: %s", run_id)
                    return
                _mark_graph_failure(run_id, db_path)
                return
            await graph.ainvoke(
                Command(resume={"confirmed": True}),
                config={"configurable": {"thread_id": run_id}},
            )
    except Exception:
        logger.exception("student LangGraph resume failed: %s", run_id)
        _mark_graph_failure(run_id, db_path)


async def run_teacher_graph(
    run_id: str,
    db_path: str,
    *,
    execute_runner: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    """Run a new teacher request from the graph START node."""

    if execute_runner is not None:
        await execute_runner(run_id, db_path)
        return

    try:
        async with _async_checkpoint_store(db_path) as checkpointer:
            graph = _teacher_graph().compile(checkpointer=checkpointer)
            await graph.ainvoke(
                {"run_id": run_id, "db_path": db_path, "operation": "execute", "scope": "teacher"},
                config={"configurable": {"thread_id": run_id}},
            )
    except Exception:
        logger.exception("teacher LangGraph run failed: %s", run_id)
        _mark_graph_failure(run_id, db_path)


async def resume_teacher_graph(run_id: str, db_path: str) -> None:
    """Resume a teacher graph whose publish confirmation was applied."""

    try:
        async with _async_checkpoint_store(db_path) as checkpointer:
            graph = _teacher_graph().compile(checkpointer=checkpointer)
            if _business_run_is_terminal(run_id, db_path):
                return
            if not await _checkpoint_matches_run(graph, run_id):
                if _business_run_status(run_id, db_path) == "waiting_confirmation":
                    logger.warning("teacher graph checkpoint missing for confirmation run: %s", run_id)
                    return
                _mark_graph_failure(run_id, db_path)
                return
            await graph.ainvoke(
                Command(resume={"confirmed": True}),
                config={"configurable": {"thread_id": run_id}},
            )
    except Exception:
        logger.exception("teacher LangGraph resume failed: %s", run_id)
        _mark_graph_failure(run_id, db_path)


def graph_state(db_path: str, run_id: str, *, scope: str) -> dict[str, Any] | None:
    """Return bounded checkpoint metadata for diagnostics and recovery tests."""

    try:
        _ensure_checkpoint_schema(db_path)
        with _checkpoint_store(db_path) as checkpointer:
            graph = (_student_graph() if scope == "student" else _teacher_graph()).compile(
                checkpointer=checkpointer
            )
            snapshot = graph.get_state({"configurable": {"thread_id": run_id}})
            values = dict(snapshot.values or {})
            return {
                "thread_id": run_id,
                "route": values.get("route"),
                "scope": values.get("scope"),
                "next": list(snapshot.next or ()),
            }
    except Exception:
        # Diagnostics and recovery callers receive no provider/checkpoint
        # internals; the business run API remains the source of truth.
        logger.warning("unable to inspect LangGraph checkpoint for run %s", run_id)
        return None


def build_student_graph(
    execute_runner: Callable[[str, str], Awaitable[None]] | None = None,
    continue_runner: Callable[[str, str], Awaitable[None]] | None = None,
):
    """Build a tiny compatibility graph for migration-era routing tests.

    Production code calls :func:`_student_graph` and therefore always uses
    ``student_graph.py``.  This helper intentionally contains no business
    behavior and can be removed with the old test contract after downstream
    integrations move to ``run_student_graph``.
    """

    from langgraph.graph import END, START, StateGraph

    async def dispatch(state: AgentGraphState) -> AgentGraphState:
        operation = state.get("operation")
        runner = continue_runner if operation in {"continue", "resume"} else execute_runner
        if runner is None:
            runner = execute_runner or continue_runner
        if runner is not None:
            await runner(state["run_id"], state["db_path"])
        return {"completed": True}

    graph = StateGraph(AgentGraphState)
    graph.add_node("dispatch", dispatch)
    graph.add_edge(START, "dispatch")
    graph.add_edge("dispatch", END)
    return graph.compile()
