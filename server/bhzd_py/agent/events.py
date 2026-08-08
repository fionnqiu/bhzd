"""Agent SSE 事件常量与持久化（蓝图 §7 / PRD-05 §5）。

为什么事件要落库（agent_events 表）而不是只在内存里推送：
前端断线后需要用 `after_seq` 重连续播（蓝图 §7），这要求每个事件都有
单调递增的 seq 且可回放，因此 emit 即 INSERT，SSE 层只做查询转发。

注意：`stream.end` 不是持久化事件，只是 SSE 流收尾标记（前端据此关闭
EventSource），因此不出现在 §7 常量清单里，由 SSE 路由自行发送。
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..db import utc_now_iso

# ---- 蓝图 §7 事件名契约（逐字） ----
RUN_STARTED = "run.started"
RUN_PROGRESS = "run.progress"
MESSAGE_DELTA = "message.delta"
PLAN_UPDATED = "plan.updated"
TOOL_CALL_REQUESTED = "tool.call.requested"
TOOL_CALL_COMPLETED = "tool.call.completed"
RAG_RETRIEVAL_STARTED = "rag.retrieval.started"
RAG_RETRIEVAL_COMPLETED = "rag.retrieval.completed"
CITATION_ATTACHED = "citation.attached"
CONFIRMATION_REQUIRED = "confirmation.required"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"
RUN_USAGE = "run.usage"

# 仅 SSE 传输层使用，不落 agent_events（不属于 §7 持久化事件）
STREAM_END = "stream.end"

_SENSITIVE_KEY = re.compile(
    r"(?i)^(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"api[_ -]?key|access[_ -]?token|token|secret|password|session[_ -]?id|"
    r"diagnostic[_ -]?token)$"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?P<key>authorization|proxy-authorization|cookie|set-cookie|"
    r"api[_ -]?key|access[_ -]?token|token|secret|password|session[_ -]?id|"
    r"diagnostic[_ -]?token)\s*[:=：]\s*(?:bearer\s+)?[^,;\s]+"
)
_COMMAND_TOOL_PREFIXES = ("shell.", "command.", "terminal.", "exec.")
_FILE_TOOL_PREFIXES = ("file.", "filesystem.", "fs.")


def execution_kind(tool: str | None) -> str:
    """Classify an execution without exposing the underlying tool payload.

    The current registry contains domain tools only.  Keeping command/file
    prefixes here means a future shell or filesystem tool automatically gets a
    truthful UI label without teaching the browser to infer it from arguments.
    """

    normalized = tool.strip().lower() if isinstance(tool, str) else ""
    if normalized.startswith(_COMMAND_TOOL_PREFIXES):
        return "command"
    if normalized.startswith(_FILE_TOOL_PREFIXES):
        return "file"
    return "tool"


def _safe_text(value: object, *, limit: int = 160) -> str:
    """Collapse and redact arbitrary tool text before it enters an activity event."""

    text = " ".join(str(value).split())
    text = _SENSITIVE_VALUE.sub(
        lambda match: f"{match.group('key')}: [已隐藏]", text
    )
    return text[:limit]


def redact_tool_payload(value: object, *, depth: int = 0) -> object:
    """Keep compatibility result cards useful while removing sensitive leaves.

    Tool results remain in the private database for orchestration.  The copy
    attached to an SSE event is a bounded projection: secret-like keys are
    replaced, strings are whitespace-collapsed, and deeply nested/large
    collections are truncated.  This lets the existing task and graph cards
    keep working without making raw provider or upload payloads public.
    """

    if depth > 5:
        return "[内容已省略]"
    if isinstance(value, dict):
        projected: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                projected["…"] = "其余内容已省略"
                break
            key_text = str(key)
            if _SENSITIVE_KEY.match(key_text.replace(" ", "_")):
                projected[key_text] = "[已隐藏]"
            else:
                projected[key_text] = redact_tool_payload(item, depth=depth + 1)
        return projected
    if isinstance(value, list):
        projected_list = [redact_tool_payload(item, depth=depth + 1) for item in value[:40]]
        if len(value) > 40:
            projected_list.append("其余内容已省略")
        return projected_list
    if isinstance(value, tuple):
        return [redact_tool_payload(item, depth=depth + 1) for item in value[:40]]
    if isinstance(value, str):
        return _safe_text(value, limit=500)
    return value


def public_tool_result(tool: str | None, result: object) -> object | None:
    """Return a card-safe result, omitting retrieval internals entirely.

    RAG search/answer payloads can contain private document excerpts and are
    already consumed by the final assistant response/citation events.  They
    therefore stay in the private tool-call row instead of travelling through
    the student SSE stream; other typed cards receive the bounded projection.
    """

    if isinstance(tool, str) and tool.strip().lower().startswith("rag."):
        return None
    return redact_tool_payload(result)


def summarize_tool_input(args: object, *, title: str | None = None) -> str:
    """Return a useful parameter count while keeping values out of the browser."""

    if isinstance(args, dict):
        count = len(args)
        prefix = _safe_text(title, limit=96) if title else ""
        return f"{prefix + ' · ' if prefix else ''}参数 {count} 项，具体值已隐藏"
    return "参数值已隐藏"


def summarize_tool_result(result: object, *, status: str) -> str:
    """Project common tool outcomes into bounded learner-facing copy.

    Result bodies can contain retrieved text, uploaded excerpts, or database
    records.  Only counts and deterministic outcome markers are allowed here;
    the raw result remains an internal compatibility payload for existing cards.
    """

    if status == "awaiting_confirmation":
        return "等待确认，尚未执行写入"
    if status in {"cancelled", "expired"}:
        return "已取消，未执行写入"
    if status != "completed":
        if isinstance(result, dict) and result.get("error"):
            return f"执行失败：{_safe_text(result['error'], limit=96)}"
        return "执行未完成"
    if result is None:
        return "执行完成，无返回内容"
    if isinstance(result, list):
        return f"执行完成，返回 {len(result)} 项"
    if not isinstance(result, dict):
        return "执行完成，已返回结果"

    if result.get("error"):
        return f"执行失败：{_safe_text(result['error'], limit=96)}"
    if isinstance(result.get("hit_count"), int):
        return f"执行完成，命中 {max(result['hit_count'], 0)} 条资料"
    for key, label in (("nodes", "图谱节点"), ("hits", "检索结果"), ("items", "条目")):
        value = result.get(key)
        if isinstance(value, list):
            return f"执行完成，返回 {len(value)} 个{label}"
    if result.get("card") is not None:
        return "执行完成，已生成任务卡"
    if result.get("answer") is not None:
        return "执行完成，已生成回答"
    if result.get("saved") or result.get("created") or result.get("updated"):
        return "执行完成，数据已更新"
    return f"执行完成，返回 {len(result)} 项结构化结果"


def emit_progress(
    db: sqlite3.Connection,
    run_id: str,
    *,
    phase: str,
    status: str,
    title: str,
    detail: str | None = None,
    activity_id: str | None = None,
    commit: bool = True,
) -> int:
    """Persist a small, replayable description of run progress.

    Progress is deliberately a closed projection rather than a copy of model
    prompts, tool arguments, or tool results.  This keeps the live activity
    feed useful after reconnecting without turning it into a channel for
    hidden reasoning or sensitive data.  ``activity_id`` is deliberately
    optional so replayable framework frames do not automatically become
    student-visible activity rows.
    """

    def _text(value: str, limit: int) -> str:
        # Collapse control whitespace and bound payload size so callers cannot
        # accidentally turn a progress update into an unbounded text channel.
        return " ".join(value.split())[:limit]

    payload: dict[str, Any] = {
        "phase": _text(phase, 48),
        "status": _text(status, 48),
        "title": _text(title, 160),
    }
    if detail:
        payload["detail"] = _text(detail, 280)
    if activity_id:
        # The client uses this key to replace a lifecycle row in place rather
        # than append another fixed progress item for the same visible action.
        payload["activity_id"] = _text(activity_id, 96)
    return emit(db, run_id, RUN_PROGRESS, payload, commit=commit)


def emit(
    db: sqlite3.Connection,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    commit: bool = True,
) -> int:
    """持久化一条事件并返回其 seq（同一 run 内从 1 单调递增）。

    seq 用 `COALESCE(MAX(seq),0)+1` 在单条 INSERT...SELECT 里计算，
    避免"先查后插"在并发下的竞态（SQLite 单写者串行化兜底）。
    """
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    cursor = db.execute(
        """
        INSERT INTO agent_events (run_id, seq, event_type, payload_json, created_at)
        SELECT ?,
               COALESCE((SELECT MAX(seq) FROM agent_events WHERE run_id = ?), 0) + 1,
               ?, ?, ?
        """,
        (run_id, run_id, event_type, payload_json, utc_now_iso()),
    )
    # Terminal lifecycle transitions defer this commit so state and all replayable
    # events become visible to SSE readers in one SQLite transaction.
    if commit:
        db.commit()
    row = db.execute(
        "SELECT seq FROM agent_events WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return int(row["seq"])


def list_events(
    db: sqlite3.Connection, run_id: str, after_seq: int = 0
) -> list[sqlite3.Row]:
    """按 seq 升序返回 `seq > after_seq` 的事件（SSE 重连续播的数据源）。"""
    return db.execute(
        """
        SELECT id, run_id, seq, event_type, payload_json, created_at
        FROM agent_events
        WHERE run_id = ? AND seq > ?
        ORDER BY seq ASC
        """,
        (run_id, after_seq),
    ).fetchall()
