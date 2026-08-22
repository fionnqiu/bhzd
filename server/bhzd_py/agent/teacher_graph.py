"""Native LangGraph workflow for the class-scoped teacher Agent.

Each node reloads the teacher workspace from SQLite and delegates only the
domain operation to ``teacher_orchestrator`` helpers.  The graph owns the
phase transitions and confirmation interrupt; the existing tables remain the
authoritative source for class ownership, tool calls and SSE replay.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..db import connect
from . import events


class TeacherGraphState(TypedDict, total=False):
    """Opaque coordinates and routing state persisted by the checkpointer."""

    run_id: str
    db_path: str
    route: str
    resumed: bool
    completed: bool


def _load(db_path: str, run_id: str):
    from . import teacher_orchestrator as service

    db = connect(db_path)
    run, conversation, user = service._load_context(db, run_id)
    return db, run, conversation, user, service


def _plan_payload(run) -> dict[str, Any]:
    try:
        payload = json.loads(run["plan_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _save_graph_meta(db, run_id: str, **updates: Any) -> dict[str, Any]:
    row = db.execute("SELECT plan_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    try:
        raw_payload = json.loads(row["plan_json"] or "{}") if row else {}
    except json.JSONDecodeError:
        raw_payload = {}
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    graph_value = payload.get("graph")
    graph: dict[str, Any] = graph_value if isinstance(graph_value, dict) else {}
    graph.update(updates)
    payload["graph"] = graph
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False, default=str), run_id),
    )
    db.commit()
    return graph


def _graph_meta(run) -> dict[str, Any]:
    payload = _plan_payload(run)
    graph = payload.get("graph")
    return graph if isinstance(graph, dict) else {}


def _step_result(db, step: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = step.get("tool_call_id")
    if not isinstance(tool_call_id, str):
        return {}
    row = db.execute(
        "SELECT result_json FROM tool_calls WHERE id = ?", (tool_call_id,)
    ).fetchone()
    if row is None:
        return {}
    try:
        value = json.loads(row["result_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _persist_plan_preserving_meta(
    db,
    *,
    run_id: str,
    steps: list[dict[str, Any]],
    request_draft: bool,
    target_cap_ids: list[str],
    data_type: str | None,
    meta: dict[str, Any],
    service,
) -> None:
    """Write the service plan while retaining graph-only continuation metadata.

    The shared business helper intentionally rewrites ``plan_json`` to its public
    teacher request shape.  Every graph node reloads that row, so dropping the
    metadata after the first node would lose attachment and routing context.
    Reapply the bounded metadata after the service write instead of storing
    business payloads in LangGraph state.
    """

    service._persist_plan(
        db,
        run_id=run_id,
        steps=steps,
        request_draft=request_draft,
        target_cap_ids=target_cap_ids,
        data_type=data_type,
    )
    _save_graph_meta(db, run_id, **meta)


def _latest_publish_confirmation(db, run_id: str):
    """Return the latest publish gate so interrupt re-entry is idempotent."""

    return db.execute(
        """
        SELECT * FROM pending_confirmations
        WHERE run_id = ? AND action_type = 'teacher.task_publish'
        ORDER BY rowid DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()


def _prepare(state: TeacherGraphState) -> TeacherGraphState:
    """Create the deterministic teacher plan and emit its replayable events."""

    db, run, _conversation, _user, service = _load(state["db_path"], state["run_id"])
    try:
        if run["status"] in service._RUN_TERMINAL or run["status"] == "waiting_confirmation":
            return {"route": "complete", "completed": True}
        if db.execute(
            "SELECT 1 FROM agent_events WHERE run_id = ? AND event_type = ? LIMIT 1",
            (run["id"], events.RUN_STARTED),
        ).fetchone() is None:
            events.emit(
                db,
                run["id"],
                events.RUN_STARTED,
                {"run_id": run["id"], "conversation_id": run["conversation_id"]},
            )
        requested_draft, target_cap_ids, data_type, attachment = service._request_envelope(run)
        wants_draft = service._wants_draft(run["input_text"], requested_draft)
        steps: list[dict[str, Any]] = [
            {
                "id": "s1",
                "title": "汇总班级学习数据",
                "tool": "teacher.class_insights",
                "status": "pending",
            }
        ]
        if wants_draft:
            steps.append(
                {
                    "id": "s2",
                    "title": "生成针对性任务草稿",
                    "tool": "teacher.task_draft_preview",
                    "status": "pending",
                }
            )
        media_token = attachment.get("attachment_token") if attachment else None
        _persist_plan_preserving_meta(
            db,
            run_id=run["id"],
            steps=steps,
            request_draft=wants_draft,
            target_cap_ids=target_cap_ids,
            data_type=data_type,
            meta={
                "wants_draft": wants_draft,
                "target_cap_ids": target_cap_ids,
                "data_type": data_type,
                "media_token": media_token,
            },
            service=service,
        )
        service.events.emit_progress(
            db,
            run["id"],
            phase="planning",
            status="completed",
            title="已制定教师工作台计划",
            detail="仅使用当前班级的匿名聚合数据",
            activity_id=f"teacher-plan:{run['id']}",
        )
        service._update_plan_event(db, run["id"], steps)
        return {"route": "insights"}
    finally:
        db.close()


async def _class_insights(state: TeacherGraphState) -> TeacherGraphState:
    """Run the aggregate-only class tool and persist its tool-call result."""

    db, run, _conversation, user, service = _load(state["db_path"], state["run_id"])
    try:
        payload = _plan_payload(run)
        steps = payload.get("steps") or []
        if not steps:
            return {"route": "complete", "completed": True}
        insights = _step_result(db, steps[0]) if steps[0].get("status") == "completed" else {}
        if not insights:
            insights = await service._execute_insight_step(
                db, run=run, teacher_id=user["id"], step=steps[0]
            )
        meta = _graph_meta(run)
        _persist_plan_preserving_meta(
            db,
            run_id=run["id"],
            steps=steps,
            request_draft=bool(meta.get("wants_draft")),
            target_cap_ids=list(meta.get("target_cap_ids") or []),
            data_type=meta.get("data_type"),
            meta=meta,
            service=service,
        )
        service._update_plan_event(db, run["id"], steps)
        _ = insights
        return {"route": "preview" if meta.get("wants_draft") else "finalize"}
    finally:
        db.close()


async def _draft_preview(state: TeacherGraphState) -> TeacherGraphState:
    """Build the editable draft from the already persisted aggregate result."""

    db, run, _conversation, user, service = _load(state["db_path"], state["run_id"])
    try:
        payload = _plan_payload(run)
        steps = payload.get("steps") or []
        if len(steps) < 2:
            return {"route": "finalize"}
        insights = _step_result(db, steps[0])
        meta = _graph_meta(run)
        preview = _step_result(db, steps[1]) if steps[1].get("status") == "completed" else {}
        if not preview:
            preview = await service._execute_preview_step(
                db,
                run=run,
                teacher_id=user["id"],
                step=steps[1],
                insights=insights,
                target_cap_ids=list(meta.get("target_cap_ids") or []),
                data_type=meta.get("data_type"),
            )
        _persist_plan_preserving_meta(
            db,
            run_id=run["id"],
            steps=steps,
            request_draft=True,
            target_cap_ids=list(meta.get("target_cap_ids") or []),
            data_type=meta.get("data_type"),
            meta=meta,
            service=service,
        )
        service._update_plan_event(db, run["id"], steps)
        return {"route": "publish" if preview.get("ready_to_save") else "finalize"}
    finally:
        db.close()


async def _publish_interrupt(state: TeacherGraphState) -> TeacherGraphState:
    """Open the teacher publish gate and suspend until its API confirmation."""

    db, run, conversation, _user, service = _load(state["db_path"], state["run_id"])
    media_token: str | None = None
    try:
        if run["status"] in service._RUN_TERMINAL:
            return {"route": "complete", "completed": True}
        payload = _plan_payload(run)
        steps = payload.get("steps") or []
        if not steps:
            return {"route": "finalize"}
        preview = _step_result(db, steps[1])
        if not preview.get("ready_to_save"):
            return {"route": "finalize"}
        meta = _graph_meta(run)
        media_token = meta.get("media_token") if isinstance(meta.get("media_token"), str) else None
        existing = _latest_publish_confirmation(db, run["id"])
        if existing is not None:
            # A first invocation has already committed the preview. Re-entering
            # this node after ``Command(resume=...)`` must never create a second
            # write gate for the same teacher run.
            if existing["status"] == "pending" and run["status"] == "waiting_confirmation":
                interrupt(
                    {
                        "kind": "confirmation.required",
                        "run_id": run["id"],
                        "confirmation_id": existing["id"],
                    }
                )
                return {"route": "complete", "completed": True}
            return {"route": "complete", "completed": True}

        confirmation_id, _tool_call_id = service._open_publish_confirmation(
            db, run=run, steps=steps, preview=preview
        )
        _persist_plan_preserving_meta(
            db,
            run_id=run["id"],
            steps=steps,
            request_draft=True,
            target_cap_ids=list(meta.get("target_cap_ids") or []),
            data_type=meta.get("data_type"),
            meta=meta,
            service=service,
        )
        service._update_plan_event(db, run["id"], steps)
        insights = preview.get("insights") if isinstance(preview.get("insights"), dict) else {}
        attachment = service.media.get(media_token, run["user_id"]) if media_token else None
        fallback = (
            f"已基于班级匿名聚合数据生成「{preview['draft']['title']}」任务。"
            "请复核内容后确认发布；确认后会发送给当前班级的在班学生。"
        )
        text, usage, _streamed = await service._compose_response(
            db,
            run=run,
            insights=insights,
            preview=preview,
            fallback=fallback,
            media_attachment=attachment,
        )
        service._record_usage(db, run["id"], usage)
        service._finish_waiting_for_confirmation(
            db,
            run_id=run["id"],
            conversation_id=conversation["id"],
            confirmation_id=confirmation_id,
            preview={
                "summary": f"将发布学习任务「{preview['draft']['title']}」",
                "class_id": run["class_id"],
                "draft": preview["draft"],
                "insights": preview["insights"],
                "notice": "确认后会为当前班级的在班学生创建任务并发送通知。",
            },
            response_text=text,
        )
        interrupt({"kind": "confirmation.required", "run_id": run["id"], "confirmation_id": confirmation_id})
        # Teacher confirmation routes settle the business run atomically.  A
        # resumed checkpoint therefore only needs to close the graph branch.
        latest = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run["id"],)).fetchone()
        return {
            "route": "complete" if latest and latest["status"] in service._RUN_TERMINAL else "publish",
            "completed": bool(latest and latest["status"] in service._RUN_TERMINAL),
        }
    finally:
        if media_token:
            service.media.discard(media_token, run["user_id"])
        db.close()


async def _finalize(state: TeacherGraphState) -> TeacherGraphState:
    """Compose a non-publish teacher response and close the run."""

    db, run, conversation, _user, service = _load(state["db_path"], state["run_id"])
    media_token: str | None = None
    try:
        if run["status"] in service._RUN_TERMINAL:
            return {"route": "complete", "completed": True}
        payload = _plan_payload(run)
        steps = payload.get("steps") or []
        meta = _graph_meta(run)
        media_token = meta.get("media_token") if isinstance(meta.get("media_token"), str) else None
        insights = _step_result(db, steps[0]) if steps else {}
        preview = _step_result(db, steps[1]) if len(steps) > 1 else None
        fallback = (
            preview.get("reason")
            if isinstance(preview, dict) and isinstance(preview.get("reason"), str)
            else "已汇总当前班级的匿名学习数据，可根据薄弱能力继续生成针对性任务草稿。"
        )
        attachment = service.media.get(media_token, run["user_id"]) if media_token else None
        text, usage, _streamed = await service._compose_response(
            db,
            run=run,
            insights=insights,
            preview=preview,
            fallback=fallback,
            media_attachment=attachment,
        )
        service._record_usage(db, run["id"], usage)
        service._insert_message(
            db,
            conversation_id=conversation["id"],
            run_id=run["id"],
            role="assistant",
            content=text,
        )
        service._finish_run(
            db,
            run_id=run["id"],
            status="completed",
            event_type=events.RUN_COMPLETED,
            payload={"summary": text[:240]},
        )
        return {"route": "complete", "completed": True}
    except Exception:
        service.logger.exception("teacher graph finalization failed for %s", run["id"])
        try:
            service._finish_run(
                db,
                run_id=run["id"],
                status="failed",
                event_type=events.RUN_FAILED,
                payload={"error": service._GENERIC_ERROR},
                error=service._GENERIC_ERROR,
            )
        finally:
            return {"route": "complete", "completed": True}
    finally:
        if media_token:
            service.media.discard(media_token, run["user_id"])
        db.close()


def _route(state: TeacherGraphState) -> str:
    return state.get("route", "complete")


def build_teacher_graph():
    """Build the teacher workflow with an explicit publish interrupt node."""

    graph = StateGraph(TeacherGraphState)
    graph.add_node("prepare", _prepare)
    graph.add_node("class_insights", _class_insights)
    graph.add_node("draft_preview", _draft_preview)
    graph.add_node("publish_interrupt", _publish_interrupt)
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", _route, {"insights": "class_insights", "complete": END})
    graph.add_conditional_edges(
        "class_insights",
        _route,
        {"preview": "draft_preview", "finalize": "finalize", "complete": END},
    )
    graph.add_conditional_edges(
        "draft_preview",
        _route,
        {"publish": "publish_interrupt", "finalize": "finalize", "complete": END},
    )
    graph.add_conditional_edges(
        "publish_interrupt",
        _route,
        {"complete": END, "publish": "publish_interrupt", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph


__all__ = ["TeacherGraphState", "build_teacher_graph"]
