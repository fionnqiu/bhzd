"""Agent 域测试公共助手（不改动共享 conftest.py，避免跨域夹具冲突）。

- 直接 DB 插入用户/会话：auth 路由属 B1，当前缺席，API 登录不可用；
  这里绕过 API 直接造已验证用户 + user_sessions 行（deps.py 只认表数据）。
- stub 工具表：编排器单测与 API 测试都不应依赖 B2/B4 真实域。
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from bhzd_py import db as db_module
from bhzd_py.db import utc_now_iso
from bhzd_py.security import hash_token
from bhzd_py.tools import registry
from bhzd_py.tools.registry import ToolSpec

TEST_CSRF = "test-csrf-token"


def make_db(path: str) -> sqlite3.Connection:
    conn = db_module.connect(path)
    db_module.apply_migrations(conn)
    return conn


def insert_user(
    db: sqlite3.Connection,
    email: str = "student@test.local",
    *,
    role: str = "student",
    verified: bool = True,
) -> str:
    user_id = uuid.uuid4().hex
    now = utc_now_iso()
    db.execute(
        """
        INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (user_id, email, email.split("@")[0], role,
         now if verified else None, now, now),
    )
    db.commit()
    return user_id


def insert_session(db: sqlite3.Connection, user_id: str) -> str:
    """插入一条 user_sessions 并返回明文令牌（token_hash 有唯一约束，
    同库多用户必须各自独立令牌）。"""
    now = utc_now_iso()
    token = f"test-session-{uuid.uuid4().hex}"
    db.execute(
        """
        INSERT INTO user_sessions
          (id, user_id, token_hash, csrf_token_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, user_id, hash_token(token),
         hash_token(TEST_CSRF), now, "2999-01-01T00:00:00+00:00"),
    )
    db.commit()
    return token


def insert_run(
    db: sqlite3.Connection, user_id: str, input_text: str,
    *, status: str = "running",
) -> tuple[str, str]:
    """直接插入 会话+运行 行，返回 (run_id, conversation_id)。"""
    now = utc_now_iso()
    conversation_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO conversations (id, user_id, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (conversation_id, user_id, input_text[:30], now, now),
    )
    run_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, conversation_id, user_id, status, input_text, now),
    )
    db.commit()
    return run_id, conversation_id


def _stub_read(name: str, payload: dict | None = None) -> ToolSpec:
    def handler(ctx):
        result = {"tool": name, "args": dict(ctx.args)}
        if payload:
            result.update(payload)
        return result

    return ToolSpec(name=name, permission="read", auto_execute=True,
                    description="stub", handler=handler)


def _stub_write(name: str, apply_payload: dict | None = None) -> ToolSpec:
    def preview(ctx):
        return {"action": name, "summary": f"{name} 预览", "args": dict(ctx.args)}

    def apply(ctx):
        result = {"applied": name, "args": dict(ctx.args)}
        if apply_payload:
            result.update(apply_payload)
        return result

    return ToolSpec(name=name, permission="write", auto_execute=False,
                    description="stub", preview=preview, apply=apply)


def install_stub_tools(monkeypatch) -> dict[str, ToolSpec]:
    """用 stub 工具替换整张注册表（覆盖编排器计划用到的全部工具名）。"""
    stubs = {
        "rag.search": _stub_read("rag.search", {"hits": [], "hit_count": 0}),
        "rag.answer": _stub_read("rag.answer", {
            "answer": "这是基于资料的模板回答。",
            "citations": [{"document_id": "d1", "title": "NER 规范", "page_start": 1}],
        }),
        "graph.reason": _stub_read("graph.reason", {
            "nodes": [{"id": "CAP-AUD-WAKE-COMMAND-001", "label": "唤醒词标注", "type": "CAP"}],
            "cap_ids": ["CAP-AUD-WAKE-COMMAND-001"],
        }),
        "course.search": _stub_read("course.search", {"units": []}),
        "task.preview": _stub_read("task.preview"),
        "task.create": _stub_write("task.create", {"task_id": "task-stub-1"}),
        "diagnostic.preview": _stub_read("diagnostic.preview", {
            "report": {"weak_cap_ids": ["CAP-AUD-WAKE-COMMAND-001"], "error_count": 2},
        }),
        "diagnostic.save_summary": _stub_write("diagnostic.save_summary"),
        "mastery.update": _stub_write("mastery.update"),
    }
    monkeypatch.setattr(registry, "TOOLS", stubs)
    return stubs


def make_auth_client(tmp_db_path: str, *, verified: bool = True,
                     email: str = "student@test.local"):
    """创建带登录态的 TestClient。返回 (client, user_id)。"""
    from fastapi.testclient import TestClient

    from bhzd_py.app import create_app

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, email, verified=verified)
        token = insert_session(db, user_id)
    finally:
        db.close()
    client = TestClient(create_app())
    client.cookies.set("bhzd_session", token)
    return client, user_id


def csrf_headers() -> dict[str, str]:
    return {"x-csrf-token": TEST_CSRF}


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def wait_run_status(db_path: str, run_id: str, want: tuple[str, ...],
                    timeout: float = 5.0) -> str:
    """轮询运行状态（后台编排任务在另一线程推进，测试只能等）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = open_db(db_path)
        try:
            row = conn.execute(
                "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        if row and row["status"] in want:
            return row["status"]
        time.sleep(0.1)
    raise AssertionError(f"运行 {run_id} 未在 {timeout}s 内进入 {want}")


def fetch_events(db_path: str, run_id: str) -> list[dict]:
    conn = open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT seq, event_type, payload_json FROM agent_events WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"seq": r["seq"], "event_type": r["event_type"],
         "payload": json.loads(r["payload_json"])}
        for r in rows
    ]
