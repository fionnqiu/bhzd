"""Task 5 video content contracts."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VIDEO_UNITS_PATH = ROOT / "data" / "curriculum" / "video" / "teaching-units.json"
CENTRAL_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
LEGACY_UNITS_PATH = ROOT / "data" / "curriculum" / "legacy" / "teaching-units.json"
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
BUILD_CURRICULUM_PATH = ROOT / "scripts" / "build_curriculum.py"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"

VIDEO_POLICY_SOURCE = "SRC-POLICY-VIDEO-TASK5-001"
VIDEO_REVIEW_HISTORY = [
    "REVIEW-TASK5-VIDEO-3A425AC-001",
    "REVIEW-TASK5-VIDEO-ED484E7-002",
    "REVIEW-TASK5-VIDEO-CF9696E-003",
]
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


def test_task5_video_source_file_exists():
    assert VIDEO_UNITS_PATH.is_file(), f"missing Task 5 video source: {VIDEO_UNITS_PATH}"


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
        assert unit["review_status"] == "published"
        assert unit["student_visible"] is True
        assert unit["review_records"] == VIDEO_REVIEW_HISTORY

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


def test_task5_policy_sources_are_local_development_policy_only():
    sources = {
        source["source_id"]: source
        for source in load_json(SOURCE_REGISTRY_PATH)["sources"]
    }
    source = sources[VIDEO_POLICY_SOURCE]
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


def test_central_index_and_graph_publish_reviewed_task5_video_with_exact_counts():
    central = load_json(CENTRAL_UNITS_PATH)
    graph = load_json(GRAPH_PATH)
    video_units = [unit for unit in central["units"] if unit["data_type"] == "video"]
    assert len(central["units"]) == 19
    assert len(video_units) == 3
    assert all(unit["review_status"] == "published" for unit in video_units)
    assert all(unit["student_visible"] is True for unit in video_units)
    assert {unit["id"] for unit in video_units} <= set(central["student_visible_unit_ids"])
    assert len(central["student_visible_unit_ids"]) == 19
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
        assert link["review_status"] == "published"
        assert link["student_visible"] is True
        assert link["in_student_visible_index"] is True
        assert link["consumable"] is True


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
