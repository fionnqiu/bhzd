"""Durable orchestration for the class-scoped teacher Agent.

This intentionally does not call the learner ``orchestrator``.  Its planning
rules and tool registry include student-oriented operations, while the teacher
workspace needs a much smaller capability surface and an aggregate-only model
payload.  Events use the shared durable SSE protocol so reconnect behavior is
consistent across both portals.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import connect, utc_now_iso
from ..tools import teacher_agent_tools
from . import composer, events, media, teacher_prompts

logger = logging.getLogger(__name__)

_RUN_TERMINAL = ("completed", "failed", "cancelled")
_MESSAGE_CHUNK = 40
_GENERIC_ERROR = "处理本次教学助手请求时出现问题，请稍后重试"
_DRAFT_KEYWORDS = (
    "任务",
    "作业",
    "练习",
    "巩固",
    "制定",
    "生成",
    "安排",
    "draft",
    "task",
    "assignment",
)
_EMAIL_RE = re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)")
_LONG_ID_RE = re.compile(r"(?<!\d)\d{15,18}(?!\d)")


def _load_context(db: sqlite3.Connection, run_id: str) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
    """Load only a well-formed teacher run and its matching workspace."""

    run = db.execute(
        "SELECT * FROM agent_runs WHERE id = ? AND agent_scope = 'teacher'", (run_id,)
    ).fetchone()
    if run is None:
        raise KeyError(f"teacher run does not exist: {run_id}")
    conversation = db.execute(
        """
        SELECT * FROM conversations
        WHERE id = ? AND user_id = ? AND agent_scope = 'teacher'
          AND class_id = ? AND deleted_at IS NULL
        """,
        (run["conversation_id"], run["user_id"], run["class_id"]),
    ).fetchone()
    user = db.execute("SELECT * FROM users WHERE id = ?", (run["user_id"],)).fetchone()
    if conversation is None or user is None or not run["class_id"]:
        raise KeyError(f"teacher run has an invalid workspace: {run_id}")
    return run, conversation, user


def _request_envelope(
    run: sqlite3.Row,
) -> tuple[bool | None, list[str], str | None, dict[str, str] | None]:
    """Read the API-only request hints before the durable plan replaces them."""

    try:
        payload = json.loads(run["plan_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    request = payload.get("teacher_request") if isinstance(payload, dict) else None
    if not isinstance(request, dict):
        return None, [], None, None
    requested = request.get("request_draft")
    request_draft = requested if isinstance(requested, bool) else None
    cap_ids = request.get("target_cap_ids")
    if not isinstance(cap_ids, list):
        cap_ids = []
    data_type = request.get("data_type")
    attachment = request.get("attachment")
    normalized_attachment = (
        {"attachment_token": attachment["attachment_token"]}
        if isinstance(attachment, dict) and isinstance(attachment.get("attachment_token"), str)
        else None
    )
    return (
        request_draft,
        [str(value) for value in cap_ids if isinstance(value, str)][:3],
        data_type if isinstance(data_type, str) else None,
        normalized_attachment,
    )


def _wants_draft(input_text: str, requested: bool | None) -> bool:
    """Use an explicit UI choice when present, otherwise keep natural chat useful."""

    if requested is not None:
        return requested
    normalized = input_text.lower()
    return any(keyword in normalized for keyword in _DRAFT_KEYWORDS)


def _safe_goal_for_model(value: str) -> str:
    """Bound obvious identifiers in free text before any optional provider call.

    Student data never originates from this value, but teachers can accidentally
    paste contact details into a goal.  The tool payload never contains the
    original request, and this additional filter keeps the optional narrative
    call conservative as well.
    """

    compact = " ".join(value.split())[:600]
    compact = _EMAIL_RE.sub("[已省略]", compact)
    compact = _PHONE_RE.sub("[已省略]", compact)
    return _LONG_ID_RE.sub("[已省略]", compact)


def _insert_message(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    run_id: str | None,
    role: str,
    content: str,
    commit: bool = True,
) -> str:
    """Persist chat history without enrolling teacher workspaces in learner memory.

    Class analytics are time-sensitive and may change after a staffing update,
    so they must not be extracted into the user-wide L1-L3 private-memory
    store.  Durable conversation history remains available only behind this
    conversation's class ownership check.
    """

    message_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, conversation_id, run_id, role, content, utc_now_iso()),
    )
    if commit:
        db.commit()
    return message_id


def _insert_tool_call(
    db: sqlite3.Connection,
    *,
    run_id: str,
    tool_name: str,
    permission: str,
    args: dict[str, Any],
    status: str = "requested",
) -> str:
    """Persist only opaque scope metadata, never source learning records."""

    tool_call_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO tool_calls
          (id, run_id, tool_name, permission, status, args_json, is_write, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tool_call_id,
            run_id,
            tool_name,
            permission,
            status,
            json.dumps(args, ensure_ascii=False),
            1 if permission == "write" else 0,
            utc_now_iso(),
        ),
    )
    db.commit()
    return tool_call_id


def _public_steps(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project the durable plan into a payload that has no hidden arguments."""

    public: list[dict[str, str]] = []
    for step in steps:
        item = {
            "id": str(step["id"]),
            "title": str(step["title"])[:160],
            "status": str(step["status"]),
        }
        if isinstance(step.get("tool"), str):
            item["tool"] = step["tool"]
        if isinstance(step.get("tool_call_id"), str):
            item["tool_call_id"] = step["tool_call_id"]
        public.append(item)
    return public


def _persist_plan(
    db: sqlite3.Connection,
    *,
    run_id: str,
    steps: list[dict[str, Any]],
    request_draft: bool,
    target_cap_ids: list[str],
    data_type: str | None,
) -> None:
    """Keep enough opaque state for reload/confirmation without preserving raw goals."""

    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (
            json.dumps(
                {
                    "steps": steps,
                    "teacher_request": {
                        "request_draft": request_draft,
                        "target_cap_ids": target_cap_ids,
                        "data_type": data_type,
                    },
                },
                ensure_ascii=False,
            ),
            run_id,
        ),
    )
    db.commit()


def _update_plan_event(db: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]) -> None:
    events.emit(db, run_id, events.PLAN_UPDATED, {"steps": _public_steps(steps)})


async def _emit_deltas(
    db: sqlite3.Connection, run_id: str, text: str
) -> None:
    """Commit each chunk so a reconnecting SSE client can replay live text."""

    for offset in range(0, len(text), _MESSAGE_CHUNK):
        events.emit(
            db,
            run_id,
            events.MESSAGE_DELTA,
            {"delta": text[offset : offset + _MESSAGE_CHUNK]},
        )
        await asyncio.sleep(0)


def _finish_run(
    db: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    event_type: str,
    payload: dict[str, Any],
    error: str | None = None,
) -> None:
    """Commit terminal state and durable terminal event in one transaction."""

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE agent_runs SET status = ?, error = ?, completed_at = ? WHERE id = ?",
            (status, error, utc_now_iso(), run_id),
        )
        events.emit(db, run_id, event_type, payload, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _finish_waiting_for_confirmation(
    db: sqlite3.Connection,
    *,
    run_id: str,
    conversation_id: str,
    confirmation_id: str,
    preview: dict[str, Any],
    response_text: str,
) -> None:
    """Atomically expose the pending publish state and replayable event card."""

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE agent_runs SET status = 'waiting_confirmation' WHERE id = ?",
            (run_id,),
        )
        _insert_message(
            db,
            conversation_id=conversation_id,
            run_id=run_id,
            role="assistant",
            content=response_text,
            commit=False,
        )
        events.emit(
            db,
            run_id,
            events.CONFIRMATION_REQUIRED,
            {
                "confirmation": {
                    "id": confirmation_id,
                    "action_type": "teacher.task_publish",
                    "preview": preview,
                }
            },
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


async def _compose_response(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    insights: dict[str, Any],
    preview: dict[str, Any] | None,
    fallback: str,
    media_attachment: media.MediaAttachment | None = None,
) -> tuple[str, dict[str, Any] | None, bool]:
    """Stream a narrative generated from the aggregate-only provider payload.

    No tool result is passed through a generic composer helper because those
    helpers accept arbitrary tool JSON.  This explicit payload is the final
    defense that keeps class data aggregate-only even when a provider is used.
    """

    model_payload = {
        "teacher_goal": _safe_goal_for_model(run["input_text"]),
        "class_analytics": insights,
        "task_draft": preview.get("draft") if isinstance(preview, dict) else None,
        "constraints": "不得识别个体学生；草稿未保存或发布。",
    }
    user_text = "以下为经过脱敏的教学工作台数据，请给教师简洁的下一步建议：\n" + json.dumps(
        model_payload, ensure_ascii=False
    )
    user_content: str | list[dict[str, Any]] = user_text
    if media_attachment is not None:
        # Keep bytes request-local while letting multimodal-capable providers
        # inspect the teacher's image/audio/video context; unsupported adapters
        # receive their existing safe text fallback.
        user_content = composer.build_attachment_user_content(
            user_text,
            filename=media_attachment.filename,
            mime_type=media_attachment.mime_type,
            content=media_attachment.content,
            kind=media_attachment.kind,
            extracted_text=media_attachment.extracted_text,
        )
    messages = [
        {"role": "system", "content": teacher_prompts.TEACHER_AGENT_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    capture = composer.UsageCapture()
    chunks: list[str] = []
    streamed = False
    async for delta in composer.stream_text(messages, usage_capture=capture):
        if not delta:
            continue
        streamed = True
        chunks.append(delta)
        await _emit_deltas(db, run["id"], delta)
    text = composer.sanitize_model_text("".join(chunks)) if chunks else ""
    if not text:
        await _emit_deltas(db, run["id"], fallback)
        return fallback, capture.value, False
    return text, capture.value, streamed


def _record_usage(db: sqlite3.Connection, run_id: str, usage: dict[str, Any] | None) -> None:
    """Persist provider accounting only after its safe response is available."""

    if not usage:
        return
    persisted_usage = usage.get("usage")
    db.execute(
        "UPDATE agent_runs SET usage_json = ?, provider_id = ? WHERE id = ?",
        (
            json.dumps(persisted_usage, ensure_ascii=False, default=str)
            if persisted_usage is not None
            else None,
            usage.get("provider_id"),
            run_id,
        ),
    )
    db.commit()
    events.emit(
        db,
        run_id,
        events.RUN_USAGE,
        {"model": usage.get("model"), "usage": persisted_usage},
    )


async def _execute_insight_step(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    teacher_id: str,
    step: dict[str, Any],
) -> dict[str, Any]:
    """Run the aggregate-only read tool and publish a typed safe event."""

    tool_call_id = _insert_tool_call(
        db,
        run_id=run["id"],
        tool_name="teacher.class_insights",
        permission="read",
        args={"class_id": run["class_id"], "aggregate_only": True},
    )
    step["tool_call_id"] = tool_call_id
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_REQUESTED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.class_insights",
            "permission": "read",
            "execution_kind": "tool",
            "input_summary": "已校验班级权限，仅汇总匿名学习数据",
        },
    )
    insights = teacher_agent_tools.class_insights(
        db, teacher_id=teacher_id, class_id=run["class_id"]
    )
    db.execute(
        """
        UPDATE tool_calls
        SET status = 'completed', result_json = ?, duration_ms = 0, completed_at = ?
        WHERE id = ?
        """,
        (json.dumps(insights, ensure_ascii=False), utc_now_iso(), tool_call_id),
    )
    db.commit()
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_COMPLETED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.class_insights",
            "status": "completed",
            "duration_ms": 0,
            "is_write": 0,
            "execution_kind": "tool",
            "output_summary": "已生成班级匿名学习概览",
            "result": insights,
        },
    )
    step["status"] = "completed"
    return insights


async def _execute_preview_step(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    teacher_id: str,
    step: dict[str, Any],
    insights: dict[str, Any],
    target_cap_ids: list[str],
    data_type: str | None,
) -> dict[str, Any]:
    """Build an editable draft from already-safe aggregates and eligible sources."""

    tool_call_id = _insert_tool_call(
        db,
        run_id=run["id"],
        tool_name="teacher.task_draft_preview",
        permission="read",
        args={"class_id": run["class_id"], "target_cap_ids": target_cap_ids},
    )
    step["tool_call_id"] = tool_call_id
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_REQUESTED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.task_draft_preview",
            "permission": "read",
            "execution_kind": "tool",
            "input_summary": "根据班级匿名聚合数据生成可编辑草稿",
        },
    )
    preview = teacher_agent_tools.task_draft_preview(
        db,
        teacher_id=teacher_id,
        class_id=run["class_id"],
        insights=insights,
        requested_cap_ids=target_cap_ids,
        data_type=data_type,
    )
    db.execute(
        """
        UPDATE tool_calls
        SET status = 'completed', result_json = ?, duration_ms = 0, completed_at = ?
        WHERE id = ?
        """,
        (json.dumps(preview, ensure_ascii=False), utc_now_iso(), tool_call_id),
    )
    db.commit()
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_COMPLETED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.task_draft_preview",
            "status": "completed",
            "duration_ms": 0,
            "is_write": 0,
            "execution_kind": "tool",
            "output_summary": (
                "已生成可保存的任务草稿"
                if preview.get("ready_to_save")
                else "暂不能生成可保存的任务草稿"
            ),
            "result": preview,
        },
    )
    step["status"] = "completed"
    return preview


def _open_publish_confirmation(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    steps: list[dict[str, Any]],
    preview: dict[str, Any],
) -> tuple[str, str]:
    """Create the teacher publish gate; no template or student copy exists yet."""

    tool_call_id = _insert_tool_call(
        db,
        run_id=run["id"],
        tool_name="teacher.task_publish",
        permission="write",
        args={"class_id": run["class_id"], "publish_to": "active_class_students"},
        status="awaiting_confirmation",
    )
    steps.append(
        {
            "id": "s3",
            "title": "发布教师任务",
            "tool": "teacher.task_publish",
            "status": "waiting",
            "tool_call_id": tool_call_id,
        }
    )
    preview_payload = {
        "summary": f"将发布学习任务「{preview['draft']['title']}」",
        "class_id": run["class_id"],
        "draft": preview["draft"],
        "insights": preview["insights"],
        "notice": "确认后会为当前班级的在班学生创建任务并发送通知。",
    }
    confirmation_id = uuid.uuid4().hex
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    db.execute(
        """
        INSERT INTO pending_confirmations
          (id, run_id, user_id, tool_call_id, action_type, preview_json,
          status, expires_at, created_at)
        VALUES (?, ?, ?, ?, 'teacher.task_publish', ?, 'pending', ?, ?)
        """,
        (
            confirmation_id,
            run["id"],
            run["user_id"],
            tool_call_id,
            json.dumps(preview_payload, ensure_ascii=False),
            # Keep the standard write-preview lifetime while requiring a fresh
            # ownership check again when the teacher actually confirms.
            expires_at,
            utc_now_iso(),
        ),
    )
    db.commit()
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_REQUESTED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.task_publish",
            "permission": "write",
            "execution_kind": "tool",
            "input_summary": "将发布到当前班级，具体内容与影响范围请在预览中复核",
        },
    )
    events.emit(
        db,
        run["id"],
        events.TOOL_CALL_COMPLETED,
        {
            "tool_call_id": tool_call_id,
            "tool": "teacher.task_publish",
            "status": "awaiting_confirmation",
            "duration_ms": 0,
            "is_write": 1,
            "execution_kind": "tool",
            "output_summary": "等待教师确认，尚未创建学生任务",
        },
    )
    return confirmation_id, tool_call_id


async def execute_run(run_id: str, db_path: str) -> None:
    """Execute one durable teacher-Agent run outside the request event loop."""

    db = connect(db_path)
    media_token: str | None = None
    owner_id: str | None = None
    try:
        run, conversation, user = _load_context(db, run_id)
        owner_id = run["user_id"]
        if run["status"] in _RUN_TERMINAL:
            return
        events.emit(
            db,
            run_id,
            events.RUN_STARTED,
            {"run_id": run_id, "conversation_id": run["conversation_id"]},
        )
        requested_draft, target_cap_ids, data_type, attachment = _request_envelope(run)
        media_token = (
            attachment.get("attachment_token")
            if isinstance(attachment, dict)
            else None
        )
        media_attachment = media.get(media_token, run["user_id"]) if media_token else None
        wants_draft = _wants_draft(run["input_text"], requested_draft)
        steps = [
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
        _persist_plan(
            db,
            run_id=run_id,
            steps=steps,
            request_draft=wants_draft,
            target_cap_ids=target_cap_ids,
            data_type=data_type,
        )
        events.emit_progress(
            db,
            run_id,
            phase="planning",
            status="completed",
            title="已制定教师工作台计划",
            detail="仅使用当前班级的匿名聚合数据",
            activity_id=f"teacher-plan:{run_id}",
        )
        _update_plan_event(db, run_id, steps)

        insights = await _execute_insight_step(
            db, run=run, teacher_id=user["id"], step=steps[0]
        )
        _update_plan_event(db, run_id, steps)

        preview: dict[str, Any] | None = None
        if wants_draft:
            preview = await _execute_preview_step(
                db,
                run=run,
                teacher_id=user["id"],
                step=steps[1],
                insights=insights,
                target_cap_ids=target_cap_ids,
                data_type=data_type,
            )
            _update_plan_event(db, run_id, steps)

        if preview and preview.get("ready_to_save"):
            confirmation_id, _tool_call_id = _open_publish_confirmation(
                db, run=run, steps=steps, preview=preview
            )
            _persist_plan(
                db,
                run_id=run_id,
                steps=steps,
                request_draft=wants_draft,
                target_cap_ids=target_cap_ids,
                data_type=data_type,
            )
            _update_plan_event(db, run_id, steps)
            fallback = (
                f"已基于班级匿名聚合数据生成「{preview['draft']['title']}」任务。"
                "请复核内容后确认发布；确认后会发送给当前班级的在班学生。"
            )
            text, usage, _streamed = await _compose_response(
                db,
                run=run,
                insights=insights,
                preview=preview,
                fallback=fallback,
                media_attachment=media_attachment,
            )
            _record_usage(db, run_id, usage)
            _finish_waiting_for_confirmation(
                db,
                run_id=run_id,
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
            return

        fallback = (
            preview["reason"]
            if preview and isinstance(preview.get("reason"), str)
            else "已汇总当前班级的匿名学习数据，可根据薄弱能力继续生成针对性任务草稿。"
        )
        text, usage, _streamed = await _compose_response(
            db,
            run=run,
            insights=insights,
            preview=preview,
            fallback=fallback,
            media_attachment=media_attachment,
        )
        _record_usage(db, run_id, usage)
        _insert_message(
            db,
            conversation_id=conversation["id"],
            run_id=run_id,
            role="assistant",
            content=text,
        )
        _finish_run(
            db,
            run_id=run_id,
            status="completed",
            event_type=events.RUN_COMPLETED,
            payload={"summary": text[:240]},
        )
    except Exception:
        logger.exception("teacher Agent run %s failed", run_id)
        try:
            _finish_run(
                db,
                run_id=run_id,
                status="failed",
                event_type=events.RUN_FAILED,
                payload={"error": _GENERIC_ERROR},
                error=_GENERIC_ERROR,
            )
        except Exception:
            logger.exception("failed to persist terminal teacher Agent state for %s", run_id)
    finally:
        if media_token and owner_id:
            # Attachment tokens are one-run capabilities and must not survive
            # a completed, failed, or confirmation-waiting teacher run.
            media.discard(media_token, owner_id)
        db.close()
