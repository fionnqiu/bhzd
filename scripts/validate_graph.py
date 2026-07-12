#!/usr/bin/env python3
"""Validate the annotation capability graph contract."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCHEMA_VERSION = "1.0.0"
EXPECTED_GRAPH_VERSION = "1.0.0"
EXPECTED_NODE_COUNTS = {
    "CAP": 40,
    "KNG": 60,
    "TSK": 20,
    "SCN": 4,
    "RES": 30,
    "CERT": 12,
}
EXPECTED_EDGE_COUNT = 240
RELATION_ORDER = ("PRE", "ISA", "SUP", "REL", "INSCN", "MAPCERT")
ALLOWED_DATA_TYPES = {"text", "image", "audio", "video"}
ALLOWED_ENDPOINTS = {
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


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def add_error(errors: list[str], code: str, message: str) -> None:
    errors.append(f"[{code}] {message}")


def resolve_registry_path(graph: dict[str, Any]) -> Path | None:
    value = graph.get("source_registry")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def validate_schema_and_counts(graph: dict[str, Any], errors: list[str]) -> None:
    if graph.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        add_error(
            errors,
            "schema_version",
            f"expected {EXPECTED_SCHEMA_VERSION}, got {graph.get('schema_version')!r}",
        )
    if graph.get("graph_version") != EXPECTED_GRAPH_VERSION:
        add_error(
            errors,
            "graph_version",
            f"expected {EXPECTED_GRAPH_VERSION}, got {graph.get('graph_version')!r}",
        )
    if graph.get("graph_id") != "annotation-capability-graph":
        add_error(errors, "graph_id", "graph_id must be annotation-capability-graph")

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        add_error(errors, "schema_nodes", "nodes must be an array")
        nodes = []
    if not isinstance(edges, list):
        add_error(errors, "schema_edges", "edges must be an array")
        edges = []

    computed_node_counts = Counter(
        node.get("type") for node in nodes if isinstance(node, dict)
    )
    if dict(computed_node_counts) != EXPECTED_NODE_COUNTS:
        add_error(
            errors,
            "type_counts",
            f"expected {EXPECTED_NODE_COUNTS}, got {dict(computed_node_counts)}",
        )
    if graph.get("node_type_counts") != EXPECTED_NODE_COUNTS:
        add_error(errors, "declared_type_counts", "node_type_counts metadata is stale")
    if len(nodes) != sum(EXPECTED_NODE_COUNTS.values()):
        add_error(errors, "node_count", f"expected 166 nodes, got {len(nodes)}")
    if len(edges) != EXPECTED_EDGE_COUNT:
        add_error(errors, "edge_count", f"expected 240 edges, got {len(edges)}")

    computed_edge_counts = Counter(
        edge.get("relation") for edge in edges if isinstance(edge, dict)
    )
    if set(computed_edge_counts) != set(RELATION_ORDER):
        add_error(
            errors,
            "relation_types",
            f"relations must be exactly {list(RELATION_ORDER)}",
        )
    if graph.get("edge_type_counts") != {
        relation: computed_edge_counts[relation] for relation in RELATION_ORDER
    }:
        add_error(errors, "declared_edge_counts", "edge_type_counts metadata is stale")


def validate_ids_and_endpoints(
    graph: dict[str, Any], errors: list[str]
) -> dict[str, dict[str, Any]]:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    node_ids = [node.get("id") for node in nodes]
    edge_ids = [edge.get("id") for edge in edges]
    duplicate_node_ids = sorted(
        node_id for node_id, count in Counter(node_ids).items() if count > 1
    )
    duplicate_edge_ids = sorted(
        edge_id for edge_id, count in Counter(edge_ids).items() if count > 1
    )
    if duplicate_node_ids:
        add_error(errors, "duplicate_node_id", f"duplicates: {duplicate_node_ids}")
    if duplicate_edge_ids:
        add_error(errors, "duplicate_edge_id", f"duplicates: {duplicate_edge_ids}")

    nodes_by_id = {
        node["id"]: node
        for node in nodes
        if isinstance(node.get("id"), str) and node.get("id")
    }
    for node in nodes:
        node_id = node.get("id", "<missing>")
        node_type = node.get("type")
        if node_type not in EXPECTED_NODE_COUNTS:
            add_error(errors, "node_type", f"{node_id}: invalid type {node_type!r}")
        elif not str(node_id).startswith(f"{node_type}-"):
            add_error(errors, "node_namespace", f"{node_id}: does not match {node_type}")
        if not node.get("label") or not node.get("description"):
            add_error(errors, "node_content", f"{node_id}: label/description required")
        data_types = node.get("data_types")
        if not isinstance(data_types, list) or not data_types:
            add_error(errors, "node_data_types", f"{node_id}: data_types required")
        elif not set(data_types) <= ALLOWED_DATA_TYPES:
            add_error(errors, "node_data_types", f"{node_id}: invalid data_types")
        if node.get("status") not in {"draft", "reviewed", "published"}:
            add_error(errors, "node_status", f"{node_id}: invalid status")

    for edge in edges:
        edge_id = edge.get("id", "<missing>")
        source_id = edge.get("source")
        target_id = edge.get("target")
        relation = edge.get("relation")
        missing = [
            endpoint
            for endpoint in (source_id, target_id)
            if endpoint not in nodes_by_id
        ]
        if missing:
            add_error(errors, "missing_endpoint", f"{edge_id}: missing {missing}")
            continue
        if source_id == target_id:
            add_error(errors, "self_edge", f"{edge_id}: self edges are not allowed")
        if relation not in ALLOWED_ENDPOINTS:
            add_error(errors, "relation_type", f"{edge_id}: invalid relation {relation!r}")
            continue
        pair = (nodes_by_id[source_id]["type"], nodes_by_id[target_id]["type"])
        if pair not in ALLOWED_ENDPOINTS[relation]:
            add_error(
                errors,
                "relation_endpoint",
                f"{edge_id}: {relation} does not allow {pair[0]} -> {pair[1]}",
            )
    return nodes_by_id


def validate_pre_acyclicity(
    graph: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], errors: list[str]
) -> None:
    capability_ids = {
        node_id for node_id, node in nodes_by_id.items() if node.get("type") == "CAP"
    }
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in capability_ids}
    for edge in graph.get("edges", []):
        if edge.get("relation") != "PRE":
            continue
        source = edge.get("source")
        target = edge.get("target")
        if source in capability_ids and target in capability_ids:
            outgoing[source].append(target)
            indegree[target] += 1

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        node_id = ready.popleft()
        visited += 1
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(capability_ids):
        cyclic = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
        add_error(errors, "pre_cycle", f"PRE cycle includes {cyclic}")


def load_source_registry(
    graph: dict[str, Any], errors: list[str]
) -> dict[str, dict[str, Any]]:
    path = resolve_registry_path(graph)
    if path is None or not path.exists():
        add_error(errors, "source_registry", f"source registry not found: {path}")
        return {}
    try:
        registry = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(errors, "source_registry", f"cannot read {path}: {exc}")
        return {}
    return {
        source["source_id"]: source
        for source in registry.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }


def compatible_source_refs(
    knowledge: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
    *,
    require_publishable: bool = False,
) -> list[str]:
    compatible = []
    claim_type = knowledge.get("claim_type")
    knowledge_data_types = set(knowledge.get("data_types", []))
    for source_ref in knowledge.get("source_refs", []):
        source = sources_by_id.get(source_ref)
        if source is None:
            continue
        if claim_type not in source.get("supported_claim_types", []):
            continue
        source_data_types = set(
            source.get("supported_data_types", [source.get("data_type")])
        )
        if not knowledge_data_types <= source_data_types:
            continue
        if (
            knowledge.get("claim_basis") == "project_policy"
            and source.get("source_kind") != "project_policy"
        ):
            continue
        if require_publishable:
            authorization = source.get("license_or_authorization", {})
            usage_rights = source.get("usage_rights", {})
            if (
                source.get("status") != "verified"
                or authorization.get("publishable") is not True
                or usage_rights.get("citation_allowed") is not True
            ):
                continue
        compatible.append(source_ref)
    return compatible


def validate_knowledge_provenance(
    nodes_by_id: dict[str, dict[str, Any]],
    sources_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    allowed_bases = {"external_reference", "curriculum_draft", "project_policy"}
    for knowledge in (
        node for node in nodes_by_id.values() if node.get("type") == "KNG"
    ):
        node_id = knowledge["id"]
        claim_type = knowledge.get("claim_type")
        claim_basis = knowledge.get("claim_basis")
        source_refs = knowledge.get("source_refs")
        if not isinstance(claim_type, str) or not claim_type:
            add_error(errors, "knowledge_claim_type", f"{node_id}: claim_type required")
        if claim_basis not in allowed_bases:
            add_error(errors, "knowledge_claim_basis", f"{node_id}: invalid claim_basis")
        if not isinstance(source_refs, list):
            add_error(errors, "knowledge_source", f"{node_id}: source_refs must be an array")
            continue
        if claim_basis == "curriculum_draft" and source_refs:
            add_error(
                errors,
                "knowledge_source_scope",
                f"{node_id}: curriculum_draft must not cite authority sources",
            )
        missing_refs = sorted(ref for ref in source_refs if ref not in sources_by_id)
        if missing_refs:
            add_error(
                errors,
                "knowledge_source",
                f"{node_id}: unresolved sources {missing_refs}",
            )
        if source_refs and len(compatible_source_refs(knowledge, sources_by_id)) != len(
            source_refs
        ):
            add_error(
                errors,
                "knowledge_source_scope",
                f"{node_id}: one or more sources do not support {claim_type!r}",
            )
        if claim_basis in {"external_reference", "project_policy"} and not source_refs:
            add_error(
                errors,
                "knowledge_source",
                f"{node_id}: {claim_basis} requires a source",
            )


def validate_task_traceability(
    graph: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    sources_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    inbound_support: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        if edge.get("relation") != "SUP":
            continue
        source = nodes_by_id.get(edge.get("source"))
        if source is not None:
            inbound_support[edge.get("target")].append(source)

    for task in (node for node in nodes_by_id.values() if node.get("type") == "TSK"):
        supporters = inbound_support[task["id"]]
        capabilities = [node for node in supporters if node.get("type") == "CAP"]
        knowledge = [node for node in supporters if node.get("type") == "KNG"]
        if not capabilities or not knowledge:
            add_error(
                errors,
                "task_traceability",
                f"{task['id']}: requires inbound CAP and KNG support",
            )

        links = task.get("teaching_unit_links")
        if not isinstance(links, list):
            add_error(
                errors,
                "teaching_unit_links",
                f"{task['id']}: teaching_unit_links must be an array",
            )
            continue
        for link in links:
            expected_consumable = (
                link.get("review_status") == "published"
                and link.get("student_visible") is True
                and link.get("in_student_visible_index") is True
            )
            if link.get("consumable") is not expected_consumable:
                add_error(
                    errors,
                    "publication_gate",
                    f"{task['id']}: invalid link gate for {link.get('unit_id')}",
                )

        if task.get("status") == "published" or task.get("student_visible") is True:
            verified_sources = [
                source_ref
                for node in knowledge
                for source_ref in compatible_source_refs(
                    node, sources_by_id, require_publishable=True
                )
            ]
            if not verified_sources:
                add_error(
                    errors,
                    "task_traceability",
                    f"{task['id']}: published/visible task lacks verified sources",
                )


def validate_scenarios(
    graph: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], errors: list[str]
) -> None:
    scenarios = {
        node_id: node
        for node_id, node in nodes_by_id.items()
        if node.get("type") == "SCN"
    }
    covered = set()
    for scenario_id, scenario in scenarios.items():
        supported = scenario.get("supported_data_types")
        if not isinstance(supported, list) or not supported:
            add_error(
                errors,
                "scenario_data_types",
                f"{scenario_id}: supported_data_types required",
            )
        elif set(supported) != set(scenario.get("data_types", [])):
            add_error(
                errors,
                "scenario_data_types",
                f"{scenario_id}: data_types must match supported_data_types",
            )

    for edge in graph.get("edges", []):
        if edge.get("relation") != "INSCN":
            continue
        source = nodes_by_id.get(edge.get("source"))
        scenario = scenarios.get(edge.get("target"))
        if source is None or scenario is None:
            continue
        covered.add(scenario["id"])
        metadata = edge.get("metadata")
        if not isinstance(metadata, dict):
            add_error(errors, "inscn_metadata", f"{edge.get('id')}: metadata required")
            continue
        required = {
            "rule_id",
            "base_rule_ref",
            "override_type",
            "data_types",
            "description",
            "review_status",
        }
        if not required <= metadata.keys():
            add_error(
                errors,
                "inscn_metadata",
                f"{edge.get('id')}: missing {sorted(required - metadata.keys())}",
            )
            continue
        base_rule = nodes_by_id.get(metadata["base_rule_ref"])
        if base_rule is None or base_rule.get("type") != "KNG":
            add_error(
                errors,
                "inscn_base_rule",
                f"{edge.get('id')}: base_rule_ref must resolve to KNG",
            )
        if metadata["override_type"] not in {"add", "replace"}:
            add_error(
                errors,
                "inscn_override_type",
                f"{edge.get('id')}: invalid override_type",
            )
        if metadata["review_status"] not in {"draft", "reviewed", "published"}:
            add_error(
                errors,
                "inscn_review_status",
                f"{edge.get('id')}: invalid review_status",
            )
        edge_types = metadata["data_types"]
        if (
            not isinstance(edge_types, list)
            or not edge_types
            or not set(edge_types) <= set(source.get("data_types", []))
            or not set(edge_types) <= set(scenario.get("supported_data_types", []))
        ):
            add_error(
                errors,
                "inscn_data_type",
                f"{edge.get('id')}: rule data_types are incompatible",
            )
        if (
            isinstance(edge_types, list)
            and edge_types
            and base_rule is not None
            and base_rule.get("type") == "KNG"
            and not set(edge_types) <= set(base_rule.get("data_types", []))
        ):
            add_error(
                errors,
                "inscn_base_data_type",
                f"{edge.get('id')}: base KNG data_types are incompatible",
            )
    missing_coverage = sorted(set(scenarios) - covered)
    if missing_coverage:
        add_error(
            errors,
            "scenario_coverage",
            f"scenarios without INSCN rules: {missing_coverage}",
        )


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    validate_schema_and_counts(graph, errors)
    nodes_by_id = validate_ids_and_endpoints(graph, errors)
    validate_pre_acyclicity(graph, nodes_by_id, errors)
    sources_by_id = load_source_registry(graph, errors)
    validate_knowledge_provenance(nodes_by_id, sources_by_id, errors)
    validate_task_traceability(graph, nodes_by_id, sources_by_id, errors)
    validate_scenarios(graph, nodes_by_id, errors)
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate schema, counts, topology, traceability, and scenarios."
    )
    parser.add_argument("graph", type=Path, help="Path to graph JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        graph = load_json(args.graph)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[graph_read] cannot read {args.graph}: {exc}")
        return 1

    errors = validate_graph(graph)
    if errors:
        print(f"Graph validation failed with {len(errors)} error(s):")
        for error in errors:
            print(f"- {error}")
        return 1

    checks = (
        "schema/version",
        "exact counts",
        "unique IDs",
        "edge endpoints/types",
        "PRE acyclicity",
        "claim provenance",
        "task traceability",
        "scenario compatibility",
    )
    for check in checks:
        print(f"PASS {check}")
    print(
        "Graph validation succeeded: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
