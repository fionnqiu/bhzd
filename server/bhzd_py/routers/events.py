"""埋点采集端点（蓝图 §6.7/§8）。

设计要点（为什么）：
- 事件名走 §8 白名单（14 个），未知事件名按契约**静默丢弃**——埋点客户端
  版本可能先于后端发布，严格报错会让旧客户端的其余事件也一起失败。
- 仅要求登录（get_current_user），不强制 CSRF：埋点是只追加的观测写入，
  无状态变更风险；强制 CSRF 会让页面卸载前的最后一拍埋点（sendBeacon 类）
  因拿不到令牌而丢失。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import CurrentUser, get_current_user, get_db
from ..telemetry import emit_event

router = APIRouter()


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    props: dict[str, Any] = Field(default_factory=dict)


class EventsBatchIn(BaseModel):
    # 批量上限防滥用：单帧 100 条足够前端聚合上报
    events: list[EventIn] = Field(max_length=100)


@router.post("/api/events", status_code=202)
def post_events(
    body: EventsBatchIn,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, int]:
    accepted = 0
    for event in body.events:
        # emit_event 内部做白名单判断且绝不抛异常（见 telemetry 模块 docstring）
        if emit_event(conn, current.user["id"], event.name, event.props):
            accepted += 1
    return {"accepted": accepted}
