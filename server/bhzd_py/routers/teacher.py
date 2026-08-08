"""教师端路由（蓝图 §6.5，PRD-02 全篇，PRD-06 §10）。

关键决策（为什么）：
- 数据隔离以 class_teachers 为准（蓝图 §15）：教师只能看到/操作自己带的班级，
  越权一律 403 中文提示；班级存在性对非本班教师也按 403 处理（不单独做存在性探测）。
- 教师任务原件也是 learning_tasks 行（user_id=教师本人、source='teacher'、
  status='draft' 作为模板态）；发布 = 为每个在班学生复制一行
  （parent_task_id 链回原件）。原件保持 'draft'：发布状态由"有无学生副本"
  推导，schema 的 status CHECK 没有 published 值，不能硬塞。
- 修改已发布任务 → version+1 新原件（PRD-06 §10.1：不直接覆盖学生已开始的任务）。
- 学情分析的所有数字都必须来自真实学习数据（PRD-02 §6.3）；学生 <3 人置
  sample_warning（PRD-06 §10.2 样本过小提示）。
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..audit import audit
from ..config import get_config
from ..db import transaction, utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_db, require_role
from ..errors import ApiError
from ..notify import notify_many

router = APIRouter()

TEACHER_ROLES = ("teacher", "content_admin", "system_admin")
WEAK_LINE = 0.6  # 班级薄弱线（PRD-02 §6 热力图口径）
MIN_SAMPLE = 3  # PRD-06 §10.2：少于此人数聚合报表提示样本过小


# ---------------------------------------------------------------- 依赖与小工具


def _require_teacher_role(current: CurrentUser) -> CurrentUser:
    """变更端点的角色校验（csrf_protect 只验会话不验角色，需叠加）。"""
    if current.user["role"] not in TEACHER_ROLES:
        raise ApiError(403, "FORBIDDEN", "需要教师或管理员权限")
    return current


def _owned_class_ids(conn: sqlite3.Connection, teacher_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT class_id FROM class_teachers WHERE teacher_id = ?", (teacher_id,)
    ).fetchall()
    return [r["class_id"] for r in rows]


def _get_owned_class(conn: sqlite3.Connection, class_id: str, teacher_id: str) -> sqlite3.Row:
    """取班级并强制属权：非本班教师 403（蓝图 §15 按 class_teachers 隔离）。"""
    row = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    if row is None:
        raise ApiError(404, "CLASS_NOT_FOUND", "班级不存在")
    owned = conn.execute(
        "SELECT 1 FROM class_teachers WHERE class_id = ? AND teacher_id = ?",
        (class_id, teacher_id),
    ).fetchone()
    if owned is None:
        raise ApiError(403, "FORBIDDEN", "您不是该班级的任课教师，无权操作")
    return row


def _cap_names() -> dict[str, str]:
    """cap_id → 中文名（graphx 缺席降级空映射，学情接口不被内容文件拖垮）。"""
    try:
        from ..graphx import reason

        return {
            n["id"]: n.get("name") or n["id"]
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "CAP"
        }
    except Exception:
        return {}


def _validate_cap_ids(cap_ids: list[str]) -> None:
    """校验 cap_ids 存在于图谱（教师任务必须挂真实能力节点，PRD-02 §5.4）。"""
    try:
        from ..graphx import reason

        known = {n["id"] for n in reason.get_graph()["nodes"] if n.get("type") == "CAP"}
    except Exception as exc:
        raise ApiError(500, "GRAPH_UNAVAILABLE", "能力图谱暂不可用，请稍后重试") from exc
    missing = [cid for cid in cap_ids if cid not in known]
    if missing:
        raise ApiError(400, "CAP_NOT_FOUND", f"以下能力节点不存在：{'、'.join(missing)}")


def _placeholders(ids: list[str]) -> str:
    return ",".join("?" for _ in ids)


def _class_student_ids(conn: sqlite3.Connection, class_ids: list[str]) -> list[str]:
    """若干班级的在班学生 id 并集（left_at IS NULL 才算在班）。"""
    if not class_ids:
        return []
    rows = conn.execute(
        f"SELECT DISTINCT student_id FROM class_enrollments "
        f"WHERE class_id IN ({_placeholders(class_ids)}) AND left_at IS NULL",
        class_ids,
    ).fetchall()
    return [r["student_id"] for r in rows]


def _avg_mastery(conn: sqlite3.Connection, student_ids: list[str]) -> float | None:
    """一组学生的通用掌握度均值；无记录返回 None（前端展示"暂无数据"）。"""
    if not student_ids:
        return None
    row = conn.execute(
        f"SELECT AVG(score) AS v FROM mastery WHERE scenario_id = '' AND user_id IN ({_placeholders(student_ids)})",
        student_ids,
    ).fetchone()
    return float(row["v"]) if row["v"] is not None else None


def _task_json(row: sqlite3.Row, key: str, default: Any) -> Any:
    raw = row[key]
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _teacher_task_dto(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    published = conn.execute(
        "SELECT COUNT(*) AS n FROM learning_tasks WHERE parent_task_id = ?",
        (row["id"],),
    ).fetchone()["n"]
    return {
        "id": row["id"],
        "title": row["title"],
        "goal": row["goal"],
        "data_type": row["data_type"],
        "scenario_id": row["scenario_id"],
        "cap_ids": _task_json(row, "cap_ids_json", []),
        "steps": _task_json(row, "steps_json", []),
        "resources": _task_json(row, "resources_json", []),
        "rubric": _task_json(row, "rubric_json", None),
        "practice": _task_json(row, "practice_json", None),
        "status": row["status"],
        "version": row["version"],
        "parent_task_id": row["parent_task_id"],
        "published_count": published,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_own_teacher_task(conn: sqlite3.Connection, task_id: str, teacher_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM learning_tasks WHERE id = ? AND source = 'teacher'", (task_id,)
    ).fetchone()
    if row is None or row["user_id"] != teacher_id:
        raise ApiError(404, "TASK_NOT_FOUND", "教学任务不存在")
    return row


# ---------------------------------------------------------------- 工作台


@router.get("/api/teacher/dashboard")
def dashboard(
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """工作台：班级概览（人数/完成率/平均掌握度）+ 薄弱 Top5 + 待办。"""
    teacher_id = current.user["id"]
    class_ids = _owned_class_ids(conn, teacher_id)
    classes = []
    for class_id in class_ids:
        clazz = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        student_ids = _class_student_ids(conn, [class_id])
        stats = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS done "
            "FROM learning_tasks WHERE class_id = ? AND user_id != ?",
            (class_id, teacher_id),
        ).fetchone()
        total, done = stats["total"] or 0, stats["done"] or 0
        classes.append(
            {
                "id": class_id,
                "name": clazz["name"],
                "student_count": len(student_ids),
                "task_completion_rate": (done / total) if total else None,
                "avg_mastery": _avg_mastery(conn, student_ids),
            }
        )

    all_students = _class_student_ids(conn, class_ids)
    weak_top: list[dict] = []
    if all_students:
        rows = conn.execute(
            f"SELECT cap_id, AVG(score) AS avg_score, COUNT(*) AS n FROM mastery "
            f"WHERE scenario_id = '' AND user_id IN ({_placeholders(all_students)}) "
            f"GROUP BY cap_id HAVING avg_score < ? ORDER BY avg_score ASC LIMIT 5",
            (*all_students, WEAK_LINE),
        ).fetchall()
        names = _cap_names()
        weak_top = [
            {
                "cap_id": r["cap_id"],
                "cap_name": names.get(r["cap_id"], r["cap_id"]),
                "avg_score": float(r["avg_score"]),
                "student_count": r["n"],
            }
            for r in rows
        ]

    unpublished = conn.execute(
        "SELECT COUNT(*) AS n FROM learning_tasks t WHERE t.user_id = ? AND t.source = 'teacher' "
        "AND NOT EXISTS (SELECT 1 FROM learning_tasks c WHERE c.parent_task_id = t.id)",
        (teacher_id,),
    ).fetchone()["n"]
    return {
        "classes": classes,
        "weak_caps_top5": weak_top,
        "todos": {
            "unpublished_teacher_tasks": unpublished,
        },
    }


# ---------------------------------------------------------------- 班级管理


class ClassCreateBody(BaseModel):
    name: str


@router.get("/api/teacher/classes")
def list_classes(
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    teacher_id = current.user["id"]
    items = []
    for class_id in _owned_class_ids(conn, teacher_id):
        clazz = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        recent = conn.execute(
            "SELECT title FROM learning_tasks WHERE class_id = ? ORDER BY created_at DESC LIMIT 1",
            (class_id,),
        ).fetchone()
        items.append(
            {
                "id": class_id,
                "name": clazz["name"],
                "invite_code": clazz["invite_code"],
                "student_count": len(_class_student_ids(conn, [class_id])),
                "recent_task_title": recent["title"] if recent else None,
                "created_at": clazz["created_at"],
            }
        )
    return {"items": items, "total": len(items)}


@router.post("/api/teacher/classes", status_code=201)
def create_class(
    body: ClassCreateBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    _require_teacher_role(current)
    if not body.name.strip():
        raise ApiError(400, "VALIDATION_ERROR", "班级名称不能为空")
    class_id = uuid.uuid4().hex
    invite_code = secrets.token_urlsafe(6)  # 短邀请码，学生凭码入班
    conn.execute(
        "INSERT INTO classes (id, name, invite_code, created_at) VALUES (?, ?, ?, ?)",
        (class_id, body.name.strip(), invite_code, utc_now_iso()),
    )
    conn.execute(
        "INSERT INTO class_teachers (class_id, teacher_id) VALUES (?, ?)",
        (class_id, current.user["id"]),
    )
    conn.commit()
    audit(conn, current.user, "class.create", target_type="class", target_id=class_id,
          after={"name": body.name.strip()})
    return {"id": class_id, "name": body.name.strip(), "invite_code": invite_code}


@router.get("/api/teacher/classes/{class_id}")
def class_detail(
    class_id: str,
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    clazz = _get_owned_class(conn, class_id, current.user["id"])
    student_ids = _class_student_ids(conn, [class_id])
    tasks = conn.execute(
        "SELECT id, title, status, due_at, created_at FROM learning_tasks "
        "WHERE class_id = ? ORDER BY created_at DESC LIMIT 10",
        (class_id,),
    ).fetchall()
    return {
        "id": clazz["id"],
        "name": clazz["name"],
        "invite_code": clazz["invite_code"],
        "student_count": len(student_ids),
        "avg_mastery": _avg_mastery(conn, student_ids),
        "recent_tasks": [dict(t) for t in tasks],
        "created_at": clazz["created_at"],
    }


@router.post("/api/teacher/classes/{class_id}/invite")
def regenerate_invite(
    class_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    _require_teacher_role(current)
    _get_owned_class(conn, class_id, current.user["id"])
    new_code = secrets.token_urlsafe(6)
    conn.execute("UPDATE classes SET invite_code = ? WHERE id = ?", (new_code, class_id))
    conn.commit()
    audit(conn, current.user, "class.invite_regenerate", target_type="class", target_id=class_id)
    return {"id": class_id, "invite_code": new_code}


class EnrollBody(BaseModel):
    student_email: str


@router.post("/api/teacher/classes/{class_id}/enroll", status_code=201)
def enroll_student(
    class_id: str,
    body: EnrollBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """教师按邮箱把学生加进班级（邀请码之外的主动通道；幂等 + 审计）。"""
    _require_teacher_role(current)
    _get_owned_class(conn, class_id, current.user["id"])
    student = conn.execute(
        "SELECT * FROM users WHERE email = ? AND role = 'student'", (body.student_email.strip(),)
    ).fetchone()
    if student is None:
        raise ApiError(404, "STUDENT_NOT_FOUND", "未找到该学生账号，请确认学生已注册")
    existing = conn.execute(
        "SELECT * FROM class_enrollments WHERE class_id = ? AND student_id = ?",
        (class_id, student["id"]),
    ).fetchone()
    if existing is not None and existing["left_at"] is None:
        return {"class_id": class_id, "student_id": student["id"], "already_enrolled": True}
    if existing is not None:
        conn.execute(
            "UPDATE class_enrollments SET joined_at = ?, left_at = NULL "
            "WHERE class_id = ? AND student_id = ?",
            (utc_now_iso(), class_id, student["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO class_enrollments (class_id, student_id, joined_at) VALUES (?, ?, ?)",
            (class_id, student["id"], utc_now_iso()),
        )
    conn.commit()
    audit(conn, current.user, "class.enroll", target_type="class", target_id=class_id,
          after={"student_id": student["id"], "via": "email"})
    return {"class_id": class_id, "student_id": student["id"], "already_enrolled": False}


@router.get("/api/teacher/classes/{class_id}/students")
def class_students(
    class_id: str,
    status: str | None = None,
    mastery_min: float | None = None,
    mastery_max: float | None = None,
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生列表：任务数/完成率/平均掌握度/最近活跃，支持状态与掌握度区间筛选。"""
    _get_owned_class(conn, class_id, current.user["id"])
    enrollments = conn.execute(
        """
        WITH enrolled AS (
          SELECT e.student_id, e.joined_at, e.left_at, u.name, u.email
          FROM class_enrollments e
          JOIN users u ON u.id = e.student_id
          WHERE e.class_id = ?
        ),
        task_stats AS (
          SELECT t.user_id,
                 COUNT(*) AS total,
                 SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) AS done
          FROM learning_tasks t
          JOIN enrolled e ON e.student_id = t.user_id
          WHERE t.class_id = ?
          GROUP BY t.user_id
        ),
        mastery_stats AS (
          SELECT m.user_id,
                 AVG(CASE WHEN m.scenario_id = '' THEN m.score END) AS avg_mastery
          FROM mastery m
          JOIN enrolled e ON e.student_id = m.user_id
          GROUP BY m.user_id
        ),
        activity AS (
          SELECT user_id, MAX(ts) AS last_active
          FROM (
            SELECT t.user_id, t.updated_at AS ts
            FROM learning_tasks t JOIN enrolled e ON e.student_id = t.user_id
            UNION ALL
            SELECT a.user_id, a.created_at AS ts
            FROM task_attempts a JOIN enrolled e ON e.student_id = a.user_id
            UNION ALL
            SELECT m.user_id, m.updated_at AS ts
            FROM mastery m JOIN enrolled e ON e.student_id = m.user_id
          )
          GROUP BY user_id
        )
        SELECT e.*, COALESCE(t.total, 0) AS task_total, COALESCE(t.done, 0) AS task_done,
               m.avg_mastery, a.last_active
        FROM enrolled e
        LEFT JOIN task_stats t ON t.user_id = e.student_id
        LEFT JOIN mastery_stats m ON m.user_id = e.student_id
        LEFT JOIN activity a ON a.user_id = e.student_id
        ORDER BY e.joined_at, e.student_id
        """,
        (class_id, class_id),
    ).fetchall()
    items = []
    for enr in enrollments:
        if status == "active" and enr["left_at"] is not None:
            continue
        if status == "left" and enr["left_at"] is None:
            continue
        sid = enr["student_id"]
        # The CTE above intentionally gathers all per-student aggregates in one
        # round trip.  Keeping the filtering here preserves the prior response
        # semantics without restoring the former three queries per enrollment.
        total, done = int(enr["task_total"]), int(enr["task_done"])
        avg_mastery = float(enr["avg_mastery"]) if enr["avg_mastery"] is not None else None
        if mastery_min is not None and (avg_mastery is None or avg_mastery < mastery_min):
            continue
        if mastery_max is not None and (avg_mastery is None or avg_mastery > mastery_max):
            continue
        items.append(
            {
                "id": sid,
                "name": enr["name"],
                "email": enr["email"],
                "task_count": total,
                "completion_rate": (done / total) if total else None,
                "avg_mastery": avg_mastery,
                "last_active": enr["last_active"],
                "joined_at": enr["joined_at"],
                "left_at": enr["left_at"],
            }
        )
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------- 学生诊断授权查看


def _get_enrolled_student(
    conn: sqlite3.Connection, class_id: str, student_id: str
) -> None:
    """校验学生当前在班（已退班视为不在班，教师不应继续查看其新数据）。"""
    enrolled = conn.execute(
        "SELECT 1 FROM class_enrollments "
        "WHERE class_id = ? AND student_id = ? AND left_at IS NULL",
        (class_id, student_id),
    ).fetchone()
    if enrolled is None:
        raise ApiError(403, "FORBIDDEN", "该学生不在您的班级中，无权查看")


def _share_diagnostics_enabled(conn: sqlite3.Connection, student_id: str) -> bool:
    """读学生侧的"授权教师查看诊断"开关（learning_profiles.share_diagnostics，
    009 迁移新增；学生从未写过 profile 行时按未授权处理）。"""
    row = conn.execute(
        "SELECT share_diagnostics FROM learning_profiles WHERE user_id = ?", (student_id,)
    ).fetchone()
    return bool(row["share_diagnostics"]) if row is not None else False


def _diagnostic_summary_items(conn: sqlite3.Connection, student_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM diagnostic_summaries WHERE user_id = ? ORDER BY created_at DESC",
        (student_id,),
    ).fetchall()
    items = []
    for r in rows:
        try:
            severity_counts = json.loads(r["severity_counts_json"] or "{}")
        except json.JSONDecodeError:
            severity_counts = {}
        items.append(
            {
                "id": r["id"],
                "file_format": r["file_format"],
                "data_type": r["data_type"],
                "scenario_id": r["scenario_id"],
                "error_count": r["error_count"],
                "severity_counts": severity_counts,
                "created_at": r["created_at"],
            }
        )
    return items


@router.get("/api/teacher/classes/{class_id}/students/{student_id}/diagnostics")
def student_diagnostics(
    class_id: str,
    student_id: str,
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生授权后的诊断明细（PRD-06 §15 #2：默认只看聚合，授权后看详情）。

    三道闸：教师拥有班级 → 学生在班 → 学生已开启授权；任一不过即 403。
    """
    _get_owned_class(conn, class_id, current.user["id"])
    _get_enrolled_student(conn, class_id, student_id)
    if not _share_diagnostics_enabled(conn, student_id):
        raise ApiError(
            403, "SHARE_NOT_GRANTED",
            "学生未授权教师查看诊断详情（学生可在个人中心开启授权后重试）",
        )
    items = _diagnostic_summary_items(conn, student_id)
    # 授权后才附完整报告（report_json 含逐条错误归因，属详细数据）
    for item in items:
        row = conn.execute(
            "SELECT report_json FROM diagnostic_summaries WHERE id = ?", (item["id"],)
        ).fetchone()
        try:
            item["report"] = json.loads(row["report_json"]) if row else None
        except json.JSONDecodeError:
            item["report"] = None
    return {"items": items, "total": len(items), "shared": True}


# ---------------------------------------------------------------- 教学任务


class TeacherTaskBody(BaseModel):
    title: str
    goal: str | None = None
    data_type: str | None = None
    scenario_id: str | None = None
    cap_ids: list[str] = []
    steps: list[dict] = []
    resources: list[dict] = []
    rubric: list[dict] | None = None
    practice: dict | None = None


class TeacherTaskPatchBody(BaseModel):
    title: str | None = None
    goal: str | None = None
    data_type: str | None = None
    scenario_id: str | None = None
    cap_ids: list[str] | None = None
    steps: list[dict] | None = None
    resources: list[dict] | None = None
    rubric: list[dict] | None = None
    practice: dict | None = None
    # 截止时间是"发布"的属性（存学生副本上），与内容字段分开处理
    due_at: str | None = None


def _check_task_body(title: str, cap_ids: list[str], resources: list[dict]) -> None:
    """PRD-02 §5.4：任务必须至少关联一个能力节点和一个来源资料。"""
    if not title.strip():
        raise ApiError(400, "VALIDATION_ERROR", "任务标题不能为空")
    if not cap_ids:
        raise ApiError(400, "CAPS_REQUIRED", "任务必须至少关联一个能力节点")
    if not resources:
        raise ApiError(400, "RESOURCES_REQUIRED", "任务必须至少关联一个来源资料")
    _validate_cap_ids(cap_ids)


@router.get("/api/teacher/tasks")
def list_teacher_tasks(
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    rows = conn.execute(
        "SELECT * FROM learning_tasks WHERE user_id = ? AND source = 'teacher' "
        "ORDER BY updated_at DESC, id DESC",
        (current.user["id"],),
    ).fetchall()
    return {"items": [_teacher_task_dto(conn, r) for r in rows], "total": len(rows)}


@router.get("/api/teacher/resources")
def list_published_resources(
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """List only resources that can safely be attached to a student task.

    This deliberately does not reuse the RAG management list: teachers need a
    small read-only picker, while unpublished, teacher-only, expired, and
    unlicensed documents must never be exposed or assigned to students.
    """
    now = utc_now_iso()
    clauses = [
        "d.status = 'published'",
        "d.visibility = 'student'",
        "d.license_status = 'authorized'",
        "(d.expires_at IS NULL OR d.expires_at > ?)",
        "(sl.id IS NULL OR (sl.authorization_status NOT IN ('forbidden', 'expired') "
        "AND (sl.valid_to IS NULL OR sl.valid_to > ?)))",
    ]
    params: list[object] = [now, now]
    if q and q.strip():
        clauses.append("d.title LIKE ?")
        params.append(f"%{q.strip()}%")
    where = " AND ".join(clauses)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM rag_documents d "
        f"LEFT JOIN source_ledgers sl ON sl.id = d.source_ledger_id WHERE {where}",
        params,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT d.id, d.title, d.version
        FROM rag_documents d
        LEFT JOIN source_ledgers sl ON sl.id = d.source_ledger_id
        WHERE {where}
        ORDER BY d.published_at DESC, d.updated_at DESC, d.rowid DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [{"id": row["id"], "title": row["title"], "version": row["version"]} for row in rows],
        "total": total,
    }


@router.post("/api/teacher/tasks", status_code=201)
def create_teacher_task(
    body: TeacherTaskBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    _require_teacher_role(current)
    _check_task_body(body.title, body.cap_ids, body.resources)
    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, goal, data_type, scenario_id, cap_ids_json, source,
           status, steps_json, resources_json, rubric_json, practice_json,
           counts_toward_mastery, teacher_id, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'teacher', 'draft', ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            task_id,
            current.user["id"],
            body.title.strip(),
            body.goal,
            body.data_type,
            body.scenario_id,
            json.dumps(body.cap_ids, ensure_ascii=False),
            json.dumps(body.steps, ensure_ascii=False),
            json.dumps(body.resources, ensure_ascii=False),
            json.dumps(body.rubric, ensure_ascii=False) if body.rubric is not None else None,
            json.dumps(body.practice, ensure_ascii=False) if body.practice is not None else None,
            current.user["id"],
            current.user["id"],
            now,
            now,
        ),
    )
    conn.commit()
    audit(conn, current.user, "teacher_task.create", target_type="learning_task",
          target_id=task_id, after={"title": body.title.strip()})
    return _teacher_task_dto(conn, _get_own_teacher_task(conn, task_id, current.user["id"]))


@router.get("/api/teacher/tasks/{task_id}")
def teacher_task_detail(
    task_id: str,
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return _teacher_task_dto(conn, _get_own_teacher_task(conn, task_id, current.user["id"]))


@router.patch("/api/teacher/tasks/{task_id}")
def patch_teacher_task(
    task_id: str,
    body: TeacherTaskPatchBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """编辑教学任务：已有学生副本的原件改为生成 version+1 新记录（PRD-06 §10.1）。

    为什么不直接改原件：学生副本 parent_task_id 指向原件，原件内容被改会让
    "学生正在做的任务"与"教师以为发布的任务"漂移；版本链保住双方。

    截止时间（due_at）例外：它是"发布"的属性、存在学生副本上而非原件上，
    因此已发布任务的截止变更直接改学生副本并通知学生（PRD-06 §10.1"通知
    学生并记录审计"），不触发版本升级——版本链保护的是任务内容，截止
    时间漂移不影响内容一致性。
    """
    _require_teacher_role(current)
    row = _get_own_teacher_task(conn, task_id, current.user["id"])
    children = conn.execute(
        "SELECT user_id, due_at FROM learning_tasks WHERE parent_task_id = ?", (task_id,)
    ).fetchall()
    has_children = len(children) > 0
    now = utc_now_iso()

    # ---- 截止时间变更：改学生副本 + 站内通知（与内容编辑相互独立）----
    due_change: dict | None = None
    if body.due_at is not None and has_children:
        old_due = children[0]["due_at"]  # MVP 单班级发布，副本共享同一截止时间
        if body.due_at != old_due:
            conn.execute(
                "UPDATE learning_tasks SET due_at = ?, updated_at = ? WHERE parent_task_id = ?",
                (body.due_at, now, task_id),
            )
            notify_many(
                conn,
                [c["user_id"] for c in children],
                "task_due_changed",
                row["title"],
                body=f"任务「{row['title']}」的截止时间已调整为 {body.due_at}，请按新时间完成",
                ref_type="task",
                ref_id=task_id,
            )
            due_change = {"old": old_due, "new": body.due_at}

    content_changed = any(
        getattr(body, field) is not None
        for field in ("title", "goal", "data_type", "scenario_id",
                      "cap_ids", "steps", "resources", "rubric", "practice")
    )
    if has_children and not content_changed:
        # 仅截止变更（或空 PATCH）：学生副本已更新，无需版本升级，直接收尾
        conn.commit()
        if due_change is not None:
            audit(conn, current.user, "teacher_task.due_change", target_type="learning_task",
                  target_id=task_id, before={"due_at": due_change["old"]},
                  after={"due_at": due_change["new"]})
        result = _teacher_task_dto(conn, _get_own_teacher_task(conn, task_id, current.user["id"]))
        result["version_bumped"] = False
        return result

    cap_ids = body.cap_ids if body.cap_ids is not None else _task_json(row, "cap_ids_json", [])
    resources = (
        body.resources if body.resources is not None else _task_json(row, "resources_json", [])
    )
    title = body.title if body.title is not None else row["title"]
    # 合并后的内容仍要满足发布底线（能力≥1 + 资料≥1）
    _check_task_body(title, cap_ids, resources)
    new_fields = {
        "title": title.strip(),
        "goal": body.goal if body.goal is not None else row["goal"],
        "data_type": body.data_type if body.data_type is not None else row["data_type"],
        "scenario_id": body.scenario_id if body.scenario_id is not None else row["scenario_id"],
        "cap_ids_json": json.dumps(cap_ids, ensure_ascii=False),
        "steps_json": json.dumps(
            body.steps if body.steps is not None else _task_json(row, "steps_json", []),
            ensure_ascii=False,
        ),
        "resources_json": json.dumps(resources, ensure_ascii=False),
        "rubric_json": (
            json.dumps(body.rubric, ensure_ascii=False) if body.rubric is not None else row["rubric_json"]
        ),
        "practice_json": (
            json.dumps(body.practice, ensure_ascii=False) if body.practice is not None else row["practice_json"]
        ),
    }
    if has_children:
        # 版本升级：新建 version+1 原件，parent_task_id 链回上一版；学生副本不动
        # （上面的截止变更/通知会随本次 commit 一并落库，保持原子性）
        new_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO learning_tasks
              (id, user_id, title, goal, data_type, scenario_id, cap_ids_json, source,
               status, steps_json, resources_json, rubric_json, practice_json,
               counts_toward_mastery, teacher_id, version, parent_task_id,
               created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'teacher', 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                current.user["id"],
                new_fields["title"],
                new_fields["goal"],
                new_fields["data_type"],
                new_fields["scenario_id"],
                new_fields["cap_ids_json"],
                new_fields["steps_json"],
                new_fields["resources_json"],
                new_fields["rubric_json"],
                new_fields["practice_json"],
                row["counts_toward_mastery"],
                current.user["id"],
                row["version"] + 1,
                task_id,
                current.user["id"],
                now,
                now,
            ),
        )
        conn.commit()
        audit(conn, current.user, "teacher_task.version_bump", target_type="learning_task",
              target_id=new_id, before={"version": row["version"]},
              after={"version": row["version"] + 1, "from": task_id})
        if due_change is not None:
            audit(conn, current.user, "teacher_task.due_change", target_type="learning_task",
                  target_id=task_id, before={"due_at": due_change["old"]},
                  after={"due_at": due_change["new"]})
        result = _teacher_task_dto(conn, _get_own_teacher_task(conn, new_id, current.user["id"]))
        result["version_bumped"] = True
        return result
    # 未发布任务：直接改原件；due_at 一并记下，作为后续发布时的默认截止时间
    if body.due_at is not None:
        new_fields["due_at"] = body.due_at
    assignments = ", ".join(f"{col} = ?" for col in new_fields)
    conn.execute(
        f"UPDATE learning_tasks SET {assignments}, updated_at = ? WHERE id = ?",
        (*new_fields.values(), utc_now_iso(), task_id),
    )
    conn.commit()
    result = _teacher_task_dto(conn, _get_own_teacher_task(conn, task_id, current.user["id"]))
    result["version_bumped"] = False
    return result


class PublishBody(BaseModel):
    class_id: str
    due_at: str | None = None
    counts_toward_mastery: bool = True


@router.post("/api/teacher/tasks/{task_id}/publish", status_code=201)
def publish_teacher_task(
    task_id: str,
    body: PublishBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """发布到班级：为每个在班学生复制一行任务（同事务），返回发布份数。"""
    _require_teacher_role(current)
    row = _get_own_teacher_task(conn, task_id, current.user["id"])
    _get_owned_class(conn, body.class_id, current.user["id"])
    student_ids = _class_student_ids(conn, [body.class_id])
    now = utc_now_iso()
    # 同事务批量复制：要么全班都有，要么都不发，不留半发布状态
    with transaction(conn):
        for sid in student_ids:
            conn.execute(
                """
                INSERT INTO learning_tasks
                  (id, user_id, title, goal, data_type, scenario_id, cap_ids_json, source,
                   status, steps_json, resources_json, rubric_json, practice_json,
                   counts_toward_mastery, teacher_id, class_id, due_at, version,
                   parent_task_id, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'teacher', 'not_started', ?, ?, ?, ?, ?, ?, ?, ?, 1,
                        ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    sid,
                    row["title"],
                    row["goal"],
                    row["data_type"],
                    row["scenario_id"],
                    row["cap_ids_json"],
                    row["steps_json"],
                    row["resources_json"],
                    row["rubric_json"],
                    row["practice_json"],
                    1 if body.counts_toward_mastery else 0,
                    current.user["id"],
                    body.class_id,
                    body.due_at,
                    task_id,
                    current.user["id"],
                    now,
                    now,
                ),
            )
        # 发布触达：每个在班学生一条站内通知（PRD-06 §10.1）；
        # 与任务副本同事务，不会出现"任务没发成却收到通知"的半截状态
        due_note = f"，截止时间 {body.due_at}" if body.due_at else ""
        notify_many(
            conn,
            student_ids,
            "task_published",
            row["title"],
            body=f"教师发布了新任务「{row['title']}」{due_note}，请到学习任务中查看",
            ref_type="task",
            ref_id=task_id,
        )
    audit(conn, current.user, "teacher_task.publish", target_type="learning_task",
          target_id=task_id,
          after={"class_id": body.class_id, "published": len(student_ids),
                 "due_at": body.due_at})
    return {"published": len(student_ids), "class_id": body.class_id}


# ---------------------------------------------------------------- Agent 任务卡生成（PRD-02 §5.3）

_DATA_TYPES = ("text", "image", "audio", "video")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")


class GenerateTaskBody(BaseModel):
    description: str
    scenario_id: str | None = None
    data_type: str | None = None


def _cjk_bigrams(text: str) -> set[str]:
    """CJK 字 bigram 特征。与 rag 混合召回同款思路，但教师域自留一份小实现，
    避免反向依赖 rag 模块的私有函数（跨域只走公开契约）。"""
    grams: set[str] = set()
    for run in _CJK_RUN_RE.findall(text or ""):
        if len(run) == 1:
            grams.add(run)
        else:
            grams.update(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def _cap_match_score(description: str, node: dict) -> float:
    """任务描述与能力节点（名称+描述）的 bigram 重合率，用于图谱定位排序。"""
    query = _cjk_bigrams(description)
    if not query:
        return 0.0
    hay = _cjk_bigrams(f"{node.get('name') or ''} {node.get('description') or ''}")
    return len(query & hay) / len(query)


def _draft_title(description: str) -> str:
    """从描述提炼标题：取首个句读之前的短句并截到 30 字（模板兜底，LLM 可再润色）。"""
    first = re.split(r"[，。；！？,.;!?\n]", description.strip(), maxsplit=1)[0].strip()
    return (first or description.strip())[:30]


def _locate_caps(
    conn: sqlite3.Connection,
    description: str,
    data_type: str | None,
    scenario_id: str | None,
    hits: list,
) -> list[str]:
    """能力节点定位（≤3）：召回资料声明的 cap 优先（自带证据链），图谱关键词
    重合度补充；图谱不可用时草稿仍按资料 cap 生成，不被内容文件拖垮。"""
    cap_ids: list[str] = []
    if hits:
        doc_ids = list(dict.fromkeys(h.document_id for h in hits))
        rows = conn.execute(
            f"SELECT cap_ids_json FROM rag_documents WHERE id IN ({_placeholders(doc_ids)})",
            doc_ids,
        ).fetchall()
        for r in rows:
            for cid in json.loads(r["cap_ids_json"] or "[]"):
                if cid not in cap_ids:
                    cap_ids.append(cid)
    try:
        from ..graphx import reason

        candidates = reason.search_nodes(
            node_type="CAP", data_type=data_type, scenario_id=scenario_id, limit=50
        )
    except Exception:
        candidates = []
    for node in sorted(candidates, key=lambda n: _cap_match_score(description, n), reverse=True):
        if len(cap_ids) >= 3:
            break
        if _cap_match_score(description, node) > 0 and node["id"] not in cap_ids:
            cap_ids.append(node["id"])
    if not cap_ids and candidates:
        # 既无资料命中也无关键词重合：取该数据类型/场景下的首个节点兜底，
        # 保证草稿满足"至少关联一个能力节点"的发布底线（PRD-02 §5.4），教师可改
        cap_ids.append(candidates[0]["id"])
    return cap_ids[:3]


@router.post("/api/teacher/tasks/generate")
def generate_teacher_task(
    body: GenerateTaskBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Agent 任务卡生成（PRD-02 §5.3 交互流的服务端）：识别→召回→定位→组装草稿。

    不落库（预览先行：教师编辑确认后才经 POST /api/teacher/tasks 正式创建，
    PRD-02 §5.4"发布前必须展示预览"）；LLM 可用时润色标题与步骤，未配置或
    失败一律回落模板组装，保证离线可用（PRD-06 §11.1）。
    """
    _require_teacher_role(current)
    description = body.description.strip()
    if not description:
        raise ApiError(400, "VALIDATION_ERROR", "任务描述不能为空")
    if body.data_type is not None and body.data_type not in _DATA_TYPES:
        raise ApiError(400, "VALIDATION_ERROR", "数据类型仅支持 text / image / audio / video")

    # 1) 意图识别：数据类型/场景（请求里的显式参数优先于识别结果）
    from ..agent import intents

    intent = intents.detect(description)
    data_type = body.data_type or intent.data_type
    scenario_id = body.scenario_id or intent.scenario_id

    # 2) RAG 召回规范/案例：仅已发布资料——任务卡最终面向学生，引用必须是
    #    学生可回流的出处（与 PRD-06 §4.4 学生召回边界同口径）
    from ..rag import retriever

    retrieval = retriever.retrieve(
        conn,
        get_config(),
        description,
        retriever.RagFilters(scenario_id=scenario_id, data_type=data_type, published_only=True),
    )
    # 低于阈值 = 知识库没有可靠依据：不给引用（不编造出处），草稿其余部分照常组装
    hits = [] if retrieval.below_threshold else retrieval.hits

    # 3) 图谱定位能力节点（≤3，带中文名）
    cap_ids = _locate_caps(conn, description, data_type, scenario_id, hits)
    names = _cap_names()

    # 4) 模板组装草稿（确定性，离线可用）
    title = _draft_title(description)
    norm_title = hits[0].title if hits else "相关标注规范"
    steps = [
        {"title": "学习规范", "description": f"通读《{norm_title}》，圈出与本次任务直接相关的条款"},
        {"title": "示范学习", "description": "对照示范样本逐条理解规范的应用方式，记录易错点"},
        {"title": "实操标注", "description": f"按规范独立完成「{title}」的标注实操"},
        {"title": "自检互检", "description": "按评分规则逐项自检并修正，提交前对照规范复核一遍"},
    ]
    resources = [
        {
            "type": "rag_document",
            "ref_id": hit.document_id,
            "title": hit.title,
            "citation": f"【{hit.title} {hit.section_title or ''} v{hit.version}】",
        }
        for hit in hits[:5]
    ]
    rubric = [
        {"criterion": "规范符合性", "description": "标注结果符合引用规范条款", "points": 40},
        {"criterion": "标注准确率", "description": "类别/边界/转写准确，错误率低", "points": 40},
        {"criterion": "质检通过率", "description": "自检发现并修正问题后再提交", "points": 20},
    ]
    # 难度/时长：PRD 未给公式。难度沿用预设路径的 1-4 整数口径，企业实战/综合
    # 类描述默认升一档；时长取一节课 60 分钟占位，教师发布前可改
    difficulty = 3 if any(kw in description for kw in ("实战", "综合", "复杂", "企业")) else 2
    est_minutes = 60

    # 5) LLM 可选润色：任何失败都静默回落上面的模板结果（PRD-06 §11.1）
    llm_used = False
    try:
        from ..agent import providers

        polished = asyncio.run(
            providers.complete(
                [
                    {
                        "role": "system",
                        "content": "你是职业院校数据标注课程的助教。根据教师的企业任务描述，"
                        "输出润色后的任务标题（不超过30字）和4条学习步骤的标题。"
                        "共5行，每行一条，不要编号，不要解释。",
                    },
                    {"role": "user", "content": description},
                ]
            )
        )
        if polished and polished.get("text"):
            lines = [ln.strip() for ln in polished["text"].splitlines() if ln.strip()]
            if lines:
                title = lines[0][:30]
                for step, line in zip(steps, lines[1:5]):
                    step["title"] = line[:20]
                llm_used = True
    except Exception:
        llm_used = False

    # 6) 埋点（惰性加载 telemetry，失败不阻断生成）
    try:
        from ..telemetry import emit_event

        emit_event(
            conn,
            current.user["id"],
            "task_preview_created",
            {
                "source": "teacher_generate",
                "data_type": data_type,
                "scenario_id": scenario_id,
                "cap_count": len(cap_ids),
                "llm_used": llm_used,
            },
        )
    except Exception:
        pass

    citations = [
        {
            "document_id": hit.document_id,
            "title": hit.title,
            "section_title": hit.section_title,
            "page_start": hit.page_start,
            "page_end": hit.page_end,
            "version": hit.version,
            "score": hit.score,
        }
        for hit in hits[:5]
    ]
    if hits:
        sources_note = f"已引用 {len(resources)} 份已发布知识库资料，发布前请核对引用条款是否适用"
    else:
        sources_note = "知识库暂无可靠命中的已发布资料，草稿按图谱能力生成；发布前请补充至少一份来源资料"
    return {
        "title": title,
        "goal": f"完成「{title}」对应的标注任务，掌握相关规范要点并达到质检要求",
        "data_type": data_type,
        "scenario_id": scenario_id,
        "cap_ids": cap_ids,
        "caps": [{"cap_id": cid, "cap_name": names.get(cid, cid)} for cid in cap_ids],
        "steps": steps,
        "resources": resources,
        "citations": citations,
        "rubric": rubric,
        "difficulty": difficulty,
        "est_minutes": est_minutes,
        "sources_note": sources_note,
        "llm_used": llm_used,
        "notice": retrieval.notice,
    }


# ---------------------------------------------------------------- 学情分析


@router.get("/api/teacher/analytics")
def analytics(
    class_id: str | None = None,
    data_type: str | None = None,
    scenario_id: str | None = None,
    source: str | None = None,
    range: str = "30d",
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学情分析：热力图/趋势/高频错误/场景对比/干预建议（全部来自真实数据）。"""
    teacher_id = current.user["id"]
    if class_id:
        _get_owned_class(conn, class_id, teacher_id)
        class_ids = [class_id]
    else:
        class_ids = _owned_class_ids(conn, teacher_id)
    student_ids = _class_student_ids(conn, class_ids)
    names = _cap_names()

    since: str | None = None
    if range == "7d":
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif range == "30d":
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    # range='term' 不限时间（本学期数据全量）

    # ---- 热力图：按 cap 聚合平均掌握度与薄弱人数 ----
    heatmap: list[dict] = []
    if student_ids:
        clauses = [f"user_id IN ({_placeholders(student_ids)})"]
        params: list[Any] = list(student_ids)
        if scenario_id:
            clauses.append("scenario_id = ?")
            params.append(scenario_id)
        else:
            clauses.append("scenario_id = ''")  # 默认看通用视图（§8.4）
        rows = conn.execute(
            f"SELECT cap_id, AVG(score) AS avg_score, "
            f"SUM(CASE WHEN score < ? THEN 1 ELSE 0 END) AS weak_count, COUNT(*) AS n "
            f"FROM mastery WHERE {' AND '.join(clauses)} GROUP BY cap_id "
            f"ORDER BY avg_score ASC",
            # SQL 里第一个 ? 是 SELECT 区的薄弱线，绑定顺序必须在 WHERE 参数之前
            (WEAK_LINE, *params),
        ).fetchall()
        # 数据类型过滤：cap 的 data_types 命中才算（图谱缺席时跳过该过滤）
        allowed_caps: set[str] | None = None
        if data_type:
            try:
                from ..graphx import reason

                allowed_caps = {
                    n["id"]
                    for n in reason.get_graph()["nodes"]
                    if n.get("type") == "CAP" and data_type in (n.get("data_types") or [])
                }
            except Exception:
                allowed_caps = None
        for r in rows:
            if allowed_caps is not None and r["cap_id"] not in allowed_caps:
                continue
            heatmap.append(
                {
                    "cap_id": r["cap_id"],
                    "cap_name": names.get(r["cap_id"], r["cap_id"]),
                    "avg_score": float(r["avg_score"]),
                    "weak_count": r["weak_count"],
                    "student_count": r["n"],
                }
            )

    # ---- 趋势：提交数（task_attempts）与完成数（learning_tasks）按日聚合 ----
    trend: list[dict] = []
    if student_ids:
        task_filters = f"t.user_id IN ({_placeholders(student_ids)})"
        task_params: list[Any] = list(student_ids)
        if source:
            task_filters += " AND t.source = ?"
            task_params.append(source)
        if data_type:
            task_filters += " AND t.data_type = ?"
            task_params.append(data_type)
        if scenario_id:
            task_filters += " AND t.scenario_id = ?"
            task_params.append(scenario_id)
        sub_rows = conn.execute(
            f"SELECT substr(a.created_at, 1, 10) AS day, COUNT(*) AS n "
            f"FROM task_attempts a JOIN learning_tasks t ON t.id = a.task_id "
            f"WHERE {task_filters}" + (" AND a.created_at >= ?" if since else "")
            + " GROUP BY day",
            (*task_params, since) if since else task_params,
        ).fetchall()
        done_rows = conn.execute(
            f"SELECT substr(updated_at, 1, 10) AS day, COUNT(*) AS n FROM learning_tasks t "
            f"WHERE {task_filters} AND t.status = 'completed'"
            + (" AND t.updated_at >= ?" if since else "")
            + " GROUP BY day",
            (*task_params, since) if since else task_params,
        ).fetchall()
        by_day: dict[str, dict] = {}
        for r in sub_rows:
            by_day.setdefault(r["day"], {"date": r["day"], "submissions": 0, "completions": 0})[
                "submissions"
            ] = r["n"]
        for r in done_rows:
            by_day.setdefault(r["day"], {"date": r["day"], "submissions": 0, "completions": 0})[
                "completions"
            ] = r["n"]
        trend = [by_day[d] for d in sorted(by_day)]

    # ---- 高频错误：聚合诊断摘要报告里的 error_type ----
    top_errors: list[dict] = []
    if student_ids:
        diag_clauses = [f"user_id IN ({_placeholders(student_ids)})"]
        diag_params: list[Any] = list(student_ids)
        if scenario_id:
            diag_clauses.append("scenario_id = ?")
            diag_params.append(scenario_id)
        if data_type:
            diag_clauses.append("data_type = ?")
            diag_params.append(data_type)
        if since:
            diag_clauses.append("created_at >= ?")
            diag_params.append(since)
        diag_rows = conn.execute(
            f"SELECT report_json FROM diagnostic_summaries WHERE {' AND '.join(diag_clauses)}",
            diag_params,
        ).fetchall()
        counter: dict[str, dict] = {}
        for r in diag_rows:
            try:
                report = json.loads(r["report_json"])
            except json.JSONDecodeError:
                continue
            for err in report.get("errors", []):
                slot = counter.setdefault(
                    err.get("error_type", "unknown"),
                    {"error_type": err.get("error_type", "unknown"), "count": 0, "major": 0, "minor": 0},
                )
                slot["count"] += 1
                slot["major" if err.get("severity") == "major" else "minor"] += 1
        top_errors = sorted(counter.values(), key=lambda x: (-x["count"], x["error_type"]))[:5]

    # ---- 场景掌握度对比 ----
    scenario_comparison: list[dict] = []
    if student_ids:
        rows = conn.execute(
            f"SELECT scenario_id, AVG(score) AS avg_score, COUNT(*) AS n FROM mastery "
            f"WHERE user_id IN ({_placeholders(student_ids)}) GROUP BY scenario_id "
            f"ORDER BY avg_score ASC",
            student_ids,
        ).fetchall()
        scn_names: dict[str, str] = {}
        try:
            from ..graphx import reason

            scn_names = {
                n["id"]: n.get("name") or n["id"]
                for n in reason.get_graph()["nodes"]
                if n.get("type") == "SCN"
            }
        except Exception:
            pass
        scenario_comparison = [
            {
                "scenario_id": r["scenario_id"],
                "scenario_name": (
                    "通用" if r["scenario_id"] == "" else scn_names.get(r["scenario_id"], r["scenario_id"])
                ),
                "avg_score": float(r["avg_score"]),
                "student_count": r["n"],
            }
            for r in rows
        ]

    # ---- 干预建议：规则化生成，只引用上面算出的真实数字（PRD-02 §6.3）----
    suggestions: list[str] = []
    for item in heatmap[:3]:
        if item["avg_score"] < WEAK_LINE:
            suggestions.append(
                f"班级在「{item['cap_name']}」上的平均掌握度仅 {item['avg_score']:.2f}"
                f"（{item['weak_count']} 人薄弱），建议安排专项纠错练习"
            )
    total_done = sum(d["completions"] for d in trend)
    total_subs = sum(d["submissions"] for d in trend)
    if total_subs and total_done / total_subs < 0.5:
        suggestions.append(
            f"统计期内任务完成率偏低（提交 {total_subs} 次、完成 {total_done} 项），"
            "建议跟进未完成学生并调整任务节奏"
        )
    if top_errors:
        try:
            from ..diagnosis.rules import RULE_NAMES

            top = top_errors[0]
            suggestions.append(
                f"高频错误「{RULE_NAMES.get(top['error_type'], top['error_type'])}」"
                f"出现 {top['count']} 次，建议课堂上集中讲解对应规范"
            )
        except Exception:
            pass
    if not suggestions and student_ids:
        suggestions.append("当前数据未发现明显短板，可按计划推进后续教学内容")

    return {
        "heatmap": heatmap,
        "trend": trend,
        "top_errors": top_errors,
        "scenario_comparison": scenario_comparison,
        "suggestions": suggestions,
        "student_count": len(student_ids),
        "sample_warning": len(student_ids) < MIN_SAMPLE,
    }


@router.get("/api/teacher/analytics/students/{student_id}")
def student_analytics_detail(
    student_id: str,
    class_id: str = Query(...),
    current: CurrentUser = Depends(require_role(*TEACHER_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生个人能力地图（PRD-02 §6 逐学生明细）：掌握度 + 任务 + 掌握度事件趋势。

    诊断明细遵循 PRD-06 §15 #2：学生未授权时只回 note 不回数据（教师侧
    仍可用本接口的聚合学习数据）。class_id 必传——教师的数据权限以班级
    为边界，离开班级语境谈"某学生"没有意义。
    """
    _get_owned_class(conn, class_id, current.user["id"])
    _get_enrolled_student(conn, class_id, student_id)
    names = _cap_names()

    mastery_rows = conn.execute(
        "SELECT * FROM mastery WHERE user_id = ? ORDER BY cap_id, scenario_id",
        (student_id,),
    ).fetchall()
    mastery = [
        {
            "cap_id": r["cap_id"],
            "cap_name": names.get(r["cap_id"], r["cap_id"]),
            "scenario_id": r["scenario_id"],  # '' = 通用掌握度（蓝图 §5 口径）
            "score": float(r["score"]),
            "updated_at": r["updated_at"],
        }
        for r in mastery_rows
    ]

    # 最近 20 条任务；分数取该任务最近一次提交的得分（task_attempts）
    task_rows = conn.execute(
        """
        SELECT t.id, t.title, t.status, t.source, t.updated_at,
               (SELECT a.score FROM task_attempts a WHERE a.task_id = t.id
                ORDER BY a.created_at DESC LIMIT 1) AS score
        FROM learning_tasks t WHERE t.user_id = ?
        ORDER BY t.updated_at DESC, t.id DESC LIMIT 20
        """,
        (student_id,),
    ).fetchall()
    tasks = [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "source": r["source"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "updated_at": r["updated_at"],
        }
        for r in task_rows
    ]

    # 掌握度事件趋势（最近 30 条，新→旧，前端自行反转画折线）
    event_rows = conn.execute(
        "SELECT * FROM mastery_events WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 30",
        (student_id,),
    ).fetchall()
    mastery_events = [
        {
            "cap_id": r["cap_id"],
            "scenario_id": r["scenario_id"],
            "old_score": float(r["old_score"]),
            "new_score": float(r["new_score"]),
            "source": r["source"],
            "created_at": r["created_at"],
        }
        for r in event_rows
    ]

    if _share_diagnostics_enabled(conn, student_id):
        diagnostics: list[dict] | None = _diagnostic_summary_items(conn, student_id)
        diagnostics_note = None
    else:
        diagnostics = None
        diagnostics_note = "学生未授权教师查看诊断详情，此处仅展示聚合学习数据（PRD-06 §10.2）"

    return {
        "student_id": student_id,
        "class_id": class_id,
        "mastery": mastery,
        "tasks": tasks,
        "diagnostics": diagnostics,
        "diagnostics_note": diagnostics_note,
        "mastery_events": mastery_events,
    }
