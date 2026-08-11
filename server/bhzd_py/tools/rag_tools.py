"""rag.search / rag.answer / rag.preview_upload（均 read，自动执行）（蓝图 §9）。

rag.answer 的合成策略（任务书决策，记录为什么）：
工具 handler 是同步函数，而 LLM 合成是 async（B1 providers）。在同步
handler 里 `asyncio.run` 套 LLM 既脆弱（嵌套事件循环）又难测，因此
rag.answer 工具固定以 composer=None 调用 B2（模板合成模式），最终回答
若需 LLM 润色，由**编排器**在生成 assistant 消息时统一重写——
LLM 只润色表达，引用与事实仍全部来自工具结果。
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

from ..agent import events
from .registry import ToolContext, ToolSpec

_RAG_NOT_READY = "知识库模块未就绪，暂时无法检索资料"

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # PRD：上传 ≤20MB
_ALLOWED_EXTENSIONS = {"pdf", "docx", "md", "txt", "xlsx", "csv"}
# 敏感信息检测（PRD-06 §4.3 预检）：手机号 / 身份证 / 邮箱
_SENSITIVE_PATTERNS = {
    "手机号": re.compile(r"1[3-9]\d{9}"),
    "身份证号": re.compile(r"\d{17}[\dXx]"),
    "邮箱": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def _retriever():
    try:
        from ..rag import retriever  # B2，惰性导入
    except ImportError:
        return None
    return retriever


def _to_jsonable(value: Any) -> Any:
    """把 B2 的返回对象（dataclass / 对象 / dict）转成 JSON 可序列化结构。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {k: _to_jsonable(v) for k, v in vars(value).items()}
    return value


def rag_search_handler(ctx: ToolContext) -> dict[str, Any]:
    retriever = _retriever()
    if retriever is None:
        return {"error": _RAG_NOT_READY}
    args = ctx.args
    run_id = ctx.run_row["id"] if ctx.run_row is not None else None
    # 召回事件挂在当前 run 上，前端执行轨迹可展示召回耗时（蓝图 §7）
    # Retrieval-start events are replayed to the browser, so never persist the
    # user's query merely to signal work has begun.
    if run_id:
        events.emit(ctx.db, run_id, events.RAG_RETRIEVAL_STARTED, {})
    # 编排器传的是 plain dict（蓝图契约允许），B2 的 retrieve 需要 RagFilters 实例，
    # 在此做边界归一化，未知键静默忽略（编排器可能多传 top_k 等）
    raw_filters = args.get("filters")
    if raw_filters is None:
        raw_filters = {}
        if args.get("scenario_id"):
            raw_filters["scenario_id"] = args["scenario_id"]
        if args.get("data_type"):
            raw_filters["data_type"] = args["data_type"]
    if isinstance(raw_filters, dict):
        known = {"scenario_id", "data_type", "published_only", "document_ids"}
        filters = retriever.RagFilters(
            **{k: v for k, v in raw_filters.items() if k in known}
        )
    else:
        filters = raw_filters  # 已是 RagFilters（测试/内部调用）
    result = retriever.retrieve(
        ctx.db,
        ctx.config,
        args.get("query") or "",
        filters,
        top_k=args.get("top_k"),
    )
    hits = _to_jsonable(getattr(result, "hits", result))
    hit_count = len(hits) if isinstance(hits, list) else 0
    latency_ms = getattr(result, "latency_ms", None)
    # Preserve a non-negative numeric SSE field when an adapter cannot report timing.
    safe_latency_ms = (
        latency_ms
        if isinstance(latency_ms, (int, float))
        and not isinstance(latency_ms, bool)
        and latency_ms >= 0
        else 0
    )
    if run_id:
        events.emit(ctx.db, run_id, events.RAG_RETRIEVAL_COMPLETED,
                    {"hit_count": hit_count, "latency_ms": safe_latency_ms})
    return {
        "hits": hits,
        "hit_count": hit_count,
        "latency_ms": safe_latency_ms,
        "below_threshold": bool(getattr(result, "below_threshold", False)),
    }


def rag_answer_handler(ctx: ToolContext) -> dict[str, Any]:
    retriever = _retriever()
    if retriever is None:
        return {"error": _RAG_NOT_READY}
    args = ctx.args
    # composer=None：模板合成（见模块 docstring）；LLM 润色由编排器负责
    answer = retriever.answer_question(
        ctx.db,
        ctx.config,
        args.get("question") or "",
        scenario_id=args.get("scenario_id"),
        data_type=args.get("data_type"),
        published_only=bool(args.get("published_only", True)),
        document_ids=args.get("document_ids"),
        composer=None,
    )
    payload = _to_jsonable(answer)
    if not isinstance(payload, dict):
        payload = {"answer": str(payload)}
    return payload


def rag_preview_upload_handler(ctx: ToolContext) -> dict[str, Any]:
    """上传预检：类型 / 大小（≤20MB）/ 敏感信息提示（PRD-06 §4.3）。"""
    args = ctx.args
    filename = args.get("filename") or ""
    size_bytes = int(args.get("size_bytes") or 0)
    text_excerpt = args.get("text_excerpt") or ""

    ext = Path(filename).suffix.lstrip(".").lower()
    warnings: list[str] = []
    ok = True
    if ext not in _ALLOWED_EXTENSIONS:
        ok = False
        warnings.append("文件格式暂不支持，请上传 PDF、Word 或 Markdown 等格式")
    if size_bytes <= 0:
        ok = False
        warnings.append("文件大小异常，请重新选择文件")
    elif size_bytes > _MAX_UPLOAD_BYTES:
        ok = False
        warnings.append("文件超过 20MB 上限，请拆分或压缩后再上传")

    sensitive_hints: list[str] = []
    if text_excerpt:
        for label, pattern in _SENSITIVE_PATTERNS.items():
            if pattern.search(text_excerpt):
                sensitive_hints.append(f"检测到疑似{label}，请脱敏后再上传")
        if sensitive_hints:
            warnings.extend(sensitive_hints)

    return {
        "ok": ok,
        "filename": filename,
        "file_type": ext or None,
        "size_bytes": size_bytes,
        "size_ok": 0 < size_bytes <= _MAX_UPLOAD_BYTES,
        "sensitive_hints": sensitive_hints,
        "warnings": warnings,
    }


SEARCH_SPEC = ToolSpec(
    name="rag.search",
    permission="read",
    auto_execute=True,
    description="按问题与元数据过滤召回知识库切片（附 rag.retrieval.* 事件）",
    handler=rag_search_handler,
)

ANSWER_SPEC = ToolSpec(
    name="rag.answer",
    permission="read",
    auto_execute=True,
    description="基于召回证据生成答案（模板合成；LLM 润色由编排器统一处理）",
    handler=rag_answer_handler,
)

PREVIEW_UPLOAD_SPEC = ToolSpec(
    name="rag.preview_upload",
    permission="read",
    auto_execute=True,
    description="上传预检：类型/大小/敏感信息检测",
    handler=rag_preview_upload_handler,
)
