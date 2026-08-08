"""学习域/教师域 API 测试的公共辅助：直接建库内用户与会话（不依赖 B1 的 auth 路由）。

为什么不走 /api/auth/register+login：auth 路由由 B1 并行开发，本域测试必须
离线自足；会话直接 INSERT user_sessions（与 deps.py 读取口径完全一致），
测到的仍是真实的会话加载与 CSRF 校验链路。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from bhzd_py import db as db_module
from bhzd_py.app import create_app
from bhzd_py.security import generate_token, hash_token


def make_user(
    conn: sqlite3.Connection,
    email: str,
    name: str,
    role: str = "student",
    verified: bool = True,
) -> str:
    """直接 INSERT 一个用户（verified=False 时 email_verified_at 为 NULL）。"""
    user_id = uuid.uuid4().hex
    now = db_module.utc_now_iso()
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
        (user_id, email, name, role, now if verified else None, now, now),
    )
    conn.commit()
    return user_id


def make_session(conn: sqlite3.Connection, user_id: str) -> tuple[str, str]:
    """直接 INSERT 一个有效会话，返回 (会话 token, csrf token) 明文。"""
    token = generate_token()
    csrf = generate_token()
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO user_sessions (id, user_id, token_hash, csrf_token_hash, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            user_id,
            hash_token(token),
            hash_token(csrf),
            now.isoformat(),
            (now + timedelta(hours=72)).isoformat(),
        ),
    )
    conn.commit()
    return token, csrf


class Api:
    """TestClient + 建库连接的组合夹具；login_as 切换当前登录身份。"""

    def __init__(self, conn: sqlite3.Connection, client: TestClient) -> None:
        self.conn = conn
        self.client = client

    def login_as(
        self,
        email: str,
        name: str = "测试同学",
        role: str = "student",
        verified: bool = True,
    ) -> dict:
        """建用户 + 建会话 + 设置 cookie，返回 {user_id, csrf, headers, token}。"""
        user_id = make_user(self.conn, email, name, role=role, verified=verified)
        token, csrf = make_session(self.conn, user_id)
        self.client.cookies.set("bhzd_session", token)
        return {
            "user_id": user_id,
            "csrf": csrf,
            "token": token,
            "headers": {"x-csrf-token": csrf},
        }

    def act_as(self, user: dict) -> dict:
        """切回 login_as 之前返回的某个身份（cookie 是单槽位，多用户测试必须显式切换）。"""
        self.client.cookies.set("bhzd_session", user["token"])
        return user

    def logout(self) -> None:
        self.client.cookies.clear()


@pytest.fixture()
def api(tmp_db_path):
    """每测试独立临时库：先迁移，再让 TestClient 走完整 lifespan。"""
    conn = db_module.connect(tmp_db_path)
    db_module.apply_migrations(conn)
    with TestClient(create_app()) as client:
        yield Api(conn, client)
    conn.close()
