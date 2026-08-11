"""Teacher-Agent aggregate tools and draft construction.

The functions in this module deliberately avoid the regular Agent registry.
That registry is a learner-facing capability set and several of its tools can
read or write individual learning records.  A teacher Agent receives only the
bounded, class-owned aggregates built here; it never receives names, e-mails,
raw submissions, score answers, or diagnostic reports.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import utc_now_iso
from ..errors import ApiError

WEAK_LINE = 0.6
MAX_WEAK_CAPABILITIES = 5
MAX_DRAFT_CAPABILITIES = 3
MAX_DRAFT_RESOURCES = 3


def _placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def assert_owned_teacher_class(
    db: sqlite3.Connection, *, teacher_id: str, class_id: str
) -> None:
    """Recheck live class ownership at every teacher-Agent data boundary.

    A conversation can outlive a staffing change.  Looking up
    ``class_teachers`` instead of trusting the stored conversation scope makes
    old runs, SSE reconnects, and confirmation clicks lose access immediately.
    """

    row = db.execute("SELECT id FROM classes WHERE id = ?", (class_id,)).fetchone()
    if row is None:
        raise ApiError(404, "CLASS_NOT_FOUND", "班级不存在")
    owned = db.execute(
        "SELECT 1 FROM class_teachers WHERE class_id = ? AND teacher_id = ?",
        (class_id, teacher_id),
    ).fetchone()
    if owned is None:
        raise ApiError(403, "FORBIDDEN", "您不是该班级的任课教师，无权操作")


def _class_student_ids(db: sqlite3.Connection, class_id: str) -> list[str]:
    """Return opaque IDs only for SQL aggregation, never for a tool payload."""

    rows = db.execute(
        """
        SELECT student_id
        FROM class_enrollments
        WHERE class_id = ? AND left_at IS NULL
        """,
        (class_id,),
    ).fetchall()
    return [str(row["student_id"]) for row in rows]


def _cap_names() -> dict[str, str]:
    """Resolve capability labels without making graph availability a data leak."""

    try:
        from ..graphx import reason

        return {
            str(node["id"]): str(node.get("name") or node["id"])
            for node in reason.get_graph()["nodes"]
            if node.get("type") == "CAP"
        }
    except Exception:
        # A stable capability ID remains enough to build a constrained draft
        # when optional graph content is unavailable.
        return {}


def class_insights(
    db: sqlite3.Connection, *, teacher_id: str, class_id: str
) -> dict[str, Any]:
    """Build a small, anonymous class-learning snapshot.

    The query intentionally never joins ``users`` and never reads
    ``task_attempts`` or ``diagnostic_summaries``.  It therefore cannot put
    student PII, original work, answer keys, or diagnostic details into an
    Agent tool result or model context.
    """

    assert_owned_teacher_class(db, teacher_id=teacher_id, class_id=class_id)
    student_ids = _class_student_ids(db, class_id)
    cap_names = _cap_names()

    weak_capabilities: list[dict[str, Any]] = []
    mastery_record_count = 0
    if student_ids:
        rows = db.execute(
            f"""
            SELECT cap_id,
                   AVG(score) AS average_mastery,
                   SUM(CASE WHEN score < ? THEN 1 ELSE 0 END) AS weak_student_count,
                   COUNT(*) AS record_count
            FROM mastery
            WHERE scenario_id = '' AND user_id IN ({_placeholders(student_ids)})
            GROUP BY cap_id
            ORDER BY average_mastery ASC, cap_id ASC
            LIMIT ?
            """,
            (WEAK_LINE, *student_ids, MAX_WEAK_CAPABILITIES),
        ).fetchall()
        mastery_record_count = sum(int(row["record_count"]) for row in rows)
        weak_capabilities = [
            {
                "cap_id": row["cap_id"],
                "cap_name": cap_names.get(row["cap_id"], row["cap_id"]),
                # Keep the public names aligned with the teacher analytics UI;
                # these are class-level aggregates, never student records.
                "avg_score": round(float(row["average_mastery"]), 3),
                "affected_student_count": int(row["weak_student_count"]),
            }
            for row in rows
        ]

    assigned_task_count = 0
    completed_task_count = 0
    submitted_task_count = 0
    if student_ids:
        counts = db.execute(
            f"""
            SELECT COUNT(*) AS assigned_task_count,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_task_count,
                   SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) AS submitted_task_count
            FROM learning_tasks
            WHERE class_id = ? AND user_id IN ({_placeholders(student_ids)})
            """,
            (class_id, *student_ids),
        ).fetchone()
        assigned_task_count = int(counts["assigned_task_count"] or 0)
        completed_task_count = int(counts["completed_task_count"] or 0)
        submitted_task_count = int(counts["submitted_task_count"] or 0)

    completion_rate = (
        round(completed_task_count / assigned_task_count, 3)
        if assigned_task_count
        else None
    )
    return {
        "class_id": class_id,
        "student_count": len(student_ids),
        "mastery_record_count": mastery_record_count,
        "assigned_task_count": assigned_task_count,
        "completed_task_count": completed_task_count,
        "submitted_task_count": submitted_task_count,
        "completion_rate": completion_rate,
        "weak_capabilities": weak_capabilities,
        "sample_warning": len(student_ids) < 3,
    }


def _eligible_student_resources(
    db: sqlite3.Connection,
    *,
    cap_ids: list[str],
    data_type: str | None = None,
    scenario_id: str | None = None,
) -> list[dict[str, str]]:
    """Choose only published, authorized resources that students may receive."""

    now = utc_now_iso()
    rows = db.execute(
        """
        SELECT d.id, d.title, d.cap_ids_json, d.data_types_json, d.scenario_ids_json
        FROM rag_documents d
        LEFT JOIN source_ledgers sl ON sl.id = d.source_ledger_id
        WHERE d.status = 'published'
          AND d.visibility = 'student'
          AND d.license_status = 'authorized'
          AND (d.expires_at IS NULL OR d.expires_at > ?)
          AND (
            sl.id IS NULL
            OR (
              sl.authorization_status NOT IN ('forbidden', 'expired')
              AND (sl.valid_to IS NULL OR sl.valid_to > ?)
            )
          )
        ORDER BY d.published_at DESC, d.updated_at DESC, d.rowid DESC
        LIMIT 30
        """,
        (now, now),
    ).fetchall()

    # SQLite JSON support is not guaranteed in the supported local runtime.
    # The database result set is deliberately small, so parsing the declared
    # capability array in Python keeps the eligibility rule portable.
    docs: list[dict[str, str]] = []
    for row in rows:
        try:
            document_caps = set(json.loads(row["cap_ids_json"] or "[]"))
            document_types = set(json.loads(row["data_types_json"] or "[]"))
            document_scenarios = set(json.loads(row["scenario_ids_json"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            # Malformed source metadata cannot become a candidate for an Agent
            # draft, because it would weaken the declared student-resource scope.
            continue
        if data_type and data_type not in document_types:
            continue
        if scenario_id and scenario_id not in document_scenarios:
            continue
        if not cap_ids or document_caps.intersection(cap_ids):
            docs.append({"type": "rag_document", "ref_id": row["id"], "title": row["title"]})
        if len(docs) >= MAX_DRAFT_RESOURCES:
            break
    return docs


def _first_capability(
    insights: dict[str, Any], requested_cap_ids: list[str] | None
) -> list[str]:
    """Prefer measured weak capabilities, allowing a teacher-selected fallback."""

    if requested_cap_ids:
        return list(dict.fromkeys(str(item) for item in requested_cap_ids if str(item)))[:MAX_DRAFT_CAPABILITIES]
    return [
        str(item["cap_id"])
        for item in insights.get("weak_capabilities", [])[:MAX_DRAFT_CAPABILITIES]
        if isinstance(item, dict) and isinstance(item.get("cap_id"), str)
    ]


def task_draft_preview(
    db: sqlite3.Connection,
    *,
    teacher_id: str,
    class_id: str,
    insights: dict[str, Any] | None = None,
    requested_cap_ids: list[str] | None = None,
    data_type: str | None = None,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Create an editable, non-persistent teacher-task draft from aggregates.

    The teacher's free-text request is intentionally not copied into this tool
    payload.  The draft is steered by the request-selected capabilities and
    anonymous analytics, while preventing a pasted student record from being
    stored in tool-call arguments or sent to an optional language model.
    """

    assert_owned_teacher_class(db, teacher_id=teacher_id, class_id=class_id)
    snapshot = insights or class_insights(db, teacher_id=teacher_id, class_id=class_id)
    cap_ids = _first_capability(snapshot, requested_cap_ids)
    if not cap_ids:
        return {
            "ready_to_save": False,
            "reason": "当前班级尚无可用于定向任务的能力掌握度数据，请先选择目标能力后再生成草稿。",
            "insights": snapshot,
        }

    resources = _eligible_student_resources(
        db,
        cap_ids=cap_ids,
        data_type=data_type,
        scenario_id=scenario_id,
    )
    if not resources:
        return {
            "ready_to_save": False,
            "reason": "当前没有可分配给学生的已发布授权资料，请先补充资料后再生成草稿。",
            "insights": snapshot,
        }

    cap_names = _cap_names()
    primary_cap = cap_ids[0]
    primary_label = cap_names.get(primary_cap, primary_cap)
    weak_item = next(
        (
            item
            for item in snapshot.get("weak_capabilities", [])
            if isinstance(item, dict) and item.get("cap_id") == primary_cap
        ),
        None,
    )
    average_mastery = (
        float(weak_item["avg_score"])
        if isinstance(weak_item, dict) and isinstance(weak_item.get("avg_score"), (float, int))
        else None
    )
    mastery_note = (
        f"当前班级该能力平均掌握度为 {average_mastery:.0%}，"
        if average_mastery is not None
        else "围绕教师选择的目标能力，"
    )
    modality = {"text": "文本", "image": "图像", "audio": "音频", "video": "视频"}.get(
        data_type or "", ""
    )
    title = f"{modality}{primary_label}定向巩固任务"[:80]
    draft = {
        "title": title,
        "goal": f"{mastery_note}通过规范学习、示范练习和自检巩固 {primary_label}。",
        # These normalized categories originate from an explicit selection or
        # intent detection.  They preserve the teacher's goal without copying
        # free text into a tool payload that might contain pasted student data.
        "data_type": data_type,
        "scenario_id": scenario_id,
        "cap_ids": cap_ids,
        "steps": [
            {
                "title": "聚焦规范要点",
                "description": f"阅读关联资料，整理 {primary_label} 的关键规则与常见遗漏。",
            },
            {
                "title": "完成定向练习",
                "description": "按规范完成练习，并在提交前逐项自查。",
            },
            {
                "title": "复盘并巩固",
                "description": "根据反馈复盘薄弱环节，记录下一次练习需要注意的规则。",
            },
        ],
        "resources": resources,
        "rubric": [
            {"criterion": "规范符合性", "description": "结果符合关联资料中的规则", "points": 50},
            {"criterion": "完整性", "description": "关键字段、边界或标签无遗漏", "points": 30},
            {"criterion": "自检质量", "description": "提交前完成对照检查并修正问题", "points": 20},
        ],
    }
    return {
        "ready_to_save": True,
        "class_id": class_id,
        "draft": draft,
        "insights": snapshot,
        "notice": "任务尚未发布。确认后会为当前班级的在班学生创建任务并发送通知。",
    }


def validate_student_resources(db: sqlite3.Connection, resources: list[dict[str, Any]]) -> None:
    """Keep an edited Agent draft within the student-visible resource boundary."""

    ref_ids = [
        str(item.get("ref_id"))
        for item in resources
        if isinstance(item, dict) and item.get("type") == "rag_document" and item.get("ref_id")
    ]
    if len(ref_ids) != len(resources) or not ref_ids:
        raise ApiError(400, "RESOURCES_REQUIRED", "任务资料必须是可分配给学生的已发布资料")
    placeholders = _placeholders(ref_ids)
    now = utc_now_iso()
    eligible_rows = db.execute(
        f"""
        SELECT d.id
        FROM rag_documents d
        LEFT JOIN source_ledgers sl ON sl.id = d.source_ledger_id
        WHERE d.id IN ({placeholders})
          AND d.status = 'published'
          AND d.visibility = 'student'
          AND d.license_status = 'authorized'
          AND (d.expires_at IS NULL OR d.expires_at > ?)
          AND (
            sl.id IS NULL
            OR (
              sl.authorization_status NOT IN ('forbidden', 'expired')
              AND (sl.valid_to IS NULL OR sl.valid_to > ?)
            )
          )
        """,
        (*ref_ids, now, now),
    ).fetchall()
    eligible = {str(row["id"]) for row in eligible_rows}
    if any(ref_id not in eligible for ref_id in ref_ids):
        raise ApiError(400, "RESOURCE_NOT_AVAILABLE", "所选资料不可分配给学生")
