"""Student-facing adapter for the bounded read-only exploration subgraph.

The durable student graph owns the run lifecycle; this adapter only translates
one run into an exploration context and projects the safe evidence trace back
into plan steps.  It deliberately does not expose provider prompts or write
tool arguments to the LangGraph checkpoint.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import get_config
from ..db import connect
from .exploration import ExplorationContext, run_exploration


def _attachment(run) -> dict[str, Any] | None:
    """Read the request envelope without treating malformed JSON as fatal."""

    try:
        payload = json.loads(run["plan_json"] or "{}")
    except json.JSONDecodeError:
        return None
    value = payload.get("attachment") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else None


def run_readonly_react(run_id: str, db_path: str) -> dict[str, Any]:
    """Run bounded RAG/graph/course exploration for one owned student run."""

    db = connect(db_path)
    try:
        run = db.execute(
            "SELECT * FROM agent_runs WHERE id = ? AND agent_scope = 'student'",
            (run_id,),
        ).fetchone()
        if run is None:
            raise KeyError(f"student run does not exist: {run_id}")
        conversation = db.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (run["conversation_id"], run["user_id"]),
        ).fetchone()
        user = db.execute("SELECT * FROM users WHERE id = ?", (run["user_id"],)).fetchone()
        if conversation is None or user is None:
            raise KeyError(f"student run has an invalid workspace: {run_id}")
        query = str(run["input_text"] or "").strip()
        data_type = run["data_type"]
        context = ExplorationContext(
            db=db,
            config=get_config(),
            user_row=user,
            run_row=run,
            conversation_row=conversation,
        )
        # This adapter is called from the parent async graph.  The exploration
        # module still exposes a native StateGraph for standalone callers, but
        # nested sync execution must avoid inheriting the parent's checkpointer.
        result = run_exploration(query, context, use_graph=False)
        # Keep only a bounded, typed projection for the parent graph.  The
        # fused payload is persisted in business plan metadata by student_graph.
        steps: list[dict[str, Any]] = []
        for index, item in enumerate(result.get("steps") or [], start=1):
            tool = item.get("tool") if isinstance(item, dict) else None
            if not isinstance(tool, str):
                continue
            args: dict[str, Any]
            if tool == "rag.search":
                args = {"query": query, "filters": {"data_type": data_type}}
                title = "召回相关资料"
            elif tool == "graph.reason":
                args = {"action": "locate", "query": query, "limit": 8}
                title = "定位相关能力"
            elif tool == "course.search":
                args = {"query": query, "data_type": data_type}
                title = "检索教学单元"
            else:
                continue
            steps.append(
                {
                    "id": f"react-{index}",
                    "title": title,
                    "tool": tool,
                    "args": args,
                    "status": "completed" if item.get("status") == "completed" else "failed",
                }
            )
        return {
            "steps": steps,
            "fused": result.get("fused") or {},
            "timed_out": bool(result.get("timed_out")),
            "error": result.get("error"),
        }
    finally:
        db.close()


__all__ = ["run_readonly_react"]
