"""掌握度服务测试：clamp、练习公式、诊断扣分聚合、历史事件、薄弱排序。"""

from __future__ import annotations

import uuid

import pytest

from bhzd_py import db as db_module
from bhzd_py.mastery import service

USER = "user-test-001"
CAP_A = "CAP-AUD-SEGMENT-ALIGN-001"
CAP_B = "CAP-AUD-SPEAKER-001"
CAP_C = "CAP-CORE-TASK-SCOPE-001"


@pytest.fixture()
def db(tmp_db_path):
    """独立临时库连接（掌握度是纯 db 逻辑，不需要起 app）。"""
    conn = db_module.connect(tmp_db_path)
    db_module.apply_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at) "
        "VALUES (?, ?, '测试', 'student', 'active', '2026-01-01', '2026-01-01', '2026-01-01')",
        (USER, f"{USER}@test.local"),
    )
    conn.commit()
    yield conn
    conn.close()


def test_exercise_formula_and_preview_no_write(db):
    """练习公式：new = old + 0.15*score − 0.1*(1−score)；preview 不落库。"""
    service.apply_updates(
        db, USER, [{"cap_id": CAP_A, "delta": 0.5}], source="assessment"
    )
    delta = service.exercise_delta(0.8)
    assert delta == pytest.approx(0.15 * 0.8 - 0.1 * 0.2)  # 0.10
    preview = service.preview_from_deltas(
        db, USER, [{"cap_id": CAP_A, "delta": delta}]
    )
    assert preview == [
        {
            "cap_id": CAP_A,
            "delta": pytest.approx(0.10),
            "old_score": pytest.approx(0.5),
            "new_score": pytest.approx(0.6),
        }
    ]
    # preview 无副作用：库里仍是 0.5
    assert service.get_mastery(db, USER)[0]["score"] == pytest.approx(0.5)


def test_clamp_bounds(db):
    """低于 0 钳 0、高于 1 钳 1（PRD-06 §8.4）。"""
    applied = service.apply_updates(
        db, USER, [{"cap_id": CAP_A, "delta": -5.0}], source="diagnostic"
    )
    assert applied[0]["new_score"] == 0.0
    applied = service.apply_updates(
        db, USER, [{"cap_id": CAP_A, "delta": 9.0}], source="exercise"
    )
    assert applied[0]["new_score"] == 1.0
    row = db.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = ?", (USER, CAP_A)
    ).fetchone()
    assert row["score"] == 1.0


def test_diagnostic_deltas_aggregation():
    """诊断扣分按 cap 聚合：major −0.2 / minor −0.05。"""
    errors = [
        {"cap_id": CAP_A, "severity": "major"},
        {"cap_id": CAP_A, "severity": "major"},
        {"cap_id": CAP_A, "severity": "minor"},
        {"cap_id": CAP_B, "severity": "minor"},
        {"cap_id": None, "severity": "major"},  # 无 cap 的错误被丢弃
    ]
    deltas = service.diagnostic_deltas(errors)
    assert deltas == [
        {"cap_id": CAP_A, "delta": -0.45},
        {"cap_id": CAP_B, "delta": -0.05},
    ]


def test_apply_updates_writes_history_events(db):
    service.apply_updates(
        db,
        USER,
        [{"cap_id": CAP_A, "delta": 0.3}],
        source="exercise",
        ref_id="attempt-1",
    )
    service.apply_updates(
        db,
        USER,
        [{"cap_id": CAP_A, "delta": -0.2}],
        source="diagnostic",
        ref_id="summary-1",
    )
    events = db.execute(
        "SELECT * FROM mastery_events WHERE user_id = ? ORDER BY rowid",  # rowid = 插入序，不受同微秒时间戳影响
        (USER,),
    ).fetchall()
    assert len(events) == 2
    first, second = events[0], events[1]
    assert (first["old_score"], first["new_score"], first["source"], first["ref_id"]) == (
        0.0,
        0.3,
        "exercise",
        "attempt-1",
    )
    assert (second["old_score"], second["new_score"], second["source"]) == (
        0.3,
        pytest.approx(0.1),
        "diagnostic",
    )


def test_get_mastery_joins_cap_names(db):
    service.apply_updates(db, USER, [{"cap_id": CAP_A, "delta": 0.5}], source="exercise")
    rows = service.get_mastery(db, USER)
    assert rows[0]["cap_name"] == "切割音频并对齐"  # 图谱中文名


def test_weak_caps_ordering_and_threshold(db):
    for cap_id, delta in ((CAP_A, 0.1), (CAP_B, 0.3), (CAP_C, 0.9)):
        service.apply_updates(
            db, USER, [{"cap_id": cap_id, "delta": delta}], source="exercise"
        )
    weak = service.weak_caps(db, USER)
    assert [w["cap_id"] for w in weak] == [CAP_A, CAP_B]  # 升序，0.9 不算薄弱
    assert weak[0]["cap_name"] == "切割音频并对齐"
    limited = service.weak_caps(db, USER, limit=1)
    assert [w["cap_id"] for w in limited] == [CAP_A]
    strict = service.weak_caps(db, USER, threshold=0.05)
    assert strict == []
