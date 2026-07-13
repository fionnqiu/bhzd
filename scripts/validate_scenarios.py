#!/usr/bin/env python3
"""Validate complete Task 5 scenario envelopes against the graph catalog."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_REGISTRY = ROOT / "data" / "sources" / "source-registry.json"
DEFAULT_REVIEW_REGISTRY = ROOT / "data" / "reviews" / "scenario-review-registry.json"
EXPECTED_SCHEMA_VERSION = "1.0.0"
EXPECTED_ROOT_KEYS = {"schema_version", "scenario"}
DATA_TYPE_ORDER = ("text", "image", "audio", "video")
DATA_TYPE_SET = set(DATA_TYPE_ORDER)
NODE_TYPES = ("CAP", "KNG", "TSK", "SCN", "RES", "CERT")
REF_PATTERNS = {
    prefix: re.compile(rf"^{prefix}(?:-[A-Z0-9]+)+-\d{{3}}$")
    for prefix in ("CAP", "KNG", "SCN", "SCNR", "SRC", "TSK", "EX")
}
REVIEW_ID_PATTERN = re.compile(r"^REVIEW(?:-[A-Z0-9]+)+-\d{3}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LIFECYCLE_FIELDS = {
    "review_status",
    "student_visible",
    "review_records",
    "publication_scope",
    "human_release_allowed",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def add_error(errors: list[str], code: str, message: str) -> None:
    errors.append(f"[{code}] {message}")


def strip_lifecycle(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_lifecycle(item)
            for key, item in value.items()
            if key not in LIFECYCLE_FIELDS
        }
    if isinstance(value, list):
        return [strip_lifecycle(item) for item in value]
    return value


def scenario_content_digest(document: Any) -> str:
    canonical = json.dumps(
        strip_lifecycle(copy.deepcopy(document)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def unique_registry_index(
    registry: Any,
    *,
    records_key: str,
    id_key: str,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(registry, dict):
        add_error(errors, f"{label}_registry", f"{label} registry must be an object")
        return {}
    records = registry.get(records_key)
    if not isinstance(records, list):
        add_error(
            errors,
            f"{label}_registry",
            f"{label} registry {records_key} must be an array",
        )
        return {}
    index: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            add_error(
                errors,
                f"{label}_registry",
                f"{label} registry record {position} must be an object",
            )
            continue
        record_id = record.get(id_key)
        if not isinstance(record_id, str) or not record_id:
            add_error(
                errors,
                f"{label}_registry",
                f"{label} registry record {position} requires {id_key}",
            )
            continue
        if record_id in index:
            add_error(errors, f"{label}_registry", f"duplicate {id_key}: {record_id}")
            continue
        index[record_id] = record
    return index


def validate_source_registry(
    source_registry: Any, errors: list[str]
) -> dict[str, dict[str, Any]]:
    sources = unique_registry_index(
        source_registry,
        records_key="sources",
        id_key="source_id",
        label="source",
        errors=errors,
    )
    return sources


def source_is_eligible(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    authorization = source.get("license_or_authorization")
    rights = source.get("usage_rights")
    return bool(
        source.get("source_kind") == "project_policy"
        and source.get("authority_scope") == "local_project_policy_only"
        and source.get("status") == "verified"
        and source.get("publication_scope") == "development_only"
        and source.get("human_release_allowed") is False
        and isinstance(authorization, dict)
        and authorization.get("publishable") is True
        and isinstance(rights, dict)
        and rights.get("citation_allowed") is True
        and rights.get("asset_redistribution_allowed") is False
    )


def validate_scenario_review_registry(
    review_registry: Any, errors: list[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(review_registry, dict):
        add_error(errors, "review_registry", "scenario review registry must be an object")
        return {}
    if review_registry.get("schema_version") != "1.0.0":
        add_error(errors, "review_registry", "scenario review schema_version must be 1.0.0")
    contract = review_registry.get("digest_contract")
    excluded = contract.get("excluded_fields") if isinstance(contract, dict) else None
    if (
        not isinstance(excluded, list)
        or not all(isinstance(field, str) for field in excluded)
        or set(excluded) != LIFECYCLE_FIELDS
    ):
        add_error(
            errors,
            "review_registry",
            "scenario review digest_contract must declare the lifecycle exclusions",
        )
    reviews = unique_registry_index(
        review_registry,
        records_key="records",
        id_key="review_id",
        label="review",
        errors=errors,
    )
    required = {
        "review_id",
        "reviewer_id",
        "reviewer_type",
        "independent_of_implementation",
        "reviewed_at",
        "reviewed_commit",
        "scope",
        "scenario_versions",
        "decision",
        "findings",
        "finding_count",
        "remaining_risks",
        "publication_scope",
        "human_release_allowed",
        "authorizes_publication",
    }
    for review_id, review in reviews.items():
        missing = sorted(required - review.keys())
        if missing:
            add_error(errors, "review_registry", f"{review_id} missing {missing[0]}")
            continue
        if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
            add_error(errors, "review_registry", f"invalid review_id: {review_id}")
        for field in ("reviewer_id", "reviewed_at"):
            if not isinstance(review.get(field), str) or not review[field]:
                add_error(errors, "review_registry", f"{review_id} has invalid {field}")
        if review.get("reviewer_type") not in {"ai_agent", "human"}:
            add_error(errors, "review_registry", f"{review_id} has invalid reviewer_type")
        if review.get("reviewer_type") == "ai_agent" and review.get(
            "independent_of_implementation"
        ) is not True:
            add_error(errors, "review_independence", f"{review_id} AI review is not independent")
        if not isinstance(review.get("reviewed_commit"), str) or COMMIT_PATTERN.fullmatch(
            review["reviewed_commit"]
        ) is None:
            add_error(errors, "review_registry", f"{review_id} has invalid reviewed_commit")
        if review.get("decision") != "approved" or review.get(
            "authorizes_publication"
        ) is not True:
            add_error(errors, "review_approval", f"{review_id} does not authorize publication")
        if review.get("publication_scope") != "development_only" or review.get(
            "human_release_allowed"
        ) is not False:
            add_error(errors, "review_approval", f"{review_id} is not development-only")
        findings = review.get("findings")
        if not isinstance(findings, list) or review.get("finding_count") != len(findings):
            add_error(errors, "review_registry", f"{review_id} finding_count mismatch")
        if not isinstance(review.get("remaining_risks"), list):
            add_error(errors, "review_registry", f"{review_id} remaining_risks must be an array")

        scope = review.get("scope")
        scenario_ids = scope.get("scenario_ids") if isinstance(scope, dict) else None
        rule_ids = scope.get("rule_ids") if isinstance(scope, dict) else None
        if not isinstance(scope, dict) or scope.get(
            "publication_scope"
        ) != "development_only" or scope.get("human_release_allowed") is not False:
            add_error(
                errors,
                "review_approval",
                f"{review_id} scope is not development-only",
            )
        if not isinstance(scenario_ids, list) or not scenario_ids or not all(
            valid_ref(item, "SCN") for item in scenario_ids
        ) or len(scenario_ids) != len(set(scenario_ids)):
            add_error(errors, "review_registry", f"{review_id} has invalid scenario scope")
            scenario_ids = []
        if not isinstance(rule_ids, list) or not rule_ids or not all(
            valid_ref(item, "SCNR") for item in rule_ids
        ) or len(rule_ids) != len(set(rule_ids)):
            add_error(errors, "review_registry", f"{review_id} has invalid rule scope")
            rule_ids = []
        versions = review.get("scenario_versions")
        if not isinstance(versions, list):
            add_error(errors, "review_registry", f"{review_id} scenario_versions must be an array")
            continue
        version_ids: list[str] = []
        for version in versions:
            if not isinstance(version, dict):
                add_error(errors, "review_registry", f"{review_id} has invalid scenario version")
                continue
            scenario_id = version.get("scenario_id")
            digest = version.get("content_digest")
            if not valid_ref(scenario_id, "SCN"):
                add_error(errors, "review_registry", f"{review_id} has invalid scenario_id")
                continue
            version_ids.append(scenario_id)
            if version.get("schema_version") != EXPECTED_SCHEMA_VERSION:
                add_error(errors, "review_registry", f"{review_id} has invalid schema_version")
            if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
                add_error(errors, "review_registry", f"{review_id} has invalid content_digest")
        if len(version_ids) != len(set(version_ids)) or set(version_ids) != set(
            scenario_ids
        ):
            add_error(errors, "review_registry", f"{review_id} scope/version mismatch")
    return reviews


def valid_ref(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and REF_PATTERNS[prefix].fullmatch(value) is not None


def validate_ref_list(
    value: Any,
    *,
    prefix: str,
    location: str,
    errors: list[str],
    code: str,
) -> list[str]:
    if not isinstance(value, list) or not value:
        add_error(errors, code, f"{location} must be a nonempty array")
        return []

    valid_values: list[str] = []
    for index, ref in enumerate(value):
        if not valid_ref(ref, prefix):
            add_error(
                errors,
                code,
                f"{location}[{index}] must be a canonical {prefix}-* reference",
            )
            continue
        valid_values.append(ref)

    duplicates = sorted(
        ref for ref, count in Counter(valid_values).items() if count > 1
    )
    if duplicates:
        add_error(errors, code, f"{location} contains duplicate references: {duplicates}")
    return valid_values


def validate_data_types(
    value: Any,
    *,
    location: str,
    errors: list[str],
    code: str,
) -> list[str]:
    if not isinstance(value, list) or not value:
        add_error(errors, code, f"{location} must be a nonempty array")
        return []
    valid_values = [
        data_type
        for data_type in value
        if isinstance(data_type, str) and data_type in DATA_TYPE_SET
    ]
    if len(valid_values) != len(value):
        add_error(
            errors,
            code,
            f"{location} may contain only {list(DATA_TYPE_ORDER)}",
        )

    if len(valid_values) != len(set(valid_values)):
        add_error(errors, code, f"{location} must not contain duplicates")
    canonical = [
        data_type for data_type in DATA_TYPE_ORDER if data_type in valid_values
    ]
    if valid_values != canonical:
        add_error(
            errors,
            code,
            f"{location} must use canonical text/image/audio/video order",
        )
    return valid_values


def validate_review_refs(
    value: Any,
    *,
    location: str,
    errors: list[str],
    required: bool,
) -> list[str]:
    if not isinstance(value, list):
        add_error(errors, "review_refs", f"{location} must be an array")
        return []
    if required and not value:
        add_error(errors, "review_approval", f"{location} requires an approved review")
    valid_values = []
    for index, review_ref in enumerate(value):
        if not isinstance(review_ref, str) or REVIEW_ID_PATTERN.fullmatch(review_ref) is None:
            add_error(
                errors,
                "review_refs",
                f"{location}[{index}] must be a canonical REVIEW-* reference",
            )
            continue
        valid_values.append(review_ref)
    if len(valid_values) != len(set(valid_values)):
        add_error(errors, "review_refs", f"{location} must not contain duplicates")
    return valid_values


def validate_policy_sources(
    source_refs: list[str],
    *,
    sources: dict[str, dict[str, Any]],
    location: str,
    errors: list[str],
) -> None:
    for source_ref in source_refs:
        if not source_is_eligible(sources.get(source_ref)):
            add_error(
                errors,
                "source_eligibility",
                f"{location} source {source_ref} is not an eligible local development policy",
            )


def review_version_for_scenario(
    review: dict[str, Any], scenario_id: str, schema_version: str
) -> dict[str, Any] | None:
    scope = review.get("scope")
    if not isinstance(scope, dict) or scenario_id not in scope.get("scenario_ids", []):
        return None
    versions = review.get("scenario_versions")
    if not isinstance(versions, list):
        return None
    return next(
        (
            version
            for version in versions
            if isinstance(version, dict)
            and version.get("scenario_id") == scenario_id
            and version.get("schema_version") == schema_version
        ),
        None,
    )


def approved_scenario_reviews(
    review_refs: list[str],
    *,
    reviews: dict[str, dict[str, Any]],
    scenario_id: str,
    schema_version: str,
    content_digest: str,
    errors: list[str],
    location: str,
) -> list[dict[str, Any]]:
    matching_versions: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for review_ref in review_refs:
        review = reviews.get(review_ref)
        if review is None:
            add_error(errors, "review_ref", f"{location} references unknown review {review_ref}")
            continue
        if review.get("decision") != "approved" or review.get(
            "authorizes_publication"
        ) is not True:
            continue
        if review.get("reviewer_type") == "ai_agent" and review.get(
            "independent_of_implementation"
        ) is not True:
            continue
        version = review_version_for_scenario(review, scenario_id, schema_version)
        if version is not None:
            matching_versions.append((review, version))
    approved = [
        review
        for review, version in matching_versions
        if version.get("content_digest") == content_digest
    ]
    if approved:
        return approved
    if matching_versions:
        add_error(
            errors,
            "review_content_digest",
            f"{location} content_digest does not match its approved review",
        )
    else:
        add_error(
            errors,
            "review_approval",
            f"{location} requires a complete digest-bound approval",
        )
    return []


def build_catalog_index(
    catalog: Any, errors: list[str]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    if not isinstance(catalog, dict):
        add_error(errors, "catalog_root", "graph catalog root must be an object")
        return {}, {}, {}, {}
    nodes = catalog.get("nodes")
    if not isinstance(nodes, dict):
        add_error(errors, "catalog_nodes", "graph catalog nodes must be an object")
        return {}, {}, {}, {}

    nodes_by_id: dict[str, dict[str, Any]] = {}
    node_types_by_id: dict[str, str] = {}
    node_data_types_by_id: dict[str, list[str]] = {}
    scenario_supported_types_by_id: dict[str, list[str]] = {}
    for node_type in NODE_TYPES:
        records = nodes.get(node_type)
        if not isinstance(records, list):
            add_error(
                errors,
                "catalog_nodes",
                f"graph catalog nodes.{node_type} must be an array",
            )
            continue
        for index, node in enumerate(records):
            if not isinstance(node, dict):
                add_error(
                    errors,
                    "catalog_nodes",
                    f"nodes.{node_type}[{index}] must be an object",
                )
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id:
                add_error(
                    errors,
                    "catalog_node_id",
                    f"nodes.{node_type}[{index}] requires a string id",
                )
                continue
            if node_id in nodes_by_id:
                add_error(errors, "catalog_node_id", f"duplicate graph node id: {node_id}")
                continue
            nodes_by_id[node_id] = node
            node_types_by_id[node_id] = node_type
            node_data_types_by_id[node_id] = validate_data_types(
                node.get("data_types"),
                location=f"nodes.{node_type}[{index}].data_types",
                errors=errors,
                code="catalog_node_data_types",
            )
            if node_type == "SCN":
                supported_types = validate_data_types(
                    node.get("supported_data_types"),
                    location=f"nodes.SCN[{index}].supported_data_types",
                    errors=errors,
                    code="catalog_scenario_supported_data_types",
                )
                scenario_supported_types_by_id[node_id] = supported_types
                if node_data_types_by_id[node_id] != supported_types:
                    add_error(
                        errors,
                        "catalog_scenario_supported_data_types",
                        f"{node_id} data_types must match supported_data_types",
                    )
    return (
        nodes_by_id,
        node_types_by_id,
        node_data_types_by_id,
        scenario_supported_types_by_id,
    )


def validate_inscn_edges(
    catalog: Any,
    nodes_by_id: dict[str, dict[str, Any]],
    node_types_by_id: dict[str, str],
    node_data_types_by_id: dict[str, list[str]],
    scenario_supported_types_by_id: dict[str, list[str]],
    errors: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(catalog, dict):
        return {}
    relations = catalog.get("relations")
    if not isinstance(relations, dict):
        add_error(errors, "inscn_schema", "graph catalog relations must be an object")
        return {}
    edges = relations.get("INSCN")
    if not isinstance(edges, list):
        add_error(errors, "inscn_schema", "graph catalog INSCN must be an array")
        return {}

    by_rule_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rule_ids: list[str] = []
    for index, edge in enumerate(edges):
        location = f"relations.INSCN[{index}]"
        if not isinstance(edge, dict):
            add_error(errors, "inscn_schema", f"{location} must be an object")
            continue
        source = edge.get("source")
        target = edge.get("target")
        source_node = nodes_by_id.get(source) if isinstance(source, str) else None
        target_node = nodes_by_id.get(target) if isinstance(target, str) else None
        if source_node is None or node_types_by_id.get(source) not in {"CAP", "KNG", "TSK"}:
            add_error(errors, "inscn_source", f"{location}.source must resolve to CAP/KNG/TSK")
        if target_node is None or node_types_by_id.get(target) != "SCN":
            add_error(errors, "inscn_target", f"{location}.target must resolve to SCN")

        metadata = edge.get("metadata")
        if not isinstance(metadata, dict):
            add_error(errors, "inscn_metadata", f"{location}.metadata must be an object")
            continue
        edge_status = metadata.get("review_status")
        if edge_status not in {"draft", "reviewed", "published"}:
            add_error(
                errors,
                "inscn_review_status",
                f"{location}.metadata.review_status is invalid",
            )
        if edge_status in {"reviewed", "published"}:
            validate_review_refs(
                metadata.get("review_records"),
                location=f"{location}.metadata.review_records",
                errors=errors,
                required=True,
            )
            if (
                metadata.get("publication_scope") != "development_only"
                or metadata.get("human_release_allowed") is not False
            ):
                add_error(
                    errors,
                    "inscn_publication_scope",
                    f"{location}.metadata must remain development-only",
                )
        rule_id = metadata.get("rule_id")
        if not valid_ref(rule_id, "SCNR"):
            add_error(
                errors,
                "inscn_rule_id",
                f"{location}.metadata.rule_id must be a canonical SCNR-* reference",
            )
        else:
            rule_ids.append(rule_id)
            by_rule_id[rule_id].append(edge)

        base_rule_ref = metadata.get("base_rule_ref")
        base_rule = (
            nodes_by_id.get(base_rule_ref)
            if valid_ref(base_rule_ref, "KNG")
            else None
        )
        if base_rule is None or node_types_by_id.get(base_rule_ref) != "KNG":
            add_error(
                errors,
                "inscn_base_rule_ref",
                f"{location}.metadata.base_rule_ref must resolve to KNG",
            )

        if metadata.get("override_type") not in {"add", "replace"}:
            add_error(
                errors,
                "inscn_override_type",
                f"{location}.metadata.override_type must be add or replace",
            )
        edge_types = validate_data_types(
            metadata.get("data_types"),
            location=f"{location}.metadata.data_types",
            errors=errors,
            code="inscn_data_types",
        )
        edge_type_set = set(edge_types)
        if source_node is not None and not edge_type_set <= set(
            node_data_types_by_id.get(source, [])
        ):
            add_error(
                errors,
                "inscn_data_type",
                f"{location} data_types are incompatible with source {source}",
            )
        if target_node is not None and not edge_type_set <= set(
            scenario_supported_types_by_id.get(target, [])
        ):
            add_error(
                errors,
                "inscn_data_type",
                f"{location} data_types are incompatible with target {target}",
            )
        if base_rule is not None and not edge_type_set <= set(
            node_data_types_by_id.get(base_rule_ref, [])
        ):
            add_error(
                errors,
                "inscn_data_type",
                f"{location} data_types are incompatible with base rule {base_rule_ref}",
            )

    for rule_id, count in sorted(Counter(rule_ids).items()):
        if count > 1:
            add_error(
                errors,
                "inscn_rule_id",
                f"graph catalog has {count} INSCN edges for rule_id {rule_id}",
            )
    return dict(by_rule_id)


def validate_scenario_documents(
    documents: Iterable[Any],
    catalog: Any,
    *,
    source_registry: Any | None = None,
    review_registry: Any | None = None,
) -> list[str]:
    """Return deterministic contract errors for complete scenario documents."""

    errors: list[str] = []
    if isinstance(documents, (str, bytes, dict)) or not isinstance(documents, Iterable):
        add_error(errors, "documents", "scenario documents must be an iterable of envelopes")
        return errors
    document_list = list(documents)
    if not document_list:
        add_error(errors, "documents", "at least one scenario document is required")
        return errors

    if source_registry is None:
        try:
            source_registry = load_json(DEFAULT_SOURCE_REGISTRY)
        except (OSError, json.JSONDecodeError) as exc:
            add_error(errors, "source_registry", f"cannot read source registry: {exc}")
            source_registry = {}
    if review_registry is None:
        try:
            review_registry = load_json(DEFAULT_REVIEW_REGISTRY)
        except (OSError, json.JSONDecodeError) as exc:
            add_error(errors, "review_registry", f"cannot read scenario review registry: {exc}")
            review_registry = {}
    sources = validate_source_registry(source_registry, errors)
    reviews = validate_scenario_review_registry(review_registry, errors)

    (
        nodes_by_id,
        node_types_by_id,
        node_data_types_by_id,
        scenario_supported_types_by_id,
    ) = build_catalog_index(catalog, errors)
    inscn_by_rule_id = validate_inscn_edges(
        catalog,
        nodes_by_id,
        node_types_by_id,
        node_data_types_by_id,
        scenario_supported_types_by_id,
        errors,
    )
    seen_scenario_ids: set[str] = set()
    seen_rule_ids: set[str] = set()
    seen_example_ids: set[str] = set()

    for document_index, document in enumerate(document_list):
        document_location = f"documents[{document_index}]"
        if not isinstance(document, dict):
            add_error(errors, "document_root", f"{document_location} must be an object")
            continue
        if set(document) != EXPECTED_ROOT_KEYS:
            missing = sorted(EXPECTED_ROOT_KEYS - set(document))
            unknown = sorted(set(document) - EXPECTED_ROOT_KEYS)
            add_error(
                errors,
                "root_keys",
                f"{document_location} requires canonical root keys; missing={missing}, unknown={unknown}",
            )
        if document.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            add_error(
                errors,
                "schema_version",
                f"{document_location}.schema_version must equal {EXPECTED_SCHEMA_VERSION}",
            )

        scenario = document.get("scenario")
        if not isinstance(scenario, dict):
            add_error(errors, "scenario_schema", f"{document_location}.scenario must be an object")
            continue
        scenario_id = scenario.get("id")
        scenario_location = (
            scenario_id if isinstance(scenario_id, str) and scenario_id else document_location
        )
        if not valid_ref(scenario_id, "SCN"):
            add_error(
                errors,
                "scenario_id",
                f"{document_location}.scenario.id must be a canonical SCN-* reference",
            )
        elif scenario_id in seen_scenario_ids:
            add_error(errors, "duplicate_scenario_id", f"duplicate scenario id: {scenario_id}")
        else:
            seen_scenario_ids.add(scenario_id)

        scenario_status = scenario.get("review_status")
        if scenario_status not in {"draft", "reviewed", "published"}:
            add_error(
                errors,
                "review_status",
                f"{scenario_location}.review_status is invalid",
            )
        scenario_review_refs = validate_review_refs(
            scenario.get("review_records"),
            location=f"{scenario_location}.review_records",
            errors=errors,
            required=scenario_status in {"reviewed", "published"},
        )
        if scenario_status == "published" and scenario.get("student_visible") is not True:
            add_error(
                errors,
                "publication_visibility",
                f"{scenario_location} published scenario must be student_visible",
            )
        if scenario_status != "published" and scenario.get("student_visible") is True:
            add_error(
                errors,
                "publication_visibility",
                f"{scenario_location} non-published scenario cannot be student_visible",
            )
        if scenario_status in {"reviewed", "published"} and (
            scenario.get("publication_scope") != "development_only"
            or scenario.get("human_release_allowed") is not False
        ):
            add_error(
                errors,
                "publication_scope",
                f"{scenario_location} must remain development-only",
            )
        scenario_digest = scenario_content_digest(document)
        scenario_approvals: list[dict[str, Any]] = []
        if (
            scenario_status in {"reviewed", "published"}
            and isinstance(scenario_id, str)
        ):
            scenario_approvals = approved_scenario_reviews(
                scenario_review_refs,
                reviews=reviews,
                scenario_id=scenario_id,
                schema_version=document.get("schema_version", ""),
                content_digest=scenario_digest,
                errors=errors,
                location=scenario_location,
            )

        supported_types = validate_data_types(
            scenario.get("supported_data_types"),
            location=f"{scenario_location}.supported_data_types",
            errors=errors,
            code="supported_data_types",
        )
        supported_type_set = set(supported_types)
        scenario_source_refs = validate_ref_list(
            scenario.get("source_refs"),
            prefix="SRC",
            location=f"{scenario_location}.source_refs",
            errors=errors,
            code="source_refs",
        )
        if scenario_status in {"reviewed", "published"}:
            validate_policy_sources(
                scenario_source_refs,
                sources=sources,
                location=scenario_location,
                errors=errors,
            )
        capability_refs = validate_ref_list(
            scenario.get("applicable_capability_refs"),
            prefix="CAP",
            location=f"{scenario_location}.applicable_capability_refs",
            errors=errors,
            code="capability_refs",
        )

        graph_scenario = nodes_by_id.get(scenario_id) if isinstance(scenario_id, str) else None
        if graph_scenario is None or node_types_by_id.get(scenario_id) != "SCN":
            add_error(
                errors,
                "scenario_ref",
                f"{scenario_location} must resolve to a graph SCN node",
            )
        elif scenario_supported_types_by_id.get(scenario_id, []) != supported_types:
            add_error(
                errors,
                "scenario_graph_types",
                f"{scenario_location} supported_data_types must exactly match the graph SCN node",
            )
        elif scenario_status in {"reviewed", "published"}:
            if graph_scenario.get("status") != scenario_status:
                add_error(
                    errors,
                    "scenario_graph_lifecycle",
                    f"{scenario_location} graph status must match the scenario document",
                )
            for field in (
                "student_visible",
                "review_records",
                "publication_scope",
                "human_release_allowed",
            ):
                if graph_scenario.get(field) != scenario.get(field):
                    add_error(
                        errors,
                        "scenario_graph_lifecycle",
                        f"{scenario_location} graph {field} must match the scenario document",
                    )

        covered_capability_types: set[str] = set()
        for capability_ref in capability_refs:
            capability = nodes_by_id.get(capability_ref)
            if capability is None or node_types_by_id.get(capability_ref) != "CAP":
                add_error(
                    errors,
                    "capability_ref",
                    f"{scenario_location}: unknown CAP reference {capability_ref}",
                )
                continue
            capability_types = set(node_data_types_by_id.get(capability_ref, []))
            if not capability_types or not capability_types <= supported_type_set:
                add_error(
                    errors,
                    "capability_data_type",
                    f"{scenario_location}: {capability_ref} is incompatible with supported_data_types",
                )
                continue
            covered_capability_types.update(capability_types)
        missing_capability_types = sorted(
            supported_type_set - covered_capability_types,
            key=DATA_TYPE_ORDER.index,
        )
        if missing_capability_types:
            add_error(
                errors,
                "capability_coverage",
                f"{scenario_location} lacks applicable CAP coverage for {missing_capability_types}",
            )

        overrides = scenario.get("overrides")
        if not isinstance(overrides, list) or not overrides:
            add_error(errors, "overrides", f"{scenario_location}.overrides must be a nonempty array")
            overrides = []
        local_overrides: dict[str, dict[str, Any]] = {}
        override_types: set[str] = set()
        for override_index, override in enumerate(overrides):
            override_location = f"{scenario_location}.overrides[{override_index}]"
            if not isinstance(override, dict):
                add_error(errors, "override_schema", f"{override_location} must be an object")
                continue
            override_status = override.get("review_status")
            if override_status not in {"draft", "reviewed", "published"}:
                add_error(
                    errors,
                    "review_status",
                    f"{override_location}.review_status is invalid",
                )
            override_review_refs = validate_review_refs(
                override.get("review_records"),
                location=f"{override_location}.review_records",
                errors=errors,
                required=override_status in {"reviewed", "published"},
            )
            if override_status in {"reviewed", "published"} and (
                override.get("publication_scope") != "development_only"
                or override.get("human_release_allowed") is not False
            ):
                add_error(
                    errors,
                    "publication_scope",
                    f"{override_location} must remain development-only",
                )
            rule_id = override.get("rule_id")
            if not valid_ref(rule_id, "SCNR"):
                add_error(
                    errors,
                    "rule_id",
                    f"{override_location}.rule_id must be a canonical SCNR-* reference",
                )
            else:
                if rule_id in seen_rule_ids:
                    add_error(errors, "duplicate_rule_id", f"duplicate rule id: {rule_id}")
                else:
                    seen_rule_ids.add(rule_id)
                local_overrides.setdefault(rule_id, override)

            data_type = override.get("data_type")
            if not isinstance(data_type, str) or data_type not in supported_type_set:
                add_error(
                    errors,
                    "override_data_type",
                    f"{override_location}.data_type must be declared by the scenario",
                )
            else:
                override_types.add(data_type)

            base_rule_ref = override.get("base_rule_ref")
            if not valid_ref(base_rule_ref, "KNG"):
                add_error(
                    errors,
                    "base_rule_ref",
                    f"{override_location}.base_rule_ref must be a canonical KNG-* reference",
                )
                base_rule = None
            else:
                base_rule = nodes_by_id.get(base_rule_ref)
                if base_rule is None or node_types_by_id.get(base_rule_ref) != "KNG":
                    add_error(
                        errors,
                        "base_rule_ref",
                        f"{override_location}.base_rule_ref must resolve to KNG",
                    )
                    base_rule = None
            if (
                base_rule is not None
                and isinstance(data_type, str)
                and data_type not in set(node_data_types_by_id.get(base_rule_ref, []))
            ):
                add_error(
                    errors,
                    "base_rule_data_type",
                    f"{override_location} data_type is incompatible with {base_rule_ref}",
                )

            if override.get("override_type") not in {"add", "replace"}:
                add_error(
                    errors,
                    "override_type",
                    f"{override_location}.override_type must be add or replace",
                )
            if not isinstance(override.get("content"), str) or not override["content"].strip():
                add_error(errors, "override_content", f"{override_location}.content is required")
            override_source_refs = validate_ref_list(
                override.get("source_refs"),
                prefix="SRC",
                location=f"{override_location}.source_refs",
                errors=errors,
                code="source_refs",
            )
            if override_status in {"reviewed", "published"}:
                validate_policy_sources(
                    override_source_refs,
                    sources=sources,
                    location=override_location,
                    errors=errors,
                )
                eligible_rule_reviews = []
                for review_ref in override_review_refs:
                    review = reviews.get(review_ref)
                    if review is None:
                        add_error(
                            errors,
                            "review_ref",
                            f"{override_location} references unknown review {review_ref}",
                        )
                        continue
                    scope = review.get("scope")
                    if review in scenario_approvals and isinstance(scope, dict) and rule_id in scope.get(
                        "rule_ids", []
                    ):
                        eligible_rule_reviews.append(review)
                if not eligible_rule_reviews:
                    add_error(
                        errors,
                        "review_approval",
                        f"{override_location} requires a digest-bound rule approval",
                    )

            if valid_ref(rule_id, "SCNR"):
                matching_edges = []
                for edge in inscn_by_rule_id.get(rule_id, []):
                    metadata = edge.get("metadata")
                    if not isinstance(metadata, dict):
                        continue
                    if (
                        edge.get("target") == scenario_id
                        and metadata.get("base_rule_ref") == base_rule_ref
                        and metadata.get("override_type") == override.get("override_type")
                        and isinstance(metadata.get("data_types"), list)
                        and data_type in metadata["data_types"]
                    ):
                        matching_edges.append(edge)
                if len(matching_edges) != 1:
                    add_error(
                        errors,
                        "inscn_match",
                        f"{override_location} must match exactly one INSCN edge; found {len(matching_edges)}",
                    )
                elif override_status in {"reviewed", "published"}:
                    metadata = matching_edges[0]["metadata"]
                    for field in (
                        "review_status",
                        "review_records",
                        "publication_scope",
                        "human_release_allowed",
                    ):
                        if metadata.get(field) != override.get(field):
                            add_error(
                                errors,
                                "inscn_lifecycle",
                                f"{override_location} INSCN {field} must match the override",
                            )

        if override_types != supported_type_set:
            add_error(
                errors,
                "override_coverage",
                f"{scenario_location} overrides must cover every supported data type exactly by type set",
            )

        examples = scenario.get("examples")
        if not isinstance(examples, list) or not examples:
            add_error(errors, "examples", f"{scenario_location}.examples must be a nonempty array")
            examples = []
        example_types: set[str] = set()
        for example_index, example in enumerate(examples):
            example_location = f"{scenario_location}.examples[{example_index}]"
            if not isinstance(example, dict):
                add_error(errors, "example_schema", f"{example_location} must be an object")
                continue
            example_id = example.get("example_id")
            if not valid_ref(example_id, "EX"):
                add_error(
                    errors,
                    "example_id",
                    f"{example_location}.example_id must be a canonical EX-* reference",
                )
            elif example_id in seen_example_ids:
                add_error(
                    errors,
                    "duplicate_example_id",
                    f"duplicate example id: {example_id}",
                )
            else:
                seen_example_ids.add(example_id)

            rule_id = example.get("rule_id")
            if not valid_ref(rule_id, "SCNR") or rule_id not in local_overrides:
                add_error(
                    errors,
                    "example_rule_ref",
                    f"{example_location}.rule_id must resolve to an override in the same scenario",
                )
                linked_override = None
            else:
                linked_override = local_overrides[rule_id]
            data_type = example.get("data_type")
            if not isinstance(data_type, str) or data_type not in supported_type_set:
                add_error(
                    errors,
                    "example_data_type",
                    f"{example_location}.data_type must be declared by the scenario",
                )
            else:
                example_types.add(data_type)
            if linked_override is not None and linked_override.get("data_type") != data_type:
                add_error(
                    errors,
                    "example_data_type",
                    f"{example_location}.data_type must match its override",
                )
            if not example.get("input"):
                add_error(errors, "example_input", f"{example_location}.input is required")
            if not example.get("expected"):
                add_error(errors, "example_expected", f"{example_location}.expected is required")
            if not isinstance(example.get("explanation"), str) or not example[
                "explanation"
            ].strip():
                add_error(
                    errors,
                    "example_explanation",
                    f"{example_location}.explanation is required",
                )

        if example_types != supported_type_set:
            add_error(
                errors,
                "example_coverage",
                f"{scenario_location} examples must cover every supported data type exactly by type set",
            )

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate complete scenario JSON envelopes against a graph catalog."
    )
    parser.add_argument(
        "--graph-catalog",
        type=Path,
        default=ROOT / "data" / "graph" / "graph-catalog.json",
        help="Graph catalog JSON (default: data/graph/graph-catalog.json)",
    )
    parser.add_argument(
        "--source-registry",
        type=Path,
        default=DEFAULT_SOURCE_REGISTRY,
        help="Source registry JSON (default: data/sources/source-registry.json)",
    )
    parser.add_argument(
        "--review-registry",
        type=Path,
        default=DEFAULT_REVIEW_REGISTRY,
        help="Scenario review registry JSON (default: data/reviews/scenario-review-registry.json)",
    )
    parser.add_argument("scenarios", type=Path, nargs="+", help="Scenario JSON files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    read_errors: list[str] = []
    try:
        catalog = load_json(args.graph_catalog)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(
            read_errors,
            "catalog_read",
            f"cannot read {args.graph_catalog}: {exc}",
        )
        catalog = None

    try:
        source_registry = load_json(args.source_registry)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(
            read_errors,
            "source_registry",
            f"cannot read {args.source_registry}: {exc}",
        )
        source_registry = {}
    try:
        review_registry = load_json(args.review_registry)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(
            read_errors,
            "review_registry",
            f"cannot read {args.review_registry}: {exc}",
        )
        review_registry = {}

    documents: list[Any] = []
    for path in args.scenarios:
        try:
            documents.append(load_json(path))
        except (OSError, json.JSONDecodeError) as exc:
            add_error(read_errors, "scenario_read", f"cannot read {path}: {exc}")

    errors = [
        *read_errors,
        *validate_scenario_documents(
            documents,
            catalog,
            source_registry=source_registry,
            review_registry=review_registry,
        ),
    ]
    if errors:
        print(f"Scenario validation failed with {len(errors)} error(s):")
        for error in errors:
            print(f"- {error}")
        return 1

    scenarios = [document["scenario"] for document in documents]
    override_count = sum(len(scenario["overrides"]) for scenario in scenarios)
    example_count = sum(len(scenario["examples"]) for scenario in scenarios)
    for check in (
        "full document envelopes",
        "canonical data types and references",
        "global scenario/rule/example identities",
        "CAP/KNG data-type compatibility",
        "unique INSCN override matches",
        "eligible local policy sources",
        "digest-bound development reviews",
    ):
        print(f"PASS {check}")
    print(
        "Scenario validation succeeded: "
        f"{len(documents)} documents, {len(scenarios)} scenarios, "
        f"{override_count} overrides, {example_count} examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
