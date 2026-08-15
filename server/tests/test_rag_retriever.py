"""RAG 召回与问答契约测试（蓝图 §16：AC4 未发布不可召回 / AC6 无依据拒答）。

全部在 DB 层构造数据（直接插入已发布/未发布文档与切片嵌入），离线运行。
覆盖：学生端硬过滤、阈值拒答、多版本取最新、
模板答案与 composer 注入、引用上限、拒答策略 generic_advice。
"""

from __future__ import annotations

import json
import struct
import uuid

import pytest

from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.rag.local_embed import EMBEDDING_MODEL, embed_text
from bhzd_py.rag import retriever as retriever_module
from bhzd_py.rag.retriever import (
    REFUSAL_MESSAGE,
    RagFilters,
    answer_question,
    retrieve,
)
from bhzd_py.rag.vectorstore import search as vector_search
from bhzd_py.security import hash_password


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
def uploader_id(db_path):
    conn = connect(db_path)
    now = utc_now_iso()
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at)"
        " VALUES (?, ?, ?, 'teacher', 'active', ?, ?, ?)",
        (user_id, "retriever-teacher@test.local", "召回教师", now, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at) VALUES (?, ?, 'argon2id', ?)",
        (user_id, hash_password("Test1234!"), now),
    )
    conn.commit()
    conn.close()
    return user_id


def insert_doc(
    db_path,
    uploader_id,
    *,
    title: str,
    status: str = "published",
    visibility: str = "student",
    license_status: str = "authorized",
    cap_ids: list[str] | None = None,
    data_types: list[str] | None = None,
    version: str = "v1.0",
    published_at: str | None = None,
    expires_at: str | None = None,
) -> str:
    """插入文档行；published 默认补 published_at（多版本测试依赖它排新旧）。"""
    conn = connect(db_path)
    now = utc_now_iso()
    doc_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO rag_documents (id, title, file_type, source_type, source_name, version,
          license_status, data_types_json, cap_ids_json, visibility, status,
          process_version, created_by, created_at, updated_at, published_at, expires_at)
        VALUES (?, ?, 'md', 'standard', '测试来源', ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            title,
            version,
            license_status,
            json.dumps(data_types or [], ensure_ascii=False),
            json.dumps(cap_ids or [], ensure_ascii=False),
            visibility,
            status,
            uploader_id,
            now,
            now,
            published_at if published_at is not None else (now if status == "published" else None),
            expires_at,
        ),
    )
    conn.commit()
    conn.close()
    return doc_id


def insert_chunk(
    db_path,
    doc_id: str,
    content: str,
    index: int = 0,
    section: str | None = None,
    *,
    embedding: bytes | None = None,
    embedding_model: str = EMBEDDING_MODEL,
) -> str:
    """Insert a chunk with a controllable vector for model-compatibility tests."""
    conn = connect(db_path)
    chunk_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO rag_chunks (id, document_id, chunk_index, content, keywords_json,
          section_title, token_count, embedding, embedding_model, status, process_version)
        VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?, 'active', 1)
        """,
        (
            chunk_id,
            doc_id,
            index,
            content,
            section,
            len(content) // 2,
            embedding if embedding is not None else embed_text(content),
            embedding_model,
        ),
    )
    conn.commit()
    conn.close()
    return chunk_id


def _retrieve(db_path, query, **filter_kwargs):
    conn = connect(db_path)
    result = retrieve(conn, get_config(), query, RagFilters(**filter_kwargs))
    conn.close()
    return result


def _answer(db_path, question, **kwargs):
    conn = connect(db_path)
    result = answer_question(conn, get_config(), question, **kwargs)
    conn.close()
    return result


def test_query_rewrite_is_opt_in_and_bridges_async_provider(db_path, uploader_id, monkeypatch):
    """短查询开启开关后才调用 provider，并把改写文本送入同步召回入口。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET query_rewrite_enabled = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    provider_prompts: list[str] = []

    async def fake_complete(messages, *, role="primary"):
        assert role == "primary"
        provider_prompts.append(messages[0]["content"])
        return {"text": "语音情感标注 标签判定 正负例标准"}

    monkeypatch.setattr("bhzd_py.agent.providers.complete", fake_complete)
    embedded_queries: list[str] = []

    def fake_embed(db, texts):
        embedded_queries.extend(texts)
        return [embed_text(CS_CONTENT)], EMBEDDING_MODEL

    monkeypatch.setattr(retriever_module, "embed_chunks", fake_embed)
    result = _retrieve(db_path, "怎么标注")

    assert result.hits and result.hits[0].document_id == doc_id
    assert provider_prompts and "怎么标注" in provider_prompts[0]
    assert embedded_queries == ["语音情感标注 标签判定 正负例标准"]


def test_query_rewrite_failure_falls_back_to_original_query(db_path, uploader_id, monkeypatch):
    """供应商不可用时改写增强不得阻断原有离线召回。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET query_rewrite_enabled = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    async def broken_complete(_messages, *, role="primary"):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("bhzd_py.agent.providers.complete", broken_complete)
    embedded_queries: list[str] = []

    def fake_embed(db, texts):
        embedded_queries.extend(texts)
        return [embed_text(CS_CONTENT)], EMBEDDING_MODEL

    monkeypatch.setattr(retriever_module, "embed_chunks", fake_embed)
    result = _retrieve(db_path, "怎么标注")

    assert result.hits and result.hits[0].document_id == doc_id
    assert embedded_queries == ["怎么标注"]


def test_query_rewrite_disabled_skips_provider(db_path, uploader_id, monkeypatch):
    """默认关闭时保持完全离线行为，连 provider 模块都不触发。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)
    monkeypatch.setattr(
        retriever_module,
        "_rewrite_query",
        lambda *_args, **_kwargs: pytest.fail("query rewrite must stay disabled"),
    )

    result = _retrieve(db_path, "怎么标注")
    assert result.hits and result.hits[0].document_id == doc_id


WAKE_CONTENT = "车载唤醒词边界误差必须控制在正负五十毫秒以内，抽检超差样本占比超过百分之五整批返工。"
CS_CONTENT = "客服语音情感标注以语音表现为准，客户语速加快音调升高并叹气时应标焦虑标签。"


def test_student_recall_excludes_unpublished_and_unauthorized(db_path, uploader_id):
    """AC4：未发布/不可见/未授权/过期资料一律不进入学生召回。"""
    good = insert_doc(db_path, uploader_id, title="车载唤醒词标注指南")
    insert_chunk(db_path, good, WAKE_CONTENT)
    cases = {
        "draft": {"status": "draft"},
        "teacher_only": {"visibility": "teacher"},
        "forbidden": {"license_status": "forbidden"},
        "pending_license": {"license_status": "pending"},
        "expired": {"expires_at": "2020-01-01T00:00:00+00:00"},
        "archived": {"status": "archived"},
    }
    for suffix, overrides in cases.items():
        doc_id = insert_doc(db_path, uploader_id, title=f"车载唤醒词标注指南-{suffix}", **overrides)
        insert_chunk(db_path, doc_id, WAKE_CONTENT + suffix)

    result = _retrieve(db_path, "唤醒词边界误差要求是多少")
    hit_doc_ids = {h.document_id for h in result.hits}
    assert good in hit_doc_ids
    assert len(hit_doc_ids) == 1  # 其余全部被硬过滤

    # 教师预览（published_only=False）可以看到未发布资料，但仍排除归档
    preview = _retrieve(db_path, "唤醒词边界误差要求是多少", published_only=False)
    preview_titles = {h.title for h in preview.hits}
    assert "车载唤醒词标注指南-draft" in preview_titles
    assert "车载唤醒词标注指南-archived" not in preview_titles


def test_gibberish_query_below_threshold_and_refused(db_path, uploader_id):
    """AC6：无可靠召回 → 拒答，引用为空，绝不编造。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)
    result = _retrieve(db_path, "啊啊呃呃呜呜呀呀咦咦")
    assert result.below_threshold is True
    answer = _answer(db_path, "啊啊呃呃呜呜呀呀咦咦")
    assert answer.refused is True
    assert answer.answer == REFUSAL_MESSAGE
    assert answer.citations == []
    assert answer.related_cap_ids == []


def test_answer_can_limit_recall_to_selected_documents(db_path, uploader_id):
    """Answer synthesis must honor the same document scope as recall testing."""
    selected = insert_doc(db_path, uploader_id, title="选定资料")
    insert_chunk(db_path, selected, WAKE_CONTENT)
    outside = insert_doc(db_path, uploader_id, title="未选资料")
    insert_chunk(db_path, outside, WAKE_CONTENT)

    answer = _answer(
        db_path,
        "唤醒词边界误差要求是多少",
        document_ids=[selected],
    )

    assert answer.refused is False
    assert answer.citations
    assert {citation["document_id"] for citation in answer.citations} == {selected}


def test_retrieval_ignores_incompatible_embedding_models_and_dimensions(
    db_path, uploader_id, monkeypatch
):
    """A provider change must skip old local vectors instead of raising a 500."""
    local_doc = insert_doc(db_path, uploader_id, title="local embedding document")
    insert_chunk(db_path, local_doc, WAKE_CONTENT)
    provider_doc = insert_doc(db_path, uploader_id, title="provider embedding document")
    provider_blob = struct.pack("<8f", *([1.0] + [0.0] * 7))
    insert_chunk(
        db_path,
        provider_doc,
        "provider-compatible evidence",
        embedding=provider_blob,
        embedding_model="provider-eight",
    )

    conn = connect(db_path)
    try:
        # The low-level search intentionally omits a model filter here.  Its
        # shape guard must still avoid scoring the stored 512-d local vector.
        candidates = vector_search(conn, provider_blob, published_only=True)
        assert [candidate.document_id for candidate in candidates] == [provider_doc]
    finally:
        conn.close()

    # Retrieval passes the active model name, so same-dimension model changes
    # also fail closed until operators deliberately rebuild the old index.
    monkeypatch.setattr(
        "bhzd_py.rag.retriever.embed_chunks",
        lambda _db, _texts: ([provider_blob], "provider-eight"),
    )
    result = _retrieve(db_path, "provider query")
    assert [hit.document_id for hit in result.hits] == [provider_doc]


def test_multiple_versions_keep_latest_published(db_path, uploader_id):
    """同标题多版本：只召回最新已发布版本，答案注释展示版本号。"""
    old_doc = insert_doc(
        db_path, uploader_id, title="标注规范", version="v1.0",
        published_at="2026-01-01T00:00:00+00:00",
    )
    insert_chunk(db_path, old_doc, "旧版内容：唤醒词误差一百毫秒以内即可。")
    new_doc = insert_doc(
        db_path, uploader_id, title="标注规范", version="v2.0",
        published_at="2026-06-01T00:00:00+00:00",
    )
    insert_chunk(db_path, new_doc, "新版内容：唤醒词误差必须控制在五十毫秒以内。")

    result = _retrieve(db_path, "唤醒词误差要求")
    assert result.hits, "应有召回"
    assert {h.document_id for h in result.hits} == {new_doc}
    assert all(h.version == "v2.0" for h in result.hits)
    answer = _answer(db_path, "唤醒词误差要求")
    assert any("v2.0" in note for note in answer.notes)


def test_answer_question_template_fallback_and_contract(db_path, uploader_id):
    """无 composer：确定性模板答案 + 步骤 + 引用（封顶）+ 关联能力并集 + 追问。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范", cap_ids=["CAP-A", "CAP-B"])
    content = (
        "1. 听取完整通话后再判定情感标签。\n"
        "2. 语速加快音调升高并叹气时标焦虑。\n"
        "3. 听不清的片段用 [UNK] 标记。\n"
        "4. 禁止臆测补全内容。\n"
        "5. 每段标注后自查一遍。"
    )
    insert_chunk(db_path, doc_id, content, section="情感标注")
    # 查询与切片共享"情感标签/判定"词面，保证本地哈希嵌入 + 混合召回能过阈值
    answer = _answer(db_path, "情感标签如何判定")
    assert answer.refused is False
    assert 0 < len(answer.answer) <= 301  # 截取 ≤300 字（可能带省略号）
    assert 1 <= len(answer.steps) <= 4  # 按编号行取前 4 步
    assert not any("自查" in step for step in answer.steps)  # 第 5 步被截掉
    assert len(answer.citations) == 1
    citation = answer.citations[0]
    assert citation["title"] == "客服语音标注规范"
    assert citation["version"] == "v1.0"
    assert "chunk_id" not in citation  # 学生端不暴露切片 ID（PRD-06 §4.5）
    assert answer.related_cap_ids == ["CAP-A", "CAP-B"]
    assert len(answer.followups) == 3


def test_answer_question_uses_injected_composer(db_path, uploader_id):
    """agent 域注入的 composer 优先；composer 异常时回退模板（PRD-06 §11.1）。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)

    seen_messages: list[list[dict]] = []

    def composer(messages):
        seen_messages.append(messages)
        return "这是 LLM 合成的答案"

    answer = _answer(db_path, "情感标注以什么为准", composer=composer)
    assert answer.answer == "这是 LLM 合成的答案"
    assert seen_messages and seen_messages[0][0]["role"] == "system"
    assert "证据" in seen_messages[0][1]["content"]  # 证据压缩进入 prompt

    def broken_composer(_messages):
        raise RuntimeError("LLM down")

    fallback = _answer(db_path, "情感标注以什么为准", composer=broken_composer)
    assert fallback.refused is False
    assert fallback.answer != "这是 LLM 合成的答案"  # 回退到模板截取


def test_refusal_policy_generic_advice(db_path, uploader_id):
    """refusal_policy=generic_advice 时，拒答附通用学习建议（PRD-06 §4.4）。"""
    doc_id = insert_doc(db_path, uploader_id, title="客服语音标注规范")
    insert_chunk(db_path, doc_id, CS_CONTENT)
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET refusal_policy = 'generic_advice' WHERE id = 1")
    conn.commit()
    conn.close()
    answer = _answer(db_path, "啊啊呃呃呜呜呀呀咦咦")
    assert answer.refused is True
    assert answer.answer.startswith(REFUSAL_MESSAGE)
    assert "预设学习" in answer.answer


def test_document_ids_filter_restricts_candidates(db_path, uploader_id):
    doc_a = insert_doc(db_path, uploader_id, title="规范甲")
    insert_chunk(db_path, doc_a, WAKE_CONTENT)
    doc_b = insert_doc(db_path, uploader_id, title="规范乙")
    insert_chunk(db_path, doc_b, WAKE_CONTENT)
    result = _retrieve(db_path, "唤醒词边界误差", document_ids=[doc_a])
    assert {h.document_id for h in result.hits} == {doc_a}
