"""预设学习 API 测试：筛选、薄弱优先排序、详情拼接、start 走确认门。"""

from __future__ import annotations

import json
import uuid

from _learning_fixtures import api  # noqa: F401  # pytest 夹具复用


def _seed_mastery(api, user_id: str, cap_id: str, score: float):
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, '', ?, 'exercise', '2026-01-01')",
        (user_id, cap_id, score),
    )
    api.conn.commit()


def test_list_filters(api):
    user = api.login_as("preset-filter@test.local")
    resp = api.client.get("/api/presets?data_type=audio")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["items"]]
    assert ids == ["preset-cs-emotion", "preset-wake-word"]
    resp = api.client.get("/api/presets?scenario_id=SCN-CONTENT-SAFETY-001")
    ids = {p["id"] for p in resp.json()["items"]}
    assert ids == {"preset-video-event", "preset-content-safety-text"}
    resp = api.client.get("/api/presets?difficulty=1")
    assert [p["id"] for p in resp.json()["items"]] == ["preset-intro-basics"]
    resp = api.client.get("/api/presets?goal=证书")
    assert [p["id"] for p in resp.json()["items"]] == ["preset-cert-1x"]
    # 无筛选 → 8 条全量
    assert api.client.get("/api/presets").json()["total"] == 8


def test_weak_first_ordering_and_mastery_marks(api):
    """PRD-01 §4.4：含薄弱能力的路径排前面；已掌握能力有 mastered 标记。"""
    user = api.login_as("preset-sort@test.local")
    # 让"客服情感标注"路径含一个薄弱 cap（0.3 < 0.6），另一个 cap 已掌握（0.9）
    _seed_mastery(api, user["user_id"], "CAP-AUD-EMOTION-PARALING-001", 0.3)
    _seed_mastery(api, user["user_id"], "CAP-AUD-TRANSCRIBE-PUNCT-001", 0.9)
    items = api.client.get("/api/presets").json()["items"]
    assert items[0]["id"] == "preset-cs-emotion"  # 唯一含薄弱 cap 的路径
    assert items[0]["weak_count"] == 1
    caps = {c["cap_id"]: c for c in items[0]["caps"]}
    assert caps["CAP-AUD-EMOTION-PARALING-001"]["mastery_status"] == "weak"
    assert caps["CAP-AUD-TRANSCRIBE-PUNCT-001"]["mastery_status"] == "mastered"
    assert items[0]["mastered_collapsed"] is False
    # caps/units 已拼接中文名与单元标题
    assert items[0]["caps"][0]["cap_name"]
    assert items[0]["units"][0]["title"]


def test_mastered_collapsed_flag(api):
    user = api.login_as("preset-collapsed@test.local")
    preset_caps = ["CAP-TXT-ENTITY-BOUNDARY-001", "CAP-TXT-ENTITY-TYPE-001", "CAP-TXT-LABEL-VALIDATE-001"]
    for cap in preset_caps:
        _seed_mastery(api, user["user_id"], cap, 0.95)
    items = {p["id"]: p for p in api.client.get("/api/presets").json()["items"]}
    assert items["preset-ner-intro"]["mastered_collapsed"] is True


def test_detail_joins_units_and_caps(api):
    api.login_as("preset-detail@test.local")
    resp = api.client.get("/api/presets/preset-ner-intro")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "NER 实体标注入门"
    unit_ids = [u["unit_id"] for u in body["units"]]
    assert unit_ids == ["TU-TEXT-NER-BOUNDARY-001", "TU-TEXT-LABEL-VOCAB-001"]
    assert all(u["title"] and u["goals"] is not None for u in body["units"])
    assert body["caps"][0]["cap_name"] == "确定实体边界"
    missing = api.client.get("/api/presets/preset-nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PRESET_NOT_FOUND"


def test_start_creates_pending_confirmation(api):
    """start → 确认门：pending_confirmations 行 + 预览载荷带齐 task.create 字段。"""
    user = api.login_as("preset-start@test.local")
    resp = api.client.post("/api/presets/preset-ner-intro/start", headers=user["headers"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["confirmation"]["action_type"] == "task.create"
    assert body["confirmation"]["status"] == "pending"
    preview = body["preview"]
    # 预览载荷必须带齐 Agent 确认端点建任务所需的全部字段
    for key in (
        "title",
        "goal",
        "data_type",
        "scenario_id",
        "cap_ids",
        "steps",
        "resources",
        "source",
        "counts_toward_mastery",
    ):
        assert key in preview, f"预览缺字段 {key}"
    assert preview["source"] == "preset"
    assert preview["counts_toward_mastery"] == 1
    assert preview["cap_ids"] == ["CAP-TXT-ENTITY-BOUNDARY-001", "CAP-TXT-ENTITY-TYPE-001", "CAP-TXT-LABEL-VALIDATE-001"]
    assert preview["steps"]  # 来自首个单元的 goals

    row = api.conn.execute(
        "SELECT * FROM pending_confirmations WHERE id = ?",
        (body["confirmation"]["id"],),
    ).fetchone()
    assert row is not None
    assert row["action_type"] == "task.create"
    assert row["status"] == "pending"
    stored_preview = json.loads(row["preview_json"])
    assert stored_preview["source"] == "preset"
    run = api.conn.execute("SELECT * FROM agent_runs WHERE id = ?", (row["run_id"],)).fetchone()
    assert run["status"] == "waiting_confirmation"
    assert run["input_text"] == "开始预设学习:preset-ner-intro"

    # 再次 start 复用同一会话，不重复建"预设学习"会话
    api.client.post("/api/presets/preset-wake-word/start", headers=user["headers"])
    convs = api.conn.execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE user_id = ? AND title = '预设学习'",
        (user["user_id"],),
    ).fetchone()["n"]
    assert convs == 1


def test_start_requires_csrf(api):
    api.login_as("preset-csrf@test.local")
    resp = api.client.post("/api/presets/preset-ner-intro/start")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
