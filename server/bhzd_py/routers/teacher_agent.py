"""Class-scoped teacher Agent API.

Teacher conversations live beside, rather than inside, the learner cockpit.
Every read and mutation checks both the durable owner/scope fields and the
current ``class_teachers`` relationship.  This double check is important: a
conversation can survive a class reassignment, but the former teacher must not
retain a replay or confirmation path to that class's aggregate learning data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent import events as agent_events
from ..agent import graph_runtime
from ..agent import media
from ..agent.confirmation_state import (
    CANCELLED,
    CLAIMED,
    EXPIRED,
    EXPIRED_NOTICE,
    cancel_pending_confirmation,
    claim_confirmation_tool,
    expire_pending_confirmation,
)
from ..agent.orchestrator import spawn
from ..agent.teacher_orchestrator import execute_run
from ..audit import audit
from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, require_role
from ..errors import ApiError
from ..tools import teacher_agent_tools
from . import teacher
from .runs import get_agent_db

router = APIRouter(prefix="/api/teacher/agent", tags=["teacher-agent"])
logger = logging.getLogger(__name__)

_RUN_TERMINAL = ("completed", "failed", "cancelled")
_SSE_POLL_SECONDS = 0.25
_SSE_HEARTBEAT_SECONDS = 15.0
_DRAFT_ACTION = "teacher.task_draft_save"
_PUBLISH_ACTION = "teacher.task_publish"
_CONFIRMATION_ACTIONS = (_DRAFT_ACTION, _PUBLISH_ACTION)
_CONFIRMATION_NOTICE = "教学任务已发布给当前班级的学生。"
_LEGACY_DRAFT_NOTICE = "教学任务草稿已保存，尚未向学生发布。"
_CANCELLED_NOTICE = "已取消草稿保存，未做任何修改。"


def require_teacher_csrf(
    current: CurrentUser = Depends(csrf_protect),
) -> CurrentUser:
    """Pair CSRF with the teacher role boundary for every state-changing call."""

    if current.user["role"] not in teacher.TEACHER_ROLES:
        raise ApiError(403, "FORBIDDEN", "需要教师或管理员权限")
    return current


def _conversation_dto(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "class_id": row["class_id"],
        "agent_scope": row["agent_scope"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _load_teacher_conversation(
    db: sqlite3.Connection, *, conversation_id: str, teacher_id: str
) -> sqlite3.Row:
    """Load one owned teacher workspace and revalidate its current class grant."""

    row = db.execute(
        """
        SELECT * FROM conversations
        WHERE id = ? AND user_id = ? AND agent_scope = 'teacher' AND deleted_at IS NULL
        """,
        (conversation_id, teacher_id),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "教师助手会话不存在")
    if not row["class_id"]:
        # A missing scope is an invalid server state, not an opportunity to
        # fall back to a user-wide query.
        raise ApiError(404, "NOT_FOUND", "教师助手会话不存在")
    teacher_agent_tools.assert_owned_teacher_class(
        db, teacher_id=teacher_id, class_id=row["class_id"]
    )
    return row


def _load_teacher_run(
    db: sqlite3.Connection, *, run_id: str, teacher_id: str
) -> tuple[sqlite3.Row, sqlite3.Row]:
    """Load a run only when its conversation and current class scope still match."""

    run = db.execute(
        """
        SELECT * FROM agent_runs
        WHERE id = ? AND user_id = ? AND agent_scope = 'teacher'
        """,
        (run_id, teacher_id),
    ).fetchone()
    if run is None or not run["class_id"]:
        raise ApiError(404, "NOT_FOUND", "教师助手运行不存在")
    conversation = _load_teacher_conversation(
        db, conversation_id=run["conversation_id"], teacher_id=teacher_id
    )
    if conversation["class_id"] != run["class_id"]:
        raise ApiError(404, "NOT_FOUND", "教师助手运行不存在")
    teacher_agent_tools.assert_owned_teacher_class(
        db, teacher_id=teacher_id, class_id=run["class_id"]
    )
    return run, conversation


def _load_teacher_confirmation(
    db: sqlite3.Connection, *, confirmation_id: str, teacher_id: str
) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
    """Resolve confirmation ownership through the same live class boundary."""

    confirmation = db.execute(
        "SELECT * FROM pending_confirmations WHERE id = ?", (confirmation_id,)
    ).fetchone()
    if (
        confirmation is None
        or confirmation["user_id"] != teacher_id
        or confirmation["action_type"] not in _CONFIRMATION_ACTIONS
    ):
        raise ApiError(404, "NOT_FOUND", "教师助手确认单不存在")
    run, conversation = _load_teacher_run(
        db, run_id=confirmation["run_id"], teacher_id=teacher_id
    )
    if confirmation["tool_call_id"] is None:
        raise ApiError(404, "NOT_FOUND", "教师助手确认单不存在")
    return confirmation, run, conversation


def _parse_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _insert_teacher_message(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    run_id: str,
    role: str = "user",
    content: str,
    commit: bool = True,
) -> None:
    """Persist teacher-workspace history without invoking learner memory hooks."""

    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, conversation_id, run_id, role, content, utc_now_iso()),
    )
    if commit:
        db.commit()


def _safe_plan(run: sqlite3.Row) -> dict[str, Any] | None:
    """Expose visible labels only; teacher goals and implementation state stay private."""

    raw = _parse_json(run["plan_json"], {})
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return None
    steps: list[dict[str, Any]] = []
    for item in raw["steps"]:
        if not isinstance(item, dict):
            continue
        step: dict[str, Any] = {}
        for key in ("id", "title", "status", "tool", "tool_call_id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                step[key] = value[:160]
        if step.get("id") and step.get("title"):
            steps.append(step)
    return {"steps": steps}


def _safe_insights(value: Any) -> dict[str, Any] | None:
    """Re-project aggregate results before returning durable tool history."""

    if not isinstance(value, dict):
        return None
    public: dict[str, Any] = {}
    for key in (
        "class_id",
        "student_count",
        "mastery_record_count",
        "assigned_task_count",
        "completed_task_count",
        "submitted_task_count",
        "completion_rate",
        "sample_warning",
    ):
        if key in value:
            public[key] = value[key]
    weak = value.get("weak_capabilities")
    if isinstance(weak, list):
        public["weak_capabilities"] = [
            {
                key: item[key]
                for key in ("cap_id", "cap_name", "avg_score", "affected_student_count")
                if key in item
            }
            for item in weak[:5]
            if isinstance(item, dict)
        ]
    return public


def _safe_draft(value: Any) -> dict[str, Any] | None:
    """Keep preview/history cards limited to the editable task draft shape."""

    if not isinstance(value, dict):
        return None
    public: dict[str, Any] = {}
    for key in ("ready_to_save", "class_id", "reason", "notice"):
        if key in value:
            public[key] = value[key]
    draft = value.get("draft")
    if isinstance(draft, dict):
        public["draft"] = {
            key: draft[key]
            # Only the four authored task fields are safe to expose in a
            # replay card. Routing metadata stays in the durable payload for
            # server-side validation but is never rendered as task content.
            for key in ("title", "description", "knowledge_points", "exercises")
            if key in draft
        }
    snapshot = _safe_insights(value.get("insights"))
    if snapshot is not None:
        public["insights"] = snapshot
    return public


def _safe_tool_result(tool_name: str, raw: str | None) -> dict[str, Any] | None:
    value = _parse_json(raw, None)
    if tool_name == "teacher.class_insights":
        return _safe_insights(value)
    if tool_name == "teacher.task_draft_preview":
        return _safe_draft(value)
    if tool_name in _CONFIRMATION_ACTIONS and isinstance(value, dict):
        return {
            key: value[key]
            for key in ("saved", "task_id", "title", "class_id", "published", "publish_required")
            if key in value
        }
    return None


def _confirmation_preview(row: sqlite3.Row) -> dict[str, Any] | None:
    """Return only the safe draft card stored behind the confirmation gate."""

    payload = _parse_json(row["preview_json"], {})
    if not isinstance(payload, dict):
        return None
    safe = {
        key: payload[key]
        for key in ("summary", "class_id", "notice")
        if key in payload
    }
    draft = payload.get("draft")
    if isinstance(draft, dict):
        safe["draft"] = {
            key: draft[key]
            for key in ("title", "description", "knowledge_points", "exercises")
            if key in draft
        }
    insights = _safe_insights(payload.get("insights"))
    if insights is not None:
        safe["insights"] = insights
    return safe


class TeacherConversationCreate(BaseModel):
    class_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=120)


class TeacherRunCreate(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    class_id: str | None = Field(default=None, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)
    request_draft: bool | None = None
    target_cap_ids: list[str] = Field(default_factory=list, max_length=3)
    data_type: str | None = Field(default=None, max_length=20)
    # The durable row stores only this owner-scoped token; media bytes remain
    # in the bounded in-process cache until the current run composes a reply.
    attachment: dict[str, Any] | None = None


class TeacherAgentDraftEdit(BaseModel):
    """Editable task fields; publication scope remains outside the task body."""

    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1200)
    knowledge_points: list[dict[str, Any]] | None = Field(default=None, max_length=10)
    exercises: list[dict[str, Any]] | None = Field(default=None, max_length=20)


class TeacherConfirmationBody(BaseModel):
    draft: TeacherAgentDraftEdit | None = None


class _EmptyBody(BaseModel):
    """Mutations with no additional payload still require an explicit body."""


def _validate_teacher_attachment(
    attachment: dict[str, Any] | None, user_id: str
) -> dict[str, str] | None:
    """Accept only a live owner-scoped media token for teacher Agent runs."""

    if not attachment:
        return None
    token = attachment.get("attachment_token")
    if not isinstance(token, str) or not token or media.get(token, user_id) is None:
        raise ApiError(403, "FORBIDDEN", "附件不属于当前账号或已过期")
    return {"attachment_token": token}


@router.get("/conversations")
def list_conversations(
    class_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentUser = Depends(require_role(*teacher.TEACHER_ROLES)),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """List only workspaces for classes currently assigned to this teacher."""

    if class_id:
        teacher_agent_tools.assert_owned_teacher_class(
            db, teacher_id=current.user["id"], class_id=class_id
        )
    clauses = [
        "c.user_id = ?",
        "c.agent_scope = 'teacher'",
        "c.deleted_at IS NULL",
        "ct.teacher_id = ?",
    ]
    params: list[Any] = [current.user["id"], current.user["id"]]
    if class_id:
        clauses.append("c.class_id = ?")
        params.append(class_id)
    where = " AND ".join(clauses)
    total = db.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM conversations c
        JOIN class_teachers ct ON ct.class_id = c.class_id
        WHERE {where}
        """,
        params,
    ).fetchone()["count"]
    rows = db.execute(
        f"""
        SELECT c.*
        FROM conversations c
        JOIN class_teachers ct ON ct.class_id = c.class_id
        WHERE {where}
        ORDER BY c.updated_at DESC, c.rowid DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {"items": [_conversation_dto(row) for row in rows], "total": total}


@router.post("/conversations", status_code=201)
def create_conversation(
    body: TeacherConversationCreate,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    teacher_agent_tools.assert_owned_teacher_class(
        db, teacher_id=current.user["id"], class_id=body.class_id
    )
    conversation_id = uuid.uuid4().hex
    now = utc_now_iso()
    title = body.title.strip() if body.title and body.title.strip() else "新的教学助手会话"
    db.execute(
        """
        INSERT INTO conversations
          (id, user_id, title, created_at, updated_at, agent_scope, class_id)
        VALUES (?, ?, ?, ?, ?, 'teacher', ?)
        """,
        (conversation_id, current.user["id"], title, now, now, body.class_id),
    )
    db.commit()
    row = _load_teacher_conversation(
        db, conversation_id=conversation_id, teacher_id=current.user["id"]
    )
    return _conversation_dto(row)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current: CurrentUser = Depends(require_role(*teacher.TEACHER_ROLES)),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    conversation = _load_teacher_conversation(
        db, conversation_id=conversation_id, teacher_id=current.user["id"]
    )
    messages = db.execute(
        """
        SELECT id, run_id, role, content, created_at
        FROM messages
        WHERE conversation_id = ? AND role IN ('user', 'assistant', 'system')
        ORDER BY created_at ASC, rowid ASC
        """,
        (conversation_id,),
    ).fetchall()
    runs = db.execute(
        """
        SELECT id, status, created_at, completed_at
        FROM agent_runs
        WHERE conversation_id = ? AND user_id = ? AND agent_scope = 'teacher' AND class_id = ?
        ORDER BY created_at ASC, rowid ASC
        """,
        (conversation_id, current.user["id"], conversation["class_id"]),
    ).fetchall()
    return {
        "conversation": _conversation_dto(conversation),
        "messages": [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in messages
        ],
        "runs": [dict(row) for row in runs],
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    conversation = _load_teacher_conversation(
        db, conversation_id=conversation_id, teacher_id=current.user["id"]
    )
    now = utc_now_iso()
    db.execute(
        "UPDATE conversations SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (now, now, conversation_id),
    )
    db.commit()
    audit(
        db,
        current.user,
        "teacher_agent.conversation_delete",
        target_type="conversation",
        target_id=conversation_id,
        after={"class_id": conversation["class_id"]},
    )
    return {"deleted": True}


@router.get("/classes/{class_id}/insights")
def get_class_insights(
    class_id: str,
    current: CurrentUser = Depends(require_role(*teacher.TEACHER_ROLES)),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Expose the same aggregate-only snapshot used by the Agent tools."""

    return teacher_agent_tools.class_insights(
        db, teacher_id=current.user["id"], class_id=class_id
    )


@router.post("/attachments", status_code=201)
def upload_teacher_agent_attachment(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_teacher_csrf),
) -> dict[str, Any]:
    """Store one teacher-owned allow-listed file for the next Agent run only."""

    content = file.file.read(media.MAX_MEDIA_BYTES + 1)
    try:
        item = media.store(
            current.user["id"],
            file.filename or "upload",
            file.content_type or "",
            content,
        )
    except ValueError as exc:
        if str(exc) == "media_too_large":
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "文件不能超过 20MB") from exc
        if str(exc) == "pdf_ocr_page_limit":
            raise ApiError(422, "PDF_OCR_PAGE_LIMIT", "扫描 PDF 最多支持 12 页，请拆分后重新上传") from exc
        if str(exc) == "pdf_ocr_no_text":
            raise ApiError(
                422,
                "PDF_OCR_NO_TEXT",
                "PDF 未识别到可读取文字，请上传更清晰的扫描件或文字版 PDF",
            ) from exc
        if str(exc) == "pdf_ocr_failed":
            raise ApiError(422, "PDF_OCR_FAILED", "PDF OCR 处理失败，请稍后重试") from exc
        if str(exc) == "document_parse_failed":
            raise ApiError(422, "DOCUMENT_PARSE_FAILED", "文件无法解析为可读取文本") from exc
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "不支持该文件类型") from exc
    return {
        "attachment_token": item.token,
        "name": item.filename,
        "mime_type": item.mime_type,
        "kind": item.kind,
        "size": item.size,
        "expires_at": item.expires_at,
    }


@router.post("/runs", status_code=202)
def create_run(
    body: TeacherRunCreate,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Persist an input before scheduling durable background orchestration."""

    now = utc_now_iso()
    normalized_attachment = _validate_teacher_attachment(body.attachment, current.user["id"])
    if body.data_type is not None and body.data_type not in ("text", "image", "audio", "video"):
        raise ApiError(400, "VALIDATION_ERROR", "数据类型仅支持 text / image / audio / video")
    # Convert the natural-language goal into known, non-identifying scope
    # fields.  Only these categories enter tool arguments or draft assembly.
    from ..agent import intents

    detected = intents.detect(body.input)
    data_type = body.data_type or detected.data_type
    if body.conversation_id:
        conversation = _load_teacher_conversation(
            db, conversation_id=body.conversation_id, teacher_id=current.user["id"]
        )
        if body.class_id and body.class_id != conversation["class_id"]:
            raise ApiError(400, "CLASS_SCOPE_MISMATCH", "会话已绑定其他班级，不能切换班级范围")
    else:
        if not body.class_id:
            raise ApiError(400, "CLASS_REQUIRED", "新建教师助手运行必须选择班级")
        teacher_agent_tools.assert_owned_teacher_class(
            db, teacher_id=current.user["id"], class_id=body.class_id
        )
        conversation_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO conversations
              (id, user_id, title, created_at, updated_at, agent_scope, class_id)
            VALUES (?, ?, ?, ?, ?, 'teacher', ?)
            """,
            (
                conversation_id,
                current.user["id"],
                body.input.strip()[:30] or "新的教学助手会话",
                now,
                now,
                body.class_id,
            ),
        )
        db.commit()
        conversation = _load_teacher_conversation(
            db, conversation_id=conversation_id, teacher_id=current.user["id"]
        )

    # Ownership is repeated after creating/loading the workspace so a stale UI
    # cannot enqueue work for a class that was reassigned during the request.
    teacher_agent_tools.assert_owned_teacher_class(
        db, teacher_id=current.user["id"], class_id=conversation["class_id"]
    )
    run_id = uuid.uuid4().hex
    request_envelope = {
        "teacher_request": {
            "request_draft": body.request_draft,
            "target_cap_ids": list(dict.fromkeys(body.target_cap_ids))[:3],
            "data_type": data_type,
            "attachment": normalized_attachment,
        }
    }
    db.execute(
        """
        INSERT INTO agent_runs
          (id, conversation_id, user_id, status, input_text, plan_json, data_type, created_at,
           agent_scope, class_id)
        VALUES (?, ?, ?, 'running', ?, ?, ?, ?, 'teacher', ?)
        """,
        (
            run_id,
            conversation["id"],
            current.user["id"],
            body.input.strip(),
            json.dumps(request_envelope, ensure_ascii=False),
            data_type,
            now,
            conversation["class_id"],
        ),
    )
    _insert_teacher_message(
        db,
        conversation_id=conversation["id"],
        run_id=run_id,
        role="user",
        content=body.input.strip(),
        commit=False,
    )
    db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation["id"]),
    )
    db.commit()
    spawn(execute_run(run_id, get_config().resolved_database_path))
    return {"run_id": run_id, "conversation_id": conversation["id"], "class_id": conversation["class_id"]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    current: CurrentUser = Depends(require_role(*teacher.TEACHER_ROLES)),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    run, _conversation = _load_teacher_run(db, run_id=run_id, teacher_id=current.user["id"])
    tool_rows = db.execute(
        """
        SELECT id, tool_name, permission, status, result_json, duration_ms, is_write, created_at, completed_at
        FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC, rowid ASC
        """,
        (run_id,),
    ).fetchall()
    confirmation_rows = db.execute(
        """
        SELECT id, tool_call_id, action_type, preview_json, status, expires_at, created_at
        FROM pending_confirmations WHERE run_id = ? ORDER BY created_at ASC, rowid ASC
        """,
        (run_id,),
    ).fetchall()
    message = db.execute(
        """
        SELECT id, run_id, role, content, created_at
        FROM messages WHERE run_id = ? AND role = 'assistant'
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    return {
        "run": {
            "id": run["id"],
            "conversation_id": run["conversation_id"],
            "class_id": run["class_id"],
            "status": run["status"],
            "input_text": run["input_text"],
            "data_type": run["data_type"],
            "error": run["error"],
            "created_at": run["created_at"],
            "completed_at": run["completed_at"],
        },
        "plan": _safe_plan(run),
        "assistant_message": (
            {
                "id": message["id"],
                "run_id": message["run_id"],
                "role": message["role"],
                "content": message["content"],
                "created_at": message["created_at"],
            }
            if message is not None
            else None
        ),
        "tool_calls": [
            {
                "id": row["id"],
                "tool": row["tool_name"],
                "permission": row["permission"],
                "status": row["status"],
                "duration_ms": row["duration_ms"],
                "is_write": bool(row["is_write"]),
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
                "result": _safe_tool_result(row["tool_name"], row["result_json"]),
            }
            for row in tool_rows
        ],
        "confirmations": [
            {
                "id": row["id"],
                "tool_call_id": row["tool_call_id"],
                "action_type": row["action_type"],
                "preview": _confirmation_preview(row),
                "status": row["status"],
                "expires_at": row["expires_at"],
                "created_at": row["created_at"],
            }
            for row in confirmation_rows
        ],
    }


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    current: CurrentUser = Depends(require_role(*teacher.TEACHER_ROLES)),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> StreamingResponse:
    run, _conversation = _load_teacher_run(db, run_id=run_id, teacher_id=current.user["id"])
    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        after_seq = max(after_seq, int(last_event_id))
    db_path = get_config().resolved_database_path
    class_id = run["class_id"]
    teacher_id = current.user["id"]

    async def generate() -> AsyncIterator[str]:
        # A stream lives after the request dependency closes, so it owns a
        # separate connection and repeats the class grant check before every
        # replay poll.  Revocation therefore stops a long-lived SSE stream too.
        stream_db = db_connect(db_path)
        cursor_seq = after_seq
        last_beat = time.monotonic()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    teacher_agent_tools.assert_owned_teacher_class(
                        stream_db, teacher_id=teacher_id, class_id=class_id
                    )
                except ApiError:
                    break
                rows = agent_events.list_events(stream_db, run_id, cursor_seq)
                for row in rows:
                    cursor_seq = int(row["seq"])
                    payload = _parse_json(row["payload_json"], {})
                    frame_data = json.dumps(
                        {"seq": cursor_seq, **(payload if isinstance(payload, dict) else {})},
                        ensure_ascii=False,
                    )
                    yield f"id: {cursor_seq}\nevent: {row['event_type']}\ndata: {frame_data}\n\n"
                    last_beat = time.monotonic()
                state = stream_db.execute(
                    "SELECT status FROM agent_runs WHERE id = ? AND agent_scope = 'teacher'",
                    (run_id,),
                ).fetchone()
                if state is None or (state["status"] in _RUN_TERMINAL and not rows):
                    yield f"event: {agent_events.STREAM_END}\ndata: {{}}\n\n"
                    break
                if time.monotonic() - last_beat >= _SSE_HEARTBEAT_SECONDS:
                    yield ": heartbeat\n\n"
                    last_beat = time.monotonic()
                await asyncio.sleep(_SSE_POLL_SECONDS)
        finally:
            stream_db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _confirmation_pending_or_raise(row: sqlite3.Row) -> None:
    if row["status"] != "pending":
        raise ApiError(409, "CONFIRMATION_NOT_PENDING", "该确认单已被处理，请刷新页面")


def _expire_or_raise(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    if expire_pending_confirmation(db, row):
        raise ApiError(410, "CONFIRMATION_EXPIRED", EXPIRED_NOTICE)
    latest = db.execute(
        "SELECT status FROM pending_confirmations WHERE id = ?", (row["id"],)
    ).fetchone()
    if latest is not None and latest["status"] == "expired":
        raise ApiError(410, "CONFIRMATION_EXPIRED", EXPIRED_NOTICE)
    raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")


def _draft_from_confirmation(row: sqlite3.Row) -> dict[str, Any]:
    payload = _parse_json(row["preview_json"], {})
    draft = payload.get("draft") if isinstance(payload, dict) else None
    if not isinstance(draft, dict):
        raise ApiError(500, "INTERNAL_ERROR", "草稿预览数据异常，请重新生成")
    return dict(draft)


def _merge_draft(base: dict[str, Any], edit: TeacherAgentDraftEdit | None) -> dict[str, Any]:
    """Apply only whitelisted editor fields; class and publish controls are immutable."""

    if edit is None:
        return base
    merged = dict(base)
    for key in ("title", "description", "knowledge_points", "exercises"):
        value = getattr(edit, key)
        if value is not None:
            merged[key] = value
    return merged


def _normalize_knowledge_points(raw: Any) -> list[dict[str, str]]:
    """Normalize authored lesson rows before they enter the durable content tables."""

    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if title and content:
            normalized.append({"title": title[:200], "content": content[:8000]})
    return normalized


def _normalize_exercises(raw: Any) -> list[dict[str, Any]]:
    """Normalize practice controls so stored types match the student renderer."""

    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    aliases = {
        "choice": "multiple_choice",
        "single_choice": "multiple_choice",
        "boolean": "true_false",
        "truefalse": "true_false",
        "true_false": "true_false",
    }
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        raw_kind = str(item.get("type") or "open_ended").strip().casefold().replace("-", "_")
        kind = aliases.get(raw_kind, raw_kind)
        if not question or kind not in {"open_ended", "multiple_choice", "true_false"}:
            continue
        options = [
            str(option).strip()
            for option in (item.get("options") or [])
            if str(option).strip()
        ]
        if kind == "true_false" and not options:
            options = ["正确", "错误"]
        normalized.append(
            {
                "question": question[:4000],
                "type": kind,
                "options": options if options else None,
                "reference_answer": str(item.get("reference_answer") or "").strip()[:4000],
            }
        )
    return normalized


def _normalize_draft_for_teacher_task(draft: dict[str, Any]) -> dict[str, Any]:
    """Build the active four-field task shape while ignoring legacy content."""

    normalized = dict(draft)
    # Pending confirmations created before this change can still be settled,
    # but their legacy task prose/rubrics must not be written into new rows.
    normalized["description"] = str(draft.get("description") or draft.get("goal") or "").strip()
    normalized["knowledge_points"] = _normalize_knowledge_points(draft.get("knowledge_points"))
    normalized["exercises"] = _normalize_exercises(draft.get("exercises"))
    normalized.pop("goal", None)
    normalized.pop("steps", None)
    normalized.pop("rubric", None)
    return normalized


def _validate_draft(db: sqlite3.Connection, draft: dict[str, Any]) -> None:
    """Validate the authored fields and keep routing metadata server-owned."""

    title = draft.get("title")
    description = draft.get("description")
    cap_ids = draft.get("cap_ids", [])
    points = draft.get("knowledge_points")
    exercises = draft.get("exercises")
    if (
        not isinstance(title, str)
        or not isinstance(description, str)
        or not isinstance(cap_ids, list)
        or not isinstance(points, list)
        or not isinstance(exercises, list)
    ):
        raise ApiError(400, "VALIDATION_ERROR", "草稿字段格式不正确")
    if len(cap_ids) > 3:
        raise ApiError(400, "VALIDATION_ERROR", "草稿关联的能力数量超出限制")
    if draft.get("data_type") is not None and draft["data_type"] not in ("text", "image", "audio", "video"):
        raise ApiError(400, "VALIDATION_ERROR", "数据类型仅支持 text / image / audio / video")
    for point in points:
        if not isinstance(point, dict) or not point.get("title") or not point.get("content"):
            raise ApiError(400, "VALIDATION_ERROR", "学习内容必须包含标题和正文")
    for exercise in exercises:
        if not isinstance(exercise, dict) or not exercise.get("question"):
            raise ApiError(400, "VALIDATION_ERROR", "练习题必须包含题干")
        if exercise.get("type") == "multiple_choice" and not exercise.get("options"):
            raise ApiError(400, "VALIDATION_ERROR", "选择题必须提供选项")
    teacher._check_task_body(title, cap_ids)


def _settle_waiting_step(
    db: sqlite3.Connection, *, run: sqlite3.Row, tool_call_id: str, status: str
) -> list[dict[str, Any]]:
    """Keep the persisted plan in sync with the confirmation terminal state."""

    if status not in {"completed", "failed"}:
        raise ValueError(f"unsupported teacher draft plan status: {status}")

    payload = _parse_json(run["plan_json"], {})
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
        return []
    for step in payload["steps"]:
        if isinstance(step, dict) and step.get("tool_call_id") == tool_call_id:
            step["status"] = status
            break
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), run["id"]),
    )
    return [
        {
            key: value
            for key, value in step.items()
            if key in ("id", "title", "status", "tool", "tool_call_id")
            and isinstance(value, str)
        }
        for step in payload["steps"]
        if isinstance(step, dict) and isinstance(step.get("id"), str) and isinstance(step.get("title"), str)
    ]


def _persist_draft_save_failure(
    db: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    confirmation: sqlite3.Row,
    tool_call: sqlite3.Row,
) -> None:
    """Converge a claimed save failure so SSE never leaves a run waiting forever."""

    db.rollback()
    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now_iso()
        tool_cursor = db.execute(
            """
            UPDATE tool_calls SET status = 'failed', completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'running'
            """,
            (now, tool_call["id"], run["id"]),
        )
        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations SET status = 'cancelled', resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, confirmation["id"]),
        )
        if tool_cursor.rowcount != 1 or confirmation_cursor.rowcount != 1:
            db.rollback()
            return
        plan_steps = _settle_waiting_step(
            db, run=run, tool_call_id=tool_call["id"], status="failed"
        )
        publish_requested = confirmation["action_type"] == _PUBLISH_ACTION
        failure_notice = "任务发布失败，请重新生成后再试" if publish_requested else "草稿保存失败，请重新生成后再试"
        db.execute(
            """
            UPDATE agent_runs SET status = 'failed', error = ?, completed_at = ?
            WHERE id = ? AND status = 'waiting_confirmation'
            """,
            (failure_notice, now, run["id"]),
        )
        _insert_teacher_message(
            db,
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            role="assistant",
            content=f"{failure_notice}，未做任何修改，请重新生成后再试。",
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": tool_call["id"],
                "tool": confirmation["action_type"],
                "status": "failed",
                "duration_ms": 0,
                "is_write": 1,
                "execution_kind": "tool",
                "output_summary": "任务发布失败，未创建学生任务" if publish_requested else "草稿保存失败，未执行发布",
            },
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.PLAN_UPDATED,
            {"steps": plan_steps},
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.RUN_FAILED,
            {"error": failure_notice},
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to converge a teacher Agent draft-save failure")


def _insert_teacher_draft(
    db: sqlite3.Connection,
    *,
    teacher_id: str,
    class_id: str,
    draft: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Persist a teacher-owned four-field draft and its authored lesson rows."""

    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    title = str(draft["title"]).strip()
    description = str(draft.get("description") or "").strip()
    db.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, goal, data_type, cap_ids_json, source,
           status, steps_json, resources_json, rubric_json, practice_json,
           counts_toward_mastery, teacher_id, class_id, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'teacher', 'draft', '[]', '[]', NULL, NULL, 1, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            teacher_id,
            title,
            description,
            draft.get("data_type"),
            json.dumps(draft.get("cap_ids") or [], ensure_ascii=False),
            teacher_id,
            class_id,
            teacher_id,
            now,
            now,
        ),
    )
    for index, point in enumerate(draft["knowledge_points"]):
        db.execute(
            "INSERT INTO task_knowledge_points "
            "(id, task_id, title, content, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                task_id,
                point["title"],
                point["content"],
                index,
                now,
                now,
            ),
        )
    for index, exercise in enumerate(draft["exercises"]):
        options = exercise.get("options")
        db.execute(
            "INSERT INTO task_exercises "
            "(id, task_id, question, type, options_json, reference_answer, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                task_id,
                exercise["question"],
                exercise["type"],
                json.dumps(options, ensure_ascii=False) if options else None,
                exercise.get("reference_answer") or None,
                index,
                now,
            ),
        )
    # Agent content is already reviewed in the confirmation card and is
    # written atomically with the task. Mark it terminal before fan-out so a
    # detached generator cannot replace this authored lesson after commit.
    db.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = ? WHERE id = ?",
        (now, task_id),
    )
    return task_id, {
        "id": task_id,
        "title": title,
        "description": description,
        "knowledge_points": draft["knowledge_points"],
        "exercises": draft["exercises"],
        "status": "draft",
        "class_id": class_id,
        "publish_required": True,
    }


@router.post("/confirmations/{confirmation_id}/confirm")
def confirm_task(
    confirmation_id: str,
    body: TeacherConfirmationBody | None = None,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """Confirm a reviewed Agent task and publish new confirmations atomically."""

    confirmation, run, _conversation = _load_teacher_confirmation(
        db, confirmation_id=confirmation_id, teacher_id=current.user["id"]
    )
    publish_requested = confirmation["action_type"] == _PUBLISH_ACTION
    _confirmation_pending_or_raise(confirmation)
    if confirmation["expires_at"] <= utc_now_iso():
        _expire_or_raise(db, confirmation)
    # Revalidation immediately before the state claim closes the final gap
    # between opening the preview and committing its teacher-owned draft.
    teacher_agent_tools.assert_owned_teacher_class(
        db, teacher_id=current.user["id"], class_id=run["class_id"]
    )
    tool_call = db.execute(
        "SELECT * FROM tool_calls WHERE id = ? AND run_id = ?",
        (confirmation["tool_call_id"], run["id"]),
    ).fetchone()
    if tool_call is None:
        raise ApiError(500, "INTERNAL_ERROR", "确认单数据异常，请重新生成草稿")
    # Validation happens before claiming the single-use write gate.  A teacher
    # can correct an invalid in-card edit and retry instead of leaving a
    # confirmation stuck in the transient ``running`` tool state.
    # Normalize before validation and the confirmation claim: retrying a
    # corrected card must keep the same publisher/scorer contract as a newly
    # generated card, while an invalid card remains safely retryable.
    draft = _normalize_draft_for_teacher_task(
        _merge_draft(_draft_from_confirmation(confirmation), body.draft if body else None)
    )
    _validate_draft(db, draft)
    claim = claim_confirmation_tool(db, confirmation)
    if claim == EXPIRED:
        _expire_or_raise(db, confirmation)
    if claim != CLAIMED:
        raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")

    try:
        db.execute("BEGIN IMMEDIATE")
        task_id, task = _insert_teacher_draft(
            db,
            teacher_id=current.user["id"],
            class_id=run["class_id"],
            draft=draft,
        )
        published = 0
        content_task_ids: list[str] = []
        if publish_requested:
            # The shared publisher owns fan-out and notifications. Keeping it
            # inside this transaction prevents an Agent confirmation from
            # settling without the matching student tasks.
            publish_result = teacher.publish_teacher_task_rows(
                db,
                task_id=task_id,
                teacher_id=current.user["id"],
                class_id=run["class_id"],
            )
            published = publish_result["published"]
            content_task_ids = publish_result.get("_content_task_ids", [])
        now = utc_now_iso()
        confirmation_cursor = db.execute(
            """
            UPDATE pending_confirmations
            SET status = 'confirmed', resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, confirmation["id"]),
        )
        tool_cursor = db.execute(
            """
            UPDATE tool_calls
            SET status = 'completed', result_json = ?, duration_ms = 0, completed_at = ?
            WHERE id = ? AND run_id = ? AND status = 'running'
            """,
            (
                json.dumps(
                    {
                        "saved": True,
                        "task_id": task_id,
                        "title": task["title"],
                        "class_id": run["class_id"],
                        "published": published,
                        "publish_required": not publish_requested,
                    },
                    ensure_ascii=False,
                ),
                now,
                tool_call["id"],
                run["id"],
            ),
        )
        if confirmation_cursor.rowcount != 1 or tool_cursor.rowcount != 1:
            db.rollback()
            raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")
        plan_steps = _settle_waiting_step(
            db, run=run, tool_call_id=tool_call["id"], status="completed"
        )
        db.execute(
            "UPDATE agent_runs SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, run["id"]),
        )
        _insert_teacher_message(
            db,
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            role="assistant",
            content=_CONFIRMATION_NOTICE if publish_requested else _LEGACY_DRAFT_NOTICE,
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": tool_call["id"],
                "tool": confirmation["action_type"],
                "status": "completed",
                "duration_ms": 0,
                "is_write": 1,
                "execution_kind": "tool",
                "output_summary": (
                    f"教师任务已发布给 {published} 名学生"
                    if publish_requested
                    else "教师任务草稿已保存，尚未发布"
                ),
                "result": {
                    "saved": True,
                    "task_id": task_id,
                    "published": published,
                    "publish_required": not publish_requested,
                },
            },
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.PLAN_UPDATED,
            {"steps": plan_steps},
            commit=False,
        )
        agent_events.emit(
            db,
            run["id"],
            agent_events.RUN_COMPLETED,
            {"summary": _CONFIRMATION_NOTICE if publish_requested else _LEGACY_DRAFT_NOTICE},
            commit=False,
        )
        db.commit()
        # The source task already owns reviewed content and is terminal. Only
        # published student copies need a post-commit worker, which reuses the
        # source rows instead of generating a different lesson per student.
        if content_task_ids:
            from ..tools.task_tools import queue_task_content

            for generated_task_id in content_task_ids:
                queue_task_content(db, generated_task_id)
        # Wake the interrupted LangGraph thread after the business confirmation
        # transaction settles the run.  The graph sees the terminal business
        # status and exits without creating a second confirmation.
        spawn(graph_runtime.resume_teacher_graph(run["id"], get_config().resolved_database_path))
    except ApiError:
        raise
    except Exception:
        logger.exception("teacher Agent task confirmation failed after confirmation claim")
        _persist_draft_save_failure(
            db, run=run, confirmation=confirmation, tool_call=tool_call
        )
        raise ApiError(500, "INTERNAL_ERROR", "草稿保存失败，请重新生成后再试")

    audit(
        db,
        current.user,
        "teacher_agent.task_publish" if publish_requested else "teacher_agent.task_draft_save",
        target_type="learning_task",
        target_id=task_id,
        after={
            "class_id": run["class_id"],
            "cap_count": len(draft["cap_ids"]),
            "published": published,
            "publish_required": not publish_requested,
        },
    )
    return {
        "status": "confirmed",
        "task": task,
        "published": published,
        "publish_required": not publish_requested,
    }


@router.post("/confirmations/{confirmation_id}/cancel")
def cancel_draft(
    confirmation_id: str,
    _body: _EmptyBody | None = None,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    confirmation, run, _conversation = _load_teacher_confirmation(
        db, confirmation_id=confirmation_id, teacher_id=current.user["id"]
    )
    _confirmation_pending_or_raise(confirmation)
    if confirmation["expires_at"] <= utc_now_iso():
        _expire_or_raise(db, confirmation)
    outcome = cancel_pending_confirmation(db, confirmation, _CANCELLED_NOTICE)
    if outcome == EXPIRED:
        _expire_or_raise(db, confirmation)
    if outcome != CANCELLED:
        raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")
    audit(
        db,
        current.user,
        "teacher_agent.task_draft_cancel",
        target_type="agent_run",
        target_id=run["id"],
        after={"class_id": run["class_id"]},
    )
    return {"status": "cancelled"}


@router.post("/confirmations/{confirmation_id}/expire")
def expire_draft(
    confirmation_id: str,
    _body: _EmptyBody | None = None,
    current: CurrentUser = Depends(require_teacher_csrf),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    confirmation, _run, _conversation = _load_teacher_confirmation(
        db, confirmation_id=confirmation_id, teacher_id=current.user["id"]
    )
    if confirmation["status"] == "expired":
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    _confirmation_pending_or_raise(confirmation)
    if confirmation["expires_at"] > utc_now_iso():
        raise ApiError(409, "CONFIRMATION_NOT_EXPIRED", "确认单尚未过期")
    if expire_pending_confirmation(db, confirmation):
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    latest = db.execute(
        "SELECT status FROM pending_confirmations WHERE id = ?", (confirmation["id"],)
    ).fetchone()
    if latest is not None and latest["status"] == "expired":
        return {"status": "expired", "summary": EXPIRED_NOTICE}
    raise ApiError(409, "CONFIRMATION_IN_PROGRESS", "确认操作正在处理中，请刷新页面")
