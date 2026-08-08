"""站内通知路由：全角色（学生/教师/管理员）读取与管理自己的通知。

为什么单独成模块：通知是跨域自有数据（任何登录用户都有），不专属于
teacher/profile 任一域；蓝图 §2.1 的 router 按域划分，新增域对应新模块。
注意：app.py 的 ROUTER_MODULES 是地基清单（Wave1 契约），需要集成阶段
追加 "notifications" 一行后本路由才会被自动挂载。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db
from ..errors import ApiError

router = APIRouter()


def _notification_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "body": row["body"],
        "ref_type": row["ref_type"],
        "ref_id": row["ref_id"],
        "read_at": row["read_at"],
        "created_at": row["created_at"],
    }


@router.get("/api/notifications")
def list_notifications(
    unread: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """自己的通知列表（新→旧）；unread=1 时只返回未读。"""
    where = "user_id = ?" + (" AND read_at IS NULL" if unread == 1 else "")
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM notifications WHERE {where}",
        (current.user["id"],),
    ).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM notifications WHERE {where} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (current.user["id"], limit, offset),
    ).fetchall()
    return {"items": [_notification_dto(r) for r in rows], "total": total}


@router.get("/api/notifications/unread-count")
def unread_count(
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """未读数（前端角标轮询用，保持极轻）。"""
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (current.user["id"],),
    ).fetchone()["n"]
    return {"unread": n}


@router.post("/api/notifications/{notification_id}/read")
def mark_read(
    notification_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """标记单条已读（幂等）。

    他人的通知按 404 处理而非 403：不暴露该通知 id 是否真实存在。
    """
    row = conn.execute(
        "SELECT * FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, current.user["id"]),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "通知不存在")
    if row["read_at"] is None:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE id = ?",
            (utc_now_iso(), notification_id),
        )
        conn.commit()
    return {"id": notification_id, "read": True}


@router.post("/api/notifications/read-all")
def mark_all_read(
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """一键全部已读，返回实际更新的条数。"""
    cursor = conn.execute(
        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
        (utc_now_iso(), current.user["id"]),
    )
    conn.commit()
    return {"updated": cursor.rowcount}
