#!/usr/bin/env python3
"""Build the deterministic annotation capability graph in JSON and GraphML."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "graph" / "graph-catalog.json"
DEFAULT_TEACHING_UNITS = ROOT / "data" / "curriculum" / "teaching-units.json"
DEFAULT_JSON_OUTPUT = ROOT / "data" / "graph" / "annotation-capability-graph.json"
DEFAULT_GRAPHML_OUTPUT = ROOT / "data" / "graph" / "annotation-capability-graph.graphml"
NODE_TYPE_ORDER = ("CAP", "KNG", "TSK", "SCN", "RES", "CERT")
RELATION_ORDER = ("PRE", "ISA", "SUP", "REL", "INSCN", "MAPCERT")
RELATION_LABELS = {
    "PRE": "前置于",
    "ISA": "归属于",
    "SUP": "支持",
    "REL": "关联",
    "INSCN": "应用于场景",
    "MAPCERT": "映射证书",
}
GRAPHML_NAMESPACE = "http://graphml.graphdrawing.org/xmlns"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def catalog_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_teaching_unit_links(
    references: list[str], teaching_units: dict[str, Any]
) -> list[dict[str, Any]]:
    units_by_id = {unit["id"]: unit for unit in teaching_units.get("units", [])}
    links = []
    visible_index = set(teaching_units.get("student_visible_unit_ids", []))
    for unit_id in sorted(references):
        if unit_id not in units_by_id:
            raise ValueError(f"unknown teaching unit reference: {unit_id}")
        unit = units_by_id[unit_id]
        in_student_visible_index = unit_id in visible_index
        consumable = (
            unit.get("review_status") == "published"
            and unit.get("student_visible") is True
            and in_student_visible_index
        )
        links.append(
            {
                "unit_id": unit_id,
                "review_status": unit.get("review_status"),
                "student_visible": unit.get("student_visible") is True,
                "in_student_visible_index": in_student_visible_index,
                "consumable": consumable,
            }
        )
    return links


def build_graph(
    catalog: dict[str, Any],
    teaching_units: dict[str, Any],
    digest: str,
) -> dict[str, Any]:
    if catalog.get("schema_version") != "1.0.0":
        raise ValueError("catalog schema_version must be 1.0.0")

    graph_config = catalog["graph"]
    nodes = []
    for node_type in NODE_TYPE_ORDER:
        for raw_node in catalog["nodes"].get(node_type, []):
            node = copy.deepcopy(raw_node)
            node["type"] = node_type
            node.setdefault("status", "draft")
            node.setdefault("source_refs", [])
            node["data_types"] = sorted(set(node.get("data_types", [])))
            if node_type == "TSK":
                references = node.pop("teaching_unit_refs", [])
                node["teaching_unit_links"] = build_teaching_unit_links(
                    references, teaching_units
                )
                node.setdefault("student_visible", False)
            nodes.append(node)
    nodes.sort(key=lambda node: node["id"])

    edge_records = []
    for relation in RELATION_ORDER:
        for raw_edge in catalog["relations"].get(relation, []):
            edge = copy.deepcopy(raw_edge)
            edge["relation"] = relation
            edge.setdefault("label", RELATION_LABELS[relation])
            edge.setdefault("metadata", {})
            edge_records.append(edge)
    edge_records.sort(
        key=lambda edge: (
            RELATION_ORDER.index(edge["relation"]),
            edge["source"],
            edge["target"],
            canonical_json(edge["metadata"]),
        )
    )
    edges = [
        {"id": f"EDGE-{index:04d}", **edge}
        for index, edge in enumerate(edge_records, start=1)
    ]

    node_counts = Counter(node["type"] for node in nodes)
    edge_counts = Counter(edge["relation"] for edge in edges)
    return {
        "schema_version": catalog["schema_version"],
        "graph_id": graph_config["id"],
        "graph_version": graph_config["version"],
        "title": graph_config["title"],
        "description": graph_config["description"],
        "publication_state": graph_config["publication_state"],
        "generated_from": graph_config["generated_from"],
        "generated_by": "scripts/build_graph.py",
        "catalog_sha256": digest,
        "source_registry": graph_config["source_registry"],
        "teaching_units": graph_config["teaching_units"],
        "node_type_counts": {
            node_type: node_counts[node_type] for node_type in NODE_TYPE_ORDER
        },
        "edge_type_counts": {
            relation: edge_counts[relation] for relation in RELATION_ORDER
        },
        "nodes": nodes,
        "edges": edges,
    }


def add_graphml_data(
    parent: ET.Element,
    key_id: str,
    value: Any,
    *,
    encode_json: bool = False,
) -> None:
    element = ET.SubElement(parent, f"{{{GRAPHML_NAMESPACE}}}data", {"key": key_id})
    if encode_json:
        element.text = canonical_json(value)
    elif isinstance(value, bool):
        element.text = "true" if value else "false"
    else:
        element.text = str(value)


def graph_to_graphml(graph: dict[str, Any]) -> bytes:
    ET.register_namespace("", GRAPHML_NAMESPACE)
    root = ET.Element(f"{{{GRAPHML_NAMESPACE}}}graphml")
    key_definitions = (
        ("n0", "node", "type"),
        ("n1", "node", "label"),
        ("n2", "node", "description"),
        ("n3", "node", "data_types"),
        ("n4", "node", "status"),
        ("n5", "node", "source_refs"),
        ("n6", "node", "attributes"),
        ("e0", "edge", "relation"),
        ("e1", "edge", "label"),
        ("e2", "edge", "metadata"),
    )
    for key_id, target, name in key_definitions:
        ET.SubElement(
            root,
            f"{{{GRAPHML_NAMESPACE}}}key",
            {
                "id": key_id,
                "for": target,
                "attr.name": name,
                "attr.type": "string",
            },
        )

    graph_element = ET.SubElement(
        root,
        f"{{{GRAPHML_NAMESPACE}}}graph",
        {"id": graph["graph_id"], "edgedefault": "directed"},
    )
    core_node_fields = {
        "id",
        "type",
        "label",
        "description",
        "data_types",
        "status",
        "source_refs",
    }
    for node in graph["nodes"]:
        node_element = ET.SubElement(
            graph_element,
            f"{{{GRAPHML_NAMESPACE}}}node",
            {"id": node["id"]},
        )
        add_graphml_data(node_element, "n0", node["type"])
        add_graphml_data(node_element, "n1", node["label"])
        add_graphml_data(node_element, "n2", node["description"])
        add_graphml_data(node_element, "n3", node["data_types"], encode_json=True)
        add_graphml_data(node_element, "n4", node["status"])
        add_graphml_data(node_element, "n5", node["source_refs"], encode_json=True)
        extra_attributes = {
            key: value for key, value in node.items() if key not in core_node_fields
        }
        add_graphml_data(node_element, "n6", extra_attributes, encode_json=True)

    for edge in graph["edges"]:
        edge_element = ET.SubElement(
            graph_element,
            f"{{{GRAPHML_NAMESPACE}}}edge",
            {
                "id": edge["id"],
                "source": edge["source"],
                "target": edge["target"],
            },
        )
        add_graphml_data(edge_element, "e0", edge["relation"])
        add_graphml_data(edge_element, "e1", edge["label"])
        add_graphml_data(edge_element, "e2", edge["metadata"], encode_json=True)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def write_outputs(
    graph: dict[str, Any], json_output: Path, graphml_output: Path
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    graphml_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    graphml_output.write_bytes(graph_to_graphml(graph))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic JSON and GraphML capability graph artifacts."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--teaching-units", type=Path, default=DEFAULT_TEACHING_UNITS)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--graphml-output", type=Path, default=DEFAULT_GRAPHML_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_json(args.catalog)
    teaching_units = load_json(args.teaching_units)
    graph = build_graph(catalog, teaching_units, catalog_digest(args.catalog))
    write_outputs(graph, args.json_output, args.graphml_output)
    print(
        "Built annotation capability graph: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
    )
    print(f"JSON: {args.json_output}")
    print(f"GraphML: {args.graphml_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
