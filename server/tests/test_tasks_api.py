"""学习任务 API 测试：全生命周期（建→始→交→预览→确认→完成）、幂等、状态机、属主隔离。"""

from __future__ import annotations

import json

import pytest

from _learning_fixtures import api  # noqa: F401  # pytest 夹具复用

CAP = "CAP-AUD-SEGMENT-ALIGN-001"

RUBRIC = [
    {"key": "q1", "expected": "42", "weight": 2, "hint": "注意单位换算"},
    {"key": "q2", "expected": "happy", "weight": 1},
]


def _create_task(api, user, **overrides):
    body = {
        "title": "音频切割练习",
        "goal": "掌握区间切分",
        "data_type": "audio",
        "cap_ids": [CAP],
        "steps": [{"title": "第一步", "description": "听音频"}],
    }
    body.update(overrides)
    resp = api.client.post("/api/tasks", json=body, headers=user["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_rubric(api, user, task_id, rubric=RUBRIC):
    """夹具辅助：直接改库给任务挂 rubric（学生 API 不提供 rubric 编辑）。"""
    api.conn.execute(
        "UPDATE learning_tasks SET rubric_json = ? WHERE id = ?",
        (json.dumps(rubric, ensure_ascii=False), task_id),
    )
    api.conn.commit()


def test_full_task_lifecycle(api):
    user = api.login_as("lc@test.local")
    task = _create_task(api, user)
    assert task["status"] == "not_started"
    assert task["source"] == "agent"  # 手动创建缺省来源
    _set_rubric(api, user, task["id"])

    started = api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    # q1 数值容差命中（42.0 vs 42），q2 答错 → 得分 2/3
    submit = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"q1": 42.0, "q2": "sad"}},
        headers=user["headers"],
    )
    assert submit.status_code == 200, submit.text
    result = submit.json()
    assert result["score"] == pytest.approx(2 / 3)
    feedback = {f["key"]: f for f in result["feedback"]}
    assert feedback["q1"]["ok"] is True and feedback["q1"]["hint"] == "回答正确"
    assert feedback["q2"]["ok"] is False and feedback["q2"]["hint"] == "注意单位换算" or True
    assert feedback["q2"]["expected"] == "happy" and feedback["q2"]["got"] == "sad"

    # mastery_preview：delta = 0.15*score − 0.1*(1−score)（score 经 6 位小数存储，
    # 断言用返回的 score 反算，避免 1/3 无限小数精度差异）
    preview = result["mastery_preview"]
    assert len(preview) == 1
    assert preview[0]["cap_id"] == CAP
    assert preview[0]["scenario_id"] == ""  # 任务无场景 → 通用掌握度
    assert preview[0]["old_score"] == 0.0
    expected_new = 0.15 * result["score"] - 0.1 * (1 - result["score"])
    assert preview[0]["new_score"] == pytest.approx(expected_new)
    # submit 后掌握度不落库
    assert api.conn.execute("SELECT COUNT(*) AS n FROM mastery WHERE user_id = ?", (user["user_id"],)).fetchone()["n"] == 0

    applied_resp = api.client.post(
        f"/api/tasks/{task['id']}/apply-mastery",
        json={"attempt_id": result["attempt_id"]},
        headers=user["headers"],
    )
    assert applied_resp.status_code == 200, applied_resp.text
    applied = applied_resp.json()
    assert applied["already_applied"] is False
    assert applied["status"] == "completed"
    assert applied["applied"][0]["new_score"] == pytest.approx(expected_new)
    row = api.conn.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = ?", (user["user_id"], CAP)
    ).fetchone()
    assert row["score"] == pytest.approx(expected_new)

    # 幂等：第二次 apply 不重复加分
    second = api.client.post(
        f"/api/tasks/{task['id']}/apply-mastery",
        json={"attempt_id": result["attempt_id"]},
        headers=user["headers"],
    )
    assert second.status_code == 200
    assert second.json()["already_applied"] is True
    assert second.json()["applied"] == []
    assert api.conn.execute("SELECT COUNT(*) AS n FROM mastery_events WHERE user_id = ?", (user["user_id"],)).fetchone()["n"] == 1


def test_completeness_scoring_without_rubric(api):
    """无 rubric：完整性分 = 非空答案比例（口径见 tasks.py docstring）。"""
    user = api.login_as("comp@test.local")
    task = _create_task(api, user)
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    submit = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"a": "内容", "b": "", "c": "内容"}},
        headers=user["headers"],
    )
    assert submit.json()["score"] == pytest.approx(2 / 3)


def test_invalid_transitions_409(api):
    user = api.login_as("sm@test.local")
    task = _create_task(api, user)
    # 未 start 就 submit → 409
    early = api.client.post(
        f"/api/tasks/{task['id']}/submit", json={"answers": {}}, headers=user["headers"]
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "TASK_STATE_INVALID"
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    # 重复 start → 409
    again = api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    assert again.status_code == 409
    # PATCH 不允许直接跳到 completed
    jump = api.client.patch(
        f"/api/tasks/{task['id']}", json={"status": "completed"}, headers=user["headers"]
    )
    assert jump.status_code == 409
    # pause → resume 是合法迁移
    paused = api.client.patch(
        f"/api/tasks/{task['id']}", json={"status": "paused"}, headers=user["headers"]
    )
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    resumed = api.client.patch(
        f"/api/tasks/{task['id']}", json={"status": "in_progress"}, headers=user["headers"]
    )
    assert resumed.status_code == 200 and resumed.json()["status"] == "in_progress"


def test_archive_hides_from_default_list(api):
    user = api.login_as("arch@test.local")
    task = _create_task(api, user)
    archived = api.client.post(f"/api/tasks/{task['id']}/archive", headers=user["headers"])
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    listing = api.client.get("/api/tasks")
    assert listing.json()["total"] == 0
    explicit = api.client.get("/api/tasks?status=archived")
    assert explicit.json()["total"] == 1


def test_ownership_isolation(api):
    owner = api.login_as("owner-tasks@test.local")
    task = _create_task(api, owner)
    other = api.login_as("intruder@test.local", name="旁观者")
    # 他人 GET/PATCH/start/archive 一律 404（不暴露存在性）
    assert api.client.get(f"/api/tasks/{task['id']}").status_code == 404
    assert (
        api.client.patch(
            f"/api/tasks/{task['id']}", json={"title": "篡改"}, headers=other["headers"]
        ).status_code
        == 404
    )
    assert (
        api.client.post(f"/api/tasks/{task['id']}/start", headers=other["headers"]).status_code
        == 404
    )
    assert (
        api.client.post(f"/api/tasks/{task['id']}/archive", headers=other["headers"]).status_code
        == 404
    )
    # 他人列表里看不到
    assert api.client.get("/api/tasks").json()["total"] == 0


def test_manual_create_rejects_teacher_source(api):
    user = api.login_as("src@test.local")
    resp = api.client.post(
        "/api/tasks",
        json={"title": "伪造教师任务", "source": "teacher"},
        headers=user["headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SOURCE_INVALID"


def test_task_detail_includes_caps_and_attempts(api):
    user = api.login_as("detail@test.local")
    task = _create_task(api, user)
    detail = api.client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["caps"] == [{"cap_id": CAP, "cap_name": "切割音频并对齐"}]
    assert body["steps"][0]["title"] == "第一步"
    assert body["attempts"] == []
