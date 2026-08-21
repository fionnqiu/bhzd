"""工具注册表（蓝图 §9 / PRD-05 §6 工具契约）。

要点（为什么这样设计）：
- `TOOLS` 是普通 dict 而非构建函数产物：测试可以整体 monkeypatch 替换
  （编排器单测用 stub 工具），运行期也不隐藏状态。
- 读工具只有 `handler`；写工具必须同时提供 `preview`（确认门预览载荷）
  与 `apply`（确认后真正落库）——这是"写操作必须经确认门"（PRD-06 §6.4）
  在代码层的强制点：编排器对写工具只调 preview，apply 由确认路由触发。
- handler 同步签名 `fn(ctx) -> dict`：SQLite 操作本身是同步的，跨域
  调用（graphx/diagnosis 等）也都是同步函数，异步编排层直接调用即可。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """一次工具调用的上下文。

    db 由编排器/确认路由持有的连接传入（工具不得自行关连接）；
    args 为计划步骤或确认记录里的原始参数。
    """

    db: sqlite3.Connection
    config: Any
    user_row: Any
    run_row: Any
    conversation_row: Any
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    permission: str  # "read" | "write"
    auto_execute: bool
    description: str
    handler: Callable[[ToolContext], dict[str, Any]] | None = None
    preview: Callable[[ToolContext], dict[str, Any]] | None = None
    apply: Callable[[ToolContext], dict[str, Any]] | None = None


def emit_telemetry(db: sqlite3.Connection, user_id: str, name: str, props: dict) -> None:
    """惰性调用 B1 telemetry；未就绪或失败仅记日志，绝不阻断工具主流程。"""
    try:
        from ..telemetry import emit_event  # B1，惰性导入
    except ImportError:
        return
    try:
        emit_event(db, user_id, name, props)
    except Exception:
        logger.warning("埋点 %s 写入失败", name, exc_info=True)


def _build_tools() -> dict[str, ToolSpec]:
    from . import (
        course_search,
        diagnostic_tools,
        graph_reason,
        learning_tools,
        mastery_tools,
        rag_admin_tools,
        rag_tools,
        task_tools,
    )

    specs = [
        course_search.SPEC,
        graph_reason.SPEC,
        task_tools.PREVIEW_SPEC,
        task_tools.CREATE_SPEC,
        diagnostic_tools.PREVIEW_SPEC,
        diagnostic_tools.SAVE_SUMMARY_SPEC,
        mastery_tools.SPEC,
        rag_tools.SEARCH_SPEC,
        rag_tools.ANSWER_SPEC,
        rag_tools.PREVIEW_UPLOAD_SPEC,
        rag_admin_tools.CREATE_DOCUMENT_SPEC,
        rag_admin_tools.REINDEX_DOCUMENT_SPEC,
        rag_admin_tools.PUBLISH_DOCUMENT_SPEC,
        rag_admin_tools.ARCHIVE_DOCUMENT_SPEC,
        rag_admin_tools.SAVE_EVAL_CASE_SPEC,
        learning_tools.TASK_AUTO_CREATE_SPEC,
        learning_tools.PROGRESS_RECORD_SPEC,
        learning_tools.MASTERY_SYNC_SPEC,
        learning_tools.EXERCISE_REVIEW_SPEC,
    ]
    return {spec.name: spec for spec in specs}


# 蓝图 §9 全量工具表（测试可 monkeypatch 整个 dict 或单项）
TOOLS: dict[str, ToolSpec] = _build_tools()


def get(name: str) -> ToolSpec:
    """按名取工具；未注册抛 KeyError（编排器捕获后走 run.failed）。"""
    return TOOLS[name]
