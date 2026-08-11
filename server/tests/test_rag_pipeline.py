"""RAG 解析器/切片器/管线测试（蓝图 §16：上传→发布→召回的管线段）。

覆盖：四种格式解析（pdf 用 pypdf 合成、docx 用 python-docx 合成）、
PARSE_UNSUPPORTED / PARSE_EMPTY_TEXT 错误码、切片大小/重叠/标题继承、
管线状态机（draft→…→indexed）、幂等（同参数复用任务、参数变化新版本）、
失败重试（只从失败阶段继续）、敏感信息扫描（身份证命中阻止发布）。
全部离线运行（本地哈希嵌入）。
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.rag import pipeline
from bhzd_py.rag.chunker import chunk_blocks
from bhzd_py.rag.errors import PARSE_EMPTY_TEXT, PARSE_UNSUPPORTED, RAGError
from bhzd_py.rag.parsers import Block, parse_document
from bhzd_py.security import hash_password


# ---------------------------------------------------------------- 夹具与工具

@pytest.fixture()
def db_path(tmp_db_path, tmp_path, monkeypatch):
    """临时库 + 临时上传目录（复用 conftest 的 tmp_db_path，绝不污染仓库 var/）。"""
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
def uploader_id(db_path):
    """管线测试需要一个存在的上传人（rag_documents.created_by 外键）。"""
    conn = connect(db_path)
    now = utc_now_iso()
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at)"
        " VALUES (?, ?, ?, 'teacher', 'active', ?, ?, ?)",
        (user_id, "pipe-teacher@test.local", "管线教师", now, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at)"
        " VALUES (?, ?, 'argon2id', ?)",
        (user_id, hash_password("Test1234!"), now),
    )
    conn.commit()
    conn.close()
    return user_id


def make_pdf_bytes(pages_text: list[str]) -> bytes:
    """用 pypdf 合成带文本的 PDF（无第三方依赖，离线可重复）。"""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = writer._add_object(font)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_docx_bytes(sections: list[tuple[str, str]]) -> bytes:
    """用 python-docx 合成带标题层级的 Word 文档。"""
    import docx

    document = docx.Document()
    for heading, body in sections:
        document.add_heading(heading, level=1)
        document.add_paragraph(body)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def create_document(db_path, uploader_id, file_bytes: bytes, filename: str, file_type: str) -> str:
    """直接把文件落盘并插入 draft 文档行，返回 doc_id（绕开 API 的管线级测试）。"""
    config = get_config()
    doc_id = uuid.uuid4().hex
    doc_dir = Path(config.resolved_upload_dir) / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / filename).write_bytes(file_bytes)
    conn = connect(db_path)
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO rag_documents (id, title, file_type, source_type, source_name, version,
          license_status, visibility, status, storage_path, file_hash, process_version,
          created_by, created_at, updated_at)
        VALUES (?, ?, ?, 'standard', '测试来源', 'v1.0', 'authorized', 'teacher', 'draft',
          ?, ?, 1, ?, ?, ?)
        """,
        (
            doc_id,
            filename,
            file_type,
            str(doc_dir / filename),
            hashlib.sha256(file_bytes).hexdigest(),
            uploader_id,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return doc_id


def _stage_params(chunk_size: int = 500, chunk_overlap: int = 80, title_inherit: bool = True) -> dict:
    return {
        "parse": {},
        "chunk": {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap, "title_inherit": title_inherit},
        "index": {},
    }


def _doc_row(db_path, doc_id) -> sqlite3.Row:
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return row


def _job_rows(db_path, doc_id) -> list[sqlite3.Row]:
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT * FROM rag_jobs WHERE document_id = ? ORDER BY created_at, rowid", (doc_id,)
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------- 解析器

def test_parse_markdown_splits_on_headings():
    md = "# 第一章 总则\n标注员须持证上岗。\n\n## 第二章 质检\n一级质检通过率不得低于 95%。\n"
    doc = parse_document(md.encode("utf-8"), "md")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].section_title == "第一章 总则"
    assert "持证上岗" in doc.blocks[0].text
    assert doc.blocks[1].section_title == "第二章 质检"
    assert doc.blocks[0].page is None  # markdown 无页码，引用展示章节标题


def test_parse_markdown_omits_governed_front_matter():
    """Package metadata must not become a student-visible retrieval chunk."""
    md = "---\nid: MAT-ONE\nvisibility: student\n---\n# 正文标题\n只应索引正文。\n"
    doc = parse_document(md.encode("utf-8"), "md")
    assert doc.blocks[0].section_title == "正文标题"
    assert doc.blocks[0].text == "只应索引正文。"


def test_parse_pdf_preserves_page_numbers():
    pdf = make_pdf_bytes(["Annotation guideline page one", "Second page of rules"])
    doc = parse_document(pdf, "pdf")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].page == 1 and "page one" in doc.blocks[0].text
    assert doc.blocks[1].page == 2 and "Second page" in doc.blocks[1].text


def test_parse_docx_heading_becomes_section_title():
    data = make_docx_bytes([("第一章 标注总则", "所有标注须双人复核。"), ("第二章 交付", "交付前须通过质检。")])
    doc = parse_document(data, "docx")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].section_title == "第一章 标注总则"
    assert "双人复核" in doc.blocks[0].text


def test_parse_unsupported_xlsx_raises():
    with pytest.raises(RAGError) as excinfo:
        parse_document(b"PK\x03\x04 fake xlsx", "xlsx")
    assert excinfo.value.code == PARSE_UNSUPPORTED


def test_parse_empty_text_raises():
    # 空白页 PDF：能打开但提取不到文本 → 扫描件语义（PARSE_EMPTY_TEXT）
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(RAGError) as excinfo:
        parse_document(buffer.getvalue(), "pdf")
    assert excinfo.value.code == PARSE_EMPTY_TEXT


# ---------------------------------------------------------------- 切片器

def test_chunker_splits_long_text_with_sentence_preference():
    # 构造超过 chunk_size 的单块文本，验证滑动窗口与句读下刀
    sentence = "标注规范要求每条语音切片不小于二百毫秒。"
    block = Block(text=sentence * 30, page=1, section_title="时长规则")
    drafts = chunk_blocks([block], chunk_size=200, chunk_overlap=40, title_inherit=True)
    assert len(drafts) > 1
    for draft in drafts:
        assert draft.section_title == "时长规则"
        assert draft.page_start == 1 and draft.page_end == 1
        assert draft.token_count == len(draft.content) // 2  # 混合 CJK 近似
        # 标题继承前缀计入内容，放宽少量余量
        assert len(draft.content) <= 200 + len("【时长规则】\n") + 40
    # 内容完整性：去掉继承前缀拼接应覆盖原文（允许重叠重复）
    joined = "".join(d.content.replace("【时长规则】\n", "") for d in drafts)
    assert "二百毫秒" in joined


def test_chunker_title_inherit_can_be_disabled():
    blocks = [Block(text="正文内容。", page=None, section_title="章节名")]
    with_title = chunk_blocks(blocks, chunk_size=500, chunk_overlap=80, title_inherit=True)
    without_title = chunk_blocks(blocks, chunk_size=500, chunk_overlap=80, title_inherit=False)
    assert with_title[0].content.startswith("【章节名】")
    assert not without_title[0].content.startswith("【章节名】")


def test_chunker_respects_section_boundaries():
    blocks = [
        Block(text="第一段内容。", page=None, section_title="甲"),
        Block(text="第二段内容。", page=None, section_title="乙"),
    ]
    drafts = chunk_blocks(blocks, chunk_size=500, chunk_overlap=80, title_inherit=False)
    # 章节是语义边界：两个小段不合并为一个切片
    assert len(drafts) == 2
    assert drafts[0].section_title == "甲" and drafts[1].section_title == "乙"


# ---------------------------------------------------------------- 管线状态机

def test_pipeline_full_run_and_idempotent_enqueue(db_path, uploader_id):
    md = "# 总则\n客服语音标注须遵循双人复核制度，质检通过率不低于百分之九十五。\n"
    doc_id = create_document(db_path, uploader_id, md.encode("utf-8"), "规范.md", "md")
    config = get_config()
    conn = connect(db_path)

    job_ids = pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
    assert len(job_ids) == 3
    summary = pipeline.run_pending(conn, config, document_id=doc_id)
    assert summary["failed"] == 0
    assert _doc_row(db_path, doc_id)["status"] == "indexed"
    chunk_count = conn.execute(
        "SELECT COUNT(*) AS n FROM rag_chunks WHERE document_id = ?", (doc_id,)
    ).fetchone()["n"]
    assert chunk_count >= 1

    # 幂等：同文档同版本同参数再次入队 → 复用既有任务，不新增
    again = pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
    assert again == job_ids
    assert len(_job_rows(db_path, doc_id)) == 3

    # 参数变化 → 新处理版本 → 生成新任务（PRD-06 §5.2）
    conn.execute("UPDATE rag_documents SET process_version = 2 WHERE id = ?", (doc_id,))
    conn.commit()
    new_ids = pipeline.enqueue(
        conn, doc_id, ["chunk", "index"], _stage_params(chunk_size=120), 2
    )
    assert set(new_ids).isdisjoint(job_ids)
    conn.close()


def test_pipeline_defers_downstream_stage_until_predecessor_is_durable(db_path, uploader_id):
    """Concurrent workers must leave dependent rows queued, not fail the document."""
    doc_id = create_document(
        db_path,
        uploader_id,
        b"# Queue ordering\nA downstream stage waits for committed parse output.\n",
        "queue-order.md",
        "md",
    )
    conn = connect(db_path)
    try:
        pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
        jobs = {row["stage"]: row for row in _job_rows(db_path, doc_id)}

        # This simulates a second worker seeing chunk before the first worker
        # has committed parse.  The row stays available for the first worker.
        assert pipeline._run_job(conn, get_config(), jobs["chunk"]) is None
        assert conn.execute(
            "SELECT status FROM rag_jobs WHERE id = ?", (jobs["chunk"]["id"],)
        ).fetchone()["status"] == "queued"

        summary = pipeline.run_pending(conn, get_config(), document_id=doc_id)
        assert summary["failed"] == 0
        assert _doc_row(db_path, doc_id)["status"] == "indexed"
    finally:
        conn.close()


def test_pipeline_requeues_a_job_interrupted_after_claim(db_path, uploader_id):
    """A process crash after the CAS claim remains recoverable on next startup."""
    doc_id = create_document(
        db_path,
        uploader_id,
        b"# Recover queue\nThe durable job must resume after an interrupted worker.\n",
        "recover-queue.md",
        "md",
    )
    conn = connect(db_path)
    try:
        job_ids = pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
        conn.execute(
            "UPDATE rag_jobs SET status = 'running', started_at = ? WHERE id = ?",
            (utc_now_iso(), job_ids[0]),
        )
        conn.commit()

        assert pipeline.recover_interrupted_jobs(conn) == 1
        assert conn.execute(
            "SELECT status FROM rag_jobs WHERE id = ?", (job_ids[0],)
        ).fetchone()["status"] == "queued"

        summary = pipeline.run_pending(conn, get_config(), document_id=doc_id)
        assert summary["failed"] == 0
        assert _doc_row(db_path, doc_id)["status"] == "indexed"
    finally:
        conn.close()


def test_pipeline_parse_failure_then_retry_from_failed_stage(db_path, uploader_id):
    doc_id = create_document(db_path, uploader_id, b"not a real pdf", "broken.pdf", "pdf")
    config = get_config()
    conn = connect(db_path)
    job_ids = pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
    summary = pipeline.run_pending(conn, config, document_id=doc_id)
    assert summary["failed"] == 1
    doc = _doc_row(db_path, doc_id)
    assert doc["status"] == "failed" and doc["error_code"] == PARSE_EMPTY_TEXT
    jobs = {j["stage"]: j for j in _job_rows(db_path, doc_id)}
    assert jobs["parse"]["status"] == "failed"
    # 下游排队任务被自动取消，且不会误执行
    assert jobs["chunk"]["status"] == "cancelled"
    assert jobs["index"]["status"] == "cancelled"

    # 修复文件后重试：只从失败阶段继续，最终跑到 indexed
    storage = Path(doc["storage_path"])
    storage.write_bytes(make_pdf_bytes(["Recovered guideline text for retry"]))
    retry_summary = pipeline.retry_job(conn, config, job_ids[0])
    assert retry_summary["failed"] == 0
    assert _doc_row(db_path, doc_id)["status"] == "indexed"
    jobs = {j["stage"]: j for j in _job_rows(db_path, doc_id)}
    assert all(j["status"] == "succeeded" for j in jobs.values())
    assert jobs["parse"]["attempt"] == 2  # 重试计入尝试次数
    conn.close()


def test_pipeline_parse_stage_records_sensitive_flags(db_path, uploader_id):
    md = "# 名单\n联系人张三，手机号 13800138000，身份证号 110101199003071234，邮箱 zhang@example.com。\n"
    doc_id = create_document(db_path, uploader_id, md.encode("utf-8"), "名单.md", "md")
    conn = connect(db_path)
    pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
    pipeline.run_pending(conn, get_config(), document_id=doc_id)
    parse_job = conn.execute(
        "SELECT params_json FROM rag_jobs WHERE document_id = ? AND stage = 'parse'", (doc_id,)
    ).fetchone()
    flags = json.loads(parse_job["params_json"])["sensitive_flags"]
    assert flags["phone"] == 1
    assert flags["id_card"] == 1
    assert flags["email"] == 1
    assert flags["block_publish"] is True  # 身份证命中 → 阻止发布（PRD-06 §4.3）
    conn.close()


def test_retry_non_failed_job_rejected(db_path, uploader_id):
    md = "# 总则\n内容。\n"
    doc_id = create_document(db_path, uploader_id, md.encode("utf-8"), "a.md", "md")
    conn = connect(db_path)
    job_ids = pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), _stage_params(), 1)
    pipeline.run_pending(conn, get_config(), document_id=doc_id)
    with pytest.raises(RAGError) as excinfo:
        pipeline.retry_job(conn, get_config(), job_ids[0])
    assert excinfo.value.code == "JOB_NOT_RETRYABLE"
    conn.close()
