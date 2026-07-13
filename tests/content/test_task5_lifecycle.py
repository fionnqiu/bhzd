import copy
import hashlib
import importlib.util
import inspect
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VIDEO_PATH = ROOT / "data" / "curriculum" / "video" / "teaching-units.json"
CENTRAL_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
LEGACY_PATH = ROOT / "data" / "curriculum" / "legacy" / "teaching-units.json"
CONTENT_REVIEW_PATH = ROOT / "data" / "reviews" / "content-review-registry.json"
SCENARIO_REVIEW_PATH = ROOT / "data" / "reviews" / "scenario-review-registry.json"
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
GRAPH_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
BUILD_CURRICULUM_PATH = ROOT / "scripts" / "build_curriculum.py"
SCENARIO_VALIDATOR_PATH = ROOT / "scripts" / "validate_scenarios.py"
SCENARIO_PATHS = {
    "SCN-CONTENT-SAFETY-001": ROOT / "data" / "scenarios" / "content-safety.json",
    "SCN-CUSTOMER-SERVICE-001": ROOT / "data" / "scenarios" / "customer-service.json",
    "SCN-IN-VEHICLE-001": ROOT / "data" / "scenarios" / "in-vehicle.json",
    "SCN-MEDICAL-001": ROOT / "data" / "scenarios" / "medical.json",
}

UNIT_DIGEST_EXCLUDED_FIELDS = {
    "review_status",
    "student_visible",
    "review_records",
}
SCENARIO_DIGEST_EXCLUDED_FIELDS = {
    *UNIT_DIGEST_EXCLUDED_FIELDS,
    "publication_scope",
    "human_release_allowed",
}
VIDEO_REVIEW_HISTORY = [
    "REVIEW-TASK5-VIDEO-3A425AC-001",
    "REVIEW-TASK5-VIDEO-ED484E7-002",
    "REVIEW-TASK5-VIDEO-CF9696E-003",
]
VIDEO_UNIT_VERSIONS = {
    "TU-VIDEO-BEHAVIOR-EVENT-001": (
        "1.1.0",
        "1.1.0",
        "c75e20ea6fd81fd5efbc2c96ce560ef3580b272fee5c4403ace5070a8d79ec65",
    ),
    "TU-VIDEO-FRAME-ANNOTATION-001": (
        "1.1.0",
        "1.1.0",
        "8ba77f32cbe46e96768cdbab6fd08af0b37b14e8d42dc15de95fcb15f995819d",
    ),
    "TU-VIDEO-OBJECT-TRACKING-001": (
        "1.1.1",
        "1.1.0",
        "193ebd6180ddc0d4759dc07f6a724060a5abfb98f60a3303b6c87e65c53cc7ef",
    ),
}
VIDEO_NEGATIVE_REVIEWS = {
    "REVIEW-TASK5-VIDEO-3A425AC-001": {
        "commit": "3a425ac49566405b4a2d80cd8e4efeea637e4b36",
        "finding_ids": {
            "VID-001",
            "VID-002",
            "VID-003",
            "VID-004",
            "VID-005",
            "VID-006",
        },
        "versions": {
            unit_id: ("1.0.0", "1.0.0") for unit_id in VIDEO_UNIT_VERSIONS
        },
    },
    "REVIEW-TASK5-VIDEO-ED484E7-002": {
        "commit": "ed484e757cf5334624ab09f4438e0d0283c81fcf",
        "finding_ids": {"VID-003R"},
        "versions": {
            unit_id: ("1.1.0", "1.1.0") for unit_id in VIDEO_UNIT_VERSIONS
        },
    },
}

SCENARIO_REVIEWS = {
    "REVIEW-TASK5-SCENARIOS-C5A91CB-001": {
        "commit": "c5a91cb7146316d479f7051b1e92a6edd693c892",
        "scenario_digests": {
            "SCN-CUSTOMER-SERVICE-001": "d5e6a69cb8cb0e5d59fc1de09f294da30f3f75db911a4794181c84f8f3b6489d",
            "SCN-MEDICAL-001": "4c86b98e27d8204c31967797062c988143a405d2deca4c8fbfa5b009b5449cd6",
        },
        "rule_ids": {
            "SCNR-CS-AUD-SPEAKER-001",
            "SCNR-CS-TXT-INTENT-001",
            "SCNR-MED-AUD-TRANSCRIPT-001",
            "SCNR-MED-IMG-MASK-001",
            "SCNR-MED-TXT-ENTITY-001",
        },
    },
    "REVIEW-TASK5-SCENARIOS-09638A7-001": {
        "commit": "09638a7efc899910f39a3268f7fa9d7781333423",
        "scenario_digests": {
            "SCN-CONTENT-SAFETY-001": "ffd9596da8418fdb29bb5c432014d032c5dbd708a2b991a52bf30344c88fb357",
            "SCN-IN-VEHICLE-001": "736cfb1c8e625f9d3c1af86af2c9c1ec17e9574efa9258b1dac88b8b61fcb4c8",
        },
        "rule_ids": {
            "SCNR-CSAFE-AUD-EVENT-001",
            "SCNR-CSAFE-TXT-CLASS-001",
            "SCNR-CSAFE-VID-ACTION-001",
            "SCNR-IV-AUD-COMMAND-001",
        },
    },
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strip_scenario_lifecycle(value):
    if isinstance(value, dict):
        return {
            key: strip_scenario_lifecycle(item)
            for key, item in value.items()
            if key not in SCENARIO_DIGEST_EXCLUDED_FIELDS
        }
    if isinstance(value, list):
        return [strip_scenario_lifecycle(item) for item in value]
    return value


def canonical_unit_digest(value) -> str:
    reviewed_content = copy.deepcopy(value)
    for field in UNIT_DIGEST_EXCLUDED_FIELDS:
        reviewed_content.pop(field, None)
    canonical = json.dumps(
        reviewed_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_scenario_digest(value) -> str:
    canonical = json.dumps(
        strip_scenario_lifecycle(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_video_review_history_is_exact_and_digest_bound():
    records = {
        record["review_id"]: record
        for record in load_json(CONTENT_REVIEW_PATH)["records"]
    }
    assert set(VIDEO_REVIEW_HISTORY) <= records.keys()

    for review_id, expected in VIDEO_NEGATIVE_REVIEWS.items():
        record = records[review_id]
        assert record["reviewer_id"] == "codex-task5-video-review"
        assert record["reviewer_type"] == "ai_agent"
        assert record["independent_of_implementation"] is True
        assert record["reviewed_at"] == "2026-07-13"
        assert record["reviewed_commit"] == expected["commit"]
        assert record["decision"] == "changes_required"
        assert record["authorizes_publication"] is False
        assert {item["finding_id"] for item in record["findings"]} == expected[
            "finding_ids"
        ]
        assert record["finding_count"] == len(expected["finding_ids"])
        versions = {
            item["unit_id"]: (item["data_version"], item["evaluation_version"])
            for item in record["unit_versions"]
        }
        assert versions == expected["versions"]

    approved = records[VIDEO_REVIEW_HISTORY[-1]]
    assert approved["reviewer_id"] == "codex-task5-video-review"
    assert approved["reviewer_type"] == "ai_agent"
    assert approved["independent_of_implementation"] is True
    assert approved["reviewed_at"] == "2026-07-13"
    assert approved["reviewed_commit"] == (
        "cf9696e37da10a56cd5115736abb423229e0b02c"
    )
    assert approved["decision"] == "approved"
    assert approved["findings"] == []
    assert approved["finding_count"] == 0
    assert approved["authorizes_publication"] is True
    assert approved["publication_scope"] == "development_only"
    assert approved["human_release_allowed"] is False
    versions = {
        item["unit_id"]: (
            item["data_version"],
            item["evaluation_version"],
            item["content_digest"],
        )
        for item in approved["unit_versions"]
    }
    assert versions == VIDEO_UNIT_VERSIONS

    units = load_json(VIDEO_PATH)["units"]
    assert {unit["id"] for unit in units} == set(VIDEO_UNIT_VERSIONS)
    for unit in units:
        assert canonical_unit_digest(unit) == VIDEO_UNIT_VERSIONS[unit["id"]][2]
        assert unit["review_status"] == "published"
        assert unit["student_visible"] is True
        assert unit["review_records"] == VIDEO_REVIEW_HISTORY


def test_scenario_review_registry_binds_four_scenarios_and_nine_rules():
    assert SCENARIO_REVIEW_PATH.is_file(), (
        f"missing scenario review registry: {SCENARIO_REVIEW_PATH}"
    )
    registry = load_json(SCENARIO_REVIEW_PATH)
    assert registry["schema_version"] == "1.0.0"
    assert set(registry["digest_contract"]["excluded_fields"]) == (
        SCENARIO_DIGEST_EXCLUDED_FIELDS
    )
    records = {record["review_id"]: record for record in registry["records"]}
    assert set(records) == set(SCENARIO_REVIEWS)

    scenario_to_review = {}
    for review_id, expected in SCENARIO_REVIEWS.items():
        record = records[review_id]
        assert record["reviewer_id"] == "codex-task5-scenario-review"
        assert record["reviewer_type"] == "ai_agent"
        assert record["independent_of_implementation"] is True
        assert record["reviewed_at"] == "2026-07-13"
        assert record["reviewed_commit"] == expected["commit"]
        assert record["decision"] == "approved"
        assert record["findings"] == []
        assert record["finding_count"] == 0
        assert record["authorizes_publication"] is True
        assert record["publication_scope"] == "development_only"
        assert record["human_release_allowed"] is False
        assert record["scope"]["publication_scope"] == "development_only"
        assert record["scope"]["human_release_allowed"] is False
        assert set(record["scope"]["scenario_ids"]) == set(
            expected["scenario_digests"]
        )
        assert set(record["scope"]["rule_ids"]) == expected["rule_ids"]
        versions = {
            item["scenario_id"]: item["content_digest"]
            for item in record["scenario_versions"]
        }
        assert versions == expected["scenario_digests"]
        scenario_to_review.update(
            {scenario_id: review_id for scenario_id in expected["scenario_digests"]}
        )

    override_count = 0
    for scenario_id, path in SCENARIO_PATHS.items():
        document = load_json(path)
        scenario = document["scenario"]
        review_id = scenario_to_review[scenario_id]
        expected_digest = SCENARIO_REVIEWS[review_id]["scenario_digests"][scenario_id]
        assert canonical_scenario_digest(document) == expected_digest
        assert scenario["review_status"] == "published"
        assert scenario["student_visible"] is True
        assert scenario["review_records"] == [review_id]
        assert scenario["publication_scope"] == "development_only"
        assert scenario["human_release_allowed"] is False
        for override in scenario["overrides"]:
            override_count += 1
            assert override["rule_id"] in SCENARIO_REVIEWS[review_id]["rule_ids"]
            assert override["review_status"] == "published"
            assert override["review_records"] == [review_id]
            assert override["publication_scope"] == "development_only"
            assert override["human_release_allowed"] is False
    assert override_count == 9


def test_scenario_validator_requires_source_eligibility_and_review_digest():
    validator = load_module(SCENARIO_VALIDATOR_PATH, "task5_lifecycle_validator")
    parameters = inspect.signature(validator.validate_scenario_documents).parameters
    assert {"source_registry", "review_registry"} <= parameters.keys()

    documents = [load_json(path) for path in SCENARIO_PATHS.values()]
    catalog = load_json(GRAPH_CATALOG_PATH)
    sources = load_json(SOURCE_REGISTRY_PATH)
    reviews = load_json(SCENARIO_REVIEW_PATH)
    assert validator.validate_scenario_documents(
        documents,
        catalog,
        source_registry=sources,
        review_registry=reviews,
    ) == []

    ineligible_sources = copy.deepcopy(sources)
    policy = next(
        source
        for source in ineligible_sources["sources"]
        if source["source_id"] == "SRC-POLICY-SCENARIOS-TASK5-001"
    )
    policy["license_or_authorization"]["publishable"] = False
    errors = validator.validate_scenario_documents(
        documents,
        catalog,
        source_registry=ineligible_sources,
        review_registry=reviews,
    )
    assert any("[source_eligibility]" in error for error in errors), errors

    stale_reviews = copy.deepcopy(reviews)
    stale_reviews["records"][0]["scenario_versions"][0]["content_digest"] = "0" * 64
    errors = validator.validate_scenario_documents(
        documents,
        catalog,
        source_registry=sources,
        review_registry=stale_reviews,
    )
    assert any("[review_content_digest]" in error for error in errors), errors


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    (
        ("unhashable_source_id", "source_registry"),
        ("unhashable_excluded_field", "review_registry"),
        ("empty_reviewer_id", "review_registry"),
        ("external_scope", "review_approval"),
    ),
)
def test_scenario_validator_reports_malformed_lifecycle_registries_without_raising(
    mutation, error_code
):
    validator = load_module(SCENARIO_VALIDATOR_PATH, f"malformed_{mutation}")
    documents = [load_json(path) for path in SCENARIO_PATHS.values()]
    catalog = load_json(GRAPH_CATALOG_PATH)
    sources = load_json(SOURCE_REGISTRY_PATH)
    reviews = load_json(SCENARIO_REVIEW_PATH)
    if mutation == "unhashable_source_id":
        sources["sources"][0]["source_id"] = {}
    elif mutation == "unhashable_excluded_field":
        reviews["digest_contract"]["excluded_fields"] = [{}]
    elif mutation == "empty_reviewer_id":
        reviews["records"][0]["reviewer_id"] = ""
    else:
        reviews["records"][0]["scope"]["publication_scope"] = "external_release"

    errors = validator.validate_scenario_documents(
        documents,
        catalog,
        source_registry=sources,
        review_registry=reviews,
    )
    assert any(f"[{error_code}]" in error for error in errors), errors

    mutated_documents = copy.deepcopy(documents)
    mutated_documents[0]["scenario"]["description"] += " unreviewed"
    errors = validator.validate_scenario_documents(
        mutated_documents,
        catalog,
        source_registry=sources,
        review_registry=reviews,
    )
    assert any("[review_content_digest]" in error for error in errors), errors


def test_graph_publishes_exactly_reviewed_scenarios_and_nine_inscn_rules():
    catalog = load_json(GRAPH_CATALOG_PATH)
    scenario_nodes = {node["id"]: node for node in catalog["nodes"]["SCN"]}
    assert set(scenario_nodes) == set(SCENARIO_PATHS)
    for scenario_id, node in scenario_nodes.items():
        expected_review = next(
            review_id
            for review_id, expected in SCENARIO_REVIEWS.items()
            if scenario_id in expected["scenario_digests"]
        )
        assert node["status"] == "published"
        assert node["student_visible"] is True
        assert node["review_records"] == [expected_review]
        assert node["publication_scope"] == "development_only"
        assert node["human_release_allowed"] is False

    published_edges = []
    draft_edges = []
    expected_rule_reviews = {
        rule_id: review_id
        for review_id, expected in SCENARIO_REVIEWS.items()
        for rule_id in expected["rule_ids"]
    }
    for edge in catalog["relations"]["INSCN"]:
        metadata = edge["metadata"]
        if metadata["review_status"] == "published":
            published_edges.append(edge)
            rule_id = metadata["rule_id"]
            assert metadata["review_records"] == [expected_rule_reviews[rule_id]]
            assert metadata["publication_scope"] == "development_only"
            assert metadata["human_release_allowed"] is False
        else:
            draft_edges.append(edge)
            assert metadata["review_status"] == "draft"
    assert {edge["metadata"]["rule_id"] for edge in published_edges} == set(
        expected_rule_reviews
    )
    assert len(published_edges) == 9
    assert len(draft_edges) == 15


def test_curriculum_requires_all_authored_domains_without_legacy_fallback(tmp_path):
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_no_fallback_builder")
    assert set(builder.AUTHORED_SOURCE_DOMAINS) == set(builder.DOMAIN_ORDER)
    assert builder.LEGACY_FALLBACK_DOMAINS == set()

    curriculum_root = tmp_path / "curriculum"
    shutil.copytree(ROOT / "data" / "curriculum", curriculum_root)
    shutil.rmtree(curriculum_root / "video")
    with pytest.raises(ValueError, match="missing authored domain source:.*video"):
        builder.build_curriculum(curriculum_root, curriculum_root / "legacy" / "teaching-units.json")

    legacy = load_json(LEGACY_PATH)
    assert legacy["snapshot_version"]
    assert legacy["domains"] == ["audio", "video"]
    assert legacy["units"]


def test_task5_central_and_graph_publish_audio_and_video():
    central = load_json(CENTRAL_PATH)
    graph = load_json(GRAPH_PATH)
    by_domain = {
        domain: [unit for unit in central["units"] if unit["data_type"] == domain]
        for domain in ("text", "image", "audio", "video")
    }
    assert len(central["units"]) == 19
    assert len(central["student_visible_unit_ids"]) == 19
    assert all(unit["review_status"] == "published" for unit in by_domain["text"])
    assert all(unit["review_status"] == "published" for unit in by_domain["image"])
    assert all(unit["review_status"] == "published" for unit in by_domain["audio"])
    assert all(unit["student_visible"] is True for unit in by_domain["audio"])
    assert all(unit["review_status"] == "published" for unit in by_domain["video"])
    assert all(unit["student_visible"] is True for unit in by_domain["video"])

    task_links = {
        link["unit_id"]: link
        for node in graph["nodes"]
        if node["type"] == "TSK"
        for link in node["teaching_unit_links"]
    }
    assert all(task_links[unit["id"]]["consumable"] for unit in by_domain["video"])
    assert all(task_links[unit["id"]]["consumable"] for unit in by_domain["audio"])
    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240


def test_unit_digest_excludes_only_top_level_review_fields():
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_lifecycle_digest")
    unit = load_json(VIDEO_PATH)["units"][0]
    baseline = builder.content_digest(unit)
    review_only = copy.deepcopy(unit)
    review_only["review_status"] = "draft"
    review_only["student_visible"] = False
    review_only["review_records"] = []
    assert builder.content_digest(review_only) == baseline

    publication_change = copy.deepcopy(unit)
    publication_change["publication_scope"] = "internal_test"
    assert builder.content_digest(publication_change) != baseline

    nested_review_field = copy.deepcopy(unit)
    nested_review_field["exercise"]["review_status"] = "draft"
    assert builder.content_digest(nested_review_field) != baseline

    content_change = copy.deepcopy(unit)
    content_change["title"] += " unreviewed"
    assert builder.content_digest(content_change) != baseline


@pytest.mark.parametrize(
    "unit_ids",
    (
        [],
        [
            "TU-VIDEO-BEHAVIOR-EVENT-001",
            "TU-VIDEO-BEHAVIOR-EVENT-001",
            "TU-VIDEO-FRAME-ANNOTATION-001",
            "TU-VIDEO-OBJECT-TRACKING-001",
        ],
        [{"unit_id": "TU-VIDEO-BEHAVIOR-EVENT-001"}],
        [None],
        [7],
        [" "],
    ),
)
def test_review_scope_rejects_invalid_unit_ids_with_value_error(unit_ids):
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_invalid_scope_unit_ids")
    reviews = copy.deepcopy(load_json(CONTENT_REVIEW_PATH))
    approved = next(
        record
        for record in reviews["records"]
        if record["review_id"] == VIDEO_REVIEW_HISTORY[-1]
    )
    approved["scope"]["unit_ids"] = unit_ids

    with pytest.raises(
        ValueError,
        match="scope.unit_ids must be a non-empty unique string list",
    ):
        builder._validate_review_registry(reviews)


@pytest.mark.parametrize("data_type", (None, "", "scenario", "VIDEO", {}))
def test_review_scope_rejects_illegal_data_type(data_type):
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_illegal_scope_data_type")
    reviews = copy.deepcopy(load_json(CONTENT_REVIEW_PATH))
    reviews["records"][-1]["scope"]["data_type"] = data_type

    with pytest.raises(ValueError, match="scope.data_type must be an authored domain"):
        builder._validate_review_registry(reviews)


def test_review_scope_data_type_must_match_approved_unit():
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_mismatched_scope_data_type")
    reviews = copy.deepcopy(load_json(CONTENT_REVIEW_PATH))
    approved = next(
        record
        for record in reviews["records"]
        if record["review_id"] == VIDEO_REVIEW_HISTORY[-1]
    )
    approved["scope"]["data_type"] = "image"

    with pytest.raises(ValueError, match="scope.data_type does not match"):
        builder.validate_publication_contract(
            load_json(CENTRAL_PATH),
            load_json(SOURCE_REGISTRY_PATH),
            reviews,
        )


@pytest.mark.parametrize("mutation", ("duplicate_versions", "scope_version_mismatch"))
def test_review_scope_rejects_duplicate_or_mismatched_unit_versions(mutation):
    builder = load_module(BUILD_CURRICULUM_PATH, f"task5_{mutation}")
    reviews = copy.deepcopy(load_json(CONTENT_REVIEW_PATH))
    approved = next(
        record
        for record in reviews["records"]
        if record["review_id"] == VIDEO_REVIEW_HISTORY[-1]
    )
    if mutation == "duplicate_versions":
        approved["unit_versions"].append(copy.deepcopy(approved["unit_versions"][0]))
        expected = "unit_versions must have unique unit IDs"
    else:
        approved["scope"]["unit_ids"].pop()
        expected = "scope/version unit mismatch"

    with pytest.raises(ValueError, match=expected):
        builder._validate_review_registry(reviews)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    (
        ("review", "publication_scope", "external_release"),
        ("review", "human_release_allowed", True),
        ("scope", "publication_scope", "external_release"),
        ("scope", "human_release_allowed", True),
    ),
)
def test_ai_publication_review_requires_development_only_boundaries(
    location, field, value
):
    builder = load_module(BUILD_CURRICULUM_PATH, f"task5_review_{location}_{field}")
    reviews = copy.deepcopy(load_json(CONTENT_REVIEW_PATH))
    approved = next(
        record
        for record in reviews["records"]
        if record["review_id"] == VIDEO_REVIEW_HISTORY[-1]
    )
    target = approved if location == "review" else approved["scope"]
    target[field] = value

    with pytest.raises(
        ValueError,
        match="AI publication review must be development-only",
    ):
        builder.validate_publication_contract(
            load_json(CENTRAL_PATH),
            load_json(SOURCE_REGISTRY_PATH),
            reviews,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_kind", "external_reference"),
        ("authority_scope", "external_authority"),
        ("publication_scope", "external_release"),
        ("human_release_allowed", True),
    ),
)
def test_published_ai_reviewed_unit_requires_local_project_policy_source(
    field, value
):
    builder = load_module(BUILD_CURRICULUM_PATH, f"task5_policy_{field}")
    sources = copy.deepcopy(load_json(SOURCE_REGISTRY_PATH))
    video_policy = next(
        source
        for source in sources["sources"]
        if source["source_id"] == "SRC-POLICY-VIDEO-TASK5-001"
    )
    video_policy[field] = value

    with pytest.raises(ValueError, match="local project policy"):
        builder.validate_publication_contract(
            load_json(CENTRAL_PATH),
            sources,
            load_json(CONTENT_REVIEW_PATH),
        )
