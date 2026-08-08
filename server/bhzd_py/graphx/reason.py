"""图谱只读推理（公开契约层，Agent 工具域 graph.reason 与本域 routers 共用）。

Pinned 公开签名（蓝图 §2.1 / 任务契约，签名不可改）：
- get_graph() -> dict
- search_nodes(query=None, *, node_type=None, data_type=None, scenario_id=None, limit=50)
- node_detail(node_id) -> dict | None
- subgraph(node_id, depth=2) -> dict
- pre_path(target_id, *, skip_ids=None) -> list[str]

关键语义（为什么）：
- PRE 边方向：源文件 `source -PRE(前置于)-> target`，即 source 是 target 的
  前置能力；求 target 的前置链要沿 PRE 边**逆向往回走**。
- pre_path 用 Kahn 拓扑排序保证"基础在前"（PRD-01 §5.1 推荐补强顺序），
  图中 PRE 子图必须无环（PRD-01 §5.2），检测到环抛 ValueError("PRE_CYCLE")，
  宁可报错也不给出顺序不可信的学习路径。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .loader import load_graph


def get_graph() -> dict:
    """返回规范化全图 {"nodes": [...], "edges": [...]}（共享缓存，只读使用）。"""
    return load_graph()


def _node_index(graph: dict) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in graph["nodes"]}


def _edges_of(graph: dict, relation: str) -> list[dict[str, Any]]:
    return [e for e in graph["edges"] if e.get("type") == relation]


def search_nodes(
    query: str | None = None,
    *,
    node_type: str | None = None,
    data_type: str | None = None,
    scenario_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """按关键词/类型/数据类型/场景过滤节点。

    - query：对 id/name/description 做大小写不敏感的子串匹配；
    - data_type：命中节点的 data_types 列表（SCN/CERT 等无该字段的节点被排除）；
    - scenario_id：命中通过 INSCN 边连到该场景的节点，以及场景节点本身
      （INSCN 是"应用于场景"边，CAP/KNG/TSK → SCN）。
    """
    graph = get_graph()
    nodes = graph["nodes"]
    scenario_hit: set[str] | None = None
    if scenario_id:
        scenario_hit = {scenario_id}
        for edge in _edges_of(graph, "INSCN"):
            if edge["target"] == scenario_id:
                scenario_hit.add(edge["source"])
    q = query.strip().lower() if query else None
    results: list[dict[str, Any]] = []
    for node in nodes:
        if node_type and node.get("type") != node_type:
            continue
        if data_type and data_type not in (node.get("data_types") or []):
            continue
        if scenario_hit is not None and node["id"] not in scenario_hit:
            continue
        if q:
            haystack = " ".join(
                str(node.get(key) or "") for key in ("id", "name", "description")
            ).lower()
            if q not in haystack:
                continue
        results.append(node)
        if len(results) >= limit:
            break
    return results


def node_detail(node_id: str) -> dict | None:
    """节点详情：节点本体 + 直接前置（PRE 源）+ 关联 KNG/RES/TSK/CERT + 应用场景。

    关联边的语义（来自图谱 build 脚本口径）：
    - ISA: KNG → CAP（知识归属于能力）；SUP: CAP→TSK、KNG→CAP/TSK、RES→CAP（支持）；
    - MAPCERT: CAP → CERT；INSCN: * → SCN；REL: 双向都视作"关联"。
    找不到节点返回 None（由路由层翻译为 404 中文提示）。
    """
    graph = get_graph()
    node = _node_index(graph).get(node_id)
    if node is None:
        return None
    by_id = _node_index(graph)

    def _nodes(ids: list[str]) -> list[dict[str, Any]]:
        return [by_id[i] for i in ids if i in by_id]

    prerequisites: list[str] = []
    knowledge: list[str] = []
    resources: list[str] = []
    tasks: list[str] = []
    certs: list[str] = []
    scenarios: list[str] = []
    related: list[str] = []
    for edge in graph["edges"]:
        etype, src, tgt = edge.get("type"), edge["source"], edge["target"]
        if etype == "PRE" and tgt == node_id:
            prerequisites.append(src)
        elif etype == "ISA" and tgt == node_id and src.startswith("KNG"):
            knowledge.append(src)
        elif etype == "SUP":
            # RES→CAP：资源支持能力；CAP→TSK：能力支持任务；KNG→CAP：知识支撑
            if tgt == node_id and src.startswith("RES"):
                resources.append(src)
            elif src == node_id and tgt.startswith("TSK"):
                tasks.append(tgt)
            elif tgt == node_id and src.startswith("KNG"):
                knowledge.append(src)
        elif etype == "MAPCERT" and src == node_id:
            certs.append(tgt)
        elif etype == "INSCN" and src == node_id:
            scenarios.append(tgt)
        elif etype == "REL":
            if src == node_id:
                related.append(tgt)
            elif tgt == node_id:
                related.append(src)
    return {
        **node,
        "prerequisites": _nodes(prerequisites),
        "knowledge": _nodes(knowledge),
        "resources": _nodes(resources),
        "tasks": _nodes(tasks),
        "certificates": _nodes(certs),
        "scenarios": _nodes(scenarios),
        "related": _nodes(related),
    }


def subgraph(node_id: str, depth: int = 2) -> dict:
    """以 node_id 为中心的局部子图（所有边类型视为无向做 BFS，限 depth 层）。

    返回 {"nodes": [...], "edges": [...]}；中心节点不存在时返回空图
    （路由层据此返回 404）。全内存 BFS，166 节点规模下远低于 500ms 预算。
    """
    graph = get_graph()
    by_id = _node_index(graph)
    if node_id not in by_id:
        return {"nodes": [], "edges": []}
    depth = max(0, min(depth, 10))  # 防御性上限，避免误传大值扫全图
    adjacency: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        adjacency.setdefault(edge["source"], []).append(edge["target"])
        adjacency.setdefault(edge["target"], []).append(edge["source"])
    visited = {node_id}
    frontier = [node_id]
    for _ in range(depth):
        nxt: list[str] = []
        for nid in frontier:
            for nb in adjacency.get(nid, []):
                if nb not in visited:
                    visited.add(nb)
                    nxt.append(nb)
        frontier = nxt
        if not frontier:
            break
    nodes = [by_id[i] for i in sorted(visited)]
    edges = [
        e for e in graph["edges"] if e["source"] in visited and e["target"] in visited
    ]
    return {"nodes": nodes, "edges": edges}


def pre_path(target_id: str, *, skip_ids: set[str] | None = None) -> list[str]:
    """target 的全部传递前置（含 target 自身）按 Kahn 拓扑序输出（基础在前）。

    skip_ids（如已掌握能力）在排序完成后**从结果中剔除**——不参与排序而不是
    不参与建图，因为被跳过节点仍可能是其余节点的拓扑桥梁，从图中删掉会
    改变剩余节点的相对顺序语义。检测到 PRE 环抛 ValueError("PRE_CYCLE")。
    """
    graph = get_graph()
    pre_edges = _edges_of(graph, "PRE")
    # 第一步：从 target 沿 PRE 逆向收集传递闭包
    prereq_of: dict[str, list[str]] = {}
    for edge in pre_edges:
        prereq_of.setdefault(edge["target"], []).append(edge["source"])
    closure: set[str] = set()
    stack = [target_id]
    while stack:
        nid = stack.pop()
        if nid in closure:
            continue
        closure.add(nid)
        stack.extend(prereq_of.get(nid, []))
    # 第二步：闭包内做 Kahn 拓扑排序（边方向 source→target，即基础→进阶）
    indegree: dict[str, int] = {nid: 0 for nid in closure}
    outgoing: dict[str, list[str]] = {nid: [] for nid in closure}
    for edge in pre_edges:
        src, tgt = edge["source"], edge["target"]
        if src in closure and tgt in closure:
            indegree[tgt] += 1
            outgoing[src].append(tgt)
    # 排序后入队保证输出确定性（同一层按 id 字典序）
    queue = deque(sorted(nid for nid, deg in indegree.items() if deg == 0))
    ordered: list[str] = []
    while queue:
        nid = queue.popleft()
        ordered.append(nid)
        ready: list[str] = []
        for tgt in outgoing[nid]:
            indegree[tgt] -= 1
            if indegree[tgt] == 0:
                ready.append(tgt)
        for tgt in sorted(ready):
            queue.append(tgt)
    if len(ordered) != len(closure):
        # 有节点没被排到 = 闭包内存在环；学习路径顺序不可信，直接报错
        raise ValueError("PRE_CYCLE")
    skips = skip_ids or set()
    return [nid for nid in ordered if nid not in skips]
