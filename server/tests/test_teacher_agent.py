"""Teacher-Agent ownership, aggregate-data, and confirmation-gate coverage."""

from __future__ import annotations

import json
import uuid

import pytest

from bhzd_py.agent import composer
from bhzd_py.agent import events as agent_events
from bhzd_py.agent import media

from _agent_helpers import fetch_events, wait_run_status

CAP = "CAP-AUD-SEGMENT-ALIGN-001"


def _create_class(api, teacher, name: str = "教学助手班") -> dict:
    response = api.client.post(
        "/api/teacher/classes", json={"name": name}, headers=teacher["headers"]
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_student_visible_resource(api, teacher_id: str) -> str:
    """Insert one eligible document; drafts must not fall back to private material."""

    document_id = uuid.uuid4().hex
    now = "2026-08-09T00:00:00+00:00"
    api.conn.execute(
        """
        INSERT INTO rag_documents
          (id, title, file_type, source_type, source_name, version, license_status,
           data_types_json, scenario_ids_json, cap_ids_json, visibility, status,
           created_by, created_at, updated_at, published_at)
        VALUES (?, '音频切分公开规范', 'md', 'teacher', '教师公开资料', 'v1', 'authorized',
                '["audio"]', '[]', ?, 'student', 'published', ?, ?, ?, ?)
        """,
        (document_id, json.dumps([CAP]), teacher_id, now, now, now),
    )
    api.conn.commit()
    return document_id


def _setup_class_with_analytics(api):
    teacher = api.login_as("teacher-agent-owner@test.local", name="任课教师", role="teacher")
    clazz = _create_class(api, teacher)
    student = api.login_as("teacher-agent-student@test.local", name="不应泄露的学生")
    joined = api.client.post(
        "/api/student/join-class",
        json={"invite_code": clazz["invite_code"]},
        headers=student["headers"],
    )
    assert joined.status_code == 200, joined.text
    api.act_as(teacher)
    resource_id = _seed_student_visible_resource(api, teacher["user_id"])
    # These individual records intentionally contain values that must never be
    # present in Agent tool results, events, or optional model context.
    task_id = uuid.uuid4().hex
    now = "2026-08-09T00:00:00+00:00"
    api.conn.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, cap_ids_json, source, status, steps_json, resources_json,
           counts_toward_mastery, class_id, created_by, created_at, updated_at)
        VALUES (?, ?, '学生原始任务', ?, 'teacher', 'submitted', '[]', '[]', 1, ?, ?, ?, ?)
        """,
        (task_id, student["user_id"], json.dumps([CAP]), clazz["id"], teacher["user_id"], now, now),
    )
    api.conn.execute(
        """
        INSERT INTO task_attempts
          (id, task_id, user_id, attempt_number, submission_json, score, feedback_json, created_at)
        VALUES (?, ?, ?, 1, ?, 0.2, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            task_id,
            student["user_id"],
            json.dumps({"answer": "RAW_STUDENT_ANSWER_DO_NOT_LEAK"}),
            json.dumps({"feedback": "RAW_DIAGNOSTIC_DO_NOT_LEAK"}),
            now,
        ),
    )
    api.conn.execute(
        """
        INSERT INTO diagnostic_summaries
          (id, user_id, file_format, error_count, severity_counts_json, report_json,
           weak_cap_ids_json, created_at)
        VALUES (?, ?, 'json', 1, '{}', ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            student["user_id"],
            json.dumps({"raw": "RAW_DIAGNOSTIC_REPORT_DO_NOT_LEAK"}),
            json.dumps([CAP]),
            now,
        ),
    )
    api.conn.execute(
        """
        INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at)
        VALUES (?, ?, '', 0.35, 'exercise', ?)
        """,
        (student["user_id"], CAP, now),
    )
    api.conn.commit()
    return teacher, student, clazz, resource_id


def _create_draft_run(api, teacher, clazz) -> str:
    response = api.client.post(
        "/api/teacher/agent/runs",
        json={
            "class_id": clazz["id"],
            "input": "请根据本班薄弱能力制定针对性巩固任务",
            "request_draft": True,
            "target_cap_ids": [CAP],
        },
        headers=teacher["headers"],
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_teacher_agent_uses_aggregate_only_data_and_publishes_task(api, tmp_db_path, monkeypatch):
    """The provider, run DTO, and published task remain free of individual records."""

    teacher, student, clazz, resource_id = _setup_class_with_analytics(api)
    received_messages: list[list[dict]] = []

    class FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            received_messages.append(messages)
            assert role == "primary"
            yield {"delta": "已生成可编辑的班级任务草稿。"}
            yield {"done": True, "model": "safe-test-model", "provider_id": "safe-provider"}

    monkeypatch.setattr(composer, "_providers", lambda: FakeProviders)
    run_id = _create_draft_run(api, teacher, clazz)
    assert wait_run_status(tmp_db_path, run_id, ("waiting_confirmation",)) == "waiting_confirmation"

    run = api.client.get(f"/api/teacher/agent/runs/{run_id}")
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["run"]["class_id"] == clazz["id"]
    assert payload["run"]["status"] == "waiting_confirmation"
    insights = next(
        item["result"]
        for item in payload["tool_calls"]
        if item["tool"] == "teacher.class_insights"
    )
    assert insights["student_count"] == 1
    assert insights["weak_capabilities"][0]["cap_id"] == CAP
    assert insights["weak_capabilities"][0]["avg_score"] == pytest.approx(0.35)
    assert insights["weak_capabilities"][0]["affected_student_count"] == 1
    preview = next(
        item["result"]
        for item in payload["tool_calls"]
        if item["tool"] == "teacher.task_draft_preview"
    )
    assert preview["draft"]["resources"] == [
        {"type": "rag_document", "ref_id": resource_id, "title": "音频切分公开规范"}
    ]
    assert preview["insights"]["weak_capabilities"][0]["avg_score"] == pytest.approx(0.35)
    confirmation = payload["confirmations"][0]
    assert confirmation["action_type"] == "teacher.task_publish"
    assert confirmation["preview"]["insights"]["weak_capabilities"][0]["affected_student_count"] == 1

    # The test fixture contains names, an email, a submission, feedback, and a
    # diagnostic report.  The anonymous aggregate path must exclude all of it.
    visible = json.dumps(payload, ensure_ascii=False)
    model_payload = json.dumps(received_messages, ensure_ascii=False)
    for forbidden in (
        student["user_id"],
        "teacher-agent-student@test.local",
        "不应泄露的学生",
        "RAW_STUDENT_ANSWER_DO_NOT_LEAK",
        "RAW_DIAGNOSTIC_DO_NOT_LEAK",
        "RAW_DIAGNOSTIC_REPORT_DO_NOT_LEAK",
    ):
        assert forbidden not in visible
        assert forbidden not in model_payload

    # A preview is not a write: no teacher source row or student copy exists
    # until the teacher confirms through the publish confirmation endpoint.
    before = api.conn.execute(
        "SELECT COUNT(*) AS count FROM learning_tasks WHERE user_id = ? AND source = 'teacher'",
        (teacher["user_id"],),
    ).fetchone()["count"]
    confirmed = api.client.post(
        f"/api/teacher/agent/confirmations/{confirmation['id']}/confirm",
        headers=teacher["headers"],
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["status"] == "confirmed"
    assert result["publish_required"] is False
    assert result["published"] == 1
    task = api.conn.execute(
        "SELECT * FROM learning_tasks WHERE id = ?", (result["task"]["id"],)
    ).fetchone()
    assert task["source"] == "teacher"
    assert task["status"] == "draft"
    assert task["class_id"] == clazz["id"]
    assert task["user_id"] == teacher["user_id"]

    # Agent previews use reader-friendly description/criterion field names,
    # while the teacher task editor persists its canonical notes/key contract.
    # Keep this mapping at the save boundary so a handoff cannot later fail
    # when the teacher edits or publishes the generated draft.
    expected_steps = [
        {"title": step["title"], "notes": step["description"]}
        for step in preview["draft"]["steps"]
    ]
    expected_rubric = [
        {
            "key": item["criterion"],
            "expected": item["description"],
            "weight": item["points"],
        }
        for item in preview["draft"]["rubric"]
    ]
    assert json.loads(task["steps_json"]) == expected_steps
    assert json.loads(task["rubric_json"]) == expected_rubric

    # The task DTO is the route used by the publish page after an Agent handoff;
    # it must retain the bound class and the canonical shapes on a reload.
    detail = api.client.get(f"/api/teacher/tasks/{task['id']}", headers=teacher["headers"])
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["class_id"] == clazz["id"]
    assert detail_body["steps"] == expected_steps
    assert detail_body["rubric"] == expected_rubric
    assert api.conn.execute(
        "SELECT COUNT(*) AS count FROM learning_tasks WHERE parent_task_id = ?",
        (task["id"],),
    ).fetchone()["count"] == 1
    after = api.conn.execute(
        "SELECT COUNT(*) AS count FROM learning_tasks WHERE user_id = ? AND source = 'teacher'",
        (teacher["user_id"],),
    ).fetchone()["count"]
    assert after == before + 1
    assert api.conn.execute(
        "SELECT COUNT(*) AS count FROM audit_logs WHERE action = 'teacher_agent.task_publish'"
    ).fetchone()["count"] == 1

    student_copy = api.conn.execute(
        "SELECT * FROM learning_tasks WHERE parent_task_id = ?", (task["id"],)
    ).fetchone()
    assert student_copy is not None
    assert student_copy["user_id"] == student["user_id"]
    assert student_copy["class_id"] == clazz["id"]
    assert json.loads(student_copy["steps_json"]) == expected_steps
    assert json.loads(student_copy["rubric_json"]) == expected_rubric

    # The database copy alone is not sufficient for this workflow: the
    # student-facing learning-task list is the destination the teacher expects
    # after publishing from the Agent handoff.
    api.act_as(student)
    student_listing = api.client.get("/api/tasks?source=teacher")
    assert student_listing.status_code == 200, student_listing.text
    published_items = [
        item for item in student_listing.json()["items"] if item["id"] == student_copy["id"]
    ]
    assert len(published_items) == 1
    assert published_items[0]["title"] == task["title"]
    assert published_items[0]["status"] == "not_started"
    assert published_items[0]["source"] == "teacher"


def test_teacher_agent_media_upload_is_owner_scoped_and_short_lived(api):
    """Teacher media uses a portal-specific upload gate and an opaque run token."""

    teacher = api.login_as("teacher-agent-media@test.local", name="媒体教师", role="teacher")
    clazz = _create_class(api, teacher, name="媒体班")
    upload = api.client.post(
        "/api/teacher/agent/attachments",
        files={"file": ("lesson.png", b"fake-image", "image/png")},
        headers=teacher["headers"],
    )
    assert upload.status_code == 201, upload.text
    payload = upload.json()
    assert payload["kind"] == "image"
    token = payload["attachment_token"]
    assert media.get(token, teacher["user_id"]) is not None

    run = api.client.post(
        "/api/teacher/agent/runs",
        json={
            "class_id": clazz["id"],
            "input": "请结合这张图片给出课堂建议",
            "attachment": {"attachment_token": token},
        },
        headers=teacher["headers"],
    )
    assert run.status_code == 202, run.text
    stored = api.conn.execute(
        "SELECT plan_json FROM agent_runs WHERE id = ?", (run.json()["run_id"],)
    ).fetchone()
    assert json.loads(stored["plan_json"])["teacher_request"]["attachment"] == {
        "attachment_token": token
    }

    api.act_as(teacher)
    invalid = api.client.post(
        "/api/teacher/agent/runs",
        json={
            "class_id": clazz["id"],
            "input": "再次使用已消费附件",
            "attachment": {"attachment_token": "not-a-live-token"},
        },
        headers=teacher["headers"],
    )
    assert invalid.status_code == 403


def test_teacher_agent_hides_untagged_reasoning_before_event_replay(api, tmp_db_path, monkeypatch):
    """Teacher responses share the composer gate before their SSE events persist."""

    teacher, _student, clazz, _resource = _setup_class_with_analytics(api)

    class FakeProviders:
        @staticmethod
        async def stream_deltas(_messages, *, role):
            assert role == "primary"
            yield {"delta": "reason"}
            yield {"delta": "ing: private teaching chain"}
            yield {"delta": "\n最终回答："}
            yield {"delta": "已生成可编辑的班级任务草稿。"}
            yield {"done": True, "model": "safe-test-model", "provider_id": "safe-provider"}

    monkeypatch.setattr(composer, "_providers", lambda: FakeProviders)
    run_id = _create_draft_run(api, teacher, clazz)
    assert wait_run_status(tmp_db_path, run_id, ("waiting_confirmation",)) == "waiting_confirmation"

    payload = api.client.get(f"/api/teacher/agent/runs/{run_id}", headers=teacher["headers"]).json()
    assert payload["assistant_message"]["content"] == "已生成可编辑的班级任务草稿。"

    deltas = [
        row["payload"]["delta"]
        for row in fetch_events(tmp_db_path, run_id)
        if row["event_type"] == agent_events.MESSAGE_DELTA
    ]
    assert "".join(deltas) == payload["assistant_message"]["content"]
    assert all("private teaching chain" not in delta for delta in deltas)
    assert all("reasoning:" not in delta.lower() for delta in deltas)


def test_teacher_agent_cross_class_and_role_boundaries(api, tmp_db_path):
    """A run is unreadable after either ownership or role scope no longer matches."""

    owner, _student, clazz, _resource = _setup_class_with_analytics(api)
    run_id = _create_draft_run(api, owner, clazz)
    assert wait_run_status(tmp_db_path, run_id, ("waiting_confirmation",)) == "waiting_confirmation"

    api.login_as("teacher-agent-other@test.local", name="其他教师", role="teacher")
    assert api.client.get(f"/api/teacher/agent/runs/{run_id}").status_code == 404
    assert api.client.get("/api/teacher/agent/conversations").json() == {"items": [], "total": 0}

    student = api.login_as("teacher-agent-role@test.local", role="student")
    denied = api.client.get(f"/api/teacher/agent/runs/{run_id}", headers=student["headers"])
    assert denied.status_code == 403

    # A staffing change must invalidate even the original teacher's durable
    # replay/reload route; persisted scope alone is never sufficient.
    api.conn.execute(
        "DELETE FROM class_teachers WHERE class_id = ? AND teacher_id = ?",
        (clazz["id"], owner["user_id"]),
    )
    api.conn.commit()
    api.act_as(owner)
    revoked = api.client.get(f"/api/teacher/agent/runs/{run_id}", headers=owner["headers"])
    assert revoked.status_code == 403


def test_teacher_agent_sse_replays_confirmation_and_terminal_events(api, tmp_db_path):
    """The shared durable event protocol survives a reload and closes after cancel."""

    teacher, _student, clazz, _resource = _setup_class_with_analytics(api)
    run_id = _create_draft_run(api, teacher, clazz)
    assert wait_run_status(tmp_db_path, run_id, ("waiting_confirmation",)) == "waiting_confirmation"
    run = api.client.get(f"/api/teacher/agent/runs/{run_id}").json()
    confirmation_id = run["confirmations"][0]["id"]
    cancelled = api.client.post(
        f"/api/teacher/agent/confirmations/{confirmation_id}/cancel",
        headers=teacher["headers"],
    )
    assert cancelled.status_code == 200, cancelled.text

    replay = api.client.get(f"/api/teacher/agent/runs/{run_id}/events", headers=teacher["headers"])
    assert replay.status_code == 200, replay.text
    assert f"event: {agent_events.CONFIRMATION_REQUIRED}" in replay.text
    assert f"event: {agent_events.RUN_COMPLETED}" in replay.text
    assert f"event: {agent_events.STREAM_END}" in replay.text
    assert "id: 1" in replay.text
