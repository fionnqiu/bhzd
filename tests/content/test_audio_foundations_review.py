from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOUNDATIONS_PATH = ROOT / "data" / "curriculum" / "audio" / "01-foundations.json"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"
GENERIC_ERROR = "unclassified_submission"
FINITE_RESPONSE_SPACE = {
    "type": "finite_closed_set",
    "recognized_submissions": ["standard_answer", "diagnostic_rules"],
    "unmatched_behavior": "manual_review",
}
BCP47_LABELS = ["cmn", "yue", "und"]
PROJECT_SENTINEL_LABELS = ["mixed"]


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_evaluator():
    spec = importlib.util.spec_from_file_location("foundations_review_evaluator", EVALUATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exercises_for(unit: dict) -> list[dict]:
    return [unit["exercise"], *unit["practice_variants"]]


def foundations_units() -> list[dict]:
    return load_json(FOUNDATIONS_PATH)["units"]


def test_unmatched_and_multi_error_submissions_require_manual_review():
    evaluator = load_evaluator()
    for unit in foundations_units():
        for exercise in exercises_for(unit):
            evaluation = exercise["evaluation"]
            for key, value in FINITE_RESPONSE_SPACE.items():
                assert evaluation["response_space"][key] == value
            assert evaluation["manual_review_on_unmatched"] is True
            assert GENERIC_ERROR in exercise["error_types"]
            assert evaluation["incorrect_feedback"]["error_type"] == GENERIC_ERROR
            assert evaluation["incorrect_feedback"]["remediation"]

            mappings = [
                mapping
                for mapping in unit["learning_path"]["error_mappings"]
                if mapping["error_type"] == GENERIC_ERROR
            ]
            assert len(mappings) == 1
            assert mappings[0]["rule_refs"]
            assert mappings[0]["capability_refs"]
            assert mappings[0]["remediation_resource_refs"]

            unmatched = {
                "unmatched_submission": exercise["exercise_id"],
                "violations": ["schema", "semantic"],
            }
            first = evaluator.evaluate_unit(
                unit, unmatched, exercise_id=exercise["exercise_id"]
            )
            second = evaluator.evaluate_unit(
                unit, unmatched, exercise_id=exercise["exercise_id"]
            )
            assert first == second
            assert first["passed"] is False
            assert first["error_type"] == GENERIC_ERROR
            assert first["manual_review_required"] is True
            assert first["feedback"] == evaluation["incorrect_feedback"]["feedback"]
            assert first["remediation"] == evaluation["incorrect_feedback"]["remediation"]

            for diagnostic in evaluation["diagnostic_rules"]:
                result = evaluator.evaluate_unit(
                    unit,
                    diagnostic["submission"],
                    exercise_id=exercise["exercise_id"],
                )
                assert result["error_type"] == diagnostic["error_type"]
                assert result["manual_review_required"] is diagnostic.get(
                    "manual_review_required", False
                )


def test_speaker_swap_is_a_first_appearance_error():
    evaluator = load_evaluator()
    unit = next(unit for unit in foundations_units() if unit["capability_key"] == "speaker_turns")
    exercise = unit["exercise"]
    swapped = copy.deepcopy(exercise["answer"])
    swap_ids = {"spk_01": "spk_02", "spk_02": "spk_01"}
    for turn in swapped["turns"]:
        turn["speaker_id"] = swap_ids[turn["speaker_id"]]

    matching = [
        rule
        for rule in exercise["evaluation"]["diagnostic_rules"]
        if rule["submission"] == swapped
    ]
    assert len(matching) == 1
    assert matching[0]["error_type"] == "speaker_first_appearance_mismatch"
    result = evaluator.evaluate_unit(
        unit, swapped, exercise_id=exercise["exercise_id"]
    )
    assert result["error_type"] == "speaker_first_appearance_mismatch"
    assert result["manual_review_required"] is False


def test_mandarin_uses_cmn_bcp47_language_subtag():
    unit = next(
        unit for unit in foundations_units() if unit["capability_key"] == "language_dialect"
    )
    serialized = json.dumps(unit, ensure_ascii=False)
    assert "zh-CN" not in serialized
    assert "cmn" in serialized
    assert any(
        "cmn" in fact["statement"]
        for fact in unit["rule_explanation"]["external_format_facts"]
    )
    for exercise in exercises_for(unit):
        configured_labels = exercise["input"].get("configured_labels")
        if configured_labels is not None:
            assert "cmn" in configured_labels
            assert "zh-CN" not in configured_labels


def _assert_language_label_partition(container: dict):
    assert container["configured_bcp47_labels"] == BCP47_LABELS
    assert container["configured_project_sentinel_labels"] == PROJECT_SENTINEL_LABELS
    assert not set(container["configured_bcp47_labels"]) & set(
        container["configured_project_sentinel_labels"]
    )


def test_mixed_is_explicitly_a_project_only_sentinel_not_a_bcp47_tag():
    unit = next(
        unit for unit in foundations_units() if unit["capability_key"] == "language_dialect"
    )
    explanation = unit["rule_explanation"]
    policy = explanation["project_policy"]
    _assert_language_label_partition(policy)
    assert "mixed" in policy["statement"]
    assert "项目专用哨兵标签" in policy["statement"]
    assert "不是 BCP 47" in policy["statement"]
    assert all(
        "mixed" not in fact["statement"]
        for fact in explanation["external_format_facts"]
    )

    records = [
        *unit["positive_examples"],
        *unit["negative_examples"],
        unit["exercise"],
        *unit["practice_variants"],
    ]
    for record in records:
        input_data = record["input"]
        if "configured_labels" not in input_data:
            continue
        _assert_language_label_partition(input_data)
        assert input_data["configured_labels"] == [
            *BCP47_LABELS,
            *PROJECT_SENTINEL_LABELS,
        ]

    for exercise in exercises_for(unit):
        _assert_language_label_partition(exercise["evaluation"]["response_space"])

    # Shared follow-up, intentionally not asserted in this foundations-only test:
    # align the language graph overlay and RES-AUD-DIALECT-LABEL-CARD-001 wording.


def test_stm_external_fact_uses_begin_end_fields():
    unit = next(unit for unit in foundations_units() if unit["capability_key"] == "speaker_turns")
    fact = next(
        fact
        for fact in unit["rule_explanation"]["external_format_facts"]
        if "NIST" in fact["statement"] or "SCTK" in fact["statement"]
    )
    statement = fact["statement"].lower()
    assert "begin/end" in statement
    assert "duration" not in statement
    assert "时长" not in fact["statement"]


def _assert_speaker_labels(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"speaker_id", "submitted_speaker_id"}:
                assert re.fullmatch(r"spk_\d{2}", child)
            _assert_speaker_labels(child)
    elif isinstance(value, list):
        for child in value:
            _assert_speaker_labels(child)


def test_speaker_labels_and_local_errors_use_speaker_turn_rule_only():
    unit = next(unit for unit in foundations_units() if unit["capability_key"] == "speaker_turns")
    _assert_speaker_labels(unit)
    serialized = json.dumps(unit, ensure_ascii=False)
    assert "agent_a" not in serialized
    assert "customer_b" not in serialized
    assert "agent_c" not in serialized

    for mapping in unit["learning_path"]["error_mappings"]:
        assert mapping["rule_refs"] == ["KNG-AUD-SPEAKER-TURN-001"]


def test_non_media_assets_are_declared_structured_fixtures():
    for unit in foundations_units():
        records = [
            *unit["positive_examples"],
            *unit["negative_examples"],
            unit["exercise"],
            *unit["practice_variants"],
        ]
        for record in records:
            assert record["asset_ref"]
            assert record["asset_authorization"]["representation"] == (
                "structured_fixture"
            )


def test_review_fix_bumps_versions_and_publishes_with_full_history():
    expected_history = [
        "REVIEW-TASK4-AUDIO-FOUNDATIONS-BF69CD1-001",
        "REVIEW-TASK4-AUDIO-FOUNDATIONS-492B020-002",
        "REVIEW-TASK4-AUDIO-FOUNDATIONS-E745A34-003",
    ]
    for unit in foundations_units():
        assert unit["review_records"] == expected_history
        assert unit["review_status"] == "published"
        assert unit["student_visible"] is True
        expected_data_version = (
            "1.1.1" if unit["capability_key"] == "language_dialect" else "1.1.0"
        )
        for exercise in exercises_for(unit):
            assert exercise["data_version"] == expected_data_version
            assert exercise["evaluation"]["version"] == "1.1.0"
