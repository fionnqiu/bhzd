import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIO_FILES = (
    ROOT / "data" / "curriculum" / "audio" / "01-foundations.json",
    ROOT / "data" / "curriculum" / "audio" / "02-advanced.json",
)
MANIFEST_PATH = (
    ROOT
    / "data"
    / "assets"
    / "audio"
    / "task4-structured-fixture-manifest.json"
)
AUTHORIZATION_PATH = (
    ROOT
    / "data"
    / "assets"
    / "audio"
    / "task4-segmentation-alignment.authorization.json"
)
SOURCE_REGISTRY_PATH = ROOT / "data" / "sources" / "source-registry.json"
REVIEW_REGISTRY_PATH = ROOT / "data" / "reviews" / "content-review-registry.json"
GRAPH_CATALOG_PATH = ROOT / "data" / "graph" / "graph-catalog.json"
GRAPH_PATH = ROOT / "data" / "graph" / "annotation-capability-graph.json"
CENTRAL_PATH = ROOT / "data" / "curriculum" / "teaching-units.json"

FOUNDATION_REVIEW = {
    "review_id": "REVIEW-TASK4-AUDIO-FOUNDATIONS-BF69CD1-001",
    "reviewer_id": "codex-task4-foundations-review",
    "reviewer_type": "ai_agent",
    "independent_of_implementation": True,
    "reviewed_at": "2026-07-12T23:35:40+08:00",
    "reviewed_commit": "bf69cd101e5bea97a5a63934d88a236c9097f03a",
    "unit_ids": {
        "TU-AUDIO-LANGUAGE-DIALECT-001",
        "TU-AUDIO-SPEAKER-TURNS-001",
        "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001",
    },
    "finding_summaries": [
        "Exact diagnostic samples did not enforce declared precedence, and unmatched or multi-error submissions received misleading specific errors.",
        "speaker_first_appearance_mismatch was absent.",
        "Mandarin was incorrectly mapped to the region tag zh-CN instead of cmn.",
        "The STM format fact incorrectly described begin time plus duration rather than begin time plus end time.",
        "The spk_01 policy and turn/boundary KNG/resource mappings were inconsistent.",
        "Twelve foundation ASSET references lacked a resolvable manifest and media/fixture distinction.",
    ],
}

ADVANCED_REVIEW = {
    "review_id": "REVIEW-TASK4-AUDIO-ADVANCED-7D6416B-001",
    "reviewer_id": "codex-task4-audio-advanced-review",
    "reviewer_type": "ai_agent",
    "independent_of_implementation": True,
    "reviewed_at": "2026-07-12",
    "reviewed_commit": "7d6416be724da40bf48d774495e726e62377d5f6",
    "unit_ids": {
        "TU-AUDIO-EMOTION-PARALINGUISTICS-001",
        "TU-AUDIO-SEGMENTATION-ALIGNMENT-001",
        "TU-AUDIO-WAKE-COMMAND-WORDS-001",
    },
    "finding_summaries": [
        "The curriculum integer-millisecond policy conflicted with the graph's seconds policy.",
        "Emotion answers lacked a deterministic local cue mapping and ambiguity handling.",
        "Unmatched submissions received misleading specific diagnoses.",
        "Boundary errors lacked a semantically matching timestamp KNG and graph trace.",
        "Asset and remediation-resource identities were not closed.",
    ],
}

EXPECTED_REMAINING_RISKS = [
    "A corrected candidate requires independent AI re-review before development publication.",
    "Formal competition and real-student release still require human domain-expert review.",
]

EXPECTED_RESOURCE_TERMS = {
    "RES-AUD-CONFIG-CHECKLIST-001": ("数据字段", "标签集合", "音频引用"),
    "RES-AUD-TRANSCRIPT-STYLE-SHEET-001": ("数字", "标点", "不可听"),
    "RES-AUD-SPEAKER-TIMELINE-001": ("spk_01", "首次出现", "轮次边界"),
    "RES-AUD-DIALECT-LABEL-CARD-001": ("BCP 47", "mixed", "und"),
    "RES-AUD-EVENT-CATALOG-001": ("emotion_label", "副语言", "区间"),
    "RES-AUD-ALIGNMENT-WORKSHEET-001": ("秒", "half-up", "[start_ms,end_ms)"),
}

EXPECTED_VIDEO_TASK_LINKS = {
    "TSK-VID-FRAME-LABEL-001": ["TU-VIDEO-FRAME-ANNOTATION-001"],
    "TSK-VID-OBJECT-TRACK-001": ["TU-VIDEO-OBJECT-TRACKING-001"],
    "TSK-VID-ACTION-EVENT-001": ["TU-VIDEO-BEHAVIOR-EVENT-001"],
}

EXPECTED_RESOLVED_FOLLOW_UPS = {
    "FOLLOWUP-AUDIO-TIMESTAMP-OVERLAY-001": (
        "data/graph/graph-catalog.json#POLICY-AUD-SEGMENT-ALIGNMENT-001"
    ),
    "FOLLOWUP-AUDIO-EVENT-RESOURCE-001": (
        "data/graph/graph-catalog.json#RES-AUD-EVENT-CATALOG-001"
    ),
    "FOLLOWUP-AUDIO-COMMAND-RESOURCE-001": (
        "data/graph/graph-catalog.json#RES-AUD-CONFIG-CHECKLIST-001->CAP-AUD-WAKE-COMMAND-001"
    ),
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audio_asset_items() -> list[tuple[dict, dict]]:
    result = []
    for path in AUDIO_FILES:
        document = load_json(path)
        for unit in document["units"]:
            items = [
                *unit["positive_examples"],
                *unit["negative_examples"],
                unit["exercise"],
                *unit["practice_variants"],
            ]
            result.extend((unit, item) for item in items)
    return result


def item_id(item: dict) -> str:
    return item.get("id", item.get("exercise_id"))


def test_stm_claim_and_spk_01_overlay_match_the_corrected_foundations_content():
    catalog = load_json(GRAPH_CATALOG_PATH)
    knowledge = {node["id"]: node for node in catalog["nodes"]["KNG"]}
    speaker = knowledge["KNG-AUD-SPEAKER-TURN-001"]

    assert speaker["description"] == (
        "STM 片段记录说话人、开始时间、结束时间和转写文本。"
    )
    overlay = speaker["policy_overlays"][0]
    assert overlay["overlay_id"] == "POLICY-AUD-SPEAKER-TURN-001"
    assert overlay["version"] == "1.1.0"
    assert "spk_01" in overlay["description"]
    assert "首次出现" in overlay["description"]
    assert "SPEAKER_01" not in overlay["description"]

    sources = {
        source["source_id"]: source
        for source in load_json(SOURCE_REGISTRY_PATH)["sources"]
    }
    assert sources["SRC-NIST-SCTK-FORMATS-001"]["license_or_authorization"][
        "review_note"
    ] == (
        "The audit received HTTP 206 and confirmed that STM records begin and "
        "end times, while CTM records begin time and duration; cite/link only."
    )


def test_segment_overlay_converts_external_seconds_with_half_up_integer_ms():
    catalog = load_json(GRAPH_CATALOG_PATH)
    knowledge = {node["id"]: node for node in catalog["nodes"]["KNG"]}
    timestamp = knowledge["KNG-AUD-SEGMENT-TIMESTAMP-001"]

    # The stable KNG remains an external format fact; project conversion semantics
    # stay additive in its local policy overlay.
    assert timestamp["claim_type"] == "audio_segment_timing"
    assert timestamp["claim_basis"] == "external_reference"
    assert timestamp["source_refs"] == [
        "SRC-KALDI-DATA-PREP-001",
        "SRC-PRAAT-TEXTGRID-001",
    ]
    overlay = timestamp["policy_overlays"][0]
    assert overlay["version"] == "1.1.0"
    assert overlay["external_timebase"] == "decimal_seconds"
    assert overlay["project_timebase"] == "integer_ms"
    assert overlay["conversion"] == (
        "milliseconds = round_half_up(decimal_seconds * 1000)"
    )
    assert overlay["rounding"] == "decimal_half_up_to_nearest_integer_ms"
    assert overlay["interval_convention"] == "[start_ms,end_ms)"
    assert "half-up" in overlay["description"]


def test_audio_resources_describe_the_concrete_remediation_operation():
    catalog = load_json(GRAPH_CATALOG_PATH)
    resources = {node["id"]: node for node in catalog["nodes"]["RES"]}
    generated_resources = {
        node["id"]: node
        for node in load_json(GRAPH_PATH)["nodes"]
        if node["type"] == "RES"
    }

    for resource_id, required_terms in EXPECTED_RESOURCE_TERMS.items():
        description = resources[resource_id]["description"]
        assert len(description) >= 30
        assert all(term in description for term in required_terms)
        assert generated_resources[resource_id]["description"] == description

    config_description = resources["RES-AUD-CONFIG-CHECKLIST-001"]["description"]
    assert all(
        term in config_description
        for term in ("command intent", "target", "unknown", "silence")
    )


def test_segment_rule_has_a_real_rel_edge_without_changing_graph_totals():
    catalog = load_json(GRAPH_CATALOG_PATH)
    relations = catalog["relations"]
    rel_pairs = {(edge["source"], edge["target"]) for edge in relations["REL"]}
    sup_pairs = {(edge["source"], edge["target"]) for edge in relations["SUP"]}

    # This direct rule-to-capability trace replaces the weak cross-domain analogy
    # from text entity boundaries to audio alignment.
    assert (
        "KNG-AUD-SEGMENT-TIMESTAMP-001",
        "CAP-AUD-SEGMENT-ALIGN-001",
    ) in rel_pairs
    assert (
        "CAP-TXT-ENTITY-BOUNDARY-001",
        "CAP-AUD-SEGMENT-ALIGN-001",
    ) not in rel_pairs
    # The command checklist uses a semantic SUP edge. Its edge budget comes from
    # deleting the weaker text-intent/audio-wake REL analogy.
    assert (
        "RES-AUD-CONFIG-CHECKLIST-001",
        "CAP-AUD-WAKE-COMMAND-001",
    ) in sup_pairs
    assert (
        "CAP-TXT-INTENT-001",
        "CAP-AUD-WAKE-COMMAND-001",
    ) not in rel_pairs
    assert len(relations["REL"]) == 19
    assert len(relations["SUP"]) == 77
    assert sum(len(edges) for edges in relations.values()) == 240

    graph = load_json(GRAPH_PATH)
    assert len(graph["nodes"]) == 166
    assert len(graph["edges"]) == 240
    assert any(
        edge["relation"] == "REL"
        and edge["source"] == "KNG-AUD-SEGMENT-TIMESTAMP-001"
        and edge["target"] == "CAP-AUD-SEGMENT-ALIGN-001"
        for edge in graph["edges"]
    )
    assert any(
        edge["relation"] == "SUP"
        and edge["source"] == "RES-AUD-CONFIG-CHECKLIST-001"
        and edge["target"] == "CAP-AUD-WAKE-COMMAND-001"
        for edge in graph["edges"]
    )


def test_every_audio_asset_ref_resolves_to_a_manifest_record():
    manifest = load_json(MANIFEST_PATH)
    records = {asset["asset_id"]: asset for asset in manifest["assets"]}
    items = audio_asset_items()
    refs = [item["asset_ref"] for _, item in items]

    assert manifest["schema_version"] == "1.0.0"
    assert len(items) == 24
    assert len(refs) == len(set(refs))
    assert set(records) == set(refs)
    assert manifest["asset_count"] == 24
    assert manifest["structured_fixture_count"] == 23
    assert manifest["authorized_audio_count"] == 1

    for unit, item in items:
        record = records[item["asset_ref"]]
        assert record["unit_id"] == unit["id"]
        assert record["source_item_id"] == item_id(item)


def test_structured_fixture_manifest_records_are_non_media_and_digest_bound():
    manifest = load_json(MANIFEST_PATH)
    records = {asset["asset_id"]: asset for asset in manifest["assets"]}

    for unit, item in audio_asset_items():
        if item["asset_ref"] == "ASSET-AUDIO-TASK4-TONE-SILENCE-TONE-001":
            continue
        record = records[item["asset_ref"]]
        assert record["representation"] == "structured_fixture"
        assert record["is_media"] is False
        assert record["media_type"] == "application/json"
        assert record["storage"] == "inline_input"
        assert record["inline_input_sha256"] == canonical_digest(item["input"])
        assert record["authorization"]["type"] == "self-authored"
        assert record["authorization"]["student_use_allowed"] is True


def test_advanced_asset_bindings_and_shared_follow_ups_are_resolved():
    advanced = load_json(AUDIO_FILES[1])
    manifest_ids = {
        asset["asset_id"] for asset in load_json(MANIFEST_PATH)["assets"]
    }
    structured = []
    for unit in advanced["units"]:
        items = [
            *unit["positive_examples"],
            *unit["negative_examples"],
            unit["exercise"],
            *unit["practice_variants"],
        ]
        structured.extend(
            item for item in items if item["representation"] == "structured_fixture"
        )

    assert len(structured) == 11
    assert all(item["manifest_resolution"] == "resolved" for item in structured)
    assert {item["asset_ref"] for item in structured} <= manifest_ids

    follow_ups = {
        item["follow_up_id"]: item for item in advanced["shared_follow_ups"]
    }
    assert set(follow_ups) == set(EXPECTED_RESOLVED_FOLLOW_UPS)
    for follow_up_id, resolution_ref in EXPECTED_RESOLVED_FOLLOW_UPS.items():
        assert follow_ups[follow_up_id]["status"] == "resolved"
        assert follow_ups[follow_up_id]["resolution_ref"] == resolution_ref


def test_authorized_audio_manifest_record_resolves_wav_and_authorization_id():
    manifest = load_json(MANIFEST_PATH)
    records = {asset["asset_id"]: asset for asset in manifest["assets"]}
    authorization = load_json(AUTHORIZATION_PATH)
    record = records["ASSET-AUDIO-TASK4-TONE-SILENCE-TONE-001"]
    wav_path = AUTHORIZATION_PATH.parent / record["file"]

    assert record["representation"] == "authorized_audio"
    assert record["is_media"] is True
    assert record["media_type"] == "audio/wav"
    assert record["authorization_file"] == AUTHORIZATION_PATH.name
    assert record["authorization_asset_id"] == authorization["asset_id"]
    assert record["sha256"] == authorization["sha256"]
    assert hashlib.sha256(wav_path.read_bytes()).hexdigest() == record["sha256"]


def test_failed_task4_ai_reviews_are_retained_exactly_for_audit():
    records = {
        record["review_id"]: record
        for record in load_json(REVIEW_REGISTRY_PATH)["records"]
    }

    for expected in (FOUNDATION_REVIEW, ADVANCED_REVIEW):
        record = records[expected["review_id"]]
        for field in (
            "reviewer_id",
            "reviewer_type",
            "independent_of_implementation",
            "reviewed_at",
            "reviewed_commit",
        ):
            assert record[field] == expected[field]
        assert record["scope"]["data_type"] == "audio"
        assert set(record["scope"]["unit_ids"]) == expected["unit_ids"]
        assert record["scope"]["publication_scope"] == "development_only"
        assert record["scope"]["human_release_allowed"] is False
        assert {item["unit_id"] for item in record["unit_versions"]} == expected[
            "unit_ids"
        ]
        assert all(
            item["data_version"] == "1.0.0"
            and item["evaluation_version"] == "1.0.0"
            for item in record["unit_versions"]
        )
        assert record["decision"] == "changes_required"
        assert record["authorizes_publication"] is False
        assert record["publication_scope"] == "development_only"
        assert record["human_release_allowed"] is False
        assert record["finding_count"] == len(expected["finding_summaries"])
        assert [finding["summary"] for finding in record["findings"]] == expected[
            "finding_summaries"
        ]
        assert record["remaining_risks"] == EXPECTED_REMAINING_RISKS


def test_central_build_has_19_units_and_all_task4_task5_draft_links():
    central = load_json(CENTRAL_PATH)
    graph = load_json(GRAPH_PATH)
    task_nodes = {
        node["id"]: node for node in graph["nodes"] if node["type"] == "TSK"
    }
    audio_units = [unit for unit in central["units"] if unit["data_type"] == "audio"]
    video_units = [unit for unit in central["units"] if unit["data_type"] == "video"]

    assert len(central["units"]) == 19
    assert len(audio_units) == 6
    assert len(video_units) == 3
    assert all(unit["review_status"] == "draft" for unit in audio_units + video_units)
    assert all(unit["student_visible"] is False for unit in audio_units + video_units)
    assert {
        unit["id"] for unit in audio_units + video_units
    }.isdisjoint(central["student_visible_unit_ids"])

    linked_audio = {
        link["unit_id"]
        for node in task_nodes.values()
        for link in node["teaching_unit_links"]
        if link["unit_id"].startswith("TU-AUDIO-")
    }
    assert linked_audio == {unit["id"] for unit in audio_units}
    for task_id, unit_ids in EXPECTED_VIDEO_TASK_LINKS.items():
        links = task_nodes[task_id]["teaching_unit_links"]
        assert [link["unit_id"] for link in links] == unit_ids
        assert all(
            link == {
                "unit_id": link["unit_id"],
                "review_status": "draft",
                "student_visible": False,
                "in_student_visible_index": False,
                "consumable": False,
            }
            for link in links
        )
    all_graph_links = {
        link["unit_id"]
        for node in task_nodes.values()
        for link in node["teaching_unit_links"]
    }
    assert "TU-VIDEO-TRACK-ID-001" not in all_graph_links
