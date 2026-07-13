import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADVANCED_PATH = ROOT / "data" / "curriculum" / "audio" / "02-advanced.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
ASSET_AUTH_PATH = (
    ROOT
    / "data"
    / "assets"
    / "audio"
    / "task4-segmentation-alignment.authorization.json"
)
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"

GENERIC_ERROR = "unclassified_submission"
TIMESTAMP_RULE = "KNG-AUD-SEGMENT-TIMESTAMP-001"
ALIGNMENT_RESOURCE = "RES-AUD-ALIGNMENT-WORKSHEET-001"
EVENT_RESOURCE = "RES-AUD-EVENT-CATALOG-001"
CONFIG_RESOURCE = "RES-AUD-CONFIG-CHECKLIST-001"
TRANSCRIPT_RESOURCE = "RES-AUD-TRANSCRIPT-STYLE-SHEET-001"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def advanced_document() -> dict:
    return load_json(ADVANCED_PATH)


@pytest.fixture(scope="module")
def units_by_key(advanced_document) -> dict[str, dict]:
    return {
        unit["capability_key"]: unit for unit in advanced_document["units"]
    }


@pytest.fixture(scope="module")
def evaluator():
    return load_module(EVALUATOR_PATH, "audio_advanced_review_evaluator")


def exercises_for(unit: dict) -> list[dict]:
    return [unit["exercise"], *unit["practice_variants"]]


def timestamp_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"start_ms", "end_ms"}:
                yield key, item
            yield from timestamp_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from timestamp_values(item)


def graph_node(catalog: dict, node_type: str, node_id: str) -> dict:
    return next(node for node in catalog["nodes"][node_type] if node["id"] == node_id)


def mapping_for(unit: dict, error_type: str) -> dict:
    matches = [
        mapping
        for mapping in unit["learning_path"]["error_mappings"]
        if mapping["error_type"] == error_type
    ]
    assert len(matches) == 1
    return matches[0]


def diagnostic_for(unit: dict, error_type: str) -> dict:
    matches = [
        rule
        for exercise in exercises_for(unit)
        for rule in exercise["evaluation"]["diagnostic_rules"]
        if rule["error_type"] == error_type
    ]
    assert len(matches) == 1
    return matches[0]


def test_timebase_policy_converts_external_seconds_to_integer_ms_and_tracks_graph_follow_up(
    advanced_document, units_by_key
):
    unit = units_by_key["segmentation_alignment"]
    assert "timebase_policy" in unit, "review requires an explicit timebase conversion"
    policy = unit["timebase_policy"]
    assert policy["external_timebases"] == {
        "kaldi_segments": "seconds",
        "praat_textgrid_intervals": "seconds",
    }
    assert policy["project_timebase"] == "integer_ms"
    assert policy["conversion"] == (
        "milliseconds = round_half_up(decimal_seconds * 1000)"
    )
    assert policy["rounding"] == "decimal_half_up_to_nearest_integer_ms"
    assert policy["interval_convention"] == "[start_ms,end_ms)"
    assert policy["conversion_examples"] == [
        {"seconds": "0.400", "milliseconds": 400},
        {"seconds": "1.550", "milliseconds": 1550},
    ]

    values = list(timestamp_values(unit))
    assert values
    assert all(type(value) is int for _, value in values)

    catalog = load_json(GRAPH_CATALOG_PATH)
    graph_rule = graph_node(catalog, "KNG", TIMESTAMP_RULE)
    overlay = graph_rule["policy_overlays"][0]
    assert "秒为单位" in overlay["description"]
    assert "shared_follow_ups" in advanced_document
    follow_up = next(
        item
        for item in advanced_document["shared_follow_ups"]
        if item["target_ref"] == TIMESTAMP_RULE
    )
    assert follow_up["follow_up_type"] == "policy_overlay_alignment"
    assert follow_up["current_graph_version"] == overlay["version"]
    assert follow_up["required_state"]["project_timebase"] == "integer_ms"
    assert follow_up["required_state"]["interval_convention"] == "[start_ms,end_ms)"
    assert follow_up["status"] == "resolved"
    assert follow_up["resolution_ref"] == (
        "data/graph/graph-catalog.json#POLICY-AUD-SEGMENT-ALIGNMENT-001"
    )


def test_emotion_exercises_use_allowed_answers_and_manual_review_for_plausible_cues(
    units_by_key, evaluator
):
    unit = units_by_key["emotion_paralinguistics"]
    for exercise in exercises_for(unit):
        evaluation = exercise["evaluation"]
        assert evaluation["method"] == "allowed_answers"
        assert evaluation["pass_score"] == 1.0
        assert evaluation["local_cue_mapping"]["policy_basis"] == (
            "local_project_policy_only"
        )
        cue_rules = evaluation["local_cue_mapping"]["rules"]
        assert cue_rules
        assert all(rule["observed_cues"] for rule in cue_rules)
        assert all(rule["canonical_label"] for rule in cue_rules)
        assert all(rule["plausible_ambiguous_labels"] for rule in cue_rules)

        allowed = evaluation["allowed_answers"]
        canonical = [candidate for candidate in allowed if candidate["score"] == 1.0]
        ambiguous = [
            candidate for candidate in allowed if 0.0 < candidate["score"] < 1.0
        ]
        assert len(canonical) == 1
        assert canonical[0]["answer"] == exercise["answer"]
        assert canonical[0]["manual_review_required"] is False
        assert canonical[0]["error_type"] is None
        assert ambiguous
        assert all(candidate["manual_review_required"] is True for candidate in ambiguous)
        assert all(
            candidate["error_type"] == "emotion_cue_ambiguous"
            for candidate in ambiguous
        )

        canonical_result = evaluator.evaluate_unit(
            unit, exercise["answer"], exercise_id=exercise["exercise_id"]
        )
        assert canonical_result["score"] == 1.0
        assert canonical_result["passed"] is True
        assert canonical_result["manual_review_required"] is False

        ambiguous_result = evaluator.evaluate_unit(
            unit,
            ambiguous[0]["answer"],
            exercise_id=exercise["exercise_id"],
        )
        assert 0.0 < ambiguous_result["score"] < 1.0
        assert ambiguous_result["passed"] is False
        assert ambiguous_result["manual_review_required"] is True
        assert ambiguous_result["error_type"] == "emotion_cue_ambiguous"


def test_every_exercise_uses_generic_manual_review_for_unmatched_closed_responses(
    units_by_key, evaluator
):
    for unit in units_by_key.values():
        for exercise in exercises_for(unit):
            response_space = exercise.get("response_space")
            assert response_space, f"{exercise['exercise_id']} must declare its space"
            assert response_space["type"] == "finite_closed"
            assert response_space["unmatched_error_type"] == GENERIC_ERROR
            assert response_space["declared_by"]

            evaluation = exercise["evaluation"]
            assert evaluation["manual_review_on_unmatched"] is True
            assert evaluation["incorrect_feedback"]["error_type"] == GENERIC_ERROR
            assert GENERIC_ERROR in exercise["error_types"]
            result = evaluator.evaluate_unit(
                unit,
                {"submission_shape": "not_declared"},
                exercise_id=exercise["exercise_id"],
            )
            assert result["error_type"] == GENERIC_ERROR
            assert result["manual_review_required"] is True
            assert result["passed"] is False

        mapping = mapping_for(unit, GENERIC_ERROR)
        assert mapping["rule_refs"]
        assert mapping["capability_refs"]
        assert mapping["remediation_resource_refs"]


@pytest.mark.parametrize(
    ("capability_key", "error_types"),
    (
        ("emotion_paralinguistics", ("paralinguistic_boundary_mismatch",)),
        (
            "wake_command_words",
            ("wake_boundary_mismatch", "command_boundary_mismatch"),
        ),
    ),
)
def test_paralinguistic_and_command_boundary_errors_reference_timestamp_rule(
    units_by_key, capability_key, error_types
):
    unit = units_by_key[capability_key]
    assert TIMESTAMP_RULE in unit["rule_refs"]
    for error_type in error_types:
        diagnostic = diagnostic_for(unit, error_type)
        assert TIMESTAMP_RULE in diagnostic["rule_refs"]
        mapping = mapping_for(unit, error_type)
        assert TIMESTAMP_RULE in mapping["rule_refs"]
        assert ALIGNMENT_RESOURCE in mapping["remediation_resource_refs"]


def test_asset_bindings_distinguish_authorized_audio_from_structured_fixtures(
    units_by_key,
):
    authorization = load_json(ASSET_AUTH_PATH)
    authorized_asset_id = authorization["asset_id"]
    segmentation = units_by_key["segmentation_alignment"]
    primary = segmentation["exercise"]
    assert primary["asset_ref"] == authorized_asset_id
    assert primary["representation"] == "authorized_audio"
    assert primary["manifest_resolution"] == "resolved"
    assert primary["input"]["media_role"] == "deterministic_time_anchor_surrogate"
    assert primary["input"]["contains_recorded_speech"] is False

    records = []
    for unit in units_by_key.values():
        records.extend(unit["positive_examples"])
        records.extend(unit["negative_examples"])
        records.extend(exercises_for(unit))
    non_media = [record for record in records if record is not primary]
    assert non_media
    for record in non_media:
        assert record["representation"] == "structured_fixture"
        assert record["manifest_resolution"] == "resolved"


def test_remediation_uses_best_current_resources_and_exposes_graph_follow_ups(
    advanced_document, units_by_key
):
    emotion = units_by_key["emotion_paralinguistics"]
    for error_type in (
        "emotion_event_conflation",
        "emotion_label_mismatch",
        "paralinguistic_event_omitted",
        "emotion_cue_ambiguous",
    ):
        assert EVENT_RESOURCE in mapping_for(emotion, error_type)[
            "remediation_resource_refs"
        ]

    wake = units_by_key["wake_command_words"]
    for error_type in (
        "command_intent_mismatch",
        "target_command_class_mismatch",
        "unknown_class_mismatch",
        "silence_class_mismatch",
    ):
        resources = mapping_for(wake, error_type)["remediation_resource_refs"]
        assert CONFIG_RESOURCE in resources
        assert TRANSCRIPT_RESOURCE not in resources

    segmentation = units_by_key["segmentation_alignment"]
    assert TRANSCRIPT_RESOURCE in mapping_for(
        segmentation, "transcript_alignment_mismatch"
    )["remediation_resource_refs"]

    catalog = load_json(GRAPH_CATALOG_PATH)
    event_description = graph_node(catalog, "RES", EVENT_RESOURCE)["description"]
    config_description = graph_node(catalog, "RES", CONFIG_RESOURCE)["description"]
    assert "情感" not in event_description
    assert "命令意图" not in config_description

    follow_ups = {
        item["target_ref"]: item for item in advanced_document["shared_follow_ups"]
    }
    assert follow_ups[EVENT_RESOURCE]["follow_up_type"] == (
        "resource_description_and_support_alignment"
    )
    assert "情感" in follow_ups[EVENT_RESOURCE]["required_description_scope"]
    assert follow_ups[CONFIG_RESOURCE]["follow_up_type"] == (
        "resource_description_and_support_alignment"
    )
    assert "命令意图" in follow_ups[CONFIG_RESOURCE]["required_description_scope"]
    assert follow_ups[EVENT_RESOURCE]["status"] == "resolved"
    assert follow_ups[EVENT_RESOURCE]["resolution_ref"] == (
        "data/graph/graph-catalog.json#RES-AUD-EVENT-CATALOG-001"
    )
    assert follow_ups[CONFIG_RESOURCE]["status"] == "resolved"
    assert follow_ups[CONFIG_RESOURCE]["resolution_ref"] == (
        "data/graph/graph-catalog.json#RES-AUD-CONFIG-CHECKLIST-001->CAP-AUD-WAKE-COMMAND-001"
    )


def test_review_fix_versions_and_lifecycle_remain_candidate_only(units_by_key):
    for unit in units_by_key.values():
        assert unit["review_status"] == "draft"
        assert unit["student_visible"] is False
        assert unit["review_records"] == []
        for exercise in exercises_for(unit):
            assert exercise["data_version"] == "1.1.0"
            assert exercise["evaluation"]["version"] == "1.1.0"
