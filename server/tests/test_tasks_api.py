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
    """Seed the current per-question grading contract for lifecycle tests."""
    api.conn.execute(
        "UPDATE learning_tasks SET rubric_json = ? WHERE id = ?",
        (json.dumps(rubric, ensure_ascii=False), task_id),
    )
    for index, item in enumerate(rubric):
        exercise_id = f"{task_id}-exercise-{index}"
        api.conn.execute(
            "INSERT INTO task_exercises (id, task_id, question, type, reference_answer, sort_order) "
            "VALUES (?, ?, ?, 'open_ended', ?, ?)",
            (exercise_id, task_id, item["key"], str(item["expected"]), index),
        )
        score = 100 if index == 0 else 0
        api.conn.execute(
            "INSERT INTO task_exercise_submissions "
            "(id, exercise_id, student_id, answer, grade_status, score, feedback, graded_at) "
            "VALUES (?, ?, ?, ?, 'done', ?, ?, datetime('now'))",
            (f"{exercise_id}-submission", exercise_id, user["user_id"], "sad" if index == 1 else str(item["expected"]), score,
             "回答正确" if score else item.get("hint", "请重新检查")),
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
    assert result["score"] == pytest.approx(0.6667)
    # Task submission aggregates durable exercise grades.  Feedback is keyed by
    # exercise ID and never returns reference answers, so a retry cannot read
    # the grading key from its previous attempt.
    feedback = {f["got"]: f for f in result["feedback"]}
    assert feedback["42"]["ok"] is True and feedback["42"]["hint"] == "回答正确"
    assert feedback["sad"]["ok"] is False and feedback["sad"]["hint"] == "请重新检查"
    assert feedback["sad"]["expected"] is None

    # mastery_preview：delta = 0.15*score − 0.1*(1−score)（score 经 6 位小数存储，
    # 断言用返回的 score 反算，避免 1/3 无限小数精度差异）
    preview = result["mastery_preview"]
    assert len(preview) == 1
    assert preview[0]["cap_id"] == CAP
    assert "scenario_id" not in preview[0]
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
    """没有单题评分时，填写内容不能生成任务总分。"""
    user = api.login_as("comp@test.local")
    task = _create_task(api, user)
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    submit = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"a": "内容", "b": "", "c": "内容"}},
        headers=user["headers"],
    )
    assert submit.status_code == 409
    assert submit.json()["error"]["code"] == "TASK_GRADING_INCOMPLETE"


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
    # The compatibility field remains in the DTO, but new learning tasks no
    # longer keep an operation-step workflow as part of their content.
    assert body["steps"] == []
    assert body["attempts"] == []


def test_task_detail_hides_answer_key_and_restores_latest_pending_attempt(api):
    """学生详情只拿到可出题 rubric，并可在刷新后恢复待确认提交。"""
    user = api.login_as("detail-recovery@test.local")
    task = _create_task(api, user)
    _set_rubric(api, user, task["id"])
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    submitted = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"q1": "42", "q2": "sad"}},
        headers=user["headers"],
    )
    assert submitted.status_code == 200, submitted.text

    detail = api.client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # `expected` remains server-only in rubric_json; it is absent before the
    # student starts a new answer, while post-submit feedback stays recoverable.
    assert body["rubric"] == [
        {"key": "q1", "hint": "注意单位换算", "weight": 2.0},
        {"key": "q2", "weight": 1.0},
    ]
    assert all("expected" not in item for item in body["rubric"])
    latest = body["latest_attempt"]
    assert latest["id"] == submitted.json()["attempt_id"]
    assert latest["mastery_applied"] is False
    assert latest["answers"] == {"q1": "42", "q2": "sad"}
    assert latest["feedback"] == submitted.json()["feedback"]
    assert latest["mastery_preview"] == submitted.json()["mastery_preview"]


def test_apply_mastery_rejects_a_superseded_pending_attempt(api):
    """重新提交后只能确认最新预览，避免把已经过期的结果写入掌握度。"""
    user = api.login_as("latest-attempt@test.local")
    task = _create_task(api, user)
    _set_rubric(api, user, task["id"])
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    first = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"q1": "42", "q2": "sad"}},
        headers=user["headers"],
    ).json()
    second = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"q1": "42", "q2": "happy"}},
        headers=user["headers"],
    ).json()

    stale = api.client.post(
        f"/api/tasks/{task['id']}/apply-mastery",
        json={"attempt_id": first["attempt_id"]},
        headers=user["headers"],
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "ATTEMPT_NOT_CURRENT"

    current = api.client.post(
        f"/api/tasks/{task['id']}/apply-mastery",
        json={"attempt_id": second["attempt_id"]},
        headers=user["headers"],
    )
    assert current.status_code == 200, current.text
    assert current.json()["status"] == "completed"


def test_task_detail_strips_practice_answer_fixtures_but_keeps_practice_display(api):
    """练习展示不能携带评分 fixture；完整性评分仍从数据库中的原件读取键集合。"""
    user = api.login_as("practice-redaction@test.local")
    task = _create_task(api, user)
    practice = {
        "questions": [
            {
                "key": "q1",
                "prompt": "请填写标注结果",
                "hint": "核对字段完整性",
                "expected": "仅服务端可见",
                "answers": {"q1": "仅服务端可见"},
            }
        ],
        "samples": [
            {
                "input": {"text": "待标注文本"},
                "expected": "标准标注",
                "nested": {"correct_answer": "标准标注", "context": "保留给学生"},
            }
        ],
        "checklist": ["已检查字段", {"answer": "不应转成展示文本"}],
        "answers": {"q1": "仅服务端可见"},
        "expected": {"q1": "仅服务端可见"},
    }
    api.conn.execute(
        "UPDATE learning_tasks SET practice_json = ? WHERE id = ?",
        (json.dumps(practice, ensure_ascii=False), task["id"]),
    )
    api.conn.commit()

    detail = api.client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["practice"] == {
        "questions": [
            {
                "key": "q1",
                "prompt": "请填写标注结果",
                "hint": "核对字段完整性",
                "type": "open_ended",
            }
        ],
        "samples": [{"input": {"text": "待标注文本"}, "nested": {"context": "保留给学生"}}],
        "checklist": ["已检查字段"],
    }

    # Redaction changes the response DTO, while a legacy task without durable
    # question grades must not receive a fabricated completeness score.
    api.client.post(f"/api/tasks/{task['id']}/start", headers=user["headers"])
    submitted = api.client.post(
        f"/api/tasks/{task['id']}/submit",
        json={"answers": {"q1": "学生作答"}},
        headers=user["headers"],
    )
    assert submitted.status_code == 409, submitted.text
    assert submitted.json()["error"]["code"] == "TASK_GRADING_INCOMPLETE"
