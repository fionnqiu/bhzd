"""能力图谱路由（蓝图 §6.3，PRD-01 §5）：全图/搜索/详情/子图/PRE 补强路径。

关键决策（为什么）：
- 图谱是只读内容数据，登录可选：未登录给纯图，登录后叠加本人掌握状态
  （PRD-01 §5.1 节点抽屉要展示掌握度；v3.0 §7.3.3 配色口径 mastered/weak/beginner）。
- 全部计算走 graphx 内存推理，166 节点规模下远低于 500ms 预算（PRD-01 §5.2）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..deps import CurrentUser, get_current_user, get_db
from ..diagnosis.engine import load_teaching_units
from ..errors import ApiError
from ..graphx import reason
from ..mastery.service import MASTERED_THRESHOLD

router = APIRouter()

WEAK_LINE = 0.4  # 图谱页"待加强"线（v3.0 §7.3.3：橙描边阈值）


def _optional_user(request: Request, conn: sqlite3.Connection) -> CurrentUser | None:
    """可选登录：有有效会话返回 CurrentUser，没有/失效返回 None（不抛 401）。"""
    try:
        return get_current_user(request, conn)
    except ApiError:
        return None


def _mastery_map(conn: sqlite3.Connection, user_id: str) -> dict[str, float]:
    """通用（scenario=''）掌握度映射；图谱总览按通用视图着色（§8.4 口径）。"""
    rows = conn.execute(
        "SELECT cap_id, score FROM mastery WHERE user_id = ? AND scenario_id = ''",
        (user_id,),
    ).fetchall()
    return {row["cap_id"]: float(row["score"]) for row in rows}


def _status_of(score: float | None) -> str:
    if score is None:
        return "beginner"
    if score >= MASTERED_THRESHOLD:
        return "mastered"
    if score < WEAK_LINE:
        return "weak"
    return "beginner"


def _available_learning_materials(detail: dict[str, Any]) -> list[dict[str, str]]:
    """Project a CAP's consumable teaching units without treating graph RES nodes as materials.

    Graph task nodes are a curriculum catalogue, while a learning task needs an
    actual student-visible teaching unit.  Require both the reviewed graph-link
    flags and a current local unit title so a stale catalogue reference cannot
    create a broken resource entry for a student.
    """
    unit_titles = {
        str(unit["id"]): str(unit.get("title") or unit["id"])
        for unit in load_teaching_units()
        if unit.get("id")
    }
    materials: list[dict[str, str]] = []
    seen_unit_ids: set[str] = set()
    for task in detail.get("tasks", []):
        if not isinstance(task, dict):
            continue
        for link in task.get("teaching_unit_links", []):
            if not isinstance(link, dict):
                continue
            unit_id = link.get("unit_id")
            if (
                not isinstance(unit_id, str)
                or unit_id in seen_unit_ids
                or not link.get("consumable")
                or not link.get("student_visible")
                or not link.get("in_student_visible_index")
                or link.get("review_status") != "published"
                or unit_id not in unit_titles
            ):
                continue
            seen_unit_ids.add(unit_id)
            materials.append(
                {
                    "type": "teaching_unit",
                    "ref_id": unit_id,
                    "title": unit_titles[unit_id],
                }
            )
    return materials


@router.get("/api/graph/overview")
def graph_overview(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    """全图（166 节点 + 240 边）；登录用户在 CAP 节点上叠加 mastery_status。"""
    current = _optional_user(request, conn)
    graph = reason.get_graph()
    mastery = _mastery_map(conn, current.user["id"]) if current else {}
    nodes: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        item = dict(node)
        if current and node.get("type") == "CAP":
            score = mastery.get(node["id"])
            item["mastery_status"] = _status_of(score)
            item["mastery_score"] = score
        nodes.append(item)
    return {"nodes": nodes, "edges": graph["edges"]}


@router.get("/api/graph/nodes")
def search_nodes(
    q: str | None = None,
    type: str | None = None,
    data_type: str | None = None,
    scenario_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """节点搜索（关键词/类型/数据类型/场景），走 graphx.search_nodes。"""
    items = reason.search_nodes(
        q, node_type=type, data_type=data_type, scenario_id=scenario_id, limit=limit
    )
    return {"items": items, "total": len(items)}


@router.get("/api/graph/nodes/{node_id}")
def node_detail(
    node_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """节点详情（前置/知识/资源/任务/证书/场景）+ 学生本人的该能力掌握记录。"""
    detail = reason.node_detail(node_id)
    if detail is None:
        raise ApiError(404, "NODE_NOT_FOUND", "图谱节点不存在")
    # Keep the browser on a narrow, student-safe DTO instead of making it
    # reconstruct course eligibility from generic graph task nodes.
    detail["learning_materials"] = _available_learning_materials(detail)
    current = _optional_user(request, conn)
    if current and node_id.startswith("CAP"):
        rows = conn.execute(
            "SELECT scenario_id, score, source, updated_at FROM mastery "
            "WHERE user_id = ? AND cap_id = ? ORDER BY scenario_id",
            (current.user["id"], node_id),
        ).fetchall()
        detail["mastery"] = [
            {
                "scenario_id": row["scenario_id"],
                "score": float(row["score"]),
                "source": row["source"],
                "updated_at": row["updated_at"],
                "mastery_status": _status_of(float(row["score"])),
            }
            for row in rows
        ]
    return detail


@router.get("/api/graph/subgraph")
def get_subgraph(node_id: str, depth: int = 2) -> dict:
    """局部子图（内存 BFS，远低于 500ms 预算）；中心节点不存在 404。"""
    result = reason.subgraph(node_id, depth)
    if not result["nodes"]:
        raise ApiError(404, "NODE_NOT_FOUND", "图谱节点不存在")
    return result


@router.get("/api/graph/pre-path")
def get_pre_path(
    target_id: str,
    skip_mastered: int = 0,
    request: Request = None,  # type: ignore[assignment]
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """PRE 补强路径（基础在前）；skip_mastered=1 时跳过本人已掌握（≥0.8）的能力。"""
    index = {n["id"]: n for n in reason.get_graph()["nodes"]}
    if target_id not in index:
        raise ApiError(404, "NODE_NOT_FOUND", "图谱节点不存在")
    skip_ids: set[str] = set()
    if skip_mastered:
        current = _optional_user(request, conn)
        if current:
            skip_ids = {
                cid
                for cid, score in _mastery_map(conn, current.user["id"]).items()
                if score >= MASTERED_THRESHOLD
            }
    try:
        path_ids = reason.pre_path(target_id, skip_ids=skip_ids)
    except ValueError as exc:
        # PRE 环是图谱内容事故：启动校验兜底，这里如实报告而非给可疑顺序
        raise ApiError(409, "GRAPH_PRE_CYCLE", "图谱前置关系存在环，请联系管理员修复") from exc
    return {
        "target_id": target_id,
        "path": [
            {"id": nid, "name": index[nid].get("name", nid), "type": index[nid].get("type")}
            for nid in path_ids
        ],
        "skipped_mastered": sorted(skip_ids & set(index)) if skip_mastered else [],
    }
