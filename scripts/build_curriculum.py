#!/usr/bin/env python3
"""Build the canonical teaching-unit index from per-domain sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURRICULUM_ROOT = ROOT / "data" / "curriculum"
DEFAULT_CENTRAL = DEFAULT_CURRICULUM_ROOT / "teaching-units.json"
DEFAULT_SOURCE_REGISTRY = ROOT / "data" / "sources" / "source-registry.json"
DEFAULT_REVIEW_REGISTRY = ROOT / "data" / "reviews" / "content-review-registry.json"
DOMAIN_ORDER = ("text", "image", "audio", "video")
TASK3_SOURCE_DOMAINS = {"text", "image"}
TASK3_LEGACY_FALLBACK_DOMAINS = {"audio", "video"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def _load_domain(path: Path, domain: str) -> list[dict[str, Any]]:
    document = load_json(path)
    if document.get("schema_version") != "1.1.0":
        raise ValueError(f"{path} schema_version must be 1.1.0")
    if document.get("data_type") != domain:
        raise ValueError(f"{path} data_type must be {domain!r}")
    units = document.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError(f"{path} units must be a non-empty list")
    ids = []
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError(f"{path} contains a non-object teaching unit")
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            raise ValueError(f"{path} contains a teaching unit without an ID")
        if unit.get("data_type") != domain:
            raise ValueError(f"{unit_id} data_type must be {domain!r}")
        ids.append(unit_id)
    if ids != sorted(ids):
        raise ValueError(f"non-canonical teaching unit ordering in {path}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate teaching unit ID within {path}")
    return units


def _unique_index(records: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError(f"{label} must be a list")
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{label} must contain objects")
        record_id = record.get(key)
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(f"{label} record missing {key}")
        if record_id in index:
            raise ValueError(f"duplicate {key}: {record_id}")
        index[record_id] = record
    return index


def _validate_review_registry(review_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if review_registry.get("schema_version") != "1.0.0":
        raise ValueError("review registry schema_version must be 1.0.0")
    reviews = _unique_index(review_registry.get("records"), "review_id", "reviews")
    required = {
        "review_id",
        "reviewer_id",
        "reviewer_type",
        "reviewed_at",
        "reviewed_commit",
        "scope",
        "unit_versions",
        "decision",
        "findings",
        "finding_count",
        "remaining_risks",
        "authorizes_publication",
    }
    for review_id, review in reviews.items():
        missing = sorted(required - review.keys())
        if missing:
            raise ValueError(f"review {review_id} missing field: {missing[0]}")
        if review["reviewer_type"] not in {"human", "ai_agent"}:
            raise ValueError(f"review {review_id} has invalid reviewer_type")
        if review["decision"] not in {"approved", "changes_required", "rejected"}:
            raise ValueError(f"review {review_id} has invalid decision")
        if not isinstance(review["authorizes_publication"], bool):
            raise ValueError(f"review {review_id} authorizes_publication must be boolean")
        if review["decision"] != "approved" and review["authorizes_publication"]:
            raise ValueError(f"review {review_id} failed review cannot authorize publication")
        if not isinstance(review["findings"], list):
            raise ValueError(f"review {review_id} findings must be a list")
        if review["finding_count"] != len(review["findings"]):
            raise ValueError(f"review {review_id} finding_count mismatch")
        if not isinstance(review["remaining_risks"], list):
            raise ValueError(f"review {review_id} remaining_risks must be a list")
        scope = review["scope"]
        if not isinstance(scope, dict) or not isinstance(scope.get("unit_ids"), list):
            raise ValueError(f"review {review_id} scope.unit_ids must be a list")
        versions = review["unit_versions"]
        if not isinstance(versions, list):
            raise ValueError(f"review {review_id} unit_versions must be a list")
        version_ids = [version.get("unit_id") for version in versions if isinstance(version, dict)]
        if len(version_ids) != len(versions) or len(version_ids) != len(set(version_ids)):
            raise ValueError(f"review {review_id} unit_versions must have unique unit IDs")
        if set(version_ids) != set(scope["unit_ids"]):
            raise ValueError(f"review {review_id} scope/version unit mismatch")
        for version in versions:
            if not all(
                isinstance(version.get(field), str) and version[field]
                for field in ("unit_id", "data_version", "evaluation_version")
            ):
                raise ValueError(f"review {review_id} has incomplete unit version")
        for field in ("reviewer_id", "reviewed_at", "reviewed_commit"):
            if not isinstance(review[field], str) or not review[field]:
                raise ValueError(f"review {review_id} has invalid {field}")
    return reviews


def _review_approves_unit(review: dict[str, Any], unit: dict[str, Any]) -> bool:
    if review["decision"] != "approved" or review["authorizes_publication"] is not True:
        return False
    if unit["id"] not in review["scope"]["unit_ids"]:
        return False
    if review["reviewer_type"] == "ai_agent" and review.get(
        "independent_of_implementation"
    ) is not True:
        return False
    return any(
        version["unit_id"] == unit["id"]
        and version["data_version"] == unit["exercise"]["data_version"]
        and version["evaluation_version"]
        == unit["exercise"]["evaluation"]["version"]
        for version in review["unit_versions"]
    )


def validate_publication_contract(
    teaching_units: dict[str, Any],
    source_registry: dict[str, Any],
    review_registry: dict[str, Any],
) -> None:
    sources = _unique_index(source_registry.get("sources"), "source_id", "sources")
    reviews = _validate_review_registry(review_registry)
    units = teaching_units.get("units")
    if not isinstance(units, list):
        raise ValueError("teaching units must be a list")
    visible_ids = set(teaching_units.get("student_visible_unit_ids", []))

    for unit in units:
        unit_id = unit.get("id", "<unknown>")
        status = unit.get("review_status")
        if status not in {"draft", "reviewed", "published"}:
            raise ValueError(f"{unit_id} has invalid review_status")
        student_visible = unit.get("student_visible") is True
        if (student_visible or unit_id in visible_ids) and status != "published":
            raise ValueError(f"{unit_id} violates publication visibility gate")
        review_refs = unit.get("review_records")
        if (
            review_refs is None
            and status == "draft"
            and unit.get("data_type") in TASK3_LEGACY_FALLBACK_DOMAINS
        ):
            review_refs = []
        if not isinstance(review_refs, list) or any(
            not isinstance(review_ref, str) or not review_ref for review_ref in review_refs
        ):
            raise ValueError(f"{unit_id} review_records must be a string list")
        if len(review_refs) != len(set(review_refs)):
            raise ValueError(f"{unit_id} has duplicate review_records")
        unknown_reviews = sorted(set(review_refs) - reviews.keys())
        if unknown_reviews:
            raise ValueError(f"{unit_id} references unknown review: {unknown_reviews[0]}")
        if status == "draft":
            continue

        for source_ref in unit.get("source_refs", []):
            source = sources.get(source_ref)
            authorization = source.get("license_or_authorization", {}) if source else {}
            usage_rights = source.get("usage_rights", {}) if source else {}
            if not (
                source
                and source.get("status") == "verified"
                and authorization.get("publishable") is True
                and usage_rights.get("citation_allowed") is True
            ):
                raise ValueError(
                    f"{unit_id} source eligibility failed for {source_ref}"
                )
        if not any(
            _review_approves_unit(reviews[review_ref], unit)
            for review_ref in review_refs
        ):
            raise ValueError(f"{unit_id} requires a complete approved review")


def build_curriculum(
    curriculum_root: Path,
    legacy_central: Path,
) -> dict[str, Any]:
    legacy_document = load_json(legacy_central)
    legacy_units = legacy_document.get("units")
    if not isinstance(legacy_units, list):
        raise ValueError(f"{legacy_central} units must be a list")

    all_units: list[dict[str, Any]] = []
    loaded_domains: set[str] = set()
    for domain in DOMAIN_ORDER:
        domain_path = curriculum_root / domain / "teaching-units.json"
        if domain_path.exists():
            all_units.extend(_load_domain(domain_path, domain))
            loaded_domains.add(domain)
            continue
        if domain in TASK3_SOURCE_DOMAINS:
            raise ValueError(f"missing Task 3 domain source: {domain_path}")

    fallback_domains = TASK3_LEGACY_FALLBACK_DOMAINS - loaded_domains
    all_units.extend(
        unit
        for unit in legacy_units
        if isinstance(unit, dict) and unit.get("data_type") in fallback_domains
    )

    ids = [unit.get("id") for unit in all_units]
    if any(not isinstance(unit_id, str) or not unit_id for unit_id in ids):
        raise ValueError("all teaching units must have non-empty string IDs")
    duplicates = sorted({unit_id for unit_id in ids if ids.count(unit_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate teaching unit ID: {', '.join(duplicates)}")
    units = sorted(all_units, key=lambda unit: unit["id"])
    visible_ids = sorted(
        unit["id"] for unit in units if unit.get("student_visible") is True
    )
    return {
        "schema_version": "1.1.0",
        "student_visible_unit_ids": visible_ids,
        "units": units,
    }


def write_document(document: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curriculum-root", type=Path, default=DEFAULT_CURRICULUM_ROOT)
    parser.add_argument("--legacy-central", type=Path, default=DEFAULT_CENTRAL)
    parser.add_argument("--source-registry", type=Path, default=DEFAULT_SOURCE_REGISTRY)
    parser.add_argument("--review-registry", type=Path, default=DEFAULT_REVIEW_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_CENTRAL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = build_curriculum(args.curriculum_root, args.legacy_central)
    validate_publication_contract(
        document,
        load_json(args.source_registry),
        load_json(args.review_registry),
    )
    write_document(document, args.output)
    fallback = ", ".join(sorted(TASK3_LEGACY_FALLBACK_DOMAINS))
    print(
        f"Built curriculum index: {len(document['units'])} units "
        f"(Task 3 legacy fallback domains: {fallback})"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
