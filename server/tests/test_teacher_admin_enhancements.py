"""教师/管理域增强测试（A3）：站内通知、任务生命周期触达、诊断授权查看、
Agent 任务卡生成、逐学生学情明细、告警评估。

夹具策略（为什么）：
- 入班/建库直接 INSERT（不依赖并行开发中的学生端路由），教师/管理操作走
  真实 API，测到的仍是完整的会话 + CSRF + 角色校验链路。
- notifications 路由尚未进 app.py 的 ROUTER_MODULES（地基清单由集成阶段
  维护），测试在 create_app 后手动挂载；即使后续清单补上行，重复 include
  指向同一批视图函数，行为不变。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _learning_fixtures import Api, make_session, make_user
from bhzd_py import db as db_module
from bhzd_py.app import create_app
from bhzd_py.routers.notifications import router as notifications_router
from bhzd_py.security import generate_token, hash_token

CAP = "CAP-AUD-SEGMENT-ALIGN-001"
SCN = "SCN-CUSTOMER-SERVICE-001"
RES = {"type": "teaching_unit", "ref_id": "TU-AUDIO-SEGMENTATION-ALIGNMENT-001", "title": "切割话语并对齐文本时间戳"}


@pytest.fixture()
def api(tmp_db_path):
    """每测试独立临时库 + 全量应用（notifications 路由手动挂载，见模块 docstring）。"""
    conn = db_module.connect(tmp_db_path)
    db_module.apply_migrations(conn)
    app = create_app()
    app.include_router(notifications_router)
    with TestClient(app) as client:
        yield Api(conn, client)
    conn.close()


# ---------------------------------------------------------------- 公共辅助


def _login_admin(api, email="admin@test.local") -> dict:
    """直接 INSERT 管理端会话（bhzd_admin_session cookie），与 deps.py 读取口径一致。"""
    user_id = make_user(api.conn, email, "系统管理员", role="system_admin")
    token, csrf = generate_token(), generate_token()
    now = datetime.now(timezone.utc)
    api.conn.execute(
        "INSERT INTO admin_sessions (id, user_id, token_hash, csrf_token_hash, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, user_id, hash_token(token), hash_token(csrf),
         now.isoformat(), (now + timedelta(hours=72)).isoformat()),
    )
    api.conn.commit()
    api.client.cookies.set("bhzd_admin_session", token)
    return {"user_id": user_id, "token": token, "headers": {"x-csrf-token": csrf}}


def _create_class(api, teacher, name="一班") -> dict:
    resp = api.client.post("/api/teacher/classes", json={"name": name}, headers=teacher["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _enroll(api, class_id: str, student_id: str) -> None:
    """直接 INSERT 在班记录（绕开学生端路由，保持本域测试自足）。"""
    api.conn.execute(
        "INSERT INTO class_enrollments (class_id, student_id, joined_at) VALUES (?, ?, ?)",
        (class_id, student_id, db_module.utc_now_iso()),
    )
    api.conn.commit()


def _create_task(api, teacher, **overrides) -> dict:
    body = {"title": "岗位任务：音频切割", "cap_ids": [CAP], "resources": [RES], "data_type": "audio"}
    body.update(overrides)
    resp = api.client.post("/api/teacher/tasks", json=body, headers=teacher["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _notifications_of(api, user_id: str) -> list[dict]:
    rows = api.conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _seed_diagnostic_summary(api, student_id: str) -> str:
    summary_id = uuid.uuid4().hex
    api.conn.execute(
        "INSERT INTO diagnostic_summaries "
        "(id, user_id, file_format, data_type, error_count, severity_counts_json, report_json, created_at) "
        "VALUES (?, ?, 'json', 'text', 2, ?, ?, ?)",
        (
            summary_id,
            student_id,
            json.dumps({"major": 1, "minor": 1}),
            json.dumps({"errors": [{"error_type": "duration_out_of_range", "severity": "major"}]}, ensure_ascii=False),
            db_module.utc_now_iso(),
        ),
    )
    api.conn.commit()
    return summary_id


def _set_share_diagnostics(api, student_id: str, enabled: bool) -> None:
    """直接写授权开关（学生侧的开关端点在 profile.py，属另一代理的范畴）。"""
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO learning_profiles (user_id, share_diagnostics, created_at, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET share_diagnostics = excluded.share_diagnostics",
        (student_id, 1 if enabled else 0, now, now),
    )
    api.conn.commit()


# ---------------------------------------------------------------- 1. 站内通知


def test_notifications_read_flow(api):
    """列表/未读数/单条已读/全部已读/越读他人通知 404/CSRF 校验。"""
    student = api.login_as("s-noti@test.local", name="小李")
    other = api.login_as("s-noti2@test.local", name="小王")
    api.act_as(student)

    # 通过发布任务制造一条真实通知（顺带验证发布触达）
    api.act_as(other)
    teacher = api.login_as("t-noti@test.local", role="teacher", name="王老师")
    clazz = _create_class(api, teacher)
    _enroll(api, clazz["id"], student["user_id"])
    task = _create_task(api, teacher)
    published = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"]},
        headers=teacher["headers"],
    )
    assert published.status_code == 201, published.text

    api.act_as(student)
    unread = api.client.get("/api/notifications/unread-count")
    assert unread.status_code == 200 and unread.json()["unread"] == 1
    listed = api.client.get("/api/notifications", params={"unread": 1})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    item = listed.json()["items"][0]
    assert item["type"] == "task_published"
    assert item["title"] == task["title"]
    assert item["ref_type"] == "task" and item["ref_id"] == task["id"]

    # 未带 CSRF 的变更请求一律 403
    no_csrf = api.client.post(f"/api/notifications/{item['id']}/read")
    assert no_csrf.status_code == 403

    read = api.client.post(f"/api/notifications/{item['id']}/read", headers=student["headers"])
    assert read.status_code == 200 and read.json()["read"] is True
    assert api.client.get("/api/notifications/unread-count").json()["unread"] == 0
    # 幂等：重复已读不报错
    again = api.client.post(f"/api/notifications/{item['id']}/read", headers=student["headers"])
    assert again.status_code == 200

    # 他人的通知按 404 处理（不暴露存在性）
    api.act_as(other)
    foreign = api.client.post(f"/api/notifications/{item['id']}/read", headers=other["headers"])
    assert foreign.status_code == 404

    # read-all：给学生再补两条，一键全读
    from bhzd_py.notify import notify_many

    notify_many(api.conn, [student["user_id"]], "task_published", "任务A")
    notify_many(api.conn, [student["user_id"]], "task_due_changed", "任务B")
    api.conn.commit()
    api.act_as(student)
    assert api.client.get("/api/notifications/unread-count").json()["unread"] == 2
    cleared = api.client.post("/api/notifications/read-all", headers=student["headers"])
    assert cleared.status_code == 200 and cleared.json()["updated"] == 2
    assert api.client.get("/api/notifications/unread-count").json()["unread"] == 0


def test_publish_notifies_each_enrolled_student(api):
    teacher = api.login_as("t-pub2@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    s1 = api.login_as("s-pub21@test.local")
    s2 = api.login_as("s-pub22@test.local")
    outsider = api.login_as("s-pub23@test.local")
    _enroll(api, clazz["id"], s1["user_id"])
    _enroll(api, clazz["id"], s2["user_id"])
    api.act_as(teacher)
    task = _create_task(api, teacher)
    resp = api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"], "due_at": "2026-08-10T12:00:00+00:00"},
        headers=teacher["headers"],
    )
    assert resp.status_code == 201 and resp.json()["published"] == 2

    for sid in (s1["user_id"], s2["user_id"]):
        notes = _notifications_of(api, sid)
        assert len(notes) == 1
        assert notes[0]["type"] == "task_published"
        assert notes[0]["title"] == task["title"]
        assert notes[0]["ref_type"] == "task" and notes[0]["ref_id"] == task["id"]
        assert notes[0]["read_at"] is None
    # 未入班的学生不收到通知
    assert _notifications_of(api, outsider["user_id"]) == []


def test_due_change_on_published_task_notifies(api):
    """PRD-06 §10.1：截止时间变更→学生副本更新 + 站内通知 + 审计，不升版本。"""
    teacher = api.login_as("t-due@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    s1 = api.login_as("s-due@test.local")
    _enroll(api, clazz["id"], s1["user_id"])
    api.act_as(teacher)
    task = _create_task(api, teacher)
    api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"], "due_at": "2026-08-10T12:00:00+00:00"},
        headers=teacher["headers"],
    )
    patched = api.client.patch(
        f"/api/teacher/tasks/{task['id']}",
        json={"due_at": "2026-08-15T12:00:00+00:00"},
        headers=teacher["headers"],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version_bumped"] is False  # 截止变更不触发版本升级

    # 学生副本的截止时间已更新
    copy = api.conn.execute(
        "SELECT due_at FROM learning_tasks WHERE parent_task_id = ?", (task["id"],)
    ).fetchone()
    assert copy["due_at"] == "2026-08-15T12:00:00+00:00"

    notes = [n for n in _notifications_of(api, s1["user_id"]) if n["type"] == "task_due_changed"]
    assert len(notes) == 1
    assert "2026-08-15" in notes[0]["body"]
    assert notes[0]["ref_id"] == task["id"]

    audits = api.conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'teacher_task.due_change' AND target_id = ?",
        (task["id"],),
    ).fetchall()
    assert len(audits) == 1
    assert json.loads(audits[0]["after_json"])["due_at"] == "2026-08-15T12:00:00+00:00"


def test_due_change_on_unpublished_task_no_notification(api):
    teacher = api.login_as("t-due2@test.local", role="teacher")
    task = _create_task(api, teacher)
    patched = api.client.patch(
        f"/api/teacher/tasks/{task['id']}",
        json={"due_at": "2026-08-20T12:00:00+00:00"},
        headers=teacher["headers"],
    )
    assert patched.status_code == 200 and patched.json()["version_bumped"] is False
    row = api.conn.execute("SELECT due_at FROM learning_tasks WHERE id = ?", (task["id"],)).fetchone()
    assert row["due_at"] == "2026-08-20T12:00:00+00:00"
    total = api.conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
    assert total == 0  # 未发布没有学生受影响，不产生通知


def test_content_patch_on_published_still_version_bumps(api):
    """回归：内容修改仍走版本升级，且不影响学生副本的截止时间。"""
    teacher = api.login_as("t-ver@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    s1 = api.login_as("s-ver@test.local")
    _enroll(api, clazz["id"], s1["user_id"])
    api.act_as(teacher)
    task = _create_task(api, teacher)
    api.client.post(
        f"/api/teacher/tasks/{task['id']}/publish",
        json={"class_id": clazz["id"], "due_at": "2026-08-10T12:00:00+00:00"},
        headers=teacher["headers"],
    )
    patched = api.client.patch(
        f"/api/teacher/tasks/{task['id']}",
        json={"title": "岗位任务：音频切割（修订版）"},
        headers=teacher["headers"],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version_bumped"] is True
    assert patched.json()["version"] == 2
    # 内容升级不产生截止变更通知
    notes = [n for n in _notifications_of(api, s1["user_id"]) if n["type"] == "task_due_changed"]
    assert notes == []


# ---------------------------------------------------------------- 2. 学生授权教师查看诊断（PRD-06 §15 #2）


def test_student_diagnostics_share_gate(api):
    teacher = api.login_as("t-diag@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    s1 = api.login_as("s-diag@test.local")
    _enroll(api, clazz["id"], s1["user_id"])
    summary_id = _seed_diagnostic_summary(api, s1["user_id"])
    api.act_as(teacher)
    url = f"/api/teacher/classes/{clazz['id']}/students/{s1['user_id']}/diagnostics"

    denied = api.client.get(url)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "SHARE_NOT_GRANTED"

    _set_share_diagnostics(api, s1["user_id"], True)
    allowed = api.client.get(url)
    assert allowed.status_code == 200, allowed.text
    payload = allowed.json()
    assert payload["total"] == 1 and payload["shared"] is True
    item = payload["items"][0]
    assert item["id"] == summary_id
    assert item["file_format"] == "json"
    assert item["error_count"] == 2
    assert item["severity_counts"] == {"major": 1, "minor": 1}
    assert item["report"]["errors"][0]["error_type"] == "duration_out_of_range"

    # 非本班教师 403；学生不在班也 403
    other_teacher = api.login_as("t-diag2@test.local", role="teacher")
    api.act_as(other_teacher)
    assert api.client.get(url).status_code == 403

    s2 = api.login_as("s-diag2@test.local")
    api.act_as(teacher)
    not_enrolled = api.client.get(f"/api/teacher/classes/{clazz['id']}/students/{s2['user_id']}/diagnostics")
    assert not_enrolled.status_code == 403


# ---------------------------------------------------------------- 3. Agent 任务卡生成（PRD-02 §5.3）


def _seed_published_doc(api, uploader_id: str) -> str:
    """造一份已发布+学生可见+已授权的资料（含真实嵌入的切片），让召回能命中。"""
    from bhzd_py.rag.embeddings import embed_chunks

    content = (
        "客服语音情感标注规范：标注员需要根据客服录音的语音内容判断情感类别，"
        "为每段语音标注情感标签。标注时先切片对齐文本，再逐段判定情感极性，"
        "最后按质检规则自检一遍，确保情感标注结果符合规范要求。"
    )
    doc_id = uuid.uuid4().hex
    now = db_module.utc_now_iso()
    api.conn.execute(
        """
        INSERT INTO rag_documents
          (id, title, file_type, source_type, source_name, version, license_status,
           data_types_json, scenario_ids_json, cap_ids_json, visibility, status,
           created_by, created_at, updated_at, published_at)
        VALUES (?, '客服语音情感标注规范', 'md', 'standard', '赛项组委会', 'v1', 'authorized',
                ?, ?, ?, 'student', 'published', ?, ?, ?, ?)
        """,
        (
            doc_id,
            json.dumps(["audio"]),
            json.dumps([SCN]),
            json.dumps([CAP]),
            uploader_id,
            now, now, now,
        ),
    )
    blobs, model = embed_chunks(api.conn, [content])
    api.conn.execute(
        """
        INSERT INTO rag_chunks
          (id, document_id, chunk_index, content, keywords_json, token_count,
           embedding, embedding_model, metadata_json, status, process_version)
        VALUES (?, ?, 0, ?, '[]', ?, ?, ?, '{}', 'active', 1)
        """,
        (uuid.uuid4().hex, doc_id, content, len(content) // 2, blobs[0], model),
    )
    api.conn.commit()
    return doc_id


def test_generate_task_card_offline(api):
    """离线（无 LLM）生成完整草稿：cap_ids 非空、引用来自已发布资料、不落库。"""
    teacher = api.login_as("t-gen@test.local", role="teacher")
    doc_id = _seed_published_doc(api, teacher["user_id"])
    before = api.conn.execute("SELECT COUNT(*) AS n FROM learning_tasks").fetchone()["n"]

    resp = api.client.post(
        "/api/teacher/tasks/generate",
        json={"description": "客服语音情感标注任务：让学生根据客服录音标注情感标签"},
        headers=teacher["headers"],
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    assert draft["title"]
    assert draft["goal"]
    assert draft["data_type"] == "audio"  # intents 识别结果
    assert draft["scenario_id"] == SCN
    assert draft["cap_ids"], "cap_ids 不能为空"
    assert draft["caps"][0]["cap_name"]
    assert len(draft["steps"]) >= 3
    assert len(draft["rubric"]) == 3
    assert draft["citations"], "已发布资料命中时 citations 不能为空"
    assert draft["citations"][0]["document_id"] == doc_id
    assert draft["resources"][0]["citation"]
    assert draft["sources_note"]
    assert draft["llm_used"] is False  # 测试环境无 provider，走模板降级
    after = api.conn.execute("SELECT COUNT(*) AS n FROM learning_tasks").fetchone()["n"]
    assert after == before, "生成草稿不得落库（教师编辑后才创建）"

    # 学生角色 403
    student = api.login_as("s-gen@test.local")
    api.act_as(student)
    forbidden = api.client.post(
        "/api/teacher/tasks/generate",
        json={"description": "客服语音标注"},
        headers=student["headers"],
    )
    assert forbidden.status_code == 403


# ---------------------------------------------------------------- 4. 逐学生学情明细（PRD-02 §6）


def _seed_student_learning(api, student_id: str) -> None:
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, '', 0.45, 'exercise', ?)",
        (student_id, CAP, now),
    )
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, ?, ?, 0.7, 'exercise', ?)",
        (student_id, CAP, SCN, now),
    )
    task_id = uuid.uuid4().hex
    api.conn.execute(
        "INSERT INTO learning_tasks "
        "(id, user_id, title, source, status, created_by, created_at, updated_at) "
        "VALUES (?, ?, '客服语音练习', 'agent', 'completed', ?, ?, ?)",
        (task_id, student_id, student_id, now, now),
    )
    api.conn.execute(
        "INSERT INTO task_attempts (id, task_id, user_id, attempt_number, submission_json, score, created_at) "
        "VALUES (?, ?, ?, 1, '{}', 0.8, ?)",
        (uuid.uuid4().hex, task_id, student_id, now),
    )
    api.conn.execute(
        "INSERT INTO mastery_events (id, user_id, cap_id, scenario_id, old_score, new_score, source, created_at) "
        "VALUES (?, ?, ?, '', 0.3, 0.45, 'exercise', ?)",
        (uuid.uuid4().hex, student_id, CAP, now),
    )
    api.conn.commit()


def test_student_analytics_detail(api):
    teacher = api.login_as("t-ana@test.local", role="teacher")
    clazz = _create_class(api, teacher)
    s1 = api.login_as("s-ana@test.local")
    _enroll(api, clazz["id"], s1["user_id"])
    _seed_student_learning(api, s1["user_id"])
    _seed_diagnostic_summary(api, s1["user_id"])
    api.act_as(teacher)
    url = f"/api/teacher/analytics/students/{s1['user_id']}"

    resp = api.client.get(url, params={"class_id": clazz["id"]})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["mastery"]) == 2  # 通用 + 场景两条
    general = [m for m in payload["mastery"] if m["scenario_id"] == ""][0]
    assert general["cap_id"] == CAP and general["cap_name"]
    assert general["score"] == pytest.approx(0.45)
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["status"] == "completed"
    assert payload["tasks"][0]["score"] == pytest.approx(0.8)
    assert len(payload["mastery_events"]) == 1
    assert payload["mastery_events"][0]["new_score"] == pytest.approx(0.45)

    # 未授权：诊断只回 note 不回数据（PRD-06 §10.2）
    assert payload["diagnostics"] is None
    assert payload["diagnostics_note"]

    # 授权后：诊断摘要可见
    _set_share_diagnostics(api, s1["user_id"], True)
    shared = api.client.get(url, params={"class_id": clazz["id"]}).json()
    assert shared["diagnostics"] and shared["diagnostics"][0]["error_count"] == 2
    assert shared["diagnostics_note"] is None

    # 非本班教师 403
    other_teacher = api.login_as("t-ana2@test.local", role="teacher")
    api.act_as(other_teacher)
    assert api.client.get(url, params={"class_id": clazz["id"]}).status_code == 403


# ---------------------------------------------------------------- 5. 告警评估（PRD-06 §13.2）


def _alerts(api) -> list[dict]:
    resp = api.client.get("/api/admin/alerts")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["evaluated_at"]
    return payload["alerts"]


def test_admin_alerts_requires_admin_session(api):
    # 无会话 → 401；普通用户会话 → 401/403（/api/admin/* 仅认管理端会话）
    assert api.client.get("/api/admin/alerts").status_code == 401
    api.login_as("t-alr@test.local", role="teacher")
    assert api.client.get("/api/admin/alerts").status_code in (401, 403)


def test_admin_alerts_healthy_database_is_empty(api):
    _login_admin(api)
    assert _alerts(api) == []


def test_admin_alerts_agent_run_failure(api):
    """5 分钟内失败率 >10%（样本≥10）→ critical 告警。"""
    admin = _login_admin(api)
    conv_id = uuid.uuid4().hex
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO conversations (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, admin["user_id"], now, now),
    )
    for i in range(10):
        api.conn.execute(
            "INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text, created_at) "
            "VALUES (?, ?, ?, ?, '测试输入', ?)",
            (uuid.uuid4().hex, conv_id, admin["user_id"],
             "failed" if i < 2 else "completed", now),
        )
    api.conn.commit()
    alerts = _alerts(api)
    hit = [a for a in alerts if a["code"] == "AGENT_RUN_FAILURE_RATE"]
    assert len(hit) == 1
    assert hit[0]["level"] == "critical"
    assert hit[0]["current"] == pytest.approx(0.2)
    assert hit[0]["threshold"] == 0.10
    assert hit[0]["since"]


def test_admin_alerts_recall_timeout(api):
    """10 分钟召回超时率 >10%：latency_ms 超线事件占比过阈 → warning。"""
    _login_admin(api)
    now = db_module.utc_now_iso()
    for i in range(10):
        api.conn.execute(
            "INSERT INTO analytics_events (user_id, event_name, props_json, created_at) "
            "VALUES (NULL, 'rag_retrieval_completed', ?, ?)",
            (json.dumps({"latency_ms": 5000 if i < 3 else 50}), now),
        )
    api.conn.commit()
    alerts = _alerts(api)
    hit = [a for a in alerts if a["code"] == "RAG_RECALL_TIMEOUT_RATE"]
    assert len(hit) == 1 and hit[0]["level"] == "warning"
    assert hit[0]["current"] == pytest.approx(0.3)


def test_admin_alerts_parse_failure(api):
    """单日 parse 任务失败率 >20%（样本≥5）→ warning 告警。"""
    admin = _login_admin(api)
    doc_id = uuid.uuid4().hex
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO rag_documents (id, title, file_type, source_type, source_name, version, "
        "license_status, status, created_by, created_at, updated_at) "
        "VALUES (?, '解析测试.pdf', 'pdf', 'other', '测试', 'v1', 'internal', 'failed', ?, ?, ?)",
        (doc_id, admin["user_id"], now, now),
    )
    for i in range(5):
        api.conn.execute(
            "INSERT INTO rag_jobs (id, document_id, stage, status, created_at) "
            "VALUES (?, ?, 'parse', ?, ?)",
            (uuid.uuid4().hex, doc_id, "failed" if i < 2 else "succeeded", now),
        )
    api.conn.commit()
    alerts = _alerts(api)
    hit = [a for a in alerts if a["code"] == "DOC_PARSE_FAILURE_RATE"]
    assert len(hit) == 1 and hit[0]["level"] == "warning"
    assert hit[0]["current"] == pytest.approx(0.4)
    assert hit[0]["threshold"] == 0.20


def test_admin_alerts_provider_decrypt_and_conn_failures(api):
    """API Key 解密失败（任意发生）+ 连接测试连续失败≥3 → 两条 critical。"""
    _login_admin(api)
    provider_id = uuid.uuid4().hex
    now = db_module.utc_now_iso()
    api.conn.execute(
        "INSERT INTO provider_configs (id, name, protocol, base_url, model, api_key_encrypted, "
        "role, enabled, timeout_seconds, extra_json, created_at, updated_at) "
        "VALUES (?, '讯飞星辰', 'chat_completions', 'https://api.example.com', 'spark-x', "
        "'!!!not-a-valid-ciphertext!!!', 'primary', 1, 30, '{}', ?, ?)",
        (provider_id, now, now),
    )
    for _ in range(3):
        api.conn.execute(
            "INSERT INTO audit_logs (id, actor_id, action, target_type, target_id, after_json, created_at) "
            "VALUES (?, NULL, 'provider.test', 'provider', ?, ?, ?)",
            (uuid.uuid4().hex, provider_id, json.dumps({"ok": False}), now),
        )
    api.conn.commit()
    alerts = _alerts(api)
    codes = {a["code"] for a in alerts}
    assert "API_KEY_DECRYPT_FAILURE" in codes
    assert "PROVIDER_CONN_FAILURE" in codes
    decrypt_alert = next(a for a in alerts if a["code"] == "API_KEY_DECRYPT_FAILURE")
    assert decrypt_alert["level"] == "critical" and decrypt_alert["current"] == 1
    conn_alert = next(a for a in alerts if a["code"] == "PROVIDER_CONN_FAILURE")
    assert conn_alert["current"] == 3 and "讯飞星辰" in conn_alert["message"]
