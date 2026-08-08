"""站内通知写入助手（PRD-06 §10.1 等触达场景的公共入口）。

事务约定（为什么不 commit）：notify/notify_many 只执行 INSERT，**不 commit**——
通知必须与触发它的业务写入同生共死（例如教师发布任务：学生任务副本与
通知要么都落库、要么都回滚，不能出现"任务没发成却收到通知"），提交时机
交给调用方的事务边界。

其他域（如诊断域）需要发通知时：`from ..notify import notify, notify_many`，
在自己的业务提交点统一 commit 即可，不要在本模块内补 commit。
"""

from __future__ import annotations

import sqlite3
import uuid

from .db import utc_now_iso


def notify(
    db: sqlite3.Connection,
    user_id: str,
    type: str,
    title: str,
    body: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> str:
    """写一条站内通知，返回通知 id（不 commit，见模块 docstring 的事务约定）。"""
    notification_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO notifications (id, user_id, type, title, body, ref_type, ref_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (notification_id, user_id, type, title, body, ref_type, ref_id, utc_now_iso()),
    )
    return notification_id


def notify_many(
    db: sqlite3.Connection,
    user_ids: list[str],
    type: str,
    title: str,
    body: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> list[str]:
    """给一组用户各写一条同内容通知，返回通知 id 列表（不 commit）。

    user_ids 先去重（保序）：班级成员列表等来源可能出现重复 id，
    同一学生不应为同一件事收到两条相同通知。
    """
    ids: list[str] = []
    for user_id in dict.fromkeys(user_ids):
        ids.append(notify(db, user_id, type, title, body, ref_type, ref_id))
    return ids
