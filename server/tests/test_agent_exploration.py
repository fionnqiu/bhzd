"""Focused tests for the bounded read-only exploration subgraph."""

from __future__ import annotations

from bhzd_py.agent.exploration import (
    ExplorationContext,
    ExplorationPolicy,
    merge_graphrag,
    run_exploration,
)
from bhzd_py.tools.registry import ToolSpec


def test_exploration_runs_allowlisted_reads_and_fuses_sources(monkeypatch) -> None:
    """The default ReAct loop visits RAG, graph, and curriculum read tools."""

    calls: list[str] = []

    def rag(ctx):
        calls.append("rag.search")
        return {"hits": [{"chunk_id": "chunk-1", "content": "规范"}]}

    def graph(ctx):
        calls.append("graph.reason")
        return {"nodes": [{"id": "CAP-1", "type": "CAP", "label": "能力"}], "cap_ids": ["CAP-1"]}

    def course(ctx):
        calls.append("course.search")
        return {"units": [{"unit_id": "unit-1", "cap_ids": ["CAP-1"]}]}

    replacement = {
        "rag.search": ToolSpec("rag.search", "read", True, "", handler=rag),
        "graph.reason": ToolSpec("graph.reason", "read", True, "", handler=graph),
        "course.search": ToolSpec("course.search", "read", True, "", handler=course),
    }
    monkeypatch.setattr("bhzd_py.tools.registry.TOOLS", replacement)

    result = run_exploration("标注规范", ExplorationContext())

    assert calls == ["rag.search", "graph.reason", "course.search"]
    assert result["timed_out"] is False
    assert result["fused"]["related_cap_ids"] == ["CAP-1"]
    assert [item["source"] for item in result["fused"]["fused_evidence"]] == [
        "rag",
        "graph",
        "curriculum",
    ]


def test_exploration_never_invokes_write_tools(monkeypatch) -> None:
    """A planner selecting a write spec is denied before its handler runs."""

    writes: list[str] = []

    def write_handler(ctx):
        writes.append("write")
        return {"ok": True}

    replacement = {
        "task.create": ToolSpec("task.create", "write", True, "", handler=write_handler),
    }
    monkeypatch.setattr("bhzd_py.tools.registry.TOOLS", replacement)

    def planner(query, observed):
        return "task.create", {"title": "do not write"}

    result = run_exploration(
        "test",
        ExplorationContext(),
        policy=ExplorationPolicy(max_steps=1, allowed_tools=frozenset({"task.create"})),
        planner=planner,
    )

    assert writes == []
    assert result["steps"] == [{"tool": "task.create", "status": "denied"}]
    assert result["tool_results"]["task.create"] == {"error": "read_tool_denied"}


def test_exploration_respects_step_budget_and_merge_limits(monkeypatch) -> None:
    """Step and evidence limits remain effective even when a planner loops."""

    calls: list[str] = []

    def rag(ctx):
        calls.append("rag.search")
        return {"hits": [{"chunk_id": str(i)} for i in range(5)]}

    replacement = {"rag.search": ToolSpec("rag.search", "read", True, "", handler=rag)}
    monkeypatch.setattr("bhzd_py.tools.registry.TOOLS", replacement)

    def planner(query, observed):
        return "rag.search", {"query": query}

    result = run_exploration(
        "test",
        ExplorationContext(),
        policy=ExplorationPolicy(max_steps=1, max_results=2, allowed_tools=frozenset({"rag.search"})),
        planner=planner,
    )

    assert calls == ["rag.search"]
    assert len(result["fused"]["rag_hits"]) == 2


def test_merge_graphrag_is_pure_and_deduplicates_capabilities() -> None:
    """Fusion only projects evidence and never mutates tool payloads."""

    tool_results = {
        "rag.search": {"hits": [{"chunk_id": "c1"}]},
        "graph.reason": {
            "nodes": [{"id": "CAP-1", "type": "CAP"}],
            "cap_ids": ["CAP-1", "CAP-1"],
        },
    }
    before = {key: value.copy() for key, value in tool_results.items()}

    fused = merge_graphrag("q", tool_results, max_results=1)

    assert fused["related_cap_ids"] == ["CAP-1"]
    assert tool_results == before
