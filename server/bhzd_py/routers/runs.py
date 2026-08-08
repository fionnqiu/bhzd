"""Agent 运行与会话路由（蓝图 §6.2）。

要点：
- 所有变更类端点走 csrf_protect + 邮箱验证门（PRD-06 §3.2 未验证禁止 Agent）。
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

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent import conversation_memory
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


def _require_verified(current: CurrentUser) -> CurrentUser:
    """csrf_protect 已加载会话，这里叠加邮箱验证门（PRD-06 §3.2）。"""
    if current.user["email_verified_at"] is None:
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "请先完成邮箱验证后再使用此功能")
    return current


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
    _require_verified(current)
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
    return {
        **_conversation_dto(row),
        "messages": [
            {
                "id": m["id"],
                "run_id": m["run_id"],
                "role": m["role"],
                # Older assistant rows may contain a provider-emitted thinking
                # block. Sanitize at the API projection so history never
                # reintroduces content hidden from the live stream.
                "content": (
                    sanitize_model_text(m["content"])
                    if m["role"] == "assistant"
                    else m["content"]
                ),
                "created_at": m["created_at"],
            }
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


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    conversation_id: str | None = None
    input: str = Field(min_length=1, max_length=4000)
    scenario_id: str | None = None
    data_type: str | None = None
    attachment: dict[str, Any] | None = None


@router.post("/runs", status_code=202)
async def create_run(
    body: RunCreate,
    current: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_agent_db),
) -> dict[str, Any]:
    _require_verified(current)
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
        json.dumps({"attachment": body.attachment}, ensure_ascii=False) if body.attachment else None
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
    return {"run_id": run_id, "conversation_id": conversation_id}


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
