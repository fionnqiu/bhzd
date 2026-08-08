"""RAG 管理端路由（蓝图 §6.4，PRD-03 全篇，PRD-06 §4/§5）。

权限（蓝图 §15）：全部端点仅允许 system_admin；教师、内容管理员和学生一律
403；变更类请求叠加 csrf_protect。系统管理员可能只有管理端会话
（bhzd_admin_session），因此 GET 端点用本模块的 rag_staff 依赖（任一类会话
均可），写端点直接复用 csrf_protect 的"任一会话"加载再查角色。

实现形态：上传后同步执行解析/切片/索引管线（MVP），但完整保留任务状态机、
幂等与重试语义（蓝图 §6.4"同步执行但保留状态机/重试语义"）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel

from .. import deps as _deps
from ..audit import audit
from ..config import get_config
from ..db import connect, utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_db
from ..errors import ApiError
from ..rag import pipeline
from ..rag.errors import (
    CHUNK_EMPTY,
    LICENSE_BLOCKED,
    PARSE_UNSUPPORTED,
    REVIEW_REQUIRED,
    SENSITIVE_INFO_BLOCKED,
    RAGError,
    to_api_error,
)
from ..rag.parsers import SUPPORTED_FILE_TYPES
from ..rag.recall_logs import record_recall_logs
from ..rag.retriever import (
    RagFilters,
    _cjk_bigrams,
    answer_question,
    load_settings,
    retrieve,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# RAG management includes operational metadata and mutations, so it is an
# explicit system-admin-only boundary. Teacher resource selection uses a
# separate published-only endpoint in the teacher domain.
RAG_ADMIN_ROLES = ("system_admin",)

# 上传约束（PRD-03 §5）：单文件 ≤50MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Multipart headers include form fields and boundaries, so the cheap header
# preflight keeps a small allowance while the streamed byte count remains the
# authoritative per-file limit.
_MAX_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024
# A BackgroundTasks worker is independent of request handling.  A few short
# retries cover the common SQLite writer hand-off without turning a 202 upload
# into an unbounded in-process queue worker.
_UPLOAD_PIPELINE_MAX_ATTEMPTS = 4
_UPLOAD_PIPELINE_RETRY_DELAYS_SECONDS = (0.1, 0.3, 0.8)

_SOURCE_TYPES = ("textbook", "standard", "enterprise", "teacher", "competition", "other")
_LICENSE_STATUSES = ("authorized", "internal", "pending", "forbidden")
_VISIBILITIES = ("admin", "teacher", "student")
_DATA_TYPES = ("text", "image", "audio", "video")
_EXT_TO_FILE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".bmp": "image",
    ".webp": "image",
}


class _UploadTooLarge(ValueError):
    """Internal sentinel so a streamed size rejection receives the public 413 contract."""


def _reject_oversized_content_length(request: Request) -> None:
    """Reject clearly oversized multipart bodies before creating a file on disk.

    Content-Length is only an early optimization because it can be absent and
    represents the whole multipart envelope. `_stream_upload_to_path` below
    therefore enforces the exact file limit while copying the body.
    """
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        content_length = int(raw_length)
    except ValueError:
        # The streaming guard is authoritative, so a malformed optional header
        # must not turn an otherwise valid upload into an implementation error.
        return
    if content_length > MAX_UPLOAD_BYTES + _MAX_MULTIPART_OVERHEAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "文件超过 50MB 上限，请拆分后再上传")


def _stream_upload_to_path(file: UploadFile, destination: Path) -> tuple[int, str]:
    """Copy an upload in bounded chunks and calculate its content hash in one pass."""
    byte_count = 0
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as output:
            while chunk := file.file.read(_UPLOAD_CHUNK_BYTES):
                byte_count += len(chunk)
                if byte_count > MAX_UPLOAD_BYTES:
                    raise _UploadTooLarge()
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        # A rejected or interrupted stream must not leave a partial asset that a
        # later retry could mistake for a successfully persisted document.
        destination.unlink(missing_ok=True)
        raise
    return byte_count, digest.hexdigest()


def _preflight_uploaded_file(file_type: str, storage_path: Path) -> None:
    """Reject structurally invalid container files before they enter the async queue.

    XLSX is a ZIP container.  Checking that inexpensive boundary preserves the
    former immediate 422 for obviously corrupt spreadsheets without returning
    to synchronous parsing, chunking, or embedding for every upload.
    """
    if file_type == "xlsx" and not zipfile.is_zipfile(storage_path):
        raise to_api_error(RAGError(PARSE_UNSUPPORTED))


def _is_transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    """Limit automatic retries to SQLite's normal short-lived lock contention."""
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def _run_upload_pipeline(
    document_id: str,
    database_path: str,
    auto_submit: bool,
    actor_id: str,
    client_meta: dict[str, str | None],
) -> None:
    """Run a queued upload with an independent connection after the 202 response.

    FastAPI closes the request-scoped dependency before background work begins.
    Reopening SQLite here prevents a closed or cross-thread request connection
    from turning a durable queued job into a silent failure.
    """
    background_conn: sqlite3.Connection | None = None
    try:
        for attempt in range(_UPLOAD_PIPELINE_MAX_ATTEMPTS):
            try:
                background_conn = connect(database_path)
                pipeline.run_pending(background_conn, get_config(), document_id=document_id)
                break
            except sqlite3.OperationalError as exc:
                # A connection with a failed SQLite operation cannot safely be
                # reused.  Reopening it also releases any partial transaction
                # before another concurrent upload gets its next turn.
                if background_conn is not None:
                    background_conn.close()
                    background_conn = None
                if (
                    not _is_transient_sqlite_error(exc)
                    or attempt == _UPLOAD_PIPELINE_MAX_ATTEMPTS - 1
                ):
                    logger.exception("Background RAG upload pipeline failed for document %s", document_id)
                    return
                delay = _UPLOAD_PIPELINE_RETRY_DELAYS_SECONDS[attempt]
                logger.warning(
                    "RAG upload pipeline hit a transient SQLite lock; retrying document %s in %.1fs",
                    document_id,
                    delay,
                )
                time.sleep(delay)

        # Loop completion means the queue work has either run or been claimed
        # by another worker.  Auto-submit remains conditional on durable index
        # completion, exactly as it was before asynchronous processing.
        assert background_conn is not None
        doc = background_conn.execute(
            "SELECT id, title, file_type, status FROM rag_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if auto_submit and doc is not None and doc["status"] == "indexed":
            # Auto-submit remains conditional on a successful pipeline, matching
            # the previous synchronous behavior without delaying the upload response.
            background_conn.execute(
                "UPDATE rag_documents SET status='review_pending', updated_at=? WHERE id=?",
                (utc_now_iso(), document_id),
            )
            _add_review_record(background_conn, document_id, actor_id, "submit", "上传时自动送审")
            background_conn.commit()
            audit(
                background_conn,
                actor_id,
                "rag.auto_submit_document",
                target_type="rag_document",
                target_id=document_id,
                after={"status": "review_pending"},
                **client_meta,
            )
    except Exception:
        # The pipeline persists per-stage failures itself; this catches only
        # unexpected worker faults that would otherwise be invisible after 202.
        logger.exception("Background RAG upload pipeline failed for document %s", document_id)
    finally:
        # A lock can occur while opening the connection itself, so there may be
        # no resource to release after the bounded retry path gives up.
        if background_conn is not None:
            background_conn.close()


# ---------------------------------------------------------------- 权限依赖

def rag_staff(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> CurrentUser:
    """GET 端点的系统管理员校验：接受用户端或管理端任一会话，角色不足 403。"""
    current = _deps._load_any_session(request, conn)  # 复用地基会话加载，语义一致
    if current is None:
        raise ApiError(401, "UNAUTHORIZED", "请先登录")
    if current.user["role"] not in RAG_ADMIN_ROLES:
        raise ApiError(403, "FORBIDDEN", "没有权限执行此操作")
    return current


def rag_staff_mutation(current: CurrentUser = Depends(csrf_protect)) -> CurrentUser:
    """写端点的系统管理员校验：csrf_protect 已完成会话加载与 CSRF 校验。"""
    if current.user["role"] not in RAG_ADMIN_ROLES:
        raise ApiError(403, "FORBIDDEN", "没有权限执行此操作")
    return current


def _client_meta(request: Request) -> dict:
    """审计用的客户端信息（ip/ua）。"""
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


# ---------------------------------------------------------------- DTO 序列化

def _json_list(raw: str | None) -> list:
    return json.loads(raw or "[]")


def _doc_dto(row: sqlite3.Row, chunk_count: int | None = None) -> dict:
    """资料 DTO：JSON 列展开为数组，便于前端直接消费。"""
    dto = {
        "id": row["id"],
        "title": row["title"],
        "file_type": row["file_type"],
        "source_type": row["source_type"],
        "source_name": row["source_name"],
        "source_url": row["source_url"],
        "source_ledger_id": row["source_ledger_id"],
        "version": row["version"],
        "license_status": row["license_status"],
        "data_types": _json_list(row["data_types_json"]),
        "scenario_ids": _json_list(row["scenario_ids_json"]),
        "cap_ids": _json_list(row["cap_ids_json"]),
        "visibility": row["visibility"],
        "status": row["status"],
        "file_hash": row["file_hash"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "process_version": row["process_version"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "published_at": row["published_at"],
        "expires_at": row["expires_at"],
    }
    if chunk_count is not None:
        dto["chunk_count"] = chunk_count
    return dto


def _job_dto(row: sqlite3.Row, with_params: bool = True) -> dict:
    """任务 DTO；params 里剥离大块产物（blocks/chunks），保留标志位与统计。"""
    params = json.loads(row["params_json"] or "{}") if with_params else {}
    params.pop("blocks", None)
    params.pop("chunks", None)
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "stage": row["stage"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "progress": row["progress"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "attempt": row["attempt"],
        "params": params,
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _chunk_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "chunk_index": row["chunk_index"],
        "content": row["content"],
        "summary": row["summary"],
        "keywords": _json_list(row["keywords_json"]),
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "section_title": row["section_title"],
        "token_count": row["token_count"],
        "embedding_model": row["embedding_model"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "status": row["status"],
        "process_version": row["process_version"],
    }


def _get_doc_or_404(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "资料不存在")
    return row


def _chunk_count(conn: sqlite3.Connection, doc_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM rag_chunks WHERE document_id = ?", (doc_id,)
    ).fetchone()["n"]


def _latest_parse_flags(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    """取最近一次解析任务的敏感信息标志（PRD-06 §4.3 检测结果的对外出口）。"""
    row = conn.execute(
        """
        SELECT params_json FROM rag_jobs
        WHERE document_id = ? AND stage = 'parse'
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (doc_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["params_json"] or "{}").get("sensitive_flags")


def _add_review_record(
    conn: sqlite3.Connection, doc_id: str, reviewer_id: str, action: str, comment: str | None
) -> None:
    conn.execute(
        "INSERT INTO review_records (id, target_type, target_id, reviewer_id, action, comment, created_at)"
        " VALUES (?, 'rag_document', ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, doc_id, reviewer_id, action, comment, utc_now_iso()),
    )


def _default_stage_params(settings) -> dict[str, dict]:
    """按当前 rag_settings 组装三段管线参数（上传/重处理共用）。"""
    return {
        "parse": {},
        "chunk": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "title_inherit": settings.title_inherit,
            "table_strategy": settings.table_strategy,
        },
        "index": {},
    }


# ---------------------------------------------------------------- 资料列表 / 上传 / 详情 / 编辑 / 删除

@router.get("/api/rag/documents")
def list_documents(
    status: str | None = None,
    index_status: str | None = None,
    review_status: str | None = None,
    data_type: str | None = None,
    scenario_id: str | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """资料列表：状态/索引状态/审核状态/数据类型/场景/标题关键字筛选 + 分页。

    索引状态与审核状态是 PRD-03 §4.1 筛选区的业务视角，映射到底层单一 status：
    - index_status=indexed → 已索引及之后的状态；pending → 之前的状态；
    - review_status=pending/approved/rejected 对应 review_pending/published/rejected。
    """
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    if index_status == "indexed":
        clauses.append("d.status IN ('indexed','review_pending','published','archived')")
    elif index_status == "pending":
        clauses.append("d.status NOT IN ('indexed','review_pending','published','archived')")
    if review_status == "pending":
        clauses.append("d.status = 'review_pending'")
    elif review_status == "approved":
        clauses.append("d.status = 'published'")
    elif review_status == "rejected":
        clauses.append("d.status = 'rejected'")
    if data_type:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(d.data_types_json) je WHERE je.value = ?)"
        )
        params.append(data_type)
    if scenario_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(d.scenario_ids_json) je WHERE je.value = ?)"
        )
        params.append(scenario_id)
    if q:
        clauses.append("d.title LIKE ?")
        params.append(f"%{q.strip()}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM rag_documents d {where}", params
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT d.*, (SELECT COUNT(*) FROM rag_chunks c WHERE c.document_id = d.id) AS chunk_count
        FROM rag_documents d {where}
        ORDER BY d.updated_at DESC, d.rowid DESC LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_doc_dto(row, chunk_count=row["chunk_count"]) for row in rows],
        "total": total,
    }


@router.post("/api/rag/documents", status_code=202)
def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    source_type: str = Form(...),
    source_name: str = Form(...),
    source_url: str | None = Form(None),
    source_ledger_id: str | None = Form(None),
    version: str = Form(...),
    license_status: str = Form(...),
    visibility: str = Form(...),
    data_types: list[str] = Form(default=[]),
    scenario_ids: list[str] = Form(default=[]),
    cap_ids: list[str] = Form(default=[]),
    auto_submit: bool = Form(False),
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """上传资料：流式落盘、创建可查询任务，并在响应后异步执行处理管线。

    202 只表示资料和任务已经持久化，调用方应通过文档详情或任务列表观察
    parse → chunk → index 的结果；这避免上传请求占住线程池执行 CPU/网络密集工作。
    """
    # ---- 必填与枚举校验（PRD-03 §5.2：未填来源/授权状态不得上传）----
    if not title.strip():
        raise ApiError(422, "VALIDATION_ERROR", "请填写资料标题")
    if source_type not in _SOURCE_TYPES:
        raise ApiError(422, "VALIDATION_ERROR", "来源类型不合法")
    if not source_name.strip():
        raise ApiError(422, "VALIDATION_ERROR", "请填写来源（未填来源不得上传）")
    if license_status not in _LICENSE_STATUSES:
        raise ApiError(422, "VALIDATION_ERROR", "请填写授权状态（未填授权状态不得上传）")
    if visibility not in _VISIBILITIES:
        raise ApiError(422, "VALIDATION_ERROR", "可见范围不合法")
    if not version.strip():
        raise ApiError(422, "VALIDATION_ERROR", "请填写版本号")
    if not data_types or any(dt not in _DATA_TYPES for dt in data_types):
        raise ApiError(422, "VALIDATION_ERROR", "请填写适用数据类型（text/image/audio/video）")

    # 扩展名决定 file_type；csv/xlsx 属 PRD-03 §3 P1 已支持，image/other 入口直接拒绝
    filename = Path(file.filename or "upload.bin").name  # 去路径，防目录穿越
    file_type = _EXT_TO_FILE_TYPE.get(Path(filename).suffix.lower(), "other")
    if file_type not in SUPPORTED_FILE_TYPES:
        raise to_api_error(RAGError(PARSE_UNSUPPORTED))
    _reject_oversized_content_length(request)

    config = get_config()
    doc_id = uuid.uuid4().hex
    doc_dir = Path(config.resolved_upload_dir) / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    storage_path = doc_dir / filename
    try:
        file_size, file_hash = _stream_upload_to_path(file, storage_path)
    except _UploadTooLarge as exc:
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise ApiError(413, "FILE_TOO_LARGE", "文件超过 50MB 上限，请拆分后再上传") from exc
    if file_size == 0:
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise ApiError(422, "VALIDATION_ERROR", "文件内容为空")
    try:
        _preflight_uploaded_file(file_type, storage_path)
    except ApiError:
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO rag_documents (id, title, file_type, source_type, source_name, source_url,
          source_ledger_id, version, license_status, data_types_json, scenario_ids_json,
          cap_ids_json, visibility, status, storage_path, file_hash, process_version,
          created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, 1, ?, ?, ?)
        """,
        (
            doc_id,
            title.strip(),
            file_type,
            source_type,
            source_name.strip(),
            source_url,
            source_ledger_id,
            version.strip(),
            license_status,
            json.dumps(data_types, ensure_ascii=False),
            json.dumps(scenario_ids, ensure_ascii=False),
            json.dumps(cap_ids, ensure_ascii=False),
            visibility,
            str(storage_path),
            file_hash,
            current.user["id"],
            now,
            now,
        ),
    )
    conn.commit()

    settings = load_settings(conn)
    pipeline.enqueue(
        conn, doc_id, list(pipeline.STAGE_ORDER), _default_stage_params(settings), 1
    )
    # Capture only non-sensitive request metadata.  The background task opens
    # its own connection after this request-scoped one has been closed.
    background_tasks.add_task(
        _run_upload_pipeline,
        doc_id,
        config.resolved_database_path,
        auto_submit,
        current.user["id"],
        _client_meta(request),
    )
    doc = _get_doc_or_404(conn, doc_id)

    audit(
        conn,
        current.user,
        "rag.upload_document",
        target_type="rag_document",
        target_id=doc_id,
        after={"title": doc["title"], "file_type": file_type, "status": doc["status"]},
        **_client_meta(request),
    )
    from .rag_query import emit_telemetry

    emit_telemetry("rag_document_uploaded", {"document_id": doc_id, "status": doc["status"]})

    jobs = conn.execute(
        "SELECT * FROM rag_jobs WHERE document_id = ? ORDER BY created_at, rowid", (doc_id,)
    ).fetchall()
    return {
        "document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id)),
        "jobs": [_job_dto(j) for j in jobs],
    }


@router.get("/api/rag/documents/{doc_id}")
def get_document(
    doc_id: str,
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """资料详情：元数据 + 切片数 + 任务列表 + 敏感信息标志 + 台账 + 审核记录。"""
    doc = _get_doc_or_404(conn, doc_id)
    jobs = conn.execute(
        "SELECT * FROM rag_jobs WHERE document_id = ? ORDER BY created_at DESC, rowid DESC",
        (doc_id,),
    ).fetchall()
    ledger = None
    if doc["source_ledger_id"]:
        row = conn.execute(
            "SELECT * FROM source_ledgers WHERE id = ?", (doc["source_ledger_id"],)
        ).fetchone()
        if row is not None:
            ledger = _ledger_dto(conn, row)
    reviews = conn.execute(
        "SELECT * FROM review_records WHERE target_type='rag_document' AND target_id = ?"
        " ORDER BY created_at DESC, rowid DESC",
        (doc_id,),
    ).fetchall()
    return {
        "document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id)),
        "jobs": [_job_dto(j) for j in jobs],
        "sensitive_flags": _latest_parse_flags(conn, doc_id),
        "ledger": ledger,
        "review_records": [
            {
                "id": r["id"],
                "action": r["action"],
                "comment": r["comment"],
                "reviewer_id": r["reviewer_id"],
                "created_at": r["created_at"],
            }
            for r in reviews
        ],
    }


class DocumentPatchBody(BaseModel):
    """资料元数据编辑；chunk_* 属切片参数，变化必须生成新处理版本（PRD-06 §5.2）。"""

    title: str | None = None
    source_type: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    source_ledger_id: str | None = None
    version: str | None = None
    license_status: str | None = None
    visibility: str | None = None
    data_types: list[str] | None = None
    scenario_ids: list[str] | None = None
    cap_ids: list[str] | None = None
    expires_at: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    title_inherit: bool | None = None


@router.patch("/api/rag/documents/{doc_id}")
def patch_document(
    doc_id: str,
    body: DocumentPatchBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """编辑元数据；切片参数变化 → process_version+1 并排期 chunk/index（幂等）。"""
    doc = _get_doc_or_404(conn, doc_id)
    before = _doc_dto(doc)
    updates: dict[str, object] = {}
    if body.title is not None:
        if not body.title.strip():
            raise ApiError(422, "VALIDATION_ERROR", "标题不能为空")
        updates["title"] = body.title.strip()
    if body.source_type is not None:
        if body.source_type not in _SOURCE_TYPES:
            raise ApiError(422, "VALIDATION_ERROR", "来源类型不合法")
        updates["source_type"] = body.source_type
    if body.source_name is not None:
        updates["source_name"] = body.source_name.strip()
    if body.source_url is not None:
        updates["source_url"] = body.source_url
    if body.source_ledger_id is not None:
        updates["source_ledger_id"] = body.source_ledger_id
    if body.version is not None:
        updates["version"] = body.version.strip()
    if body.license_status is not None:
        if body.license_status not in _LICENSE_STATUSES:
            raise ApiError(422, "VALIDATION_ERROR", "授权状态不合法")
        updates["license_status"] = body.license_status
    if body.visibility is not None:
        if body.visibility not in _VISIBILITIES:
            raise ApiError(422, "VALIDATION_ERROR", "可见范围不合法")
        updates["visibility"] = body.visibility
    if body.data_types is not None:
        if any(dt not in _DATA_TYPES for dt in body.data_types):
            raise ApiError(422, "VALIDATION_ERROR", "数据类型不合法")
        updates["data_types_json"] = json.dumps(body.data_types, ensure_ascii=False)
    if body.scenario_ids is not None:
        updates["scenario_ids_json"] = json.dumps(body.scenario_ids, ensure_ascii=False)
    if body.cap_ids is not None:
        updates["cap_ids_json"] = json.dumps(body.cap_ids, ensure_ascii=False)
    if body.expires_at is not None:
        updates["expires_at"] = body.expires_at

    chunk_params = {
        k: v
        for k, v in {
            "chunk_size": body.chunk_size,
            "chunk_overlap": body.chunk_overlap,
            "title_inherit": body.title_inherit,
        }.items()
        if v is not None
    }
    new_jobs: list[str] = []
    if chunk_params:
        # 参数变化生成新处理版本（PRD-06 §5.2），并排期重切/重索引（排队不执行，
        # 由 POST /chunk 或下一次管线触发执行，参数随任务落库不丢失）
        doc = _get_doc_or_404(conn, doc_id)
        new_version = doc["process_version"] + 1
        updates["process_version"] = new_version
        settings = load_settings(conn)
        params = _default_stage_params(settings)
        params["chunk"].update(chunk_params)
        new_jobs = pipeline.enqueue(conn, doc_id, ["chunk", "index"], params, new_version)

    if updates:
        assignments = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE rag_documents SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), utc_now_iso(), doc_id),
        )
        conn.commit()
    doc = _get_doc_or_404(conn, doc_id)
    audit(
        conn,
        current.user,
        "rag.update_document",
        target_type="rag_document",
        target_id=doc_id,
        before=before,
        after=_doc_dto(doc),
        **_client_meta(request),
    )
    return {"document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id)), "jobs": new_jobs}


@router.delete("/api/rag/documents/{doc_id}")
def delete_document(
    doc_id: str,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """删除资料：已发布仅可归档（409）；未发布物理删除 + 审计（PRD-06 §12.2）。"""
    doc = _get_doc_or_404(conn, doc_id)
    if doc["status"] == "published":
        raise ApiError(409, "INVALID_STATE", "已发布资料只能归档，不能物理删除")
    before = _doc_dto(doc)
    for table in ("rag_chunks", "rag_jobs"):
        conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (doc_id,))
    conn.execute(
        "DELETE FROM review_records WHERE target_type='rag_document' AND target_id = ?",
        (doc_id,),
    )
    conn.execute("DELETE FROM rag_documents WHERE id = ?", (doc_id,))
    conn.commit()
    if doc["storage_path"]:
        # 清理上传目录；文件缺失不阻断删除（审计已留痕）
        shutil.rmtree(Path(doc["storage_path"]).parent, ignore_errors=True)
    audit(
        conn,
        current.user,
        "rag.delete_document",
        target_type="rag_document",
        target_id=doc_id,
        before=before,
        **_client_meta(request),
    )
    return {"deleted": True, "id": doc_id}


# ---------------------------------------------------------------- 批量操作（PRD-03 §7）

class BatchBody(BaseModel):
    """批量操作请求：reindex=重建索引 / archive=归档 / submit_review=送审。"""

    ids: list[str]
    action: str


_BATCH_ACTIONS = ("reindex", "archive", "submit_review")
# 单次批量条数上限：reindex 要同步执行管线，防止一次请求长时间拖住 worker
_BATCH_MAX_IDS = 100

# 批量动作 → 审计动作名（沿用蓝图 §3 pending_confirmations 的动作命名）
_BATCH_AUDIT_ACTIONS = {
    "reindex": "rag.reindex_document",
    "archive": "rag.archive_document",
    "submit_review": "rag.submit_review",
}


def _batch_submit_review(conn: sqlite3.Connection, doc: sqlite3.Row, user_id: str) -> tuple[bool, str | None, str | None]:
    """单项送审：守卫与 POST /documents/{id}/submit-review 完全一致，
    区别只在失败收敛为逐项结果而不是整单 4xx（批量场景要求部分成功）。"""
    if not (doc["source_name"] or "").strip():
        return False, REVIEW_REQUIRED, "缺少来源，禁止送审"
    if doc["status"] not in ("indexed", "chunked"):
        return False, "INVALID_STATE", "当前状态不可送审，请先完成解析与索引"
    conn.execute(
        "UPDATE rag_documents SET status='review_pending', updated_at=? WHERE id=?",
        (utc_now_iso(), doc["id"]),
    )
    _add_review_record(conn, doc["id"], user_id, "submit", "批量送审")
    conn.commit()
    return True, None, None


def _batch_archive(conn: sqlite3.Connection, doc: sqlite3.Row, user_id: str) -> tuple[bool, str | None, str | None]:
    """单项归档：守卫与 POST /documents/{id}/archive 一致（仅已归档状态拒绝）。"""
    if doc["status"] == "archived":
        return False, "INVALID_STATE", "资料已处于归档状态"
    before_status = doc["status"]
    conn.execute(
        "UPDATE rag_documents SET status='archived', updated_at=? WHERE id=?",
        (utc_now_iso(), doc["id"]),
    )
    _add_review_record(conn, doc["id"], user_id, "archive", f"归档前状态：{before_status}（批量）")
    conn.commit()
    return True, None, None


def _batch_reindex(conn: sqlite3.Connection, doc: sqlite3.Row) -> tuple[bool, str | None, str | None]:
    """单项重建索引：按当前设置排期 chunk+index 并同步执行（幂等，与重处理端点同语义）。

    排 chunk+index 而非仅 index：索引阶段的产物来自同版本最近一次切片任务，
    设置（chunk_size/表格策略等）变化后只重跑 index 会沿用旧切片；同参数时
    幂等 key 命中既有任务自然成为 no-op，不会无谓重算。
    """
    if doc["status"] == "archived":
        return False, "INVALID_STATE", "已归档资料不可重建索引"
    settings = load_settings(conn)
    pipeline.enqueue(
        conn, doc["id"], ["chunk", "index"], _default_stage_params(settings), doc["process_version"]
    )
    pipeline.run_pending(conn, get_config(), document_id=doc["id"])
    fresh = conn.execute(
        "SELECT status, error_code, error_message FROM rag_documents WHERE id = ?", (doc["id"],)
    ).fetchone()
    if fresh["status"] == "failed":
        return False, fresh["error_code"], fresh["error_message"] or "重建索引失败，请查看任务队列"
    return True, None, None


@router.post("/api/rag/documents/batch")
def batch_documents(
    body: BatchBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """批量操作（PRD-03 §7 验收）：逐条评估与单条端点相同的守卫并同步执行，
    每条写审计；允许部分成功，结果按请求顺序逐项返回。"""
    if body.action not in _BATCH_ACTIONS:
        raise ApiError(422, "VALIDATION_ERROR", "不支持的批量操作，仅支持 reindex / archive / submit_review")
    ids = list(dict.fromkeys(body.ids))  # 去重保序：同一资料重复执行没有意义
    if not ids:
        raise ApiError(422, "VALIDATION_ERROR", "请选择要操作的资料")
    if len(ids) > _BATCH_MAX_IDS:
        raise ApiError(422, "VALIDATION_ERROR", f"单次批量操作最多 {_BATCH_MAX_IDS} 条")

    results: list[dict] = []
    for doc_id in ids:
        doc = conn.execute("SELECT * FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
        if doc is None:
            results.append({"id": doc_id, "ok": False, "code": "NOT_FOUND", "message": "资料不存在"})
            continue
        if body.action == "submit_review":
            ok, code, message = _batch_submit_review(conn, doc, current.user["id"])
        elif body.action == "archive":
            ok, code, message = _batch_archive(conn, doc, current.user["id"])
        else:
            ok, code, message = _batch_reindex(conn, doc)
        # 每条操作无论成败都写审计（NF8：状态变更类操作必须留痕）
        audit(
            conn,
            current.user,
            _BATCH_AUDIT_ACTIONS[body.action],
            target_type="rag_document",
            target_id=doc_id,
            after={"batch": True, "ok": ok, "code": code},
            **_client_meta(request),
        )
        item: dict = {"id": doc_id, "ok": ok}
        if not ok:
            item["code"] = code
            item["message"] = message
        results.append(item)
    return {"results": results}


# ---------------------------------------------------------------- 管线触发（parse/chunk/index）

_STAGE_FROM = {"parse": ["parse", "chunk", "index"], "chunk": ["chunk", "index"], "index": ["index"]}


class ReprocessBody(BaseModel):
    """重处理参数：提供切片参数即生成新处理版本（PRD-06 §5.2 参数变化新规）。"""

    chunk_size: int | None = None
    chunk_overlap: int | None = None
    title_inherit: bool | None = None


def _reprocess(
    doc_id: str,
    stage: str,
    request: Request,
    body: ReprocessBody | None,
    current: CurrentUser,
    conn: sqlite3.Connection,
) -> dict:
    """从指定阶段起排队并同步执行管线（parse→全程；chunk→切片+索引；index→索引）。"""
    doc = _get_doc_or_404(conn, doc_id)
    if stage == "parse" and not doc["storage_path"]:
        raise ApiError(409, "FILE_MISSING", "原始文件不存在，无法重新解析")
    params_override = {
        k: v for k, v in (body.model_dump() if body else {}).items() if v is not None
    }
    version = doc["process_version"]
    if params_override:
        # 参数变化 → 新处理版本（PRD-06 §5.2）。新版本下旧版本的阶段产物
        # （解析块/切片草稿）不应混用，因此整链重跑，保证三阶段产物同版本
        version += 1
        conn.execute(
            "UPDATE rag_documents SET process_version=?, updated_at=? WHERE id=?",
            (version, utc_now_iso(), doc_id),
        )
        conn.commit()
    settings = load_settings(conn)
    params = _default_stage_params(settings)
    params["chunk"].update(params_override)
    stages = list(pipeline.STAGE_ORDER) if params_override else _STAGE_FROM[stage]
    job_ids = pipeline.enqueue(conn, doc_id, stages, params, version)
    summary = pipeline.run_pending(conn, get_config(), document_id=doc_id)
    doc = _get_doc_or_404(conn, doc_id)
    jobs = conn.execute(
        "SELECT * FROM rag_jobs WHERE document_id = ? ORDER BY created_at, rowid", (doc_id,)
    ).fetchall()
    return {
        "document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id)),
        "jobs": [_job_dto(j) for j in jobs],
        "run": summary,
        "enqueued_job_ids": job_ids,
    }


# 三个显式端点而非 `/{stage}` 通配：避免抢占 submit-review/publish 等具名路由
@router.post("/api/rag/documents/{doc_id}/parse")
def reprocess_parse(
    doc_id: str,
    request: Request,
    body: ReprocessBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return _reprocess(doc_id, "parse", request, body, current, conn)


@router.post("/api/rag/documents/{doc_id}/chunk")
def reprocess_chunk(
    doc_id: str,
    request: Request,
    body: ReprocessBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return _reprocess(doc_id, "chunk", request, body, current, conn)


@router.post("/api/rag/documents/{doc_id}/index")
def reprocess_index(
    doc_id: str,
    request: Request,
    body: ReprocessBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return _reprocess(doc_id, "index", request, body, current, conn)


# ---------------------------------------------------------------- 审核流转（submit-review / publish / reject / archive）


@router.get("/api/rag/review-queue")
def list_review_queue(
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """待审核资料列表；归属 RAG 管理域以避免教师 URL 暗示可访问审核能力。"""
    rows = conn.execute(
        """
        SELECT d.id, d.title, d.source_type, d.scenario_ids_json, d.data_types_json,
               d.updated_at AS submitted_at, u.name AS uploader_name
        FROM rag_documents d
        LEFT JOIN users u ON u.id = d.created_by
        WHERE d.status = 'review_pending'
        ORDER BY d.updated_at DESC
        """
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "title": row["title"],
            "uploader_name": row["uploader_name"],
            "source_type": row["source_type"],
            "scenario_ids": json.loads(row["scenario_ids_json"] or "[]"),
            "data_types": json.loads(row["data_types_json"] or "[]"),
            "submitted_at": row["submitted_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}


@router.post("/api/rag/documents/{doc_id}/submit-review")
def submit_review(
    doc_id: str,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """送审：缺来源禁止送审（PRD-06 §4.2）；仅已切片/已索引状态可送审。"""
    doc = _get_doc_or_404(conn, doc_id)
    if not (doc["source_name"] or "").strip():
        raise ApiError(400, REVIEW_REQUIRED, "缺少来源，禁止送审")
    if doc["status"] not in ("indexed", "chunked"):
        raise ApiError(409, "INVALID_STATE", "当前状态不可送审，请先完成解析与索引")
    conn.execute(
        "UPDATE rag_documents SET status='review_pending', updated_at=? WHERE id=?",
        (utc_now_iso(), doc_id),
    )
    _add_review_record(conn, doc_id, current.user["id"], "submit", None)
    conn.commit()
    doc = _get_doc_or_404(conn, doc_id)
    audit(
        conn,
        current.user,
        "rag.submit_review",
        target_type="rag_document",
        target_id=doc_id,
        after={"status": "review_pending"},
        **_client_meta(request),
    )
    return {"document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id))}


class PublishBody(BaseModel):
    """发布范围：student=学生端可召回；teacher=仅教师端（PRD-06 §4.2 发布校验）。"""

    scope: str = "student"


@router.post("/api/rag/documents/{doc_id}/publish")
def publish_document(
    doc_id: str,
    request: Request,
    body: PublishBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """发布：走 PRD-06 §4.2 全部守卫，通过后置 published + 审核记录 + 审计（NF8）。"""
    doc = _get_doc_or_404(conn, doc_id)
    scope = (body.scope if body else "student") or "student"
    if scope not in ("student", "teacher"):
        raise ApiError(422, "VALIDATION_ERROR", "发布范围仅支持 student / teacher")
    if doc["status"] != "review_pending":
        raise ApiError(409, REVIEW_REQUIRED, "资料需要审核后才能发布（当前不在待审核状态）")
    if doc["license_status"] == "forbidden":
        raise ApiError(403, LICENSE_BLOCKED, "资料授权状态为禁止，不允许发布")
    if doc["license_status"] == "pending":
        raise ApiError(403, LICENSE_BLOCKED, "资料授权状态为待确认，请先完成授权确认后再发布")
    # 台账联动：绑定了台账的资料，台账未批准/已过期不得发布（PRD-03 §9 验收标准）
    if doc["source_ledger_id"]:
        ledger = conn.execute(
            "SELECT * FROM source_ledgers WHERE id = ?", (doc["source_ledger_id"],)
        ).fetchone()
        if ledger is not None:
            if ledger["authorization_status"] != "approved":
                raise ApiError(403, LICENSE_BLOCKED, "关联来源台账未获授权批准，不允许发布")
            if ledger["valid_to"] and ledger["valid_to"] < utc_now_iso():
                raise ApiError(403, LICENSE_BLOCKED, "关联来源台账已过有效期，不允许发布")
    if _chunk_count(conn, doc_id) == 0:
        raise ApiError(422, CHUNK_EMPTY, "切片为空，不允许发布，请检查解析文本")
    flags = _latest_parse_flags(conn, doc_id)
    if flags and (flags.get("block_publish") or flags.get("id_card")):
        raise ApiError(403, SENSITIVE_INFO_BLOCKED, "检测到身份证号等敏感信息，需脱敏后才能发布")

    now = utc_now_iso()
    conn.execute(
        "UPDATE rag_documents SET status='published', visibility=?, published_at=?, updated_at=?"
        " WHERE id=?",
        (scope, now, now, doc_id),
    )
    # scope=teacher 时记 approve_teacher_only，学生端不可见但教师端可预览
    _add_review_record(
        conn, doc_id, current.user["id"],
        "approve" if scope == "student" else "approve_teacher_only",
        f"发布范围：{scope}",
    )
    conn.commit()
    doc = _get_doc_or_404(conn, doc_id)
    audit(
        conn,
        current.user,
        "rag.publish_document",
        target_type="rag_document",
        target_id=doc_id,
        after={"status": "published", "visibility": scope},
        **_client_meta(request),
    )
    from .rag_query import emit_telemetry

    emit_telemetry("rag_document_published", {"document_id": doc_id, "scope": scope})
    return {"document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id))}


class RejectBody(BaseModel):
    comment: str | None = None


@router.post("/api/rag/documents/{doc_id}/reject")
def reject_document(
    doc_id: str,
    request: Request,
    body: RejectBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """审核驳回：仅待审核状态可驳回；驳回后不参与召回（PRD-06 §4.2）。"""
    doc = _get_doc_or_404(conn, doc_id)
    if doc["status"] != "review_pending":
        raise ApiError(409, "INVALID_STATE", "仅待审核状态的资料可以驳回")
    comment = (body.comment if body else None) or None
    conn.execute(
        "UPDATE rag_documents SET status='rejected', updated_at=? WHERE id=?",
        (utc_now_iso(), doc_id),
    )
    _add_review_record(conn, doc_id, current.user["id"], "reject", comment)
    conn.commit()
    doc = _get_doc_or_404(conn, doc_id)
    audit(
        conn,
        current.user,
        "rag.reject_document",
        target_type="rag_document",
        target_id=doc_id,
        after={"status": "rejected", "comment": comment},
        **_client_meta(request),
    )
    return {"document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id))}


@router.post("/api/rag/documents/{doc_id}/archive")
def archive_document(
    doc_id: str,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """归档：退出召回但保留切片（历史引用可追溯，PRD-06 §12.2）。"""
    doc = _get_doc_or_404(conn, doc_id)
    if doc["status"] == "archived":
        raise ApiError(409, "INVALID_STATE", "资料已处于归档状态")
    before_status = doc["status"]
    conn.execute(
        "UPDATE rag_documents SET status='archived', updated_at=? WHERE id=?",
        (utc_now_iso(), doc_id),
    )
    _add_review_record(conn, doc_id, current.user["id"], "archive", f"归档前状态：{before_status}")
    conn.commit()
    doc = _get_doc_or_404(conn, doc_id)
    audit(
        conn,
        current.user,
        "rag.archive_document",
        target_type="rag_document",
        target_id=doc_id,
        before={"status": before_status},
        after={"status": "archived"},
        **_client_meta(request),
    )
    return {"document": _doc_dto(doc, chunk_count=_chunk_count(conn, doc_id))}


# ---------------------------------------------------------------- 切片编辑器

@router.get("/api/rag/documents/{doc_id}/chunks")
def list_chunks(
    doc_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """切片列表（分页，按 chunk_index 排序）。"""
    _get_doc_or_404(conn, doc_id)
    total = _chunk_count(conn, doc_id)
    rows = conn.execute(
        "SELECT * FROM rag_chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ? OFFSET ?",
        (doc_id, limit, offset),
    ).fetchall()
    return {"items": [_chunk_dto(r) for r in rows], "total": total}


@router.get("/api/rag/documents/{doc_id}/recall-records")
def list_recall_records(
    doc_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """资料召回记录（资料详情-召回记录）：最近的命中日志，含查询/分数/时间/用户名。

    数据来自学生端问答（student_query）与召回测试台（search_test）写入的
    recall_logs；user_id 允许为空（历史数据/账号已删），用户名 LEFT JOIN 获取。
    """
    _get_doc_or_404(conn, doc_id)
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM recall_logs WHERE document_id = ?", (doc_id,)
    ).fetchone()["n"]
    rows = conn.execute(
        """
        SELECT r.*, u.name AS user_name
        FROM recall_logs r LEFT JOIN users u ON u.id = r.user_id
        WHERE r.document_id = ?
        ORDER BY r.created_at DESC, r.rowid DESC LIMIT ? OFFSET ?
        """,
        (doc_id, limit, offset),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "query": row["query"],
                "score": row["score"],
                "channel": row["channel"],
                "chunk_id": row["chunk_id"],
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "total": total,
    }


def _get_chunk_or_404(conn: sqlite3.Connection, chunk_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM rag_chunks WHERE id = ?", (chunk_id,)).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "切片不存在")
    return row


def _reembed_chunk(conn: sqlite3.Connection, chunk_id: str, content: str) -> None:
    """内容变更后重算 token 数与嵌入（切片编辑"保存即重建索引"的最小实现）。"""
    from ..rag.embeddings import embed_chunks

    blobs, model = embed_chunks(conn, [content])
    conn.execute(
        "UPDATE rag_chunks SET content=?, token_count=?, embedding=?, embedding_model=? WHERE id=?",
        (content, len(content) // 2, blobs[0], model, chunk_id),
    )


def _renumber_chunks(conn: sqlite3.Connection, doc_id: str) -> None:
    """按当前 chunk_index 顺序重排为 0..n-1（拆分/合并后保持索引连续）。"""
    rows = conn.execute(
        "SELECT id FROM rag_chunks WHERE document_id = ? ORDER BY chunk_index, rowid",
        (doc_id,),
    ).fetchall()
    for index, row in enumerate(rows):
        conn.execute("UPDATE rag_chunks SET chunk_index = ? WHERE id = ?", (index, row["id"]))


@router.get("/api/rag/chunks/{chunk_id}")
def get_chunk(
    chunk_id: str,
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return {"chunk": _chunk_dto(_get_chunk_or_404(conn, chunk_id))}


class ChunkPatchBody(BaseModel):
    """切片编辑：改内容会立即重嵌入，保证索引与内容一致。"""

    content: str | None = None
    keywords: list[str] | None = None
    metadata: dict | None = None
    summary: str | None = None


@router.patch("/api/rag/chunks/{chunk_id}")
def patch_chunk(
    chunk_id: str,
    body: ChunkPatchBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    chunk = _get_chunk_or_404(conn, chunk_id)
    before = _chunk_dto(chunk)
    if body.content is not None:
        if not body.content.strip():
            raise ApiError(422, "VALIDATION_ERROR", "切片内容不能为空")
        _reembed_chunk(conn, chunk_id, body.content.strip())
    if body.keywords is not None:
        conn.execute(
            "UPDATE rag_chunks SET keywords_json=? WHERE id=?",
            (json.dumps(body.keywords, ensure_ascii=False), chunk_id),
        )
    if body.metadata is not None:
        conn.execute(
            "UPDATE rag_chunks SET metadata_json=? WHERE id=?",
            (json.dumps(body.metadata, ensure_ascii=False), chunk_id),
        )
    if body.summary is not None:
        conn.execute("UPDATE rag_chunks SET summary=? WHERE id=?", (body.summary, chunk_id))
    conn.commit()
    chunk = _get_chunk_or_404(conn, chunk_id)
    audit(
        conn,
        current.user,
        "rag.update_chunk",
        target_type="rag_chunk",
        target_id=chunk_id,
        before=before,
        after=_chunk_dto(chunk),
        **_client_meta(request),
    )
    return {"chunk": _chunk_dto(chunk)}


class ChunkSplitBody(BaseModel):
    """拆分点：字符偏移；缺省取最靠近中点的句读位置（保证两半都是完整句子）。"""

    at: int | None = None


_SPLIT_ENDS = "。！？!?\n"


@router.post("/api/rag/chunks/{chunk_id}/split")
def split_chunk(
    chunk_id: str,
    request: Request,
    body: ChunkSplitBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    chunk = _get_chunk_or_404(conn, chunk_id)
    content = chunk["content"]
    at = body.at if body and body.at is not None else None
    if at is None:
        mid = len(content) // 2
        # 找离中点最近的句读之后的位置；找不到退化为中点硬切
        candidates = [i + 1 for i, ch in enumerate(content) if ch in _SPLIT_ENDS and 0 < i + 1 < len(content)]
        at = min(candidates, key=lambda i: abs(i - mid)) if candidates else mid
    if at <= 0 or at >= len(content):
        raise ApiError(422, "VALIDATION_ERROR", "拆分点必须位于切片内容内部")
    head, tail = content[:at].strip(), content[at:].strip()
    if not head or not tail:
        raise ApiError(422, "VALIDATION_ERROR", "拆分后存在空片段，请调整拆分点")

    doc_id = chunk["document_id"]
    # 先为后半段腾位：原切片之后的索引整体 +1，再插入新切片，最后统一重排
    conn.execute(
        "UPDATE rag_chunks SET chunk_index = chunk_index + 1 WHERE document_id = ? AND chunk_index > ?",
        (doc_id, chunk["chunk_index"]),
    )
    _reembed_chunk(conn, chunk_id, head)
    new_chunk_id = uuid.uuid4().hex
    from ..rag.embeddings import embed_chunks

    blobs, model = embed_chunks(conn, [tail])
    conn.execute(
        """
        INSERT INTO rag_chunks (id, document_id, chunk_index, content, summary, keywords_json,
          page_start, page_end, section_title, token_count, embedding, embedding_model,
          metadata_json, status, process_version)
        VALUES (?, ?, ?, ?, NULL, '[]', ?, ?, ?, ?, ?, ?, '{}', 'active', ?)
        """,
        (
            new_chunk_id,
            doc_id,
            chunk["chunk_index"] + 1,
            tail,
            chunk["page_start"],
            chunk["page_end"],
            chunk["section_title"],
            len(tail) // 2,
            blobs[0],
            model,
            chunk["process_version"],
        ),
    )
    _renumber_chunks(conn, doc_id)
    conn.commit()
    audit(
        conn,
        current.user,
        "rag.split_chunk",
        target_type="rag_chunk",
        target_id=chunk_id,
        after={"new_chunk_id": new_chunk_id, "at": at},
        **_client_meta(request),
    )
    return {"chunks": [_chunk_dto(_get_chunk_or_404(conn, chunk_id)), _chunk_dto(_get_chunk_or_404(conn, new_chunk_id))]}


class ChunkMergeBody(BaseModel):
    """合并：同一文档内 ≥2 个切片，按 chunk_index 顺序拼接进首个切片。"""

    chunk_ids: list[str]


@router.post("/api/rag/chunks/merge")
def merge_chunks(
    body: ChunkMergeBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    if len(body.chunk_ids) < 2:
        raise ApiError(422, "VALIDATION_ERROR", "合并至少需要两个切片")
    chunks = [_get_chunk_or_404(conn, cid) for cid in dict.fromkeys(body.chunk_ids)]
    doc_ids = {c["document_id"] for c in chunks}
    if len(doc_ids) != 1:
        raise ApiError(422, "VALIDATION_ERROR", "仅支持合并同一文档内的切片")
    chunks.sort(key=lambda c: c["chunk_index"])
    merged = "\n\n".join(c["content"] for c in chunks)
    keeper = chunks[0]
    _reembed_chunk(conn, keeper["id"], merged)
    # 页码范围覆盖被合并的所有切片
    pages = [p for c in chunks for p in (c["page_start"], c["page_end"]) if p is not None]
    if pages:
        conn.execute(
            "UPDATE rag_chunks SET page_start=?, page_end=? WHERE id=?",
            (min(pages), max(pages), keeper["id"]),
        )
    for chunk in chunks[1:]:
        conn.execute("DELETE FROM rag_chunks WHERE id = ?", (chunk["id"],))
    _renumber_chunks(conn, keeper["document_id"])
    conn.commit()
    audit(
        conn,
        current.user,
        "rag.merge_chunks",
        target_type="rag_chunk",
        target_id=keeper["id"],
        after={"merged_chunk_ids": body.chunk_ids},
        **_client_meta(request),
    )
    return {"chunk": _chunk_dto(_get_chunk_or_404(conn, keeper["id"]))}


# ---------------------------------------------------------------- 任务队列

@router.get("/api/rag/jobs")
def list_jobs(
    status: str | None = None,
    document_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """任务队列查询（PRD-03 §7）：按状态/文档过滤 + 分页。"""
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if document_id:
        clauses.append("document_id = ?")
        params.append(document_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM rag_jobs {where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM rag_jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return {"items": [_job_dto(r) for r in rows], "total": total}


@router.post("/api/rag/jobs/{job_id}/retry")
def retry_job_endpoint(
    job_id: str,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """重试：从失败阶段继续，不重复已成功阶段（PRD-06 §5.2）。"""
    try:
        summary = pipeline.retry_job(conn, get_config(), job_id)
    except RAGError as exc:
        raise to_api_error(exc, status_code=409) from exc
    job = conn.execute("SELECT * FROM rag_jobs WHERE id = ?", (job_id,)).fetchone()
    audit(
        conn,
        current.user,
        "rag.retry_job",
        target_type="rag_job",
        target_id=job_id,
        after=summary,
        **_client_meta(request),
    )
    return {"run": summary, "job": _job_dto(job) if job else None}


# ---------------------------------------------------------------- 召回测试台

class SearchTestFilters(BaseModel):
    scenario_id: str | None = None
    data_type: str | None = None
    published_only: bool = True
    document_ids: list[str] | None = None


class SearchTestBody(BaseModel):
    """召回测试台输入（PRD-03 §10）；save=true 时把本次问题存为评测用例。"""

    query: str
    filters: SearchTestFilters = SearchTestFilters()
    top_k: int | None = None
    save: bool = False
    expected_answer: str | None = None
    must_hit_document_ids: list[str] = []
    must_hit_chunk_ids: list[str] = []


def _hit_debug_dict(hit) -> dict:
    """测试台命中 DTO：管理端调试态展示 chunk_id 与分数（学生端不展示）。"""
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "title": hit.title,
        "section_title": hit.section_title,
        "page_start": hit.page_start,
        "page_end": hit.page_end,
        "version": hit.version,
        "content": hit.content,
        "score": hit.score,
        "rerank_score": hit.rerank_score,
    }


@router.post("/api/rag/search-test")
def search_test(
    body: SearchTestBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """召回测试：返回向量序与重排序两路结果 + 诊断信息（PRD-03 §10 验收）。"""
    query = body.query.strip()
    if not query:
        raise ApiError(422, "VALIDATION_ERROR", "查询不能为空")
    filters = RagFilters(
        scenario_id=body.filters.scenario_id,
        data_type=body.filters.data_type,
        published_only=body.filters.published_only,
        document_ids=body.filters.document_ids,
    )
    result = retrieve(conn, get_config(), query, filters, top_k=body.top_k)
    # 向量序 = 按 score 重排（rerank 未跑时本来就是这个顺序）
    vector_order = sorted(result.hits, key=lambda h: h.score, reverse=True)
    reranked = any(h.rerank_score is not None for h in result.hits)
    rerank_note = None if reranked else "未启用重排，与向量结果一致"

    hit_chunk_ids = [h.chunk_id for h in result.hits]
    embedding_model: str | None = None
    if hit_chunk_ids:
        placeholders = ",".join("?" for _ in hit_chunk_ids)
        models = [
            r["embedding_model"]
            for r in conn.execute(
                f"SELECT DISTINCT embedding_model FROM rag_chunks WHERE id IN ({placeholders})",
                hit_chunk_ids,
            )
        ]
        embedding_model = ", ".join(m for m in models if m)
    rerank_model: str | None = result.rerank_model if reranked else None

    # 召回记录（渠道 search_test）：资料详情页"召回记录"的数据来源之一；
    # 写库失败不影响测试台主流程（record_recall_logs 内部已兜底）
    record_recall_logs(
        conn,
        query=query,
        user_id=current.user["id"],
        channel="search_test",
        hits=[
            {"document_id": h.document_id, "chunk_id": h.chunk_id, "score": h.score}
            for h in result.hits
        ],
    )

    settings = load_settings(conn)
    response: dict = {
        "vector_results": [_hit_debug_dict(h) for h in vector_order],
        "reranked_results": [_hit_debug_dict(h) for h in result.hits],
        "rerank_note": rerank_note,
        "below_threshold": result.below_threshold,
        "notice": result.notice,
        "diagnostics": {
            "latency_ms": result.latency_ms,
            "embedding_model": embedding_model,
            "rerank_model": rerank_model,
            "filters": body.filters.model_dump(),
            "prompt_template_version": settings.prompt_template_version,
        },
    }
    if body.save:
        # 存为评测用例是写操作（蓝图 §9 rag.save_eval_case），落库 + 审计
        case_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO eval_cases (id, question, expected_answer, must_hit_document_ids_json,
              must_hit_chunk_ids_json, filters_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                query,
                body.expected_answer,
                json.dumps(body.must_hit_document_ids, ensure_ascii=False),
                json.dumps(body.must_hit_chunk_ids, ensure_ascii=False),
                json.dumps(body.filters.model_dump(), ensure_ascii=False),
                current.user["id"],
                utc_now_iso(),
            ),
        )
        conn.commit()
        audit(
            conn,
            current.user,
            "rag.save_eval_case",
            target_type="eval_case",
            target_id=case_id,
            after={"question": query},
            **_client_meta(request),
        )
        response["saved_case_id"] = case_id
    return response


# ---------------------------------------------------------------- 评测集与评测运行

@router.get("/api/rag/eval-cases")
def list_eval_cases(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    total = conn.execute("SELECT COUNT(*) AS n FROM eval_cases").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM eval_cases ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return {"items": [_eval_case_dto(r) for r in rows], "total": total}


def _eval_case_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "question": row["question"],
        "expected_answer": row["expected_answer"],
        "must_hit_document_ids": _json_list(row["must_hit_document_ids_json"]),
        "must_hit_chunk_ids": _json_list(row["must_hit_chunk_ids_json"]),
        "filters": json.loads(row["filters_json"] or "{}"),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


class EvalCaseBody(BaseModel):
    question: str
    expected_answer: str | None = None
    must_hit_document_ids: list[str] = []
    must_hit_chunk_ids: list[str] = []
    filters: dict = {}


@router.post("/api/rag/eval-cases", status_code=201)
def create_eval_case(
    body: EvalCaseBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not body.question.strip():
        raise ApiError(422, "VALIDATION_ERROR", "问题不能为空")
    case_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO eval_cases (id, question, expected_answer, must_hit_document_ids_json,
          must_hit_chunk_ids_json, filters_json, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            body.question.strip(),
            body.expected_answer,
            json.dumps(body.must_hit_document_ids, ensure_ascii=False),
            json.dumps(body.must_hit_chunk_ids, ensure_ascii=False),
            json.dumps(body.filters, ensure_ascii=False),
            current.user["id"],
            utc_now_iso(),
        ),
    )
    conn.commit()
    audit(
        conn,
        current.user,
        "rag.save_eval_case",
        target_type="eval_case",
        target_id=case_id,
        after={"question": body.question.strip()},
        **_client_meta(request),
    )
    row = conn.execute("SELECT * FROM eval_cases WHERE id = ?", (case_id,)).fetchone()
    return {"case": _eval_case_dto(row)}


class EvalRunBody(BaseModel):
    """评测运行：不给 case_ids 即跑全部用例。"""

    case_ids: list[str] | None = None


def _eval_recall_hit(case: sqlite3.Row, hits) -> bool | None:
    """Recall@K：必须命中的文档/切片全部出现在 TopK 内；无必须命中项则不参与该指标。"""
    must_docs = set(_json_list(case["must_hit_document_ids_json"]))
    must_chunks = set(_json_list(case["must_hit_chunk_ids_json"]))
    if not must_docs and not must_chunks:
        return None
    hit_docs = {h.document_id for h in hits}
    hit_chunks = {h.chunk_id for h in hits}
    return must_docs <= hit_docs and must_chunks <= hit_chunks


def _citation_ok(case: sqlite3.Row, answer, retrieved_doc_ids: set[str]) -> bool | None:
    """引用准确性（启发式）：未拒答时引用非空、均来自本次召回，且覆盖必须命中文档。

    为什么只能是启发式：引用"是否支持答案中的每个论断"需要语义判断，MVP 用
    来源一致性 + 必中覆盖近似，结果仅供趋势对比（PRD-03 §11）。
    """
    if answer.refused:
        return None
    if not answer.citations:
        return False
    cited_docs = {c["document_id"] for c in answer.citations}
    if not cited_docs <= retrieved_doc_ids:
        return False
    must_docs = set(_json_list(case["must_hit_document_ids_json"]))
    return not must_docs or bool(cited_docs & must_docs)


def _faithfulness(answer, hits) -> float | None:
    """答案忠实度（启发式）：答案 CJK bigram 被命中内容覆盖的比例。

    模板答案是命中内容的截取，该值趋近 1；LLM 合成答案偏离资料时该值下降，
    可用于发现"跑题/编造"趋势。token 级精确判断留待后续接入评测模型。
    """
    if answer.refused:
        return None
    answer_grams = _cjk_bigrams(answer.answer)
    if not answer_grams:
        return None
    evidence_grams: set[str] = set()
    for hit in hits:
        evidence_grams |= _cjk_bigrams(hit.content)
    return round(len(answer_grams & evidence_grams) / len(answer_grams), 4)


@router.post("/api/rag/eval-runs", status_code=201)
def run_eval(
    request: Request,
    body: EvalRunBody | None = None,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """跑评测：Recall@K / CitationAccuracy / RefusalAccuracy / Faithfulness / Latency。"""
    if body and body.case_ids:
        placeholders = ",".join("?" for _ in body.case_ids)
        cases = conn.execute(
            f"SELECT * FROM eval_cases WHERE id IN ({placeholders})", body.case_ids
        ).fetchall()
    else:
        cases = conn.execute("SELECT * FROM eval_cases ORDER BY created_at, rowid").fetchall()
    if not cases:
        raise ApiError(422, "VALIDATION_ERROR", "没有可运行的评测用例")

    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO eval_runs (id, status, created_by, created_at) VALUES (?, 'running', ?, ?)",
        (run_id, current.user["id"], utc_now_iso()),
    )
    conn.commit()

    config = get_config()
    case_results: list[dict] = []
    recall_values: list[bool] = []
    citation_values: list[bool] = []
    refusal_values: list[bool] = []
    faith_values: list[float] = []
    latencies: list[int] = []
    for case in cases:
        raw_filters = json.loads(case["filters_json"] or "{}")
        filters = RagFilters(
            scenario_id=raw_filters.get("scenario_id"),
            data_type=raw_filters.get("data_type"),
            published_only=raw_filters.get("published_only", True),
            document_ids=raw_filters.get("document_ids"),
        )
        started = time.perf_counter()
        result = retrieve(conn, config, case["question"], filters)
        answer = answer_question(
            conn,
            config,
            case["question"],
            scenario_id=filters.scenario_id,
            data_type=filters.data_type,
            published_only=filters.published_only,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        latencies.append(latency_ms)

        must_empty = not _json_list(case["must_hit_document_ids_json"]) and not _json_list(
            case["must_hit_chunk_ids_json"]
        )
        recall_hit = _eval_recall_hit(case, result.hits)
        if recall_hit is not None:
            recall_values.append(recall_hit)
        # 无必须命中项的用例期望拒答（PRD-03 §11 Refusal Accuracy）
        refusal_ok = (answer.refused is True) if must_empty else None
        if refusal_ok is not None:
            refusal_values.append(refusal_ok)
        retrieved_doc_ids = {h.document_id for h in result.hits}
        citation_ok = _citation_ok(case, answer, retrieved_doc_ids)
        if citation_ok is not None:
            citation_values.append(citation_ok)
        faith = _faithfulness(answer, result.hits)
        if faith is not None:
            faith_values.append(faith)

        case_results.append(
            {
                "case_id": case["id"],
                "question": case["question"],
                "refused": answer.refused,
                "hit_document_ids": sorted(retrieved_doc_ids),
                "hit_chunk_ids": [h.chunk_id for h in result.hits],
                "recall_hit": recall_hit,
                "citation_ok": citation_ok,
                "refusal_ok": refusal_ok,
                "faithfulness": faith,
                "latency_ms": latency_ms,
            }
        )

    def _mean(values: list) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    metrics = {
        "recall_at_k": _mean([1.0 if v else 0.0 for v in recall_values]),
        "citation_accuracy": _mean([1.0 if v else 0.0 for v in citation_values]),
        "refusal_accuracy": _mean([1.0 if v else 0.0 for v in refusal_values]),
        "answer_faithfulness": _mean(faith_values),
        "latency_ms_avg": _mean([float(v) for v in latencies]),
        "case_count": len(cases),
    }
    conn.execute(
        "UPDATE eval_runs SET status='completed', metrics_json=?, case_results_json=?, finished_at=?"
        " WHERE id=?",
        (
            json.dumps(metrics, ensure_ascii=False),
            json.dumps(case_results, ensure_ascii=False),
            utc_now_iso(),
            run_id,
        ),
    )
    conn.commit()
    audit(
        conn,
        current.user,
        "rag.run_eval",
        target_type="eval_run",
        target_id=run_id,
        after=metrics,
        **_client_meta(request),
    )
    from .rag_query import emit_telemetry

    emit_telemetry("rag_eval_run_completed", {"run_id": run_id, "case_count": len(cases)})
    return {"id": run_id, "status": "completed", "metrics": metrics, "case_results": case_results}


@router.get("/api/rag/eval-runs")
def list_eval_runs(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """评测历史列表（最新在前）：前端评测页历史面板的数据源，
    取代此前 localStorage 的临时方案；列表不携带 case_results（体积大，详情端点提供）。"""
    total = conn.execute("SELECT COUNT(*) AS n FROM eval_runs").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM eval_runs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "status": row["status"],
                "metrics": json.loads(row["metrics_json"] or "null"),
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ],
        "total": total,
    }


@router.get("/api/rag/eval-runs/{run_id}")
def get_eval_run(
    run_id: str,
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "评测运行不存在")
    return {
        "id": row["id"],
        "status": row["status"],
        "metrics": json.loads(row["metrics_json"] or "null"),
        "case_results": json.loads(row["case_results_json"] or "[]"),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


# ---------------------------------------------------------------- 来源台账

def _ledger_dto(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """台账 DTO + 风险提示（PRD-03 §9：过期/未授权/缺引用位置）。"""
    now = utc_now_iso()
    linked = _json_list(row["related_document_ids_json"])
    doc_linked = conn.execute(
        "SELECT COUNT(*) AS n FROM rag_documents WHERE source_ledger_id = ?", (row["id"],)
    ).fetchone()["n"]
    return {
        "id": row["id"],
        "source_code": row["source_code"],
        "name": row["name"],
        "publisher": row["publisher"],
        "source_type": row["source_type"],
        "version": row["version"],
        "authorization_status": row["authorization_status"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "related_document_ids": linked,
        "review_status": row["review_status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "risk_expired": bool(row["valid_to"] and row["valid_to"] < now),
        "risk_unauthorized": row["authorization_status"] != "approved",
        "risk_no_documents": not linked and doc_linked == 0,
    }


@router.get("/api/source-ledgers")
def list_ledgers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(rag_staff),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    total = conn.execute("SELECT COUNT(*) AS n FROM source_ledgers").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM source_ledgers ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return {"items": [_ledger_dto(conn, r) for r in rows], "total": total}


class LedgerBody(BaseModel):
    source_code: str
    name: str
    publisher: str | None = None
    source_type: str | None = None
    version: str | None = None
    authorization_status: str = "pending"
    valid_from: str | None = None
    valid_to: str | None = None
    notes: str | None = None


_LEDGER_AUTH_STATUSES = ("approved", "pending", "expired", "forbidden")


@router.post("/api/source-ledgers", status_code=201)
def create_ledger(
    body: LedgerBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not body.source_code.strip() or not body.name.strip():
        raise ApiError(422, "VALIDATION_ERROR", "台账编号与来源名称不能为空")
    if body.authorization_status not in _LEDGER_AUTH_STATUSES:
        raise ApiError(422, "VALIDATION_ERROR", "授权状态不合法")
    exists = conn.execute(
        "SELECT id FROM source_ledgers WHERE source_code = ?", (body.source_code.strip(),)
    ).fetchone()
    if exists:
        raise ApiError(409, "DUPLICATE", "台账编号已存在")
    ledger_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO source_ledgers (id, source_code, name, publisher, source_type, version,
          authorization_status, valid_from, valid_to, related_document_ids_json,
          review_status, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'draft', ?, ?, ?)
        """,
        (
            ledger_id,
            body.source_code.strip(),
            body.name.strip(),
            body.publisher,
            body.source_type,
            body.version,
            body.authorization_status,
            body.valid_from,
            body.valid_to,
            body.notes,
            now,
            now,
        ),
    )
    conn.commit()
    audit(
        conn,
        current.user,
        "rag.create_ledger",
        target_type="source_ledger",
        target_id=ledger_id,
        after={"source_code": body.source_code.strip()},
        **_client_meta(request),
    )
    row = conn.execute("SELECT * FROM source_ledgers WHERE id = ?", (ledger_id,)).fetchone()
    return {"ledger": _ledger_dto(conn, row)}


class LedgerPatchBody(BaseModel):
    name: str | None = None
    publisher: str | None = None
    source_type: str | None = None
    version: str | None = None
    authorization_status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    review_status: str | None = None
    notes: str | None = None


@router.patch("/api/source-ledgers/{ledger_id}")
def patch_ledger(
    ledger_id: str,
    body: LedgerPatchBody,
    request: Request,
    current: CurrentUser = Depends(rag_staff_mutation),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    row = conn.execute("SELECT * FROM source_ledgers WHERE id = ?", (ledger_id,)).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "台账不存在")
    before = _ledger_dto(conn, row)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "authorization_status" in updates and updates["authorization_status"] not in _LEDGER_AUTH_STATUSES:
        raise ApiError(422, "VALIDATION_ERROR", "授权状态不合法")
    if "review_status" in updates and updates["review_status"] not in ("draft", "reviewed", "published"):
        raise ApiError(422, "VALIDATION_ERROR", "审核状态不合法")
    if updates:
        assignments = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE source_ledgers SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), utc_now_iso(), ledger_id),
        )
        conn.commit()
    row = conn.execute("SELECT * FROM source_ledgers WHERE id = ?", (ledger_id,)).fetchone()
    audit(
        conn,
        current.user,
        "rag.update_ledger",
        target_type="source_ledger",
        target_id=ledger_id,
        before=before,
        after=_ledger_dto(conn, row),
        **_client_meta(request),
    )
    return {"ledger": _ledger_dto(conn, row)}
