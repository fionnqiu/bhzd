"""Bounded Agent learning-domain capability contracts."""

from __future__ import annotations

import json
import uuid

from bhzd_py.agent import learning_capabilities
from bhzd_py.db import utc_now_iso


def test_auto_create_and_progress_are_owner_scoped_and_idempotent(api):
    student = api.login_as("agent-capability@test.local")
    user = {"id": student["user_id"], "role": "student"}
    first = learning_capabilities.auto_create_task(
        api.conn,
        user,
        {
            "title": "Agent 自动练习",
            "goal": "掌握边界判定",
            "data_type": "text",
            "cap_ids": ["CAP-A"],
            "exercises": [{"question": "判断边界", "reference_answer": "正确"}],
            "idempotency_key": "run-1:task",
        },
        run_id=None,
    )
    replay = learning_capabilities.auto_create_task(
        api.conn,
        user,
        {"title": "不应重复", "idempotency_key": "run-1:task"},
        run_id=None,
    )
    assert replay["already_completed"] is True
    assert replay["task_id"] == first["task_id"]

    progressed = learning_capabilities.record_progress(
        api.conn,
        user,
        {"task_id": first["task_id"], "status": "in_progress", "idempotency_key": "run-1:start"},
        run_id=None,
    )
    assert progressed["progress"] == 0.5
    assert api.conn.execute("SELECT automation_actor FROM learning_tasks WHERE id = ?", (first["task_id"],)).fetchone()[0] == "agent_auto"


def test_mastery_requires_all_successful_exercises_and_review_is_append_only(api, monkeypatch):
    student = api.login_as("agent-mastery@test.local")
    user = {"id": student["user_id"], "role": "student"}
    task = learning_capabilities.auto_create_task(
        api.conn,
        user,
        {
            "title": "评分闭环",
            "cap_ids": ["CAP-M"],
            "exercises": [
                {"question": "一", "reference_answer": "A"},
                {"question": "二", "reference_answer": "B"},
            ],
            "idempotency_key": "run-2:task",
        },
        run_id=None,
    )
    exercises = api.conn.execute("SELECT id FROM task_exercises WHERE task_id = ? ORDER BY id", (task["task_id"],)).fetchall()
    now = utc_now_iso()
    for index, exercise in enumerate(exercises):
        api.conn.execute(
            "INSERT INTO task_exercise_submissions "
            "(id, exercise_id, student_id, answer, grade_status, score, feedback, graded_at) "
            "VALUES (?, ?, ?, ?, 'done', ?, ?, ?)",
            (uuid.uuid4().hex, exercise["id"], student["user_id"], "答案", 80 - index * 10, "建议复盘", now),
        )
    attempt_id = uuid.uuid4().hex
    api.conn.execute(
        "INSERT INTO task_attempts "
        "(id, task_id, user_id, attempt_number, submission_json, score, feedback_json, created_at) "
        "VALUES (?, ?, ?, 1, ?, 0.75, ?, ?)",
        (attempt_id, task["task_id"], student["user_id"], json.dumps({}), json.dumps([]), now),
    )
    api.conn.execute("UPDATE learning_tasks SET status = 'submitted' WHERE id = ?", (task["task_id"],))
    api.conn.commit()

    result = learning_capabilities.sync_mastery(
        api.conn,
        user,
        {"task_id": task["task_id"], "attempt_id": attempt_id, "idempotency_key": "run-2:mastery"},
        run_id=None,
    )
    assert result["applied"]
    assert api.conn.execute("SELECT COUNT(*) FROM mastery_events WHERE user_id = ?", (student["user_id"],)).fetchone()[0] == 1

    submission = api.conn.execute("SELECT id FROM task_exercise_submissions WHERE student_id = ? LIMIT 1", (student["user_id"],)).fetchone()[0]
    async def fake_grader(*args, **kwargs):
        return {"text": '{"score": 75, "feedback": "继续练习"}', "provider_id": "grader-test"}

    monkeypatch.setattr("bhzd_py.agent.providers.complete", fake_grader)
    reviewed = learning_capabilities.review_exercise(
        api.conn,
        user,
        {"submission_id": submission, "idempotency_key": "run-2:review"},
        run_id=None,
    )
    assert reviewed["provider_role"] == "grader"
    assert api.conn.execute("SELECT score FROM task_exercise_submissions WHERE id = ?", (submission,)).fetchone()[0] in (70, 80)
