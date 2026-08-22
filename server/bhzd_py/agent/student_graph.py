"""Native LangGraph learner workflow.

Each node reloads durable business state from SQLite and writes only bounded
metadata to the LangGraph checkpoint.  This keeps replayable SSE and existing
tool/confirmation transactions authoritative while making the control flow a
real graph rather than a single callback.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..db import connect
from . import events, intents, media, prompts
from .graph_runtime import AgentGraphState


def _load(db_path: str, run_id: str):
    from . import orchestrator as service

    db = connect(db_path)
    run, conv, user = service._load_run_context(db, run_id)
    return db, run, conv, user, service


def _attachment(run) -> dict[str, Any] | None:
    try:
        value = json.loads(run["plan_json"] or "{}").get("attachment")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _meta(run) -> dict[str, Any]:
    try:
        value = json.loads(run["plan_json"] or "{}").get("graph")
    except json.JSONDecodeError:
        value = None
    return value if isinstance(value, dict) else {}


def _save_meta(db, run_id: str, meta: dict[str, Any]) -> None:
    row = db.execute("SELECT plan_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    try:
        payload = json.loads(row["plan_json"] or "{}") if row else {}
    except json.JSONDecodeError:
        payload = {}
    payload["graph"] = meta
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False, default=str), run_id),
    )
    db.commit()


def _has_event(db, run_id: str, event_type: str) -> bool:
    return db.execute(
        "SELECT 1 FROM agent_events WHERE run_id = ? AND event_type = ? LIMIT 1",
        (run_id, event_type),
    ).fetchone() is not None


def _media_tokens(attachment: dict[str, Any] | None) -> list[str]:
    if not attachment:
        return []
    rows = attachment.get("attachments")
    if isinstance(rows, list):
        return [
            item["attachment_token"]
            for item in rows
            if isinstance(item, dict) and isinstance(item.get("attachment_token"), str)
        ]
    token = attachment.get("attachment_token")
    return [token] if isinstance(token, str) else []


def _prepare(state: AgentGraphState) -> AgentGraphState:
    """Load and classify one run, choosing the next bounded graph branch."""

    db, run, conv, _user, service = _load(state["db_path"], state["run_id"])
    try:
        if run["status"] in service._RUN_TERMINAL:
            return {"route": "complete", "completed": True}
        if not _has_event(db, run["id"], events.RUN_STARTED):
            events.emit(
                db,
                run["id"],
                events.RUN_STARTED,
                {"run_id": run["id"], "conversation_id": run["conversation_id"]},
            )
        attachment = _attachment(run)
        intent, goal_text = service._resolve_initial_intent(db, run, conv, attachment)
        intent = service._apply_l3_task_preference(
            db,
            intent,
            user_id=run["user_id"],
            task_text=goal_text,
            current_text=run["input_text"],
        )
        needs_direct = (
            intent.kind in {intents.KIND_AGENT_IDENTITY, intents.KIND_CONVERSATION_RECALL}
            or intents.next_question(intent) is not None
            or (
                intent.kind == intents.KIND_DIAGNOSE_UPLOAD
                and not (attachment and attachment.get("diagnostic_token"))
            )
            or bool(_media_tokens(attachment))
        )
        intake_scope = intent.kind in service._INTAKE_KINDS or (
            intent.kind == intents.KIND_UNKNOWN
            and service._load_latest_intake(db, run) is not None
        )
        meta = {
            "intent_kind": intent.kind,
            "data_type": intent.data_type,
            "goal_text": goal_text,
            "needs_direct": needs_direct,
            "intake_scope": intake_scope,
        }
        _save_meta(db, run["id"], meta)
        if intake_scope and not service._is_task_revision(db, run):
            route = "intake"
        elif needs_direct:
            route = "direct"
        elif intent.kind == intents.KIND_RAG_QUESTION:
            route = "react"
        else:
            route = "plan"
        return {"route": route}
    finally:
        db.close()


async def _intake(state: AgentGraphState) -> AgentGraphState:
    """Run the bounded task clarification node and persist its safe outcome."""

    db, run, _conv, _user, service = _load(state["db_path"], state["run_id"])
    try:
        meta = _meta(run)
        outcome, requirement = await service._handle_task_intake(
            db, run, str(meta.get("goal_text") or run["input_text"])
        )
        if outcome == "completed":
            return {"route": "complete", "completed": True}
        meta["intake_ready"] = outcome == "ready"
        if isinstance(requirement, str) and requirement:
            meta["goal_text"] = requirement
        _save_meta(db, run["id"], meta)
        if outcome == "ready":
            return {"route": "plan"}
        # Provider-unavailable intake falls back to the same safe direct branch
        # as the former workflow; the next node decides whether to ask one slot.
        return {"route": "direct"}
    finally:
        db.close()


async def _direct(state: AgentGraphState) -> AgentGraphState:
    """Handle direct chat, identity/recall fallback, or one clarification turn."""

    db, run, conv, _user, service = _load(state["db_path"], state["run_id"])
    attachment = _attachment(run)
    tokens = _media_tokens(attachment)
    try:
        meta = _meta(run)
        intent, goal_text = service._resolve_initial_intent(db, run, conv, attachment)
        intent = service._apply_l3_task_preference(
            db,
            intent,
            user_id=run["user_id"],
            task_text=goal_text,
            current_text=run["input_text"],
        )
        if meta.get("intake_ready"):
            return {"route": "plan"}
        if meta.get("needs_direct"):
            media_rows = [
                item for token in tokens if (item := media.get(token, run["user_id"])) is not None
            ]
            try:
                if await service._complete_direct_chat(
                    db, run, run["conversation_id"], media_attachments=media_rows
                ):
                    return {"route": "complete", "completed": True}
            finally:
                for token in tokens:
                    media.discard(token, run["user_id"])
            if intent.kind == intents.KIND_AGENT_IDENTITY:
                await service._complete_identity_fallback(db, run)
                return {"route": "complete", "completed": True}
            if intent.kind == intents.KIND_CONVERSATION_RECALL:
                await service._emit_assistant_text(
                    db, run["id"], run["conversation_id"], prompts.CONVERSATION_RECALL_UNAVAILABLE
                )
                service._finalize_run(
                    db,
                    run["id"],
                    event_type=events.RUN_COMPLETED,
                    payload={"summary": prompts.CONVERSATION_RECALL_UNAVAILABLE},
                    status="completed",
                )
                return {"route": "complete", "completed": True}
        question = intents.next_question(intent)
        if question:
            service._emit_progress(
                db,
                run["id"],
                phase="synthesis",
                status="running",
                title="正在准备下一步问题",
            )
            service._persist_clarification(
                db, run["id"], intents.make_clarification(intent, goal_text), attachment
            )
            await service._emit_assistant_text(db, run["id"], run["conversation_id"], question)
            service._emit_progress(
                db,
                run["id"],
                phase="synthesis",
                status="completed",
                title="下一步问题已生成",
            )
            service._finalize_run(
                db,
                run["id"],
                event_type=events.RUN_COMPLETED,
                payload={"summary": question},
                status="completed",
            )
            return {"route": "complete", "completed": True}
        if intent.kind == intents.KIND_DIAGNOSE_UPLOAD and not (
            attachment and attachment.get("diagnostic_token")
        ):
            notice = "请先上传需要诊断的标注结果文件（支持 JSON / TextGrid / COCO / VOC），我会先做格式校验。"
            await service._emit_assistant_text(db, run["id"], run["conversation_id"], notice)
            service._finalize_run(
                db,
                run["id"],
                event_type=events.RUN_COMPLETED,
                payload={"summary": notice},
                status="completed",
            )
            return {"route": "complete", "completed": True}
        return {"route": "react" if intent.kind == intents.KIND_RAG_QUESTION else "plan"}
    finally:
        db.close()


async def _react(state: AgentGraphState) -> AgentGraphState:
    """Run the bounded read-only ReAct subgraph for knowledge questions."""

    from .readonly_react import run_readonly_react

    exploration = run_readonly_react(state["run_id"], state["db_path"])
    db, run, _conv, _user, _service = _load(state["db_path"], state["run_id"])
    try:
        meta = _meta(run)
        meta["react_steps"] = exploration.get("steps") or []
        meta["graphrag"] = exploration.get("fused") or {}
        if exploration.get("timed_out"):
            meta["react_timeout"] = True
        if exploration.get("error"):
            meta["react_error"] = exploration["error"]
        _save_meta(db, run["id"], meta)
    finally:
        db.close()
    return {"route": "plan"}


def _plan(state: AgentGraphState) -> AgentGraphState:
    """Create the durable deterministic plan after optional read-only exploration."""

    db, run, conv, _user, service = _load(state["db_path"], state["run_id"])
    try:
        attachment = _attachment(run)
        intent, goal_text = service._resolve_initial_intent(db, run, conv, attachment)
        intent = service._apply_l3_task_preference(
            db,
            intent,
            user_id=run["user_id"],
            task_text=goal_text,
            current_text=run["input_text"],
        )
        meta = _meta(run)
        # Intake stores the original request plus the user's clarifications in
        # graph metadata.  Prefer that assembled requirement for task drafting
        # so a short READY/follow-up reply cannot replace the learner's goal.
        goal_text = str(meta.get("goal_text") or goal_text)
        steps, task_draft_args = service._build_plan(
            intent, run, conv, attachment, goal_text=goal_text
        )
        react_steps = meta.get("react_steps")
        if intent.kind == intents.KIND_RAG_QUESTION and isinstance(react_steps, list):
            # Keep the existing public two-step RAG plan contract while the
            # internal exploration trace remains available in graph metadata.
            # ``rag.search`` is replayed through the durable tool-call boundary
            # so SSE, citations and fallback checks retain their old semantics.
            rag_step = next(
                (step for step in react_steps if step.get("tool") == "rag.search"),
                None,
            )
            if isinstance(rag_step, dict):
                rag_step = {**rag_step, "status": "pending", "tool_call_id": None}
            steps = [
                rag_step
                or {
                    "id": "s1",
                    "title": "召回相关资料",
                    "tool": "rag.search",
                    "args": {"query": goal_text, "filters": {"data_type": intent.data_type}},
                    "status": "pending",
                },
                {
                "id": "react-answer",
                "title": "基于证据生成回答",
                "tool": "rag.answer",
                "args": {"question": goal_text, "data_type": intent.data_type},
                "status": "pending",
                },
            ]
            task_draft_args = None
        service._persist_plan(db, run["id"], steps)
        meta.update({"intent_kind": intent.kind, "goal_text": goal_text, "task_draft_args": task_draft_args})
        _save_meta(db, run["id"], meta)
        service._emit_progress(
            db,
            run["id"],
            phase="planning",
            status="running",
            title="正在制定执行计划",
            detail="正在安排可验证的处理步骤",
        )
        service._emit_plan_updated(db, run["id"], steps)
        service._emit_progress(
            db,
            run["id"],
            phase="planning",
            status="completed",
            title="执行计划已生成",
            detail=f"已安排 {len(steps)} 个步骤",
        )
        service._update_run(db, run["id"], data_type=run["data_type"] or intent.data_type)
        if run["data_type"] or intent.data_type:
            db.execute(
                "UPDATE conversations SET data_type = ? WHERE id = ?",
                (run["data_type"] or intent.data_type, run["conversation_id"]),
            )
            db.commit()
        return {"route": "execute"}
    finally:
        db.close()


async def _execute(state: AgentGraphState) -> AgentGraphState:
    """Execute plan steps and interrupt only after a durable confirmation preview."""

    db, run, conv, user, service = _load(state["db_path"], state["run_id"])
    try:
        payload = json.loads(run["plan_json"] or "{}")
        steps = payload.get("steps") or []
        if not steps:
            service._fail_run(db, run["id"], service._GENERIC_ERROR)
            return {"route": "complete", "completed": True}
        start_index = 0
        if state.get("resumed"):
            service._update_run(db, run["id"], status="running")
            for index, step in enumerate(steps):
                if step.get("status") == "waiting":
                    step["status"] = "completed"
                if step.get("status") not in ("completed", "failed"):
                    start_index = index
                    break
            else:
                start_index = len(steps)
            service._persist_plan(db, run["id"], steps)
        finished = await service._run_steps(
            db, service.get_config(), user, run, conv, steps, start_index
        )
        if not finished:
            # pending_confirmations and agent_runs are already committed by the
            # write-gate helper before interrupting the graph.
            interrupt({"kind": "confirmation.required", "run_id": run["id"]})
            # LangGraph resumes here after the confirmation route applies the
            # write and invokes Command(resume=...).
            state = {**state, "resumed": True}
            return await _execute(state)
        service._emit_plan_updated(db, run["id"], steps)
        return {"route": "finalize"}
    finally:
        db.close()


async def _finalize(state: AgentGraphState) -> AgentGraphState:
    """Generate the final response and close the run through the existing safe projection."""

    db, run, conv, _user, service = _load(state["db_path"], state["run_id"])
    try:
        payload = json.loads(run["plan_json"] or "{}")
        steps = payload.get("steps") or []
        attachment = _attachment(run)
        intent, goal_text = service._resolve_initial_intent(db, run, conv, attachment)
        meta = _meta(run)
        await service._finalize(
            db,
            run,
            conv,
            intent,
            steps,
            goal_text=meta.get("goal_text") or goal_text,
            task_draft_args=meta.get("task_draft_args"),
            graphrag_evidence=meta.get("graphrag"),
        )
        return {"route": "complete", "completed": True}
    finally:
        db.close()


def _route(state: AgentGraphState) -> str:
    return state.get("route", "complete")


def build_student_graph():
    """Compile the learner graph definition; checkpointer is supplied at runtime."""

    graph = StateGraph(AgentGraphState)
    graph.add_node("prepare", _prepare)
    graph.add_node("intake", _intake)
    graph.add_node("direct", _direct)
    graph.add_node("react", _react)
    graph.add_node("plan", _plan)
    graph.add_node("execute", _execute)
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        _route,
        {"intake": "intake", "direct": "direct", "react": "react", "plan": "plan", "complete": END},
    )
    graph.add_conditional_edges(
        "intake",
        _route,
        {"direct": "direct", "plan": "plan", "complete": END},
    )
    graph.add_conditional_edges(
        "direct",
        _route,
        {"react": "react", "plan": "plan", "complete": END},
    )
    graph.add_edge("react", "plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges(
        "execute", _route, {"finalize": "finalize", "complete": END}
    )
    graph.add_edge("finalize", END)
    return graph
