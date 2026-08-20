"""RAG 管理端与学生端问答 API 旅程测试（蓝图 §16：AC3/AC4/AC5/AC6）。

完整旅程：上传 md（multipart）→ 同步管线至 indexed → 送审 → 发布（student）
→ 已验证学生 /api/rag/query 命中且带引用；发布前学生查询拒答（AC4/AC6）；
乱码查询发布后仍拒答（AC6）。另覆盖：守卫（授权/来源/敏感信息/删除已发布）、
幂等、切片编辑后索引可搜、召回测试台诊断、评测五指标、来源台账风险标志。

注意（偏差说明）：auth 路由由并发代理 B1 负责、当前代码树尚未落地，因此本文件
直接在 DB 中创建已验证用户与 user_sessions 会话行（token/csrf 只存哈希），
用 cookie + x-csrf-token 头模拟登录态，与 deps.py 的校验路径完全一致。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bhzd_py.config import reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.security import hash_password, hash_token


@pytest.fixture()
def db_path(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("BHZD_UPLOAD_DIR", str(tmp_path / "uploads"))
    reset_config_cache()
    conn = connect(tmp_db_path)
    apply_migrations(conn)
    conn.execute("INSERT INTO rag_settings (id, updated_at) VALUES (1, ?)", (utc_now_iso(),))
    conn.commit()
    conn.close()
    yield tmp_db_path
    reset_config_cache()


@pytest.fixture()
def client(db_path):
    from bhzd_py.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def create_user(db_path, email: str, role: str, verified: bool = True) -> str:
    conn = connect(db_path)
    now = utc_now_iso()
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
        (user_id, email, email.split("@")[0], role, now if verified else None, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at) VALUES (?, ?, 'argon2id', ?)",
        (user_id, hash_password("Test1234!"), now),
    )
    conn.commit()
    conn.close()
    return user_id


def create_session(db_path, user_id: str) -> tuple[str, str]:
    """直接插入 user_sessions 行，返回 (会话令牌, CSRF 令牌)——替代尚未落地的登录 API。"""
    conn = connect(db_path)
    token, csrf = uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO user_sessions (id, user_id, token_hash, csrf_token_hash, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            user_id,
            hash_token(token),
            hash_token(csrf),
            now.isoformat(),
            (now + timedelta(hours=72)).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return token, csrf


@pytest.fixture()
def system_admin(db_path):
    return create_session(db_path, create_user(db_path, "rag-admin@test.local", "system_admin"))


@pytest.fixture()
def teacher(db_path):
    return create_session(db_path, create_user(db_path, "teacher@test.local", "teacher"))


@pytest.fixture()
def student(db_path):
    return create_session(db_path, create_user(db_path, "student@test.local", "student"))


def as_user(client: TestClient, session: tuple[str, str]) -> dict:
    """切换客户端登录态，返回带 CSRF 头的 headers。"""
    token, csrf = session
    client.cookies.set("bhzd_session", token)
    return {"x-csrf-token": csrf}


def test_upload_worker_retries_a_transient_sqlite_lock(db_path, monkeypatch):
    """A queued upload gets a bounded retry instead of waiting for a restart."""
    from bhzd_py.routers import rag_admin

    calls: list[str] = []
    delays: list[float] = []

    def flaky_run_pending(_conn, _config, *, document_id):
        calls.append(document_id)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"executed": 0, "failed": 0, "jobs": []}

    # The test exercises retry control flow only; no document row is needed
    # because auto-submit is disabled for this isolated queue-worker probe.
    monkeypatch.setattr(rag_admin.pipeline, "run_pending", flaky_run_pending)
    monkeypatch.setattr(rag_admin.time, "sleep", delays.append)
    rag_admin._run_upload_pipeline("queued-doc", db_path, False, "actor", {})

    assert calls == ["queued-doc", "queued-doc"]
    assert delays == [rag_admin._UPLOAD_PIPELINE_RETRY_DELAYS_SECONDS[0]]


def test_upload_worker_handles_a_lock_while_opening_its_connection(db_path, monkeypatch):
    """An exhausted connect-time lock must not mask itself with a close error."""
    from bhzd_py.routers import rag_admin

    attempts: list[str] = []
    delays: list[float] = []

    def locked_connect(_database_path):
        attempts.append("connect")
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(rag_admin, "connect", locked_connect)
    monkeypatch.setattr(rag_admin.time, "sleep", delays.append)
    rag_admin._run_upload_pipeline("queued-doc", db_path, False, "actor", {})

    assert attempts == ["connect"] * rag_admin._UPLOAD_PIPELINE_MAX_ATTEMPTS
    assert delays == list(rag_admin._UPLOAD_PIPELINE_RETRY_DELAYS_SECONDS)


SAMPLE_MD = """# 第一章 标注总则
车载唤醒词标注必须以原始音频为准，禁止凭上下文臆测。

# 第二章 边界要求
唤醒词边界误差必须控制在正负五十毫秒以内。
1. 先听完整段音频再落刀。
2. 边界落在能量最低点。
3. 拿不准的片段提交复核。
4. 每批次自查一遍边界。

# 第三章 质检
批次抽检中边界误差超差样本占比超过百分之五时整批返工。
"""


def upload_sample(client: TestClient, headers: dict, **overrides) -> dict:
    """上传一篇示例 md 资料，并返回处理完成后的详情快照。

    httpx 与 files 同传时，重复表单字段要用 dict + list 值（list-of-tuples
    会被当作原始内容流，服务端一个字段都收不到）。

    TestClient 会在请求结束前执行 BackgroundTasks；保留原始 202 响应在
    ``queued`` 字段，让调用方同时能断言异步入队契约和最终管线结果。
    """
    form: dict = {
        "title": "车载唤醒词标注指南",
        "source_type": "enterprise",
        "source_name": "合作企业车载语音项目组",
        "version": "v1.4",
        "license_status": "authorized",
        "visibility": "teacher",
        "data_types": ["audio"],
        "cap_ids": ["CAP-AUD-WAKE-COMMAND-001"],
    }
    for key, value in overrides.items():
        form[key] = [value] if key in ("data_types", "cap_ids") else value
    response = client.post(
        "/api/rag/documents",
        files={"file": ("唤醒词指南.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        data=form,
        headers=headers,
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    detail = client.get(f"/api/rag/documents/{queued['document']['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    return {
        "document": detail.json()["document"],
        "jobs": detail.json()["jobs"],
        "queued": queued,
    }


def _write_local_ragdata_package(root):
    """Create a minimal governed package to exercise the server-only import boundary."""
    materials = root / "materials"
    sources = root / "sources"
    materials.mkdir(parents=True)
    sources.mkdir()
    (sources / "SRC-ONE__table.md").write_text(
        "# 来源台账：表格来源\n"
        "| 字段 | 值 |\n| --- | --- |\n"
        "| **来源编码** | `SRC-ONE` |\n| **来源名称** | 表格来源 |\n"
        "| **发布方** | 测试发布方 |\n| **来源类型** | textbook |\n"
        "| **版本** | 2026 |\n| **授权状态** | approved |\n",
        encoding="utf-8",
    )
    (sources / "SRC-TBK-WANG-2020__knowledge-graph.md").write_text(
        "---\nsource_id: SRC-TBK-WANG-2020\ntitle: 知识图谱教材\nversion: 2020\n"
        "category: textbook\nissued_by: 测试出版社\nurl: https://example.test/kg\n"
        "status: approved\n---\n",
        encoding="utf-8",
    )
    (materials / "mat_one.md").write_text(
        "---\nid: MAT-ONE\ntitle: 第一份资料\nversion: v1\nsource: SRC-ONE\n"
        "source_type: textbook\nlicense_status: authorized\ndata_types: text\nvisibility: teacher\n"
        "---\n# 第一份资料\n用于验证表格来源台账。\n",
        encoding="utf-8",
    )
    (materials / "mat_tbk_020_kg_methodology_v1_0.md").write_text(
        "---\nid: MAT-KG\ntitle: 知识图谱资料\nversion: v1\nsource: SRC-TBK-WANG-2020\n"
        "source_type: textbook\nlicense_status: authorized\ndata_types: text\nvisibility: teacher\n"
        "---\n# 知识图谱资料\n用于验证重复来源编码规范化。\n",
        encoding="utf-8",
    )


def test_import_local_ragdata_is_admin_only_idempotent_and_site_wide(
    client, db_path, system_admin, student, tmp_path, monkeypatch
):
    """The package import preserves traceability and publishes completed materials."""
    from bhzd_py.routers import rag_admin

    package_root = tmp_path / "ragData"
    _write_local_ragdata_package(package_root)
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_ROOT", package_root)
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_MATERIALS", package_root / "materials")
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_SOURCES", package_root / "sources")

    response = client.post("/api/rag/import-local-ragdata", headers=as_user(client, student))
    assert response.status_code == 403

    response = client.post(
        "/api/rag/import-local-ragdata", headers=as_user(client, system_admin)
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["sources"] == {"total": 2, "created": 2, "skipped": 0, "failed": 0}
    assert payload["documents"] == {
        "total": 2,
        "imported": 2,
        "skipped": 0,
        "failed": 0,
        "queued": 2,
    }

    conn = connect(db_path)
    ledgers = conn.execute("SELECT source_code FROM source_ledgers ORDER BY source_code").fetchall()
    documents = conn.execute(
        "SELECT visibility, status, license_status, source_name, storage_path FROM rag_documents"
    ).fetchall()
    conn.close()
    assert [row["source_code"] for row in ledgers] == ["SRC-ONE", "SRC-TBK-WANGHAOFEN-2020"]
    assert len(documents) == 2
    assert all(row["visibility"] == "student" for row in documents)
    assert all(row["status"] == "published" for row in documents)
    assert all(row["license_status"] == "authorized" for row in documents)
    assert any(row["source_name"] == "知识图谱教材" for row in documents)
    assert all(row["storage_path"] and Path(row["storage_path"]).is_file() for row in documents)

    response = client.post(
        "/api/rag/import-local-ragdata", headers=as_user(client, system_admin)
    )
    assert response.status_code == 202, response.text
    assert response.json()["documents"]["skipped"] == 2


def test_import_local_ragdata_auto_publish_runs_after_pipeline(
    client, db_path, system_admin, tmp_path, monkeypatch
):
    """The local package may auto-publish only after durable parse/chunk/index succeeds."""
    from bhzd_py.routers import rag_admin

    package_root = tmp_path / "ragData"
    _write_local_ragdata_package(package_root)
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_ROOT", package_root)
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_MATERIALS", package_root / "materials")
    monkeypatch.setattr(rag_admin, "_LOCAL_RAGDATA_SOURCES", package_root / "sources")

    response = client.post(
        "/api/rag/import-local-ragdata",
        json={"auto_publish": True},
        headers=as_user(client, system_admin),
    )
    assert response.status_code == 202, response.text
    assert response.json()["auto_publish"] is True

    conn = connect(db_path)
    rows = conn.execute("SELECT status, visibility FROM rag_documents ORDER BY title").fetchall()
    conn.close()
    assert [(row["status"], row["visibility"]) for row in rows] == [
        ("published", "student"),
        ("published", "student"),
    ]


def test_batch_import_selected_files_queues_and_auto_publishes(
    client, db_path, system_admin
):
    """Browser-selected files use the normal pipeline and report bad siblings separately."""
    response = client.post(
        "/api/rag/documents/batch-import",
        files=[
            ("files", ("第一份.md", "# 第一份\n正文内容".encode("utf-8"), "text/markdown")),
            ("files", ("不支持.exe", b"binary", "application/octet-stream")),
        ],
        data={
            "source_type": "standard",
            "source_name": "BHZD 教学资料组",
            "version": "v1.0",
            "license_status": "authorized",
            "visibility": "student",
            "data_types": "text",
            "auto_publish": "true",
        },
        headers=as_user(client, system_admin),
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["files"] == {"total": 2, "imported": 1, "failed": 1, "queued": 1}
    assert payload["auto_publish"] is True
    assert payload["samples"]["failed"]["items"][0]["file"] == "不支持.exe"

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT title, status, visibility, storage_path FROM rag_documents"
    ).fetchall()
    conn.close()
    assert [(row["title"], row["status"], row["visibility"]) for row in rows] == [
        ("第一份", "published", "student")
    ]
    assert Path(rows[0]["storage_path"]).is_file()


def test_file_only_uploads_publish_with_pending_license(client, system_admin):
    """Default metadata keeps pending provenance while allowing student access."""

    headers = as_user(client, system_admin)
    single = client.post(
        "/api/rag/documents",
        files={"file": ("仅文件.md", "# 仅文件\n正文".encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    assert single.status_code == 202, single.text
    single_id = single.json()["document"]["id"]

    batch = client.post(
        "/api/rag/documents/batch-import",
        files=[("files", ("批量仅文件.md", "# 批量\n正文".encode("utf-8"), "text/markdown"))],
        headers=headers,
    )
    assert batch.status_code == 202, batch.text
    assert batch.json()["files"] == {"total": 1, "imported": 1, "failed": 0, "queued": 1}
    batch_id = batch.json()["samples"]["imported"]["items"][0]["id"]

    single_document = client.get(f"/api/rag/documents/{single_id}", headers=headers).json()["document"]
    batch_document = client.get(f"/api/rag/documents/{batch_id}", headers=headers).json()["document"]
    for document, title in ((single_document, "仅文件"), (batch_document, "批量仅文件")):
        assert document["title"] == title
        assert document["source_type"] == "other"
        assert document["source_name"] == "用户上传资料"
        assert document["version"] == "1.0"
        assert document["license_status"] == "pending"
        assert document["visibility"] == "student"
        assert document["data_types"] == ["text"]
        assert document["status"] == "published"
        assert document["published_at"]


def publish_sample(client: TestClient, headers: dict, doc_id: str) -> None:
    current = client.get(f"/api/rag/documents/{doc_id}", headers=headers)
    assert current.status_code == 200, current.text
    if current.json()["document"]["status"] == "published":
        return
    response = client.post(f"/api/rag/documents/{doc_id}/submit-review", headers=headers)
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/rag/documents/{doc_id}/publish", json={"scope": "student"}, headers=headers
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- 完整旅程（AC3/AC4/AC5/AC6）

def test_full_journey_upload_is_immediately_queryable(client, db_path, system_admin, student):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    doc = body["document"]
    assert doc["status"] == "published", body
    assert doc["visibility"] == "student"
    assert all(job["status"] == "succeeded" for job in body["jobs"])
    assert doc["chunk_count"] >= 3  # 三个章节至少三个切片

    # A completed upload is immediately queryable by students.
    student_headers = as_user(client, student)
    response = client.post(
        "/api/rag/query", json={"question": "唤醒词边界误差要求是多少"}, headers=student_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["refused"] is False
    assert response.json()["citations"]

    # AC3/AC5：学生查询命中且带引用，引用不含 chunk_id
    as_user(client, student)  # 切回学生会话（cookie 与 csrf 必须同属一个会话）
    response = client.post(
        "/api/rag/query", json={"question": "唤醒词边界误差要求是多少"}, headers=student_headers
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["refused"] is False
    assert answer["answer"]
    assert answer["citations"], "命中必须带引用（AC3/AC5）"
    citation = answer["citations"][0]
    assert citation["title"] == "车载唤醒词标注指南"
    assert citation["version"] == "v1.4"
    assert "chunk_id" not in citation  # PRD-06 §4.5：学生端不展示切片 ID
    assert answer["related_cap_ids"] == ["CAP-AUD-WAKE-COMMAND-001"]
    assert len(answer["steps"]) >= 1

    # AC6：乱码查询 → 拒答不编造
    response = client.post(
        "/api/rag/query", json={"question": "啊啊呃呃呜呜呀呀咦咦"}, headers=student_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["refused"] is True


def test_upload_publishes_without_batch_review(client, db_path, system_admin):
    """A completed upload reaches the student scope without a review round trip."""
    headers = as_user(client, system_admin)
    doc_id = upload_sample(client, headers)["document"]["id"]

    conn = connect(db_path)
    row = conn.execute("SELECT status, visibility FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    assert (row["status"], row["visibility"]) == ("published", "student")


def test_upload_returns_queued_snapshot_before_background_pipeline(client, db_path, system_admin):
    """202 必须先暴露可轮询任务，而不是等待解析、切片和嵌入完成。"""
    body = upload_sample(client, as_user(client, system_admin))
    queued = body["queued"]

    assert queued["document"]["status"] == "draft"
    assert all(job["status"] == "queued" for job in queued["jobs"])
    assert body["document"]["status"] == "published"


def test_pending_license_upload_is_queryable_by_students(client, db_path, system_admin, student):
    """Pending license status no longer prevents automatic student publication."""
    body = upload_sample(client, as_user(client, system_admin), license_status="pending")

    assert body["document"]["status"] == "published"
    assert body["document"]["visibility"] == "student"
    assert body["document"]["published_at"]

    conn = connect(db_path)
    review_count = conn.execute(
        "SELECT COUNT(*) AS n FROM review_records WHERE target_id = ?",
        (body["document"]["id"],),
    ).fetchone()["n"]
    conn.close()
    assert review_count == 0
    response = client.post(
        "/api/rag/query",
        json={"question": "唤醒词边界误差要求是多少"},
        headers=as_user(client, student),
    )
    assert response.status_code == 200, response.text
    assert response.json()["refused"] is False


def test_explicit_auto_submit_false_cannot_hide_uploaded_material(client, system_admin):
    """The compatibility field cannot override the site-wide upload policy."""
    body = upload_sample(
        client,
        as_user(client, system_admin),
        visibility="student",
        auto_submit="false",
    )

    assert body["document"]["status"] == "published"
    assert body["document"]["visibility"] == "student"


def test_student_auto_publish_still_honors_sensitive_content_guard(
    client, db_path, system_admin
):
    """Automatic publication must leave blocked sensitive material indexed for remediation."""
    headers = as_user(client, system_admin)
    sensitive_md = "# Roster\n身份证号 110101199003071234\n"
    response = client.post(
        "/api/rag/documents",
        files={"file": ("roster.md", sensitive_md.encode("utf-8"), "text/markdown")},
        data={
            "title": "Sensitive roster",
            "source_type": "other",
            "source_name": "Test organization",
            "version": "v1",
            "license_status": "authorized",
            "visibility": "student",
            "data_types": ["text"],
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    doc_id = response.json()["document"]["id"]

    detail = client.get(f"/api/rag/documents/{doc_id}", headers=headers).json()
    assert detail["document"]["status"] == "indexed"
    assert detail["sensitive_flags"]["block_publish"] is True

    conn = connect(db_path)
    audit_row = conn.execute(
        "SELECT action FROM audit_logs WHERE target_id = ? AND action = 'rag.auto_publish_document_blocked'",
        (doc_id,),
    ).fetchone()
    conn.close()
    assert audit_row is not None


def test_student_forced_published_only(client, db_path, system_admin, student):
    """学生即使显式传 published_only=false 也被强制为 true（蓝图 §6.4）。"""
    headers = as_user(client, system_admin)
    # A forbidden upload remains indexed for administrator remediation and is
    # therefore a stable unpublished fixture for this role-boundary assertion.
    upload_sample(client, headers, license_status="forbidden")
    student_headers = as_user(client, student)
    response = client.post(
        "/api/rag/query",
        json={"question": "唤醒词边界误差要求是多少", "published_only": False},
        headers=student_headers,
    )
    assert response.json()["refused"] is True


def test_management_answer_preview_forwards_the_retrieval_shape(client, system_admin, monkeypatch):
    """The console answer must use its vector/TopK/nucleus choices, not the default mode."""
    from bhzd_py.rag.retriever import RagAnswer
    from bhzd_py.routers import rag_query

    captured: dict[str, object] = {}

    def fake_answer(_conn, _config, question, **kwargs):
        captured["question"] = question
        captured.update(kwargs)
        return RagAnswer(answer="preview")

    monkeypatch.setattr(rag_query, "answer_question", fake_answer)
    headers = as_user(client, system_admin)
    response = client.post(
        "/api/rag/query",
        json={
            "question": "向量预览参数",
            "data_type": "text",
            "published_only": False,
            "document_ids": ["doc-preview"],
            "mode": "vector",
            "top_k": 7,
            "retrieval_top_p": 0.6,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert captured == {
        "question": "向量预览参数",
        "data_type": "text",
        "published_only": False,
        "document_ids": ["doc-preview"],
        "top_k": 7,
        "mode": "vector",
        "retrieval_top_p": 0.6,
    }

    # Nucleus filtering is defined only for pure cosine ranking, so a keyword
    # preview must fail before a response can be generated with misleading data.
    rejected = client.post(
        "/api/rag/query",
        json={"question": "关键词参数", "mode": "keyword", "retrieval_top_p": 0.6},
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unverified_student_can_query(client, db_path):
    """历史未验证账号也可访问 RAG；学生仍只检索已发布资料。"""
    user_id = create_user(db_path, "unverified@test.local", "student", verified=False)
    session = create_session(db_path, user_id)
    headers = as_user(client, session)
    response = client.post("/api/rag/query", json={"question": "你好"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["refused"] is True


# ---------------------------------------------------------------- 守卫

def test_upload_validation_and_role_guard(client, db_path, system_admin, student):
    headers = as_user(client, system_admin)
    # 文件是唯一必填项；空来源由系统补全，并保持待确认授权门禁。
    response = client.post(
        "/api/rag/documents",
        files={"file": ("a.md", "# x\n内容".encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    uploaded = response.json()["document"]
    assert uploaded["source_name"] == "用户上传资料"
    assert uploaded["license_status"] == "pending"
    assert uploaded["source_type"] == "other"
    assert uploaded["version"] == "1.0"
    assert uploaded["visibility"] == "student"
    assert uploaded["data_types"] == ["text"]

    # xlsx → PARSE_UNSUPPORTED（MVP 仅支持 pdf/docx/md/txt）
    response = client.post(
        "/api/rag/documents",
        files={"file": ("a.xlsx", b"PK\x03\x04 fake", "application/vnd.ms-excel")},
        data={
            "title": "表格", "source_type": "other", "source_name": "某单位",
            "version": "v1", "license_status": "authorized", "visibility": "teacher",
            "data_types": ["text"],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARSE_UNSUPPORTED"

    # 学生访问管理端 → 403（GET 与写操作都拦）
    student_headers = as_user(client, student)
    assert client.get("/api/rag/documents", headers=student_headers).status_code == 403
    response = client.post(
        "/api/rag/documents",
        files={"file": ("a.md", "# x\n内容".encode("utf-8"), "text/markdown")},
        data={
            "title": "越权", "source_type": "other", "source_name": "某单位",
            "version": "v1", "license_status": "authorized", "visibility": "teacher",
            "data_types": ["text"],
        },
        headers=student_headers,
    )
    assert response.status_code == 403


@pytest.mark.parametrize("non_admin_fixture", ("teacher",))
def test_teacher_cannot_manage_rag_documents(client, request, non_admin_fixture):
    """RAG metadata and uploads are system-admin-only, not teacher resource selection."""
    headers = as_user(client, request.getfixturevalue(non_admin_fixture))

    assert client.get("/api/rag/documents", headers=headers).status_code == 403
    response = client.post(
        "/api/rag/documents",
        files={"file": ("forbidden.md", b"# restricted", "text/markdown")},
        data={
            "title": "越权资料",
            "source_type": "other",
            "source_name": "某单位",
            "version": "v1",
            "license_status": "authorized",
            "visibility": "teacher",
            "data_types": ["text"],
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_publish_guards(client, db_path, system_admin):
    headers = as_user(client, system_admin)

    # 授权 forbidden → 403 LICENSE_BLOCKED（PRD-06 §4.2）
    forbidden = upload_sample(client, headers, title="禁用资料", license_status="forbidden")
    doc_id = forbidden["document"]["id"]
    client.post(f"/api/rag/documents/{doc_id}/submit-review", headers=headers)
    response = client.post(
        f"/api/rag/documents/{doc_id}/publish", json={"scope": "student"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LICENSE_BLOCKED"

    # 缺来源 → 送审 400 REVIEW_REQUIRED（先上传再 PATCH 清空来源）
    body = upload_sample(
        client, headers, title="无来源送审", license_status="forbidden"
    )
    doc_id = body["document"]["id"]
    response = client.patch(
        f"/api/rag/documents/{doc_id}", json={"source_name": ""}, headers=headers
    )
    assert response.status_code == 200
    response = client.post(f"/api/rag/documents/{doc_id}/submit-review", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REVIEW_REQUIRED"

    # 敏感信息（身份证）→ 发布 403 需脱敏（PRD-06 §4.3）
    sensitive_md = "# 名单\n联系人身份证号 110101199003071234，请妥善保管。\n"
    response = client.post(
        "/api/rag/documents",
        files={"file": ("名单.md", sensitive_md.encode("utf-8"), "text/markdown")},
        data={
            "title": "敏感资料", "source_type": "other", "source_name": "某单位",
            "version": "v1", "license_status": "authorized", "visibility": "teacher",
            "data_types": ["text"],
        },
        headers=headers,
    )
    doc_id = response.json()["document"]["id"]
    detail = client.get(f"/api/rag/documents/{doc_id}", headers=headers).json()
    assert detail["sensitive_flags"]["block_publish"] is True
    client.post(f"/api/rag/documents/{doc_id}/submit-review", headers=headers)
    response = client.post(
        f"/api/rag/documents/{doc_id}/publish", json={"scope": "student"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SENSITIVE_INFO_BLOCKED"

    # 未送审直接发布 → 409 REVIEW_REQUIRED
    body = upload_sample(client, headers, title="未送审资料", license_status="forbidden")
    response = client.post(
        f"/api/rag/documents/{body['document']['id']}/publish",
        json={"scope": "student"},
        headers=headers,
    )
    assert response.status_code == 409


def test_delete_published_conflict_and_delete_draft(client, db_path, system_admin):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    doc_id = body["document"]["id"]
    publish_sample(client, headers, doc_id)
    # 已发布只能归档不能物理删除（PRD-06 §5.2）
    response = client.delete(f"/api/rag/documents/{doc_id}", headers=headers)
    assert response.status_code == 409
    # 归档后可删除；切片随文档物理清除，审计留痕
    response = client.post(f"/api/rag/documents/{doc_id}/archive", headers=headers)
    assert response.status_code == 200
    assert response.json()["document"]["status"] == "archived"
    response = client.delete(f"/api/rag/documents/{doc_id}", headers=headers)
    assert response.status_code == 200
    assert client.get(f"/api/rag/documents/{doc_id}", headers=headers).status_code == 404


# ---------------------------------------------------------------- 幂等与重处理

def test_reprocess_idempotency_and_version_bump(client, db_path, system_admin):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    doc_id = body["document"]["id"]

    # 同参数重复触发 parse → 幂等复用任务（enqueued ids 完全一致）
    first = client.post(f"/api/rag/documents/{doc_id}/parse", headers=headers).json()
    second = client.post(f"/api/rag/documents/{doc_id}/parse", headers=headers).json()
    assert first["enqueued_job_ids"] == second["enqueued_job_ids"]

    # 参数变化 → process_version+1 且生成新任务（PRD-06 §5.2）
    response = client.post(
        f"/api/rag/documents/{doc_id}/chunk", json={"chunk_size": 120}, headers=headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["document"]["process_version"] == 2
    assert set(payload["enqueued_job_ids"]).isdisjoint(first["enqueued_job_ids"])
    assert payload["document"]["status"] == "indexed"  # 重切+重索引同步完成


# ---------------------------------------------------------------- 切片编辑

def test_chunk_patch_split_merge_keeps_index_searchable(client, db_path, system_admin, student):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    doc_id = body["document"]["id"]
    chunks = client.get(f"/api/rag/documents/{doc_id}/chunks", headers=headers).json()["items"]
    total_before = len(chunks)

    # PATCH 内容 → 自动重嵌入，新内容立即可被召回
    target = chunks[0]
    edited = "独特词阿尔法布拉：边界误差改为正负三十毫秒，复核流程不变。"
    response = client.patch(
        f"/api/rag/chunks/{target['id']}", json={"content": edited}, headers=headers
    )
    assert response.status_code == 200, response.text
    found = client.post(
        "/api/rag/search-test",
        json={"query": "独特词阿尔法布拉", "filters": {"published_only": False}, "top_k": 5},
        headers=headers,
    ).json()
    assert any("阿尔法布拉" in hit["content"] for hit in found["vector_results"])

    # 拆分 → 总数 +1，且索引连续
    response = client.post(f"/api/rag/chunks/{target['id']}/split", json={}, headers=headers)
    assert response.status_code == 200, response.text
    after_split = client.get(f"/api/rag/documents/{doc_id}/chunks", headers=headers).json()
    assert after_split["total"] == total_before + 1
    indices = [c["chunk_index"] for c in after_split["items"]]
    assert indices == list(range(after_split["total"]))

    # 合并拆出来的两个切片 → 总数还原，合并文本仍可搜
    first_two = after_split["items"][:2]
    response = client.post(
        "/api/rag/chunks/merge",
        json={"chunk_ids": [first_two[0]["id"], first_two[1]["id"]]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    after_merge = client.get(f"/api/rag/documents/{doc_id}/chunks", headers=headers).json()
    assert after_merge["total"] == total_before
    merged = client.post(
        "/api/rag/search-test",
        json={"query": "独特词阿尔法布拉", "filters": {"published_only": False}, "top_k": 5},
        headers=headers,
    ).json()
    assert any("阿尔法布拉" in hit["content"] for hit in merged["vector_results"])


# ---------------------------------------------------------------- 召回测试台与评测

def test_search_test_diagnostics_fields(client, db_path, system_admin):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    response = client.post(
        "/api/rag/search-test",
        json={"query": "边界误差要求", "filters": {"published_only": False}, "top_k": 3},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    diagnostics = payload["diagnostics"]
    for key in (
        "latency_ms",
        "embedding_model",
        "rerank_model",
        "retrieval_mode",
        "filters",
        "prompt_template_version",
    ):
        assert key in diagnostics, f"诊断信息缺少 {key}"
    assert diagnostics["embedding_model"]  # 本地哈希嵌入（离线）
    assert diagnostics["rerank_model"] is None  # 未启用重排
    assert payload["reranked_results"] == payload["vector_results"]
    assert payload["rerank_note"]

    # Each explicit console mode must survive validation and reach diagnostics.
    for mode in ("hybrid", "vector", "keyword"):
        mode_response = client.post(
            "/api/rag/search-test",
            json={
                "query": "边界误差要求",
                "mode": mode,
                "filters": {"published_only": False},
                "top_k": 3,
            },
            headers=headers,
        )
        assert mode_response.status_code == 200, mode_response.text
        mode_payload = mode_response.json()
        assert mode_payload["diagnostics"]["retrieval_mode"] == mode
        assert mode_payload["vector_results"]

    # save=true → 创建评测用例（写操作）
    response = client.post(
        "/api/rag/search-test",
        json={
            "query": "边界误差要求",
            "filters": {"published_only": True},
            "save": True,
            "must_hit_document_ids": [body["document"]["id"]],
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["saved_case_id"]


def test_search_test_persists_vector_retrieval_top_p_per_case(client, system_admin):
    """A vector-run nucleus setting is validated and saved with that case only."""

    headers = as_user(client, system_admin)
    saved = client.post(
        "/api/rag/search-test",
        json={
            "query": "仅验证单次向量召回参数",
            "mode": "vector",
            "retrieval_top_p": 0.6,
            "filters": {"published_only": False},
            "save": True,
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    case_id = saved.json()["saved_case_id"]
    cases = client.get("/api/rag/eval-cases", headers=headers)
    assert cases.status_code == 200, cases.text
    case = next(item for item in cases.json()["items"] if item["id"] == case_id)
    assert case["filters"]["mode"] == "vector"
    assert case["filters"]["retrieval_top_p"] == 0.6

    for invalid_value in (0, 1.01):
        invalid = client.post(
            "/api/rag/search-test",
            json={
                "query": "参数范围验证",
                "mode": "vector",
                "retrieval_top_p": invalid_value,
            },
            headers=headers,
        )
        assert invalid.status_code == 422

    rejected_for_hybrid = client.post(
        "/api/rag/search-test",
        json={
            "query": "混合模式不接受向量 nucleus",
            "mode": "hybrid",
            "retrieval_top_p": 0.6,
        },
        headers=headers,
    )
    assert rejected_for_hybrid.status_code == 422


def test_eval_run_replays_vector_retrieval_top_p_and_discards_invalid_snapshots(
    client, system_admin, monkeypatch
):
    """Saved console tuning affects its run only; malformed legacy values fall back to TopK."""

    from bhzd_py.rag.retriever import RagAnswer, RetrievalResult
    from bhzd_py.routers import rag_admin

    headers = as_user(client, system_admin)
    saved = client.post(
        "/api/rag/search-test",
        json={
            "query": "有效参数重放",
            "mode": "vector",
            "retrieval_top_p": 0.6,
            "filters": {"published_only": False},
            "save": True,
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    valid_case_id = saved.json()["saved_case_id"]
    invalid = client.post(
        "/api/rag/eval-cases",
        json={
            "question": "无效参数回退",
            "filters": {"published_only": False, "mode": "vector", "retrieval_top_p": 0},
        },
        headers=headers,
    )
    assert invalid.status_code == 201, invalid.text
    invalid_case_id = invalid.json()["case"]["id"]

    recalled_top_p: dict[str, float | None] = {}
    answered_top_p: dict[str, float | None] = {}

    def fake_retrieve(_conn, _config, question, filters, top_k=None):
        recalled_top_p[question] = filters.retrieval_top_p
        assert top_k is None
        return RetrievalResult()

    def fake_answer(_conn, _config, question, **kwargs):
        answered_top_p[question] = kwargs["retrieval_top_p"]
        return RagAnswer(answer="", refused=True)

    monkeypatch.setattr(rag_admin, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag_admin, "answer_question", fake_answer)
    replayed = client.post(
        "/api/rag/eval-runs",
        json={"case_ids": [valid_case_id, invalid_case_id]},
        headers=headers,
    )
    assert replayed.status_code == 201, replayed.text
    assert recalled_top_p == {"有效参数重放": 0.6, "无效参数回退": None}
    assert answered_top_p == recalled_top_p


def test_eval_sets_group_cases_runs_and_preserve_history_after_deletion(
    client, db_path, system_admin
):
    """Deleting a named group only detaches its cases and completed-run records."""

    headers = as_user(client, system_admin)
    document = upload_sample(client, headers)["document"]
    publish_sample(client, headers, document["id"])

    first_response = client.post(
        "/api/rag/eval-sets",
        json={"name": "唤醒词回归", "description": "初始说明"},
        headers=headers,
    )
    assert first_response.status_code == 201, first_response.text
    first_set = first_response.json()["set"]
    second_response = client.post(
        "/api/rag/test-sets",
        json={"name": "其他回归"},
        headers=headers,
    )
    assert second_response.status_code == 201, second_response.text
    second_set = second_response.json()["set"]

    renamed = client.patch(
        f"/api/rag/eval-sets/{first_set['id']}",
        json={"name": "唤醒词已命名回归", "description": "更新说明"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["set"]["name"] == "唤醒词已命名回归"

    first_case_response = client.post(
        "/api/rag/eval-cases",
        json={
            "question": "唤醒词边界误差要求是多少",
            "must_hit_document_ids": [document["id"]],
            "filters": {"published_only": True},
            # The compatibility field still attaches the case to the same set.
            "test_set_id": first_set["id"],
        },
        headers=headers,
    )
    assert first_case_response.status_code == 201, first_case_response.text
    first_case = first_case_response.json()["case"]
    assert first_case["eval_set_id"] == first_set["id"]
    assert first_case["test_set_id"] == first_set["id"]

    second_case_response = client.post(
        "/api/rag/eval-cases",
        json={"question": "另一组的拒答用例", "eval_set_id": second_set["id"]},
        headers=headers,
    )
    assert second_case_response.status_code == 201, second_case_response.text
    second_case = second_case_response.json()["case"]

    listed_sets = client.get("/api/rag/eval-sets", headers=headers)
    assert listed_sets.status_code == 200
    listed_by_id = {item["id"]: item for item in listed_sets.json()["items"]}
    assert listed_by_id[first_set["id"]]["case_count"] == 1
    assert listed_by_id[second_set["id"]]["case_count"] == 1

    filtered_cases = client.get(
        "/api/rag/eval-cases", params={"eval_set_id": first_set["id"]}, headers=headers
    )
    assert filtered_cases.status_code == 200, filtered_cases.text
    assert [item["id"] for item in filtered_cases.json()["items"]] == [first_case["id"]]

    run_response = client.post(
        "/api/rag/eval-runs", json={"eval_set_id": first_set["id"]}, headers=headers
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["eval_set_id"] == first_set["id"]
    assert run["metrics"]["case_count"] == 1
    assert [item["case_id"] for item in run["case_results"]] == [first_case["id"]]

    deleted = client.delete(f"/api/rag/eval-sets/{first_set['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "id": first_set["id"]}

    all_cases = client.get("/api/rag/eval-cases", headers=headers).json()["items"]
    detached = {item["id"]: item for item in all_cases}
    assert detached[first_case["id"]]["eval_set_id"] is None
    assert detached[second_case["id"]]["eval_set_id"] == second_set["id"]
    run_detail = client.get(f"/api/rag/eval-runs/{run['id']}", headers=headers)
    assert run_detail.status_code == 200, run_detail.text
    assert run_detail.json()["eval_set_id"] is None


def test_eval_run_metrics_keys(client, db_path, system_admin):
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    doc_id = body["document"]["id"]
    publish_sample(client, headers, doc_id)

    # 命中用例（published_only=true 需要已发布）+ 拒答用例（must_hit 为空）
    hit_case = client.post(
        "/api/rag/eval-cases",
        json={
            "question": "唤醒词边界误差要求是多少",
            "must_hit_document_ids": [doc_id],
            "filters": {"published_only": True},
        },
        headers=headers,
    ).json()["case"]
    refuse_case = client.post(
        "/api/rag/eval-cases",
        json={"question": "啊啊呃呃呜呜呀呀咦咦", "filters": {"published_only": True}},
        headers=headers,
    ).json()["case"]

    response = client.post(
        "/api/rag/eval-runs", json={"case_ids": [hit_case["id"], refuse_case["id"]]}, headers=headers
    )
    assert response.status_code == 201, response.text
    metrics = response.json()["metrics"]
    for key in ("recall_at_k", "citation_accuracy", "refusal_accuracy", "answer_faithfulness", "latency_ms_avg"):
        assert key in metrics, f"评测指标缺少 {key}"
    assert metrics["recall_at_k"] == 1.0
    assert metrics["refusal_accuracy"] == 1.0
    assert metrics["citation_accuracy"] == 1.0

    # GET 评测运行详情
    run_id = response.json()["id"]
    detail = client.get(f"/api/rag/eval-runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["metrics"]["recall_at_k"] == 1.0
    assert len(detail.json()["case_results"]) == 2


def test_eval_case_edit_delete_validate_documents_and_audit(client, db_path, system_admin):
    """Evaluation cases remain editable while completed run snapshots are independent rows."""

    headers = as_user(client, system_admin)
    document = upload_sample(client, headers)["document"]
    created = client.post(
        "/api/rag/eval-cases",
        json={
            "question": "初始问题",
            "must_hit_document_ids": [document["id"]],
            # Legacy clients may still submit the retired keys; the API must
            # accept the case while keeping those keys out of its snapshot.
            "filters": {
                "published_only": True,
                "scenario_id": "SCN-LEGACY",
                "scenario_ids": ["SCN-LEGACY"],
            },
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case"]["id"]
    assert "scenario_id" not in created.json()["case"]["filters"]
    assert "scenario_ids" not in created.json()["case"]["filters"]

    patched = client.patch(
        f"/api/rag/eval-cases/{case_id}",
        json={
            "question": "更新后的问题",
            "expected_answer": "正确答案",
            "must_hit_document_ids": [document["id"], document["id"]],
            "filters": {"published_only": True, "scenario_id": "SCN-STALE"},
        },
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    payload = patched.json()["case"]
    assert payload["question"] == "更新后的问题"
    assert payload["expected_answer"] == "正确答案"
    assert payload["must_hit_document_ids"] == [document["id"]]
    assert "scenario_id" not in payload["filters"]

    invalid = client.patch(
        f"/api/rag/eval-cases/{case_id}",
        json={"must_hit_document_ids": ["missing-document"]},
        headers=headers,
    )
    assert invalid.status_code == 422

    deleted = client.delete(f"/api/rag/eval-cases/{case_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert client.delete(f"/api/rag/eval-cases/{case_id}", headers=headers).status_code == 404

    conn = connect(db_path)
    actions = [
        row["action"]
        for row in conn.execute(
            "SELECT action FROM audit_logs WHERE target_type='eval_case' AND target_id=? ORDER BY created_at",
            (case_id,),
        )
    ]
    conn.close()
    assert "rag.update_eval_case" in actions
    assert "rag.delete_eval_case" in actions


# ---------------------------------------------------------------- 来源台账

def test_source_ledgers_crud_and_risk_flags(client, db_path, system_admin):
    headers = as_user(client, system_admin)
    response = client.post(
        "/api/source-ledgers",
        json={
            "source_code": "LEDGER-001",
            "name": "车载语音数据授权",
            "publisher": "合作企业",
            "authorization_status": "pending",
            "valid_to": "2020-01-01",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    ledger = response.json()["ledger"]
    assert ledger["risk_unauthorized"] is True  # 未批准
    assert ledger["risk_expired"] is True  # 已过期
    assert ledger["risk_no_documents"] is True  # 无关联资料

    # 重复编号 → 409
    response = client.post(
        "/api/source-ledgers",
        json={"source_code": "LEDGER-001", "name": "重复"},
        headers=headers,
    )
    assert response.status_code == 409

    # PATCH 批准授权 → 风险标志翻转；PATCH 写审计
    response = client.patch(
        f"/api/source-ledgers/{ledger['id']}",
        json={"authorization_status": "approved", "valid_to": "2099-12-31"},
        headers=headers,
    )
    assert response.status_code == 200
    updated = response.json()["ledger"]
    assert updated["risk_unauthorized"] is False
    assert updated["risk_expired"] is False

    listing = client.get("/api/source-ledgers", headers=headers).json()
    assert listing["total"] == 1

    conn = connect(db_path)
    audit_count = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_logs WHERE target_type = 'source_ledger'"
    ).fetchone()["n"]
    conn.close()
    assert audit_count >= 2  # create + patch 均已审计（NF8）
