"""graphx 图谱推理测试：真实图谱加载、PRE 路径拓扑序与无环、子图深度、搜索过滤。"""

from __future__ import annotations

import pytest

from bhzd_py.graphx import loader, reason


@pytest.fixture(autouse=True)
def _fresh_graph_cache():
    """每测试清图谱缓存，避免 monkeypatch 互相污染。"""
    loader.reset_cache()
    yield
    loader.reset_cache()


def test_real_graph_loads_166_nodes():
    graph = reason.get_graph()
    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240
    # 规范化契约：节点有 name，边有 type（源文件的 label/relation 也保留）
    node = next(n for n in graph["nodes"] if n["id"] == "CAP-AUD-SPEAKER-001")
    assert node["type"] == "CAP"
    assert node["name"] == "区分说话人"
    edge = next(e for e in graph["edges"] if e.get("type") == "PRE")
    assert edge["relation"] == "PRE"


def test_pre_path_topo_order_foundations_first():
    """已知 CAP 的前置链：每个节点的前置都必须排在它前面。"""
    target = "CAP-AUD-EMOTION-PARALING-001"
    path = reason.pre_path(target)
    assert path[0] == "CAP-CORE-TASK-SCOPE-001"  # 全图最基础的能力在链首
    assert path[-1] == target  # 目标在链尾
    position = {nid: idx for idx, nid in enumerate(path)}
    graph = reason.get_graph()
    for edge in graph["edges"]:
        if edge.get("type") != "PRE":
            continue
        src, tgt = edge["source"], edge["target"]
        if src in position and tgt in position:
            assert position[src] < position[tgt], f"PRE 边 {src}->{tgt} 顺序被颠倒"


def test_pre_path_all_caps_acyclic_on_real_graph():
    """PRD-01 §5.2：真实图谱全部 CAP 的 PRE 闭包都无环（不抛 PRE_CYCLE）。"""
    caps = [n["id"] for n in reason.get_graph()["nodes"] if n["type"] == "CAP"]
    assert len(caps) == 40
    for cap_id in caps:
        reason.pre_path(cap_id)  # 有环会抛 ValueError("PRE_CYCLE")


def test_pre_path_skip_ids_filtered_at_end():
    full = reason.pre_path("CAP-AUD-EMOTION-PARALING-001")
    skipped = reason.pre_path(
        "CAP-AUD-EMOTION-PARALING-001", skip_ids={full[0], full[1]}
    )
    assert skipped == full[2:]
    # 剩余节点的相对顺序不因 skip 改变（skip 是过滤不是删图）
    assert skipped == [nid for nid in full if nid not in {full[0], full[1]}]


def test_pre_path_cycle_detection_raises(monkeypatch):
    """合成含环 PRE 图：必须抛 ValueError('PRE_CYCLE')。"""
    synthetic = {
        "nodes": [
            {"id": "CAP-A", "type": "CAP", "name": "A"},
            {"id": "CAP-B", "type": "CAP", "name": "B"},
        ],
        "edges": [
            {"source": "CAP-A", "target": "CAP-B", "type": "PRE"},
            {"source": "CAP-B", "target": "CAP-A", "type": "PRE"},
        ],
    }
    # reason 模块直接引用了 load_graph 符号，patch 它即可注入合成图
    # （用 monkeypatch 夹具保证测试后自动还原，不污染同进程其他用例）
    monkeypatch.setattr(reason, "load_graph", lambda: synthetic)
    with pytest.raises(ValueError, match="PRE_CYCLE"):
        reason.pre_path("CAP-A")


def test_subgraph_respects_depth():
    center = "CAP-AUD-EMOTION-PARALING-001"
    one_hop = reason.subgraph(center, 1)
    two_hop = reason.subgraph(center, 2)
    one_ids = {n["id"] for n in one_hop["nodes"]}
    two_ids = {n["id"] for n in two_hop["nodes"]}
    assert center in one_ids
    assert one_ids < two_ids  # depth=2 严格更深
    # depth=1 只含直接邻居：手工算一跳邻集对比
    graph = reason.get_graph()
    expected = {center}
    for edge in graph["edges"]:
        if edge["source"] == center:
            expected.add(edge["target"])
        if edge["target"] == center:
            expected.add(edge["source"])
    assert one_ids == expected
    # 子图的边必须两端都在子图内
    for edge in one_hop["edges"]:
        assert edge["source"] in one_ids and edge["target"] in one_ids


def test_subgraph_unknown_center_returns_empty():
    assert reason.subgraph("CAP-NOPE-001", 2) == {"nodes": [], "edges": []}


def test_search_nodes_filters():
    by_query = reason.search_nodes("情感", node_type="CAP")
    assert {n["id"] for n in by_query} == {
        "CAP-AUD-EMOTION-PARALING-001",
        "CAP-TXT-SENTIMENT-001",
    }
    by_type = reason.search_nodes(node_type="SCN")
    assert len(by_type) == 4
    by_dtype = reason.search_nodes(node_type="CAP", data_type="image")
    assert by_dtype and all("image" in n["data_types"] for n in by_dtype)
    by_scn = reason.search_nodes(scenario_id="SCN-CUSTOMER-SERVICE-001")
    scn_ids = {n["id"] for n in by_scn}
    assert "CAP-AUD-SPEAKER-001" in scn_ids  # INSCN 边命中的能力
    assert "SCN-CUSTOMER-SERVICE-001" in scn_ids  # 场景节点本身也在结果里
    limited = reason.search_nodes(limit=3)
    assert len(limited) == 3


def test_node_detail_related_collections():
    detail = reason.node_detail("CAP-AUD-EMOTION-PARALING-001")
    assert detail is not None
    assert [n["id"] for n in detail["prerequisites"]] == ["CAP-AUD-TRANSCRIBE-PUNCT-001"]
    assert [n["id"] for n in detail["resources"]] == ["RES-AUD-EVENT-CATALOG-001"]
    assert [n["id"] for n in detail["tasks"]] == ["TSK-AUD-EMOTION-EVENT-001"]
    assert detail["certificates"] and detail["scenarios"] and detail["knowledge"]
    assert reason.node_detail("NOPE") is None
