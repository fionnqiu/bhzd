import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VIDEO_UNITS_PATH = (
    ROOT / "data" / "curriculum" / "video" / "teaching-units.json"
)
SCENARIO_ROOT = ROOT / "data" / "scenarios"
SCENARIO_PATHS = {
    "SCN-MEDICAL-001": SCENARIO_ROOT / "medical.json",
    "SCN-CUSTOMER-SERVICE-001": SCENARIO_ROOT / "customer-service.json",
    "SCN-IN-VEHICLE-001": SCENARIO_ROOT / "in-vehicle.json",
    "SCN-CONTENT-SAFETY-001": SCENARIO_ROOT / "content-safety.json",
}
CENTRAL_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
LEGACY_UNITS_PATH = ROOT / "data" / "curriculum" / "legacy" / "teaching-units.json"
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
GRAPH_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
BUILD_CURRICULUM_PATH = ROOT / "scripts" / "build_curriculum.py"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"
SCENARIO_VALIDATOR_PATH = ROOT / "scripts" / "validate_scenarios.py"

VIDEO_POLICY_SOURCE = "SRC-POLICY-VIDEO-TASK5-001"
SCENARIO_POLICY_SOURCE = "SRC-POLICY-SCENARIOS-TASK5-001"
EXPECTED_VIDEO_UNITS = {
    "frame_annotation": {
        "unit_id": "TU-VIDEO-FRAME-ANNOTATION-001",
        "capability_ref": "CAP-VID-FRAME-ANNOTATE-001",
        "task_ref": "TSK-VID-FRAME-LABEL-001",
        "rule_refs": {"KNG-VID-FRAME-ANNOTATION-001"},
    },
    "object_tracking": {
        "unit_id": "TU-VIDEO-OBJECT-TRACKING-001",
        "capability_ref": "CAP-VID-OBJECT-TRACK-001",
        "task_ref": "TSK-VID-OBJECT-TRACK-001",
        "rule_refs": {"KNG-VID-TRACK-CONTINUITY-001"},
    },
    "behavior_event": {
        "unit_id": "TU-VIDEO-BEHAVIOR-EVENT-001",
        "capability_ref": "CAP-VID-ACTION-EVENT-001",
        "task_ref": "TSK-VID-ACTION-EVENT-001",
        "rule_refs": {
            "KNG-VID-ACTION-TAXONOMY-001",
            "KNG-VID-EVENT-START-END-001",
        },
    },
}
EXPECTED_SCENARIO_TYPES = {
    "SCN-MEDICAL-001": ["text", "image", "audio"],
    "SCN-CUSTOMER-SERVICE-001": ["text", "audio"],
    "SCN-IN-VEHICLE-001": ["audio"],
    "SCN-CONTENT-SAFETY-001": ["text", "audio", "video"],
}
RESULT_FIELDS = {
    "score",
    "passed",
    "rule_refs",
    "capability_refs",
    "error_type",
    "feedback",
    "remediation",
    "manual_review_required",
    "data_version",
    "evaluation_version",
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


@pytest.fixture(scope="module")
def video_document() -> dict:
    if not VIDEO_UNITS_PATH.is_file():
        pytest.skip(f"Task 5 video source is not implemented: {VIDEO_UNITS_PATH}")
    return load_json(VIDEO_UNITS_PATH)


@pytest.fixture(scope="module")
def video_units(video_document) -> list[dict]:
    return video_document["units"]


@pytest.fixture(scope="module")
def video_units_by_key(video_units) -> dict[str, dict]:
    return {unit["capability_key"]: unit for unit in video_units}


@pytest.fixture(scope="module")
def scenario_documents() -> dict[str, dict]:
    missing = [str(path) for path in SCENARIO_PATHS.values() if not path.is_file()]
    if missing:
        pytest.skip(f"Task 5 scenario sources are not implemented: {missing}")
    return {
        scenario_id: load_json(path)
        for scenario_id, path in SCENARIO_PATHS.items()
    }


@pytest.fixture(scope="module")
def scenario_validator():
    if not SCENARIO_VALIDATOR_PATH.is_file():
        return None
    return load_module(SCENARIO_VALIDATOR_PATH, "task5_scenario_validator")


def test_task5_candidate_source_files_exist():
    expected = [VIDEO_UNITS_PATH, *SCENARIO_PATHS.values()]
    missing = [str(path) for path in expected if not path.is_file()]
    assert not missing, f"Task 5 candidate sources are missing: {missing}"


def test_video_domain_has_exactly_three_distinct_video_capabilities(
    video_document, video_units, video_units_by_key
):
    assert video_document["schema_version"] == "1.1.0"
    assert video_document["data_type"] == "video"
    assert len(video_units) == 3
    assert [unit["id"] for unit in video_units] == sorted(
        unit["id"] for unit in video_units
    )
    assert set(video_units_by_key) == set(EXPECTED_VIDEO_UNITS)
    assert {unit["id"] for unit in video_units} == {
        expected["unit_id"] for expected in EXPECTED_VIDEO_UNITS.values()
    }

    image_caps = {
        node["id"]
        for node in load_json(GRAPH_PATH)["nodes"]
        if node["type"] == "CAP" and "image" in node["data_types"]
    }
    video_caps = {
        expected["capability_ref"] for expected in EXPECTED_VIDEO_UNITS.values()
    }
    assert not (image_caps & video_caps)
    assert all(capability.startswith("CAP-VID-") for capability in video_caps)


def test_video_units_reuse_the_common_exercise_and_feedback_contract(
    video_units_by_key,
):
    exercise_ids = []
    for capability_key, expected in EXPECTED_VIDEO_UNITS.items():
        unit = video_units_by_key[capability_key]
        assert unit["id"] == expected["unit_id"]
        assert unit["data_type"] == "video"
        assert unit["goals"]
        assert unit["learning_objectives"]
        assert expected["rule_refs"] <= set(unit["rule_refs"])
        assert unit["source_refs"]
        assert VIDEO_POLICY_SOURCE in unit["source_refs"]
        assert unit["positive_examples"]
        assert unit["negative_examples"]
        assert unit["common_errors"]
        assert unit["remediation"]

        explanation = unit["rule_explanation"]
        assert explanation["external_format_facts"]
        assert explanation["project_policy"]["source_ref"] == VIDEO_POLICY_SOURCE
        assert explanation["project_policy"]["version"] == "1.0.0"

        exercise = unit["exercise"]
        exercise_ids.append(exercise["exercise_id"])
        assert exercise["exercise_type"]
        assert exercise["answer"]
        assert exercise["error_types"]
        assert expected["capability_ref"] in exercise["capability_refs"]
        assert exercise["evaluation"]["diagnostic_rules"]
        assert exercise["evaluation"]["diagnostic_precedence"]
        incorrect = exercise["evaluation"]["incorrect_feedback"]
        assert incorrect["feedback"]
        assert incorrect["remediation"]
        assert unit["review_status"] == "draft"
        assert unit["student_visible"] is False
        assert unit["review_records"] == []

    assert len(exercise_ids) == len(set(exercise_ids))


def test_video_errors_link_rules_capabilities_and_remediation_resources(video_units):
    graph = load_json(GRAPH_PATH)
    nodes = {node["id"]: node for node in graph["nodes"]}
    video_resources = {
        node_id
        for node_id, node in nodes.items()
        if node["type"] == "RES" and "video" in node["data_types"]
    }
    for unit in video_units:
        exercise = unit["exercise"]
        error_types = set(exercise["error_types"])
        mappings = unit["learning_path"]["error_mappings"]
        assert {mapping["error_type"] for mapping in mappings} == error_types
        for mapping in mappings:
            assert set(mapping["rule_refs"]) <= set(unit["rule_refs"])
            assert set(mapping["capability_refs"]) <= nodes.keys()
            assert set(mapping["remediation_resource_refs"]) <= video_resources
            assert mapping["rule_refs"]
            assert mapping["capability_refs"]
            assert mapping["remediation_resource_refs"]


def test_video_exercises_are_deterministic_and_return_rule_linked_feedback(video_units):
    evaluator = load_module(EVALUATOR_PATH, "task5_video_evaluator")
    for unit in video_units:
        exercise = unit["exercise"]
        exercise_id = exercise["exercise_id"]
        first = evaluator.evaluate_unit(
            unit, exercise["answer"], exercise_id=exercise_id
        )
        second = evaluator.evaluate_unit(
            unit, exercise["answer"], exercise_id=exercise_id
        )
        assert first == second
        assert set(first) == RESULT_FIELDS
        assert first["passed"] is True
        assert first["score"] == 1.0

        diagnostic = exercise["evaluation"]["diagnostic_rules"][0]
        wrong = evaluator.evaluate_unit(
            unit, diagnostic["submission"], exercise_id=exercise_id
        )
        assert wrong["passed"] is False
        assert wrong["error_type"] == diagnostic["error_type"]
        assert wrong["rule_refs"] == unit["rule_refs"]
        assert wrong["capability_refs"] == exercise["capability_refs"]
        assert wrong["feedback"] == diagnostic["feedback"]
        assert wrong["remediation"] == diagnostic["remediation"]


def test_scenario_files_declare_the_exact_graph_supported_types(
    scenario_documents, scenario_validator
):
    assert scenario_validator is not None, (
        f"Task 5 scenario validator is not implemented: {SCENARIO_VALIDATOR_PATH}"
    )
    catalog = load_json(GRAPH_CATALOG_PATH)
    errors = scenario_validator.validate_scenario_documents(
        list(scenario_documents.values()), catalog
    )
    assert errors == []

    graph_scenarios = {node["id"]: node for node in catalog["nodes"]["SCN"]}
    assert set(scenario_documents) == set(EXPECTED_SCENARIO_TYPES)
    for scenario_id, expected_types in EXPECTED_SCENARIO_TYPES.items():
        document = scenario_documents[scenario_id]
        scenario = document["scenario"]
        assert document["schema_version"] == "1.0.0"
        assert set(document) == {"schema_version", "scenario"}
        assert scenario["id"] == scenario_id
        assert scenario["supported_data_types"] == expected_types
        assert graph_scenarios[scenario_id]["supported_data_types"] == expected_types
        assert scenario["source_refs"]
        assert SCENARIO_POLICY_SOURCE in scenario["source_refs"]
        assert scenario["applicable_capability_refs"]
        assert scenario["review_status"] == "draft"
        assert scenario["review_records"] == []


def test_every_declared_scenario_type_has_an_override_and_example(scenario_documents):
    all_rule_ids = []
    all_example_ids = []
    for scenario_id, expected_types in EXPECTED_SCENARIO_TYPES.items():
        scenario = scenario_documents[scenario_id]["scenario"]
        overrides = scenario["overrides"]
        examples = scenario["examples"]
        assert {override["data_type"] for override in overrides} == set(expected_types)
        assert {example["data_type"] for example in examples} == set(expected_types)

        for override in overrides:
            all_rule_ids.append(override["rule_id"])
            assert override["base_rule_ref"].startswith("KNG-")
            assert override["override_type"] in {"add", "replace"}
            assert override["content"]
            assert override["source_refs"]
            assert override["review_status"] == "draft"
            assert override["review_records"] == []

        by_rule = {override["rule_id"]: override for override in overrides}
        for example in examples:
            all_example_ids.append(example["example_id"])
            assert example["rule_id"] in by_rule
            assert example["data_type"] == by_rule[example["rule_id"]]["data_type"]
            assert example["input"]
            assert example["expected"]
            assert example["explanation"]
            authorization = example["asset_authorization"]
            assert authorization["type"] == "self-authored"
            assert authorization["contains_personal_data"] is False

    assert len(all_rule_ids) == len(set(all_rule_ids))
    assert len(all_example_ids) == len(set(all_example_ids))


def test_scenario_overrides_match_compatible_inscn_relations(scenario_documents):
    catalog = load_json(GRAPH_CATALOG_PATH)
    nodes = {
        node["id"]: node
        for node_type in ("CAP", "KNG", "TSK", "SCN", "RES", "CERT")
        for node in catalog["nodes"][node_type]
    }
    inscn_by_rule = {
        edge["metadata"]["rule_id"]: edge for edge in catalog["relations"]["INSCN"]
    }
    for scenario_id, document in scenario_documents.items():
        scenario = document["scenario"]
        for override in scenario["overrides"]:
            edge = inscn_by_rule[override["rule_id"]]
            assert edge["target"] == scenario_id
            assert edge["metadata"]["base_rule_ref"] == override["base_rule_ref"]
            assert edge["metadata"]["override_type"] == override["override_type"]
            assert override["data_type"] in edge["metadata"]["data_types"]
            assert override["data_type"] in nodes[edge["source"]]["data_types"]
            assert override["data_type"] in nodes[override["base_rule_ref"]]["data_types"]


def test_scenarios_are_overlays_not_copied_curriculum_branches(scenario_documents):
    forbidden = {
        "units",
        "teaching_units",
        "learning_objectives",
        "exercise",
        "positive_examples",
        "negative_examples",
    }
    curriculum_ids = {
        unit["id"] for unit in load_json(CENTRAL_UNITS_PATH)["units"]
    }
    for document in scenario_documents.values():
        scenario = document["scenario"]
        assert not (forbidden & scenario.keys())
        assert not ({override["rule_id"] for override in scenario["overrides"]} & curriculum_ids)


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("wrong_schema_version", "schema_version"),
        ("unknown_root_key", "root_keys"),
        ("duplicate_supported_type", "supported_data_types"),
        ("noncanonical_supported_type_order", "supported_data_types"),
        ("null_scenario_source_refs", "source_refs"),
        ("malformed_scenario_source_ref", "source_refs"),
        ("duplicate_scenario_source_ref", "source_refs"),
        ("unknown_capability_ref", "capability_ref"),
        ("incompatible_capability_ref", "capability_data_type"),
        ("malformed_override_rule_ref", "rule_id"),
        ("malformed_override_base_ref", "base_rule_ref"),
        ("malformed_override_source_refs", "source_refs"),
        ("duplicate_scenario_id", "duplicate_scenario_id"),
        ("duplicate_rule_id", "duplicate_rule_id"),
        ("duplicate_example_id", "duplicate_example_id"),
        ("duplicate_inscn_rule_id", "inscn_rule_id"),
    ],
)
def test_scenario_contract_rejects_schema_reference_and_identity_mutations(
    scenario_documents, scenario_validator, mutation, error_code
):
    assert scenario_validator is not None, (
        f"Task 5 scenario validator is not implemented: {SCENARIO_VALIDATOR_PATH}"
    )
    documents = copy.deepcopy(list(scenario_documents.values()))
    catalog = copy.deepcopy(load_json(GRAPH_CATALOG_PATH))
    medical = documents[0]["scenario"]
    customer_service = documents[1]["scenario"]

    if mutation == "wrong_schema_version":
        documents[0]["schema_version"] = "1.0"
    elif mutation == "unknown_root_key":
        documents[0]["unexpected"] = True
    elif mutation == "duplicate_supported_type":
        medical["supported_data_types"].append("text")
    elif mutation == "noncanonical_supported_type_order":
        medical["supported_data_types"] = ["audio", "text", "image"]
    elif mutation == "null_scenario_source_refs":
        medical["source_refs"] = None
    elif mutation == "malformed_scenario_source_ref":
        medical["source_refs"] = ["not-a-source-ref"]
    elif mutation == "duplicate_scenario_source_ref":
        medical["source_refs"].append(medical["source_refs"][0])
    elif mutation == "unknown_capability_ref":
        medical["applicable_capability_refs"][0] = "CAP-UNKNOWN-001"
    elif mutation == "incompatible_capability_ref":
        medical["applicable_capability_refs"][0] = "CAP-VID-ACTION-EVENT-001"
    elif mutation == "malformed_override_rule_ref":
        medical["overrides"][0]["rule_id"] = None
    elif mutation == "malformed_override_base_ref":
        medical["overrides"][0]["base_rule_ref"] = "not-a-kng-ref"
    elif mutation == "malformed_override_source_refs":
        medical["overrides"][0]["source_refs"] = [None]
    elif mutation == "duplicate_scenario_id":
        customer_service["id"] = medical["id"]
    elif mutation == "duplicate_rule_id":
        customer_service["overrides"][0]["rule_id"] = medical["overrides"][0][
            "rule_id"
        ]
    elif mutation == "duplicate_example_id":
        customer_service["examples"][0]["example_id"] = medical["examples"][0][
            "example_id"
        ]
    elif mutation == "duplicate_inscn_rule_id":
        duplicate = copy.deepcopy(catalog["relations"]["INSCN"][0])
        catalog["relations"]["INSCN"].append(duplicate)
    else:  # pragma: no cover - parametrization defines the complete mutation set.
        raise AssertionError(f"unknown mutation: {mutation}")

    errors = scenario_validator.validate_scenario_documents(documents, catalog)
    assert any(f"[{error_code}]" in error for error in errors), errors


def test_scenario_validator_cli_accepts_canonical_documents_and_rejects_a_mutation(
    tmp_path,
):
    valid = run_python(
        SCENARIO_VALIDATOR_PATH,
        "--graph-catalog",
        GRAPH_CATALOG_PATH,
        *SCENARIO_PATHS.values(),
    )
    assert valid.returncode == 0, valid.stderr or valid.stdout
    assert "Scenario validation succeeded" in valid.stdout

    mutated = load_json(SCENARIO_PATHS["SCN-MEDICAL-001"])
    mutated["scenario"]["supported_data_types"].append("text")
    mutated_path = tmp_path / "medical-duplicate-type.json"
    mutated_path.write_text(
        json.dumps(mutated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    invalid = run_python(
        SCENARIO_VALIDATOR_PATH,
        "--graph-catalog",
        GRAPH_CATALOG_PATH,
        mutated_path,
    )
    assert invalid.returncode == 1, invalid.stderr or invalid.stdout
    assert "[supported_data_types]" in invalid.stdout


def test_task5_policy_sources_are_local_development_policy_only():
    sources = {
        source["source_id"]: source
        for source in load_json(SOURCE_REGISTRY_PATH)["sources"]
    }
    for source_id in (VIDEO_POLICY_SOURCE, SCENARIO_POLICY_SOURCE):
        assert source_id in sources, f"missing Task 5 policy source: {source_id}"
        source = sources[source_id]
        assert source["source_kind"] == "project_policy"
        assert source["authority_scope"] == "local_project_policy_only"
        assert source["status"] == "verified"
        assert source["publication_scope"] == "development_only"
        assert source["human_release_allowed"] is False
        assert source["license_or_authorization"]["publishable"] is True
        assert source["usage_rights"]["citation_allowed"] is True
        assert source["usage_rights"]["asset_redistribution_allowed"] is False


def test_curriculum_build_replaces_legacy_video_and_keeps_all_authored_domains():
    builder = load_module(BUILD_CURRICULUM_PATH, "task5_curriculum_builder")
    first = builder.build_curriculum(ROOT / "data" / "curriculum", LEGACY_UNITS_PATH)
    second = builder.build_curriculum(ROOT / "data" / "curriculum", LEGACY_UNITS_PATH)
    assert first == second
    by_domain = {
        domain: [unit for unit in first["units"] if unit["data_type"] == domain]
        for domain in ("text", "image", "audio", "video")
    }
    assert len(first["units"]) == 19
    assert len(by_domain["text"]) == 5
    assert len(by_domain["image"]) == 5
    assert len(by_domain["audio"]) == 6
    assert len(by_domain["video"]) == 3
    assert "TU-VIDEO-TRACK-ID-001" not in {
        unit["id"] for unit in by_domain["video"]
    }


def test_central_index_and_graph_keep_task5_candidates_hidden_with_exact_counts():
    central = load_json(CENTRAL_UNITS_PATH)
    graph = load_json(GRAPH_PATH)
    video_units = [unit for unit in central["units"] if unit["data_type"] == "video"]
    assert len(central["units"]) == 19
    assert len(video_units) == 3
    assert all(unit["review_status"] == "draft" for unit in video_units)
    assert all(unit["student_visible"] is False for unit in video_units)
    assert not ({unit["id"] for unit in video_units} & set(central["student_visible_unit_ids"]))
    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240

    task_links = {
        link["unit_id"]: (node["id"], link)
        for node in graph["nodes"]
        if node["type"] == "TSK"
        for link in node["teaching_unit_links"]
    }
    for expected in EXPECTED_VIDEO_UNITS.values():
        task_id, link = task_links[expected["unit_id"]]
        assert task_id == expected["task_ref"]
        assert link["review_status"] == "draft"
        assert link["student_visible"] is False
        assert link["in_student_visible_index"] is False
        assert link["consumable"] is False


def test_task5_evaluator_cli_uses_the_video_exercise_id(video_units):
    unit = video_units[0]
    exercise = unit["exercise"]
    result = run_python(
        EVALUATOR_PATH,
        "--unit-file",
        VIDEO_UNITS_PATH,
        "--unit-id",
        unit["id"],
        "--exercise-id",
        exercise["exercise_id"],
        "--submission",
        json.dumps(exercise["answer"], ensure_ascii=False),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["passed"] is True
