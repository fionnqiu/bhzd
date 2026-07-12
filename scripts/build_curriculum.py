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
    parser.add_argument("--output", type=Path, default=DEFAULT_CENTRAL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = build_curriculum(args.curriculum_root, args.legacy_central)
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
