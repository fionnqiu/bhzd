"""Regression tests for atomic teacher publishing and class-scoped error analysis.

These tests describe the user-visible contract before the implementation is
changed: authored lesson rows must travel with the draft write, and the
analytics card must only inspect submissions from the selected published task
copies.  The AI case also verifies that provider output is treated as a
labeling aid rather than an authority for counts or student identity.
"""

from __future__ import annotations

import json

from _learning_fixtures import api  # noqa: F401
from bhzd_py import db as db_module


CAP = "CAP-AUD-SEGMENT-ALIGN-001"


def _create_class(api, teacher, name: str) -> dict:
    response = api.client.post(
        "/api/teacher/classes",
        json={"name": name},
        headers=teacher["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _join(api, student: dict, class_info: dict) -> None:
    # The fixture's cookie jar represents one active user at a time; switch to
    # the student before exercising the student-side join endpoint.
    api.act_as(student)
    response = api.client.post(
        "/api/student/join-class",
        json={"invite_code": class_info["invite_code"]},
        headers=student["headers"],
    )
    assert response.status_code == 200, response.text


def _create_published_task(
    api,
    teacher: dict,
    class_info: dict,
    *,
    title: str,
    question: str,
    answer: str,
    score: int,
    feedback: str,
) -> tuple[str, str]:
    """Create a task through the public flow and seed one scored student copy."""

    api.act_as(teacher)
    created = api.client.post(
        "/api/teacher/tasks",
        json={
            "title": title,
            "description": f"{title}说明",
            "data_type": "audio",
            "cap_ids": [CAP],
            "defer_content_generation": True,
        },
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    content = api.client.put(
        f"/api/teacher/tasks/{task_id}/content",
        json={
            "knowledge_points": [
                {"title": f"{title}知识点", "content": f"{title}的核对规则"}
            ],
            "exercises": [
                {
                    "question": question,
                    "type": "open_ended",
                    "reference_answer": answer,
                    "sort_order": 0,
                }
            ],
        },
        headers=teacher["headers"],
    )
    assert content.status_code == 200, content.text

    published = api.client.post(
        f"/api/teacher/tasks/{task_id}/publish",
        json={"class_id": class_info["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text

    copy = api.conn.execute(
        "SELECT id FROM learning_tasks WHERE parent_task_id = ? ORDER BY id LIMIT 1",
        (task_id,),
    ).fetchone()
    assert copy is not None
    exercise = api.conn.execute(
        "SELECT id FROM task_exercises WHERE task_id = ? ORDER BY sort_order, id LIMIT 1",
        (copy["id"],),
    ).fetchone()
    assert exercise is not None
    now = db_module.utc_now_iso()
    submission_id = f"submission-{task_id}"
    api.conn.execute(
        "INSERT INTO task_exercise_submissions "
        "(id, exercise_id, student_id, answer, grade_status, score, feedback, graded_at, created_at) "
        "VALUES (?, ?, ?, ?, 'done', ?, ?, ?, ?)",
        (
            submission_id,
            exercise["id"],
            class_info["student_id"],
            "学生作答",
            score,
            feedback,
            now,
            now,
        ),
    )
    api.conn.commit()
    return task_id, copy["id"]


def test_direct_publish_persists_authored_content_before_fanout(api):
    """The save-content step must make an otherwise unsaved task publishable."""

    teacher = api.login_as("atomic-publish-teacher@test.local", role="teacher")
    student = api.login_as("atomic-publish-student@test.local")
    api.act_as(teacher)
    class_info = _create_class(api, teacher, "原子发布班")
    class_info["student_id"] = student["user_id"]
    _join(api, student, class_info)

    task_id, copy_id = _create_published_task(
        api,
        teacher,
        class_info,
        title="未保存直发任务",
        question="如何确认切片边界？",
        answer="核对语义完整性",
        score=35,
        feedback="边界判断不完整",
    )

    source_points = api.conn.execute(
        "SELECT title, content FROM task_knowledge_points WHERE task_id = ?",
        (task_id,),
    ).fetchall()
    copied_points = api.conn.execute(
        "SELECT title, content FROM task_knowledge_points WHERE task_id = ?",
        (copy_id,),
    ).fetchall()
    source_exercises = api.conn.execute(
        "SELECT question, reference_answer FROM task_exercises WHERE task_id = ?",
        (task_id,),
    ).fetchall()
    copied_exercises = api.conn.execute(
        "SELECT question, reference_answer FROM task_exercises WHERE task_id = ?",
        (copy_id,),
    ).fetchall()
    assert [tuple(row) for row in copied_points] == [tuple(row) for row in source_points]
    assert [tuple(row) for row in copied_exercises] == [tuple(row) for row in source_exercises]


def test_invalid_atomic_content_update_keeps_previous_rows(api):
    """Validation must happen before replacement so a failed publish cannot erase content."""

    teacher = api.login_as("atomic-rollback-teacher@test.local", role="teacher")
    api.act_as(teacher)
    created = api.client.post(
        "/api/teacher/tasks",
        json={
            "title": "保留旧内容",
            "defer_content_generation": True,
        },
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    initial = api.client.put(
        f"/api/teacher/tasks/{task_id}/content",
        json={
            "knowledge_points": [{"title": "旧标题", "content": "旧正文"}],
            "exercises": [
                {
                    "question": "旧题目",
                    "type": "open_ended",
                    "reference_answer": "旧答案",
                }
            ],
        },
        headers=teacher["headers"],
    )
    assert initial.status_code == 200, initial.text

    invalid = api.client.put(
        f"/api/teacher/tasks/{task_id}/content",
        json={
            "knowledge_points": [{"title": "新标题", "content": "新正文"}],
            "exercises": [{"question": "", "type": "open_ended"}],
        },
        headers=teacher["headers"],
    )
    assert invalid.status_code == 400, invalid.text

    task = api.conn.execute("SELECT title FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
    point = api.conn.execute(
        "SELECT title, content FROM task_knowledge_points WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    exercise = api.conn.execute(
        "SELECT question, reference_answer FROM task_exercises WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert task["title"] == "保留旧内容"
    assert tuple(point) == ("旧标题", "旧正文")
    assert tuple(exercise) == ("旧题目", "旧答案")


def test_error_analysis_is_scoped_to_selected_class_published_tasks(api):
    """Two classes must not inherit each other's low-score task evidence."""

    teacher = api.login_as("analysis-isolation-teacher@test.local", role="teacher")
    student = api.login_as("analysis-isolation-student@test.local")
    api.act_as(teacher)
    first = _create_class(api, teacher, "错误分析一班")
    second = _create_class(api, teacher, "错误分析二班")
    first["student_id"] = student["user_id"]
    second["student_id"] = student["user_id"]
    _join(api, student, first)
    _join(api, student, second)

    first_task, first_copy = _create_published_task(
        api,
        teacher,
        first,
        title="一班边界任务",
        question="一班应如何判断边界？",
        answer="按语义完整性",
        score=20,
        feedback="边界条件遗漏",
    )
    second_task, second_copy = _create_published_task(
        api,
        teacher,
        second,
        title="二班标签任务",
        question="二班应如何确认标签？",
        answer="按标签规范",
        score=20,
        feedback="标签规则遗漏",
    )

    api.act_as(teacher)
    first_result = api.client.get(
        "/api/teacher/analytics",
        params={"class_id": first["id"], "range": "term"},
    )
    second_result = api.client.get(
        "/api/teacher/analytics",
        params={"class_id": second["id"], "range": "term"},
    )
    assert first_result.status_code == 200, first_result.text
    assert second_result.status_code == 200, second_result.text
    first_body = first_result.json()
    second_body = second_result.json()

    assert first_body["error_analysis"]["sample_count"] == 1
    assert second_body["error_analysis"]["sample_count"] == 1
    assert first_body["error_analysis"]["source"] == "fallback"
    assert second_body["error_analysis"]["source"] == "fallback"
    assert first_body["top_errors"][0]["task_ids"] == [first_copy]
    assert second_body["top_errors"][0]["task_ids"] == [second_copy]
    assert first_body["top_errors"][0]["task_ids"] != [second_task]
    assert second_body["top_errors"][0]["task_ids"] != [first_task]
    assert "一班" in first_body["top_errors"][0]["label"]
    assert "二班" in second_body["top_errors"][0]["label"]


def test_error_analysis_uses_configured_ai_labels_and_recomputes_counts(api, monkeypatch):
    """Valid provider JSON labels evidence while the server owns frequencies."""

    teacher = api.login_as("analysis-ai-teacher@test.local", role="teacher")
    student = api.login_as("analysis-ai-student@test.local")
    api.act_as(teacher)
    class_info = _create_class(api, teacher, "AI错误分析班")
    class_info["student_id"] = student["user_id"]
    _join(api, student, class_info)
    _create_published_task(
        api,
        teacher,
        class_info,
        title="AI错误任务",
        question="如何复核时间戳？",
        answer="逐段核对",
        score=10,
        feedback="时间戳顺序混乱",
    )

    captured: list[list[dict]] = []

    async def fake_complete(messages, *, role="primary", **kwargs):
        assert role == "primary"
        assert kwargs.get("database_path")
        captured.append(messages)
        return {
            "text": json.dumps(
                {
                    "errors": [
                        {
                            "error_type": "timestamp_order",
                            "label": "时间戳顺序错误",
                            "severity": "major",
                            "evidence": [0],
                            "suggestion": "复核时间戳先后顺序",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            "model": "analysis-test-model",
            "provider_id": "analysis-test-provider",
        }

    monkeypatch.setattr("bhzd_py.agent.providers.complete", fake_complete)
    api.act_as(teacher)
    response = api.client.get(
        "/api/teacher/analytics",
        params={"class_id": class_info["id"], "range": "term"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error_analysis"]["source"] == "ai"
    assert body["error_analysis"]["provider_model"] == "analysis-test-model"
    assert body["top_errors"][0]["error_type"] == "timestamp_order"
    assert body["top_errors"][0]["label"] == "时间戳顺序错误"
    assert body["top_errors"][0]["count"] == 1
    assert body["top_errors"][0]["affected_students"] == 1
    assert body["top_errors"][0]["major"] == 1
    assert captured
    prompt = "\n".join(str(message.get("content", "")) for message in captured[0])
    assert "analysis-ai-student@test.local" not in prompt


def test_error_analysis_uses_latest_completed_attempt(api):
    """A successful retry removes the earlier low-score error from the card."""

    teacher = api.login_as("analysis-latest-teacher@test.local", role="teacher")
    student = api.login_as("analysis-latest-student@test.local")
    api.act_as(teacher)
    class_info = _create_class(api, teacher, "最新评分班")
    class_info["student_id"] = student["user_id"]
    _join(api, student, class_info)
    _task_id, copy_id = _create_published_task(
        api,
        teacher,
        class_info,
        title="重做任务",
        question="重做后应保留哪次结果？",
        answer="最新结果",
        score=20,
        feedback="首次答案不完整",
    )
    exercise = api.conn.execute(
        "SELECT id FROM task_exercises WHERE task_id = ? LIMIT 1", (copy_id,)
    ).fetchone()
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO task_exercise_submissions "
        "(id, exercise_id, student_id, answer, grade_status, score, feedback, graded_at, created_at) "
        "VALUES ('latest-success', ?, ?, '重做答案', 'done', 95, '已掌握', ?, ?)",
        (exercise["id"], student["user_id"], now, now),
    )
    api.conn.commit()

    api.act_as(teacher)
    response = api.client.get(
        "/api/teacher/analytics",
        params={"class_id": class_info["id"], "range": "term"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error_analysis"]["sample_count"] == 0
    assert body["top_errors"] == []
