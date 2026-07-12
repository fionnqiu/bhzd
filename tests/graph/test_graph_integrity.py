import copy
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
GRAPH_JSON_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
GRAPHML_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.graphml"
BUILD_SCRIPT = ROOT / "scripts" / "build_graph.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "validate_graph.py"
TEACHING_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
EXPECTED_NODE_COUNTS = {
    "CAP": 40,
    "KNG": 60,
    "TSK": 20,
    "SCN": 4,
    "RES": 30,
    "CERT": 12,
}
EXPECTED_RELATIONS = {"PRE", "ISA", "SUP", "REL", "INSCN", "MAPCERT"}
REQUIRED_PATHS = (
    CATALOG_PATH,
    GRAPH_JSON_PATH,
    GRAPHML_PATH,
    BUILD_SCRIPT,
    VALIDATE_SCRIPT,
)


def run_python(*args: object) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def graph() -> dict:
    missing = [str(path) for path in REQUIRED_PATHS if not path.exists()]
    if missing:
        pytest.skip(f"Task 2 graph files are not implemented yet: {missing}")
    return load_json(GRAPH_JSON_PATH)


def test_task2_graph_files_exist():
    missing = [str(path) for path in REQUIRED_PATHS if not path.exists()]
    assert not missing, f"Task 2 graph files are missing: {missing}"


def test_builder_is_deterministic(tmp_path):
    first_json = tmp_path / "first.json"
    first_graphml = tmp_path / "first.graphml"
    second_json = tmp_path / "second.json"
    second_graphml = tmp_path / "second.graphml"

    first = run_python(
        BUILD_SCRIPT,
        "--catalog",
        CATALOG_PATH,
        "--teaching-units",
        TEACHING_UNITS_PATH,
        "--json-output",
        first_json,
        "--graphml-output",
        first_graphml,
    )
    second = run_python(
        BUILD_SCRIPT,
        "--catalog",
        CATALOG_PATH,
        "--teaching-units",
        TEACHING_UNITS_PATH,
        "--json-output",
        second_json,
        "--graphml-output",
        second_graphml,
    )

    assert first.returncode == 0, first.stderr or first.stdout
    assert second.returncode == 0, second.stderr or second.stdout
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_graphml.read_bytes() == second_graphml.read_bytes()
    assert first_json.read_bytes() == GRAPH_JSON_PATH.read_bytes()
    assert first_graphml.read_bytes() == GRAPHML_PATH.read_bytes()


def test_json_schema_and_exact_graph_counts(graph):
    assert graph["schema_version"] == "1.0.0"
    assert graph["graph_id"] == "annotation-capability-graph"
    assert graph["graph_version"] == "1.0.0"
    assert graph["generated_from"] == "data/graph/graph-catalog.json"
    assert graph["source_registry"] == "data/sources/source-registry.json"

    node_counts = Counter(node["type"] for node in graph["nodes"])
    assert node_counts == EXPECTED_NODE_COUNTS
    assert graph["node_type_counts"] == EXPECTED_NODE_COUNTS
    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240
    assert sum(graph["edge_type_counts"].values()) == 240
    assert set(graph["edge_type_counts"]) == EXPECTED_RELATIONS

    node_ids = [node["id"] for node in graph["nodes"]]
    edge_ids = [edge["id"] for edge in graph["edges"]]
    assert len(node_ids) == len(set(node_ids))
    assert len(edge_ids) == len(set(edge_ids))
    assert node_ids == sorted(node_ids)
    assert edge_ids == [f"EDGE-{index:04d}" for index in range(1, 241)]

    for node in graph["nodes"]:
        assert node["id"].startswith(f'{node["type"]}-')
        assert node["label"]
        assert node["description"]
        assert node["status"] in {"draft", "reviewed", "published"}
        assert node["data_types"]
        assert set(node["data_types"]) <= {"text", "image", "audio", "video"}


def test_edges_use_allowed_endpoint_types(graph):
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    allowed_pairs = {
        "PRE": {("CAP", "CAP")},
        "ISA": {
            ("CAP", "CAP"),
            ("KNG", "CAP"),
            ("TSK", "CAP"),
            ("RES", "KNG"),
        },
        "SUP": {
            ("KNG", "CAP"),
            ("KNG", "TSK"),
            ("CAP", "CAP"),
            ("CAP", "TSK"),
            ("RES", "CAP"),
            ("RES", "TSK"),
        },
        "REL": {
            (source, target)
            for source in EXPECTED_NODE_COUNTS
            for target in EXPECTED_NODE_COUNTS
        },
        "INSCN": {("CAP", "SCN"), ("KNG", "SCN"), ("TSK", "SCN")},
        "MAPCERT": {("CAP", "CERT")},
    }

    assert {edge["relation"] for edge in graph["edges"]} == EXPECTED_RELATIONS
    assert Counter(edge["relation"] for edge in graph["edges"]) == graph[
        "edge_type_counts"
    ]
    for edge in graph["edges"]:
        assert edge["source"] in nodes_by_id
        assert edge["target"] in nodes_by_id
        source_type = nodes_by_id[edge["source"]]["type"]
        target_type = nodes_by_id[edge["target"]]["type"]
        assert (source_type, target_type) in allowed_pairs[edge["relation"]]
        assert edge["source"] != edge["target"]


def test_pre_relations_form_a_directed_acyclic_graph(graph):
    capability_ids = {
        node["id"] for node in graph["nodes"] if node["type"] == "CAP"
    }
    outgoing = defaultdict(list)
    indegree = {node_id: 0 for node_id in capability_ids}
    for edge in graph["edges"]:
        if edge["relation"] == "PRE":
            outgoing[edge["source"]].append(edge["target"])
            indegree[edge["target"]] += 1

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited = []
    while ready:
        node_id = ready.popleft()
        visited.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    assert set(visited) == capability_ids


def test_every_task_is_traceable_to_capability_and_sourced_knowledge(graph):
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    inbound_support = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] == "SUP":
            inbound_support[edge["target"]].append(nodes_by_id[edge["source"]])

    tasks = [node for node in graph["nodes"] if node["type"] == "TSK"]
    assert len(tasks) == 20
    for task in tasks:
        supporters = inbound_support[task["id"]]
        assert any(node["type"] == "CAP" for node in supporters), task["id"]
        assert any(
            node["type"] == "KNG" and node["source_refs"]
            for node in supporters
        ), task["id"]


def test_teaching_unit_links_respect_publication_gate(graph):
    teaching_units = load_json(TEACHING_UNITS_PATH)
    units_by_id = {unit["id"]: unit for unit in teaching_units["units"]}
    linked_units = set()

    for task in (node for node in graph["nodes"] if node["type"] == "TSK"):
        for link in task["teaching_unit_links"]:
            linked_units.add(link["unit_id"])
            unit = units_by_id[link["unit_id"]]
            assert link["review_status"] == unit["review_status"]
            assert link["student_visible"] is unit["student_visible"]
            assert link["consumable"] is (
                unit["review_status"] == "published" and unit["student_visible"]
            )
            if link["consumable"]:
                assert unit["id"] in teaching_units["student_visible_unit_ids"]

    assert {
        "TU-TEXT-LABEL-VOCAB-001",
        "TU-IMAGE-RECT-BOUNDS-001",
        "TU-AUDIO-DATA-BINDING-001",
        "TU-VIDEO-TRACK-ID-001",
    } <= linked_units
    assert not any(
        link["consumable"]
        for task in graph["nodes"]
        if task["type"] == "TSK"
        for link in task["teaching_unit_links"]
    )


def test_scenario_edges_have_compatible_rule_metadata(graph):
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    scenario_edges = [edge for edge in graph["edges"] if edge["relation"] == "INSCN"]
    assert scenario_edges

    for edge in scenario_edges:
        source = nodes_by_id[edge["source"]]
        scenario = nodes_by_id[edge["target"]]
        metadata = edge["metadata"]
        edge_data_types = set(metadata["data_types"])
        assert metadata["rule_id"].startswith("SCNR-")
        assert metadata["base_rule_ref"].startswith("KNG-")
        assert metadata["base_rule_ref"] in nodes_by_id
        assert metadata["override_type"] in {"add", "replace"}
        assert metadata["description"]
        assert edge_data_types
        assert edge_data_types <= set(source["data_types"])
        assert edge_data_types <= set(scenario["supported_data_types"])

    covered_scenarios = {edge["target"] for edge in scenario_edges}
    assert covered_scenarios == {
        node["id"] for node in graph["nodes"] if node["type"] == "SCN"
    }


def test_graphml_is_well_formed_and_structurally_matches_json(graph):
    namespace = {"g": "http://graphml.graphdrawing.org/xmlns"}
    root = ET.parse(GRAPHML_PATH).getroot()
    keys = {
        key.attrib["id"]: key.attrib["attr.name"]
        for key in root.findall("g:key", namespace)
    }

    def data_values(element):
        return {
            keys[data.attrib["key"]]: data.text or ""
            for data in element.findall("g:data", namespace)
        }

    graphml_nodes = {}
    for node in root.findall(".//g:node", namespace):
        values = data_values(node)
        graphml_nodes[node.attrib["id"]] = {
            "type": values["type"],
            "label": values["label"],
            "data_types": json.loads(values["data_types"]),
        }

    graphml_edges = {}
    for edge in root.findall(".//g:edge", namespace):
        values = data_values(edge)
        graphml_edges[edge.attrib["id"]] = {
            "source": edge.attrib["source"],
            "target": edge.attrib["target"],
            "relation": values["relation"],
            "metadata": json.loads(values["metadata"]),
        }

    assert graphml_nodes == {
        node["id"]: {
            "type": node["type"],
            "label": node["label"],
            "data_types": node["data_types"],
        }
        for node in graph["nodes"]
    }
    assert graphml_edges == {
        edge["id"]: {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
            "metadata": edge["metadata"],
        }
        for edge in graph["edges"]
    }


def test_validator_reports_all_checks_passed(graph):
    result = run_python(VALIDATE_SCRIPT, GRAPH_JSON_PATH)
    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout
    for check in (
        "schema/version",
        "exact counts",
        "unique IDs",
        "edge endpoints/types",
        "PRE acyclicity",
        "task traceability",
        "scenario compatibility",
        "Graph validation succeeded: 166 nodes, 240 edges",
    ):
        assert check in output


def corrupt_schema(graph):
    graph["schema_version"] = "9.9.9"


def corrupt_type_counts(graph):
    graph["nodes"].pop()


def corrupt_duplicate_id(graph):
    graph["nodes"].append(copy.deepcopy(graph["nodes"][0]))


def corrupt_endpoint(graph):
    graph["edges"][0]["target"] = "CAP-MISSING"


def corrupt_relation_endpoint(graph):
    knowledge = next(node for node in graph["nodes"] if node["type"] == "KNG")
    pre_edge = next(edge for edge in graph["edges"] if edge["relation"] == "PRE")
    pre_edge["source"] = knowledge["id"]


def corrupt_pre_cycle(graph):
    pre_edge = next(edge for edge in graph["edges"] if edge["relation"] == "PRE")
    reverse = copy.deepcopy(pre_edge)
    reverse["id"] = "EDGE-9999"
    reverse["source"], reverse["target"] = reverse["target"], reverse["source"]
    graph["edges"].append(reverse)


def corrupt_task_traceability(graph):
    task = next(node for node in graph["nodes"] if node["type"] == "TSK")
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if not (edge["relation"] == "SUP" and edge["target"] == task["id"])
    ]


def corrupt_scenario_compatibility(graph):
    edge = next(edge for edge in graph["edges"] if edge["relation"] == "INSCN")
    edge["metadata"]["data_types"] = ["unsupported-type"]


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (corrupt_schema, "schema_version"),
        (corrupt_type_counts, "type_counts"),
        (corrupt_duplicate_id, "duplicate_node_id"),
        (corrupt_endpoint, "missing_endpoint"),
        (corrupt_relation_endpoint, "relation_endpoint"),
        (corrupt_pre_cycle, "pre_cycle"),
        (corrupt_task_traceability, "task_traceability"),
        (corrupt_scenario_compatibility, "inscn_data_type"),
    ],
)
def test_validator_rejects_invalid_graphs(graph, tmp_path, mutation, error_code):
    corrupted = copy.deepcopy(graph)
    mutation(corrupted)
    graph_path = tmp_path / f"{error_code}.json"
    graph_path.write_text(
        json.dumps(corrupted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_python(VALIDATE_SCRIPT, graph_path)
    assert result.returncode != 0
    assert f"[{error_code}]" in (result.stdout + result.stderr)
