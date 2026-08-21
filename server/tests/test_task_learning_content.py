"""P0-7 learning-content contracts: storage, privacy, grading, and roles."""

from __future__ import annotations

import asyncio
import json

from bhzd_py.agent import providers
from bhzd_py.routers import tasks as tasks_router
from bhzd_py.tools import task_tools

CAP = "CAP-AUD-SEGMENT-ALIGN-001"
IMAGE_CAP = "CAP-IMG-BOX-ANNOTATE-001"


def _create_student_task(api, user):
    response = api.client.post(
        "/api/tasks",
        json={"title": "内容生成测试任务", "cap_ids": [CAP]},
        headers=user["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_teacher_exercise(api, teacher, task_id: str, question: str = "最小可执行练习") -> dict:
    """Attach one executable row so publish tests exercise the guarded path."""

    response = api.client.post(
        f"/api/teacher/tasks/{task_id}/exercises",
        json={
            "question": question,
            "type": "open_ended",
            "reference_answer": "完成",
        },
        headers=teacher["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_student_content_crud_hides_reference_answers(api):
    """Student detail exposes authored prompts but never the grading answer."""

    student = api.login_as("content-student@test.local")
    task = _create_student_task(api, student)
    point = api.client.post(
        f"/api/tasks/{task['id']}/knowledge-points",
        json={"title": "核心概念", "content": "先理解边界，再执行标注。"},
        headers=student["headers"],
    )
    assert point.status_code == 201, point.text
    exercise = api.client.post(
        f"/api/tasks/{task['id']}/exercises",
        json={
            "question": "请说明检查顺序",
            "reference_answer": "先检查输入，再检查输出",
        },
        headers=student["headers"],
    )
    assert exercise.status_code == 201, exercise.text
    assert "reference_answer" not in exercise.json()

    detail = api.client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # Automatic content may already be present; manual authoring is the most
    # recent entry and remains the one this privacy test is asserting.
    body["knowledge_points"].sort(key=lambda item: item["created_at"], reverse=True)
    body["exercises"].sort(key=lambda item: item["created_at"], reverse=True)
    assert body["content_status"] == "done"
    assert body["knowledge_points"][0]["title"] == "核心概念"
    assert body["exercises"][0]["question"] == "请说明检查顺序"
    assert "先检查输入" not in detail.text


def test_teacher_content_crud_is_owner_scoped_and_keeps_answers_private_to_students(api):
    """Teachers edit draft content; a student session cannot use teacher routes."""

    teacher = api.login_as("content-teacher@test.local", name="内容老师", role="teacher")
    created = api.client.post(
        "/api/teacher/tasks",
        json={"title": "教师内容任务", "cap_ids": [CAP]},
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    point = api.client.post(
        f"/api/teacher/tasks/{task_id}/knowledge-points",
        json={"title": "教师知识点", "content": "教师维护的内容"},
        headers=teacher["headers"],
    )
    assert point.status_code == 201, point.text
    exercise = api.client.post(
        f"/api/teacher/tasks/{task_id}/exercises",
        json={
            "question": "教师题目",
            "type": "multiple_choice",
            "options": ["A", "B"],
            "reference_answer": "A",
        },
        headers=teacher["headers"],
    )
    assert exercise.status_code == 201, exercise.text
    assert exercise.json()["reference_answer"] == "A"

    student = api.login_as("content-other-student@test.local")
    forbidden = api.client.get(f"/api/teacher/tasks/{task_id}/exercises")
    assert forbidden.status_code == 403
    api.act_as(teacher)
    updated = api.client.patch(
        f"/api/teacher/tasks/{task_id}/exercises/{exercise.json()['id']}",
        json={"question": "更新后的题目"},
        headers=teacher["headers"],
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["question"] == "更新后的题目"
    assert student["user_id"] != teacher["user_id"]


def test_start_learning_generates_content_and_reuses_task(api, monkeypatch):
    """Graph start is fast, while the detached worker persists deterministic content."""

    student = api.login_as("content-start@test.local")
    scheduled: list[tuple[str, str | None]] = []

    def capture(task_id: str, *, database_path: str | None = None):
        # Keep the worker detached in this test; invoke generation explicitly
        # below while asserting that enqueueing captured this fixture's DB.
        scheduled.append((task_id, database_path))

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    response = api.client.post(
        "/api/tasks/start-learning",
        json={"cap_node_id": CAP, "generate_content": True},
        headers=student["headers"],
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    assert response.json()["content_status"] == "generating"
    assert len(scheduled) == 1
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    assert scheduled[0] == (task_id, database_path)

    # A provider outage falls back to a bounded deterministic lesson, preserving
    # the main learner flow while making the generated state observable.
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(providers, "complete", unavailable)
    result = asyncio.run(tasks_router._grade_submission_async("missing-submission"))
    assert result is None
    from bhzd_py.tools.task_tools import generate_task_content

    generated = asyncio.run(generate_task_content(task_id))
    assert generated["status"] == "done"
    detail = api.client.get(f"/api/tasks/{task_id}")
    assert detail.json()["content_status"] == "done"
    assert detail.json()["knowledge_points"]
    assert detail.json()["exercises"]


def test_graph_learning_uses_reviewed_unit_when_provider_is_unavailable(api, monkeypatch):
    """A graph task stays specific offline instead of falling back to a CAP-id prompt."""

    monkeypatch.setattr(task_tools, "schedule_task_content", lambda *_args, **_kwargs: None)
    student = api.login_as("content-image-unit@test.local")
    response = api.client.post(
        "/api/tasks/start-learning",
        json={"cap_node_id": IMAGE_CAP, "generate_content": True},
        headers=student["headers"],
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    row = api.conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
    assert row is not None
    assert row["title"] == "掌握能力：绘制紧致目标框"
    assert row["goal"] == "绘制覆盖目标且尽量减少背景的矩形框。"
    assert json.loads(row["resources_json"]) == [
        {
            "type": "teaching_unit",
            "ref_id": "TU-IMAGE-OCCLUSION-TRUNCATION-001",
            "title": "区分遮挡与画面截断",
        }
    ]

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(providers, "complete", unavailable)
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    generated = asyncio.run(task_tools.generate_task_content(task_id, database_path=database_path))

    assert generated == {"knowledge_points": 2, "exercises": 1, "status": "done"}
    detail = api.client.get(f"/api/tasks/{task_id}", headers=student["headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [point["title"] for point in body["knowledge_points"]] == [
        "区分遮挡与画面截断学习目标",
        "区分遮挡与画面截断判定规则",
    ]
    assert "occlusion 表示目标仍在图像范围内" in body["knowledge_points"][1]["content"]
    assert body["exercises"][0]["question"] == "提交 JSON：分别判断 occluded 和 truncated，不得把两个状态合并为单一标签。"
    assert "reference_answer" not in body["exercises"][0]
def test_content_generation_uses_the_persisted_stage_description(api, monkeypatch):
    """A staged Agent row must give its own description to the content worker."""

    queued: list[str] = []
    monkeypatch.setattr(
        task_tools,
        "schedule_task_content",
        lambda task_id, **_kwargs: queued.append(task_id),
    )
    student = api.login_as("content-stage-description@test.local")
    created = api.client.post(
        "/api/tasks",
        json={
            "title": "文本标注练习任务·阶段2",
            "description": "针对歧义边界完成独立判断练习",
            "data_type": "text",
            "cap_ids": [CAP],
        },
        headers=student["headers"],
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert queued == [task_id]

    captured: list[list[dict]] = []

    async def generate(messages, **_kwargs):
        captured.append(messages)
        return {
            "text": json.dumps(
                {
                    "knowledge_points": [{"title": "歧义边界", "content": "核对上下文"}],
                    "exercises": [{"question": "选择正确边界", "type": "multiple_choice"}],
                },
                ensure_ascii=False,
            )
        }

    monkeypatch.setattr(providers, "complete", generate)
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    result = asyncio.run(task_tools.generate_task_content(task_id, database_path=database_path))

    assert result["status"] == "done"
    assert captured
    assert "任务描述：针对歧义边界完成独立判断练习" in captured[0][-1]["content"]


def test_task_detail_auto_queues_legacy_none_content(api, monkeypatch):
    """Opening a historical task starts generation without a learner action."""

    scheduled: list[tuple[str, str | None]] = []

    def capture(task_id: str, *, database_path: str | None = None):
        # Keep the worker out of this route test; the queue contract is the
        # behavior under test, while generation has its own persistence tests.
        scheduled.append((task_id, database_path))

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    student = api.login_as("content-legacy-detail@test.local")
    task = _create_student_task(api, student)
    scheduled.clear()
    api.conn.execute(
        "UPDATE learning_tasks SET content_status = 'none' WHERE id = ?",
        (task["id"],),
    )
    api.conn.commit()

    detail = api.client.get(f"/api/tasks/{task['id']}", headers=student["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["content_status"] == "generating"
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    assert scheduled == [(task["id"], database_path)]


def test_start_learning_targets_the_explicit_task_id(api, monkeypatch):
    """A detail-page retry must not generate content for a newer sibling task."""

    queued: list[str] = []

    def capture(task_id: str, *, database_path: str | None = None):
        queued.append(task_id)

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    student = api.login_as("content-target@test.local")
    target = _create_student_task(api, student)
    sibling = _create_student_task(api, student)
    api.conn.execute(
        "UPDATE learning_tasks SET content_status = 'none' WHERE id IN (?, ?)",
        (target["id"], sibling["id"]),
    )
    api.conn.commit()
    # Ignore the initial creation workers; this assertion covers only the
    # explicit detail-page retry and its targeted task id.
    queued.clear()
    response = api.client.post(
        "/api/tasks/start-learning",
        json={"cap_node_id": CAP, "generate_content": True, "task_id": target["id"]},
        headers=student["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == target["id"]
    assert response.json()["content_status"] == "generating"
    assert queued == [target["id"]]
    # Read the sibling directly so the historical-detail fallback does not
    # itself enqueue it while this test checks target selection.
    sibling_status = api.conn.execute(
        "SELECT content_status FROM learning_tasks WHERE id = ?", (sibling["id"],)
    ).fetchone()["content_status"]
    assert sibling_status == "none"


def test_exercise_grading_persists_done_and_failed_states(api, monkeypatch):
    """Async grading calls the grader role and always reaches a terminal state."""

    student = api.login_as("content-grade@test.local")
    task = _create_student_task(api, student)
    exercise = api.client.post(
        f"/api/tasks/{task['id']}/exercises",
        json={"question": "评分题", "reference_answer": "标准答案"},
        headers=student["headers"],
    ).json()
    scheduled: list[object] = []

    def capture(coro):
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(tasks_router, "_schedule_background", capture)
    calls: list[str] = []

    async def grade_ok(_messages, *, role="primary"):
        calls.append(role)
        return {"text": json.dumps({"score": 88, "feedback": "检查完整"}, ensure_ascii=False)}

    monkeypatch.setattr(providers, "complete", grade_ok)
    submitted = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/submit",
        json={"answer": "我的答案"},
        headers=student["headers"],
    )
    assert submitted.status_code == 202, submitted.text
    submission_id = submitted.json()["submission_id"]
    asyncio.run(tasks_router._grade_submission_async(submission_id))
    assert calls == ["grader"]
    detail = api.client.get(f"/api/tasks/{task['id']}").json()
    detail["exercises"].sort(key=lambda item: item["created_at"], reverse=True)
    submission = detail["exercises"][0]["submission"]
    assert submission["grade_status"] == "done"
    assert submission["score"] == 88

    async def grade_fail(*_args, **_kwargs):
        raise RuntimeError("grader down")

    monkeypatch.setattr(providers, "complete", grade_fail)
    second = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/submit",
        json={"answer": "再次作答"},
        headers=student["headers"],
    )
    assert second.status_code == 202
    asyncio.run(tasks_router._grade_submission_async(second.json()["submission_id"]))
    detail = api.client.get(f"/api/tasks/{task['id']}").json()
    detail["exercises"].sort(key=lambda item: item["created_at"], reverse=True)
    assert detail["exercises"][0]["submission"]["grade_status"] == "failed"


def test_failed_grading_retry_preserves_original_answer(api, monkeypatch):
    """A provider failure creates a linked retry row instead of rewriting history."""

    student = api.login_as("content-grade-retry@test.local")
    task = _create_student_task(api, student)
    exercise = api.client.post(
        f"/api/tasks/{task['id']}/exercises",
        json={"question": "可重试评分题", "reference_answer": "标准答案"},
        headers=student["headers"],
    ).json()
    scheduled: list[object] = []

    def capture(coro):
        # The request path is tested separately from the worker; closing the
        # coroutine keeps this focused test deterministic and leak-free.
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(tasks_router, "_schedule_background", capture)

    async def fail_provider(*_args, **_kwargs):
        raise RuntimeError("provider secret must not persist")

    monkeypatch.setattr(providers, "complete", fail_provider)
    first = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/submit",
        json={"answer": "原始答案"},
        headers=student["headers"],
    )
    assert first.status_code == 202, first.text
    first_id = first.json()["submission_id"]
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    asyncio.run(tasks_router._grade_submission_async(first_id, database_path=database_path))

    failed = api.conn.execute(
        "SELECT * FROM task_exercise_submissions WHERE id = ?", (first_id,)
    ).fetchone()
    assert failed["grade_status"] == "failed"
    assert failed["answer"] == "原始答案"
    assert failed["grade_retry_count"] == 0
    assert failed["manual_review_required"] == 0
    assert failed["grade_failure_reason"]
    assert "provider secret" not in failed["grade_failure_reason"]

    retry = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/retry-grade",
        headers=student["headers"],
    )
    assert retry.status_code == 202, retry.text
    retry_id = retry.json()["submission_id"]
    assert retry_id != first_id
    assert retry.json()["retry_count"] == 1
    linked = api.conn.execute(
        "SELECT retry_of_submission_id, answer, grade_status, grade_retry_count "
        "FROM task_exercise_submissions WHERE id = ?",
        (retry_id,),
    ).fetchone()
    assert tuple(linked) == (first_id, "原始答案", "pending", 1)

    async def grade_retry(_messages, *, role="primary", **_kwargs):
        assert role == "grader"
        return {"text": json.dumps({"score": 76, "feedback": "重试评分完成"}, ensure_ascii=False)}

    monkeypatch.setattr(providers, "complete", grade_retry)
    asyncio.run(tasks_router._grade_submission_async(retry_id, database_path=database_path))
    original = api.conn.execute(
        "SELECT answer, grade_status, score FROM task_exercise_submissions WHERE id = ?",
        (first_id,),
    ).fetchone()
    retried = api.conn.execute(
        "SELECT retry_of_submission_id, answer, grade_status, score, grade_retry_count "
        "FROM task_exercise_submissions WHERE id = ?",
        (retry_id,),
    ).fetchone()
    assert tuple(original) == ("原始答案", "failed", None)
    assert tuple(retried) == (first_id, "原始答案", "done", 76, 1)


def test_grading_retry_exhaustion_promotes_manual_review(api, monkeypatch):
    """Exhausted automatic attempts remain visible and become teacher-review work."""

    student = api.login_as("content-grade-exhausted@test.local")
    task = _create_student_task(api, student)
    exercise = api.client.post(
        f"/api/tasks/{task['id']}/exercises",
        json={"question": "人工评阅题", "reference_answer": "标准答案"},
        headers=student["headers"],
    ).json()
    monkeypatch.setattr(tasks_router, "_schedule_background", lambda coro: coro.close())

    async def fail_provider(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(providers, "complete", fail_provider)
    first = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/submit",
        json={"answer": "待评答案"},
        headers=student["headers"],
    )
    first_id = first.json()["submission_id"]
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    # Lower the fixture limit to one so the test reaches the manual-review
    # branch with one explicit retry rather than waiting through two retries.
    api.conn.execute(
        "UPDATE task_exercise_submissions SET grade_retry_limit = 1 WHERE id = ?",
        (first_id,),
    )
    api.conn.commit()
    asyncio.run(tasks_router._grade_submission_async(first_id, database_path=database_path))

    retry = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/retry-grade",
        headers=student["headers"],
    )
    assert retry.status_code == 202, retry.text
    retry_id = retry.json()["submission_id"]
    asyncio.run(tasks_router._grade_submission_async(retry_id, database_path=database_path))

    exhausted = api.conn.execute(
        "SELECT grade_status, grade_retry_count, grade_retry_limit, manual_review_required "
        "FROM task_exercise_submissions WHERE id = ?",
        (retry_id,),
    ).fetchone()
    assert tuple(exhausted) == ("failed", 1, 1, 1)
    blocked = api.client.post(
        f"/api/tasks/{task['id']}/exercises/{exercise['id']}/retry-grade",
        headers=student["headers"],
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "GRADE_RETRY_EXHAUSTED"

    detail = api.client.get(f"/api/tasks/{task['id']}", headers=student["headers"])
    submission = next(
        item["submission"]
        for item in detail.json()["exercises"]
        if item["id"] == exercise["id"]
    )
    assert submission["manual_review_required"] is True
    assert submission["can_retry"] is False


def test_interrupted_grading_recovery_requeues_pending_and_claimed_rows(api, monkeypatch):
    """Startup recovery resets dead claims and schedules every unfinished row."""

    student = api.login_as("content-grade-recovery@test.local")
    task = _create_student_task(api, student)
    exercise = api.client.post(
        f"/api/tasks/{task['id']}/exercises",
        json={"question": "恢复评分题", "reference_answer": "标准答案"},
        headers=student["headers"],
    ).json()
    monkeypatch.setattr(tasks_router, "_schedule_background", lambda coro: coro.close())
    submissions = []
    for answer in ("待恢复一", "待恢复二"):
        response = api.client.post(
            f"/api/tasks/{task['id']}/exercises/{exercise['id']}/submit",
            json={"answer": answer},
            headers=student["headers"],
        )
        assert response.status_code == 202
        submissions.append(response.json()["submission_id"])
    api.conn.execute(
        "UPDATE task_exercise_submissions SET grade_status = 'grading' WHERE id = ?",
        (submissions[0],),
    )
    api.conn.commit()

    scheduled: list[str] = []

    def capture_schedule(conn, submission_id):
        scheduled.append(submission_id)

    monkeypatch.setattr(tasks_router, "_schedule_grade_submission", capture_schedule)
    recovered = tasks_router.recover_interrupted_submission_grading(api.conn)
    assert set(recovered) == set(submissions)
    assert scheduled == recovered
    statuses = api.conn.execute(
        "SELECT id, grade_status FROM task_exercise_submissions ORDER BY created_at, rowid"
    ).fetchall()
    assert {row["id"]: row["grade_status"] for row in statuses} == {
        submissions[0]: "pending",
        submissions[1]: "pending",
    }


def test_teacher_create_and_publish_copies_authored_content_for_each_task(api, monkeypatch):
    """Teacher-authored rows publish only after an executable exercise exists."""

    queued: list[str] = []

    def capture(task_id: str, *, database_path: str | None = None):
        queued.append(task_id)

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    teacher = api.login_as("content-auto-teacher@test.local", role="teacher")
    created = api.client.post(
        "/api/teacher/tasks",
        json={"title": "teacher auto content", "cap_ids": [CAP]},
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["id"]
    assert created.json()["content_status"] == "generating"
    assert queued == [parent_id]
    _add_teacher_exercise(api, teacher, parent_id)

    clazz = api.client.post(
        "/api/teacher/classes",
        json={"name": "auto generation class"},
        headers=teacher["headers"],
    ).json()
    student = api.login_as("content-auto-student@test.local")
    joined = api.client.post(
        "/api/student/join-class",
        json={"invite_code": clazz["invite_code"]},
        headers=student["headers"],
    )
    assert joined.status_code == 200, joined.text
    api.act_as(teacher)
    published = api.client.post(
        f"/api/teacher/tasks/{parent_id}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text
    copy = api.conn.execute(
        "SELECT id, content_status FROM learning_tasks WHERE parent_task_id = ?",
        (parent_id,),
    ).fetchone()
    assert copy is not None
    # Authored rows are copied transactionally, so no detached generation worker
    # is needed for the student copy.
    assert copy["content_status"] == "done"
    assert copy["id"] not in queued


def test_teacher_publish_copies_content_to_every_active_student(api, monkeypatch):
    """Publishing copies the executable lesson to every active student row."""

    queued: list[str] = []

    def capture(task_id: str, *, database_path: str | None = None):
        # Keep workers detached so this assertion covers the post-commit fan-out
        # contract rather than timing-dependent provider completion.
        queued.append(task_id)

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    teacher = api.login_as("content-fanout-teacher@test.local", role="teacher")
    created = api.client.post(
        "/api/teacher/tasks",
        json={"title": "fanout content", "cap_ids": [CAP]},
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["id"]
    _add_teacher_exercise(api, teacher, parent_id)

    clazz_response = api.client.post(
        "/api/teacher/classes",
        json={"name": "fanout class"},
        headers=teacher["headers"],
    )
    assert clazz_response.status_code == 201, clazz_response.text
    clazz = clazz_response.json()
    student_ids: list[str] = []
    for index in range(2):
        student = api.login_as(f"content-fanout-student-{index}@test.local")
        student_ids.append(student["user_id"])
        joined = api.client.post(
            "/api/student/join-class",
            json={"invite_code": clazz["invite_code"]},
            headers=student["headers"],
        )
        assert joined.status_code == 200, joined.text

    # Only the publish operation is under test; discard the source-row enqueue.
    queued.clear()
    api.act_as(teacher)
    published = api.client.post(
        f"/api/teacher/tasks/{parent_id}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text
    copies = api.conn.execute(
        "SELECT id, user_id, content_status FROM learning_tasks "
        "WHERE parent_task_id = ? ORDER BY user_id",
        (parent_id,),
    ).fetchall()
    assert [row["user_id"] for row in copies] == sorted(student_ids)
    assert all(row["content_status"] == "done" for row in copies)
    assert queued == []


def test_teacher_fanout_generates_source_once_and_copies_content(api, monkeypatch):
    """One generated source lesson satisfies publish and is copied to students."""

    scheduled: list[str] = []

    def capture(task_id: str, *, database_path: str | None = None):
        # Keep the detached workers under explicit control so this test can
        # assert provider-call cardinality without timing-dependent callbacks.
        scheduled.append(task_id)

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    calls: list[tuple[str, str | None]] = []

    async def complete_once(_messages, *, role="primary", database_path=None, **_kwargs):
        calls.append((role, database_path))
        return {
            "text": json.dumps(
                {
                    "knowledge_points": [{"title": "共享知识点", "content": "共享内容"}],
                    "exercises": [
                        {
                            "question": "共享练习",
                            "type": "open_ended",
                            "reference_answer": "共享答案",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

    monkeypatch.setattr(providers, "complete", complete_once)
    teacher = api.login_as("content-reuse-teacher@test.local", role="teacher")
    created = api.client.post(
        "/api/teacher/tasks",
        json={"title": "reuse content", "cap_ids": [CAP]},
        headers=teacher["headers"],
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["id"]
    database_path = api.conn.execute("PRAGMA database_list").fetchone()[2]
    generated = asyncio.run(
        task_tools.generate_task_content(parent_id, database_path=database_path)
    )
    assert generated["status"] == "done"
    assert calls == [("primary", database_path)]
    clazz = api.client.post(
        "/api/teacher/classes",
        json={"name": "reuse class"},
        headers=teacher["headers"],
    ).json()
    students: list[str] = []
    for index in range(2):
        student = api.login_as(f"content-reuse-student-{index}@test.local")
        students.append(student["user_id"])
        joined = api.client.post(
            "/api/student/join-class",
            json={"invite_code": clazz["invite_code"]},
            headers=student["headers"],
        )
        assert joined.status_code == 200, joined.text

    # The parent enqueue is intentionally not executed; the explicit source
    # generation above makes the publish transaction copy a complete lesson.
    scheduled.clear()
    api.act_as(teacher)
    published = api.client.post(
        f"/api/teacher/tasks/{parent_id}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text
    copies = api.conn.execute(
        "SELECT id FROM learning_tasks WHERE parent_task_id = ? ORDER BY user_id",
        (parent_id,),
    ).fetchall()
    assert len(copies) == len(students)
    assert scheduled == []
    assert calls == [("primary", database_path)]
    parent_counts = api.conn.execute(
        "SELECT COUNT(*) AS points FROM task_knowledge_points WHERE task_id = ?",
        (parent_id,),
    ).fetchone()
    assert parent_counts["points"] == 1
    for row in copies:
        detail = api.conn.execute(
            "SELECT content_status FROM learning_tasks WHERE id = ?", (row["id"],)
        ).fetchone()
        counts = api.conn.execute(
            "SELECT COUNT(*) AS points FROM task_knowledge_points WHERE task_id = ?",
            (row["id"],),
        ).fetchone()
        assert detail["content_status"] == "done"
        assert counts["points"] == 1
        exercise_count = api.conn.execute(
            "SELECT COUNT(*) AS exercises FROM task_exercises WHERE task_id = ?",
            (row["id"],),
        ).fetchone()
        assert exercise_count["exercises"] == 1


def test_mark_task_content_generating_claim_is_idempotent(api):
    """Only the first normal enqueue may claim a task in ``none`` state."""

    student = api.login_as("content-claim@test.local")
    task = _create_student_task(api, student)
    api.conn.execute(
        "UPDATE learning_tasks SET content_status = 'none' WHERE id = ?", (task["id"],)
    )
    api.conn.commit()
    assert task_tools.mark_task_content_generating(api.conn, task["id"]) is True
    assert task_tools.mark_task_content_generating(api.conn, task["id"]) is False
    status = api.conn.execute(
        "SELECT content_status FROM learning_tasks WHERE id = ?", (task["id"],)
    ).fetchone()["content_status"]
    assert status == "generating"
