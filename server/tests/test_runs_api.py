"""runs 路由 API 测试：202 启动 / 终态轮询 / SSE 回放 / 属主隔离 / 会话 CRUD。"""

from __future__ import annotations

import json

import pytest

from bhzd_py.agent import events as agent_events
from bhzd_py.db import utc_now_iso

from _agent_helpers import (
    csrf_headers,
    insert_run,
    install_stub_tools,
    make_auth_client,
    open_db,
    wait_run_status,
)


@pytest.fixture()
def client(tmp_db_path, monkeypatch):
    install_stub_tools(monkeypatch)
    client, user_id = make_auth_client(tmp_db_path)
    client.test_user_id = user_id  # type: ignore[attr-defined]
    yield client
    client.close()


def _start_run(client, text="什么是 NER 标注规范？"):
    response = client.post("/api/runs", json={"input": text}, headers=csrf_headers())
    assert response.status_code == 202, response.text
    return response.json()


def test_create_run_202_and_completes(client, tmp_db_path):
    body = _start_run(client)
    assert body["run_id"] and body["conversation_id"]
    status = wait_run_status(tmp_db_path, body["run_id"], ("completed", "failed"))
    assert status == "completed"

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["plan"]["steps"]
    assert payload["summary"]
    assistant_message = payload["assistant_message"]
    assert assistant_message is not None
    assert assistant_message["run_id"] == body["run_id"]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"]
    assert set(assistant_message) == {"id", "run_id", "role", "content", "created_at"}
    # 执行轨迹：工具名/状态/耗时/是否写操作（PRD-01 §3.6）
    trace = payload["tool_calls"][0]
    assert {"tool", "status", "duration_ms", "is_write"} <= set(trace)
    assert "args" not in trace and "result" not in trace
    assert trace["execution_kind"] == "tool"
    assert "具体值已隐藏" in trace["input_summary"]
    assert payload["plan"]["steps"]
    assert all("args" not in step for step in payload["plan"]["steps"])


def test_run_detail_returns_null_assistant_message_before_persistence(client, tmp_db_path):
    """SSE recovery must distinguish an unfinished run from an empty response."""
    conn = open_db(tmp_db_path)
    try:
        run_id, _ = insert_run(conn, client.test_user_id, "等待生成的回复")  # type: ignore[attr-defined]
    finally:
        conn.close()

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["assistant_message"] is None


def test_conversation_detail_projects_safe_historical_activities(client, tmp_db_path):
    """History reload hides obsolete thinking frames while restoring real work."""

    conversation = client.post(
        "/api/conversations", json={"title": "历史步骤"}, headers=csrf_headers()
    ).json()
    run_id = "history-run"
    course_call_id = "course-call"
    task_call_id = "task-call"
    rag_call_id = "rag-call"
    confirmation_id = "history-confirmation"
    secret = "student-private-input"
    now = utc_now_iso()

    conn = open_db(tmp_db_path)
    try:
        conn.execute(
            """
            INSERT INTO agent_runs
              (id, conversation_id, user_id, status, input_text, created_at, completed_at)
            VALUES (?, ?, ?, 'completed', ?, ?, ?)
            """,
            (run_id, conversation["id"], client.test_user_id, secret, now, now),  # type: ignore[attr-defined]
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
            VALUES ('history-answer', ?, ?, 'assistant', '历史回答', ?)
            """,
            (conversation["id"], run_id, now),
        )
        conn.executemany(
            """
            INSERT INTO tool_calls
              (id, run_id, tool_name, permission, status, args_json, result_json,
               duration_ms, is_write, created_at, completed_at)
            VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    course_call_id,
                    run_id,
                    "course.search",
                    "read",
                    json.dumps({"query": secret}),
                    json.dumps({"result": secret}),
                    17,
                    0,
                    now,
                    now,
                ),
                (
                    task_call_id,
                    run_id,
                    "task.create",
                    "write",
                    json.dumps({"goal": secret}),
                    json.dumps({"created": secret}),
                    23,
                    1,
                    now,
                    now,
                ),
                (
                    rag_call_id,
                    run_id,
                    "rag.search",
                    "read",
                    json.dumps({"query": secret}),
                    json.dumps({"answer": secret}),
                    29,
                    0,
                    now,
                    now,
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO pending_confirmations
              (id, run_id, user_id, tool_call_id, action_type, preview_json,
               status, expires_at, created_at, resolved_at)
            VALUES (?, ?, ?, ?, 'task.create', ?, 'confirmed', ?, ?, ?)
            """,
            (
                confirmation_id,
                run_id,
                client.test_user_id,  # type: ignore[attr-defined]
                task_call_id,
                json.dumps({"preview": secret}),
                "2999-01-01T00:00:00+00:00",
                now,
                now,
            ),
        )
        conn.commit()

        # The fixtures intentionally include sensitive event payload fields. The
        # history DTO must rebuild its labels from trusted state, not replay them.
        legacy_understanding_seq = agent_events.emit_progress(
            conn,
            run_id,
            phase="understanding",
            status="completed",
            title=secret,
            activity_id=f"understanding:{run_id}",
        )
        planning_seq = agent_events.emit_progress(
            conn,
            run_id,
            phase="planning",
            status="completed",
            title=secret,
        )
        course_requested_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_REQUESTED,
            {
                "tool_call_id": course_call_id,
                "tool": "course.search",
                "args_summary": secret,
            },
        )
        course_completed_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": course_call_id,
                "tool": "course.search",
                "result": {"secret": secret},
            },
        )
        rag_requested_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_REQUESTED,
            {"tool_call_id": rag_call_id, "tool": "rag.search", "args_summary": secret},
        )
        rag_completed_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_COMPLETED,
            {"tool_call_id": rag_call_id, "tool": "rag.search", "result": {"secret": secret}},
        )
        task_requested_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_REQUESTED,
            {"tool_call_id": task_call_id, "tool": "task.create", "args_summary": secret},
        )
        confirmation_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.CONFIRMATION_REQUIRED,
            {
                "confirmation": {
                    "id": confirmation_id,
                    "action_type": "task.create",
                    "preview": {"secret": secret},
                }
            },
        )
        task_completed_seq = agent_events.emit(
            conn,
            run_id,
            agent_events.TOOL_CALL_COMPLETED,
            {
                "tool_call_id": task_call_id,
                "tool": "task.create",
                "result": {"secret": secret},
            },
        )
        answer_started_seq = agent_events.emit_progress(
            conn,
            run_id,
            phase="synthesis",
            status="running",
            title=secret,
            activity_id=f"answer:{run_id}",
        )
        answer_completed_seq = agent_events.emit_progress(
            conn,
            run_id,
            phase="synthesis",
            status="completed",
            title=secret,
            activity_id=f"answer:{run_id}",
        )
    finally:
        conn.close()

    response = client.get(f"/api/conversations/{conversation['id']}")
    assert response.status_code == 200
    activities = response.json()["activities_by_run"]
    assert all(
        entry["event_seq"] != legacy_understanding_seq
        for entry in activities[run_id]
    )
    assert activities == {
        run_id: [
            {
                "seq": planning_seq,
                "event_seq": planning_seq,
                "activity_id": f"history-planning:{run_id}",
                "stage": "planning",
                "status": "completed",
                "message": "执行计划已生成",
            },
            {
                "seq": course_requested_seq,
                "event_seq": course_completed_seq,
                "stage": "tool",
                "status": "completed",
                "message": "工具调用已完成",
                "tool": "course.search",
                "tool_call_id": course_call_id,
                "duration_ms": 17,
                "is_write": False,
            },
            {
                "seq": rag_requested_seq,
                "event_seq": rag_completed_seq,
                "stage": "tool",
                "status": "completed",
                "message": "工具调用已完成",
                "tool": "rag.search",
                "tool_call_id": rag_call_id,
                "duration_ms": 29,
                "is_write": False,
            },
            {
                "seq": task_requested_seq,
                "event_seq": task_completed_seq,
                "stage": "tool",
                "status": "completed",
                "message": "工具调用已完成",
                "tool": "task.create",
                "tool_call_id": task_call_id,
                "duration_ms": 23,
                "is_write": True,
            },
            {
                "seq": confirmation_seq,
                "event_seq": confirmation_seq,
                "activity_id": f"confirmation:{confirmation_id}",
                "stage": "confirmation",
                "status": "completed",
                "message": "确认已完成",
            },
            {
                "seq": answer_started_seq,
                "event_seq": answer_completed_seq,
                "activity_id": f"answer:{run_id}",
                "stage": "responding",
                "status": "completed",
                "message": "回答已生成",
            },
        ]
    }
    serialized = json.dumps(activities, ensure_ascii=False)
    assert secret not in serialized
    assert "rag.search" in serialized
    assert "args_summary" not in serialized
    assert '"result"' not in serialized
    assert "preview" not in serialized


def test_conversation_detail_keeps_empty_activity_map_for_legacy_history(client, tmp_db_path):
    """A message without durable visible events stays honest rather than fabricated."""

    conn = open_db(tmp_db_path)
    try:
        _, conversation_id = insert_run(conn, client.test_user_id, "旧会话")  # type: ignore[attr-defined]
    finally:
        conn.close()

    response = client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200
    assert response.json()["activities_by_run"] == {}


def test_conversation_detail_derives_an_activity_id_for_legacy_synthesis(client, tmp_db_path):
    """Pre-activity-id answers remain visible after a history reload."""

    conn = open_db(tmp_db_path)
    try:
        run_id, conversation_id = insert_run(
            conn,
            client.test_user_id,
            "旧版回答步骤",  # type: ignore[attr-defined]
        )
        now = utc_now_iso()
        conn.execute(
            "UPDATE agent_runs SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, run_id),
        )
        conn.commit()
        synthesis_seq = agent_events.emit_progress(
            conn,
            run_id,
            phase="synthesis",
            status="running",
            title="旧版回答正在生成",
        )
    finally:
        conn.close()

    response = client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200
    assert response.json()["activities_by_run"] == {
        run_id: [
            {
                "seq": synthesis_seq,
                "event_seq": synthesis_seq,
                "activity_id": f"history-answer:{run_id}",
                "stage": "responding",
                # Terminal state closes an old running event without fabricating a new row.
                "status": "completed",
                "message": "回答已生成",
            }
        ]
    }


def test_sse_replay_until_stream_end(client, tmp_db_path):
    body = _start_run(client)
    wait_run_status(tmp_db_path, body["run_id"], ("completed",))

    # 运行终态后请求 SSE：应回放全部持久化事件并以 stream.end 收尾
    response = client.get(f"/api/runs/{body['run_id']}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: run.started" in text
    assert "event: run.completed" in text
    assert "event: stream.end" in text
    # 帧格式：id/event/data 三段齐全，data 内含 seq（蓝图 §7）
    first_frame = text.strip().split("\n\n")[0]
    assert first_frame.startswith("id: 1\n")
    assert '"seq": 1' in first_frame

    # after_seq 续播：跳过前面的事件
    replay = client.get(f"/api/runs/{body['run_id']}/events?after_seq=2")
    assert "event: run.started" not in replay.text
    assert "event: stream.end" in replay.text

    # Last-Event-ID 头优先于 query
    replay2 = client.get(f"/api/runs/{body['run_id']}/events", headers={"Last-Event-ID": "2"})
    assert "event: run.started" not in replay2.text


def test_run_detail_owner_only(client, tmp_db_path, monkeypatch):
    body = _start_run(client)
    wait_run_status(tmp_db_path, body["run_id"], ("completed",))

    other, _ = make_auth_client(tmp_db_path, email="other@test.local")
    try:
        assert other.get(f"/api/runs/{body['run_id']}").status_code == 404
        assert other.get(f"/api/runs/{body['run_id']}/events").status_code == 404
    finally:
        other.close()


def test_runs_requires_csrf_and_verification(client, tmp_db_path, monkeypatch):
    # 缺 CSRF 头
    assert client.post("/api/runs", json={"input": "你好"}).status_code == 403
    # 未验证邮箱
    unverified, _ = make_auth_client(tmp_db_path, verified=False, email="newbie@test.local")
    try:
        response = unverified.post("/api/runs", json={"input": "你好"}, headers=csrf_headers())
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    finally:
        unverified.close()


def test_conversations_crud_and_soft_delete_audit(client, tmp_db_path):
    created = client.post(
        "/api/conversations",
        json={"title": "测试会话", "scenario_id": "SCN-IN-VEHICLE-001"},
        headers=csrf_headers(),
    )
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["scenario_id"] == "SCN-IN-VEHICLE-001"

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert any(i["id"] == conversation["id"] for i in listed.json()["items"])

    # 在该会话里跑一轮，详情应带消息
    detail = client.get(f"/api/conversations/{conversation['id']}")
    assert detail.status_code == 200
    assert "messages" in detail.json()

    # 软删除：会话 404、消息清空、审计行保留（PRD-06 §12.2）
    deleted = client.delete(f"/api/conversations/{conversation['id']}", headers=csrf_headers())
    assert deleted.status_code == 200
    assert client.get(f"/api/conversations/{conversation['id']}").status_code == 404

    conn = open_db(tmp_db_path)
    try:
        conv_row = conn.execute(
            "SELECT deleted_at FROM conversations WHERE id = ?", (conversation["id"],)
        ).fetchone()
        assert conv_row["deleted_at"] is not None
        msg_count = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
            (conversation["id"],),
        ).fetchone()["c"]
        assert msg_count == 0
        audit_row = conn.execute(
            "SELECT * FROM audit_logs WHERE action = 'conversation.delete' AND target_id = ?",
            (conversation["id"],),
        ).fetchone()
        assert audit_row is not None
    finally:
        conn.close()


def test_run_in_existing_conversation_persists_user_message(client, tmp_db_path):
    created = client.post(
        "/api/conversations", json={"title": "问答会话"}, headers=csrf_headers()
    ).json()
    response = client.post(
        "/api/runs",
        json={"conversation_id": created["id"], "input": "什么是 NER 标注规范？"},
        headers=csrf_headers(),
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    wait_run_status(tmp_db_path, run_id, ("completed",))
    detail = client.get(f"/api/conversations/{created['id']}").json()
    contents = [m["content"] for m in detail["messages"]]
    assert "什么是 NER 标注规范？" in contents  # 用户消息
    assert any(m["role"] == "assistant" for m in detail["messages"])  # 助手回复
