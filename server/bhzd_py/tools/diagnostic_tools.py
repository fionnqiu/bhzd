"""diagnostic.preview（read）与 diagnostic.save_summary（write，确认门）（蓝图 §9）。

原文件不持久化（NF3/PRD-06 §12.1）：诊断报告只存在于 B4 路由的
30 分钟内存缓存里，经 diagnostic_token 引用；确认保存时仅落摘要行。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from ..db import utc_now_iso
from .registry import ToolContext, ToolSpec, emit_telemetry

logger = logging.getLogger(__name__)

_TOKEN_EXPIRED = "诊断结果已过期，请重新上传诊断文件"
_DIAGNOSIS_NOT_READY = "诊断模块未就绪，请稍后再试"


def _get_cached_report(token: str) -> dict[str, Any] | None:
    """惰性调 B4 诊断路由的内存缓存；模块缺席视同未就绪。"""
    try:
        from ..routers import diagnostics  # B4，惰性导入
    except ImportError:
        return None
    try:
        return diagnostics.get_cached_report(token)
    except Exception:
        logger.warning("读取诊断缓存失败", exc_info=True)
        return None


def _diagnosis_ready() -> bool:
    try:
        from ..routers import diagnostics
    except ImportError:
        return False
    # Referencing the imported module keeps this readiness probe explicit for
    # static analysis while preserving the intended lazy-import behavior.
    return diagnostics is not None


def diagnostic_preview_handler(ctx: ToolContext) -> dict[str, Any]:
    token = ctx.args.get("diagnostic_token") or ""
    if not _diagnosis_ready():
        return {"error": _DIAGNOSIS_NOT_READY}
    report = _get_cached_report(token)
    if report is None:
        return {"error": _TOKEN_EXPIRED}
    return {"report": report}


def _summary_payload(report: dict[str, Any]) -> dict[str, Any]:
    """从诊断报告提取确认门预览需要的最小摘要（错误数/薄弱能力/掌握度预览）。"""
    return {
        "error_count": report.get("error_count")
        or (report.get("severity_counts") or {}).get("total")
        or len(report.get("errors") or []),
        "file_format": report.get("file_format"),
        "data_type": report.get("data_type"),
        "severity_counts": report.get("severity_counts") or {},
        "weak_cap_ids": report.get("weak_cap_ids") or [],
        "mastery_preview": report.get("mastery_preview") or [],
    }


def save_summary_preview(ctx: ToolContext) -> dict[str, Any]:
    token = ctx.args.get("diagnostic_token") or ""
    if not _diagnosis_ready():
        return {"error": _DIAGNOSIS_NOT_READY}
    report = _get_cached_report(token)
    if report is None:
        return {"error": _TOKEN_EXPIRED}
    summary = _summary_payload(report)
    return {
        "action": "diagnostic.save_summary",
        "summary": (
            f"将保存诊断摘要（{summary['error_count']} 个问题）并更新掌握度"
        ),
        "diagnostic": summary,
    }


def save_summary_apply(ctx: ToolContext) -> dict[str, Any]:
    token = ctx.args.get("diagnostic_token") or ""
    report = _get_cached_report(token)
    if report is None:
        return {"error": _TOKEN_EXPIRED}
    summary = _summary_payload(report)
    summary_id = uuid.uuid4().hex
    ctx.db.execute(
        """
        INSERT INTO diagnostic_summaries
            (id, user_id, file_format, data_type, error_count,
           severity_counts_json, report_json, weak_cap_ids_json, plan_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary_id,
            ctx.user_row["id"],
            summary.get("file_format") or "unknown",
            summary.get("data_type"),
            int(summary.get("error_count") or 0),
            json.dumps(summary.get("severity_counts") or {}, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False, default=str),
            json.dumps(summary.get("weak_cap_ids") or [], ensure_ascii=False),
            json.dumps(report.get("plan"), ensure_ascii=False, default=str)
            if report.get("plan") is not None
            else None,
            utc_now_iso(),
        ),
    )
    ctx.db.commit()

    # 掌握度更新走 B4 mastery.service（诊断来源，ref 指回摘要行）；
    # 该域缺席时摘要仍已保存，掌握度更新降级为跳过并记日志。
    mastery_updates = summary.get("mastery_preview") or []
    applied = 0
    if mastery_updates:
        try:
            from ..mastery import service as mastery_service  # B4，惰性导入
        except ImportError:
            mastery_service = None
        if mastery_service is not None:
            mastery_service.apply_updates(
                ctx.db,
                ctx.user_row["id"],
                mastery_updates,
                source="diagnostic",
                ref_id=summary_id,
            )
            applied = len(mastery_updates)
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "diagnostic_summary_saved",
        {"summary_id": summary_id, "error_count": summary.get("error_count")},
    )
    return {
        "summary_id": summary_id,
        "error_count": summary.get("error_count"),
        "mastery_applied": applied,
    }


PREVIEW_SPEC = ToolSpec(
    name="diagnostic.preview",
    permission="read",
    auto_execute=True,
    description="按 diagnostic_token 读取诊断报告（原文件不持久化）",
    handler=diagnostic_preview_handler,
)

SAVE_SUMMARY_SPEC = ToolSpec(
    name="diagnostic.save_summary",
    permission="write",
    auto_execute=False,
    description="确认后保存诊断摘要并触发掌握度更新",
    preview=save_summary_preview,
    apply=save_summary_apply,
)
