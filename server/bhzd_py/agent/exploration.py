"""Bounded read-only exploration for the hybrid LangGraph architecture.

The main Agent graphs own durable business workflows.  This module is the
small, intentionally disposable exploration subgraph used when a question
benefits from more than one source: RAG evidence, capability graph nodes, and
curriculum units.  Every tool call is checked against the caller's allowlist
and the registry's read permission before it is executed; no preview/apply
path is reachable from this graph.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from ..tools.registry import ToolContext, ToolSpec, get as get_tool

# These are the product-approved default exploration sources.  ``course.search``
# is the curriculum read tool; callers may narrow this set for a given role.
READ_ONLY_TOOLS = frozenset({"rag.search", "graph.reason", "course.search"})


@dataclass(frozen=True)
class ExplorationPolicy:
    """Hard limits for one read-only exploration run.

    The limits are deliberately part of the value object so API callers and
    tests can make the bounded behavior explicit instead of relying on hidden
    module globals.
    """

    max_steps: int = 3
    timeout_seconds: float = 5.0
    allowed_tools: frozenset[str] = field(default_factory=lambda: READ_ONLY_TOOLS)
    max_results: int = 8

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_results < 1:
            raise ValueError("max_results must be positive")
        object.__setattr__(
            self,
            "allowed_tools",
            frozenset(str(name) for name in self.allowed_tools),
        )


@dataclass
class ExplorationContext:
    """Read-only dependencies passed to registered tool handlers.

    ``ToolContext`` is rebuilt for every call so a planner cannot smuggle
    arguments from one step into another.  The connection/config objects are
    owned by the caller and are never closed or mutated by this module.
    """

    db: Any = None
    config: Any = None
    user_row: Any = None
    run_row: Any = None
    conversation_row: Any = None


class ExplorationState(TypedDict, total=False):
    """LangGraph state; tool results contain only read-tool payloads."""

    query: str
    context: ExplorationContext
    policy: ExplorationPolicy
    tool_results: dict[str, dict[str, Any]]
    steps: list[dict[str, Any]]
    step_count: int
    started_at: float
    next_tool: str | None
    next_args: dict[str, Any]
    timed_out: bool
    error: str | None
    fused: dict[str, Any]
    finished: bool


Planner = Callable[[str, Mapping[str, dict[str, Any]]], tuple[str, Mapping[str, Any]] | None]


def _tool_payload(value: Any) -> dict[str, Any]:
    """Normalize a handler result without exposing arbitrary object state."""

    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def _read_tool(spec: ToolSpec, context: ExplorationContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke only a registered read handler; writes are rejected at the edge."""

    if spec.permission != "read" or spec.handler is None:
        raise PermissionError("exploration only permits registered read tools")
    tool_context = ToolContext(
        db=context.db,
        config=context.config,
        user_row=context.user_row,
        run_row=context.run_row,
        conversation_row=context.conversation_row,
        args=dict(args),
    )
    return _tool_payload(spec.handler(tool_context))


def _default_planner(query: str, observed: Mapping[str, dict[str, Any]]) -> tuple[str, Mapping[str, Any]] | None:
    """Use a deterministic ReAct plan: evidence, graph, then curriculum.

    Each next action is selected from the observations already collected.  The
    deterministic default keeps latency and cost predictable while callers can
    inject a similarly constrained planner when model-guided selection is useful.
    """

    if "rag.search" not in observed:
        return "rag.search", {"query": query}
    if "graph.reason" not in observed:
        return "graph.reason", {"action": "locate", "query": query, "limit": 8}
    if "course.search" not in observed:
        return "course.search", {"query": query}
    return None


def _initialize(state: ExplorationState) -> ExplorationState:
    """Initialize bounded-loop bookkeeping and normalize untrusted query text."""

    return {
        "query": str(state.get("query") or "").strip(),
        "tool_results": {},
        "steps": [],
        "step_count": 0,
        "started_at": time.monotonic(),
        "timed_out": False,
        "error": None,
        "finished": False,
    }


def _plan_node(state: ExplorationState, planner: Planner) -> ExplorationState:
    """Select one next read action, enforcing the policy before routing."""

    policy = state["policy"]
    elapsed = time.monotonic() - state["started_at"]
    if state["step_count"] >= policy.max_steps or elapsed >= policy.timeout_seconds:
        return {"next_tool": None, "timed_out": elapsed >= policy.timeout_seconds}

    planned = planner(state["query"], state.get("tool_results", {}))
    if planned is None:
        return {"next_tool": None}
    name, raw_args = planned
    tool_name = str(name)
    if tool_name not in policy.allowed_tools:
        return {"next_tool": None, "error": "tool_not_allowed"}
    if tool_name in state.get("tool_results", {}):
        return {"next_tool": None, "error": "planner_repeated_tool"}
    return {"next_tool": tool_name, "next_args": dict(raw_args)}


def _route(state: ExplorationState) -> str:
    """Keep conditional routing closed to the two compiled graph branches."""

    return "tool" if state.get("next_tool") else "finish"


def _tool_node(state: ExplorationState) -> ExplorationState:
    """Execute one bounded, permission-checked read call and record a safe trace."""

    name = state.get("next_tool")
    if not name:
        return {}
    policy = state["policy"]
    if name not in policy.allowed_tools:
        return {"next_tool": None, "error": "tool_not_allowed"}
    if state["step_count"] >= policy.max_steps:
        return {"timed_out": True, "next_tool": None}
    if time.monotonic() - state["started_at"] >= policy.timeout_seconds:
        return {"timed_out": True, "next_tool": None}

    result: dict[str, Any]
    status = "completed"
    try:
        # Registry lookup is repeated at execution time so runtime overrides and
        # tests cannot bypass the permission check captured by the planner.
        spec = get_tool(name)
        result = _read_tool(spec, state["context"], state.get("next_args", {}))
    except (KeyError, PermissionError):
        status = "denied"
        result = {"error": "read_tool_denied"}
    except Exception:
        # Tool internals may contain provider/database details; expose only a
        # stable safe marker to the caller and continue to the other sources.
        status = "failed"
        result = {"error": "read_tool_failed"}

    results = dict(state.get("tool_results", {}))
    results[name] = result
    steps = list(state.get("steps", []))
    steps.append({"tool": name, "status": status})
    return {
        "tool_results": results,
        "steps": steps,
        "step_count": state["step_count"] + 1,
        "next_tool": None,
        "next_args": {},
    }


def _as_list(payload: Mapping[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = payload.get(key, []) if payload else []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def merge_graphrag(
    query: str,
    tool_results: Mapping[str, Mapping[str, Any]],
    *,
    max_results: int = 8,
) -> dict[str, Any]:
    """Fuse RAG hits with graph and curriculum evidence without writing state."""

    rag = tool_results.get("rag.search", {})
    graph = tool_results.get("graph.reason", {})
    curriculum = tool_results.get("course.search", {})
    rag_hits = _as_list(rag, "hits")[:max_results]
    graph_nodes = _as_list(graph, "nodes")[:max_results]
    units = _as_list(curriculum, "units")[:max_results]

    related_cap_ids: list[str] = []
    for source in (graph,):
        for cap_id in source.get("cap_ids", []) if isinstance(source, Mapping) else []:
            value = str(cap_id)
            if value and value not in related_cap_ids:
                related_cap_ids.append(value)
    for node in graph_nodes:
        if node.get("type") == "CAP" and node.get("id") not in related_cap_ids:
            related_cap_ids.append(str(node["id"]))
    for unit in units:
        for cap_id in unit.get("cap_ids", []):
            value = str(cap_id)
            if value and value not in related_cap_ids:
                related_cap_ids.append(value)

    # Prefix evidence identifiers so a chunk id and graph node id can coexist.
    fused_evidence: list[dict[str, Any]] = []
    for hit in rag_hits:
        fused_evidence.append({"source": "rag", "id": hit.get("chunk_id"), "item": hit})
    for node in graph_nodes:
        fused_evidence.append({"source": "graph", "id": node.get("id"), "item": node})
    for unit in units:
        fused_evidence.append({"source": "curriculum", "id": unit.get("unit_id"), "item": unit})

    return {
        "query": query,
        "rag_hits": rag_hits,
        "graph_nodes": graph_nodes,
        "curriculum_units": units,
        "related_cap_ids": related_cap_ids,
        "fused_evidence": fused_evidence,
    }


def _finish_node(state: ExplorationState) -> ExplorationState:
    """Create the query-time GraphRAG projection used by the parent Agent graph."""

    return {
        "fused": merge_graphrag(
            state["query"],
            state.get("tool_results", {}),
            max_results=state["policy"].max_results,
        ),
        "finished": True,
    }


def _merge_state(state: ExplorationState, updates: ExplorationState) -> ExplorationState:
    """Mirror LangGraph's partial-state merge for the nested synchronous path."""

    return cast(ExplorationState, {**state, **updates})


def build_exploration_graph(
    *,
    policy: ExplorationPolicy | None = None,
    planner: Planner | None = None,
):
    """Compile the bounded ReAct-style exploration StateGraph."""

    effective_policy = policy or ExplorationPolicy()
    effective_planner = planner or _default_planner

    def initialize(state: ExplorationState) -> ExplorationState:
        initialized = _initialize(state)
        # Supplying the policy at compile time keeps direct graph callers safe;
        # run_exploration also passes it explicitly for checkpoint portability.
        if not isinstance(state.get("policy"), ExplorationPolicy):
            initialized["policy"] = effective_policy
        return initialized

    def plan(state: ExplorationState) -> ExplorationState:
        return _plan_node(state, effective_planner)

    graph = StateGraph(ExplorationState)
    graph.add_node("initialize", initialize)
    graph.add_node("plan", plan)
    graph.add_node("tool", _tool_node)
    graph.add_node("finish", _finish_node)
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "plan")
    graph.add_conditional_edges("plan", _route, {"tool": "tool", "finish": "finish"})
    graph.add_edge("tool", "plan")
    graph.add_edge("finish", END)
    return graph.compile()


def run_exploration(
    query: str,
    context: ExplorationContext,
    *,
    policy: ExplorationPolicy | None = None,
    planner: Planner | None = None,
    use_graph: bool = True,
) -> dict[str, Any]:
    """Run one bounded exploration and return only its safe public projection."""

    effective_policy = policy or ExplorationPolicy()
    if use_graph:
        graph = build_exploration_graph(policy=effective_policy, planner=planner)
        state = graph.invoke(
            {"query": query, "context": context, "policy": effective_policy},
            config={"configurable": {"thread_id": f"explore-{id(context)}"}},
        )
    else:
        # Nested execution from a durable async parent cannot use a synchronous
        # child checkpointer.  Run the same compiled-node contract directly;
        # the top-level public path remains the native LangGraph subgraph.
        state = _initialize({"query": query, "context": context, "policy": effective_policy})
        # The direct child path mirrors LangGraph's state merge semantics.  Keep
        # the policy and context in the accumulator because the node helpers
        # intentionally return only their changed fields.
        state["policy"] = effective_policy
        state["context"] = context
        effective_planner = planner or _default_planner
        while True:
            state = _merge_state(state, _plan_node(state, effective_planner))
            if not state.get("next_tool"):
                state = _merge_state(state, _finish_node(state))
                break
            state = _merge_state(state, _tool_node(state))
    return {
        "query": state.get("query", ""),
        "steps": state.get("steps", []),
        "tool_results": state.get("tool_results", {}),
        "fused": state.get("fused", {}),
        "timed_out": bool(state.get("timed_out", False)),
        "error": state.get("error"),
    }


__all__ = [
    "ExplorationContext",
    "ExplorationPolicy",
    "ExplorationState",
    "READ_ONLY_TOOLS",
    "build_exploration_graph",
    "merge_graphrag",
    "run_exploration",
]
