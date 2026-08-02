"""Agent SSE 事件常量与持久化（蓝图 §7 / PRD-05 §5）。

为什么事件要落库（agent_events 表）而不是只在内存里推送：
前端断线后需要用 `after_seq` 重连续播（蓝图 §7），这要求每个事件都有
单调递增的 seq 且可回放，因此 emit 即 INSERT，SSE 层只做查询转发。

注意：`stream.end` 不是持久化事件，只是 SSE 流收尾标记（前端据此关闭
EventSource），因此不出现在 §7 常量清单里，由 SSE 路由自行发送。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import utc_now_iso

# ---- 蓝图 §7 事件名契约（逐字） ----
RUN_STARTED = "run.started"
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
