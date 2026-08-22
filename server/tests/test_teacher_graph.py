"""Focused contracts for the native teacher LangGraph definition."""

from __future__ import annotations

from bhzd_py.agent import teacher_graph


def test_teacher_graph_exposes_the_bounded_teacher_nodes() -> None:
    """The graph has explicit business phases instead of one callback node."""

    graph = teacher_graph.build_teacher_graph()

    assert set(graph.nodes) == {
        "prepare",
        "class_insights",
        "draft_preview",
        "publish_interrupt",
        "finalize",
    }
    # Compile without a checkpointer to catch invalid edges and state schemas
    # while keeping this contract test independent from SQLite fixtures.
    assert graph.compile() is not None


def test_teacher_graph_private_plan_parser_ignores_malformed_rows() -> None:
    """Legacy/corrupt plan JSON cannot leak into graph routing state."""

    assert teacher_graph._plan_payload({"plan_json": "{"}) == {}
    payload = {"plan_json": '{"steps":[{"id":"s1","status":"pending"}]}' }
    parsed = teacher_graph._plan_payload(payload)
    assert parsed["steps"] == [{"id": "s1", "status": "pending"}]
