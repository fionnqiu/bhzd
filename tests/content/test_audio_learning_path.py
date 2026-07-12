import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
AUDIO_SOURCE_FILES = (
    ROOT / "data" / "curriculum" / "audio" / "01-foundations.json",
    ROOT / "data" / "curriculum" / "audio" / "02-advanced.json",
)
CENTRAL_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
LEGACY_UNITS_PATH = ROOT / "data" / "curriculum" / "legacy" / "teaching-units.json"
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
GRAPH_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
BUILD_CURRICULUM_PATH = ROOT / "scripts" / "build_curriculum.py"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_exercise.py"

AUDIO_ASSET_PATH = (
    ROOT / "data" / "assets" / "audio" / "task4-segmentation-alignment.wav"
)
AUDIO_AUTH_PATH = (
    ROOT
    / "data"
    / "assets"
    / "audio"
    / "task4-segmentation-alignment.authorization.json"
)
EVIDENCE_ROOT = ROOT / "evidence" / "audio-learning-chain"
EVIDENCE_FILES = {
    "html": EVIDENCE_ROOT / "index.html",
    "css": EVIDENCE_ROOT / "styles.css",
    "javascript": EVIDENCE_ROOT / "app.js",
    "screenshot": EVIDENCE_ROOT / "learning-loop-desktop.png",
    "webm": EVIDENCE_ROOT / "learning-loop.webm",
    "mp4": EVIDENCE_ROOT / "learning-loop.mp4",
    "metadata": EVIDENCE_ROOT / "recording-metadata.json",
    "webm_probe": EVIDENCE_ROOT / "ffprobe-webm.json",
    "mp4_probe": EVIDENCE_ROOT / "ffprobe-mp4.json",
}

EXPECTED_CAPABILITIES = {
    "transcription_punctuation": {
        "unit_id": "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001",
        "capability_ref": "CAP-AUD-TRANSCRIBE-PUNCT-001",
        "prerequisite_ref": "CAP-AUD-CONFIG-VALIDATE-001",
    },
    "speaker_turns": {
        "unit_id": "TU-AUDIO-SPEAKER-TURNS-001",
        "capability_ref": "CAP-AUD-SPEAKER-001",
        "prerequisite_ref": "CAP-AUD-CONFIG-VALIDATE-001",
    },
    "language_dialect": {
        "unit_id": "TU-AUDIO-LANGUAGE-DIALECT-001",
        "capability_ref": "CAP-AUD-LANGUAGE-DIALECT-001",
        "prerequisite_ref": "CAP-AUD-TRANSCRIBE-PUNCT-001",
    },
    "emotion_paralinguistics": {
        "unit_id": "TU-AUDIO-EMOTION-PARALINGUISTICS-001",
        "capability_ref": "CAP-AUD-EMOTION-PARALING-001",
        "prerequisite_ref": "CAP-AUD-TRANSCRIBE-PUNCT-001",
    },
    "wake_command_words": {
        "unit_id": "TU-AUDIO-WAKE-COMMAND-WORDS-001",
        "capability_ref": "CAP-AUD-WAKE-COMMAND-001",
        "prerequisite_ref": "CAP-AUD-TRANSCRIBE-PUNCT-001",
    },
    "segmentation_alignment": {
        "unit_id": "TU-AUDIO-SEGMENTATION-ALIGNMENT-001",
        "capability_ref": "CAP-AUD-SEGMENT-ALIGN-001",
        "prerequisite_ref": "CAP-AUD-TRANSCRIBE-PUNCT-001",
    },
}

REQUIRED_EXTERNAL_SOURCES = {
    "SRC-NIST-SCTK-FORMATS-001",
    "SRC-IETF-RFC5646-001",
    "SRC-IANA-LANGUAGE-SUBTAG-001",
    "SRC-W3C-EMOTIONML-001",
    "SRC-SPEECH-COMMANDS-PAPER-001",
    "SRC-KALDI-DATA-PREP-001",
    "SRC-PRAAT-TEXTGRID-001",
}
POLICY_SOURCE_ID = "SRC-POLICY-AUDIO-TASK4-001"
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
def audio_documents() -> list[dict]:
    missing = [str(path) for path in AUDIO_SOURCE_FILES if not path.exists()]
    if missing:
        pytest.skip(f"Task 4 audio source files are not implemented yet: {missing}")
    return [load_json(path) for path in AUDIO_SOURCE_FILES]


@pytest.fixture(scope="module")
def audio_units(audio_documents) -> list[dict]:
    return [unit for document in audio_documents for unit in document["units"]]


@pytest.fixture(scope="module")
def units_by_key(audio_units) -> dict[str, dict]:
    return {unit["capability_key"]: unit for unit in audio_units}


def exercises_for(unit: dict) -> list[dict]:
    return [unit["exercise"], *unit["practice_variants"]]


def reachable_errors(exercise: dict) -> set[str]:
    evaluation = exercise["evaluation"]
    reached = {
        rule["error_type"] for rule in evaluation.get("diagnostic_rules", [])
    }
    reached.update(
        candidate["error_type"]
        for candidate in evaluation.get("allowed_answers", [])
        if candidate.get("error_type") is not None
    )
    incorrect = evaluation.get("incorrect_feedback")
    if isinstance(incorrect, dict) and incorrect.get("error_type"):
        reached.add(incorrect["error_type"])
    elif evaluation.get("default_error_type"):
        reached.add(evaluation["default_error_type"])
    return reached


def test_audio_candidate_source_files_exist():
    missing = [str(path) for path in AUDIO_SOURCE_FILES if not path.exists()]
    assert not missing, f"Task 4 audio source files are missing: {missing}"


def test_exactly_six_candidate_units_cover_the_required_capability_keys(
    audio_documents, audio_units, units_by_key
):
    for document in audio_documents:
        assert document["schema_version"] == "1.1.0"
        assert document["data_type"] == "audio"
        assert document["units"]
        assert [unit["id"] for unit in document["units"]] == sorted(
            unit["id"] for unit in document["units"]
        )

    assert len(audio_units) == 6
    assert set(units_by_key) == set(EXPECTED_CAPABILITIES)
    assert {unit["id"] for unit in audio_units} == {
        item["unit_id"] for item in EXPECTED_CAPABILITIES.values()
    }
    assert len({unit["id"] for unit in audio_units}) == 6


def test_units_define_goals_examples_policy_overlay_and_two_exercise_types(
    units_by_key,
):
    exercise_ids = []
    for capability_key, expected in EXPECTED_CAPABILITIES.items():
        unit = units_by_key[capability_key]
        assert unit["id"] == expected["unit_id"]
        assert unit["data_type"] == "audio"
        assert unit["goals"]
        assert unit["learning_objectives"]
        assert expected["prerequisite_ref"] in unit["prerequisites"]
        assert unit["rule_refs"]
        assert unit["source_refs"]
        assert unit["positive_examples"]
        assert unit["negative_examples"]
        assert unit["common_errors"]
        assert unit["remediation"]

        explanation = unit["rule_explanation"]
        assert set(explanation) >= {"external_format_facts", "project_policy"}
        assert explanation["external_format_facts"]
        for fact in explanation["external_format_facts"]:
            assert fact["statement"]
            assert fact["source_refs"]
            assert set(fact["source_refs"]) <= set(unit["source_refs"])
        policy = explanation["project_policy"]
        assert policy["source_ref"] == POLICY_SOURCE_ID
        assert policy["statement"]
        assert policy["version"] == "1.0.0"

        exercises = exercises_for(unit)
        assert len(exercises) >= 2
        assert len({exercise["exercise_type"] for exercise in exercises}) >= 2
        for exercise in exercises:
            exercise_ids.append(exercise["exercise_id"])
            assert exercise["exercise_id"]
            assert exercise["exercise_type"]
            assert exercise["answer"]
            assert exercise["error_types"]
            assert expected["capability_ref"] in exercise["capability_refs"]
            assert exercise["evaluation"]["diagnostic_rules"]
            assert exercise["evaluation"]["diagnostic_precedence"]
            assert exercise["evaluation"]["incorrect_feedback"]["feedback"]
            assert exercise["evaluation"]["incorrect_feedback"]["remediation"]
            assert set(exercise["error_types"]) <= reachable_errors(exercise)

        assert unit["review_status"] == "draft"
        assert unit["student_visible"] is False
        assert unit["review_records"] == []

    assert len(exercise_ids) == len(set(exercise_ids))


def test_every_error_maps_to_a_rule_capability_and_existing_audio_resource(
    units_by_key,
):
    graph = load_json(GRAPH_PATH)
    nodes = {node["id"]: node for node in graph["nodes"]}
    audio_resources = {
        node_id
        for node_id, node in nodes.items()
        if node["type"] == "RES" and "audio" in node["data_types"]
    }

    for capability_key, expected in EXPECTED_CAPABILITIES.items():
        unit = units_by_key[capability_key]
        errors = {
            error_type
            for exercise in exercises_for(unit)
            for error_type in exercise["error_types"]
        }
        mappings = unit["learning_path"]["error_mappings"]
        assert {mapping["error_type"] for mapping in mappings} == errors
        assert len(mappings) == len(errors)
        for mapping in mappings:
            assert mapping["rule_refs"]
            assert set(mapping["rule_refs"]) <= set(unit["rule_refs"])
            assert mapping["capability_refs"]
            assert expected["capability_ref"] in mapping["capability_refs"]
            assert set(mapping["capability_refs"]) <= nodes.keys()
            assert mapping["remediation_resource_refs"]
            assert set(mapping["remediation_resource_refs"]) <= audio_resources


def test_capability_prerequisites_match_real_graph_pre_edges(units_by_key):
    catalog = load_json(GRAPH_CATALOG_PATH)
    pre_edges = {
        (edge["source"], edge["target"]) for edge in catalog["relations"]["PRE"]
    }
    for capability_key, expected in EXPECTED_CAPABILITIES.items():
        unit = units_by_key[capability_key]
        assert (
            expected["prerequisite_ref"],
            expected["capability_ref"],
        ) in pre_edges
        assert expected["prerequisite_ref"] in unit["prerequisites"]


def test_evaluator_selects_variants_by_exercise_id_and_stays_deterministic(
    audio_units,
):
    evaluator = load_module(EVALUATOR_PATH, "task4_audio_evaluator")
    for unit in audio_units:
        for exercise in exercises_for(unit):
            exercise_id = exercise["exercise_id"]
            first = evaluator.evaluate_unit(
                unit, exercise["answer"], exercise_id=exercise_id
            )
            second = evaluator.evaluate_unit(
                unit, exercise["answer"], exercise_id=exercise_id
            )
            assert set(first) == RESULT_FIELDS
            assert first == second
            assert evaluator.serialize_result(first) == evaluator.serialize_result(second)
            assert first["passed"] is True
            assert first["score"] == 1.0
            assert first["capability_refs"] == exercise["capability_refs"]
            assert first["data_version"] == exercise["data_version"]
            assert first["evaluation_version"] == exercise["evaluation"]["version"]

            wrong = exercise["evaluation"]["diagnostic_rules"][0]
            result = evaluator.evaluate_unit(
                unit, wrong["submission"], exercise_id=exercise_id
            )
            assert result["passed"] is False
            assert result["error_type"] == wrong["error_type"]
            assert result["rule_refs"] == unit["rule_refs"]
            assert result["capability_refs"] == exercise["capability_refs"]
            assert result["feedback"] == wrong["feedback"]
            assert result["remediation"] == wrong["remediation"]

        with pytest.raises(ValueError, match="exercise_id"):
            evaluator.evaluate_unit(unit, {}, exercise_id="EXERCISE-AUDIO-UNKNOWN")


def test_evaluator_cli_accepts_exercise_id(units_by_key):
    unit = units_by_key["segmentation_alignment"]
    variant = unit["practice_variants"][0]
    result = run_python(
        EVALUATOR_PATH,
        "--unit-file",
        AUDIO_SOURCE_FILES[1],
        "--unit-id",
        unit["id"],
        "--exercise-id",
        variant["exercise_id"],
        "--submission",
        json.dumps(variant["answer"], ensure_ascii=False),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["passed"] is True


def test_audio_sources_separate_external_facts_from_local_policy(audio_units):
    registry = load_json(SOURCE_REGISTRY_PATH)
    sources = {source["source_id"]: source for source in registry["sources"]}
    referenced = {
        source_ref for unit in audio_units for source_ref in unit["source_refs"]
    }
    assert REQUIRED_EXTERNAL_SOURCES <= referenced
    assert POLICY_SOURCE_ID in referenced

    for source_id in REQUIRED_EXTERNAL_SOURCES:
        source = sources[source_id]
        assert source["source_kind"] == "external_reference"
        assert source["status"] == "verified"
        assert source["license_or_authorization"]["student_use_allowed"] is True
        assert source["usage_rights"]["citation_allowed"] is True

    policy = sources[POLICY_SOURCE_ID]
    assert policy["source_kind"] == "project_policy"
    assert policy["authority_scope"] == "local_project_policy_only"
    assert policy["status"] == "verified"
    assert policy["publication_scope"] == "development_only"
    assert policy["human_release_allowed"] is False
    assert policy["license_or_authorization"]["publishable"] is True
    assert policy["usage_rights"]["asset_redistribution_allowed"] is False


def test_audio_asset_is_authorized_deterministic_pcm16_mono_16khz():
    assert AUDIO_ASSET_PATH.is_file()
    assert AUDIO_AUTH_PATH.is_file()
    authorization = load_json(AUDIO_AUTH_PATH)
    payload = AUDIO_ASSET_PATH.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert authorization["asset_id"] == "ASSET-AUDIO-TASK4-TONE-SILENCE-TONE-001"
    assert authorization["file"] == AUDIO_ASSET_PATH.name
    assert authorization["sha256"] == digest
    assert authorization["authorization"]["type"] == "self-authored"
    assert authorization["authorization"]["student_use_allowed"] is True
    assert (
        authorization["authorization"]["development_publication_allowed"] is True
    )
    assert authorization["authorization"]["contains_personal_data"] is False
    assert authorization["generation"]["deterministic"] is True
    assert authorization["generation"]["script"] == (
        "scripts/generate_task4_audio_evidence.py"
    )

    with wave.open(str(AUDIO_ASSET_PATH), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16000
        assert audio.getcomptype() == "NONE"
        assert audio.getnframes() > 0
        duration = audio.getnframes() / audio.getframerate()
    metadata = authorization["technical_metadata"]
    assert metadata["sample_rate_hz"] == 16000
    assert metadata["channels"] == 1
    assert metadata["sample_width_bytes"] == 2
    assert metadata["frame_count"] == round(duration * 16000)
    assert metadata["duration_seconds"] == pytest.approx(duration, abs=1e-6)


def test_browser_evidence_contract_uses_real_task4_data_and_media():
    missing = [str(path) for path in EVIDENCE_FILES.values() if not path.is_file()]
    assert not missing, f"Task 4 evidence artifacts are missing: {missing}"
    assert all(path.stat().st_size > 0 for path in EVIDENCE_FILES.values())

    html = EVIDENCE_FILES["html"].read_text(encoding="utf-8")
    css = EVIDENCE_FILES["css"].read_text(encoding="utf-8")
    javascript = EVIDENCE_FILES["javascript"].read_text(encoding="utf-8")
    combined = (html + css).lower()
    assert "<main" in html.lower()
    assert "<audio" in html.lower()
    assert "controls" in html.lower()
    assert "aria-label" in html.lower()
    assert "styles.css" in html
    assert "app.js" in html
    assert "linear-gradient" not in combined
    assert "radial-gradient" not in combined
    assert "gradient" not in combined
    assert "fetch(" in javascript
    assert "02-advanced.json" in javascript
    assert "task4-segmentation-alignment.wav" in javascript
    for field in (
        "rule_explanation",
        "diagnostic_rules",
        "error_type",
        "capability_refs",
        "remediation",
    ):
        assert field in javascript

    png = EVIDENCE_FILES["screenshot"].read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert width >= 1200
    assert height >= 700


@pytest.mark.parametrize(
    ("artifact_key", "probe_key", "format_name"),
    (("webm", "webm_probe", "webm"), ("mp4", "mp4_probe", "mp4")),
)
def test_recordings_have_real_video_streams_and_ffprobe_evidence(
    artifact_key, probe_key, format_name
):
    assert EVIDENCE_FILES[probe_key].is_file()
    assert EVIDENCE_FILES[artifact_key].is_file()
    probe = load_json(EVIDENCE_FILES[probe_key])
    assert any(stream.get("codec_type") == "video" for stream in probe["streams"])
    assert float(probe["format"]["duration"]) > 0
    assert format_name in probe["format"]["format_name"]
    assert int(probe["format"]["size"]) == EVIDENCE_FILES[artifact_key].stat().st_size


def test_recording_metadata_proves_wrong_feedback_remediation_and_correct_retry():
    assert EVIDENCE_FILES["metadata"].is_file()
    metadata = load_json(EVIDENCE_FILES["metadata"])
    assert metadata["unit_id"] == "TU-AUDIO-SEGMENTATION-ALIGNMENT-001"
    assert metadata["exercise_id"]
    assert metadata["source_unit_file"] == (
        "data/curriculum/audio/02-advanced.json"
    )
    assert metadata["source_audio_file"] == (
        "data/assets/audio/task4-segmentation-alignment.wav"
    )
    assert metadata["automated_browser"] == "playwright-cli"
    assert metadata["wrong_attempt"]["passed"] is False
    assert metadata["wrong_attempt"]["error_type"]
    assert metadata["wrong_attempt"]["rule_refs"]
    assert metadata["wrong_attempt"]["capability_refs"]
    assert metadata["wrong_attempt"]["remediation"]
    assert metadata["correct_retry"]["passed"] is True
    assert metadata["correct_retry"]["score"] == 1.0
    assert metadata["viewport"]["width"] >= 1200
    assert metadata["viewport"]["height"] >= 700


def test_curriculum_build_overrides_legacy_audio_but_keeps_legacy_video():
    builder = load_module(BUILD_CURRICULUM_PATH, "task4_curriculum_builder")
    first = builder.build_curriculum(ROOT / "data" / "curriculum", LEGACY_UNITS_PATH)
    second = builder.build_curriculum(ROOT / "data" / "curriculum", LEGACY_UNITS_PATH)
    assert first == second
    assert len(first["units"]) == 17
    assert first["student_visible_unit_ids"] == sorted(
        first["student_visible_unit_ids"]
    )
    by_domain = {
        domain: [unit for unit in first["units"] if unit["data_type"] == domain]
        for domain in ("text", "image", "audio", "video")
    }
    assert len(by_domain["text"]) == 5
    assert len(by_domain["image"]) == 5
    assert len(by_domain["audio"]) == 6
    assert len(by_domain["video"]) == 1
    assert {unit["id"] for unit in by_domain["audio"]} == {
        item["unit_id"] for item in EXPECTED_CAPABILITIES.values()
    }
    assert "TU-AUDIO-DATA-BINDING-001" not in {
        unit["id"] for unit in first["units"]
    }
    assert by_domain["video"][0]["id"] == "TU-VIDEO-TRACK-ID-001"


def test_central_index_and_graph_keep_candidates_hidden_and_exact_counts():
    central = load_json(CENTRAL_UNITS_PATH)
    graph = load_json(GRAPH_PATH)
    audio_units = [unit for unit in central["units"] if unit["data_type"] == "audio"]
    assert len(central["units"]) == 17
    assert len(audio_units) == 6
    assert all(unit["review_status"] == "draft" for unit in audio_units)
    assert all(unit["student_visible"] is False for unit in audio_units)
    assert all(unit["review_records"] == [] for unit in audio_units)
    assert not ({unit["id"] for unit in audio_units} & set(central["student_visible_unit_ids"]))

    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240
    task_links = [
        link
        for node in graph["nodes"]
        if node["type"] == "TSK"
        for link in node["teaching_unit_links"]
    ]
    audio_ids = {unit["id"] for unit in audio_units}
    linked_audio = {link["unit_id"] for link in task_links if link["unit_id"] in audio_ids}
    assert linked_audio == audio_ids
    for link in task_links:
        if link["unit_id"] not in audio_ids:
            continue
        assert link["review_status"] == "draft"
        assert link["student_visible"] is False
        assert link["in_student_visible_index"] is False
        assert link["consumable"] is False
