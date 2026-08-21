"""任务草稿真实链路验证（直连 127.0.0.1:8787 运行中后端）。

步骤：直写验证用户+会话到运行库 → 登录态调 API：发起任务生成 → 轮询完成 →
会话详情取草稿 → 同步（两次，验幂等）→ 核对任务与内容行 → 清理验证数据。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid

import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8787"
DB = "var/bhzd.sqlite"
EMAIL = "draft-verify@test.local"
CSRF = "verify-csrf-token"

sys.path.insert(0, "server")
from bhzd_py.security import hash_token  # noqa: E402
from bhzd_py.db import utc_now_iso  # noqa: E402


def db_exec(sql: str, params: tuple = (), fetch: bool = False):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows
    finally:
        conn.close()


def api(method: str, path: str, body: dict | None = None, token: str = "", csrf: str = ""):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Cookie", f"bhzd_session={token}")
    if csrf:
        req.add_header("x-csrf-token", csrf)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    # 1) 验证用户 + 会话令牌
    user_id = uuid.uuid4().hex
    token = f"verify-session-{uuid.uuid4().hex}"
    now = utc_now_iso()
    db_exec(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at)"
        " VALUES (?, ?, ?, 'student', 'active', ?, ?, ?)",
        (user_id, EMAIL, "draft-verify", now, now, now),
    )
    db_exec(
        "INSERT INTO user_sessions (id, user_id, token_hash, csrf_token_hash, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, '2999-01-01T00:00:00+00:00')",
        (uuid.uuid4().hex, user_id, hash_token(token), hash_token(CSRF), now),
    )

    created_task_ids: list[str] = []
    try:
        # 2) 发起任务生成（生成前澄清：无草稿则按澄清问题跟答，最多 3 轮）
        status, run = api("POST", "/api/runs", {"input": "帮我生成一个图像标注的学习任务"}, token, CSRF)
        assert status == 202, (status, run)
        conv_id = run["conversation_id"]

        def wait_completed(rid: str) -> dict:
            for _ in range(60):
                status, detail = api("GET", f"/api/runs/{rid}", token=token)
                assert status == 200, (status, detail)
                if detail["run"]["status"] in ("completed", "failed"):
                    assert detail["run"]["status"] == "completed", detail["run"]
                    return detail
                time.sleep(1)
            raise AssertionError(f"run {rid} 未在 60s 内完成")

        answers = ["框选", "零基础", "都可以"]
        drafts: dict = {}
        for turn in range(4):
            wait_completed(run["run_id"] if turn == 0 else follow["run_id"])
            status, conv = api("GET", f"/api/conversations/{conv_id}", token=token)
            assert status == 200, (status, conv)
            drafts = conv.get("task_drafts_by_run") or {}
            if drafts:
                break
            assert turn < 3, "澄清超过 3 轮仍未生成（封顶失效）"
            question = conv["messages"][-1]["content"]
            print(f"intake turn {turn + 1} question:", question[:60])
            status, follow = api("POST", "/api/runs",
                                 {"input": answers[turn], "conversation_id": conv_id}, token, CSRF)
            assert status == 202, (status, follow)
        assert drafts, "未拿到任务草稿"
        print("draft ready after intake turns")
        projection = next(iter(drafts.values()))
        draft_id = projection["id"]
        assert projection["status"] == "draft"
        assert projection["cards"], projection
        print("draft:", draft_id, "| cards:", len(projection["cards"]),
              "| title:", projection["cards"][0].get("title"))
        assert projection["cards"][0]["knowledge_points"], "模板/LLM 卡都应有学习内容"
        assert projection["cards"][0]["exercises"], "模板/LLM 卡都应有练习"

        # 5) 同步（第一次）
        status, synced = api("POST", f"/api/task-drafts/{draft_id}/sync", {}, token, CSRF)
        assert status == 200, (status, synced)
        assert synced["status"] == "synced" and synced["already_synced"] is False, synced
        created_task_ids = synced["task_ids"]
        print("synced -> tasks:", created_task_ids)

        # 6) 同步（第二次，幂等）
        status, again = api("POST", f"/api/task-drafts/{draft_id}/sync", {}, token, CSRF)
        assert status == 200 and again["already_synced"] is True, (status, again)
        assert again["task_ids"] == created_task_ids

        # 7) 任务可见且带内容
        status, tasks = api("GET", "/api/tasks", token=token)
        assert status == 200
        titles = {t["id"]: t["title"] for t in tasks["items"]}
        for tid in created_task_ids:
            assert tid in titles, titles
        rows = db_exec(
            "SELECT (SELECT COUNT(*) FROM task_knowledge_points WHERE task_id = ?) AS kp,"
            " (SELECT COUNT(*) FROM task_exercises WHERE task_id = ?) AS ex",
            (created_task_ids[0], created_task_ids[0]),
            fetch=True,
        )
        assert rows[0]["kp"] > 0 and rows[0]["ex"] > 0, dict(rows[0])
        print("task content rows ok:", dict(rows[0]))

        # 8) 无 CSRF / 他人草稿的负向校验
        status, _ = api("POST", f"/api/task-drafts/{draft_id}/sync", {}, token)
        assert status == 403, status
        print("csrf negative check ok")

        print("REAL-CHAIN VERIFICATION PASSED")
    finally:
        # 清理验证数据
        for tid in created_task_ids:
            db_exec("DELETE FROM task_knowledge_points WHERE task_id = ?", (tid,))
            db_exec("DELETE FROM task_exercises WHERE task_id = ?", (tid,))
            db_exec("DELETE FROM learning_tasks WHERE id = ?", (tid,))
        db_exec("DELETE FROM task_drafts WHERE user_id = ?", (user_id,))
        db_exec("DELETE FROM agent_events WHERE run_id IN (SELECT id FROM agent_runs WHERE user_id = ?)", (user_id,))
        db_exec("DELETE FROM tool_calls WHERE run_id IN (SELECT id FROM agent_runs WHERE user_id = ?)", (user_id,))
        db_exec("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)", (user_id,))
        db_exec("DELETE FROM agent_runs WHERE user_id = ?", (user_id,))
        db_exec("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        db_exec("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        db_exec("DELETE FROM users WHERE id = ?", (user_id,))
        print("verification data cleaned up")


if __name__ == "__main__":
    main()
