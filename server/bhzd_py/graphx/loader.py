"""图谱 JSON 的进程内缓存加载器（data/graph/annotation-capability-graph.json）。

设计要点（为什么）：
- 图谱文件是只读运行时数据（蓝图 §13.3 不入库），但 166 节点/240 边的 JSON
  每次请求都读盘解析不划算，因此做进程级缓存；同时按 mtime 失效重载，
  图谱修订后无需重启进程即可生效。
- 源文件的字段名与蓝图规范化口径不一致（节点用 `label`、边用 `relation`），
  加载时统一规范化为 `{"nodes":[{id,type,name,...attrs}], "edges":[{source,
  target,type,...}]}`，让上层（reason/routers）只面对一种形状；原始字段
  （label/relation 等）原样保留在 attrs 里，不丢信息。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..config import get_config

GRAPH_FILENAME = "annotation-capability-graph.json"

# 缓存三元组：(mtime, graph)；lock 保证并发首次加载只解析一次
_cache_lock = threading.Lock()
_cached_graph: dict[str, Any] | None = None
_cached_mtime: float | None = None


def graph_path() -> Path:
    """图谱文件绝对路径；数据目录走配置（BHZD_DATA_DIR），与全站一致。"""
    return Path(get_config().resolved_data_dir) / "graph" / GRAPH_FILENAME


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """把源 JSON 规范化为 reason 层消费的形状（见模块 docstring）。"""
    nodes: list[dict[str, Any]] = []
    for node in raw.get("nodes", []):
        item = dict(node)
        # 蓝图口径要求节点有 name；源文件只有 label，映射之（label 保留不删）
        item.setdefault("name", item.get("label", item.get("id", "")))
        nodes.append(item)
    edges: list[dict[str, Any]] = []
    for edge in raw.get("edges", []):
        item = dict(edge)
        # 源文件边类型字段叫 relation，规范化出 type（relation 保留）
        item.setdefault("type", item.get("relation", ""))
        edges.append(item)
    return {"nodes": nodes, "edges": edges}


def load_graph(force_reload: bool = False) -> dict[str, Any]:
    """返回规范化后的全图（进程内缓存，mtime 变化时自动重载）。

    返回值是共享缓存对象，调用方**只读**使用；需要改动请自行深拷贝。
    文件缺失/损坏时抛出的异常原样上抛（启动校验依赖它失败即停，蓝图 §13.3）。
    """
    global _cached_graph, _cached_mtime
    path = graph_path()
    mtime = os.stat(path).st_mtime
    with _cache_lock:
        if not force_reload and _cached_graph is not None and _cached_mtime == mtime:
            return _cached_graph
        raw = json.loads(path.read_text(encoding="utf-8"))
        _cached_graph = _normalize(raw)
        _cached_mtime = mtime
        return _cached_graph


def reset_cache() -> None:
    """清缓存（测试隔离用；生产代码不应调用）。"""
    global _cached_graph, _cached_mtime
    with _cache_lock:
        _cached_graph = None
        _cached_mtime = None
