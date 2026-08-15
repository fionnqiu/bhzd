"""course.search（read，自动执行）：检索教学单元（蓝图 §9）。

数据源 `data/curriculum/teaching-units.json` 不入库（蓝图 §13.3），
这里按文件 mtime 做进程内缓存（内存索引）。

数据现实与取舍（为什么 cap_ids/est_minutes 需要推导）：
- 单元没有"教授能力"显式字段，只有 prerequisites 与 rule_refs；
  cap_ids 取单元 JSON 全文里出现的所有 CAP-* 引用（确定性、来自数据本身）。
- 单元没有时长字段，est_minutes 用 goals/objectives 数量做确定性启发式
  估算，仅作展示参考。
- 图谱关系仅作为能力元数据保留；课程检索只按单元自身的数据类型、能力
  引用和关键词筛选，不再按已撤销的业务上下文过滤。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .registry import ToolContext, ToolSpec

logger = logging.getLogger(__name__)

_CAP_ID_RE = re.compile(r"CAP-[A-Z0-9-]+-\d+")

# (mtime, 单元列表) 进程内缓存
_units_cache: tuple[float, list[dict]] | None = None


def _load_units(data_dir: str) -> list[dict]:
    global _units_cache
    path = Path(data_dir) / "curriculum" / "teaching-units.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _units_cache and _units_cache[0] == mtime:
        return _units_cache[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("教学单元文件不可读: %s", path, exc_info=True)
        return []
    units = payload.get("units", payload if isinstance(payload, list) else [])
    _units_cache = (mtime, units)
    return units


def _unit_cap_ids(unit: dict) -> list[str]:
    """单元全文中出现的 CAP id（去重保序）——数据未提供显式教授能力字段。"""
    seen: list[str] = []
    for match in _CAP_ID_RE.findall(json.dumps(unit, ensure_ascii=False)):
        if match not in seen:
            seen.append(match)
    return seen


def _est_minutes(unit: dict) -> int:
    """确定性时长启发式：单元数据无 duration 字段，按目标/要点数量估算。"""
    goals = len(unit.get("goals") or [])
    objectives = len(unit.get("learning_objectives") or [])
    return min(15 + 10 * goals + 5 * objectives, 120)


def course_search_handler(ctx: ToolContext) -> dict[str, Any]:
    args = ctx.args
    data_dir = ctx.config.resolved_data_dir
    units = _load_units(data_dir)

    data_type = args.get("data_type")
    cap_ids = set(args.get("cap_ids") or [])
    query = (args.get("query") or "").strip()

    results: list[dict[str, Any]] = []
    for unit in units:
        if unit.get("student_visible") is False:
            continue
        if data_type and unit.get("data_type") != data_type:
            continue
        unit_caps = set(_unit_cap_ids(unit))
        if cap_ids and not (unit_caps & cap_ids):
            continue
        if query:
            haystack = " ".join(
                [
                    str(unit.get("title", "")),
                    " ".join(map(str, unit.get("goals") or [])),
                    " ".join(map(str, unit.get("learning_objectives") or [])),
                ]
            )
            if query not in haystack:
                continue
        results.append(
            {
                "unit_id": unit.get("id"),
                "title": unit.get("title"),
                "modality": unit.get("data_type"),
                "est_minutes": _est_minutes(unit),
                "cap_ids": sorted(unit_caps),
            }
        )
        if len(results) >= 8:  # 契约：top 8
            break
    return {"units": results, "total": len(results)}


SPEC = ToolSpec(
    name="course.search",
    permission="read",
    auto_execute=True,
    description="检索已发布教学单元（按数据类型/能力/关键词过滤，top 8）",
    handler=course_search_handler,
)
