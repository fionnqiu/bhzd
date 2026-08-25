"""学习与个人中心增强测试（008 迁移配套）：

入学测评闭环（v3.0 §11.1）、收藏资料（PRD-01 §9）、诊断缓存 DB 化、
任务批量归档（PRD-01 §6.1）、掌握度趋势端点。

CSRF 令牌稳定化契约的测试在 test_auth.py（该域契约由本批改动），这里不重复。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from bhzd_py.db import utc_now_iso
from bhzd_py.seed import assessment as assessment_seed

from _learning_fixtures import api  # noqa: F401  # pytest 夹具复用

# ---------------------------------------------------------------- 入学测评


def _correct_answers() -> dict[str, int]:
    return {q["id"]: q["answer_index"] for q in assessment_seed.get_questions()}


def test_assessment_questions_hide_answers(api):
    """下发题目不得泄露 answer_index；初始状态 not_started；cap_id 全部真实存在于图谱。"""
    assert assessment_seed.validate_question_caps() == []  # 题库无悬空引用
    user = api.login_as("assess@test.local")
    resp = api.client.get("/api/onboarding/assessment")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "not_started"
    assert body["total"] == 8
    assert len(body["questions"]) == 8
    for q in body["questions"]:
        assert "answer_index" not in q  # 防作弊：答案不下发
        assert {"id", "question", "options", "cap_id", "data_type"} <= set(q)
        assert len(q["options"]) == 4
    # 覆盖文本/图像/语音/视频四类
    assert {q["data_type"] for q in body["questions"]} == {"text", "image", "audio", "video"}


def test_assessment_submit_applies_mastery_and_persists(api):
    """全对提交：8 条 mastery 行（source='assessment'，+0.4）+ onboarding_json 落库。"""
    user = api.login_as("assess2@test.local")
    resp = api.client.post(
        "/api/onboarding/assessment",
        json={"answers": _correct_answers(), "goal": "成为数据标注工程师", "major": "人工智能技术应用"},
        headers=user["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] == 1.0 and body["correct"] == 8 and body["total"] == 8
    assert body["status"] == "completed"
    assert len(body["mastery_applied"]) == 8
    for item in body["mastery_applied"]:
        assert item["old_score"] == 0.0
        assert item["new_score"] == pytest.approx(0.4)  # 答对 +0.4
    # 落库核对：mastery + mastery_events 都是 assessment 来源
    rows = api.conn.execute(
        "SELECT cap_id, score, source FROM mastery WHERE user_id = ?", (user["user_id"],)
    ).fetchall()
    assert len(rows) == 8
    assert all(r["source"] == "assessment" for r in rows)
    assert all(r["score"] == pytest.approx(0.4) for r in rows)
    events = api.conn.execute(
        "SELECT COUNT(*) AS n FROM mastery_events WHERE user_id = ? AND source = 'assessment'",
        (user["user_id"],),
    ).fetchone()
    assert events["n"] == 8
    # onboarding_json 持久化（goal/major 同步独立列）
    profile = api.conn.execute(
        "SELECT goal_text, major, onboarding_json FROM learning_profiles WHERE user_id = ?",
        (user["user_id"],),
    ).fetchone()
    onboarding = json.loads(profile["onboarding_json"])
    assert onboarding["completed_at"] and onboarding["score"] == 1.0
    assert profile["goal_text"] == "成为数据标注工程师"
    assert profile["major"] == "人工智能技术应用"
    # 再次 GET：状态 completed 并回带成绩摘要
    status = api.client.get("/api/onboarding/assessment").json()
    assert status["status"] == "completed"
    assert status["result"]["score"] == 1.0
    # 重复提交拒绝（防止刷掌握度）
    resp = api.client.post(
        "/api/onboarding/assessment", json={"answers": {}}, headers=user["headers"]
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ASSESSMENT_COMPLETED"


def test_assessment_wrong_answers_get_baseline(api):
    """答错给 +0.1 基线分；混合对错按题分别计分。"""
    user = api.login_as("assess3@test.local")
    answers = _correct_answers()
    first_qid = assessment_seed.get_questions()[0]["id"]
    first_cap = assessment_seed.get_questions()[0]["cap_id"]
    answers[first_qid] = (answers[first_qid] + 1) % 4  # 改成错误选项
    resp = api.client.post(
        "/api/onboarding/assessment", json={"answers": answers}, headers=user["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["correct"] == 7 and body["score"] == pytest.approx(7 / 8)
    row = api.conn.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = ?",
        (user["user_id"], first_cap),
    ).fetchone()
    assert row["score"] == pytest.approx(0.1)  # 答错基线分


def test_assessment_skip_is_idempotent(api):
    user = api.login_as("assess4@test.local")
    resp = api.client.post("/api/onboarding/skip", headers=user["headers"])
    assert resp.status_code == 200 and resp.json()["status"] == "skipped"
    # 幂等：重复跳过仍 200 且状态不变
    resp = api.client.post("/api/onboarding/skip", headers=user["headers"])
    assert resp.status_code == 200 and resp.json()["status"] == "skipped"
    assert api.client.get("/api/onboarding/assessment").json()["status"] == "skipped"
    # 跳过后仍允许补做测评（skip 不是终态）
    resp = api.client.post(
        "/api/onboarding/assessment", json={"answers": _correct_answers()}, headers=user["headers"]
    )
    assert resp.status_code == 200
    # 完成后再跳过 → 409
    resp = api.client.post("/api/onboarding/skip", headers=user["headers"])
    assert resp.status_code == 409


# ---------------------------------------------------------------- 收藏资料


def _add_favorite(api, user, item_id="doc-1", item_type="rag_document", title="NER 规范"):
    return api.client.post(
        "/api/profile/favorites",
        json={"item_type": item_type, "item_id": item_id, "title": title, "meta": {"page": 3}},
        headers=user["headers"],
    )


def test_favorites_add_list_dedupe_delete(api):
    user = api.login_as("fav@test.local")
    # 添加
    resp = _add_favorite(api, user)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True
    favorite = resp.json()["favorite"]
    assert favorite["item_type"] == "rag_document" and favorite["meta"] == {"page": 3}

    # 幂等去重：同一条目再收藏 → created=False，列表仍只有 1 行（标题被刷新）
    resp = _add_favorite(api, user, title="NER 规范 v3")
    assert resp.status_code == 200
    assert resp.json()["created"] is False
    assert resp.json()["favorite"]["id"] == favorite["id"]  # 保留原 id

    _add_favorite(api, user, item_id="node-1", item_type="graph_node", title="实体边界")
    listed = api.client.get("/api/profile/favorites").json()
    assert listed["total"] == 2
    assert listed["items"][0]["title"] == "实体边界"  # 最新在前
    assert listed["items"][1]["title"] == "NER 规范 v3"

    # 个人中心聚合返回真实收藏（不再有 P1 桩说明）
    overview = api.client.get("/api/profile").json()
    assert overview["favorites"] and "favorites_note" not in overview

    # 删除
    resp = api.client.delete(f"/api/profile/favorites/{favorite['id']}", headers=user["headers"])
    assert resp.status_code == 200
    assert api.client.get("/api/profile/favorites").json()["total"] == 1
    # 再删 → 404
    assert api.client.delete(
        f"/api/profile/favorites/{favorite['id']}", headers=user["headers"]
    ).status_code == 404


def test_favorites_isolation_and_validation(api):
    owner = api.login_as("fav-owner@test.local")
    favorite = _add_favorite(api, owner).json()["favorite"]

    other = api.login_as("fav-other@test.local")
    # 他人列表为空（隔离）
    assert api.client.get("/api/profile/favorites").json()["total"] == 0
    # 他人删除 → 404（不暴露存在性）
    resp = api.client.delete(f"/api/profile/favorites/{favorite['id']}", headers=other["headers"])
    assert resp.status_code == 404
    # 非法类型 → 400
    resp = api.client.post(
        "/api/profile/favorites",
        json={"item_type": "evil", "item_id": "x", "title": "x"},
        headers=other["headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "ITEM_TYPE_INVALID"
    # 无 CSRF → 403
    resp = api.client.post(
        "/api/profile/favorites",
        json={"item_type": "citation", "item_id": "x", "title": "x"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------- 诊断缓存 DB 化

TEXTGRID_SAMPLE = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 2.0
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "emotion"
        xmin = 0
        xmax = 2.0
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1.0
            text = "happy"
        intervals [2]:
            xmin = 0.8
            xmax = 2.0
            text = "sad"
'''


def _upload_diagnostic(api, user) -> str:
    resp = api.client.post(
        "/api/diagnostics",
        files={"file": ("sample.TextGrid", TEXTGRID_SAMPLE.encode("utf-8"), "text/plain")},
        data={"data_type": "audio"},
        headers=user["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["diagnostic_token"]


def test_diagnostic_cache_persisted_and_save_summary(api):
    """上传后报告落 diagnostic_cache 表（不再只在进程内存）；save-summary 全链路可用。"""
    user = api.login_as("diag-cache@test.local")
    token = _upload_diagnostic(api, user)
    row = api.conn.execute(
        "SELECT user_id, expires_at FROM diagnostic_cache WHERE token = ?", (token,)
    ).fetchone()
    assert row is not None and row["user_id"] == user["user_id"]
    assert row["expires_at"] > utc_now_iso()

    resp = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=user["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary_id"]
    # 一次性确认：生效后缓存行作废
    assert api.conn.execute(
        "SELECT COUNT(*) AS n FROM diagnostic_cache WHERE token = ?", (token,)
    ).fetchone()["n"] == 0


def test_diagnostic_cache_expired_token_chinese_error(api):
    """过期 token → 410 + 中文提示；过期行在读取时被惰性删除。"""
    user = api.login_as("diag-expired@test.local")
    token = _upload_diagnostic(api, user)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    api.conn.execute("UPDATE diagnostic_cache SET expires_at = ? WHERE token = ?", (past, token))
    api.conn.commit()

    resp = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=user["headers"]
    )
    assert resp.status_code == 410
    error = resp.json()["error"]
    assert error["code"] == "DIAGNOSTIC_TOKEN_EXPIRED"
    assert "过期" in error["message"]  # 面向用户的中文消息
    # 惰性删除：读过一次后过期行不复存在
    assert api.conn.execute(
        "SELECT COUNT(*) AS n FROM diagnostic_cache WHERE token = ?", (token,)
    ).fetchone()["n"] == 0


def test_diagnostic_cache_second_user_forbidden(api):
    owner = api.login_as("diag-owner@test.local")
    token = _upload_diagnostic(api, owner)
    other = api.login_as("diag-other@test.local")
    resp = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=other["headers"]
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
    # 属主不受影响，仍可正常保存
    api.act_as(owner)
    resp = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=owner["headers"]
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------- 任务批量归档


def _insert_task(api, user_id: str, title: str, source: str = "agent", status: str = "not_started") -> str:
    """直接建库行（教师来源任务学生 API 建不了，只能模拟教师发布后的落库形态）。"""
    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    api.conn.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, source, status, cap_ids_json, steps_json, resources_json,
           counts_toward_mastery, teacher_id, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', 1, ?, ?, ?, ?)
        """,
        (
            task_id, user_id, title, source, status,
            "teacher-1" if source == "teacher" else None,
            user_id, now, now,
        ),
    )
    api.conn.commit()
    return task_id


def test_batch_archive_partial_results(api):
    user = api.login_as("batch@test.local")
    own_task = _insert_task(api, user["user_id"], "自己的任务")
    teacher_task = _insert_task(api, user["user_id"], "教师任务", source="teacher")
    archived_task = _insert_task(api, user["user_id"], "已归档任务", status="archived")
    other = api.login_as("batch-other@test.local")
    foreign_task = _insert_task(api, other["user_id"], "别人的任务")

    api.act_as(user)
    resp = api.client.post(
        "/api/tasks/batch",
        json={"ids": [own_task, teacher_task, archived_task, foreign_task, "ghost-id"], "action": "archive"},
        headers=user["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 3 and body["failed"] == 2
    results = {r["id"]: r for r in body["results"]}
    assert results[own_task]["ok"] is True and results[own_task]["message"] == "已归档"
    # 教师来源任务允许归档（PRD-06 §8.2：只能归档不能删）
    assert results[teacher_task]["ok"] is True
    # 已归档幂等视为成功
    assert results[archived_task]["ok"] is True and "无需重复" in results[archived_task]["message"]
    # 他人任务与不存在 id：失败且不暴露存在性
    assert results[foreign_task]["ok"] is False
    assert results["ghost-id"]["ok"] is False

    # 落库核对：自己的两个任务已归档，别人的任务不受影响
    for tid in (own_task, teacher_task):
        row = api.conn.execute("SELECT status, archived_at FROM learning_tasks WHERE id = ?", (tid,)).fetchone()
        assert row["status"] == "archived" and row["archived_at"]
    row = api.conn.execute("SELECT status FROM learning_tasks WHERE id = ?", (foreign_task,)).fetchone()
    assert row["status"] == "not_started"


def test_batch_action_validation(api):
    user = api.login_as("batch2@test.local")
    resp = api.client.post(
        "/api/tasks/batch", json={"ids": ["x"], "action": "delete"}, headers=user["headers"]
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "BATCH_ACTION_INVALID"
    resp = api.client.post(
        "/api/tasks/batch", json={"ids": [], "action": "archive"}, headers=user["headers"]
    )
    assert resp.status_code == 400
    # 无 CSRF → 403
    assert api.client.post(
        "/api/tasks/batch", json={"ids": ["x"], "action": "archive"}
    ).status_code == 403


# ---------------------------------------------------------------- 掌握度趋势


def test_mastery_trend_series(api):
    user = api.login_as("trend@test.local")
    # 用入学测评制造 8 条 assessment 事件，再直接 apply 一次练习事件
    resp = api.client.post(
        "/api/onboarding/assessment", json={"answers": _correct_answers()}, headers=user["headers"]
    )
    assert resp.status_code == 200
    cap_id = assessment_seed.get_questions()[0]["cap_id"]
    from bhzd_py.mastery import service as mastery_service

    mastery_service.apply_updates(
        api.conn, user["user_id"], [{"cap_id": cap_id, "delta": 0.15}],
        source="exercise",
    )

    resp = api.client.get("/api/profile/mastery/trend", params={"cap_id": cap_id, "days": 30})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2  # 该 cap 的 assessment + exercise 各一条
    items = body["items"]
    assert [i["source"] for i in items] == ["assessment", "exercise"]  # 时间升序
    for item in items:
        assert {"date", "cap_id", "old_score", "new_score", "source"} <= set(item)
        assert item["cap_id"] == cap_id
    assert items[0]["old_score"] == 0.0 and items[0]["new_score"] == pytest.approx(0.4)
    assert items[1]["old_score"] == pytest.approx(0.4) and items[1]["new_score"] == pytest.approx(0.55)

    # 不带 cap_id：返回全部 9 条事件
    all_items = api.client.get("/api/profile/mastery/trend").json()
    assert all_items["total"] == 9
    # 他人不可见（隔离）
    api.login_as("trend-other@test.local")
    assert api.client.get("/api/profile/mastery/trend").json()["total"] == 0


# ---------------------------------------------------------------- 个人设置：诊断分享开关（PRD-06 §15 #2）


def test_share_diagnostics_toggle_roundtrip(api):
    """PATCH /api/profile 开关 → GET /api/profile settings 回读一致；变更写审计。"""
    user = api.login_as("share@test.local")
    # 默认关闭
    resp = api.client.get("/api/profile")
    assert resp.status_code == 200
    assert resp.json()["settings"]["share_diagnostics"] is False
    # 开启
    resp = api.client.patch(
        "/api/profile", json={"share_diagnostics": True}, headers=user["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["share_diagnostics"] is True
    # 回读持久化
    resp = api.client.get("/api/profile")
    assert resp.json()["settings"]["share_diagnostics"] is True
    # 关闭 + 审计行存在
    api.client.patch(
        "/api/profile", json={"share_diagnostics": False}, headers=user["headers"]
    )
    row = api.conn.execute(
        "SELECT share_diagnostics FROM learning_profiles WHERE user_id = ?",
        (user["user_id"],),
    ).fetchone()
    assert row["share_diagnostics"] == 0
    audited = api.conn.execute(
        "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'profile.share_diagnostics' AND actor_id = ?",
        (user["user_id"],),
    ).fetchone()["n"]
    assert audited >= 2


def test_share_diagnostics_patch_validation(api):
    """空 PATCH（无可更新字段）应 422。"""
    user = api.login_as("share2@test.local")
    resp = api.client.patch("/api/profile", json={}, headers=user["headers"])
    assert resp.status_code == 422


# ---------------------------------------------------------------- 自助改名（PATCH /api/auth/profile，三类账号共用）


def test_update_own_name_roundtrip(api):
    """改名 → users 表与响应 DTO 一致（去首尾空白）；变更写审计。"""
    user = api.login_as("rename@test.local", name="旧名字")
    resp = api.client.patch(
        "/api/auth/profile", json={"name": " 新名字 "}, headers=user["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["name"] == "新名字"
    row = api.conn.execute(
        "SELECT name FROM users WHERE id = ?", (user["user_id"],)
    ).fetchone()
    assert row["name"] == "新名字"
    audited = api.conn.execute(
        "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'auth.update_name' AND actor_id = ?",
        (user["user_id"],),
    ).fetchone()["n"]
    assert audited == 1


def test_update_own_name_allows_teacher(api):
    """教师被学生门户角色门挡在 /api/profile 外，但改名是身份操作，所有角色可用。"""
    user = api.login_as("teacher-rename@test.local", role="teacher")
    resp = api.client.patch(
        "/api/auth/profile", json={"name": "王老师"}, headers=user["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["name"] == "王老师"


def test_update_own_name_validation(api):
    """纯空白名显式 422（min_length=1 在 strip 之前判定，挡不住空格）；缺 name 字段 422。"""
    user = api.login_as("rename2@test.local")
    resp = api.client.patch(
        "/api/auth/profile", json={"name": "   "}, headers=user["headers"]
    )
    assert resp.status_code == 422
    resp = api.client.patch("/api/auth/profile", json={}, headers=user["headers"])
    assert resp.status_code == 422
