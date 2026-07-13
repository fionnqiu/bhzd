import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIDEO_UNITS_PATH = ROOT / "data" / "curriculum" / "video" / "teaching-units.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def units_by_key() -> dict[str, dict]:
    return {
        unit["capability_key"]: unit
        for unit in load_json(VIDEO_UNITS_PATH)["units"]
    }


def mappings_by_error(unit: dict) -> dict[str, dict]:
    return {
        mapping["error_type"]: mapping
        for mapping in unit["learning_path"]["error_mappings"]
    }


def schema_shape(value):
    if isinstance(value, dict):
        return {
            key: schema_shape(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        assert value, "reviewed exercise response arrays must not be empty"
        return [schema_shape(value[0])]
    return type(value).__name__


def test_vid_001_behavior_input_proves_direction_and_defines_every_event():
    behavior = units_by_key()["behavior_event"]
    exercise = behavior["exercise"]
    observations = [
        observation
        for observation in exercise["input"]["timeline_observations"]
        if observation["participant_track_id"] == "person-01"
    ]
    regions = [observation["observable_region"] for observation in observations]
    assert regions == ["outside", "outside", "threshold", "inside", "inside"]
    assert exercise["answer"]["events"][0]["event_type"] == "door_entry"

    definitions = behavior["rule_explanation"]["project_policy"][
        "event_definitions"
    ]
    allowed = set(exercise["response_space"]["allowed_event_types"])
    assert set(definitions) == allowed == {"door_entry", "door_exit", "idle"}
    for definition in definitions.values():
        assert definition["inclusion_criteria"]
        assert definition["exclusion_criteria"]
        assert definition["start_boundary"]
        assert definition["end_boundary"]
    assert definitions["door_entry"]["ordered_region_transition"] == [
        "outside",
        "threshold",
        "inside",
    ]
    assert definitions["door_exit"]["ordered_region_transition"] == [
        "inside",
        "threshold",
        "outside",
    ]
    positive_regions = [
        observation["observable_region"]
        for observation in behavior["positive_examples"][0]["input"][
            "timeline_observations"
        ]
    ]
    assert positive_regions == ["outside", "outside", "threshold", "inside"]


def test_vid_002_specialized_error_mappings_keep_primary_capabilities():
    units = units_by_key()
    behavior_mappings = mappings_by_error(units["behavior_event"])
    for error_type in (
        "event_start_boundary_mismatch",
        "event_end_boundary_mismatch",
    ):
        mapping = behavior_mappings[error_type]
        assert set(mapping["rule_refs"]) == {"KNG-VID-EVENT-START-END-001"}
        assert {
            "CAP-VID-ACTION-EVENT-001",
            "CAP-VID-EVENT-BOUNDARY-001",
        } <= set(mapping["capability_refs"])

    tracking = units["object_tracking"]
    assert "KNG-VID-OCCLUSION-REID-001" in tracking["rule_refs"]
    tracking_mappings = mappings_by_error(tracking)
    for error_type in (
        "track_identity_fragmented",
        "track_occlusion_gap_omitted",
    ):
        mapping = tracking_mappings[error_type]
        assert "KNG-VID-OCCLUSION-REID-001" in mapping["rule_refs"]
        assert {
            "CAP-VID-OBJECT-TRACK-001",
            "CAP-VID-OCCLUSION-REID-001",
        } <= set(mapping["capability_refs"])


def test_vid_003_tracking_requires_observable_occlusion_and_reid_evidence():
    tracking = units_by_key()["object_tracking"]
    exercise_input = tracking["exercise"]["input"]
    decision_policy = exercise_input["occlusion_decision_policy"]
    assert decision_policy["missing_frames_alone_sufficient"] is False
    assert set(decision_policy["required_evidence_fields"]) == {
        "visibility_state",
        "occluder_ref",
        "observable_evidence",
    }

    assert exercise_input["missing_identity_key"] == "vehicle-a"
    missing_frames = set(exercise_input["missing_frame_indices"])
    evidence = exercise_input["visibility_evidence"]
    assert {item["frame_index"] for item in evidence} == missing_frames
    for item in evidence:
        assert item["identity_key"] == exercise_input["missing_identity_key"]
        assert item["visibility_state"] == "occluded"
        assert item["occluder_ref"]
        assert item["observable_evidence"]

    reid = exercise_input["reidentification_evidence"]
    assert reid["appearance_signature_match"] is True
    assert reid["motion_direction_consistent"] is True
    assert reid["spatial_continuity"] is True


def test_vid_003r_positive_example_has_sufficient_declared_reid_evidence():
    tracking = units_by_key()["object_tracking"]
    example = tracking["positive_examples"][0]
    example_input = example["input"]
    requirements = tracking["rule_explanation"]["project_policy"][
        "reidentification_requirements"
    ]
    assert requirements == [
        "appearance_signature_match",
        "motion_direction_consistent",
        "spatial_continuity",
    ]

    reid = example_input["reidentification_evidence"]
    assert all(reid[requirement] is True for requirement in requirements)
    observations = {
        item["observation_id"]: item for item in example_input["observations"]
    }
    before = observations[reid["pre_occlusion_observation_id"]]
    after = observations[reid["post_occlusion_observation_id"]]
    assert before["motion_direction"] == after["motion_direction"] == "right"
    assert reid["identity_key"] == before["identity_key"] == after["identity_key"]

    assert example["explanation_evidence_refs"] == [
        "input.visibility_evidence",
        "input.reidentification_evidence.appearance_signature_match",
        "input.reidentification_evidence.motion_direction_consistent",
        "input.reidentification_evidence.spatial_continuity",
    ]
    assert example["explanation"] == (
        "两个缺失帧均有 visibility_evidence；reidentification_evidence 明确给出 "
        "appearance_signature_match=true、motion_direction_consistent=true、"
        "spatial_continuity=true，因此按项目策略复用 trk_01。"
    )


def test_vid_004_tracking_assesses_first_appearance_with_id_swap_diagnostic():
    tracking = units_by_key()["object_tracking"]
    exercise = tracking["exercise"]
    observations = exercise["input"]["observations"]
    identities = sorted({item["identity_key"] for item in observations})
    assert len(identities) >= 2

    first_frame = {
        identity: min(
            item["frame_index"]
            for item in observations
            if item["identity_key"] == identity
        )
        for identity in identities
    }
    assert len(set(first_frame.values())) == len(first_frame)
    expected_order = [
        identity for identity, _ in sorted(first_frame.items(), key=lambda item: item[1])
    ]
    observation_identity = {
        item["observation_id"]: item["identity_key"] for item in observations
    }
    answer_ids = {
        observation_identity[track["observation_ids"][0]]: track["track_id"]
        for track in exercise["answer"]["tracks"]
    }
    assert [answer_ids[identity] for identity in expected_order] == [
        f"trk_{index:02d}" for index in range(1, len(expected_order) + 1)
    ]

    swap = next(
        rule
        for rule in exercise["evaluation"]["diagnostic_rules"]
        if rule["error_type"] == "track_first_appearance_id_swap"
    )
    evaluator = load_module(EVALUATOR_PATH, "video_review_tracking_evaluator")
    result = evaluator.evaluate_unit(
        tracking,
        swap["submission"],
        exercise_id=exercise["exercise_id"],
    )
    assert result["passed"] is False
    assert result["error_type"] == "track_first_appearance_id_swap"


def test_vid_005_negative_examples_are_single_fault_evaluator_regressions():
    evaluator = load_module(EVALUATOR_PATH, "video_review_negative_evaluator")
    for unit in units_by_key().values():
        exercise = unit["exercise"]
        diagnostic_submissions = {
            json.dumps(rule["submission"], ensure_ascii=False, sort_keys=True): rule
            for rule in exercise["evaluation"]["diagnostic_rules"]
        }
        for example in unit["negative_examples"]:
            assert example["fault_model"]["type"] == "single_fault"
            assert example["input"]["exercise_id"] == exercise["exercise_id"]
            submission = example["input"]["submission"]
            assert schema_shape(submission) == schema_shape(exercise["answer"])
            key = json.dumps(submission, ensure_ascii=False, sort_keys=True)
            assert key in diagnostic_submissions
            expected_error = diagnostic_submissions[key]["error_type"]
            assert example["expected"] == {
                "passed": False,
                "error_type": expected_error,
            }
            result = evaluator.evaluate_unit(
                unit,
                submission,
                exercise_id=exercise["exercise_id"],
            )
            assert result["passed"] is False
            assert result["manual_review_required"] is False
            assert result["error_type"] == expected_error


def test_vid_006_frame_prerequisite_follows_pre_and_image_box_is_rel_only():
    frame = units_by_key()["frame_annotation"]
    assert frame["prerequisites"] == ["CAP-VID-FRAME-SAMPLE-001"]
    assert frame["related_primitives"] == [
        {
            "capability_ref": "CAP-IMG-BOX-ANNOTATE-001",
            "relation_type": "REL",
            "purpose": "复用矩形几何原语，不构成视频课程前置能力",
        }
    ]

    catalog = load_json(GRAPH_CATALOG_PATH)
    pre_pairs = {
        (edge["source"], edge["target"]) for edge in catalog["relations"]["PRE"]
    }
    rel_pairs = {
        (edge["source"], edge["target"]) for edge in catalog["relations"]["REL"]
    }
    assert (
        "CAP-VID-FRAME-SAMPLE-001",
        "CAP-VID-FRAME-ANNOTATE-001",
    ) in pre_pairs
    assert (
        "CAP-IMG-BOX-ANNOTATE-001",
        "CAP-VID-FRAME-ANNOTATE-001",
    ) in rel_pairs
    assert (
        "CAP-IMG-BOX-ANNOTATE-001",
        "CAP-VID-FRAME-ANNOTATE-001",
    ) not in pre_pairs


def test_review_fix_versions_and_visibility_gate_are_explicit():
    expected_data_versions = {
        "behavior_event": "1.1.0",
        "frame_annotation": "1.1.0",
        "object_tracking": "1.1.1",
    }
    for capability_key, unit in units_by_key().items():
        exercise = unit["exercise"]
        assert exercise["data_version"] == expected_data_versions[capability_key]
        assert exercise["evaluation"]["version"] == "1.1.0"
        assert unit["review_status"] == "draft"
        assert unit["student_visible"] is False
        assert unit["review_records"] == []
