"""RAG 管理类写工具（全部 write + 确认门 + 审计，蓝图 §9）。

仅服务系统管理员经 Agent 管理资料；其他角色在 handler 内直接中文拒绝
（服务端逐点校验是 PRD-04 §5.1 的要求，不能只靠前端正守卫）。

实现取舍（为什么用直接 SQL 而不是调 rag.pipeline）：
这些工具只负责"状态机迁移 + 审计 + review_records"，与 rag_admin 路由的
守卫保持最小镜像（如 publish 要求 review_pending）；重建索引等重活以
rag_jobs 队列行表达（幂等 key），由 B2 管线消费——B2 缺席时工具返回
"RAG 模块未就绪"，不产生半截状态。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

from ..audit import audit
from ..db import utc_now_iso
from .registry import ToolContext, ToolSpec

logger = logging.getLogger(__name__)

_RAG_NOT_READY = "RAG 模块未就绪，暂时无法执行资料管理操作"
_FORBIDDEN_ROLE = "只有系统管理员可以执行资料管理操作"
# Agent calls bypass HTTP routing, so this must mirror the RAG route boundary.
_ALLOWED_ROLES = ("system_admin",)


def _role_denied(ctx: ToolContext) -> dict[str, Any] | None:
    role = ctx.user_row["role"] if ctx.user_row is not None else None
    if role not in _ALLOWED_ROLES:
        return {"error": _FORBIDDEN_ROLE}
    return None


def _doc_row(ctx: ToolContext, document_id: str) -> sqlite3.Row | None:
    try:
        return ctx.db.execute(
            "SELECT * FROM rag_documents WHERE id = ?", (document_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        # rag 表不存在（005 未应用 / B2 未就绪）——比裸栈更可读的中文错误
        return None


def _get_doc_or_error(ctx: ToolContext) -> tuple[sqlite3.Row | None, dict | None]:
    document_id = ctx.args.get("document_id") or ""
    if not document_id:
        return None, {"error": "缺少 document_id"}
    doc = _doc_row(ctx, document_id)
    if doc is None:
        return None, {"error": _RAG_NOT_READY + "，或资料不存在"}
    return doc, None


# ---------------------------------------------------------------------------
# rag.create_document
# ---------------------------------------------------------------------------

def create_document_preview(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    args = ctx.args
    return {
        "action": "rag.create_document",
        "summary": f"将创建资料草稿「{args.get('title', '未命名资料')}」",
        "document": {
            "title": args.get("title"),
            "source_type": args.get("source_type") or "other",
            "source_name": args.get("source_name") or "",
            "data_types": args.get("data_types") or [],
            "visibility": args.get("visibility") or "teacher",
        },
    }


def create_document_apply(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    args = ctx.args
    if not args.get("title"):
        return {"error": "缺少资料标题"}
    doc_id = uuid.uuid4().hex
    now = utc_now_iso()
    import json

    try:
        ctx.db.execute(
            """
            INSERT INTO rag_documents
              (id, title, file_type, source_type, source_name, version,
               license_status, data_types_json, visibility,
               status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, 'draft', ?, ?, ?)
            """,
            (
                doc_id,
                args["title"],
                args.get("file_type") or "other",
                args.get("source_type") or "other",
                args.get("source_name") or "Agent 创建",
                args.get("version") or "v1",
                json.dumps(args.get("data_types") or [], ensure_ascii=False),
                args.get("visibility") or "teacher",
                ctx.user_row["id"],
                now,
                now,
            ),
        )
    except sqlite3.OperationalError:
        return {"error": _RAG_NOT_READY}
    audit(ctx.db, ctx.user_row, "rag.create_document", "rag_document", doc_id,
          after={"title": args["title"]})
    ctx.db.commit()
    return {"document_id": doc_id, "title": args["title"], "status": "draft"}


# ---------------------------------------------------------------------------
# rag.reindex_document
# ---------------------------------------------------------------------------

def reindex_document_preview(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err
    return {
        "action": "rag.reindex_document",
        "summary": f"将为资料「{doc['title']}」重建向量索引（当前状态：{doc['status']}）",
        "document_id": doc["id"],
    }


def reindex_document_apply(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err

    job_id = uuid.uuid4().hex
    now = utc_now_iso()
    try:
        # 幂等 key（PRD-06 §5.2）：同一资料同一处理版本只排一次索引任务
        idem = f"reindex:{doc['id']}:v{doc['process_version']}"
        existing = ctx.db.execute(
            "SELECT id, status FROM rag_jobs WHERE idempotency_key = ?", (idem,)
        ).fetchone()
        if existing and existing["status"] in ("queued", "running"):
            return {"job_id": existing["id"], "status": existing["status"],
                    "deduplicated": True}
        ctx.db.execute(
            """
            INSERT INTO rag_jobs
              (id, document_id, stage, status, idempotency_key, params_json, created_at)
            VALUES (?, ?, 'index', 'queued', ?, '{}', ?)
            """,
            (job_id, doc["id"], idem, now),
        )
        ctx.db.execute(
            "UPDATE rag_documents SET status = 'indexing', updated_at = ? WHERE id = ?",
            (now, doc["id"]),
        )
    except sqlite3.OperationalError:
        return {"error": _RAG_NOT_READY}
    audit(ctx.db, ctx.user_row, "rag.reindex_document", "rag_document", doc["id"],
          before={"status": doc["status"]}, after={"status": "indexing"})
    ctx.db.commit()
    return {"job_id": job_id, "document_id": doc["id"], "status": "queued"}


# ---------------------------------------------------------------------------
# rag.publish_document
# ---------------------------------------------------------------------------

def publish_document_preview(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err
    return {
        "action": "rag.publish_document",
        "summary": (
            f"将发布资料「{doc['title']}」（版本 {doc['version']}，"
            f"可见范围 {doc['visibility']}）"
        ),
        "document_id": doc["id"],
    }


def publish_document_apply(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err
    # 与 rag_admin 守卫的最小镜像（PRD-06 §5.3 错误码）
    if doc["license_status"] == "forbidden":
        return {"error": "资料授权状态不允许发布（LICENSE_BLOCKED）"}
    if doc["status"] != "review_pending":
        return {"error": "资料需要审核后才能发布（REVIEW_REQUIRED）"}
    now = utc_now_iso()
    ctx.db.execute(
        "UPDATE rag_documents SET status = 'published', published_at = ?, "
        "updated_at = ? WHERE id = ?",
        (now, now, doc["id"]),
    )
    ctx.db.execute(
        """
        INSERT INTO review_records (id, target_type, target_id, reviewer_id, action, created_at)
        VALUES (?, 'rag_document', ?, ?, 'publish', ?)
        """,
        (uuid.uuid4().hex, doc["id"], ctx.user_row["id"], now),
    )
    audit(ctx.db, ctx.user_row, "rag.publish_document", "rag_document", doc["id"],
          before={"status": doc["status"]}, after={"status": "published"})
    ctx.db.commit()
    return {"document_id": doc["id"], "status": "published"}


# ---------------------------------------------------------------------------
# rag.archive_document
# ---------------------------------------------------------------------------

def archive_document_preview(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err
    return {
        "action": "rag.archive_document",
        "summary": (
            f"将归档资料「{doc['title']}」：归档后学生端不再召回，"
            "历史引用保留快照"
        ),
        "document_id": doc["id"],
    }


def archive_document_apply(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    doc, err = _get_doc_or_error(ctx)
    if err:
        return err
    if doc["status"] != "published":
        return {"error": "仅已发布资料可归档"}
    now = utc_now_iso()
    ctx.db.execute(
        "UPDATE rag_documents SET status = 'archived', updated_at = ? WHERE id = ?",
        (now, doc["id"]),
    )
    ctx.db.execute(
        """
        INSERT INTO review_records (id, target_type, target_id, reviewer_id, action, created_at)
        VALUES (?, 'rag_document', ?, ?, 'archive', ?)
        """,
        (uuid.uuid4().hex, doc["id"], ctx.user_row["id"], now),
    )
    audit(ctx.db, ctx.user_row, "rag.archive_document", "rag_document", doc["id"],
          before={"status": doc["status"]}, after={"status": "archived"})
    ctx.db.commit()
    return {"document_id": doc["id"], "status": "archived"}


# ---------------------------------------------------------------------------
# rag.save_eval_case
# ---------------------------------------------------------------------------

def save_eval_case_preview(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    question = ctx.args.get("question") or ""
    if not question:
        return {"error": "缺少评测问题 question"}
    return {
        "action": "rag.save_eval_case",
        "summary": f"将保存评测问题：{question[:50]}",
        "case": {
            "question": question,
            "expected_answer": ctx.args.get("expected_answer"),
            "filters": ctx.args.get("filters") or {},
        },
    }


def save_eval_case_apply(ctx: ToolContext) -> dict[str, Any]:
    denied = _role_denied(ctx)
    if denied:
        return denied
    import json

    args = ctx.args
    if not args.get("question"):
        return {"error": "缺少评测问题 question"}
    case_id = uuid.uuid4().hex
    try:
        ctx.db.execute(
            """
            INSERT INTO eval_cases
              (id, question, expected_answer, must_hit_document_ids_json,
               must_hit_chunk_ids_json, filters_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                args["question"],
                args.get("expected_answer"),
                json.dumps(args.get("must_hit_document_ids") or [], ensure_ascii=False),
                json.dumps(args.get("must_hit_chunk_ids") or [], ensure_ascii=False),
                json.dumps(args.get("filters") or {}, ensure_ascii=False),
                ctx.user_row["id"],
                utc_now_iso(),
            ),
        )
    except sqlite3.OperationalError:
        return {"error": _RAG_NOT_READY}
    audit(ctx.db, ctx.user_row, "rag.save_eval_case", "eval_case", case_id,
          after={"question": args["question"]})
    ctx.db.commit()
    return {"case_id": case_id}


CREATE_DOCUMENT_SPEC = ToolSpec(
    name="rag.create_document", permission="write", auto_execute=False,
    description="系统管理员经 Agent 创建资料草稿",
    preview=create_document_preview, apply=create_document_apply,
)
REINDEX_DOCUMENT_SPEC = ToolSpec(
    name="rag.reindex_document", permission="write", auto_execute=False,
    description="确认后重建资料向量索引（幂等 rag_jobs）",
    preview=reindex_document_preview, apply=reindex_document_apply,
)
PUBLISH_DOCUMENT_SPEC = ToolSpec(
    name="rag.publish_document", permission="write", auto_execute=False,
    description="确认后发布资料（需 review_pending，写 review_records + 审计）",
    preview=publish_document_preview, apply=publish_document_apply,
)
ARCHIVE_DOCUMENT_SPEC = ToolSpec(
    name="rag.archive_document", permission="write", auto_execute=False,
    description="确认后归档资料（仅已发布；10 分钟确认门）",
    preview=archive_document_preview, apply=archive_document_apply,
)
SAVE_EVAL_CASE_SPEC = ToolSpec(
    name="rag.save_eval_case", permission="write", auto_execute=False,
    description="确认后保存 RAG 评测问题",
    preview=save_eval_case_preview, apply=save_eval_case_apply,
)
