"""向量库：SQLite BLOB 余弦检索 + 文档级 SQL 预过滤 + 事务化重建索引（蓝图 §2.1）。

架构要点（为什么）：
- 向量以 local_embed 打包的 float32 BLOB 直接存 rag_chunks.embedding，
  检索时 SQL 先做文档级预过滤（状态/可见性/授权/过期/数据类型/指定文档/
  台账有效性），命中候选才在 Python 里算余弦——MVP 数据量下这比引入
  独立向量库更可靠，且天然离线可跑（PRD-06 §11 降级要求）。
- 已移除的上下文维度不再参与 SQL 预过滤；候选只按仍受支持的资料条件筛选。
- `index_chunks` 用单事务"删旧插新"：PRD-06 §5.2 要求新索引成功后再切换，
  事务的原子性保证召回侧永远看到完整的旧索引或完整的新索引。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from ..db import transaction, utc_now_iso
from .local_embed import bytes_to_array, cosine_similarity


def _unpack(blob: bytes):
    """Expose any stored float32 BLOB without materializing a Python float list."""
    return bytes_to_array(blob)


@dataclass
class Candidate:
    """一条召回候选：切片字段 + 所属文档的过滤/展示字段 + 向量余弦分。"""

    chunk_id: str
    document_id: str
    content: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    title: str
    version: str
    cap_ids: list[str]
    published_at: str | None
    created_at: str
    cosine: float


def _filtered_rows(
    db: sqlite3.Connection,
    *,
    embedding_model: str | None = None,
    require_embedding: bool = True,
    published_only: bool = True,
    data_type: str | None = None,
    document_ids: list[str] | None = None,
    now: str | None = None,
) -> list[sqlite3.Row]:
    """Return the shared metadata-filtered chunk rows for every retrieval mode.

    Keyword-only recall must obey exactly the same publication, license, expiry,
    and document-scope guards as vector recall; keeping the SQL in one helper
    prevents a new mode from accidentally widening the student boundary.
    """
    now = now or utc_now_iso()
    clauses: list[str] = ["c.status = 'active'"]
    if require_embedding:
        clauses.append("c.embedding IS NOT NULL")
    params: list[object] = []
    if embedding_model:
        # Cosine distance only has semantic meaning within one embedding model.
        # Excluding old/fallback vectors makes provider migrations fail closed
        # until a deliberate reindex, rather than mixing incompatible spaces.
        clauses.append("c.embedding_model = ?")
        params.append(embedding_model)
    if published_only:
        clauses.append("d.status = 'published'")
        clauses.append("d.visibility = 'student'")
        clauses.append("d.license_status = 'authorized'")
        clauses.append("(d.expires_at IS NULL OR d.expires_at > ?)")
        params.append(now)
        # 台账联动：绑定台账的资料，台账过期/禁用即移出学生召回
        clauses.append(
            "(sl.id IS NULL OR (sl.authorization_status NOT IN ('forbidden','expired')"
            " AND (sl.valid_to IS NULL OR sl.valid_to > ?)))"
        )
        params.append(now)
    else:
        clauses.append("d.status NOT IN ('archived','expired','failed')")
    if data_type:
        # 空数组 = 通用资料，匹配一切数据类型
        clauses.append(
            "(d.data_types_json = '[]' OR EXISTS"
            " (SELECT 1 FROM json_each(d.data_types_json) je WHERE je.value = ?))"
        )
        params.append(data_type)
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        clauses.append(f"d.id IN ({placeholders})")
        params.extend(document_ids)
    rows = db.execute(
        f"""
        SELECT c.id AS chunk_id, c.document_id, c.content, c.section_title,
               c.page_start, c.page_end, c.embedding,
               d.title, d.version, d.cap_ids_json,
               d.published_at, d.created_at
        FROM rag_chunks c
        JOIN rag_documents d ON d.id = c.document_id
        LEFT JOIN source_ledgers sl ON sl.id = d.source_ledger_id
        WHERE {" AND ".join(clauses)}
        """,
        params,
    ).fetchall()

    return rows


def _candidate_from_row(row: sqlite3.Row, score: float) -> Candidate:
    """Build the stable candidate DTO used by vector and lexical scoring."""
    import json

    return Candidate(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        content=row["content"],
        section_title=row["section_title"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        title=row["title"],
        version=row["version"],
        cap_ids=json.loads(row["cap_ids_json"] or "[]"),
        published_at=row["published_at"],
        created_at=row["created_at"],
        cosine=score,
    )


def search(
    db: sqlite3.Connection,
    query_blob: bytes,
    *,
    embedding_model: str | None = None,
    published_only: bool = True,
    data_type: str | None = None,
    document_ids: list[str] | None = None,
    now: str | None = None,
) -> list[Candidate]:
    """SQL 预过滤 + Python 余弦打分，返回全部候选（截断/重排交给调用方）。

    预过滤规则（PRD-06 §4.4 学生召回边界）：
    - published_only=True：status=published AND visibility=student AND
      license_status=authorized AND 未过期 AND 关联台账未过期/未禁用；
    - published_only=False（教师预览/测试台）：仅排除 archived/expired/failed，
      让未发布资料可被管理端测试（PRD-06 §15 #7）。
    """
    query_vec = _unpack(query_blob)
    candidates: list[Candidate] = []
    for row in _filtered_rows(
        db,
        embedding_model=embedding_model,
        published_only=published_only,
        data_type=data_type,
        document_ids=document_ids,
        now=now,
    ):
        try:
            chunk_vec = _unpack(row["embedding"])
        except ValueError:
            # A malformed historical BLOB is ignored so one corrupt chunk does
            # not make an otherwise healthy retrieval endpoint return 500.
            continue
        if chunk_vec.shape != query_vec.shape:
            # Direct callers may omit the model filter.  Retain a dimension
            # guard here as a second line of defense against mixed corpora.
            continue
        candidates.append(_candidate_from_row(row, cosine_similarity(query_vec, chunk_vec)))
    return candidates


def search_keyword(
    db: sqlite3.Connection,
    *,
    embedding_model: str | None = None,
    published_only: bool = True,
    data_type: str | None = None,
    document_ids: list[str] | None = None,
    now: str | None = None,
) -> list[Candidate]:
    """Return metadata-filtered chunks for lexical scoring without embeddings.

    The caller owns tokenization/scoring because the retriever's CJK bigram
    implementation is intentionally dependency-free.  ``embedding_model`` is
    accepted for API symmetry but ignored: keyword mode can inspect chunks that
    have not yet received a vector.
    """
    return [
        _candidate_from_row(row, 0.0)
        for row in _filtered_rows(
            db,
            embedding_model=None,
            require_embedding=False,
            published_only=published_only,
            data_type=data_type,
            document_ids=document_ids,
            now=now,
        )
    ]


@dataclass
class ChunkRecord:
    """待写入索引的切片记录（切片草稿 + 嵌入产物）。"""

    content: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    token_count: int
    keywords: list[str]
    embedding: bytes
    embedding_model: str
    metadata: dict


def index_chunks(
    db: sqlite3.Connection,
    document_id: str,
    records: list[ChunkRecord],
    process_version: int,
) -> int:
    """事务化替换某文档的全部切片索引，返回写入数量。

    单事务删旧插新（见模块 docstring）；chunk_index 按传入顺序重排，
    保证切片顺序稳定可重建。
    """
    import json

    with transaction(db):
        db.execute("DELETE FROM rag_chunks WHERE document_id = ?", (document_id,))
        for index, record in enumerate(records):
            db.execute(
                """
                INSERT INTO rag_chunks
                  (id, document_id, chunk_index, content, summary, keywords_json,
                   page_start, page_end, section_title, token_count,
                   embedding, embedding_model, metadata_json, status, process_version)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    uuid.uuid4().hex,
                    document_id,
                    index,
                    record.content,
                    json.dumps(record.keywords, ensure_ascii=False),
                    record.page_start,
                    record.page_end,
                    record.section_title,
                    record.token_count,
                    record.embedding,
                    record.embedding_model,
                    json.dumps(record.metadata, ensure_ascii=False),
                    process_version,
                ),
            )
    return len(records)
