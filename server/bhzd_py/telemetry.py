"""埋点采集（蓝图 §8）：事件白名单 + 统一写入入口。

关键决策（为什么）：
- 白名单是唯一的合法性来源：客户端与后端各域都通过 `emit_event` 写入，
  未在白名单内的事件名一律静默丢弃——埋点是观测数据，宁可丢点也不能让
  脏事件名污染分析口径。
- `emit_event` 绝不向请求路径抛异常：埋点失败（如磁盘满、锁竞争）不应让
  用户的真实操作失败，只记一条告警日志。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from .db import utc_now_iso

logger = logging.getLogger(__name__)

# 蓝图 §8（v3.0 §16）的 14 个合法事件名；新增事件必须先改蓝图再改这里
EVENT_WHITELIST: frozenset[str] = frozenset(
    {
        "preset_clicked",
        "goal_submitted",
        "agent_plan_shown",
        "rag_query_submitted",
        "rag_retrieval_completed",
        "citation_clicked",
        "task_preview_created",
        "task_created",
        "diagnostic_uploaded",
        "diagnostic_summary_saved",
        "mastery_updated",
        "rag_document_uploaded",
        "rag_document_published",
        "rag_eval_run_completed",
    }
)


def emit_event(
    db: sqlite3.Connection,
    user_id: str | None,
    name: str,
    props: dict[str, Any] | None = None,
) -> bool:
    """写入一条 analytics_events；返回是否真正落库（未知事件名直接丢弃）。

    本函数是"尽力而为"的观测写入：任何异常都只记日志、返回 False，
    绝不向调用方的请求路径传播（见模块 docstring）。
    """
    if name not in EVENT_WHITELIST:
        return False
    try:
        db.execute(
            "INSERT INTO analytics_events (user_id, event_name, props_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                user_id,
                name,
                json.dumps(props or {}, ensure_ascii=False, default=str),
                utc_now_iso(),
            ),
        )
        db.commit()
        return True
    except Exception:  # 埋点失败不许影响业务请求
        logger.warning("埋点写入失败（已忽略）: event=%s", name, exc_info=True)
        return False
