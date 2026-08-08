"""标注诊断路由（蓝图 §6.3）：上传诊断 → 数据库缓存报告 → 确认后存摘要 + 掌握度生效。

关键决策（为什么）：
- 报告缓存落 diagnostic_cache 表（008 迁移）：原进程内 dict 在多实例部署/进程
  重启后全部失效，用户确认时只剩"已过期"。DB 化后缓存在实例间共享、重启不丢；
  缓存语义不变——报告只存活 30 分钟（确认门窗口），过期行在读取/写入时惰性删除，
  不需要后台清扫线程。上传原文件仍绝不落盘（NF3/PRD-06 §12.1 只允许摘要），
  表里只有报告 JSON。
- get_cached_report 是模块级公开函数：Agent 工具域 diagnostic.save_summary
  直接 import 它读缓存，不经过 HTTP；它自行开库连接（无 conn 参数），
  签名自内存缓存时代起保持不变。
- rag.retriever 一律函数内 lazy import：B2 域并行开发，缺席时引用召回
  整体降级（cite_fn=None，PRD-06 §9.2 无召回不生成专业解释）。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel

from .. import db as db_module
from ..config import get_config
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db, require_student_portal_user
from ..diagnosis.engine import DiagnosticError, diagnose
from ..errors import ApiError
from ..mastery import service as mastery_service

# Diagnostics persist a learner's report and mastery state; teachers use the
# separate class-scoped read APIs instead of this personal workflow.
router = APIRouter(dependencies=[Depends(require_student_portal_user)])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # PRD-06 §9.1：单文件 ≤20MB
REPORT_TTL_MINUTES = 30  # 确认门 30min（蓝图 §6.3）；过期后读取即清，语义同原内存缓存


def _cache_conn() -> sqlite3.Connection:
    """缓存读写的独立连接：get_cached_report 没有 conn 参数（签名契约），自行开库。"""
    return db_module.connect(get_config().resolved_database_path)


def get_cached_report(token: str) -> dict | None:
    """读取缓存的诊断报告（含 user_id/report/expires_at）；不存在或已过期返回 None。

    过期条目在读取时顺手删除（惰性淘汰，不需要后台清扫线程）。
    """
    conn = _cache_conn()
    try:
        row = conn.execute(
            "SELECT * FROM diagnostic_cache WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= utc_now_iso():
            conn.execute("DELETE FROM diagnostic_cache WHERE token = ?", (token,))
            conn.commit()
            return None
        return {
            "report": json.loads(row["report_json"]),
            "user_id": row["user_id"],
            "expires_at": row["expires_at"],
        }
    finally:
        conn.close()


def _store_report(report: dict, user_id: str) -> str:
    """写入缓存并返回 token；写前顺手清一轮过期行，避免缓存表无界增长。"""
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=REPORT_TTL_MINUTES)).isoformat()
    token = secrets.token_urlsafe(24)
    conn = _cache_conn()
    try:
        conn.execute("DELETE FROM diagnostic_cache WHERE expires_at <= ?", (utc_now_iso(),))
        conn.execute(
            """
            INSERT INTO diagnostic_cache (token, user_id, report_json, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, user_id, json.dumps(report, ensure_ascii=False), expires_at, utc_now_iso()),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def _evict_report(token: str) -> None:
    conn = _cache_conn()
    try:
        conn.execute("DELETE FROM diagnostic_cache WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def _require_verified(current: CurrentUser) -> None:
    """诊断属核心能力，走邮箱验证门（PRD-06 §3.2）；csrf_protect 只验会话不验邮箱。"""
    if current.user["email_verified_at"] is None:
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "请先完成邮箱验证后再使用此功能")


def _track(conn: sqlite3.Connection, user_id: str | None, name: str, props: dict) -> None:
    """埋点：优先走 B1 的 telemetry 模块；缺席时直接写 analytics_events 兜底。

    为什么兜底直写：analytics_events 表结构在迁移 004 里是固定契约，埋点
    不应因 telemetry 模块未就绪而丢失；任何异常都吞掉——埋点失败绝不能
    影响业务主流程。
    """
    try:
        try:
            from .. import telemetry  # type: ignore

            track = (
                getattr(telemetry, "emit_event", None)
                or getattr(telemetry, "track", None)
                or getattr(telemetry, "track_event", None)
            )
            if track is not None:
                # emit_event(db, user_id, name, props) 为 B1 当前接口；全位置参数调用
                track(conn, user_id, name, props)
                return
        except ImportError:
            pass
        conn.execute(
            "INSERT INTO analytics_events (user_id, event_name, props_json, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, json.dumps(props, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    except Exception:
        pass


def _build_cite_fn(
    conn: sqlite3.Connection, scenario_id: str | None, data_type: str | None
):
    """组装 RAG 引用召回函数（question=规则中文名，published_only 学生口径）。

    rag.retriever 由 B2 域实现：当前接口为 retrieve(db, config, query,
    RagFilters) → RetrievalResult(hits=[RagHit])。接线做全量防御——模块缺席 /
    接口漂移 / 单条召回异常都降级为"无引用"，绝不影响诊断主流程
    （PRD-06 §9.2：无召回依据时只展示结构化错误）。
    """
    try:
        from ..rag import retriever  # type: ignore
    except ImportError:
        return None
    retrieve = getattr(retriever, "retrieve", None)
    filters_cls = getattr(retriever, "RagFilters", None)
    if retrieve is None or filters_cls is None:
        return None

    def cite(rule_texts: list[str]) -> list[dict]:
        from ..config import get_config

        results: list[dict] = []
        for rule in rule_texts:
            try:
                filters = filters_cls(
                    scenario_id=scenario_id, data_type=data_type, published_only=True
                )
                outcome = retrieve(conn, get_config(), rule, filters)
                hits = getattr(outcome, "hits", None) or []
                # 映射为 CitationDTO 形状（蓝图 §6.4：学生端不含 chunk_id/上传人）
                citations = [
                    {
                        "document_id": getattr(hit, "document_id", None),
                        "title": getattr(hit, "title", None),
                        "section_title": getattr(hit, "section_title", None),
                        "page_start": getattr(hit, "page_start", None),
                        "page_end": getattr(hit, "page_end", None),
                        "version": getattr(hit, "version", None),
                        "score": getattr(hit, "score", None),
                    }
                    for hit in hits[:3]  # 每条规则最多 3 条引用，避免报告膨胀
                ]
            except Exception:
                continue  # 单条召回失败不拖垮其余规则
            if citations:
                results.append({"rule": rule, "citations": citations})
        return results

    return cite


class SaveSummaryBody(BaseModel):
    diagnostic_token: str


@router.post("/api/diagnostics")
def upload_diagnostic(
    file: UploadFile = File(...),
    data_type: str | None = Form(None),
    scenario_id: str | None = Form(None),
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """上传标注文件 → 确定性诊断报告 + diagnostic_token（原文件不落盘，NF3）。

    为什么是同步 def 而不是 async def：get_db 在线程池创建 sqlite 连接，
    sqlite3 默认 check_same_thread=True；async 端点体会跑在事件循环线程，
    跨线程用连接直接 ProgrammingError。同步端点与依赖在同一线程池链路执行，
    文件读取走 UploadFile.file（Starlette 的同步 SpooledTemporaryFile）。
    """
    _require_verified(current)
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "文件超过 20MB 上限，请拆分或压缩后再上传")
    try:
        report = diagnose(
            content,
            file.filename or "upload",
            data_type=data_type or None,
            scenario_id=scenario_id or None,
            cite_fn=_build_cite_fn(conn, scenario_id or None, data_type or None),
        )
    except DiagnosticError as exc:
        status = 422 if exc.code == "FIELDS_MISSING" else 400
        raise ApiError(status, exc.code, exc.message) from exc

    # engine 报告不含请求上下文，落缓存前补上（save-summary 入库要用）
    report["data_type"] = data_type or None
    report["scenario_id"] = scenario_id or None

    # engine 无 db 只算出 delta；这里用真实用户数据补齐 old/new 预览（预览即所得）
    deltas = [
        {"cap_id": p["cap_id"], "scenario_id": p["scenario_id"], "delta": p["delta"]}
        for p in report["mastery_preview"]
    ]
    report["mastery_preview"] = mastery_service.preview_from_deltas(
        conn, current.user["id"], deltas
    )

    token = _store_report(report, current.user["id"])
    _track(
        conn,
        current.user["id"],
        "diagnostic_uploaded",
        {
            "file_format": report["file_format"],
            "error_count": len(report["errors"]),
            "data_type": data_type,
            "scenario_id": scenario_id,
        },
    )
    return {**report, "diagnostic_token": token}


@router.post("/api/diagnostics/save-summary")
def save_summary(
    body: SaveSummaryBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """确认门动作（蓝图 §6.3）：存诊断摘要 + 掌握度预览生效（source='diagnostic'）。"""
    _require_verified(current)
    entry = get_cached_report(body.diagnostic_token)
    if entry is None:
        # 区分"从未存在/别人的"与"已过期"：过期给 410（确认门口径 §6.2）
        raise ApiError(410, "DIAGNOSTIC_TOKEN_EXPIRED", "诊断结果已过期，请重新上传诊断")
    if entry["user_id"] != current.user["id"]:
        # 不暴露他人 token 的存在性，统一按无效处理
        raise ApiError(403, "FORBIDDEN", "该诊断结果不属于当前账号")

    report = entry["report"]
    summary_id = uuid.uuid4().hex
    severity_counts = report["severity_counts"]
    conn.execute(
        """
        INSERT INTO diagnostic_summaries
          (id, user_id, file_format, data_type, scenario_id, error_count,
           severity_counts_json, report_json, weak_cap_ids_json, plan_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary_id,
            current.user["id"],
            report["file_format"],
            report.get("data_type"),
            report.get("scenario_id"),
            len(report["errors"]),
            json.dumps(severity_counts, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False),
            json.dumps(report["weak_cap_ids"], ensure_ascii=False),
            json.dumps(report["plan"], ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    # 掌握度生效：用缓存报告里的 delta（与上传时展示的预览同源同公式）
    deltas = [
        {"cap_id": p["cap_id"], "scenario_id": p["scenario_id"], "delta": p["delta"]}
        for p in report["mastery_preview"]
    ]
    applied = mastery_service.apply_updates(
        conn, current.user["id"], deltas, source="diagnostic", ref_id=summary_id
    )
    _evict_report(body.diagnostic_token)  # 一次性确认：生效后 token 作废
    _track(conn, current.user["id"], "diagnostic_summary_saved", {"summary_id": summary_id})
    if applied:
        _track(
            conn,
            current.user["id"],
            "mastery_updated",
            {"source": "diagnostic", "cap_count": len(applied)},
        )
    return {"summary_id": summary_id, "mastery_applied": applied}


@router.get("/api/diagnostics/summaries")
def list_summaries(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """本人历史诊断摘要（分页；列表不含完整报告，保持轻量）。"""
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM diagnostic_summaries WHERE user_id = ?",
        (current.user["id"],),
    ).fetchone()["n"]
    rows = conn.execute(
        """
        SELECT id, file_format, data_type, scenario_id, error_count,
               severity_counts_json, weak_cap_ids_json, created_at
        FROM diagnostic_summaries
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (current.user["id"], limit, offset),
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "file_format": row["file_format"],
            "data_type": row["data_type"],
            "scenario_id": row["scenario_id"],
            "error_count": row["error_count"],
            "severity_counts": json.loads(row["severity_counts_json"]),
            "weak_cap_ids": json.loads(row["weak_cap_ids_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": total}
