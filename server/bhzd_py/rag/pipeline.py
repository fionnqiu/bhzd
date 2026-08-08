"""RAG 处理管线：parse → chunk → index 的任务状态机（PRD-06 §5.1/§5.2，蓝图 §2.1）。

核心规则落实：
- 幂等（PRD-06 §5.2"重复提交同一任务"）：idempotency_key =
  `f"{doc}:{stage}:{process_version}:{sha256(params_json)[:16]}"`，同文档同阶段
  同版本同参数复用既有任务；参数变化由调用方提升 process_version 生成新处理版本。
- 状态机：draft→parsing→parsed→chunking→chunked→indexing→indexed；
  任一阶段失败 → 任务 failed（记 error_code/message/attempt），文档 status=failed，
  同版本下游排队任务自动取消；retry_job 只从失败阶段重跑，不重复已成功阶段。
- MVP 同步执行：run_pending 逐条跑队列，但保留完整状态机/重试语义（蓝图 §6.4）。
- 敏感信息检测（PRD-06 §4.3）在解析阶段执行，结果写入该 parse 任务
  params_json 的 "sensitive_flags" 键；身份证命中置 block_publish=true（阻止发布）。
- 阶段产物（解析块/切片草稿）随任务 params_json 落库：重试时下游阶段可直接
  读取上游产物，不必重做上游工作（"从失败阶段继续"的数据基础）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path

from ..config import AppConfig
from ..db import utc_now_iso
from .chunker import chunk_blocks
from .embeddings import embed_chunks
from .errors import CHUNK_EMPTY, RAGError
from .parsers import Block, parse_document
from .retriever import load_settings
from .vectorstore import ChunkRecord, index_chunks

logger = logging.getLogger(__name__)

STAGE_ORDER = ("parse", "chunk", "index")

# 文档状态迁移表：阶段开始 → 进行中状态，阶段成功 → 完成态（PRD-06 §5.1）
_STAGE_RUNNING_STATUS = {"parse": "parsing", "chunk": "chunking", "index": "indexing"}
_STAGE_SUCCESS_STATUS = {"parse": "parsed", "chunk": "chunked", "index": "indexed"}

# PRD-06 §4.3 首期敏感信息检测：手机号 / 身份证 / 邮箱
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scan_sensitive_info(text: str) -> dict:
    """敏感信息扫描：返回各类型命中数；身份证命中即 block_publish（§4.3 阻止发布）。"""
    id_cards = len(_ID_CARD_RE.findall(text))
    return {
        "phone": len(_PHONE_RE.findall(text)),
        "id_card": id_cards,
        "email": len(_EMAIL_RE.findall(text)),
        "block_publish": id_cards > 0,
    }


def _canonical_params(params: dict) -> str:
    """参数规范化序列化：排序键保证同参数同哈希（幂等 key 的稳定输入）。"""
    return json.dumps(params or {}, ensure_ascii=False, sort_keys=True)


def enqueue(
    db: sqlite3.Connection,
    document_id: str,
    stages: list[str],
    params: dict[str, dict],
    process_version: int,
) -> list[str]:
    """为文档排队一组阶段任务，返回任务 id 列表（同 key 复用既有任务）。

    `params` 形如 `{"parse": {...}, "chunk": {...}, "index": {...}}`，按阶段取参；
    幂等 key 只哈希调用方传入的参数，阶段产物后续追加进 params_json 不影响 key。
    """
    job_ids: list[str] = []
    for stage in stages:
        if stage not in STAGE_ORDER:
            raise RAGError("STAGE_UNKNOWN", f"未知的处理阶段：{stage}")
        stage_params = (params or {}).get(stage, {})
        canonical = _canonical_params(stage_params)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        key = f"{document_id}:{stage}:{process_version}:{digest}"
        existing = db.execute(
            "SELECT id FROM rag_jobs WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing:
            job_ids.append(existing["id"])  # 幂等命中：复用，不重复解析
            continue
        job_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO rag_jobs (id, document_id, stage, status, idempotency_key,
                                  params_json, created_at)
            VALUES (?, ?, ?, 'queued', ?, ?, ?)
            """,
            (job_id, document_id, stage, key, canonical, utc_now_iso()),
        )
        job_ids.append(job_id)
    db.commit()
    return job_ids


def _parse_job_key(job: sqlite3.Row) -> tuple[str, int]:
    """从 idempotency_key 拆出 (文档 id, 处理版本)；key 形如 doc:stage:version:hash。"""
    parts = (job["idempotency_key"] or "").split(":")
    doc_id = parts[0] if parts else job["document_id"]
    try:
        version = int(parts[2])
    except (IndexError, ValueError):
        version = 1  # 老数据/异常 key 兜底，避免重试路径崩溃
    return doc_id, version


def _latest_succeeded_job(
    db: sqlite3.Connection, document_id: str, stage: str, process_version: int
) -> sqlite3.Row | None:
    """找同文档同版本指定阶段最近一次成功的任务（下游阶段的产物来源）。"""
    return db.execute(
        """
        SELECT * FROM rag_jobs
        WHERE document_id = ? AND stage = ? AND status = 'succeeded'
          AND idempotency_key LIKE ?
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (document_id, stage, f"{document_id}:{stage}:{process_version}:%"),
    ).fetchone()


def recover_interrupted_jobs(db: sqlite3.Connection) -> int:
    """Return jobs left ``running`` by a stopped worker to the durable queue.

    This is called during application startup, before any local maintenance
    worker is launched.  It deliberately preserves ``attempt`` so operators
    can still distinguish an interrupted retry from a first attempt; each
    stage is safe to re-run from its persisted predecessor artifacts.
    """
    recovered = db.execute(
        "UPDATE rag_jobs SET status='queued', started_at=NULL WHERE status='running'"
    )
    db.commit()
    return max(recovered.rowcount, 0)


def _upstream_stage_succeeded(db: sqlite3.Connection, job: sqlite3.Row) -> bool:
    """Check that a queued dependent stage has durable input before claiming it.

    Independent upload and startup workers may inspect the same queue.  A
    downstream row must remain queued while its predecessor is still running,
    rather than being marked failed merely because its artifacts are not yet
    committed.  A succeeded predecessor is terminal for that process version,
    so this check stays valid after the compare-and-set claim below.
    """
    stage_index = STAGE_ORDER.index(job["stage"])
    if stage_index == 0:
        return True
    document_id, process_version = _parse_job_key(job)
    upstream_stage = STAGE_ORDER[stage_index - 1]
    return _latest_succeeded_job(db, document_id, upstream_stage, process_version) is not None


def _fail_job(db: sqlite3.Connection, job: sqlite3.Row, doc_id: str, code: str, message: str) -> None:
    """统一失败收尾：任务记错误，文档置 failed，同版本下游排队任务取消。"""
    now = utc_now_iso()
    db.execute(
        "UPDATE rag_jobs SET status='failed', error_code=?, error_message=?, finished_at=? WHERE id=?",
        (code, message, now, job["id"]),
    )
    db.execute(
        "UPDATE rag_documents SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
        (code, message, now, doc_id),
    )
    _, version = _parse_job_key(job)
    stage_idx = STAGE_ORDER.index(job["stage"])
    for downstream in STAGE_ORDER[stage_idx + 1 :]:
        db.execute(
            """
            UPDATE rag_jobs SET status='cancelled',
                   error_message='上游阶段失败，已自动取消', finished_at=?
            WHERE document_id=? AND stage=? AND status='queued'
              AND idempotency_key LIKE ?
            """,
            (now, doc_id, downstream, f"{doc_id}:{downstream}:{version}:%"),
        )
    db.commit()


def _merge_job_params(db: sqlite3.Connection, job_id: str, outputs: dict) -> None:
    """把阶段产物合并进任务 params_json（幂等 key 在入队时已定型，不受影响）。"""
    row = db.execute("SELECT params_json FROM rag_jobs WHERE id = ?", (job_id,)).fetchone()
    params = json.loads(row["params_json"] or "{}")
    params.update(outputs)
    db.execute(
        "UPDATE rag_jobs SET params_json = ? WHERE id = ?",
        (json.dumps(params, ensure_ascii=False, sort_keys=True), job_id),
    )


def _run_parse_stage(db: sqlite3.Connection, config: AppConfig, job: sqlite3.Row, doc: sqlite3.Row) -> None:
    """解析阶段：读文件 → parse_document → 敏感信息扫描 → 产物落 params_json。"""
    storage_path = doc["storage_path"]
    if not storage_path:
        raise RAGError("FILE_MISSING", "原始文件不存在，无法解析")
    path = Path(storage_path)
    if not path.is_absolute():
        path = Path(config.resolved_upload_dir) / path  # 相对路径按上传目录解析
    try:
        file_bytes = path.read_bytes()
    except OSError as exc:
        raise RAGError("FILE_MISSING", f"原始文件读取失败：{exc}") from exc
    parsed = parse_document(file_bytes, doc["file_type"])
    flags = scan_sensitive_info(parsed.total_text)
    _merge_job_params(
        db,
        job["id"],
        {
            "blocks": [
                {"text": b.text, "page": b.page, "section_title": b.section_title}
                for b in parsed.blocks
            ],
            "sensitive_flags": flags,
        },
    )


def _run_chunk_stage(db: sqlite3.Connection, _config: AppConfig, job: sqlite3.Row, doc: sqlite3.Row) -> None:
    """切片阶段：取同版本最近一次解析产物 → chunk_blocks → 草稿落 params_json。"""
    _, version = _parse_job_key(job)
    parse_job = _latest_succeeded_job(db, doc["id"], "parse", version)
    if parse_job is None:
        raise RAGError("UPSTREAM_MISSING", "缺少已完成的解析结果，请先执行解析")
    parse_params = json.loads(parse_job["params_json"] or "{}")
    blocks = [
        Block(text=b["text"], page=b.get("page"), section_title=b.get("section_title"))
        for b in parse_params.get("blocks", [])
    ]
    settings = load_settings(db)
    job_params = json.loads(job["params_json"] or "{}")
    drafts = chunk_blocks(
        blocks,
        chunk_size=int(job_params.get("chunk_size", settings.chunk_size)),
        chunk_overlap=int(job_params.get("chunk_overlap", settings.chunk_overlap)),
        title_inherit=bool(job_params.get("title_inherit", settings.title_inherit)),
        # 表格策略随设置消费（PRD-03 §6）：任务参数优先，缺省用当前 rag_settings
        table_strategy=str(job_params.get("table_strategy", settings.table_strategy)),
    )
    if not drafts:
        raise RAGError(CHUNK_EMPTY)
    _merge_job_params(
        db,
        job["id"],
        {
            "chunks": [
                {
                    "content": d.content,
                    "section_title": d.section_title,
                    "page_start": d.page_start,
                    "page_end": d.page_end,
                    "token_count": d.token_count,
                }
                for d in drafts
            ]
        },
    )


def _run_index_stage(db: sqlite3.Connection, _config: AppConfig, job: sqlite3.Row, doc: sqlite3.Row) -> None:
    """索引阶段：取同版本切片草稿 → 嵌入（provider 优先本地兜底）→ 事务化重建索引。"""
    _, version = _parse_job_key(job)
    chunk_job = _latest_succeeded_job(db, doc["id"], "chunk", version)
    if chunk_job is None:
        raise RAGError("UPSTREAM_MISSING", "缺少已完成的切片结果，请先执行切片")
    chunk_params = json.loads(chunk_job["params_json"] or "{}")
    drafts = chunk_params.get("chunks", [])
    if not drafts:
        raise RAGError(CHUNK_EMPTY)
    texts = [d["content"] for d in drafts]
    try:
        blobs, model = embed_chunks(db, texts)
    except Exception as exc:  # embed_chunks 对 provider 故障已兜底，这里只防本地意外
        raise RAGError("EMBEDDING_FAILED") from exc
    records = [
        ChunkRecord(
            content=d["content"],
            section_title=d.get("section_title"),
            page_start=d.get("page_start"),
            page_end=d.get("page_end"),
            token_count=int(d.get("token_count", 0)),
            keywords=[],
            embedding=blob,
            embedding_model=model,
            metadata={},
        )
        for d, blob in zip(drafts, blobs)
    ]
    count = index_chunks(db, doc["id"], records, version)
    _merge_job_params(db, job["id"], {"chunk_count": count, "embedding_model": model})


_STAGE_HANDLERS = {
    "parse": _run_parse_stage,
    "chunk": _run_chunk_stage,
    "index": _run_index_stage,
}


def _run_job(db: sqlite3.Connection, config: AppConfig, job: sqlite3.Row) -> bool | None:
    """Execute one queued job, or skip it when another worker claimed it first.

    Upload BackgroundTasks and startup recovery can overlap briefly.  The status
    compare-and-set makes the durable queue single-consumer without introducing
    a process-local lock that would fail across reloads or multiple workers.
    """
    # A second worker can observe chunk/index rows while their upstream work is
    # still running.  Leave them queued until the predecessor commits instead
    # of converting a harmless scheduling race into a document failure.
    if not _upstream_stage_succeeded(db, job):
        return None

    now = utc_now_iso()
    claimed = db.execute(
        """
        UPDATE rag_jobs
        SET status='running', started_at=?, attempt=attempt+1
        WHERE id=? AND status='queued'
        """,
        (now, job["id"]),
    )
    if claimed.rowcount != 1:
        return None
    doc = db.execute("SELECT * FROM rag_documents WHERE id = ?", (job["document_id"],)).fetchone()
    if doc is None:
        _fail_job(db, job, job["document_id"], "DOC_MISSING", "文档不存在或已删除")
        return False
    db.execute(
        "UPDATE rag_documents SET status=?, updated_at=? WHERE id=?",
        (_STAGE_RUNNING_STATUS[job["stage"]], now, doc["id"]),
    )
    db.commit()
    try:
        _STAGE_HANDLERS[job["stage"]](db, config, job, doc)
    except RAGError as exc:
        logger.warning("rag 任务 %s(%s) 失败：%s %s", job["id"], job["stage"], exc.code, exc.message)
        _fail_job(db, job, doc["id"], exc.code, exc.message)
        return False
    except Exception as exc:  # 意外错误：保留类型信息给管理端排查，消息仍是中文
        logger.exception("rag 任务 %s(%s) 意外失败", job["id"], job["stage"])
        _fail_job(db, job, doc["id"], "STAGE_ERROR", f"处理失败（{type(exc).__name__}），请重试或联系管理员")
        return False
    done = utc_now_iso()
    db.execute(
        "UPDATE rag_jobs SET status='succeeded', progress=1, finished_at=? WHERE id=?",
        (done, job["id"]),
    )
    db.execute(
        "UPDATE rag_documents SET status=?, error_code=NULL, error_message=NULL, updated_at=? WHERE id=?",
        (_STAGE_SUCCESS_STATUS[job["stage"]], done, doc["id"]),
    )
    db.commit()
    return True


def run_pending(
    db: sqlite3.Connection,
    config: AppConfig,
    document_id: str | None = None,
) -> dict:
    """同步执行排队任务（可按文档过滤），返回执行汇总。"""
    if document_id:
        rows = db.execute(
            "SELECT * FROM rag_jobs WHERE status='queued' AND document_id=? ORDER BY created_at, rowid",
            (document_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM rag_jobs WHERE status='queued' ORDER BY created_at, rowid"
        ).fetchall()
    summary = {"executed": 0, "failed": 0, "jobs": []}
    for job in rows:
        # 任务列表是循环前取的快照：前序任务失败会取消下游排队任务，
        # 执行前必须复查最新状态，否则被取消的任务会被陈旧快照误执行
        fresh = db.execute("SELECT status FROM rag_jobs WHERE id = ?", (job["id"],)).fetchone()
        if fresh is None or fresh["status"] != "queued":
            continue
        summary["jobs"].append(job["id"])
        outcome = _run_job(db, config, job)
        if outcome is True:
            summary["executed"] += 1
        elif outcome is False:
            summary["failed"] += 1
    return summary


def retry_job(db: sqlite3.Connection, config: AppConfig, job_id: str) -> dict:
    """从失败阶段重试：重置该任务及其同版本被取消的下游任务后重新执行队列。

    已成功的上游阶段不动（其产物仍在 params_json 中），满足 PRD-06 §5.2
    "任务重试从失败阶段重试，不重复已成功阶段"。
    """
    job = db.execute("SELECT * FROM rag_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise RAGError("JOB_NOT_FOUND", "任务不存在")
    if job["status"] not in ("failed", "cancelled"):
        raise RAGError("JOB_NOT_RETRYABLE", "仅失败或已取消的任务可以重试")
    doc_id, version = _parse_job_key(job)
    stage_idx = STAGE_ORDER.index(job["stage"])
    db.execute(
        "UPDATE rag_jobs SET status='queued', error_code=NULL, error_message=NULL,"
        " started_at=NULL, finished_at=NULL WHERE id=?",
        (job_id,),
    )
    for downstream in STAGE_ORDER[stage_idx + 1 :]:
        db.execute(
            """
            UPDATE rag_jobs SET status='queued', error_code=NULL, error_message=NULL,
                   started_at=NULL, finished_at=NULL
            WHERE document_id=? AND stage=? AND status='cancelled'
              AND idempotency_key LIKE ?
            """,
            (doc_id, downstream, f"{doc_id}:{downstream}:{version}:%"),
        )
    db.commit()
    summary = run_pending(db, config, document_id=doc_id)
    summary["retried_job_id"] = job_id
    return summary
