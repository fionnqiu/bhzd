"""FastAPI 依赖：数据库连接、会话加载、角色校验、CSRF 防护。

会话隔离（NF4）：学生/教师/内容管理员用 `bhzd_session` cookie（user_sessions
表），系统管理员用独立的 `bhzd_admin_session` cookie（admin_sessions 表），
两套互不承认。

CSRF 令牌稳定化（008 迁移后）：会话行直接保存原始 CSRF 令牌（csrf_token 列），
一次会话期内固定不变——此前"每次 GET /api/auth/session 轮换"会让多标签页
互相顶掉令牌。比对走 hmac.compare_digest；迁移前的存量会话（该列为 NULL）
回退到旧的 csrf_token_hash 哈希比对路径，保持向后兼容。
"""

from __future__ import annotations

import hmac
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterator

from fastapi import Depends, Request

from . import db as db_module
from .config import get_config
from .db import utc_now_iso
from .errors import ApiError
from .security import hash_token

USER_SESSION_COOKIE = "bhzd_session"
ADMIN_SESSION_COOKIE = "bhzd_admin_session"


@dataclass
class CurrentUser:
    """一次请求解析出的登录主体：用户行 + 所属会话的关键信息。

    csrf_token_raw 为 008 迁移后的稳定原始令牌；legacy 会话该列为 NULL，
    此时 CSRF 校验回退到 csrf_token_hash 哈希比对（见 csrf_protect）。
    """

    user: sqlite3.Row
    session_id: str
    csrf_token_hash: str
    is_admin_session: bool = False
    csrf_token_raw: str | None = None


def get_db() -> Iterator[sqlite3.Connection]:
    """每请求一个连接的 FastAPI 依赖；请求结束确保关闭。"""
    conn = db_module.connect(get_config().resolved_database_path)
    try:
        yield conn
    finally:
        conn.close()


def _unauthenticated() -> None:
    raise ApiError(401, "UNAUTHORIZED", "请先登录")


def _load_valid_session(
    conn: sqlite3.Connection, table: str, token: str
) -> sqlite3.Row | None:
    """按令牌哈希查会话，并检查吊销与过期（过期/吊销一律视为不存在）。"""
    # table 只允许内部传入的两个固定表名，不存在注入面
    session = conn.execute(
        f"SELECT * FROM {table} WHERE token_hash = ?", (hash_token(token),)
    ).fetchone()
    if session is None or session["revoked_at"] is not None:
        return None
    if session["expires_at"] <= utc_now_iso():
        return None
    return session


def _load_active_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or user["status"] != "active":
        return None
    return user


def _session_csrf_raw(session: sqlite3.Row) -> str | None:
    """取会话行里的原始 CSRF 令牌；列不存在（未跑 008 迁移的旧库）时按 NULL 处理。"""
    return session["csrf_token"] if "csrf_token" in session.keys() else None


def _build_current_user(
    user: sqlite3.Row, session: sqlite3.Row, is_admin_session: bool = False
) -> CurrentUser:
    """从用户行 + 会话行组装 CurrentUser（三个入口共用，避免漏带 csrf_token_raw）。"""
    return CurrentUser(
        user=user,
        session_id=session["id"],
        csrf_token_hash=session["csrf_token_hash"],
        is_admin_session=is_admin_session,
        csrf_token_raw=_session_csrf_raw(session),
    )


def get_current_user(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> CurrentUser:
    """加载学生/教师/内容管理员会话（`bhzd_session` cookie）。"""
    token = request.cookies.get(USER_SESSION_COOKIE)
    if not token:
        _unauthenticated()
    session = _load_valid_session(conn, "user_sessions", token)
    if session is None:
        _unauthenticated()
    user = _load_active_user(conn, session["user_id"])
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "账号不可用，请重新登录")
    return _build_current_user(user, session)


def get_admin_user(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> CurrentUser:
    """加载系统管理员会话（`bhzd_admin_session` cookie），且角色必须是 system_admin。"""
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        _unauthenticated()
    session = _load_valid_session(conn, "admin_sessions", token)
    if session is None:
        _unauthenticated()
    user = _load_active_user(conn, session["user_id"])
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "账号不可用，请重新登录")
    if user["role"] != "system_admin":
        # /api/admin/* 仅认管理端会话 + system_admin 角色（蓝图 §4）
        raise ApiError(403, "FORBIDDEN", "需要系统管理员权限")
    return _build_current_user(user, session, is_admin_session=True)


def require_verified_user(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """邮箱验证门（PRD-06 §3.2）：未验证邮箱禁止使用 Agent / RAG 问答等核心能力。

    各业务路由按需 `Depends(require_verified_user)`；认证类路由（重发验证邮件等）不得使用。
    """
    if current.user["email_verified_at"] is None:
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "请先完成邮箱验证后再使用此功能")
    return current


STUDENT_PORTAL_ROLES = ("student", "content_admin", "system_admin")


def require_student_portal_user(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Authorize the learner shell without changing the shared session dependency.

    Teacher APIs still use ``get_current_user`` directly, so making that base
    dependency role-aware would break the teacher portal.  Keeping the learner
    policy in this explicit boundary also prevents a teacher from bypassing the
    frontend route guard by calling student APIs directly.
    """
    if current.user["role"] not in STUDENT_PORTAL_ROLES:
        raise ApiError(403, "FORBIDDEN", "无权访问学生端功能")
    return current


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    """角色校验依赖工厂：`Depends(require_role("teacher", "content_admin"))`。"""

    def dependency(
        current: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current.user["role"] not in roles:
            raise ApiError(403, "FORBIDDEN", "没有权限执行此操作")
        return current

    return dependency


def _load_any_session(request: Request, conn: sqlite3.Connection) -> CurrentUser | None:
    """按请求携带的 cookie 加载任一类会话（管理端优先），供 CSRF 校验复用。"""
    admin_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if admin_token:
        session = _load_valid_session(conn, "admin_sessions", admin_token)
        if session is not None:
            user = _load_active_user(conn, session["user_id"])
            if user is not None:
                return _build_current_user(user, session, is_admin_session=True)
    user_token = request.cookies.get(USER_SESSION_COOKIE)
    if user_token:
        session = _load_valid_session(conn, "user_sessions", user_token)
        if session is not None:
            user = _load_active_user(conn, session["user_id"])
            if user is not None:
                return _build_current_user(user, session)
    return None


def csrf_protect(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> CurrentUser:
    """变更类请求的 CSRF 防护：必须携带与会话匹配的 `x-csrf-token` 头。

    优先比对会话行上的原始令牌（008 起登录时落库、会话期内不变）；
    原始令牌为 NULL 的 legacy 会话回退到 csrf_token_hash 哈希比对。
    同时完成会话加载，因此路由可直接把返回值当 CurrentUser 用，
    不必再叠一个 get_current_user 依赖。
    """
    current = _load_any_session(request, conn)
    if current is None:
        _unauthenticated()
    presented = request.headers.get("x-csrf-token", "")
    if not presented:
        raise ApiError(403, "CSRF_TOKEN_INVALID", "安全校验失败，请刷新页面后重试")
    if current.csrf_token_raw:
        ok = hmac.compare_digest(current.csrf_token_raw, presented)
    else:
        # legacy 会话（008 迁移前建立）：库里只有哈希，按旧口径比对
        ok = hmac.compare_digest(current.csrf_token_hash, hash_token(presented))
    if not ok:
        raise ApiError(403, "CSRF_TOKEN_INVALID", "安全校验失败，请刷新页面后重试")
    return current
