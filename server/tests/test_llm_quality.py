"""Offline RAG quality and tuning regression cases required by P2-2/P2-4.

These cases deliberately use the deterministic local embedding and an injected
composer.  They protect the response contract without treating a mock provider
as proof of real-provider quality, and can be selected independently in CI.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.rag.local_embed import EMBEDDING_MODEL, embed_text
from bhzd_py.rag.retriever import REFUSAL_MESSAGE, answer_question
from bhzd_py.security import hash_password


# P2-2 cases are intentionally optional in CI because they model answer
# quality, although this offline subset remains deterministic and network-free.
pytestmark = pytest.mark.slow


@pytest.fixture()
def quality_db_path(tmp_db_path, tmp_path, monkeypatch):
    """Create a clean, migrated RAG database so quality assertions share real storage paths."""

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
def quality_uploader_id(quality_db_path):
    """Create the minimum valid teacher owner for published test documents."""

    conn = connect(quality_db_path)
    now = utc_now_iso()
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at) "
        "VALUES (?, ?, ?, 'teacher', 'active', ?, ?, ?)",
        (user_id, "quality-teacher@test.local", "质量回归教师", now, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at) VALUES (?, ?, 'argon2id', ?)",
        (user_id, hash_password("Test1234!"), now),
    )
    conn.commit()
    conn.close()
    return user_id


def _insert_published_evidence(db_path: str, uploader_id: str, *, title: str, content: str) -> str:
    """Insert a fully indexed student-visible document without invoking provider-backed ingestion."""

    conn = connect(db_path)
    now = utc_now_iso()
    document_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO rag_documents (id, title, file_type, source_type, source_name, version,
          license_status, data_types_json, cap_ids_json, visibility, status, process_version,
          created_by, created_at, updated_at, published_at)
        VALUES (?, ?, 'md', 'standard', 'P2 quality corpus', 'v1', 'authorized', '[]', '[]',
                'student', 'published', 1, ?, ?, ?, ?)
        """,
        (document_id, title, uploader_id, now, now, now),
    )
    conn.execute(
        """
        INSERT INTO rag_chunks (id, document_id, chunk_index, content, keywords_json, section_title,
          token_count, embedding, embedding_model, status, process_version)
        VALUES (?, ?, 0, ?, '[]', '质量基准', ?, ?, ?, 'active', 1)
        """,
        (uuid.uuid4().hex, document_id, content, len(content), embed_text(content), EMBEDDING_MODEL),
    )
    conn.commit()
    conn.close()
    return document_id


def _answer(db_path: str, question: str, *, composer=None):
    """Run the public answer contract against a short-lived connection."""

    conn = connect(db_path)
    try:
        return answer_question(conn, get_config(), question, composer=composer)
    finally:
        conn.close()


def test_known_question_answer_contains_expected_keyword(quality_db_path, quality_uploader_id):
    """Known corpus question must keep its expected rule keyword in the fallback answer."""

    _insert_published_evidence(
        quality_db_path,
        quality_uploader_id,
        title="唤醒词边界规范",
        content="车载唤醒词的边界误差必须控制在正负五十毫秒以内。",
    )

    answer = _answer(quality_db_path, "唤醒词边界误差要求是多少")

    assert answer.refused is False
    assert "五十毫秒" in answer.answer


def test_citation_document_id_matches_retrieved_evidence(quality_db_path, quality_uploader_id):
    """A successful answer must cite the document that supplied its evidence, never a synthetic ID."""

    document_id = _insert_published_evidence(
        quality_db_path,
        quality_uploader_id,
        title="情感标注规范",
        content="客服语音中语速加快、音调升高并叹气时，应标注焦虑标签。",
    )

    answer = _answer(quality_db_path, "什么情况下应该标注焦虑标签")

    assert answer.refused is False
    assert answer.citations
    assert {citation["document_id"] for citation in answer.citations} == {document_id}


def test_out_of_knowledge_base_question_has_no_fabricated_citation(quality_db_path, quality_uploader_id):
    """Out-of-corpus input must refuse and expose no citation that could look authoritative."""

    _insert_published_evidence(
        quality_db_path,
        quality_uploader_id,
        title="情感标注规范",
        content="客服语音情感标注以语音表现为准。",
    )

    answer = _answer(quality_db_path, "啊啊呃呃呜呜呀呀咦咦")

    assert answer.refused is True
    assert answer.answer == REFUSAL_MESSAGE
    assert answer.citations == []


def test_unavailable_composer_uses_template_fallback(quality_db_path, quality_uploader_id):
    """A composer exception must preserve a useful, cited deterministic response."""

    document_id = _insert_published_evidence(
        quality_db_path,
        quality_uploader_id,
        title="语音标注规范",
        content="情感标签应以完整通话中的语音表现为准，禁止凭上下文臆测。",
    )

    def unavailable_composer(_messages):
        # The injected seam represents an unavailable LLM without a network call.
        raise RuntimeError("provider unavailable")

    answer = _answer(quality_db_path, "情感标签以什么为准", composer=unavailable_composer)

    assert answer.refused is False
    assert "语音表现" in answer.answer
    assert [citation["document_id"] for citation in answer.citations] == [document_id]


def test_eval_run_reuses_saved_top_k(quality_db_path, quality_uploader_id, monkeypatch):
    """A saved test-console TopK must survive into the comparable eval run."""

    document_id = _insert_published_evidence(
        quality_db_path,
        quality_uploader_id,
        title="TopK 评测资料",
        content="唤醒词边界误差必须控制在正负五十毫秒以内。",
    )
    from bhzd_py.routers import rag_admin

    conn = connect(quality_db_path)
    case_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO eval_cases (id, question, expected_answer, must_hit_document_ids_json,
          must_hit_chunk_ids_json, filters_json, created_by, created_at)
        VALUES (?, ?, NULL, ?, '[]', ?, ?, ?)
        """,
        (
            case_id,
            "唤醒词边界误差要求是多少",
            json.dumps([document_id]),
            json.dumps({"published_only": True, "top_k": 1}),
            quality_uploader_id,
            utc_now_iso(),
        ),
    )
    conn.commit()

    seen_top_k: list[int | None] = []
    original_retrieve = rag_admin.retrieve
    seen_answer_top_k: list[int | None] = []
    original_answer = rag_admin.answer_question

    def capture_retrieve(db, config, query, filters, top_k=None):
        seen_top_k.append(top_k)
        return original_retrieve(db, config, query, filters, top_k=top_k)

    def capture_answer(*args, **kwargs):
        seen_answer_top_k.append(kwargs.get("top_k"))
        return original_answer(*args, **kwargs)

    monkeypatch.setattr(rag_admin, "retrieve", capture_retrieve)
    monkeypatch.setattr(rag_admin, "answer_question", capture_answer)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/rag/eval-runs",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }
    )
    try:
        result = rag_admin.run_eval(
            request,
            rag_admin.EvalRunBody(case_ids=[case_id]),
            SimpleNamespace(user={"id": quality_uploader_id}),
            conn,
        )
    finally:
        conn.close()

    assert result["status"] == "completed"
    assert seen_top_k == [1]
    assert seen_answer_top_k == [1]


@pytest.mark.parametrize("top_k", [0, 21])
def test_search_test_top_k_uses_the_admin_range(top_k):
    """Direct callers cannot bypass the console's 1--20 TopK tuning boundary."""

    from bhzd_py.routers.rag_admin import SearchTestBody

    with pytest.raises(ValidationError):
        SearchTestBody(query="边界误差要求", top_k=top_k)
