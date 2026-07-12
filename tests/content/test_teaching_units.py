import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
TEACHING_UNITS_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"
CONTENT_SPEC_PATH = ROOT / "docs" / "教学内容与图谱数据规范.md"
DATA_TYPES = {"text", "image", "audio", "video"}
SOURCE_REQUIRED_FIELDS = {
    "source_id",
    "name",
    "author_or_organization",
    "version_or_publication_date",
    "original_url_or_local_archive",
    "access_date",
    "license_or_authorization",
    "citation_locations",
    "verified_by",
    "verified_at",
    "status",
}
UNIT_REQUIRED_FIELDS = {
    "id",
    "data_type",
    "title",
    "learning_objectives",
    "prerequisites",
    "rule_refs",
    "source_refs",
    "positive_examples",
    "negative_examples",
    "exercise",
    "common_errors",
    "remediation",
    "review_status",
    "student_visible",
}


def load_json(path: Path):
    if not path.exists():
        pytest.skip(f"required content data file is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def source_registry():
    return load_json(SOURCE_REGISTRY_PATH)


@pytest.fixture(scope="module")
def teaching_units():
    return load_json(TEACHING_UNITS_PATH)


def test_required_content_data_files_exist():
    missing = [
        str(path)
        for path in (SOURCE_REGISTRY_PATH, TEACHING_UNITS_PATH)
        if not path.exists()
    ]
    assert not missing, f"required content data files are missing: {missing}"


def test_source_registry_covers_each_data_type_with_verified_publishable_sources(
    source_registry,
):
    assert set(source_registry) == {"schema_version", "sources"}
    sources = source_registry["sources"]
    assert {source["data_type"] for source in sources} == DATA_TYPES
    source_ids = [source["source_id"] for source in sources]
    assert len(source_ids) == len(set(source_ids))

    for source in sources:
        assert SOURCE_REQUIRED_FIELDS <= source.keys()
        assert source["source_id"].startswith("SRC-")
        assert source["data_type"] in DATA_TYPES
        assert source["status"] in {"unverified", "verified", "restricted"}
        assert source["citation_locations"]

        authorization = source["license_or_authorization"]
        assert authorization["license_id"]
        assert authorization["license_url"].startswith("https://")
        assert isinstance(authorization["student_use_allowed"], bool)
        assert isinstance(authorization["publishable"], bool)

    eligible_data_types = {
        source["data_type"]
        for source in sources
        if source["status"] == "verified"
        and source["license_or_authorization"]["student_use_allowed"]
        and source["license_or_authorization"]["publishable"]
    }
    assert eligible_data_types == DATA_TYPES


def test_teaching_units_cover_each_data_type_and_required_fields(teaching_units):
    assert set(teaching_units) == {
        "schema_version",
        "student_visible_unit_ids",
        "units",
    }
    units = teaching_units["units"]
    assert {unit["data_type"] for unit in units} >= DATA_TYPES
    unit_ids = [unit["id"] for unit in units]
    assert len(unit_ids) == len(set(unit_ids))

    for unit in units:
        assert UNIT_REQUIRED_FIELDS <= unit.keys()
        assert unit["id"].startswith("TU-")
        assert unit["data_type"] in DATA_TYPES
        assert unit["title"]
        assert unit["learning_objectives"]
        assert isinstance(unit["prerequisites"], list)
        assert unit["common_errors"]
        assert unit["remediation"]


def test_source_and_knowledge_references_are_separate_and_resolvable(
    source_registry, teaching_units
):
    sources_by_id = {
        source["source_id"]: source for source in source_registry["sources"]
    }

    for unit in teaching_units["units"]:
        assert unit["rule_refs"]
        assert all(ref.startswith("KNG-") for ref in unit["rule_refs"])
        assert not any(ref.startswith("SRC-") for ref in unit["rule_refs"])
        assert unit["source_refs"]
        assert all(ref.startswith("SRC-") for ref in unit["source_refs"])
        assert not any(ref.startswith("KNG-") for ref in unit["source_refs"])
        assert set(unit["source_refs"]) <= sources_by_id.keys()
        assert any(
            sources_by_id[source_ref]["data_type"] == unit["data_type"]
            for source_ref in unit["source_refs"]
        )

        if unit["student_visible"]:
            for source_ref in unit["source_refs"]:
                source = sources_by_id[source_ref]
                authorization = source["license_or_authorization"]
                assert source["status"] == "verified"
                assert authorization["publishable"] is True
                assert authorization["student_use_allowed"] is True


def test_units_have_traceable_positive_and_negative_examples(teaching_units):
    example_ids = []
    for unit in teaching_units["units"]:
        for field in ("positive_examples", "negative_examples"):
            examples = unit[field]
            assert examples
            for example in examples:
                example_ids.append(example["id"])
                assert {
                    "id",
                    "asset_ref",
                    "input",
                    "expected",
                    "explanation",
                    "source_ref",
                    "asset_authorization",
                } <= example.keys()
                assert example["source_ref"] in unit["source_refs"]
                assert example["asset_authorization"]["type"] == "self-authored"
                assert example["asset_authorization"]["student_use_allowed"] is True
                if "error" in example["expected"]:
                    assert example["expected"]["error"] in unit["exercise"]["error_types"]

    assert len(example_ids) == len(set(example_ids))


def test_exercises_define_a_deterministic_evaluation(teaching_units):
    exercise_asset_refs = []
    for unit in teaching_units["units"]:
        exercise = unit["exercise"]
        exercise_asset_refs.append(exercise["asset_ref"])
        assert {
            "asset_ref",
            "input",
            "student_action",
            "answer",
            "evaluation",
            "data_version",
            "pass_condition",
            "asset_authorization",
            "capability_refs",
            "error_types",
        } <= exercise.keys()
        assert exercise["answer"]
        assert exercise["evaluation"]["method"] in {
            "exact_match",
            "ordered_exact_match",
        }
        assert exercise["evaluation"]["version"]
        assert isinstance(exercise["data_version"], str)
        assert exercise["data_version"].strip()
        assert exercise["pass_condition"] == "score == 1.0"
        assert exercise["capability_refs"]
        assert all(ref.startswith("CAP-") for ref in exercise["capability_refs"])
        assert exercise["error_types"]
        if "error" in exercise["answer"]:
            assert exercise["answer"]["error"] in exercise["error_types"]
        assert exercise["asset_authorization"]["type"] == "self-authored"
        assert exercise["asset_authorization"]["student_use_allowed"] is True

    assert len(exercise_asset_refs) == len(set(exercise_asset_refs))


def test_only_published_units_can_be_student_visible(teaching_units):
    visible_ids = set(teaching_units["student_visible_unit_ids"])
    units = teaching_units["units"]
    assert visible_ids == {unit["id"] for unit in units if unit["student_visible"]}

    for unit in units:
        assert unit["review_status"] in {"draft", "reviewed", "published"}
        if unit["student_visible"]:
            assert unit["review_status"] == "published"



def test_teaching_unit_examples_use_tu_namespace():
    content_spec = CONTENT_SPEC_PATH.read_text(encoding="utf-8")
    assert "例如 `TU-" in content_spec
    assert "例如 `CAP-" not in content_spec
    assert not re.search(r'"id"\s*:\s*"CAP-', content_spec)

    match = re.search(r"统一结构示例：\s*```json\s*(.*?)\s*```", content_spec, re.DOTALL)
    assert match, "teaching unit JSON example is missing"
    example = json.loads(match.group(1))
    assert UNIT_REQUIRED_FIELDS <= example.keys()
    assert example["id"].startswith("TU-")
    assert all(ref.startswith("CAP-") for ref in example["prerequisites"])
    assert all(ref.startswith("KNG-") for ref in example["rule_refs"])
    assert all(ref.startswith("SRC-") for ref in example["source_refs"])
    assert all(
        ref.startswith("CAP-") for ref in example["exercise"]["capability_refs"]
    )
    assert example["exercise"]["data_version"]
    assert example["exercise"]["evaluation"]["version"]
