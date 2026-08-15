"""诊断引擎编排层：detect → parse → precheck → rules → 归因 → 补强计划 → 报告 DTO。

Pinned 公开契约（任务契约，签名不可改）：
- class DiagnosticError(Exception)  # .code .message（实际定义在 detect.py，此处 re-export）
- def diagnose(file_bytes, filename, *, data_type=None, cite_fn=None) -> dict

关键决策（为什么）：
- mastery_preview 只算 delta、不带 old/new：engine 是**无 db、无用户**的纯函数
  （原文件不落盘 NF3 的前提），old_score 需要用户数据，由 router 层拿到报告后
  调 mastery.service.preview_from_deltas 补齐——公式仍来自 mastery 单点。
- graphx / 教学单元全部 lazy + 容错：诊断是离线优先能力，图谱文件缺失时
  降级为"无名称/无路径/无资源"，绝不让诊断主流程 500。
- cite_fn 由 router 注入（接 RAG 召回），None 时不附引用——PRD-06 §9.2：
  无召回依据时不生成专业规范解释。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..config import get_config
from ..mastery import service as mastery_service
from . import parsers
from .detect import (
    FORMAT_COCO,
    FORMAT_GENERIC_JSON,
    FORMAT_TEXTGRID,
    FORMAT_VOC,
    DiagnosticError,
    detect_format,
)
from .rules import COVERED_DATA_TYPES, run_rules

__all__ = ["DiagnosticError", "diagnose", "load_teaching_units"]

_PARSERS = {
    FORMAT_TEXTGRID: parsers.parse_textgrid,
    FORMAT_COCO: parsers.parse_coco,
    FORMAT_VOC: parsers.parse_voc,
    FORMAT_GENERIC_JSON: parsers.parse_generic_json,
}

# 进程内小缓存：教学单元是只读内容文件，避免每份诊断重复读盘
_units_cache: list[dict] | None = None


def _data_dir() -> Path:
    return Path(get_config().resolved_data_dir)


def load_teaching_units() -> list[dict]:
    """加载 data/curriculum/teaching-units.json 的 units 列表（进程内缓存）。"""
    global _units_cache
    if _units_cache is not None:
        return _units_cache
    path = _data_dir() / "curriculum" / "teaching-units.json"
    units: list[dict] = []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        units = body.get("units", []) if isinstance(body, dict) else body
    except (json.JSONDecodeError, OSError):
        units = []
    _units_cache = units
    return units


def _cap_names() -> dict[str, str]:
    """cap_id → 中文名；图谱不可用时降级为空映射（报告仍给 cap_id）。"""
    try:
        from ..graphx import reason

        return {
            n["id"]: n.get("name") or n["id"]
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "CAP"
        }
    except Exception:
        return {}


def _build_plan(weak_cap_ids: list[str], data_type: str | None) -> dict:
    """补强计划：薄弱能力（带名）+ PRE 路径 + 推荐资源 + 推荐练习标题。

    graphx 调用全部 try/except——蓝图 §11 要求诊断离线可跑，图谱缺失时
    pre_path 降级为空列表而不是让报告失败。
    """
    names = _cap_names()
    weak_caps = [
        {"cap_id": cap_id, "cap_name": names.get(cap_id, cap_id)} for cap_id in weak_cap_ids
    ]

    # PRE 路径：各薄弱cap的前置链按序合并去重（每条链内部已是基础在前）
    pre_path: list[str] = []
    cap_data_types: dict[str, list[str]] = {}
    try:
        from ..graphx import reason

        cap_data_types = {
            n["id"]: n.get("data_types") or []
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "CAP"
        }
        for cap_id in weak_cap_ids:
            for nid in reason.pre_path(cap_id):
                if nid not in pre_path:
                    pre_path.append(nid)
    except Exception:
        pre_path = []

    # 推荐资源：教学单元按"能力键匹配 weak cap + 数据类型过滤"打分，取前 5
    def _cap_slug(cap_id: str) -> str:
        # CAP-AUD-SEGMENT-ALIGN-001 → segment_align（去掉域前缀与序号后缀）
        parts = cap_id.split("-")
        core = parts[1:-1] if len(parts) > 2 else parts
        return "_".join(core).lower()

    def _unit_score(unit: dict) -> int:
        score = 0
        key = str(unit.get("capability_key") or "").lower()
        for cap_id in weak_cap_ids:
            slug = _cap_slug(cap_id)
            if key and (slug == key or slug.startswith(key) or key.startswith(slug)):
                score = max(score, 2)
            elif cap_id in (unit.get("prerequisites") or []):
                score = max(score, 1)
            elif unit.get("data_type") and unit["data_type"] in cap_data_types.get(cap_id, []):
                score = max(score, 1)
        return score

    wanted_type = data_type if data_type in ("text", "image", "audio", "video") else None
    candidates = [
        (u, _unit_score(u))
        for u in load_teaching_units()
        if _unit_score(u) > 0 and (wanted_type is None or u.get("data_type") == wanted_type)
    ]
    candidates.sort(key=lambda pair: (-pair[1], pair[0].get("id", "")))
    resources = [
        {
            "type": "teaching_unit",
            "unit_id": unit["id"],
            "title": unit.get("title", unit["id"]),
            "data_type": unit.get("data_type"),
        }
        for unit, _score in candidates[:5]
    ]

    # 推荐练习标题：每个薄弱能力一条专项练习 + 每条匹配单元一条案例练习
    tasks = [f"「{wc['cap_name']}」专项纠错练习" for wc in weak_caps]
    tasks.extend(f"案例练习：{unit.get('title', unit['id'])}" for unit, _ in candidates[:3])
    return {
        "weak_caps": weak_caps,
        "pre_path": pre_path,
        "resources": resources,
        "tasks": tasks,
    }


def _attach_citations(errors: list[dict], cite_fn: Callable[[list[str]], list[dict]] | None) -> None:
    """经 cite_fn 为每条错误的规则召回依据（就地写 error['citation']）。

    约定 cite_fn(rule_texts) 返回 [{"rule": 规则名, "citations": [CitationDTO...]}]；
    形状不符或调用失败时整体跳过——引用是增强信息，失败不应影响诊断主结果
    （PRD-06 §9.2：无召回依据时只展示结构化错误）。
    """
    if cite_fn is None or not errors:
        return
    rule_texts = sorted({e["rule"] for e in errors})
    try:
        results = cite_fn(rule_texts) or []
    except Exception:
        return
    by_rule: dict[str, Any] = {}
    for item in results:
        if isinstance(item, dict) and item.get("rule"):
            by_rule[str(item["rule"])] = item.get("citations", item.get("citation"))
    for error in errors:
        citations = by_rule.get(error["rule"])
        if citations:
            error["citation"] = citations


def diagnose(
    file_bytes: bytes,
    filename: str,
    *,
    data_type: str | None = None,
    cite_fn: Callable[[list[str]], list[dict]] | None = None,
) -> dict:
    """对上传的标注文件做确定性诊断，返回 DiagnosticReportDTO（蓝图 §6.3）。

    纯内存处理，原文件绝不落盘（NF3）。PARSE_FAILED / FIELDS_MISSING 以
    DiagnosticError 抛出（由 router 翻译成 HTTP 错误，不进入评分）。
    """
    file_format = detect_format(file_bytes, filename)
    text = file_bytes.decode("utf-8")
    doc = _PARSERS[file_format](text)

    notices: list[str] = list(doc.get("warnings") or [])

    # Runtime rules are scoped only by data type; graph metadata is not a filter.
    errors = run_rules(doc, data_type=data_type, source_format=file_format)

    # 规则库未覆盖的任务类型：不扣分 + notice（PRD-06 §9.2）
    if data_type and data_type not in COVERED_DATA_TYPES:
        notices.append(f"当前规则库暂未覆盖数据类型「{data_type}」，本次诊断不扣分")
        errors = []

    # 错误归因：cap_id → 中文名（图谱降级时退回 cap_id）
    names = _cap_names()
    for error in errors:
        error["cap_name"] = names.get(error["cap_id"], error["cap_id"])

    _attach_citations(errors, cite_fn)

    severity_counts = {
        "major": sum(1 for e in errors if e["severity"] == "major"),
        "minor": sum(1 for e in errors if e["severity"] == "minor"),
    }
    # 薄弱能力：优先 major 错误的 cap；无 major 才取 minor（扣分主导原则）
    major_caps = [e["cap_id"] for e in errors if e["severity"] == "major"]
    minor_caps = [e["cap_id"] for e in errors if e["severity"] == "minor"]
    weak_cap_ids = list(dict.fromkeys(major_caps or minor_caps))

    # 掌握度预览：只给 delta（engine 无 db）；old/new 由 router 调 mastery 补齐
    deltas = mastery_service.diagnostic_deltas(errors)
    mastery_preview = [
        {**item, "old_score": None, "new_score": None} for item in deltas
    ]

    return {
        "file_format": file_format,
        "sample_count": len(doc["spans"]) + len(doc["boxes"]),
        "precheck": {"fields": doc.get("fields", []), "warnings": doc.get("warnings", [])},
        "errors": errors,
        "severity_counts": severity_counts,
        "weak_cap_ids": weak_cap_ids,
        "mastery_preview": mastery_preview,
        "plan": _build_plan(weak_cap_ids, data_type),
        "notice": "；".join(notices) if notices else None,
    }
