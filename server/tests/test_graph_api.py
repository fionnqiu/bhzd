"""Graph HTTP API tests for student-safe task-material projections."""

from __future__ import annotations


def test_cap_detail_projects_only_consumable_student_teaching_units(api):
    """A graph CAP exposes a real teaching unit, not a catalogue RES node."""
    response = api.client.get("/api/graph/nodes/CAP-AUD-EMOTION-PARALING-001")

    assert response.status_code == 200, response.text
    assert response.json()["learning_materials"] == [
        {
            "type": "teaching_unit",
            "ref_id": "TU-AUDIO-EMOTION-PARALINGUISTICS-001",
            "title": "分轨标注语音情感与副语言事件",
        }
    ]


def test_cap_detail_keeps_material_list_empty_when_no_unit_is_linked(api):
    """Missing catalogue mappings stay explicit instead of producing fake materials."""
    response = api.client.get("/api/graph/nodes/CAP-CORE-ASSET-QUALITY-001")

    assert response.status_code == 200, response.text
    assert response.json()["learning_materials"] == []
