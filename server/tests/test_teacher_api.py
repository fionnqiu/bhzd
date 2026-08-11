"""教师端 API 测试：班级、任务、资源选择和越权隔离。"""

from __future__ import annotations

import uuid

import pytest

from _learning_fixtures import api  # noqa: F401  # pytest 夹具复用

CAP = "CAP-AUD-SEGMENT-ALIGN-001"
RES = {"type": "teaching_unit", "ref_id": "TU-AUDIO-SEGMENTATION-ALIGNMENT-001", "title": "切割话语并对齐文本时间戳"}


def _create_class(api, teacher, name="一班"):
    resp = api.client.post("/api/teacher/classes", json={"name": name}, headers=teacher["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_task(api, teacher, **overrides):
    body = {"title": "岗位任务：音频切割", "cap_ids": [CAP], "resources": [RES], "data_type": "audio"}
    body.update(overrides)
    return api.client.post("/api/teacher/tasks", json=body, headers=teacher["headers"])


def test_class_enroll_and_join_by_code(api):
    teacher = api.login_as("t1@test.local", name="王老师", role="teacher")
    clazz = _create_class(api, teacher)
    assert clazz["invite_code"]

    # 邀请码入班（学生侧）
    student = api.login_as("s1@test.local", name="小李")
    joined = api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["already_enrolled"] is False
    # 幂等：重复入班
    again = api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    assert again.json()["already_enrolled"] is True
    # 无效邀请码
    bad = api.client.post(
        "/api/student/join-class", json={"invite_code": "nope"}, headers=student["headers"]
    )
    assert bad.status_code == 404

    # 教师按邮箱加第二个学生（切回教师身份：cookie 是单槽位）
    api.login_as("s2@test.local", name="小王")
    api.act_as(teacher)
    enrolled = api.client.post(
        f"/api/teacher/classes/{clazz['id']}/enroll",
        json={"student_email": "s2@test.local"},
        headers=teacher["headers"],
    )
    assert enrolled.status_code == 201, enrolled.text
    ghost = api.client.post(
        f"/api/teacher/classes/{clazz['id']}/enroll",
        json={"student_email": "ghost@test.local"},
        headers=teacher["headers"],
    )
    assert ghost.status_code == 404

    students = api.client.get(f"/api/teacher/classes/{clazz['id']}/students")
    assert students.status_code == 200
    assert students.json()["total"] == 2
    emails = {s["email"] for s in students.json()["items"]}
    assert emails == {"s1@test.local", "s2@test.local"}
    for item in students.json()["items"]:
        for key in ("id", "name", "email", "task_count", "completion_rate", "avg_mastery", "last_active"):
            assert key in item

    # 重新生成邀请码后旧码失效
    regenerated = api.client.post(
        f"/api/teacher/classes/{clazz['id']}/invite", headers=teacher["headers"]
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["invite_code"] != clazz["invite_code"]


def test_student_profile_lists_active_classes_and_soft_leaves(api):
    """Profile class rows follow active enrollment state and leave preserves history."""
    teacher = api.login_as("t-profile-class@test.local", name="班主任", role="teacher")
    first = _create_class(api, teacher, "个人中心一班")
    second = _create_class(api, teacher, "个人中心二班")
    student = api.login_as("s-profile-class@test.local", name="班级学生")

    for clazz in (first, second):
        joined = api.client.post(
            "/api/student/join-class",
            json={"invite_code": clazz["invite_code"]},
            headers=student["headers"],
        )
        assert joined.status_code == 200, joined.text
        assert joined.json()["joined_at"]

    overview = api.client.get("/api/profile")
    assert overview.status_code == 200, overview.text
    assert {item["name"] for item in overview.json()["classes"]} == {
        "个人中心一班",
        "个人中心二班",
    }

    left = api.client.delete(
        f"/api/student/classes/{first['id']}", headers=student["headers"]
    )
    assert left.status_code == 200, left.text
    assert left.json()["class_name"] == "个人中心一班"
    remaining = api.client.get("/api/profile").json()["classes"]
    assert [item["name"] for item in remaining] == ["个人中心二班"]

    enrollment = api.conn.execute(
        "SELECT left_at FROM class_enrollments WHERE class_id = ? AND student_id = ?",
        (first["id"], student["user_id"]),
    ).fetchone()
    assert enrollment["left_at"] is not None


def test_class_students_aggregates_task_mastery_and_activity_in_one_response(api):
    """班级学生卡保留任务、掌握度和最新学习足迹的既有聚合口径。"""
    teacher = api.login_as("t-aggregate@test.local", role="teacher")
    clazz = _create_class(api, teacher, "聚合班")
    student = api.login_as("s-aggregate@test.local")
    api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    api.act_as(teacher)
    task = _create_task(api, teacher).json()
    published = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text

    student_task = api.conn.execute(
        "SELECT id FROM learning_tasks WHERE user_id = ? AND class_id = ?",
        (student["user_id"], clazz["id"]),
    ).fetchone()
    api.conn.execute(
        "UPDATE learning_tasks SET status = 'completed', updated_at = ? WHERE id = ?",
        ("2026-08-02T11:00:00+00:00", student_task["id"]),
    )
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, '', 0.7, 'teacher_task', ?)",
        (student["user_id"], CAP, "2026-08-02T12:00:00+00:00"),
    )
    api.conn.execute(
        "INSERT INTO task_attempts (id, task_id, user_id, attempt_number, submission_json, created_at) "
        "VALUES (?, ?, ?, 1, '{}', ?)",
        (uuid.uuid4().hex, student_task["id"], student["user_id"], "2026-08-02T13:00:00+00:00"),
    )
    api.conn.commit()

    response = api.client.get(f"/api/teacher/classes/{clazz['id']}/students")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["task_count"] == 1
    assert item["completion_rate"] == pytest.approx(1.0)
    assert item["avg_mastery"] == pytest.approx(0.7)
    assert item["last_active"] == "2026-08-02T13:00:00+00:00"


def test_task_validation_rules(api):
    """PRD-02 §5.4：≥1 能力节点 + ≥1 来源资料；cap 必须存在于图谱。"""
    teacher = api.login_as("t-valid@test.local", role="teacher")
    no_caps = _create_task(api, teacher, cap_ids=[])
    assert no_caps.status_code == 400 and no_caps.json()["error"]["code"] == "CAPS_REQUIRED"
    no_res = _create_task(api, teacher, resources=[])
    assert no_res.status_code == 400 and no_res.json()["error"]["code"] == "RESOURCES_REQUIRED"
    bad_cap = _create_task(api, teacher, cap_ids=["CAP-NOPE-001"])
    assert bad_cap.status_code == 400 and "CAP-NOPE-001" in bad_cap.json()["error"]["message"]
    ok = _create_task(api, teacher)
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "draft"


def test_publish_creates_student_copies(api):
    teacher = api.login_as("t-pub@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    task = _create_task(api, teacher).json()
    student = api.login_as("s-pub@test.local")
    api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    api.act_as(teacher)
    published = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"], "due_at": "2026-08-10T00:00:00+00:00", "counts_toward_mastery": True},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text
    assert published.json()["published"] == 1

    # 学生任务列表出现教师副本（source=teacher，parent_task_id 链回原件）
    api.act_as(student)
    listing = api.client.get("/api/tasks?source=teacher")
    assert listing.json()["total"] == 1
    copy = listing.json()["items"][0]
    assert copy["title"] == "岗位任务：音频切割"
    assert copy["status"] == "not_started"
    assert copy["due_at"] == "2026-08-10T00:00:00+00:00"
    row = api.conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (copy["id"],)).fetchone()
    assert row["parent_task_id"] == task["id"]
    assert row["teacher_id"] == teacher["user_id"]
    assert row["class_id"] == clazz["id"]

    # 审计已写发布记录
    audits = api.conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'teacher_task.publish'"
    ).fetchall()
    assert len(audits) == 1


def test_patch_published_task_bumps_version(api):
    """PRD-06 §10.1：改已发布任务 → version+1 新记录，学生副本不动。"""
    teacher = api.login_as("t-ver@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    task = _create_task(api, teacher).json()
    student = api.login_as("s-ver@test.local")
    api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    api.act_as(teacher)
    api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    patched = api.client.patch(
        f"/api/teacher/tasks/{task['id']}",
        json={"title": "岗位任务：音频切割（修订版）"},
        headers=teacher["headers"],
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["version_bumped"] is True
    assert body["version"] == 2
    assert body["parent_task_id"] == task["id"]
    # 学生副本还是旧标题
    copy = api.conn.execute(
        "SELECT * FROM learning_tasks WHERE parent_task_id = ?", (task["id"],)
    ).fetchone()
    assert copy["title"] == "岗位任务：音频切割"
    # 新版本原件出现在教师任务列表，旧版本原件保留
    mine = api.client.get("/api/teacher/tasks").json()
    assert mine["total"] == 2


def test_dashboard_omits_resource_review_and_rejects_teacher_review_access(api):
    """Resource review moved to the system-admin RAG boundary, not the teacher UI."""
    teacher = api.login_as("t-dash@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    student = api.login_as("s-dash@test.local")
    api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    api.act_as(teacher)
    # 学生一条薄弱掌握度；资源审核待办不再属于教师工作台。
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, '', 0.3, 'exercise', '2026-07-01')",
        (student["user_id"], CAP),
    )
    api.conn.commit()
    dash = api.client.get("/api/teacher/dashboard")
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["classes"][0]["student_count"] == 1
    assert body["classes"][0]["avg_mastery"] == pytest.approx(0.3)
    assert body["weak_caps_top5"][0]["cap_id"] == CAP
    assert body["weak_caps_top5"][0]["cap_name"] == "切割音频并对齐"
    assert body["todos"]["unpublished_teacher_tasks"] == 0
    assert "review_pending_documents" not in body["todos"]

    assert api.client.get("/api/teacher/review-queue").status_code == 404
    assert api.client.get("/api/rag/review-queue").status_code == 403

    system_admin = api.login_as("system-review@test.local", role="system_admin")
    admin_queue = api.client.get("/api/rag/review-queue", headers=system_admin["headers"])
    assert admin_queue.status_code == 200
    assert admin_queue.json() == {"items": [], "total": 0}


def test_system_admin_review_queue_returns_pending_documents_only(api):
    """The RAG-domain queue preserves its data contract after leaving the teacher router."""
    teacher = api.login_as("queue-uploader@test.local", name="资料上传者", role="teacher")
    pending_id = uuid.uuid4().hex
    excluded_id = uuid.uuid4().hex
    reviewed_at = "2026-08-06T12:00:00+00:00"

    # A pending row and an indexed decoy verify that the new admin-only URL did
    # not turn into a broad document listing when the route moved out of teacher.py.
    api.conn.executemany(
        """
        INSERT INTO rag_documents
          (id, title, file_type, source_type, source_name, version, license_status,
           status, created_by, created_at, updated_at)
        VALUES (?, ?, 'md', 'enterprise', '队列测试来源', 'v1', 'authorized', ?, ?, ?, ?)
        """,
        [
            (pending_id, "待审核资料", "review_pending", teacher["user_id"], reviewed_at, reviewed_at),
            (excluded_id, "未送审资料", "indexed", teacher["user_id"], reviewed_at, reviewed_at),
        ],
    )
    api.conn.commit()

    system_admin = api.login_as("queue-admin@test.local", role="system_admin")
    response = api.client.get("/api/rag/review-queue", headers=system_admin["headers"])
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "id": pending_id,
                "title": "待审核资料",
                "uploader_name": "资料上传者",
                "source_type": "enterprise",
                "scenario_ids": [],
                "data_types": [],
                "submitted_at": reviewed_at,
            }
        ],
        "total": 1,
    }


def test_teacher_resources_only_lists_student_eligible_documents(api):
    """The teacher picker cannot substitute for the system-admin RAG list."""
    teacher = api.login_as("t-resource-picker@test.local", role="teacher")
    now = "2026-08-06T12:00:00+00:00"
    docs = {
        "eligible_a": uuid.uuid4().hex,
        "eligible_b": uuid.uuid4().hex,
        "teacher_only": uuid.uuid4().hex,
        "not_published": uuid.uuid4().hex,
        "expired_document": uuid.uuid4().hex,
        "expired_ledger": uuid.uuid4().hex,
    }
    expired_ledger_id = uuid.uuid4().hex
    api.conn.execute(
        """
        INSERT INTO source_ledgers
          (id, source_code, name, authorization_status, related_document_ids_json,
           review_status, created_at, updated_at)
        VALUES (?, 'SRC-EXPIRED', '过期资料台账', 'expired', '[]', 'reviewed', ?, ?)
        """,
        (expired_ledger_id, now, now),
    )
    rows = [
        (docs["eligible_a"], "学生可用资料 A", "student", "published", None, None),
        (docs["eligible_b"], "学生可用资料 B", "student", "published", None, None),
        (docs["teacher_only"], "仅教师资料", "teacher", "published", None, None),
        (docs["not_published"], "尚未发布资料", "student", "indexed", None, None),
        (docs["expired_document"], "已过期资料", "student", "published", "2000-01-01T00:00:00+00:00", None),
        (docs["expired_ledger"], "过期台账资料", "student", "published", None, expired_ledger_id),
    ]
    api.conn.executemany(
        """
        INSERT INTO rag_documents
          (id, title, file_type, source_type, source_name, version, license_status,
           visibility, status, source_ledger_id, created_by, created_at, updated_at, published_at,
           expires_at)
        VALUES (?, ?, 'md', 'enterprise', '测试来源', 'v1', 'authorized', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (doc_id, title, visibility, status, ledger_id, teacher["user_id"], now, now, now, expires_at)
            for doc_id, title, visibility, status, expires_at, ledger_id in rows
        ],
    )
    api.conn.commit()

    listing = api.client.get("/api/teacher/resources", headers=teacher["headers"])
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 2
    assert {item["id"] for item in listing.json()["items"]} == {
        docs["eligible_a"],
        docs["eligible_b"],
    }
    assert all(set(item) == {"id", "title", "version"} for item in listing.json()["items"])

    filtered = api.client.get(
        "/api/teacher/resources",
        params={"q": "学生可用资料 A"},
        headers=teacher["headers"],
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"] == [
        {"id": docs["eligible_a"], "title": "学生可用资料 A", "version": "v1"}
    ]

    page = api.client.get("/api/teacher/resources?limit=1&offset=1", headers=teacher["headers"])
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1

    # The old management endpoint remains the authoritative access check and
    # must not be reopened merely because the picker has a read-only endpoint.
    assert api.client.get("/api/rag/documents", headers=teacher["headers"]).status_code == 403


def test_analytics_sample_warning_and_heatmap(api):
    """PRD-06 §10.2：学生 <3 人 sample_warning；热力图/建议来自真实数据。"""
    teacher = api.login_as("t-ana@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    student = api.login_as("s-ana@test.local")
    api.client.post(
        "/api/student/join-class", json={"invite_code": clazz["invite_code"]}, headers=student["headers"]
    )
    api.act_as(teacher)
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, '', 0.4, 'exercise', '2026-07-01')",
        (student["user_id"], CAP),
    )
    api.conn.commit()
    resp = api.client.get("/api/teacher/analytics")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sample_warning"] is True  # 只有 1 名学生
    assert body["student_count"] == 1
    assert body["heatmap"][0]["cap_id"] == CAP
    assert body["heatmap"][0]["avg_score"] == pytest.approx(0.4)
    assert body["heatmap"][0]["weak_count"] == 1
    assert any("切割音频并对齐" in s for s in body["suggestions"])
    for key in ("trend", "top_errors", "scenario_comparison"):
        assert key in body


def test_non_owner_teacher_forbidden(api):
    """蓝图 §15：教师数据按 class_teachers 隔离，非本班教师 403。"""
    owner = api.login_as("t-owner@test.local", role="teacher")
    clazz = _create_class(api, owner)
    task = _create_task(api, owner).json()
    stranger = api.login_as("t-stranger@test.local", name="另一位老师", role="teacher")

    resp = api.client.get(f"/api/teacher/classes/{clazz['id']}/students")
    assert resp.status_code == 403
    resp = api.client.get(f"/api/teacher/classes/{clazz['id']}")
    assert resp.status_code == 403
    resp = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"]},
        headers=stranger["headers"],
    )
    assert resp.status_code == 404  # 别人的任务原件：不暴露存在性
    resp = api.client.post(
        f"/api/teacher/classes/{clazz['id']}/invite", headers=stranger["headers"]
    )
    assert resp.status_code == 403
    # 学生角色直接无权进教师端
    student = api.login_as("s-nop@test.local")
    assert api.client.get("/api/teacher/dashboard").status_code == 403


def test_publish_requires_class_ownership(api):
    owner = api.login_as("t-pc@test.local", role="teacher")
    task = _create_task(api, owner).json()
    other = api.login_as("t-pc2@test.local", name="别班老师", role="teacher")
    other_class = _create_class(api, other, "别班")
    api.act_as(owner)
    resp = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": other_class["id"]},
        headers=owner["headers"],
    )
    assert resp.status_code == 403
