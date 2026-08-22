"""Focused contracts for the LangGraph compatibility runtime."""

from __future__ import annotations

import asyncio

from bhzd_py.agent import graph_runtime


def test_student_graph_routes_initial_execution() -> None:
    """The student graph dispatches only the opaque run coordinates."""

    calls: list[tuple[str, str, str]] = []

    async def execute(run_id: str, db_path: str) -> None:
        calls.append(("execute", run_id, db_path))

    async def continue_run(run_id: str, db_path: str) -> None:
        calls.append(("continue", run_id, db_path))

    asyncio.run(
        graph_runtime.run_student_graph(
            "run-1",
            "db.sqlite",
            operation="execute",
            execute_runner=execute,
            continue_runner=continue_run,
        )
    )

    assert calls == [("execute", "run-1", "db.sqlite")]


def test_student_graph_routes_confirmation_continuation() -> None:
    """The confirmation route resumes through the graph's continuation node."""

    calls: list[str] = []

    async def execute(run_id: str, db_path: str) -> None:
        calls.append("execute")

    async def continue_run(run_id: str, db_path: str) -> None:
        calls.append("continue")

    asyncio.run(
        graph_runtime.run_student_graph(
            "run-2",
            "db.sqlite",
            operation="continue",
            execute_runner=execute,
            continue_runner=continue_run,
        )
    )

    assert calls == ["continue"]


def test_student_graph_normalizes_unknown_operation_to_execute() -> None:
    """A malformed operation cannot select an arbitrary graph node."""

    calls: list[str] = []

    async def execute(run_id: str, db_path: str) -> None:
        calls.append("execute")

    async def continue_run(run_id: str, db_path: str) -> None:
        calls.append("continue")

    graph = graph_runtime.build_student_graph(execute, continue_run)
    asyncio.run(graph.ainvoke({"run_id": "run-3", "db_path": "db.sqlite", "operation": "bad"}))

    assert calls == ["execute"]


def test_teacher_graph_routes_execution() -> None:
    """Teacher workspaces use a separate graph with no learner continuation."""

    calls: list[tuple[str, str]] = []

    async def execute(run_id: str, db_path: str) -> None:
        calls.append((run_id, db_path))

    asyncio.run(
        graph_runtime.run_teacher_graph(
            "teacher-run",
            "db.sqlite",
            execute_runner=execute,
        )
    )

    assert calls == [("teacher-run", "db.sqlite")]
