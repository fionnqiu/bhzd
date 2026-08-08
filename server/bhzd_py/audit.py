"""审计日志写入（NF8 / 蓝图 §4）。

审核/发布/归档/删除/权限变更/模型配置变更/参数修改都必须调用 `audit()`。
审计记录只能追加，不提供修改入口——这是审计可信的前提。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .db import utc_now_iso


def _to_json(value: Any) -> str | None:
    """before/after 快照统一 JSON 序列化；None 保持 NULL（表示无快照）。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def audit(
    conn: sqlite3.Connection,
    actor: Any,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """写一条 audit_logs 并返回记录 id。

    `actor` 可以是 users 表行（sqlite3.Row / dict，取 id 与 role）、用户 id
    字符串，或 None（系统动作，actor_id 落 NULL）。
    """
    actor_id: str | None = None
    actor_role: str | None = None
    if isinstance(actor, str):
        actor_id = actor
    elif actor is not None:
        # sqlite3.Row 与 dict 都支持下标访问
        actor_id = actor["id"]
        actor_role = actor["role"] if "role" in actor.keys() else None  # type: ignore[attr-defined]
    record_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO audit_logs
          (id, actor_id, actor_role, action, target_type, target_id,
           before_json, after_json, ip, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            actor_id,
            actor_role,
            action,
            target_type,
            target_id,
            _to_json(before),
            _to_json(after),
            ip,
            user_agent,
            utc_now_iso(),
        ),
    )
    conn.commit()
    return record_id
