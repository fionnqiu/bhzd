import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEXT_UNITS_PATH = ROOT / "data" / "curriculum" / "text" / "teaching-units.json"
IMAGE_UNITS_PATH = ROOT / "data" / "curriculum" / "image" / "teaching-units.json"
CENTRAL_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"
BUILD_CURRICULUM_PATH = ROOT / "scripts" / "build_curriculum.py"

TEXT_UNIT_IDS = {
    "TU-TEXT-LABEL-VOCAB-001",
    "TU-TEXT-DOCUMENT-CLASSIFY-001",
    "TU-TEXT-NER-BOUNDARY-001",
    "TU-TEXT-RELATION-DIRECTION-001",
    "TU-TEXT-INTENT-AMBIGUITY-001",
}
IMAGE_UNIT_IDS = {
    "TU-IMAGE-RECT-BOUNDS-001",
    "TU-IMAGE-OCCLUSION-TRUNCATION-001",
    "TU-IMAGE-POLYGON-VERTICES-001",
    "TU-IMAGE-KEYPOINT-VISIBILITY-001",
    "TU-IMAGE-MASK-INSTANCE-001",
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


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_module(path: Path, name: str):
    if not path.exists():
        pytest.skip(f"Task 3 script is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
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


def unit_by_id(document: dict, unit_id: str) -> dict:
    return next(unit for unit in document["units"] if unit["id"] == unit_id)


def test_task3_files_exist():
    required = (
        TEXT_UNITS_PATH,
        IMAGE_UNITS_PATH,
        EVALUATOR_PATH,
        BUILD_CURRICULUM_PATH,
    )
    missing = [str(path) for path in required if not path.exists()]
    assert not missing, f"Task 3 files are missing: {missing}"


@pytest.mark.parametrize(
    ("path", "data_type", "required_ids"),
    (
        (TEXT_UNITS_PATH, "text", TEXT_UNIT_IDS),
        (IMAGE_UNITS_PATH, "image", IMAGE_UNIT_IDS),
    ),
)
def test_domain_sources_cover_candidate_baselines(path, data_type, required_ids):
    if not path.exists():
        pytest.skip(f"Task 3 domain source is missing: {path}")
    document = load_json(path)
    assert set(document) == {"schema_version", "data_type", "units"}
    assert document["data_type"] == data_type
    assert document["schema_version"] == "1.1.0"

    units = document["units"]
    ids = [unit["id"] for unit in units]
    assert ids == sorted(ids), "domain teaching-unit IDs must use canonical ordering"
    assert len(ids) == len(set(ids))
    assert required_ids <= set(ids)
    assert len(ids) >= 5

    for unit in units:
        assert unit["data_type"] == data_type
        assert unit["rule_explanation"]
        assert unit["positive_examples"]
        assert unit["negative_examples"]
        assert unit["exercise"]["answer"]
        assert unit["exercise"]["evaluation"]["version"]
        assert unit["exercise"]["evaluation"]["incorrect_feedback"]
        assert unit["exercise"]["error_types"]
        assert unit["common_errors"]
        assert unit["remediation"]
        assert unit["review_status"] == "draft"
        assert unit["student_visible"] is False
        assert unit["review_records"] == []


def test_boundary_occlusion_and_ambiguity_are_explicit():
    if not TEXT_UNITS_PATH.exists() or not IMAGE_UNITS_PATH.exists():
        pytest.skip("Task 3 domain sources are missing")
    text = load_json(TEXT_UNITS_PATH)
    image = load_json(IMAGE_UNITS_PATH)

    ner = unit_by_id(text, "TU-TEXT-NER-BOUNDARY-001")
    assert "boundary_cases" in ner
    assert {case["case_type"] for case in ner["boundary_cases"]} >= {
        "include",
        "exclude",
    }

    occlusion = unit_by_id(image, "TU-IMAGE-OCCLUSION-TRUNCATION-001")
    assert "occlusion" in occlusion["rule_explanation"]
    assert "truncation" in occlusion["rule_explanation"]
    assert {case["condition"] for case in occlusion["boundary_cases"]} >= {
        "occlusion",
        "truncation",
        "both",
    }

    ambiguity = unit_by_id(text, "TU-TEXT-INTENT-AMBIGUITY-001")
    evaluation = ambiguity["exercise"]["evaluation"]
    assert evaluation["method"] == "allowed_answers"
    allowed = evaluation["allowed_answers"]
    assert any(item["score"] == 1.0 for item in allowed)
    assert any(0.0 < item["score"] < 1.0 for item in allowed)
    assert any(item["manual_review_required"] for item in allowed)
    assert evaluation["manual_review_conditions"]


def test_evaluator_supports_exact_ordered_and_allowed_answer_scoring():
    evaluator = load_module(EVALUATOR_PATH, "task3_evaluator")
    central = load_json(CENTRAL_UNITS_PATH)
    text = load_json(TEXT_UNITS_PATH)
    image = load_json(IMAGE_UNITS_PATH)

    exact_unit = unit_by_id(central, "TU-AUDIO-DATA-BINDING-001")
    exact = evaluator.evaluate_unit(exact_unit, exact_unit["exercise"]["answer"])
    assert exact["score"] == 1.0
    assert exact["passed"] is True

    ordered_unit = unit_by_id(image, "TU-IMAGE-POLYGON-VERTICES-001")
    ordered_answer = ordered_unit["exercise"]["answer"]
    ordered = evaluator.evaluate_unit(ordered_unit, ordered_answer)
    assert ordered["score"] == 1.0
    reversed_submission = dict(ordered_answer)
    list_field = next(
        key for key, value in reversed_submission.items() if isinstance(value, list)
    )
    reversed_submission[list_field] = list(reversed(reversed_submission[list_field]))
    reversed_result = evaluator.evaluate_unit(ordered_unit, reversed_submission)
    assert reversed_result["score"] == 0.0
    assert reversed_result["passed"] is False

    ambiguous = unit_by_id(text, "TU-TEXT-INTENT-AMBIGUITY-001")
    candidates = ambiguous["exercise"]["evaluation"]["allowed_answers"]
    full = next(item for item in candidates if item["score"] == 1.0)
    partial = next(item for item in candidates if 0.0 < item["score"] < 1.0)

    full_result = evaluator.evaluate_unit(ambiguous, full["answer"])
    assert full_result["score"] == 1.0
    assert full_result["passed"] is True
    assert full_result["manual_review_required"] is False

    partial_result = evaluator.evaluate_unit(ambiguous, partial["answer"])
    assert partial_result["score"] == partial["score"]
    assert partial_result["passed"] is False
    assert partial_result["manual_review_required"] is True
    assert partial_result["error_type"] == partial["error_type"]


def test_evaluator_result_contract_and_serialization_are_deterministic():
    evaluator = load_module(EVALUATOR_PATH, "task3_evaluator_determinism")
    text = load_json(TEXT_UNITS_PATH)
    unit = unit_by_id(text, "TU-TEXT-LABEL-VOCAB-001")
    submission = {"valid": False}

    first = evaluator.evaluate_unit(unit, submission)
    second = evaluator.evaluate_unit(unit, submission)
    assert set(first) == RESULT_FIELDS
    assert first == second
    assert evaluator.serialize_result(first) == evaluator.serialize_result(second)
    assert first["score"] == 0.0
    assert first["passed"] is False
    assert first["rule_refs"] == unit["rule_refs"]
    assert first["capability_refs"] == unit["exercise"]["capability_refs"]
    assert first["error_type"]
    assert first["feedback"]
    assert first["remediation"]
    assert first["data_version"] == unit["exercise"]["data_version"]
    assert first["evaluation_version"] == unit["exercise"]["evaluation"]["version"]


def test_curriculum_builder_is_deterministic_and_preserves_legacy_domains(tmp_path):
    if not BUILD_CURRICULUM_PATH.exists():
        pytest.skip(f"Task 3 builder is missing: {BUILD_CURRICULUM_PATH}")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    command = (
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        ROOT / "data" / "curriculum",
        "--legacy-central",
        CENTRAL_UNITS_PATH,
    )
    first_result = run_python(*command, "--output", first)
    second_result = run_python(*command, "--output", second)
    assert first_result.returncode == 0, first_result.stderr or first_result.stdout
    assert second_result.returncode == 0, second_result.stderr or second_result.stdout
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == CENTRAL_UNITS_PATH.read_bytes()

    legacy = load_json(CENTRAL_UNITS_PATH)
    rebuilt = load_json(first)
    legacy_units = {
        unit["id"]: unit
        for unit in legacy["units"]
        if unit["data_type"] in {"audio", "video"}
    }
    rebuilt_units = {unit["id"]: unit for unit in rebuilt["units"]}
    assert legacy_units
    for unit_id, unit in legacy_units.items():
        assert rebuilt_units[unit_id] == unit
    assert [unit["id"] for unit in rebuilt["units"]] == sorted(rebuilt_units)


def test_curriculum_builder_rejects_duplicate_ids_and_noncanonical_domain_order(
    tmp_path,
):
    if not BUILD_CURRICULUM_PATH.exists():
        pytest.skip(f"Task 3 builder is missing: {BUILD_CURRICULUM_PATH}")
    curriculum_root = tmp_path / "curriculum"
    shutil.copytree(TEXT_UNITS_PATH.parent, curriculum_root / "text")
    shutil.copytree(IMAGE_UNITS_PATH.parent, curriculum_root / "image")

    image_path = curriculum_root / "image" / "teaching-units.json"
    image = load_json(image_path)
    image["units"][0]["id"] = load_json(TEXT_UNITS_PATH)["units"][0]["id"]
    image["units"].sort(key=lambda unit: unit["id"])
    image_path.write_text(
        json.dumps(image, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    duplicate = run_python(
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        curriculum_root,
        "--legacy-central",
        CENTRAL_UNITS_PATH,
        "--output",
        tmp_path / "duplicate.json",
    )
    assert duplicate.returncode != 0
    assert "duplicate teaching unit ID" in (duplicate.stdout + duplicate.stderr)

    shutil.rmtree(curriculum_root)
    shutil.copytree(TEXT_UNITS_PATH.parent, curriculum_root / "text")
    shutil.copytree(IMAGE_UNITS_PATH.parent, curriculum_root / "image")
    text_path = curriculum_root / "text" / "teaching-units.json"
    text = load_json(text_path)
    text["units"].reverse()
    text_path.write_text(
        json.dumps(text, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    unstable = run_python(
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        curriculum_root,
        "--legacy-central",
        CENTRAL_UNITS_PATH,
        "--output",
        tmp_path / "unstable.json",
    )
    assert unstable.returncode != 0
    assert "non-canonical teaching unit ordering" in (
        unstable.stdout + unstable.stderr
    )


def test_task_nodes_link_all_text_and_image_candidate_units():
    catalog = load_json(GRAPH_CATALOG_PATH)
    tasks = {task["id"]: task for task in catalog["nodes"]["TSK"]}
    expected = {
        "TSK-TXT-LABEL-AUDIT-001": {"TU-TEXT-LABEL-VOCAB-001"},
        "TSK-TXT-DOCUMENT-CLASSIFY-001": {"TU-TEXT-DOCUMENT-CLASSIFY-001"},
        "TSK-TXT-NER-ANNOTATE-001": {"TU-TEXT-NER-BOUNDARY-001"},
        "TSK-TXT-RELATION-LINK-001": {"TU-TEXT-RELATION-DIRECTION-001"},
        "TSK-TXT-INTENT-REVIEW-001": {"TU-TEXT-INTENT-AMBIGUITY-001"},
        "TSK-IMG-RECT-AUDIT-001": {"TU-IMAGE-RECT-BOUNDS-001"},
        "TSK-IMG-OBJECT-BOX-001": {"TU-IMAGE-OCCLUSION-TRUNCATION-001"},
        "TSK-IMG-POLYGON-TRACE-001": {"TU-IMAGE-POLYGON-VERTICES-001"},
        "TSK-IMG-KEYPOINT-MARK-001": {"TU-IMAGE-KEYPOINT-VISIBILITY-001"},
        "TSK-IMG-MASK-REVIEW-001": {"TU-IMAGE-MASK-INSTANCE-001"},
    }
    for task_id, unit_ids in expected.items():
        assert unit_ids <= set(tasks[task_id].get("teaching_unit_refs", []))


def test_candidate_sources_record_context7_and_local_policy_boundaries():
    registry = load_json(SOURCE_REGISTRY_PATH)
    sources = {source["source_id"]: source for source in registry["sources"]}
    context7_ids = {
        "SRC-LS-CHOICES-PINNED-001",
        "SRC-LS-TEXT-SPANS-PINNED-001",
        "SRC-LS-RELATIONS-PINNED-001",
        "SRC-CVAT-ANNOTATION-FORMAT-251",
    }
    for source_id in context7_ids:
        source = sources[source_id]
        verification = source["verification"]
        assert verification["method"] == "context7_official_documentation_lookup"
        assert verification["content_verified"] is True
        assert verification["path_verified"] is True
        assert verification["direct_http_license_verified"] is False
        assert verification["remaining_license_pin_risk"]
        assert "HTTP" not in source["verified_by"]

    for source_id, data_type in (
        ("SRC-POLICY-TEXT-TASK3-001", "text"),
        ("SRC-POLICY-IMAGE-TASK3-001", "image"),
    ):
        source = sources[source_id]
        assert source["data_type"] == data_type
        assert source["source_kind"] == "project_policy"
        assert source["authority_scope"] == "local_project_policy_only"
        assert source["license_or_authorization"]["publishable"] is False
        assert source["usage_rights"]["asset_redistribution_allowed"] is False
