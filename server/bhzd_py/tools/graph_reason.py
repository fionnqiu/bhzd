"""graph.reason（read，自动执行）：能力图谱定位 / PRE 补强路径 / 子图（蓝图 §9）。

graphx（B4）惰性导入；未就绪时返回中文错误字典而不是抛异常——
读工具失败不应让整轮运行崩溃，编排器会把错误文本渲染给学生。
"""

from __future__ import annotations

from typing import Any

from .registry import ToolContext, ToolSpec

_GRAPH_NOT_READY = "图谱模块未就绪，暂时无法完成能力定位"


def _graphx():
    try:
        from ..graphx import reason as gx_reason  # B4，惰性导入
    except ImportError:
        return None
    return gx_reason


def _node_summary(node: Any) -> dict[str, Any]:
    """把 graphx 返回的节点（dict 或对象）压成可嵌入任务卡/回答的摘要。"""
    if isinstance(node, dict):
        return {
            "id": node.get("id"),
            "label": node.get("label") or node.get("name") or node.get("title"),
            "type": node.get("type"),
        }
    return {
        "id": getattr(node, "id", None),
        "label": getattr(node, "label", None) or getattr(node, "name", None),
        "type": getattr(node, "type", None),
    }


def graph_reason_handler(ctx: ToolContext) -> dict[str, Any]:
    args = ctx.args
    action = args.get("action", "locate")
    gx = _graphx()
    if gx is None:
        return {"error": _GRAPH_NOT_READY}

    if action == "locate":
        # 能力定位：按自然语言 query / 明确 cap_ids 找到图谱节点
        nodes: list[Any] = []
        for cap_id in args.get("cap_ids") or []:
            detail = gx.node_detail(cap_id)
            if detail:
                nodes.append(detail)
        query = args.get("query")
        if query or not nodes:
            nodes.extend(
                gx.search_nodes(
                    query=query or None,
                    node_type=args.get("node_type"),
                    data_type=args.get("data_type"),
                    scenario_id=args.get("scenario_id"),
                    limit=int(args.get("limit", 8)),
                )
                or []
            )
        summaries = [_node_summary(n) for n in nodes]
        # 去重（cap_ids 与 query 可能命中同一节点）
        seen: set[str] = set()
        unique = []
        for s in summaries:
            if s.get("id") and s["id"] not in seen:
                seen.add(s["id"])
                unique.append(s)
        return {
            "action": "locate",
            "nodes": unique,
            "cap_ids": [s["id"] for s in unique if s.get("type") == "CAP"],
        }

    if action == "pre_path":
        target_id = args.get("target_id")
        if not target_id:
            return {"error": "缺少 target_id，无法生成补强路径"}
        path = gx.pre_path(target_id, skip_ids=args.get("skip_ids"))
        nodes = [_node_summary(n) for n in (path or [])]
        return {"action": "pre_path", "target_id": target_id, "nodes": nodes}

    if action == "subgraph":
        node_id = args.get("node_id")
        if not node_id:
            return {"error": "缺少 node_id，无法获取子图"}
        sub = gx.subgraph(node_id, depth=int(args.get("depth", 2)))
        if isinstance(sub, dict):
            nodes = [_node_summary(n) for n in sub.get("nodes", [])]
            return {"action": "subgraph", "node_id": node_id, "nodes": nodes,
                    "edges": sub.get("edges", [])}
        return {"action": "subgraph", "node_id": node_id, "nodes": []}

    return {"error": f"不支持的图谱动作：{action}"}


SPEC = ToolSpec(
    name="graph.reason",
    permission="read",
    auto_execute=True,
    description="能力图谱推理：locate（能力定位）/ pre_path（前置补强路径）/ subgraph（局部子图）",
    handler=graph_reason_handler,
)
