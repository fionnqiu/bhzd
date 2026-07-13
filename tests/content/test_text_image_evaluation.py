import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEXT_UNITS_PATH = ROOT / "data" / "curriculum" / "text" / "teaching-units.json"
IMAGE_UNITS_PATH = ROOT / "data" / "curriculum" / "image" / "teaching-units.json"
AUDIO_UNITS_ROOT = ROOT / "data" / "curriculum" / "audio"
VIDEO_UNITS_ROOT = ROOT / "data" / "curriculum" / "video"
CENTRAL_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
LEGACY_UNITS_PATH = (
    ROOT / "data" / "curriculum" / "legacy" / "teaching-units.json"
)
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
REVIEW_REGISTRY_PATH = ROOT / "data" / "reviews" / "content-review-registry.json"
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
APPROVED_REVIEW_IDS = {
    "text": "REVIEW-TASK3-TEXT-06EEE9AA-002",
    "image": "REVIEW-TASK3-IMAGE-06EEE9A-001",
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


def canonical_content_digest(unit: dict) -> str:
    reviewed_content = copy.deepcopy(unit)
    for field in ("review_status", "student_visible", "review_records"):
        reviewed_content.pop(field, None)
    canonical = json.dumps(
        reviewed_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def copy_curriculum_sources(destination: Path) -> Path:
    curriculum_root = destination / "curriculum"
    shutil.copytree(TEXT_UNITS_PATH.parent, curriculum_root / "text")
    shutil.copytree(IMAGE_UNITS_PATH.parent, curriculum_root / "image")
    shutil.copytree(AUDIO_UNITS_ROOT, curriculum_root / "audio")
    shutil.copytree(VIDEO_UNITS_ROOT, curriculum_root / "video")
    shutil.copytree(LEGACY_UNITS_PATH.parent, curriculum_root / "legacy")
    return curriculum_root


def synthetic_unit(method: str, answer: object) -> dict:
    return {
        "rule_refs": ["KNG-TEST-001"],
        "remediation": ["重新检查提交。"],
        "exercise": {
            "answer": answer,
            "data_version": "test-data-1",
            "capability_refs": ["CAP-TEST-001"],
            "error_types": ["wrong_type", "wrong_value"],
            "evaluation": {
                "method": method,
                "version": "test-eval-1",
                "incorrect_feedback": {
                    "error_type": "wrong_type",
                    "feedback": "类型错误。",
                    "remediation": ["保留 JSON 类型。"],
                },
            },
        },
    }


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
        assert unit["review_status"] in {"draft", "reviewed", "published"}
        assert isinstance(unit["review_records"], list)
        if unit["review_status"] != "published":
            assert unit["student_visible"] is False


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

    exact_unit = unit_by_id(central, "TU-TEXT-DOCUMENT-CLASSIFY-001")
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


@pytest.mark.parametrize("pass_score", (0, 0.5, 1))
def test_allowed_answers_accept_finite_numeric_pass_score_boundaries(pass_score):
    evaluator = load_module(EVALUATOR_PATH, f"pass_score_boundary_{pass_score}")
    unit = copy.deepcopy(
        unit_by_id(load_json(TEXT_UNITS_PATH), "TU-TEXT-INTENT-AMBIGUITY-001")
    )
    evaluation = unit["exercise"]["evaluation"]
    candidate = next(
        item
        for item in evaluation["allowed_answers"]
        if item["score"] == 1.0 and not item["manual_review_required"]
    )
    evaluation["pass_score"] = pass_score
    assert evaluator.evaluate_unit(unit, candidate["answer"])["passed"] is True


def test_allowed_answers_default_pass_score_is_one():
    evaluator = load_module(EVALUATOR_PATH, "pass_score_default")
    unit = copy.deepcopy(
        unit_by_id(load_json(TEXT_UNITS_PATH), "TU-TEXT-INTENT-AMBIGUITY-001")
    )
    evaluation = unit["exercise"]["evaluation"]
    evaluation.pop("pass_score", None)
    full = next(item for item in evaluation["allowed_answers"] if item["score"] == 1.0)
    partial = next(
        item for item in evaluation["allowed_answers"] if 0 < item["score"] < 1
    )
    assert evaluator.evaluate_unit(unit, full["answer"])["passed"] is True
    assert evaluator.evaluate_unit(unit, partial["answer"])["passed"] is False


@pytest.mark.parametrize(
    "pass_score",
    (True, False, "0.5", None, float("nan"), float("inf"), -0.01, 1.01),
    ids=("true", "false", "string", "null", "nan", "infinity", "negative", "above-one"),
)
def test_allowed_answers_reject_invalid_pass_scores(pass_score):
    evaluator = load_module(EVALUATOR_PATH, f"pass_score_invalid_{pass_score!r}")
    unit = copy.deepcopy(
        unit_by_id(load_json(TEXT_UNITS_PATH), "TU-TEXT-INTENT-AMBIGUITY-001")
    )
    evaluation = unit["exercise"]["evaluation"]
    candidate = next(item for item in evaluation["allowed_answers"] if item["score"] == 1.0)
    evaluation["pass_score"] = pass_score
    with pytest.raises(ValueError, match="pass_score"):
        evaluator.evaluate_unit(unit, candidate["answer"])


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


@pytest.mark.parametrize(
    ("method", "answer", "submission"),
    (
        ("exact_match", {"value": True}, {"value": 1}),
        ("exact_match", {"value": 1}, {"value": 1.0}),
        ("ordered_exact_match", {"values": [True]}, {"values": [1]}),
        ("ordered_exact_match", {"values": [1]}, {"values": [1.0]}),
    ),
)
def test_exact_methods_preserve_json_scalar_types(method, answer, submission):
    evaluator = load_module(EVALUATOR_PATH, f"strict_json_{method}_{answer!r}")
    result = evaluator.evaluate_unit(synthetic_unit(method, answer), submission)
    assert result["score"] == 0.0
    assert result["passed"] is False


@pytest.mark.parametrize(
    "missing_field",
    (
        "answer",
        "score",
        "manual_review_required",
        "error_type",
        "feedback",
        "remediation",
    ),
)
def test_allowed_answers_require_complete_explicit_candidates(missing_field):
    evaluator = load_module(EVALUATOR_PATH, f"allowed_schema_{missing_field}")
    text = load_json(TEXT_UNITS_PATH)
    unit = copy.deepcopy(unit_by_id(text, "TU-TEXT-INTENT-AMBIGUITY-001"))
    candidate = unit["exercise"]["evaluation"]["allowed_answers"][0]
    candidate.pop(missing_field)
    with pytest.raises(ValueError, match=missing_field):
        evaluator.evaluate_unit(unit, unit["exercise"]["answer"])


def test_diagnostic_rules_use_declared_order_before_default_feedback():
    evaluator = load_module(EVALUATOR_PATH, "diagnostic_precedence")
    unit = synthetic_unit("exact_match", {"value": "correct"})
    unit["exercise"]["evaluation"]["diagnostic_rules"] = [
        {
            "submission": {"value": 1},
            "error_type": "wrong_type",
            "feedback": "值必须是字符串。",
            "remediation": ["保留字符串类型。"],
        },
        {
            "submission": {"value": "other"},
            "error_type": "wrong_value",
            "feedback": "字符串值不匹配。",
            "remediation": ["核对允许值。"],
        },
    ]
    unit["exercise"]["evaluation"]["diagnostic_precedence"] = (
        "diagnostic_rules first, then answer, then incorrect_feedback"
    )
    result = evaluator.evaluate_unit(unit, {"value": "other"})
    assert result["error_type"] == "wrong_value"
    assert result["feedback"] == "字符串值不匹配。"
    assert result["remediation"] == ["核对允许值。"]


def test_diagnostic_contract_requires_precedence_and_disjoint_submissions():
    evaluator = load_module(EVALUATOR_PATH, "diagnostic_contract")
    unit = synthetic_unit("exact_match", {"value": "correct"})
    unit["exercise"]["evaluation"]["diagnostic_rules"] = [
        {
            "submission": {"value": "other"},
            "error_type": "wrong_value",
            "feedback": "字符串值不匹配。",
            "remediation": ["核对允许值。"],
        }
    ]
    with pytest.raises(ValueError, match="diagnostic_precedence"):
        evaluator.evaluate_unit(unit, {"value": "other"})

    unit["exercise"]["evaluation"]["diagnostic_precedence"] = (
        "diagnostic_rules first, then answer, then incorrect_feedback"
    )
    unit["exercise"]["evaluation"]["diagnostic_rules"][0]["submission"] = {
        "value": "correct"
    }
    with pytest.raises(ValueError, match="overlap"):
        evaluator.evaluate_unit(unit, {"value": "correct"})


def test_every_declared_candidate_error_is_deterministically_reachable():
    evaluator = load_module(EVALUATOR_PATH, "diagnostic_reachability")
    for path in (TEXT_UNITS_PATH, IMAGE_UNITS_PATH):
        document = load_json(path)
        for unit in document["units"]:
            evaluation = unit["exercise"]["evaluation"]
            rules = evaluation.get("diagnostic_rules", [])
            assert rules, f"{unit['id']} must define ordered diagnostic_rules"
            canonical_submissions = [
                evaluator.canonical_json(rule["submission"]) for rule in rules
            ]
            assert len(canonical_submissions) == len(set(canonical_submissions))

            reachable = {rule["error_type"] for rule in rules}
            default_feedback = evaluation["incorrect_feedback"]
            if isinstance(default_feedback, dict):
                reachable.add(default_feedback["error_type"])
            for candidate in evaluation.get("allowed_answers", []):
                if candidate["error_type"] is not None:
                    reachable.add(candidate["error_type"])
            assert set(unit["exercise"]["error_types"]) == reachable

            for rule in rules:
                result = evaluator.evaluate_unit(unit, rule["submission"])
                assert result["error_type"] == rule["error_type"]
                assert result["feedback"] == rule["feedback"]
                assert result["remediation"] == rule["remediation"]


def test_candidate_prerequisites_follow_graph_predecessors():
    text = load_json(TEXT_UNITS_PATH)
    image = load_json(IMAGE_UNITS_PATH)
    expected = {
        "TU-TEXT-LABEL-VOCAB-001": ["CAP-CORE-LABEL-SCHEMA-001"],
        "TU-TEXT-DOCUMENT-CLASSIFY-001": ["CAP-TXT-LABEL-VALIDATE-001"],
        "TU-TEXT-NER-BOUNDARY-001": ["CAP-TXT-LABEL-VALIDATE-001"],
        "TU-TEXT-RELATION-DIRECTION-001": ["CAP-TXT-ENTITY-TYPE-001"],
        "TU-TEXT-INTENT-AMBIGUITY-001": [
            "CAP-TXT-CLASSIFY-001",
            "CAP-TXT-RELATION-001",
        ],
        "TU-IMAGE-RECT-BOUNDS-001": ["CAP-CORE-ASSET-QUALITY-001"],
        "TU-IMAGE-OCCLUSION-TRUNCATION-001": ["CAP-IMG-BOX-ANNOTATE-001"],
        "TU-IMAGE-POLYGON-VERTICES-001": ["CAP-IMG-BOX-ANNOTATE-001"],
        "TU-IMAGE-KEYPOINT-VISIBILITY-001": ["CAP-IMG-OBJECT-CLASS-001"],
        "TU-IMAGE-MASK-INSTANCE-001": ["CAP-IMG-SEMANTIC-SEGMENT-001"],
    }
    units = {unit["id"]: unit for unit in text["units"] + image["units"]}
    for unit_id, prerequisites in expected.items():
        assert units[unit_id]["prerequisites"] == prerequisites


def test_failed_ai_reviews_are_recorded_without_publication_authority():
    assert REVIEW_REGISTRY_PATH.exists(), "content review registry is missing"
    registry = load_json(REVIEW_REGISTRY_PATH)
    records = {
        record["reviewer_id"]: record
        for record in registry["records"]
        if record["decision"] == "changes_required"
    }
    assert set(records) >= {
        "codex-task3-text-review",
        "codex-task3-image-review",
    }
    for reviewer_id in (
        "codex-task3-text-review",
        "codex-task3-image-review",
    ):
        record = records[reviewer_id]
        assert record["reviewer_type"] == "ai_agent"
        assert record["reviewed_commit"].startswith("c05413a")
        assert record["decision"] == "changes_required"
        assert record["authorizes_publication"] is False
        assert record["finding_count"] == len(record["findings"])
        assert record["finding_count"] > 0
        assert record["remaining_risks"]


def test_approved_ai_reviews_bind_clean_commit_versions_and_development_scope():
    registry = load_json(REVIEW_REGISTRY_PATH)
    records = {record["review_id"]: record for record in registry["records"]}
    expected = {
        APPROVED_REVIEW_IDS["text"]: {
            "reviewer_id": "codex-task3-text-review",
            "reviewed_at": "2026-07-12T22:23:13+08:00",
            "unit_ids": TEXT_UNIT_IDS,
        },
        APPROVED_REVIEW_IDS["image"]: {
            "reviewer_id": "codex-task3-image-review",
            "reviewed_at": "2026-07-12",
            "unit_ids": IMAGE_UNIT_IDS,
        },
    }
    units_by_id = {
        unit["id"]: unit
        for document in (load_json(TEXT_UNITS_PATH), load_json(IMAGE_UNITS_PATH))
        for unit in document["units"]
    }
    for review_id, expected_record in expected.items():
        record = records[review_id]
        assert record["reviewer_id"] == expected_record["reviewer_id"]
        assert record["reviewer_type"] == "ai_agent"
        assert record["independent_of_implementation"] is True
        assert record["reviewed_at"] == expected_record["reviewed_at"]
        assert record["reviewed_commit"] == (
            "06eee9aa8a7c921bc9db4900bd52f72353fc84e2"
        )
        assert re.fullmatch(r"[0-9a-f]{40}", record["reviewed_commit"])
        assert set(record["scope"]["unit_ids"]) == expected_record["unit_ids"]
        assert record["decision"] == "approved"
        assert record["findings"] == []
        assert record["finding_count"] == 0
        assert record["authorizes_publication"] is True
        assert record["publication_scope"] == "development_only"
        assert record["human_release_allowed"] is False
        assert record["remaining_risks"]
        versions = {version["unit_id"]: version for version in record["unit_versions"]}
        assert set(versions) == expected_record["unit_ids"]
        for version in versions.values():
            assert version["data_version"] == "1.1.0"
            assert version["evaluation_version"] == "1.1.0"
            assert version["content_digest"] == canonical_content_digest(
                units_by_id[version["unit_id"]]
            )


def test_task3_development_publication_remains_visible_after_task5_video_release():
    text = load_json(TEXT_UNITS_PATH)
    image = load_json(IMAGE_UNITS_PATH)
    central = load_json(CENTRAL_UNITS_PATH)
    sources_document = load_json(SOURCE_REGISTRY_PATH)
    sources = {
        source["source_id"]: source for source in sources_document["sources"]
    }
    expected_visible = TEXT_UNIT_IDS | IMAGE_UNIT_IDS

    for document in (text, image):
        expected_review = APPROVED_REVIEW_IDS[document["data_type"]]
        for unit in document["units"]:
            assert unit["review_status"] == "published"
            assert unit["student_visible"] is True
            assert unit["review_records"] == [expected_review]
            for source_ref in unit["source_refs"]:
                source = sources[source_ref]
                assert source["status"] == "verified"
                assert source["license_or_authorization"]["publishable"] is True
                assert source["usage_rights"]["citation_allowed"] is True

    visible_ids = set(central["student_visible_unit_ids"])
    assert expected_visible <= visible_ids
    assert visible_ids - expected_visible == {
        "TU-VIDEO-BEHAVIOR-EVENT-001",
        "TU-VIDEO-FRAME-ANNOTATION-001",
        "TU-VIDEO-OBJECT-TRACKING-001",
    }
    central_units = {unit["id"]: unit for unit in central["units"]}
    for unit in text["units"] + image["units"]:
        assert central_units[unit["id"]] == unit
    for unit in central["units"]:
        if unit["data_type"] == "audio":
            assert unit["review_status"] == "draft"
            assert unit["student_visible"] is False
        elif unit["data_type"] == "video":
            assert unit["review_status"] == "published"
            assert unit["student_visible"] is True
            assert unit["id"] in central["student_visible_unit_ids"]

    for source_id in (
        "SRC-POLICY-TEXT-TASK3-001",
        "SRC-POLICY-IMAGE-TASK3-001",
    ):
        assert sources[source_id]["human_release_allowed"] is False


def test_semantic_tasks_use_local_policy_primary_knowledge():
    catalog = load_json(GRAPH_CATALOG_PATH)
    tasks = {task["id"]: task for task in catalog["nodes"]["TSK"]}
    expected = {
        "TSK-TXT-DOCUMENT-CLASSIFY-001": "KNG-TXT-SINGLE-MULTI-LABEL-001",
        "TSK-TXT-NER-ANNOTATE-001": "KNG-TXT-ENTITY-BOUNDARY-001",
        "TSK-TXT-RELATION-LINK-001": "KNG-TXT-RELATION-DIRECTION-001",
        "TSK-IMG-RECT-AUDIT-001": "KNG-IMG-RECT-BOUNDS-001",
        "TSK-IMG-OBJECT-BOX-001": "KNG-IMG-OCCLUSION-TRUNCATION-001",
        "TSK-IMG-POLYGON-TRACE-001": "KNG-IMG-POLYGON-VERTEX-001",
        "TSK-IMG-KEYPOINT-MARK-001": "KNG-IMG-KEYPOINT-VISIBILITY-001",
        "TSK-IMG-MASK-REVIEW-001": "KNG-IMG-INSTANCE-ID-001",
    }
    knowledge = {node["id"]: node for node in catalog["nodes"]["KNG"]}
    for task_id, knowledge_id in expected.items():
        assert tasks[task_id]["primary_knowledge_ref"] == knowledge_id
        if task_id != "TSK-TXT-DOCUMENT-CLASSIFY-001":
            assert knowledge[knowledge_id]["policy_overlays"]


def test_curriculum_builder_is_deterministic_without_reading_central_output(tmp_path):
    if not BUILD_CURRICULUM_PATH.exists():
        pytest.skip(f"Task 3 builder is missing: {BUILD_CURRICULUM_PATH}")
    curriculum_root = copy_curriculum_sources(tmp_path)
    output = curriculum_root / "teaching-units.json"
    command = (
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        curriculum_root,
        "--legacy-snapshot",
        curriculum_root / "legacy" / "teaching-units.json",
        "--source-registry",
        SOURCE_REGISTRY_PATH,
        "--review-registry",
        REVIEW_REGISTRY_PATH,
        "--output",
        output,
    )
    first = run_python(*command)
    assert first.returncode == 0, first.stderr or first.stdout
    assert output.read_bytes() == CENTRAL_UNITS_PATH.read_bytes()

    output.write_text('{"corrupt":true}\n', encoding="utf-8")
    second = run_python(*command)
    assert second.returncode == 0, second.stderr or second.stdout
    assert output.read_bytes() == CENTRAL_UNITS_PATH.read_bytes()

    output.unlink()
    third = run_python(*command)
    assert third.returncode == 0, third.stderr or third.stdout
    assert output.read_bytes() == CENTRAL_UNITS_PATH.read_bytes()


def test_curriculum_domain_sources_override_legacy_by_domain(tmp_path):
    curriculum_root = copy_curriculum_sources(tmp_path)
    audio_path = curriculum_root / "audio" / "01-foundations.json"
    audio_document = load_json(audio_path)
    audio_unit = audio_document["units"][0]
    audio_unit["title"] = "显式音频域事实源"
    audio_path.write_text(
        json.dumps(audio_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "override.json"
    result = run_python(
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        curriculum_root,
        "--legacy-snapshot",
        curriculum_root / "legacy" / "teaching-units.json",
        "--output",
        output,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    rebuilt = load_json(output)
    assert unit_by_id(rebuilt, audio_unit["id"])["title"] == "显式音频域事实源"
    assert not any(
        unit["id"] == "TU-AUDIO-DATA-BINDING-001" for unit in rebuilt["units"]
    )
    assert any(unit["data_type"] == "video" for unit in rebuilt["units"])


def test_curriculum_builder_rejects_duplicate_legacy_snapshot_ids(tmp_path):
    curriculum_root = copy_curriculum_sources(tmp_path)
    legacy_path = curriculum_root / "legacy" / "teaching-units.json"
    legacy = load_json(legacy_path)
    legacy["units"].append(copy.deepcopy(legacy["units"][0]))
    legacy_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = run_python(
        BUILD_CURRICULUM_PATH,
        "--curriculum-root",
        curriculum_root,
        "--legacy-snapshot",
        legacy_path,
        "--output",
        tmp_path / "duplicate-legacy.json",
    )
    assert result.returncode != 0
    assert "duplicate teaching unit ID" in (result.stdout + result.stderr)


def test_curriculum_builder_rejects_duplicate_ids_and_noncanonical_domain_order(
    tmp_path,
):
    if not BUILD_CURRICULUM_PATH.exists():
        pytest.skip(f"Task 3 builder is missing: {BUILD_CURRICULUM_PATH}")
    curriculum_root = tmp_path / "curriculum"
    shutil.copytree(TEXT_UNITS_PATH.parent, curriculum_root / "text")
    shutil.copytree(IMAGE_UNITS_PATH.parent, curriculum_root / "image")
    shutil.copytree(AUDIO_UNITS_ROOT, curriculum_root / "audio")
    shutil.copytree(VIDEO_UNITS_ROOT, curriculum_root / "video")

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
        "--legacy-snapshot",
        LEGACY_UNITS_PATH,
        "--output",
        tmp_path / "duplicate.json",
    )
    assert duplicate.returncode != 0
    assert "duplicate teaching unit ID" in (duplicate.stdout + duplicate.stderr)

    shutil.rmtree(curriculum_root)
    shutil.copytree(TEXT_UNITS_PATH.parent, curriculum_root / "text")
    shutil.copytree(IMAGE_UNITS_PATH.parent, curriculum_root / "image")
    shutil.copytree(AUDIO_UNITS_ROOT, curriculum_root / "audio")
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
        "--legacy-snapshot",
        LEGACY_UNITS_PATH,
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
        context7 = verification["prior_context7_evidence"]
        assert context7["method"] == "context7_official_documentation_lookup"
        assert context7["content_verified"] is True
        assert context7["path_verified"] is True
        assert verification["method"] == "direct_raw_github_http_get"
        assert verification["license_http_status"] == 200

    for source_id, data_type in (
        ("SRC-POLICY-TEXT-TASK3-001", "text"),
        ("SRC-POLICY-IMAGE-TASK3-001", "image"),
    ):
        source = sources[source_id]
        assert source["data_type"] == data_type
        assert source["source_kind"] == "project_policy"
        assert source["authority_scope"] == "local_project_policy_only"
        assert source["license_or_authorization"]["publishable"] is True
        assert source["publication_scope"] == "development_only"
        assert source["human_release_allowed"] is False
        assert source["usage_rights"]["asset_redistribution_allowed"] is False


def test_pinned_sources_record_direct_tag_document_and_license_evidence():
    registry = load_json(SOURCE_REGISTRY_PATH)
    sources = {source["source_id"]: source for source in registry["sources"]}
    expected_paths = {
        "SRC-LS-CHOICES-PINNED-001": (
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/docs/source/tags/choices.md",
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/LICENSE",
        ),
        "SRC-LS-TEXT-SPANS-PINNED-001": (
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/docs/source/tags/labels.md",
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/LICENSE",
        ),
        "SRC-LS-RELATIONS-PINNED-001": (
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/docs/source/tags/relations.md",
            "https://raw.githubusercontent.com/HumanSignal/label-studio/1.19.0/LICENSE",
        ),
        "SRC-CVAT-ANNOTATION-FORMAT-251": (
            "https://raw.githubusercontent.com/cvat-ai/cvat/v2.51.0/site/content/en/docs/dataset_management/formats/format-cvat.md",
            "https://raw.githubusercontent.com/cvat-ai/cvat/v2.51.0/LICENSE",
        ),
    }
    for source_id, (document_url, license_url) in expected_paths.items():
        source = sources[source_id]
        assert source["original_url_or_local_archive"] == document_url
        assert source["license_or_authorization"]["license_url"] == license_url
        assert source["status"] == "verified"
        assert source["license_or_authorization"]["publishable"] is True
        assert source["usage_rights"]["citation_allowed"] is True
        verification = source["verification"]
        assert verification["method"] == "direct_raw_github_http_get"
        assert verification["document_http_status"] == 200
        assert verification["license_http_status"] == 200
        assert verification["verified_at"] == "2026-07-12"

    for source_id in (
        "SRC-POLICY-TEXT-TASK3-001",
        "SRC-POLICY-IMAGE-TASK3-001",
    ):
        source = sources[source_id]
        assert source["status"] == "verified"
        assert source["license_or_authorization"]["publishable"] is True
        assert source["publication_scope"] == "development_only"
        assert source["human_release_allowed"] is False


def make_sources_eligible_for_unit(source_registry: dict, unit: dict) -> None:
    sources = {source["source_id"]: source for source in source_registry["sources"]}
    for source_ref in unit["source_refs"]:
        source = sources[source_ref]
        source["status"] = "verified"
        source["license_or_authorization"]["publishable"] = True
        source["usage_rights"]["citation_allowed"] = True


def approved_review_for(unit: dict) -> dict:
    return {
        "review_id": "REVIEW-TEST-APPROVED-001",
        "reviewer_id": "independent-test-reviewer",
        "reviewer_type": "ai_agent",
        "independent_of_implementation": True,
        "reviewed_at": "2026-07-12",
        "reviewed_commit": "0" * 40,
        "scope": {"data_type": unit["data_type"], "unit_ids": [unit["id"]]},
        "unit_versions": [
            {
                "unit_id": unit["id"],
                "data_version": unit["exercise"]["data_version"],
                "evaluation_version": unit["exercise"]["evaluation"]["version"],
                "content_digest": canonical_content_digest(unit),
            }
        ],
        "decision": "approved",
        "findings": [],
        "finding_count": 0,
        "remaining_risks": [],
        "authorizes_publication": True,
    }


def test_publication_contract_requires_eligible_sources_and_approved_review():
    builder = load_module(BUILD_CURRICULUM_PATH, "publication_contract")
    assert hasattr(builder, "validate_publication_contract")
    central = load_json(CENTRAL_UNITS_PATH)
    sources = load_json(SOURCE_REGISTRY_PATH)
    reviews = (
        load_json(REVIEW_REGISTRY_PATH)
        if REVIEW_REGISTRY_PATH.exists()
        else {"schema_version": "1.0.0", "records": []}
    )
    candidate = next(unit for unit in central["units"] if unit["data_type"] == "text")

    reviewed = copy.deepcopy(central)
    unit = next(item for item in reviewed["units"] if item["id"] == candidate["id"])
    unit["review_status"] = "reviewed"
    unit["student_visible"] = False
    unit["review_records"] = ["REVIEW-TASK3-TEXT-C05413A-001"]
    reviewed["student_visible_unit_ids"].remove(unit["id"])
    eligible_sources = copy.deepcopy(sources)
    make_sources_eligible_for_unit(eligible_sources, unit)

    with pytest.raises(ValueError, match="approved review"):
        builder.validate_publication_contract(reviewed, eligible_sources, reviews)

    approved_reviews = copy.deepcopy(reviews)
    approved_reviews["records"].append(approved_review_for(unit))
    unit["review_records"].append("REVIEW-TEST-APPROVED-001")
    ineligible_sources = copy.deepcopy(eligible_sources)
    source = next(
        item
        for item in ineligible_sources["sources"]
        if item["source_id"] == unit["source_refs"][0]
    )
    source["license_or_authorization"]["publishable"] = False
    with pytest.raises(ValueError, match="source eligibility"):
        builder.validate_publication_contract(
            reviewed, ineligible_sources, approved_reviews
        )

    builder.validate_publication_contract(reviewed, eligible_sources, approved_reviews)


@pytest.mark.parametrize(
    "mutation",
    ("rule_explanation", "student_action", "answer"),
)
def test_publication_contract_rejects_stale_review_after_content_mutation(mutation):
    builder = load_module(BUILD_CURRICULUM_PATH, f"stale_review_{mutation}")
    central = copy.deepcopy(load_json(CENTRAL_UNITS_PATH))
    unit = next(item for item in central["units"] if item["data_type"] == "text")
    if mutation == "rule_explanation":
        unit["rule_explanation"] = {"mutated_without_version_bump": True}
    elif mutation == "student_action":
        unit["exercise"]["student_action"] += " mutated"
    else:
        unit["exercise"]["answer"] = {"mutated_without_version_bump": True}

    with pytest.raises(ValueError, match="content_digest"):
        builder.validate_publication_contract(
            central,
            load_json(SOURCE_REGISTRY_PATH),
            load_json(REVIEW_REGISTRY_PATH),
        )


def test_publication_contract_requires_lowercase_full_reviewed_commit():
    builder = load_module(BUILD_CURRICULUM_PATH, "reviewed_commit_format")
    reviews = copy.deepcopy(load_json(REVIEW_REGISTRY_PATH))
    approved = next(record for record in reviews["records"] if record["decision"] == "approved")
    approved["reviewed_commit"] = "ABC123"
    with pytest.raises(ValueError, match="reviewed_commit"):
        builder.validate_publication_contract(
            load_json(CENTRAL_UNITS_PATH),
            load_json(SOURCE_REGISTRY_PATH),
            reviews,
        )


@pytest.mark.parametrize("case", ("missing", "empty", "duplicate", "malformed"))
def test_non_draft_units_require_well_formed_unique_source_refs(case):
    builder = load_module(BUILD_CURRICULUM_PATH, f"source_refs_{case}")
    central = copy.deepcopy(load_json(CENTRAL_UNITS_PATH))
    unit = next(item for item in central["units"] if item["review_status"] != "draft")
    if case == "missing":
        unit.pop("source_refs")
    elif case == "empty":
        unit["source_refs"] = []
    elif case == "duplicate":
        unit["source_refs"] = [unit["source_refs"][0], unit["source_refs"][0]]
    else:
        unit["source_refs"] = [unit["source_refs"][0], " "]
    with pytest.raises(ValueError, match="source_refs"):
        builder.validate_publication_contract(
            central,
            load_json(SOURCE_REGISTRY_PATH),
            load_json(REVIEW_REGISTRY_PATH),
        )
