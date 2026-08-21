"""任务草稿链路测试：LLM/模板生成 → task.draft 事件 → 同步端点（幂等/属主/CSRF）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from bhzd_py.agent import composer, events, orchestrator
from bhzd_py.agent import task_drafts

from _agent_helpers import (
    csrf_headers,
    fetch_events,
    insert_run,
    insert_user,
    install_stub_tools,
    make_auth_client,
    make_db,
    open_db,
    wait_run_status,
)


@pytest.fixture()
def db(tmp_db_path):
    conn = make_db(tmp_db_path)
    yield conn
    conn.close()


@pytest.fixture()
def user_id(db):
    return insert_user(db)


@pytest.fixture(autouse=True)
def _offline_composer(monkeypatch):
    """默认无 Provider：草稿走模板回退，保持测试离线确定。"""

    monkeypatch.setattr(composer, "_providers", lambda: None)


def _draft_row(db_path: str, run_id: str):
    conn = open_db(db_path)
    try:
        return conn.execute(
            "SELECT * FROM task_drafts WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()


class _JsonProviders:
    """返回固定任务卡 JSON 的 Provider 替身（complete 契约见 composer.compose_text）。"""

    payload = ""

    @classmethod
    async def complete(cls, _messages, *, role, **_kwargs):
        return {"text": cls.payload, "model": "stub", "usage": {}}

    @classmethod
    async def stream_deltas(cls, _messages, *, role, **_kwargs):
        if False:
            yield {}


# ---------------------------------------------------------------------------
# 生成：模板回退 / LLM 卡 / 坏 JSON 回退
# ---------------------------------------------------------------------------


def test_draft_falls_back_to_template_without_provider(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, _ = insert_run(db, user_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    draft = _draft_row(tmp_db_path, run_id)
    assert draft is not None
    payload = json.loads(draft["card_json"])
    assert payload["generator"] == "template"
    card = payload["cards"][0]
    assert card["title"] == "图像标注练习任务"
    assert card["data_type"] == "image"
    # 图谱 stub 的 cap_ids 经证据链注入草稿卡，而不是由模型指定
    assert card["cap_ids"] == ["CAP-AUD-WAKE-COMMAND-001"]
    assert card["knowledge_points"] and card["exercises"]


def test_draft_uses_provider_card_when_llm_returns_valid_json(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _JsonProviders.payload = json.dumps(
        {
            "title": "图像框选入门任务",
            "goal": "掌握边界框标注规范",
            "knowledge_points": [
                {"title": "边界框规则", "content": "框必须贴合目标外缘。"},
                {"title": "常见错误", "content": "漏标遮挡目标。"},
            ],
            "exercises": [
                {
                    "question": "边界框应贴合到哪里？",
                    "type": "open_ended",
                    "options": [],
                    "reference_answer": "目标物体的最外缘像素。",
                }
            ],
            "est_minutes": 30,
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(composer, "_providers", lambda: _JsonProviders)
    run_id, _ = insert_run(db, user_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    payload = json.loads(_draft_row(tmp_db_path, run_id)["card_json"])
    assert payload["generator"] == "provider"
    card = payload["cards"][0]
    assert card["title"] == "图像框选入门任务"
    assert card["knowledge_points"][0]["title"] == "边界框规则"
    assert card["est_minutes"] == 30


def test_draft_falls_back_when_llm_returns_invalid_json(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _JsonProviders.payload = "这不是 JSON"
    monkeypatch.setattr(composer, "_providers", lambda: _JsonProviders)
    run_id, _ = insert_run(db, user_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    payload = json.loads(_draft_row(tmp_db_path, run_id)["card_json"])
    assert payload["generator"] == "template"
    assert payload["cards"][0]["title"] == "图像标注练习任务"


def test_staged_request_produces_one_draft_with_multiple_cards(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    run_id, _ = insert_run(
        db, user_id, "我想学文本标注，第一阶段：学习实体边界；第二阶段：完成实体练习"
    )
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    payload = json.loads(_draft_row(tmp_db_path, run_id)["card_json"])
    assert len(payload["cards"]) == 2
    assert payload["cards"][0]["title"].endswith("阶段1")


# ---------------------------------------------------------------------------
# 同步：落库 / 幂等 / 事件 / 属主 / CSRF
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_db_path, monkeypatch):
    install_stub_tools(monkeypatch)
    client, user_id = make_auth_client(tmp_db_path)
    client.test_user_id = user_id  # type: ignore[attr-defined]
    yield client
    client.close()


def _create_draft_via_api(client, tmp_db_path, text: str = "我想学图像标注") -> str:
    response = client.post("/api/runs", json={"input": text}, headers=csrf_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    wait_run_status(tmp_db_path, run_id, ("completed",))
    draft = _draft_row(tmp_db_path, run_id)
    assert draft is not None
    return draft["id"]


def test_sync_endpoint_creates_task_with_content_and_is_idempotent(client, tmp_db_path):
    draft_id = _create_draft_via_api(client, tmp_db_path)

    first = client.post(f"/api/task-drafts/{draft_id}/sync", headers=csrf_headers())
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "synced"
    assert body["already_synced"] is False
    assert len(body["task_ids"]) == 1
    assert body["tasks"][0]["title"] == "图像标注练习任务"

    # 重复点击/双击/刷新重放：返回既有任务，不重复落库
    second = client.post(f"/api/task-drafts/{draft_id}/sync", headers=csrf_headers())
    assert second.status_code == 200
    assert second.json()["already_synced"] is True
    assert second.json()["task_ids"] == body["task_ids"]

    conn = open_db(tmp_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"] == 1
        task_id = body["task_ids"][0]
        points = conn.execute(
            "SELECT COUNT(*) AS c FROM task_knowledge_points WHERE task_id = ?", (task_id,)
        ).fetchone()["c"]
        exercises = conn.execute(
            "SELECT COUNT(*) AS c FROM task_exercises WHERE task_id = ?", (task_id,)
        ).fetchone()["c"]
        assert points > 0 and exercises > 0
        task = conn.execute(
            "SELECT source, status FROM learning_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        assert task["source"] == "agent" and task["status"] == "not_started"
        # 同步后的 task.draft 投影让 SSE 回放把卡片置为已同步
        draft_events = [
            row
            for row in fetch_events(
                tmp_db_path,
                conn.execute(
                    "SELECT run_id FROM task_drafts WHERE id = ?", (draft_id,)
                ).fetchone()["run_id"],
            )
            if row["event_type"] == events.TASK_DRAFT_UPDATED
        ]
        assert draft_events[-1]["payload"]["draft"]["status"] == "synced"
        assert draft_events[-1]["payload"]["draft"]["task_ids"] == body["task_ids"]
    finally:
        conn.close()


def test_sync_endpoint_creates_one_task_per_stage(client, tmp_db_path):
    draft_id = _create_draft_via_api(
        client, tmp_db_path, "我想学文本标注，第一阶段：学习实体边界；第二阶段：完成实体练习"
    )
    response = client.post(f"/api/task-drafts/{draft_id}/sync", headers=csrf_headers())
    assert response.status_code == 200, response.text
    assert len(response.json()["task_ids"]) == 2
    conn = open_db(tmp_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"] == 2
    finally:
        conn.close()


def test_sync_endpoint_requires_csrf_and_owner(client, tmp_db_path):
    draft_id = _create_draft_via_api(client, tmp_db_path)

    denied = client.post(f"/api/task-drafts/{draft_id}/sync")
    assert denied.status_code == 403

    other, _ = make_auth_client(tmp_db_path, email="other@test.local")
    try:
        response = other.post(f"/api/task-drafts/{draft_id}/sync", headers=csrf_headers())
        assert response.status_code == 404
    finally:
        other.close()

    missing = client.post("/api/task-drafts/no-such-draft/sync", headers=csrf_headers())
    assert missing.status_code == 404


def test_sync_task_draft_rejects_rerequest_after_reload(tmp_db_path, monkeypatch):
    """直接调用层幂等：synced 草稿重放既有 task_ids（路由之外的第二道闸）。"""

    conn = make_db(tmp_db_path)
    try:
        user_id = insert_user(conn)
        run_id, _ = insert_run(conn, user_id, "我想学图像标注")
        now_payload = {"cards": [task_drafts.task_tools.build_task_card({"title": "T"})]}
        conn.execute(
            """
            INSERT INTO task_drafts
              (id, run_id, user_id, source, status, card_json, task_ids_json, created_at, synced_at)
            VALUES ('d1', ?, ?, 'agent', 'synced', ?, '["t1"]', '2026-01-01', '2026-01-01')
            """,
            (run_id, user_id, json.dumps(now_payload, ensure_ascii=False)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM task_drafts WHERE id = 'd1'").fetchone()
        result = task_drafts.sync_task_draft(conn, draft_row=row, user_id=user_id)
        assert result["already_synced"] is True
        assert result["task_ids"] == ["t1"]
        assert conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"] == 0
    finally:
        conn.close()


def test_conversation_detail_projects_task_drafts_by_run(client, tmp_db_path):
    """历史会话回放：task_drafts_by_run 让回答底部的预览/同步按钮复原。"""

    draft_id = _create_draft_via_api(client, tmp_db_path)
    conn = open_db(tmp_db_path)
    try:
        conversation_id = conn.execute(
            "SELECT conversation_id FROM task_drafts WHERE id = ?", (draft_id,)
        ).fetchone()["conversation_id"]
    finally:
        conn.close()

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    drafts = detail["task_drafts_by_run"]
    assert len(drafts) == 1
    projection = next(iter(drafts.values()))
    assert projection["id"] == draft_id
    assert projection["status"] == "draft"
    assert projection["cards"]


def test_revision_wording_routes_to_task_flow():
    """「继续修改」预填话术进任务链路；解释性提问仍走 RAG 路由。"""

    from bhzd_py.agent import intents

    assert intents.detect("请修改刚才的学习任务").kind == intents.KIND_TASK_CONVERT
    assert intents.detect("帮我调整一下学习任务").kind == intents.KIND_TASK_CONVERT
    assert intents.detect("如何修改学习任务？").kind == intents.KIND_RAG_QUESTION


def test_revision_request_includes_previous_draft_only_for_revision_wording(
    db, tmp_db_path, user_id, monkeypatch
):
    """同一对话内：修订话术把上一版草稿交给模型参照；全新任务请求不带旧卡。"""

    install_stub_tools(monkeypatch)
    captured: list[list[dict]] = []

    class _CaptureProviders:
        @classmethod
        async def complete(cls, messages, *, role, **_kwargs):
            captured.append(messages)
            return None  # 无文本 → 模板回退（本用例只关心提示词组装）

        @classmethod
        async def stream_deltas(cls, _messages, *, role, **_kwargs):
            if False:
                yield {}

    monkeypatch.setattr(composer, "_providers", lambda: _CaptureProviders)

    def follow_up(conversation_id: str, text: str) -> str:
        import uuid as _uuid

        follow_id = _uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text, created_at)
            VALUES (?, ?, ?, 'running', ?, datetime('now'))
            """,
            (follow_id, conversation_id, user_id, text),
        )
        db.commit()
        return follow_id

    first_run, conversation_id = insert_run(db, user_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    assert _draft_row(tmp_db_path, first_run) is not None

    revision_run = follow_up(conversation_id, "请修改刚才的学习任务：加一道选择题")
    asyncio.run(orchestrator.execute_run(revision_run, tmp_db_path))
    assert any(
        "上一版任务卡" in str(message.get("content"))
        for messages in captured
        for message in messages
    ), "修订请求应把上一版草稿放进草稿生成提示词"

    captured.clear()
    fresh_run = follow_up(conversation_id, "我想学语音标注")
    asyncio.run(orchestrator.execute_run(fresh_run, tmp_db_path))
    assert not any(
        "上一版任务卡" in str(message.get("content"))
        for messages in captured
        for message in messages
    ), "全新任务请求不应被旧草稿带偏"
