"""Agent 运行与会话路由（蓝图 §6.2）。

要点：
- 所有变更类端点走 csrf_protect；邮箱状态不再是 Agent 使用门槛。
- POST /api/runs 只负责建会话/建行/落用户消息，编排经
  `orchestrator.spawn` 投递到进程级后台 loop（TestClient 的 per-request
  portal 会取消请求 loop 上的挂起任务，故不用 asyncio.create_task）。
- SSE 事件流（GET /api/runs/{id}/events）：生成器内自开连接轮询
  agent_events，支持 after_seq 与 Last-Event-ID 重连续播（蓝图 §7）。
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
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..agent import conversation_memory
from ..agent import media
from ..agent import providers
from ..agent.composer import sanitize_model_text
from ..agent import events as agent_events
from ..agent.orchestrator import execute_run, spawn
from ..audit import audit
from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, require_student_portal_user
from ..errors import ApiError

logger = logging.getLogger(__name__)

# Agent conversations back the learner cockpit and must reject a teacher even
# when the request bypasses the frontend route guard.
router = APIRouter(
    prefix="/api", tags=["agent"], dependencies=[Depends(require_student_portal_user)]
)

_RUN_TERMINAL = ("completed", "failed", "cancelled")
_HISTORY_ACTIVITY_TERMINAL = {"completed", "failed", "cancelled"}


def _safe_history_tool_name(value: object) -> str | None:
    """Accept only registered-tool-shaped names from durable metadata.

    Event payloads are replayable transport data, so the history endpoint does
    not trust arbitrary event text as a display label. Tool identifiers are
    deliberately constrained to the registry's ASCII dotted-name convention.
    """

    if not isinstance(value, str):
        return None
    tool = value.strip()
    if not tool or len(tool) > 96:
        return None
    if not all(char.isascii() and (char.isalnum() or char in "._-") for char in tool):
        return None
    return tool


def _history_activity_status(raw_status: object, *, confirmation: bool = False) -> str:
    """Project durable lifecycle states into the compact cockpit status set."""

    if raw_status == "completed" or (confirmation and raw_status == "confirmed"):
        return "completed"
    if raw_status in {"requested", "running"}:
        return "running"
    if raw_status in {"awaiting_confirmation", "waiting_confirmation", "pending"}:
        return "waiting"
    return "failed"


def _history_activity_message(stage: str, status: str) -> str:
    """Use fixed learner-safe copy instead of replaying arbitrary event text."""

    if stage == "planning":
        if status == "running":
            return "正在制定执行计划"
        return "执行计划已生成" if status == "completed" else "执行计划未完成"
    if stage == "responding":
        if status == "running":
            return "正在生成回答"
        return "回答已生成" if status == "completed" else "回答未完成"
    if stage == "confirmation":
        if status == "waiting":
            return "等待你的确认"
        return "确认已完成" if status == "completed" else "确认未完成"
    if status == "running":
        return "正在调用工具"
    if status == "waiting":
        return "等待确认后调用工具"
    return "工具调用已完成" if status == "completed" else "工具调用未完成"


def _parse_event_payload(raw: object) -> dict[str, Any] | None:
    """Parse one persisted event defensively; malformed legacy rows stay hidden."""

    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def get_agent_db():
    """请求级数据库依赖（deps.get_db 的线程亲和修正版）。

    为什么不用 deps.get_db：FastAPI 把 sync 依赖放进 anyio 线程池执行，
    而 async 端点在事件循环线程执行——标准 sqlite3 连接默认
    check_same_thread=True，跨线程使用直接 ProgrammingError。
    check_same_thread=False 在本场景安全：连接在单次请求内被**顺序**
    跨线程使用（依赖→端点），WAL + 短事务下无并发写同一连接的情形。
    """
    conn = sqlite3.connect(get_config().resolved_database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _emit_telemetry(db: sqlite3.Connection, user_id: str, name: str, props: dict) -> None:
    try:
        from ..telemetry import emit_event  # B1，惰性导入
    except ImportError:
        return
    try:
        emit_event(db, user_id, name, props)
    except Exception:
        logger.warning("埋点 %s 写入失败", name, exc_info=True)


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def _conversation_dto(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "scenario_id": row["scenario_id"],
        "data_type": row["data_type"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _attachment_thumbnail_url(message_id: str, attachment_id: str) -> str:
    """Build a cookie-authenticated URL instead of exposing a static media path."""

    return f"/api/messages/{message_id}/attachments/{attachment_id}/thumbnail"


def _attachment_dto(row: sqlite3.Row) -> dict[str, Any]:
    """Project persisted attachment metadata without returning its BLOB."""

    has_thumbnail = bool(row["has_thumbnail"])
    return {
        "id": row["id"],
        "ordinal": row["ordinal"],
        "name": row["filename"],
        "kind": row["kind"],
        "mime_type": row["mime_type"],
        "size": row["byte_size"],
        "thumbnail_url": (
            _attachment_thumbnail_url(row["message_id"], row["id"])
            if has_thumbnail
            else None
        ),
    }


def _load_message_attachments(
    db: sqlite3.Connection, message_id: str
) -> list[dict[str, Any]]:
    """Load one message's ordered, client-safe attachment projection."""

    rows = db.execute(
        """
        SELECT id, message_id, ordinal, filename, kind, mime_type, byte_size,
               thumbnail IS NOT NULL AS has_thumbnail
        FROM message_attachments
        WHERE message_id = ?
        ORDER BY ordinal ASC
        """,
        (message_id,),
    ).fetchall()
    return [_attachment_dto(row) for row in rows]


def _load_conversation_attachments(
    db: sqlite3.Connection, conversation_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Group one conversation's attachments without an unbounded SQL IN list."""

    rows = db.execute(
        """
        SELECT attachment.id, attachment.message_id, attachment.ordinal,
               attachment.filename, attachment.kind, attachment.mime_type,
               attachment.byte_size, attachment.thumbnail IS NOT NULL AS has_thumbnail
        FROM message_attachments AS attachment
        JOIN messages AS message ON message.id = attachment.message_id
        WHERE message.conversation_id = ?
        ORDER BY message.created_at ASC, message.rowid ASC, attachment.ordinal ASC
        """,
        (conversation_id,),
    ).fetchall()
    attachments_by_message: dict[str, list[dict[str, Any]]] = {}
    for attachment in rows:
        attachments_by_message.setdefault(attachment["message_id"], []).append(
            _attachment_dto(attachment)
        )
    return attachments_by_message


def _message_dto(
    row: sqlite3.Row, *, attachments: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Apply the same answer privacy projection to current and historic messages."""

    dto = {
        "id": row["id"],
        "run_id": row["run_id"],
        "role": row["role"],
        # Older assistant rows may contain a provider-emitted thinking block.
        # Sanitize at the API projection so history never reintroduces content
        # hidden from the live stream.
        "content": (
            sanitize_model_text(row["content"])
            if row["role"] == "assistant"
            else row["content"]
        ),
        "created_at": row["created_at"],
    }
    if attachments is not None:
        dto["attachments"] = attachments
    return dto


def _load_own_conversation(
    db: sqlite3.Connection, conversation_id: str, user_id: str
) -> sqlite3.Row:
    """属主校验：他人会话一律 404（不暴露存在性）。"""
    row = db.execute(
        "SELECT * FROM conversations WHERE id = ? AND deleted_at IS NULL",
        (conversation_id,),
    ).fetchone()
    if row is None or row["user_id"] != user_id:
        raise ApiError(404, "NOT_FOUND", "会话不存在")
    return row


def _project_conversation_activities(
    db: sqlite3.Connection, conversation_id: str, user_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Rebuild compact, learner-safe activity rows from durable run events.

    Conversation reload must not invent a generic work item for old messages.
    This projection therefore starts from replayable events and only enriches
    them from the owned tool/confirmation rows needed to close a lifecycle.
    Prompts, raw tool inputs/results, and confirmation previews never enter
    this response. RAG uses typed hit counts plus bounded tool summaries so a
    reloaded conversation remains truthful without trusting historic text.
    """

    run_rows = db.execute(
        """
        SELECT id, status
        FROM agent_runs
        WHERE conversation_id = ? AND user_id = ?
        ORDER BY created_at ASC, rowid ASC
        """,
        (conversation_id, user_id),
    ).fetchall()
    if not run_rows:
        return {}

    run_statuses = {run["id"]: run["status"] for run in run_rows}
    tool_rows = db.execute(
        """
        SELECT tool.id, tool.run_id, tool.tool_name, tool.status,
               tool.duration_ms, tool.is_write
        FROM tool_calls AS tool
        JOIN agent_runs AS run ON run.id = tool.run_id
        WHERE run.conversation_id = ? AND run.user_id = ?
        """,
        (conversation_id, user_id),
    ).fetchall()
    tools_by_id = {tool["id"]: tool for tool in tool_rows}
    confirmation_rows = db.execute(
        """
        SELECT confirmation.id, confirmation.run_id, confirmation.status
        FROM pending_confirmations AS confirmation
        JOIN agent_runs AS run ON run.id = confirmation.run_id
        WHERE run.conversation_id = ? AND run.user_id = ?
        """,
        (conversation_id, user_id),
    ).fetchall()
    confirmations_by_id = {confirmation["id"]: confirmation for confirmation in confirmation_rows}
    event_rows = db.execute(
        """
        SELECT run.id AS run_id, event.seq, event.event_type, event.payload_json
        FROM agent_runs AS run
        JOIN agent_events AS event ON event.run_id = run.id
        WHERE run.conversation_id = ? AND run.user_id = ?
        ORDER BY run.created_at ASC, run.rowid ASC, event.seq ASC
        """,
        (conversation_id, user_id),
    ).fetchall()

    activities_by_run: dict[str, list[dict[str, Any]]] = {}
    activity_indexes: dict[str, dict[str, int]] = {}

    def upsert_activity(run_id: str, key: str, event_seq: int, entry: dict[str, Any]) -> None:
        """Merge requested/completed frames into their original activity row."""

        entries = activities_by_run.setdefault(run_id, [])
        indexes = activity_indexes.setdefault(run_id, {})
        existing_index = indexes.get(key)
        if existing_index is None:
            indexes[key] = len(entries)
            entries.append(entry)
            return
        # Keep the first event's seq as the visual position while recording the
        # latest event sequence for recovery and terminal-state reconciliation.
        existing = entries[existing_index]
        first_seq = existing["seq"]
        existing.update(entry)
        existing["seq"] = first_seq

    for event in event_rows:
        run_id = event["run_id"]
        payload = _parse_event_payload(event["payload_json"])
        if payload is None:
            continue
        event_seq = int(event["seq"])

        if event["event_type"] == agent_events.RUN_PROGRESS:
            phase = payload.get("phase")
            # Legacy understanding frames describe model interpretation rather
            # than a user-verifiable action. Retrieval has dedicated typed
            # events below, avoiding an arbitrary historic detail string.
            if phase not in {"planning", "synthesis"}:
                continue
            activity_id = payload.get("activity_id")
            if not isinstance(activity_id, str) or not activity_id:
                activity_id = (
                    f"history-answer:{run_id}" if phase == "synthesis"
                    else f"history-{phase}:{run_id}"
                )
            status = _history_activity_status(payload.get("status"))
            stage = "responding" if phase == "synthesis" else phase
            upsert_activity(
                run_id,
                # Keep each lifecycle's first sequence as its visual position;
                # later frames only replace status/detail in that same row.
                f"progress:{stage}",
                event_seq,
                {
                    "seq": event_seq,
                    "event_seq": event_seq,
                    "activity_id": activity_id,
                    "stage": stage,
                    "status": status,
                    "message": _history_activity_message(stage, status),
                },
            )
            continue

        if event["event_type"] == agent_events.RAG_RETRIEVAL_STARTED:
            upsert_activity(
                run_id,
                "retrieval",
                event_seq,
                {
                    "seq": event_seq,
                    "event_seq": event_seq,
                    "activity_id": f"retrieval:{run_id}",
                    "stage": "retrieval",
                    "status": "running",
                    "message": "正在检索相关资料",
                },
            )
            continue

        if event["event_type"] == agent_events.RAG_RETRIEVAL_COMPLETED:
            hit_count = payload.get("hit_count")
            latency_ms = payload.get("latency_ms")
            safe_hit_count = hit_count if isinstance(hit_count, int) and hit_count >= 0 else 0
            safe_latency_ms = latency_ms if isinstance(latency_ms, int) and latency_ms >= 0 else None
            detail = f"命中 {safe_hit_count} 条资料"
            if safe_latency_ms is not None:
                detail += f"，耗时 {safe_latency_ms} ms"
            upsert_activity(
                run_id,
                "retrieval",
                event_seq,
                {
                    "seq": event_seq,
                    "event_seq": event_seq,
                    "activity_id": f"retrieval:{run_id}",
                    "stage": "retrieval",
                    "status": "completed",
                    "message": "资料检索完成",
                    "detail": detail,
                },
            )
            continue

        if event["event_type"] in {
            agent_events.TOOL_CALL_REQUESTED,
            agent_events.TOOL_CALL_COMPLETED,
        }:
            tool_call_id = payload.get("tool_call_id")
            tool_row = tools_by_id.get(tool_call_id) if isinstance(tool_call_id, str) else None
            if tool_row is None or tool_row["run_id"] != run_id:
                continue
            tool = _safe_history_tool_name(tool_row["tool_name"])
            if tool is None:
                continue
            status = _history_activity_status(tool_row["status"])
            activity_entry: dict[str, Any] = {
                "seq": event_seq,
                "event_seq": event_seq,
                "stage": "tool",
                "status": status,
                "message": _history_activity_message("tool", status),
                "tool": tool,
                "tool_call_id": tool_call_id,
                "duration_ms": tool_row["duration_ms"],
                "is_write": bool(tool_row["is_write"]),
            }
            # New lifecycle events carry safe human-readable summaries.  Do
            # not synthesize them for old rows: historical replay must remain
            # faithful when those fields were never persisted.
            for payload_key, entry_key in (
                ("execution_kind", "execution_kind"),
                ("input_summary", "input_summary"),
                ("output_summary", "output_summary"),
            ):
                value = payload.get(payload_key)
                if isinstance(value, str) and value:
                    activity_entry[entry_key] = value[:240]
            upsert_activity(
                run_id,
                f"tool:{tool_call_id}",
                event_seq,
                activity_entry,
            )
            continue

        if event["event_type"] != agent_events.CONFIRMATION_REQUIRED:
            continue
        confirmation_payload = payload.get("confirmation")
        if not isinstance(confirmation_payload, dict):
            continue
        confirmation_id = confirmation_payload.get("id")
        confirmation = (
            confirmations_by_id.get(confirmation_id) if isinstance(confirmation_id, str) else None
        )
        if confirmation is None or confirmation["run_id"] != run_id:
            continue
        status = _history_activity_status(confirmation["status"], confirmation=True)
        upsert_activity(
            run_id,
            f"confirmation:{confirmation_id}",
            event_seq,
            {
                "seq": event_seq,
                "event_seq": event_seq,
                "activity_id": f"confirmation:{confirmation_id}",
                "stage": "confirmation",
                "status": status,
                "message": _history_activity_message("confirmation", status),
            },
        )

    for run_id, entries in activities_by_run.items():
        terminal_status = run_statuses[run_id]
        if terminal_status not in _HISTORY_ACTIVITY_TERMINAL:
            continue
        settled_status = "failed" if terminal_status == "failed" else "completed"
        # A crash or old server version can leave the final lifecycle frame out
        # of the event log. The terminal run row is more recent durable truth,
        # so close only already-visible rows rather than inventing a new step.
        for entry in entries:
            if entry["status"] not in {"running", "waiting"}:
                continue
            entry["status"] = settled_status
            entry["message"] = _history_activity_message(entry["stage"], settled_status)

    return activities_by_run


class ConversationCreate(BaseModel):
    title: str | None = None
    scenario_id: str | None = None
    data_type: str | None = None


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current: CurrentUser = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    total = db.execute(
        "SELECT COUNT(*) AS c FROM conversations WHERE user_id = ? AND deleted_at IS NULL",
        (current.user["id"],),
    ).fetchone()["c"]
    rows = db.execute(
        """
        SELECT * FROM conversations
        WHERE user_id = ? AND deleted_at IS NULL
        ORDER BY updated_at DESC LIMIT ? OFFSET ?
        """,
        (current.user["id"], limit, offset),
    ).fetchall()
    return {"items": [_conversation_dto(r) for r in rows], "total": total}


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: ConversationCreate,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    conversation_id = uuid.uuid4().hex
    now = utc_now_iso()
    db.execute(
        """
        INSERT INTO conversations (id, user_id, title, scenario_id, data_type, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            current.user["id"],
            body.title or "新会话",
            body.scenario_id,
            body.data_type,
            now,
            now,
        ),
    )
    db.commit()
    row = _load_own_conversation(db, conversation_id, current.user["id"])
    return _conversation_dto(row)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    row = _load_own_conversation(db, conversation_id, current.user["id"])
    messages = db.execute(
        """
        SELECT id, run_id, role, content, created_at FROM messages
        WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC
        """,
        (conversation_id,),
    ).fetchall()
    attachments_by_message = _load_conversation_attachments(db, conversation_id)
    return {
        **_conversation_dto(row),
        "messages": [
            _message_dto(m, attachments=attachments_by_message.get(m["id"], []))
            for m in messages
        ],
        "activities_by_run": _project_conversation_activities(
            db, conversation_id, current.user["id"]
        ),
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    """软删除会话 + 删除其消息（PRD-06 §12.2：删除消息和可见工具摘要，
    审计日志保留）。"""
    row = _load_own_conversation(db, conversation_id, current.user["id"])
    now = utc_now_iso()
    db.execute(
        "UPDATE conversations SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (now, now, conversation_id),
    )
    # Retain audit metadata but erase private vector memory with its source
    # conversation; this remains explicit even though the schema also cascades.
    db.execute(
        "DELETE FROM conversation_memory_chunks WHERE user_id = ? AND conversation_id = ?",
        (current.user["id"], conversation_id),
    )
    db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    audit(
        db,
        current.user,
        "conversation.delete",
        "conversation",
        conversation_id,
        before={"title": row["title"]},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"deleted": True}


@router.get("/messages/{message_id}/attachments/{attachment_id}/thumbnail")
def get_message_attachment_thumbnail(
    message_id: str,
    attachment_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> Response:
    """Read a derived preview only after proving message and conversation ownership."""

    attachment = db.execute(
        """
        SELECT attachment.thumbnail, attachment.thumbnail_mime_type
        FROM message_attachments AS attachment
        JOIN messages AS message ON message.id = attachment.message_id
        JOIN conversations AS conversation ON conversation.id = message.conversation_id
        WHERE attachment.id = ?
          AND attachment.message_id = ?
          AND conversation.user_id = ?
          AND conversation.deleted_at IS NULL
        """,
        (attachment_id, message_id, current.user["id"]),
    ).fetchone()
    if attachment is None or attachment["thumbnail"] is None:
        # Treat missing thumbnails exactly like unauthorized objects. This
        # prevents probing whether a different learner sent an image or a file.
        raise ApiError(404, "NOT_FOUND", "附件缩略图不存在")

    return Response(
        content=bytes(attachment["thumbnail"]),
        media_type=attachment["thumbnail_mime_type"],
        # Message previews are private conversation data. Browser caches must
        # not make them durable outside the authenticated application session.
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    conversation_id: str | None = None
    input: str = Field(min_length=1, max_length=4000)
    scenario_id: str | None = None
    data_type: str | None = None
    # `attachment` remains a compatibility envelope for historic clients and
    # diagnostic-token runs. New Agent messages use the bounded list below.
    attachment: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None


@router.post("/runs/attachments", status_code=201)
def upload_run_attachment(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(csrf_protect),
) -> dict[str, Any]:
    """Accept one allow-listed file for a short-lived, user-owned Agent run."""

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
        if str(exc) == "media_total_too_large":
            raise ApiError(413, "ATTACHMENTS_TOO_LARGE", "待发送附件总量不能超过 100MB") from exc
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


@router.delete("/runs/attachments/{token}", status_code=204)
def discard_run_attachment(
    token: str,
    current: CurrentUser = Depends(csrf_protect),
) -> None:
    """Release a removed draft attachment so it no longer occupies cache quota."""

    if media.get(token, current.user["id"]) is None:
        raise ApiError(404, "NOT_FOUND", "附件不存在、已过期或不属于当前账号")
    media.discard(token, current.user["id"])


@router.get("/runs/attachments/{token}/preview")
def preview_run_attachment(
    token: str,
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return only parsed document text for the owner's temporary preview."""

    item = media.get(token, current.user["id"])
    if item is None:
        raise ApiError(404, "NOT_FOUND", "附件不存在、已过期或不属于当前账号")
    if item.kind != "document" or item.extracted_text is None:
        raise ApiError(415, "PREVIEW_UNAVAILABLE", "当前文件不支持文本预览")
    # Text extraction is already bounded for model safety; this tighter UI
    # projection prevents a modal from rendering an excessive document at once.
    preview_limit = 80_000
    content = item.extracted_text[:preview_limit]
    return {
        "name": item.filename,
        "mime_type": item.mime_type,
        "content": content,
        "truncated": len(item.extracted_text) > preview_limit,
    }


def _validate_attachment(
    attachment: dict[str, Any] | None, user_id: str
) -> dict[str, str] | None:
    """Validate an attachment and return only the token-shaped run envelope.

    The browser uploads bytes to the short-lived media cache first.  Runs only
    need the opaque token to resolve that cache later, so arbitrary client
    fields (and especially accidental base64 payloads) are discarded before
    ``plan_json`` is written.  The established diagnostic token remains a
    separate compatibility path.
    """

    if not attachment:
        return None
    token = attachment.get("attachment_token")
    diagnostic_token = attachment.get("diagnostic_token")
    if token is not None and diagnostic_token is not None:
        raise ApiError(422, "INVALID_ATTACHMENT", "附件令牌无效")
    if token is None:
        # Existing diagnostic-token runs retain their established contract.
        if isinstance(diagnostic_token, str) and diagnostic_token:
            return {"diagnostic_token": diagnostic_token}
        raise ApiError(422, "INVALID_ATTACHMENT", "附件令牌无效")
    if not isinstance(token, str) or not token:
        raise ApiError(422, "INVALID_ATTACHMENT", "附件令牌无效")
    if media.get(token, user_id) is None:
        raise ApiError(403, "FORBIDDEN", "附件不属于当前账号或已过期")
    return {"attachment_token": token}


def _validate_attachments(
    attachment: dict[str, Any] | None,
    attachments: list[dict[str, Any]] | None,
    user_id: str,
) -> dict[str, Any] | None:
    """Validate new multi-file envelopes without weakening legacy callers."""

    if attachment is not None and attachments is not None:
        raise ApiError(422, "INVALID_ATTACHMENT", "附件令牌无效")
    if attachments is None:
        return _validate_attachment(attachment, user_id)
    if not attachments:
        return None
    if len(attachments) > 10:
        raise ApiError(422, "TOO_MANY_ATTACHMENTS", "一次最多发送 10 个文件")

    tokens: list[str] = []
    seen: set[str] = set()
    total_size = 0
    for entry in attachments:
        token = entry.get("attachment_token") if isinstance(entry, dict) else None
        if not isinstance(token, str) or not token or token in seen:
            raise ApiError(422, "INVALID_ATTACHMENT", "附件令牌无效")
        item = media.get(token, user_id)
        if item is None:
            raise ApiError(403, "FORBIDDEN", "附件不属于当前账号或已过期")
        seen.add(token)
        tokens.append(token)
        total_size += item.size
    if total_size > media.MAX_USER_MEDIA_BYTES:
        raise ApiError(413, "ATTACHMENTS_TOO_LARGE", "待发送附件总量不能超过 100MB")
    return {"attachments": [{"attachment_token": token} for token in tokens]}


def _media_items_from_envelope(
    attachment: dict[str, Any] | None, user_id: str
) -> list[media.MediaAttachment]:
    """Resolve only validated short-lived media tokens for capability gating."""

    if not isinstance(attachment, dict):
        return []
    rows = attachment.get("attachments")
    tokens = (
        [entry.get("attachment_token") for entry in rows if isinstance(entry, dict)]
        if isinstance(rows, list)
        else [attachment.get("attachment_token")]
    )
    # Validation above has already enforced ownership and uniqueness. A token
    # can still expire in the tiny interval before this read; reject that race
    # rather than creating a run that silently loses its selected attachment.
    items: list[media.MediaAttachment] = []
    for token in tokens:
        if not isinstance(token, str):
            continue
        item = media.get(token, user_id)
        if item is None:
            raise ApiError(403, "FORBIDDEN", "附件不属于当前账号或已过期")
        items.append(item)
    return items


def _validate_media_provider_capability(
    db: sqlite3.Connection, attachment: dict[str, Any] | None, user_id: str
) -> list[media.MediaAttachment]:
    """Reject media that no active primary/fallback model can actually inspect."""

    items = _media_items_from_envelope(attachment, user_id)
    media_kinds = {item.kind for item in items if item.kind in {"image", "audio", "video"}}
    if not media_kinds or providers.has_compatible_media_provider(db, items):
        return items
    labels = {"image": "图片", "audio": "音频", "video": "视频"}
    kind_text = "、".join(
        labels[kind] for kind in ("image", "audio", "video") if kind in media_kinds
    )
    raise ApiError(
        422,
        "ATTACHMENT_MEDIA_UNSUPPORTED",
        f"当前主模型和回退模型均无法处理{kind_text}附件。请在“模型供应商”中选择实际支持该类型的模型，并勾选相应输入能力后重试。",
    )


def _persist_message_attachments(
    db: sqlite3.Connection,
    *,
    message_id: str,
    items: list[media.MediaAttachment],
    created_at: str,
) -> None:
    """Persist display-only metadata and optional derived previews for one message."""

    for ordinal, item in enumerate(items):
        thumbnail: media.MediaThumbnail | None = None
        if item.kind == "image":
            try:
                thumbnail = media.thumbnail_for(item)
            except Exception:
                # A preview is deliberately optional. Keep a successful media
                # run sendable if a decoder has an unexpected local failure,
                # while never falling back to storing the original upload.
                logger.warning("Unable to derive attachment thumbnail", exc_info=True)

        db.execute(
            """
            INSERT INTO message_attachments
              (id, message_id, ordinal, filename, kind, mime_type, byte_size,
               thumbnail, thumbnail_mime_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                message_id,
                ordinal,
                item.filename,
                item.kind,
                item.mime_type,
                item.size,
                thumbnail.content if thumbnail is not None else None,
                thumbnail.mime_type if thumbnail is not None else None,
                created_at,
            ),
        )


@router.post("/runs", status_code=202)
async def create_run(
    body: RunCreate,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    # Validate before creating a conversation so a forged or cross-user token
    # cannot leave an otherwise empty conversation behind.
    normalized_attachment = _validate_attachments(
        body.attachment, body.attachments, current.user["id"]
    )
    # Fail before creating a conversation/message so an incompatible media
    # request cannot look successful and then reach a text-only model.
    media_items = _validate_media_provider_capability(
        db, normalized_attachment, current.user["id"]
    )
    now = utc_now_iso()

    if body.conversation_id:
        conversation = _load_own_conversation(db, body.conversation_id, current.user["id"])
        # 显式传场景/数据类型 = 用户主动切换（PRD-06 §7.3 允许的切换路径）
        if body.scenario_id or body.data_type:
            db.execute(
                "UPDATE conversations SET scenario_id = COALESCE(?, scenario_id), "
                "data_type = COALESCE(?, data_type), updated_at = ? WHERE id = ?",
                (body.scenario_id, body.data_type, now, conversation["id"]),
            )
            db.commit()
        conversation_id = conversation["id"]
        scenario_id = body.scenario_id or conversation["scenario_id"]
        data_type = body.data_type or conversation["data_type"]
    else:
        conversation_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO conversations (id, user_id, title, scenario_id, data_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                current.user["id"],
                body.input[:30],
                body.scenario_id,
                body.data_type,
                now,
                now,
            ),
        )
        scenario_id = body.scenario_id
        data_type = body.data_type

    run_id = uuid.uuid4().hex
    # attachment 无 schema 列（003 契约不可改）：暂存于 plan_json，
    # 编排器构建计划时读取后覆盖为真正的计划
    seed_plan = (
        json.dumps({"attachment": normalized_attachment}, ensure_ascii=False)
        if normalized_attachment
        else None
    )
    db.execute(
        """
        INSERT INTO agent_runs
          (id, conversation_id, user_id, status, input_text, plan_json,
           scenario_id, data_type, created_at)
        VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            conversation_id,
            current.user["id"],
            body.input,
            seed_plan,
            scenario_id,
            data_type,
            now,
        ),
    )
    message_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, 'user', ?, ?)
        """,
        (message_id, conversation_id, run_id, body.input, now),
    )
    # Tokens remain only in the run envelope for the active provider call.
    # Message history records server-verified display facts, never the upload
    # token, the original bytes, or parsed document content.
    _persist_message_attachments(
        db,
        message_id=message_id,
        items=media_items,
        created_at=now,
    )
    db.commit()
    # The request message is indexed after its source row commits. Retrieval
    # later excludes this run because the same input is already the live prompt.
    conversation_memory.index_message(
        db,
        message_id=message_id,
        user_id=current.user["id"],
        conversation_id=conversation_id,
        run_id=run_id,
        role="user",
        content=body.input,
        created_at=now,
    )

    _emit_telemetry(
        db,
        current.user["id"],
        "goal_submitted",
        {
            "conversation_id": conversation_id,
            "has_scenario": bool(scenario_id),
            "has_data_type": bool(data_type),
        },
    )

    config = get_config()
    spawn(execute_run(run_id, config.resolved_database_path))
    user_message = db.execute(
        "SELECT id, run_id, role, content, created_at FROM messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return {
        "run_id": run_id,
        "conversation_id": conversation_id,
        "user_message": _message_dto(
            user_message,
            attachments=_load_message_attachments(db, message_id),
        ),
    }


def _load_own_run(db: sqlite3.Connection, run_id: str, user_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None or row["user_id"] != user_id:
        raise ApiError(404, "NOT_FOUND", "运行不存在")
    return row


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    run = _load_own_run(db, run_id, current.user["id"])
    try:
        raw_plan = json.loads(run["plan_json"]) if run["plan_json"] else None
    except json.JSONDecodeError:
        raw_plan = None

    # A recovery read only needs the visible plan labels.  The durable plan
    # also contains original user arguments and clarification state, which are
    # planner internals and must not cross the API boundary.
    plan = None
    if isinstance(raw_plan, dict) and isinstance(raw_plan.get("steps"), list):
        safe_steps: list[dict[str, Any]] = []
        for raw_step in raw_plan["steps"]:
            if not isinstance(raw_step, dict):
                continue
            safe_step: dict[str, Any] = {}
            for key in ("id", "title", "status", "tool", "tool_call_id"):
                value = raw_step.get(key)
                if isinstance(value, str) and value:
                    safe_step[key] = value[:160]
            if safe_step.get("id") and safe_step.get("title"):
                safe_steps.append(safe_step)
        plan = {"steps": safe_steps}
    tool_calls = db.execute(
        """
        SELECT id, tool_name, permission, status, args_json, result_json,
               duration_ms, is_write, created_at, completed_at
        FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC, rowid ASC
        """,
        (run_id,),
    ).fetchall()
    confirmations = db.execute(
        """
        SELECT id, tool_call_id, action_type, preview_json, status, expires_at, created_at
        FROM pending_confirmations
        WHERE run_id = ? AND status = 'pending' ORDER BY created_at ASC
        """,
        (run_id,),
    ).fetchall()
    assistant_message = db.execute(
        """
        SELECT id, run_id, role, content, created_at FROM messages
        WHERE run_id = ? AND conversation_id = ? AND role = 'assistant'
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (run_id, run["conversation_id"]),
    ).fetchone()

    def _parse(raw: str | None) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # The terminal SSE event is the durable source for the compact result card.
    # Project only its safe summary/suggestion fields so a recovery GET cannot
    # turn an arbitrary event payload into a new data disclosure surface.
    terminal_event = db.execute(
        """
        SELECT event_type, payload_json
        FROM agent_events
        WHERE run_id = ? AND event_type IN (?, ?)
        ORDER BY seq DESC LIMIT 1
        """,
        (run_id, agent_events.RUN_COMPLETED, agent_events.RUN_FAILED),
    ).fetchone()
    terminal_payload = _parse(terminal_event["payload_json"]) if terminal_event else None
    summary = None
    suggestion = None
    if terminal_event and terminal_event["event_type"] == agent_events.RUN_COMPLETED:
        if isinstance(terminal_payload, dict) and isinstance(terminal_payload.get("summary"), str):
            summary = terminal_payload["summary"]
        raw_suggestion = (
            terminal_payload.get("suggestion") if isinstance(terminal_payload, dict) else None
        )
        if (
            isinstance(raw_suggestion, dict)
            and isinstance(raw_suggestion.get("suggested_scenario_id"), str)
            and isinstance(raw_suggestion.get("message"), str)
        ):
            suggestion = {
                "suggested_scenario_id": raw_suggestion["suggested_scenario_id"],
                "message": raw_suggestion["message"],
            }

    return {
        "run": {
            "id": run["id"],
            "conversation_id": run["conversation_id"],
            "status": run["status"],
            "input_text": run["input_text"],
            "scenario_id": run["scenario_id"],
            "data_type": run["data_type"],
            "error": run["error"],
            "created_at": run["created_at"],
            "completed_at": run["completed_at"],
        },
        "plan": plan,
        "summary": summary,
        "suggestion": suggestion,
        # SSE can be interrupted after the response was persisted.  Limiting
        # this recovery payload to the already ownership-checked run and its
        # conversation prevents a stale or cross-conversation message leak.
        "assistant_message": (
            {
                "id": assistant_message["id"],
                "run_id": assistant_message["run_id"],
                "role": assistant_message["role"],
                # Recovery is another user-visible boundary; apply the same
                # answer-only projection used by live Composer output.
                "content": sanitize_model_text(assistant_message["content"]),
                "created_at": assistant_message["created_at"],
            }
            if assistant_message is not None
            else None
        ),
        "tool_calls": [
            {
                "id": t["id"],
                "tool": t["tool_name"],
                "permission": t["permission"],
                "status": t["status"],
                "execution_kind": agent_events.execution_kind(t["tool_name"]),
                "input_summary": agent_events.summarize_tool_input(_parse(t["args_json"])),
                "output_summary": agent_events.summarize_tool_result(
                    _parse(t["result_json"]), status=t["status"]
                ),
                "duration_ms": t["duration_ms"],
                "is_write": bool(t["is_write"]),
                "created_at": t["created_at"],
                "completed_at": t["completed_at"],
            }
            for t in tool_calls
        ],
        "confirmations": [
            {
                "id": c["id"],
                "tool_call_id": c["tool_call_id"],
                "action_type": c["action_type"],
                "preview": agent_events.redact_tool_payload(_parse(c["preview_json"])),
                "status": c["status"],
                "expires_at": c["expires_at"],
                "created_at": c["created_at"],
            }
            for c in confirmations
        ],
    }


# ---------------------------------------------------------------------------
# SSE 事件流
# ---------------------------------------------------------------------------

_SSE_POLL_SECONDS = 0.25
_SSE_HEARTBEAT_SECONDS = 15.0


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after_seq: int = Query(0, ge=0),
    current: CurrentUser = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> StreamingResponse:
    _load_own_run(db, run_id, current.user["id"])
    # EventSource 重连自动带 Last-Event-ID，优先于显式 query（蓝图 §7 断点续播）
    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        after_seq = max(after_seq, int(last_event_id))
    db_path = get_config().resolved_database_path

    async def _generate() -> AsyncIterator[str]:
        # 生成器自开连接：请求连接随响应头返回后即释放，不能跨流复用；
        # 走 db.connect 统一拿到 WAL/外键/check_same_thread=False（流式协程
        # 可能被任意线程恢复，避免与 deps.get_db 同类的跨线程 500）
        stream_db = db_connect(db_path)
        cursor_seq = after_seq
        last_beat = time.monotonic()
        try:
            while True:
                if await request.is_disconnected():
                    break
                rows = agent_events.list_events(stream_db, run_id, cursor_seq)
                for row in rows:
                    cursor_seq = row["seq"]
                    try:
                        payload = json.loads(row["payload_json"])
                    except json.JSONDecodeError:
                        payload = {}
                    frame_data = json.dumps(
                        {"seq": row["seq"], **payload}, ensure_ascii=False, default=str
                    )
                    yield (f"id: {row['seq']}\nevent: {row['event_type']}\ndata: {frame_data}\n\n")
                    last_beat = time.monotonic()
                run_row = stream_db.execute(
                    "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                terminal = run_row is not None and run_row["status"] in _RUN_TERMINAL
                if terminal and not rows:
                    # 终态且事件已 drain：发 stream.end 收尾后关闭（前端据此停 EventSource）
                    yield f"event: {agent_events.STREAM_END}\ndata: {{}}\n\n"
                    break
                if time.monotonic() - last_beat >= _SSE_HEARTBEAT_SECONDS:
                    yield ": heartbeat\n\n"
                    last_beat = time.monotonic()
                await asyncio.sleep(_SSE_POLL_SECONDS)
        finally:
            stream_db.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 反代缓冲会破坏 SSE 实时性
        },
    )
