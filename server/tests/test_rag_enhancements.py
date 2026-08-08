"""RAG 域增强能力测试（A1 扩展：provider 嵌入/重排/表格策略/csv+xlsx/批量/召回记录/评测历史）。

覆盖范围：
- provider 嵌入真实接入：embed_texts(async) 被实际调用并记录真实模型名；
  异常/None 降级本地哈希嵌入；在运行中的事件循环内调用 embed_chunks 也能工作
  （run_coro_sync 的线程桥接路径）。
- provider 重排真实接入：complete() 输出编号 JSON → 命中顺序改变并上报
  rerank_model；失败保持向量序；_parse_rerank_order 防御性解析。
- 表格策略：keep 原子不拆 / flatten 展平成句；管线从 rag_settings 消费策略。
- csv/xlsx 解析：行→块（表头作列名上下文）、sheet→块（sheet 名作章节）。
- 批量操作：逐条守卫 + 部分成功 + 逐条审计。
- 召回记录：学生问答与召回测试台写 recall_logs，召回记录端点可读。
- 评测历史列表端点：最新在前 + 分页 + 不带 case_results。

provider 调用全部 monkeypatch 为 async 假实现，离线可跑。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.rag import pipeline
from bhzd_py.rag.chunker import chunk_blocks
from bhzd_py.rag.embeddings import embed_chunks
from bhzd_py.rag.local_embed import EMBEDDING_MODEL as LOCAL_MODEL
from bhzd_py.rag.parsers import Block, parse_document
from bhzd_py.rag.retriever import RagFilters, _parse_rerank_order, retrieve
from bhzd_py.security import hash_password, hash_token


# ---------------------------------------------------------------- 公共夹具与工具

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
    """直接插入 user_sessions 行，返回 (会话令牌, CSRF 令牌)（与 test_rag_admin 同手法）。"""
    conn = connect(db_path)
    token, csrf = uuid.uuid4().hex, uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO user_sessions (id, user_id, token_hash, csrf_token_hash, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, user_id, hash_token(token), hash_token(csrf),
         now.isoformat(), (now + timedelta(hours=72)).isoformat()),
    )
    conn.commit()
    conn.close()
    return token, csrf


@pytest.fixture()
def system_admin(db_path):
    return create_session(db_path, create_user(db_path, "enh-rag-admin@test.local", "system_admin"))


@pytest.fixture()
def student(db_path):
    return create_session(db_path, create_user(db_path, "student@test.local", "student"))


@pytest.fixture()
def uploader_id(db_path):
    return create_user(db_path, "enh-uploader@test.local", "system_admin")


def as_user(client: TestClient, session: tuple[str, str]) -> dict:
    token, csrf = session
    client.cookies.set("bhzd_session", token)
    return {"x-csrf-token": csrf}


def insert_provider(db_path, role: str, model: str) -> None:
    """插入一条启用的 provider 配置（role=embedding/rerank）；密钥列为占位值，
    因为测试会 monkeypatch 掉真实调用，永远不会触发解密。"""
    conn = connect(db_path)
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO provider_configs (id, name, protocol, base_url, model, api_key_encrypted,
          role, enabled, timeout_seconds, extra_json, created_at, updated_at)
        VALUES (?, ?, 'chat_completions', 'https://provider.test/v1', ?, 'dummy', ?, 1, 30, '{}', ?, ?)
        """,
        (uuid.uuid4().hex, f"{role}-provider", model, role, now, now),
    )
    conn.commit()
    conn.close()


def insert_doc(db_path, uploader_id, *, title: str, status: str = "published") -> str:
    conn = connect(db_path)
    now = utc_now_iso()
    doc_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO rag_documents (id, title, file_type, source_type, source_name, version,
          license_status, visibility, status, process_version, created_by, created_at, updated_at,
          published_at)
        VALUES (?, ?, 'md', 'standard', '测试来源', 'v1.0', 'authorized', 'student', ?, 1, ?, ?, ?, ?)
        """,
        (doc_id, title, status, uploader_id, now, now, now if status == "published" else None),
    )
    conn.commit()
    conn.close()
    return doc_id


def insert_chunk(db_path, doc_id: str, content: str, index: int = 0) -> str:
    from bhzd_py.rag.local_embed import embed_text

    conn = connect(db_path)
    chunk_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO rag_chunks (id, document_id, chunk_index, content, keywords_json,
          token_count, embedding, embedding_model, status, process_version)
        VALUES (?, ?, ?, ?, '[]', ?, ?, ?, 'active', 1)
        """,
        (chunk_id, doc_id, index, content, len(content) // 2, embed_text(content), LOCAL_MODEL),
    )
    conn.commit()
    conn.close()
    return chunk_id


def create_document(db_path, uploader_id, file_bytes: bytes, filename: str, file_type: str) -> str:
    """直接落盘并插入 draft 文档行（绕开 API 的管线级测试，同 test_rag_pipeline 手法）。"""
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
        (doc_id, filename, file_type, str(doc_dir / filename),
         hashlib.sha256(file_bytes).hexdigest(), uploader_id, now, now),
    )
    conn.commit()
    conn.close()
    return doc_id


SAMPLE_MD = """# 第一章 标注总则
车载唤醒词标注必须以原始音频为准，禁止凭上下文臆测。

# 第二章 边界要求
唤醒词边界误差必须控制在正负五十毫秒以内。
1. 先听完整段音频再落刀。
2. 边界落在能量最低点。

# 第三章 质检
批次抽检中边界误差超差样本占比超过百分之五时整批返工。
"""


def upload_sample(client: TestClient, headers: dict, **overrides) -> dict:
    form: dict = {
        "title": "车载唤醒词标注指南",
        "source_type": "enterprise",
        "source_name": "合作企业车载语音项目组",
        "version": "v1.4",
        "license_status": "authorized",
        "visibility": "teacher",
        "data_types": ["audio"],
        "scenario_ids": ["SCN-CAR"],
        "cap_ids": ["CAP-AUD-WAKE-COMMAND-001"],
    }
    for key, value in overrides.items():
        form[key] = [value] if key in ("data_types", "scenario_ids", "cap_ids") else value
    response = client.post(
        "/api/rag/documents",
        files={"file": ("唤醒词指南.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        data=form,
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


def publish_sample(client: TestClient, headers: dict, doc_id: str) -> None:
    response = client.post(f"/api/rag/documents/{doc_id}/submit-review", headers=headers)
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/rag/documents/{doc_id}/publish", json={"scope": "student"}, headers=headers
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- 1. provider 嵌入真实接入

def test_embed_chunks_uses_provider_when_configured(db_path, monkeypatch):
    """配置 embedding provider 且调用成功：走 provider 路径并记录真实模型名。"""
    insert_provider(db_path, "embedding", "embed-model-pro-1")
    from bhzd_py.agent import providers

    seen: list[list[str]] = []

    async def fake_embed(texts):
        seen.append(list(texts))
        return [[0.25] * 8 for _ in texts]

    monkeypatch.setattr(providers, "embed_texts", fake_embed)
    conn = connect(db_path)
    blobs, model = embed_chunks(conn, ["第一段文本", "第二段文本"])
    conn.close()
    assert model == "embed-model-pro-1"  # provider 行上的真实模型名
    assert seen == [["第一段文本", "第二段文本"]]  # async provider 被实际调用
    assert all(len(blob) == 8 * 4 for blob in blobs)  # float32 BLOB


def test_embed_chunks_falls_back_on_provider_exception(db_path, monkeypatch):
    """provider 调用抛异常 → 静默降级本地哈希嵌入（PRD-06 §11 降级）。"""
    insert_provider(db_path, "embedding", "embed-model-pro-1")
    from bhzd_py.agent import providers

    async def broken_embed(_texts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(providers, "embed_texts", broken_embed)
    conn = connect(db_path)
    blobs, model = embed_chunks(conn, ["降级测试文本"])
    conn.close()
    assert model == LOCAL_MODEL
    assert len(blobs) == 1 and len(blobs[0]) == 512 * 4


def test_embed_chunks_falls_back_on_provider_none(db_path, monkeypatch):
    """provider 返回 None（未配置/协议不支持）→ 本地兜底。"""
    insert_provider(db_path, "embedding", "embed-model-pro-1")
    from bhzd_py.agent import providers

    async def none_embed(_texts):
        return None

    monkeypatch.setattr(providers, "embed_texts", none_embed)
    conn = connect(db_path)
    blobs, model = embed_chunks(conn, ["仍应得到本地向量"])
    conn.close()
    assert model == LOCAL_MODEL and len(blobs[0]) == 512 * 4


def test_embed_chunks_works_inside_running_event_loop(db_path, monkeypatch):
    """在运行中的事件循环里调用 embed_chunks：run_coro_sync 走新线程+新循环路径，
    provider 结果依然可用（上传等 async 端点触发同步管线的真实场景）。"""
    insert_provider(db_path, "embedding", "embed-model-loop")
    from bhzd_py.agent import providers

    async def fake_embed(texts):
        return [[0.5] * 4 for _ in texts]

    monkeypatch.setattr(providers, "embed_texts", fake_embed)
    conn = connect(db_path)

    async def _call():
        return embed_chunks(conn, ["事件循环内调用"])

    blobs, model = asyncio.run(_call())
    conn.close()
    assert model == "embed-model-loop"
    assert len(blobs) == 1 and len(blobs[0]) == 4 * 4


def test_pipeline_records_provider_embedding_model(db_path, uploader_id, monkeypatch):
    """管线索引阶段把 provider 真实模型名写入 rag_chunks.embedding_model。"""
    insert_provider(db_path, "embedding", "embed-model-pipe")
    from bhzd_py.agent import providers

    async def fake_embed(texts):
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(providers, "embed_texts", fake_embed)
    md = "# 总则\n客服语音标注须遵循双人复核制度，质检通过率不低于百分之九十五。\n"
    doc_id = create_document(db_path, uploader_id, md.encode("utf-8"), "规范.md", "md")
    conn = connect(db_path)
    pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), {"parse": {}, "chunk": {}, "index": {}}, 1)
    summary = pipeline.run_pending(conn, get_config(), document_id=doc_id)
    assert summary["failed"] == 0
    models = {
        row["embedding_model"]
        for row in conn.execute("SELECT DISTINCT embedding_model FROM rag_chunks WHERE document_id = ?", (doc_id,))
    }
    conn.close()
    assert models == {"embed-model-pipe"}


# ---------------------------------------------------------------- 2. provider 重排真实接入

WAKE_CONTENT = "车载唤醒词边界误差必须控制在正负五十毫秒以内，抽检超差样本占比超过百分之五整批返工。"
CS_CONTENT = "客服语音情感标注以语音表现为准，客户语速加快音调升高并叹气时应标焦虑标签。"


def test_rerank_provider_changes_order_and_reports_model(db_path, uploader_id, monkeypatch):
    """启用重排 + rerank provider：complete() 输出的编号序覆盖向量序，模型名上报。"""
    doc_a = insert_doc(db_path, uploader_id, title="车载规范")
    insert_chunk(db_path, doc_a, WAKE_CONTENT)
    doc_b = insert_doc(db_path, uploader_id, title="客服规范")
    insert_chunk(db_path, doc_b, CS_CONTENT)
    insert_provider(db_path, "rerank", "rerank-model-9")
    conn = connect(db_path)

    # 未启用重排时：向量序 A 在前（查询与 A 词面重合）
    plain = retrieve(conn, get_config(), "唤醒词边界误差要求是多少", RagFilters())
    assert [h.document_id for h in plain.hits] == [doc_a, doc_b]
    assert plain.rerank_model is None

    conn.execute("UPDATE rag_settings SET rerank_enabled = 1 WHERE id = 1")
    conn.commit()

    from bhzd_py.agent import providers

    async def fake_complete(_messages, *, role="primary"):
        assert role == "rerank"  # 重排必须用 rerank 角色调用
        return {"text": "[1, 0]", "model": "rerank-model-9", "usage": None, "provider_id": "x"}

    monkeypatch.setattr(providers, "complete", fake_complete)
    reranked = retrieve(conn, get_config(), "唤醒词边界误差要求是多少", RagFilters())
    conn.close()
    assert [h.document_id for h in reranked.hits] == [doc_b, doc_a]  # 顺序被重排翻转
    assert all(h.rerank_score is not None for h in reranked.hits)
    assert reranked.rerank_model == "rerank-model-9"


def test_rerank_failure_preserves_vector_order(db_path, uploader_id, monkeypatch):
    """重排调用失败：保持向量序、rerank_score 为空、模型名如实报 None。"""
    doc_a = insert_doc(db_path, uploader_id, title="车载规范")
    insert_chunk(db_path, doc_a, WAKE_CONTENT)
    doc_b = insert_doc(db_path, uploader_id, title="客服规范")
    insert_chunk(db_path, doc_b, CS_CONTENT)
    insert_provider(db_path, "rerank", "rerank-model-9")
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET rerank_enabled = 1 WHERE id = 1")
    conn.commit()

    from bhzd_py.agent import providers

    async def broken_complete(_messages, *, role="primary"):
        raise RuntimeError("rerank down")

    monkeypatch.setattr(providers, "complete", broken_complete)
    result = retrieve(conn, get_config(), "唤醒词边界误差要求是多少", RagFilters())
    conn.close()
    assert [h.document_id for h in result.hits] == [doc_a, doc_b]  # 向量序不变
    assert all(h.rerank_score is None for h in result.hits)
    assert result.rerank_model is None


def test_parse_rerank_order_defensive():
    """_parse_rerank_order：散文夹带/字符串编号/越界/重复/漏候选/非数组的防御性解析。"""
    assert _parse_rerank_order("根据分析 [2, 0, 1] 完毕", 3) == [2, 0, 1]
    # 字符串编号可解析；越界 5 与重复 1 跳过；漏掉的 2 按原序追加
    assert _parse_rerank_order('[1, "0", 5, 1]', 3) == [1, 0, 2]
    assert _parse_rerank_order("没有数组", 3) is None
    assert _parse_rerank_order("[]", 3) is None
    assert _parse_rerank_order("```json\n[0,1]\n```", 2) == [0, 1]


# ---------------------------------------------------------------- 3. 表格策略消费

TABLE_MD = (
    "时长规范总则如下，各批次严格执行。\n"
    "| 项目 | 要求 |\n"
    "| --- | --- |\n"
    "| 边界误差 | 正负五十毫秒以内 |\n"
    "| 抽检比例 | 不低于百分之十 |\n"
    "| 返工阈值 | 超差占比百分之五 |\n"
    "其余条款从略，以纸质版为准。"
)


def test_chunker_table_keep_atomic_never_splits():
    """keep 策略：表格是原子单元，即使超过 chunk_size 也不在表格内部下刀。"""
    block = Block(text=TABLE_MD, page=None, section_title=None)
    drafts = chunk_blocks([block], chunk_size=60, chunk_overlap=10, title_inherit=False, table_strategy="keep")
    table_drafts = [d for d in drafts if "|" in d.content]
    assert len(table_drafts) == 1  # 整张表格恰好一个切片
    table_draft = table_drafts[0]
    for line in TABLE_MD.splitlines():
        if line.startswith("|"):
            assert line in table_draft.content  # 表格完整未被切开
    assert len(table_draft.content) > 60  # 允许略超 chunk_size（原子性的代价）
    # 表格前后的正文各自成切片，不混入表格
    assert any("总则如下" in d.content and "|" not in d.content for d in drafts)
    assert any("从略" in d.content and "|" not in d.content for d in drafts)


def test_chunker_table_flatten_converts_rows_to_sentences():
    """flatten 策略：表格行展平为 "列 值；列 值" 句子后参与常规切分。"""
    block = Block(text=TABLE_MD, page=None, section_title=None)
    drafts = chunk_blocks([block], chunk_size=500, chunk_overlap=80, title_inherit=False, table_strategy="flatten")
    assert drafts, "应有切片产出"
    joined = "\n".join(d.content for d in drafts)
    assert "|" not in joined  # 管道格式已被展平
    assert "项目 边界误差；要求 正负五十毫秒以内" in joined
    assert "项目 抽检比例；要求 不低于百分之十" in joined
    assert "时长规范总则如下" in joined  # 表格外的正文不丢失


def test_pipeline_consumes_table_strategy_from_settings(db_path, uploader_id):
    """管线切片阶段从 rag_settings 读取 table_strategy 并传入切片器。"""
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET table_strategy = 'flatten' WHERE id = 1")
    conn.commit()
    conn.close()
    doc_id = create_document(db_path, uploader_id, TABLE_MD.encode("utf-8"), "表格.md", "md")
    conn = connect(db_path)
    pipeline.enqueue(conn, doc_id, list(pipeline.STAGE_ORDER), {"parse": {}, "chunk": {}, "index": {}}, 1)
    summary = pipeline.run_pending(conn, get_config(), document_id=doc_id)
    assert summary["failed"] == 0
    rows = conn.execute("SELECT content FROM rag_chunks WHERE document_id = ?", (doc_id,)).fetchall()
    conn.close()
    assert rows, "应有切片入库"
    assert all("|" not in row["content"] for row in rows)
    assert any("项目 边界误差" in row["content"] for row in rows)


# ---------------------------------------------------------------- 4. CSV / XLSX 解析

def test_parse_csv_rows_become_blocks_with_header_context():
    """csv：首行表头作列名上下文，每个数据行一个 block。"""
    csv_bytes = "姓名,语种,标注时长\n张三,中文,120\n李四,英文,80\n".encode("utf-8")
    doc = parse_document(csv_bytes, "csv")
    assert len(doc.blocks) == 2
    assert "姓名 张三" in doc.blocks[0].text
    assert "语种 英文" in doc.blocks[1].text
    assert "标注时长 120" in doc.blocks[0].text


def test_parse_csv_with_bom_and_blank_rows():
    """csv：BOM 被剥离、空行跳过；仅表头无数据 → PARSE_EMPTY_TEXT。"""
    from bhzd_py.rag.errors import PARSE_EMPTY_TEXT, RAGError

    bom_csv = "﻿姓名,语种\n\n张三,中文\n".encode("utf-8")
    doc = parse_document(bom_csv, "csv")
    assert len(doc.blocks) == 1
    assert "姓名 张三" in doc.blocks[0].text  # BOM 不混入列名
    with pytest.raises(RAGError) as excinfo:
        parse_document("姓名,语种\n".encode("utf-8"), "csv")
    assert excinfo.value.code == PARSE_EMPTY_TEXT


def _make_xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    ws1 = workbook.active
    ws1.title = "标注员"
    ws1.append(["姓名", "等级"])
    ws1.append(["张三", "高级"])
    ws2 = workbook.create_sheet("质检规则")
    ws2.append(["规则", "阈值"])
    ws2.append(["通过率", "95%"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_xlsx_per_sheet_blocks():
    """xlsx：每个 sheet 一个 block，sheet 名作章节标题，行展平为句子。"""
    doc = parse_document(_make_xlsx_bytes(), "xlsx")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].section_title == "标注员"
    assert "姓名 张三" in doc.blocks[0].text
    assert doc.blocks[1].section_title == "质检规则"
    assert "规则 通过率" in doc.blocks[1].text and "阈值 95%" in doc.blocks[1].text


def test_upload_xlsx_accepted_and_indexed(client, db_path, system_admin):
    """真实 xlsx 入队后由后台管线完成索引，响应本身不等待处理。"""
    headers = as_user(client, system_admin)
    response = client.post(
        "/api/rag/documents",
        files={"file": ("标注员名册.xlsx", _make_xlsx_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "title": "标注员名册", "source_type": "other", "source_name": "某单位",
            "version": "v1", "license_status": "authorized", "visibility": "teacher",
            "data_types": ["text"],
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["document"]["status"] == "draft"
    assert all(job["status"] == "queued" for job in queued["jobs"])
    # TestClient 已在响应后运行 BackgroundTasks；详情端点是客户端轮询的同一契约。
    detail = client.get(f"/api/rag/documents/{queued['document']['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    doc = detail.json()["document"]
    assert doc["status"] == "indexed"
    assert doc["chunk_count"] >= 1


# ---------------------------------------------------------------- 5. 批量操作

def test_batch_submit_review_partial_success(client, db_path, system_admin):
    """批量送审：已索引的成功、缺来源的失败（REVIEW_REQUIRED）、不存在的 NOT_FOUND。"""
    headers = as_user(client, system_admin)
    good = upload_sample(client, headers, title="批量送审-好")["document"]["id"]
    bad = upload_sample(client, headers, title="批量送审-缺来源")["document"]["id"]
    response = client.patch(f"/api/rag/documents/{bad}", json={"source_name": ""}, headers=headers)
    assert response.status_code == 200
    missing = "0" * 32

    response = client.post(
        "/api/rag/documents/batch",
        json={"ids": [good, bad, missing], "action": "submit_review"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    results = {item["id"]: item for item in response.json()["results"]}
    assert results[good]["ok"] is True
    assert results[bad]["ok"] is False and results[bad]["code"] == "REVIEW_REQUIRED"
    assert results[missing]["ok"] is False and results[missing]["code"] == "NOT_FOUND"

    docs = client.get(f"/api/rag/documents/{good}", headers=headers).json()["document"]
    assert docs["status"] == "review_pending"
    # 每条存在的资料无论成败都写审计（NF8）
    conn = connect(db_path)
    audit_count = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'rag.submit_review'"
    ).fetchone()["n"]
    conn.close()
    assert audit_count == 2


def test_batch_archive_guard_and_repeat(client, db_path, system_admin):
    """批量归档：已发布/已索引均可归档；重复归档第二遍得到 INVALID_STATE。"""
    headers = as_user(client, system_admin)
    published = upload_sample(client, headers, title="批量归档-发布")["document"]["id"]
    publish_sample(client, headers, published)
    indexed = upload_sample(client, headers, title="批量归档-索引")["document"]["id"]

    response = client.post(
        "/api/rag/documents/batch",
        json={"ids": [published, indexed], "action": "archive"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert all(item["ok"] for item in response.json()["results"])

    again = client.post(
        "/api/rag/documents/batch",
        json={"ids": [published], "action": "archive"},
        headers=headers,
    )
    item = again.json()["results"][0]
    assert item["ok"] is False and item["code"] == "INVALID_STATE"


def test_batch_reindex_and_archived_guard(client, db_path, system_admin):
    """批量重建索引：已索引资料 ok；已归档资料拒绝（INVALID_STATE）。"""
    headers = as_user(client, system_admin)
    doc_id = upload_sample(client, headers, title="批量重建")["document"]["id"]
    response = client.post(
        "/api/rag/documents/batch", json={"ids": [doc_id], "action": "reindex"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["ok"] is True
    assert client.get(f"/api/rag/documents/{doc_id}", headers=headers).json()["document"]["status"] == "indexed"

    client.post(f"/api/rag/documents/{doc_id}/archive", headers=headers)
    response = client.post(
        "/api/rag/documents/batch", json={"ids": [doc_id], "action": "reindex"}, headers=headers
    )
    item = response.json()["results"][0]
    assert item["ok"] is False and item["code"] == "INVALID_STATE"


def test_batch_validation(client, db_path, system_admin):
    """批量入参校验：空 ids / 未知 action → 422。"""
    headers = as_user(client, system_admin)
    response = client.post(
        "/api/rag/documents/batch", json={"ids": [], "action": "archive"}, headers=headers
    )
    assert response.status_code == 422
    response = client.post(
        "/api/rag/documents/batch", json={"ids": ["x" * 32], "action": "delete"}, headers=headers
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- 6. 召回记录

def test_student_query_writes_recall_logs_and_endpoint_returns(client, db_path, system_admin, student):
    """学生问答 → recall_logs（student_query）；召回记录端点返回查询/分数/时间/用户名。"""
    headers = as_user(client, system_admin)
    doc_id = upload_sample(client, headers)["document"]["id"]
    publish_sample(client, headers, doc_id)

    student_headers = as_user(client, student)
    question = "唤醒词边界误差要求是多少"
    response = client.post("/api/rag/query", json={"question": question}, headers=student_headers)
    assert response.status_code == 200 and response.json()["refused"] is False

    as_user(client, system_admin)
    response = client.get(f"/api/rag/documents/{doc_id}/recall-records", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    item = payload["items"][0]
    assert item["query"] == question
    assert item["channel"] == "student_query"
    assert item["user_name"] == "student"  # create_user 以邮箱前缀为名
    assert item["score"] is not None
    assert item["created_at"]

    # 分页参数生效
    limited = client.get(f"/api/rag/documents/{doc_id}/recall-records?limit=1&offset=0", headers=headers)
    assert len(limited.json()["items"]) == 1


def test_search_test_writes_recall_logs_with_chunk_id(client, db_path, system_admin):
    """召回测试台 → recall_logs（search_test），带 chunk_id；拒答查询不落学生渠道记录。"""
    headers = as_user(client, system_admin)
    doc_id = upload_sample(client, headers)["document"]["id"]
    response = client.post(
        "/api/rag/search-test",
        json={"query": "边界误差要求", "filters": {"published_only": False}, "top_k": 3},
        headers=headers,
    )
    assert response.status_code == 200
    payload = client.get(f"/api/rag/documents/{doc_id}/recall-records", headers=headers).json()
    assert payload["total"] >= 1
    item = payload["items"][0]
    assert item["channel"] == "search_test"
    assert item["chunk_id"]  # 管理端测试台记录具体命中切片


def test_refused_query_writes_no_student_recall_logs(client, db_path, system_admin, student):
    """拒答（无引用）时不产生 student_query 召回记录。"""
    headers = as_user(client, system_admin)
    doc_id = upload_sample(client, headers)["document"]["id"]
    publish_sample(client, headers, doc_id)
    student_headers = as_user(client, student)
    response = client.post("/api/rag/query", json={"question": "啊啊呃呃呜呜呀呀咦咦"}, headers=student_headers)
    assert response.json()["refused"] is True
    as_user(client, system_admin)
    payload = client.get(f"/api/rag/documents/{doc_id}/recall-records", headers=headers).json()
    assert payload["total"] == 0


# ---------------------------------------------------------------- 7. 评测历史列表

def test_eval_runs_list_newest_first_with_pagination(client, db_path, system_admin):
    """GET /api/rag/eval-runs：最新在前、带指标、不带 case_results、支持分页。"""
    headers = as_user(client, system_admin)
    body = upload_sample(client, headers)
    publish_sample(client, headers, body["document"]["id"])
    case = client.post(
        "/api/rag/eval-cases",
        json={"question": "唤醒词边界误差要求是多少", "must_hit_document_ids": [body["document"]["id"]]},
        headers=headers,
    ).json()["case"]

    run_ids = []
    for _ in range(2):
        response = client.post(
            "/api/rag/eval-runs", json={"case_ids": [case["id"]]}, headers=headers
        )
        assert response.status_code == 201, response.text
        run_ids.append(response.json()["id"])

    response = client.get("/api/rag/eval-runs", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    first, second = payload["items"]
    assert first["created_at"] >= second["created_at"]  # 最新在前
    assert first["id"] == run_ids[-1]
    assert first["metrics"]["recall_at_k"] == 1.0  # 列表带指标
    assert "case_results" not in first  # 详情留给 /eval-runs/{id}
    assert first["status"] == "completed" and first["finished_at"]

    page = client.get("/api/rag/eval-runs?limit=1&offset=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["items"][0]["id"] == run_ids[0]


# ---------------------------------------------------------------- 2b. 召回测试台 rerank_model 诊断（API 级）

def test_search_test_diagnostics_reports_rerank_model(client, db_path, system_admin, monkeypatch):
    """启用重排后，召回测试台 diagnostics.rerank_model 如实上报，重排序反映 provider 输出。"""
    headers = as_user(client, system_admin)
    upload_sample(client, headers)
    insert_provider(db_path, "rerank", "rerank-test-model")
    conn = connect(db_path)
    conn.execute("UPDATE rag_settings SET rerank_enabled = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    from bhzd_py.agent import providers

    async def fake_complete(_messages, *, role="primary"):
        # 候选按编号整体逆序，制造可断言的重排效果
        return {"text": "[2, 1, 0]", "model": "rerank-test-model", "usage": None, "provider_id": "x"}

    monkeypatch.setattr(providers, "complete", fake_complete)
    response = client.post(
        "/api/rag/search-test",
        json={"query": "边界误差要求", "filters": {"published_only": False}, "top_k": 3},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["diagnostics"]["rerank_model"] == "rerank-test-model"
    assert payload["rerank_note"] is None  # 已真正重排，不再是"与向量结果一致"
    vector_ids = [h["chunk_id"] for h in payload["vector_results"]]
    reranked_ids = [h["chunk_id"] for h in payload["reranked_results"]]
    assert len(vector_ids) == 3
    assert reranked_ids == list(reversed(vector_ids))  # [2,1,0] 的效果
