"""学习任务路由（蓝图 §6.3，PRD-06 §8 状态机/来源口径）。

状态机（PRD-06 §8.1）：
  draft --confirm_create--> not_started --start--> in_progress --submit--> submitted
  in_progress --pause--> paused --start/resume--> in_progress
  submitted --grade(apply-mastery)--> completed；任意非归档态 --archive--> archived

关键决策（为什么）：
- 评分确定性：rubric 逐项比对（数值容差/归一化字符串相等），无 rubric 时
  退化为"非空答案比例"完整性分——打分绝不能调 LLM（P0 可信口径，蓝图 §10.6）。
- submit 只给 mastery_preview 不落库，apply-mastery 才写 mastery
  （学生确认的确认门口径，PRD-06 §8.3）；apply 按 attempt 幂等
  （mastery_applied 标记），重复调用不重复加分。
- 属主隔离用 404 而非 403：不暴露他人任务的存在性。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db, require_student_portal_user
from ..errors import ApiError
from ..mastery import service as mastery_service

# Student-owned task state must enforce the same boundary as the student shell,
# rather than relying only on the client-side route guard.
router = APIRouter(dependencies=[Depends(require_student_portal_user)])

# 状态机合法迁移表（动作 → (源状态集, 目标状态)）
_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "confirm_create": ({"draft"}, "not_started"),
    "start": ({"not_started", "paused"}, "in_progress"),
    "pause": ({"in_progress"}, "paused"),
    "submit": ({"in_progress", "submitted"}, "submitted"),  # 重复提交按最新有效（§8.3）
    "grade": ({"submitted"}, "completed"),
    "archive": (
        {"draft", "not_started", "in_progress", "paused", "submitted", "completed"},
        "archived",
    ),
}

# 列表进度映射：任务没有步骤级完成记录（P1 才做），MVP 按状态给确定性进度值
_PROGRESS_BY_STATUS = {
    "draft": 0.0,
    "not_started": 0.0,
    "in_progress": 0.5,
    "paused": 0.5,
    "submitted": 0.9,
    "completed": 1.0,
    "archived": 1.0,
}

# 学生手动创建可选的来源值（'teacher' 只能由教师发布流程产生）
_MANUAL_SOURCES = {"agent", "preset", "diagnostic"}


# ---------------------------------------------------------------- 通用小工具


def _track(conn: sqlite3.Connection, user_id: str | None, name: str, props: dict) -> None:
    """埋点（telemetry 缺席兜底直写 analytics_events；失败吞掉，见 diagnostics 同名函数）。"""
    try:
        try:
            from .. import telemetry  # type: ignore

            track = (
                getattr(telemetry, "emit_event", None)
                or getattr(telemetry, "track", None)
                or getattr(telemetry, "track_event", None)
            )
            if track is not None:
                # emit_event(db, user_id, name, props) 为 B1 当前接口；全位置参数调用
                track(conn, user_id, name, props)
                return
        except ImportError:
            pass
        conn.execute(
            "INSERT INTO analytics_events (user_id, event_name, props_json, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, json.dumps(props, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    except Exception:
        pass


def _cap_names() -> dict[str, str]:
    """cap_id → 中文名（graphx 缺席降级空映射，任务接口不被图谱内容拖垮）。"""
    try:
        from ..graphx import reason

        return {
            n["id"]: n.get("name") or n["id"]
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "CAP"
        }
    except Exception:
        return {}


def _get_own_task(conn: sqlite3.Connection, task_id: str, user_id: str) -> sqlite3.Row:
    """取本人任务；不存在或不是本人的统一 404（不暴露存在性）。"""
    row = conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None or row["user_id"] != user_id:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
    return row


def _do_transition(row: sqlite3.Row, action: str) -> str:
    """校验状态机迁移并返回目标状态；非法迁移 409（PRD-06 §8.1）。"""
    sources, target = _TRANSITIONS[action]
    if row["status"] not in sources:
        raise ApiError(
            409,
            "TASK_STATE_INVALID",
            f"当前任务状态（{row['status']}）不允许该操作，请刷新后重试",
        )
    return target


def _task_json(row: sqlite3.Row, key: str, default: Any) -> Any:
    raw = row[key]
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _latest_score(conn: sqlite3.Connection, task_id: str) -> float | None:
    row = conn.execute(
        "SELECT score FROM task_attempts WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return float(row["score"]) if row and row["score"] is not None else None


def _task_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """列表项 DTO：任务行 + 进度 + 最近得分。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "goal": row["goal"],
        "data_type": row["data_type"],
        "scenario_id": row["scenario_id"],
        "cap_ids": _task_json(row, "cap_ids_json", []),
        "source": row["source"],
        "status": row["status"],
        "progress": _PROGRESS_BY_STATUS.get(row["status"], 0.0),
        "latest_score": _latest_score(conn, row["id"]),
        "counts_toward_mastery": bool(row["counts_toward_mastery"]),
        "due_at": row["due_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------- 评分


_WS_RE = re.compile(r"\s+")


def _answers_to_dict(answers: Any) -> dict[str, Any]:
    """answers 允许 dict 或 [{key,value}] 列表两种形态，统一成 dict。"""
    if isinstance(answers, dict):
        return answers
    if isinstance(answers, list):
        result: dict[str, Any] = {}
        for item in answers:
            if isinstance(item, dict) and "key" in item:
                result[str(item["key"])] = item.get("value")
        return result
    return {}


def _matches(expected: Any, got: Any) -> bool:
    """判定单个答案：数值容差（1% 相对误差）优先，否则归一化字符串相等。"""
    if got is None:
        return False
    try:
        exp_f = float(expected)
        got_f = float(got)
        return abs(exp_f - got_f) <= max(1e-6, 0.01 * abs(exp_f))
    except (TypeError, ValueError):
        pass
    norm = lambda v: _WS_RE.sub(" ", str(v)).strip().casefold()  # noqa: E731
    return norm(expected) == norm(got)


def _score_submission(task_row: sqlite3.Row, answers: dict[str, Any]) -> tuple[float, list[dict]]:
    """确定性评分，返回 (score, feedback)。

    有 rubric（[{key,expected,weight,hint?}]）按权重加权；无 rubric 退化为
    完整性分 = 非空答案数 / 期望键数（期望键取 practice_json 的 answers/
    expected 字段，都没有则以提交键为全集，即"有答即有分"的下限口径）。
    """
    rubric = _task_json(task_row, "rubric_json", None)
    if rubric:
        total_weight = 0.0
        earned = 0.0
        feedback: list[dict] = []
        for item in rubric:
            key = str(item.get("key"))
            expected = item.get("expected")
            weight = float(item.get("weight", 1.0))
            got = answers.get(key)
            ok = _matches(expected, got)
            total_weight += weight
            earned += weight if ok else 0.0
            feedback.append(
                {
                    "key": key,
                    "expected": expected,
                    "got": got,
                    "ok": ok,
                    # hint 是给答错者的指引，答对时不应把"纠错提示"塞回去
                    "hint": "回答正确" if ok else (item.get("hint") or "请对照期望值检查该项"),
                }
            )
        score = earned / total_weight if total_weight > 0 else 0.0
        return round(score, 6), feedback

    # 无 rubric：完整性分（口径见 docstring）
    practice = _task_json(task_row, "practice_json", {}) or {}
    expected_keys: list[str] = []
    for field in ("answers", "expected"):
        if isinstance(practice.get(field), dict):
            expected_keys = [str(k) for k in practice[field]]
            break
    keys = expected_keys or list(answers.keys())
    if not keys:
        return 0.0, []
    feedback = []
    filled = 0
    for key in keys:
        got = answers.get(key)
        ok = got is not None and str(got).strip() != ""
        filled += 1 if ok else 0
        feedback.append(
            {
                "key": key,
                "expected": None,
                "got": got,
                "ok": ok,
                "hint": "已作答" if ok else "该项未作答",
            }
        )
    return round(filled / len(keys), 6), feedback


# ---------------------------------------------------------------- 请求体


class TaskCreateBody(BaseModel):
    title: str
    goal: str | None = None
    data_type: str | None = None
    scenario_id: str | None = None
    cap_ids: list[str] = []
    steps: list[dict] = []
    resources: list[dict] = []
    source: str | None = None  # 缺省 'agent'（学生手动建任务视同 Agent 直出）


class TaskPatchBody(BaseModel):
    title: str | None = None
    goal: str | None = None
    steps: list[dict] | None = None
    status: str | None = None  # 仅接受目标状态：paused / in_progress / not_started


class SubmitBody(BaseModel):
    answers: dict[str, Any] | list[dict[str, Any]]


class ApplyMasteryBody(BaseModel):
    attempt_id: str


class BatchBody(BaseModel):
    ids: list[str]
    action: str  # 目前仅支持 'archive'（PRD-01 §6.1 批量操作）


# ---------------------------------------------------------------- 端点


@router.get("/api/tasks")
def list_tasks(
    status: str | None = None,
    source: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """本人任务列表（状态/来源筛选；默认不含已归档，显式 status=archived 可见）。"""
    clauses = ["user_id = ?"]
    params: list[Any] = [current.user["id"]]
    if status:
        clauses.append("status = ?")
        params.append(status)
    else:
        clauses.append("status != 'archived'")
    if source:
        clauses.append("source = ?")
        params.append(source)
    rows = conn.execute(
        f"SELECT * FROM learning_tasks WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, id DESC",
        params,
    ).fetchall()
    return {"items": [_task_summary(conn, row) for row in rows], "total": len(rows)}


@router.post("/api/tasks", status_code=201)
def create_task(
    body: TaskCreateBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生手动创建任务（status=not_started；source 缺省 'agent'，见 §8.2 来源口径）。"""
    if not body.title.strip():
        raise ApiError(400, "VALIDATION_ERROR", "任务标题不能为空")
    source = body.source or "agent"
    if source not in _MANUAL_SOURCES:
        raise ApiError(400, "SOURCE_INVALID", "任务来源只能是 agent / preset / diagnostic")
    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, goal, data_type, scenario_id, cap_ids_json, source,
           status, steps_json, resources_json, counts_toward_mastery, created_by,
           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?, 1, ?, ?, ?)
        """,
        (
            task_id,
            current.user["id"],
            body.title.strip(),
            body.goal,
            body.data_type,
            body.scenario_id,
            json.dumps(body.cap_ids, ensure_ascii=False),
            source,
            json.dumps(body.steps, ensure_ascii=False),
            json.dumps(body.resources, ensure_ascii=False),
            current.user["id"],
            now,
            now,
        ),
    )
    conn.commit()
    _track(conn, current.user["id"], "task_created", {"task_id": task_id, "source": source})
    row = _get_own_task(conn, task_id, current.user["id"])
    return _task_summary(conn, row)


@router.get("/api/tasks/{task_id}")
def task_detail(
    task_id: str,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """任务详情：步骤/资源/评分规则/练习 + 能力中文名 + 图谱关联节点。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    cap_ids = _task_json(row, "cap_ids_json", [])
    names = _cap_names()
    caps = [{"cap_id": cid, "cap_name": names.get(cid, cid)} for cid in cap_ids]
    # 图谱关联（证书/知识/相关资源）：逐 cap 取 node_detail，失败容忍为空
    linked: dict[str, list[dict]] = {"certificates": [], "knowledge": [], "graph_resources": []}
    try:
        from ..graphx import reason

        seen: dict[str, set[str]] = {k: set() for k in linked}
        for cid in cap_ids:
            detail = reason.node_detail(cid) or {}
            for key, node_key in (
                ("certificates", "certificates"),
                ("knowledge", "knowledge"),
                ("graph_resources", "resources"),
            ):
                for node in detail.get(node_key, []):
                    if node["id"] not in seen[key]:
                        seen[key].add(node["id"])
                        linked[key].append({"id": node["id"], "name": node.get("name")})
    except Exception:
        pass
    attempts = conn.execute(
        "SELECT id, attempt_number, score, mastery_applied, created_at FROM task_attempts "
        "WHERE task_id = ? ORDER BY attempt_number DESC",
        (task_id,),
    ).fetchall()
    return {
        **_task_summary(conn, row),
        "steps": _task_json(row, "steps_json", []),
        "resources": _task_json(row, "resources_json", []),
        "rubric": _task_json(row, "rubric_json", None),
        "practice": _task_json(row, "practice_json", None),
        "caps": caps,
        "linked": linked,
        "teacher_id": row["teacher_id"],
        "class_id": row["class_id"],
        "version": row["version"],
        "parent_task_id": row["parent_task_id"],
        "attempts": [dict(a) for a in attempts],
    }


@router.patch("/api/tasks/{task_id}")
def patch_task(
    task_id: str,
    body: TaskPatchBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """编辑标题/目标/步骤，或做 pause/resume/confirm 状态迁移（非法迁移 409）。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    updates: dict[str, Any] = {}
    if body.title is not None:
        if not body.title.strip():
            raise ApiError(400, "VALIDATION_ERROR", "任务标题不能为空")
        updates["title"] = body.title.strip()
    if body.goal is not None:
        updates["goal"] = body.goal
    if body.steps is not None:
        # 已完成/已归档的任务内容定型，只允许查看（历史记录可信度）
        if row["status"] in ("completed", "archived"):
            raise ApiError(409, "TASK_STATE_INVALID", "已完成或已归档的任务不能再编辑内容")
        updates["steps_json"] = json.dumps(body.steps, ensure_ascii=False)
    new_status: str | None = None
    if body.status is not None:
        action_by_target = {
            "paused": "pause",
            "in_progress": "start",
            "not_started": "confirm_create",
        }
        action = action_by_target.get(body.status)
        if action is None:
            raise ApiError(
                409, "TASK_STATE_INVALID", "该状态变更不允许，请使用对应的操作端点"
            )
        new_status = _do_transition(row, action)
        updates["status"] = new_status
    if not updates:
        raise ApiError(400, "VALIDATION_ERROR", "没有需要修改的字段")
    updates["updated_at"] = utc_now_iso()
    assignments = ", ".join(f"{col} = ?" for col in updates)
    conn.execute(
        f"UPDATE learning_tasks SET {assignments} WHERE id = ?",
        (*updates.values(), task_id),
    )
    conn.commit()
    return _task_summary(conn, _get_own_task(conn, task_id, current.user["id"]))


@router.post("/api/tasks/{task_id}/start")
def start_task(
    task_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """not_started/paused → in_progress（开始或继续任务）。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    new_status = _do_transition(row, "start")
    conn.execute(
        "UPDATE learning_tasks SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, utc_now_iso(), task_id),
    )
    conn.commit()
    return _task_summary(conn, _get_own_task(conn, task_id, current.user["id"]))


@router.post("/api/tasks/{task_id}/submit")
def submit_task(
    task_id: str,
    body: SubmitBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """提交答案 → 确定性评分 + mastery_preview（不落掌握度，等 apply-mastery 确认）。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    new_status = _do_transition(row, "submit")
    answers = _answers_to_dict(body.answers)
    score, feedback = _score_submission(row, answers)
    last = conn.execute(
        "SELECT MAX(attempt_number) AS n FROM task_attempts WHERE task_id = ?", (task_id,)
    ).fetchone()["n"]
    attempt_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO task_attempts
          (id, task_id, user_id, attempt_number, submission_json, score, feedback_json,
           mastery_applied, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            attempt_id,
            task_id,
            current.user["id"],
            (last or 0) + 1,
            json.dumps(answers, ensure_ascii=False),
            score,
            json.dumps(feedback, ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    conn.execute(
        "UPDATE learning_tasks SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, utc_now_iso(), task_id),
    )
    conn.commit()

    # 掌握度预览：仅当任务计入掌握度且挂了能力节点；公式来自 mastery 单点
    cap_ids = _task_json(row, "cap_ids_json", [])
    mastery_preview: list[dict] = []
    if row["counts_toward_mastery"] and cap_ids:
        delta = mastery_service.exercise_delta(score)
        scenario_id = row["scenario_id"] or ""
        mastery_preview = mastery_service.preview_from_deltas(
            conn,
            current.user["id"],
            [
                {"cap_id": cid, "scenario_id": scenario_id, "delta": delta}
                for cid in cap_ids
            ],
        )
    return {
        "attempt_id": attempt_id,
        "score": score,
        "feedback": feedback,
        "mastery_preview": mastery_preview,
        "status": new_status,
    }


@router.post("/api/tasks/{task_id}/apply-mastery")
def apply_mastery(
    task_id: str,
    body: ApplyMasteryBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生确认后把某次提交的掌握度变化落库（按 attempt 幂等）。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    attempt = conn.execute(
        "SELECT * FROM task_attempts WHERE id = ? AND task_id = ? AND user_id = ?",
        (body.attempt_id, task_id, current.user["id"]),
    ).fetchone()
    if attempt is None:
        raise ApiError(404, "ATTEMPT_NOT_FOUND", "提交记录不存在")
    if attempt["mastery_applied"]:
        # 幂等重放：不重复加分，如实告知已应用过
        return {"applied": [], "already_applied": True, "status": row["status"]}
    if row["status"] != "submitted":
        raise ApiError(
            409, "TASK_STATE_INVALID", "只有已提交的任务才能确认掌握度变化"
        )

    applied: list[dict] = []
    cap_ids = _task_json(row, "cap_ids_json", [])
    if row["counts_toward_mastery"] and cap_ids and attempt["score"] is not None:
        delta = mastery_service.exercise_delta(float(attempt["score"]))
        scenario_id = row["scenario_id"] or ""
        applied = mastery_service.apply_updates(
            conn,
            current.user["id"],
            [
                {"cap_id": cid, "scenario_id": scenario_id, "delta": delta}
                for cid in cap_ids
            ],
            source="exercise",
            ref_id=attempt["id"],
        )
    new_status = _do_transition(row, "grade")
    conn.execute("UPDATE task_attempts SET mastery_applied = 1 WHERE id = ?", (attempt["id"],))
    conn.execute(
        "UPDATE learning_tasks SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, utc_now_iso(), task_id),
    )
    conn.commit()
    if applied:
        _track(
            conn,
            current.user["id"],
            "mastery_updated",
            {"source": "exercise", "cap_count": len(applied)},
        )
    return {"applied": applied, "already_applied": False, "status": new_status}


@router.post("/api/tasks/batch")
def batch_tasks(
    body: BatchBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """批量操作（PRD-01 §6.1，当前支持 archive）：逐条执行并回报每项结果。

    为什么逐条部分成功而不是全成或全败：批量入口的典型场景是"勾一堆旧任务
    清理列表"，其中混入一条已归档/已删除的任务不该让其余 49 条失败回滚。
    属主隔离同单个端点——他人任务按"不存在"处理，不暴露存在性；
    教师来源任务同样允许归档（PRD-06 §8.2：教师任务只能归档不能删）。
    """
    if body.action != "archive":
        raise ApiError(400, "BATCH_ACTION_INVALID", "暂不支持该批量操作，目前仅支持 archive（归档）")
    if not body.ids:
        raise ApiError(400, "VALIDATION_ERROR", "请选择要操作的任务")
    if len(body.ids) > 100:
        raise ApiError(400, "VALIDATION_ERROR", "单次批量操作最多 100 条任务")

    results: list[dict] = []
    succeeded = 0
    for task_id in body.ids:
        row = conn.execute(
            "SELECT * FROM learning_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None or row["user_id"] != current.user["id"]:
            results.append({"id": task_id, "ok": False, "message": "任务不存在或无权限操作"})
            continue
        if row["status"] == "archived":
            # 幂等：已归档视为成功，与单个归档端点口径一致
            results.append({"id": task_id, "ok": True, "message": "任务已归档，无需重复操作"})
            succeeded += 1
            continue
        conn.execute(
            "UPDATE learning_tasks SET status = 'archived', archived_at = ?, updated_at = ?"
            " WHERE id = ?",
            (utc_now_iso(), utc_now_iso(), task_id),
        )
        results.append({"id": task_id, "ok": True, "message": "已归档"})
        succeeded += 1
    conn.commit()
    return {
        "action": body.action,
        "results": results,
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
    }


@router.post("/api/tasks/{task_id}/archive")
def archive_task(
    task_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """软归档（archived_at + status）；教师任务同样只能归档不能删（PRD-06 §8.2）。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    if row["status"] == "archived":
        # 幂等：重复归档直接返回当前态
        return _task_summary(conn, row)
    new_status = _do_transition(row, "archive")
    conn.execute(
        "UPDATE learning_tasks SET status = ?, archived_at = ?, updated_at = ? WHERE id = ?",
        (new_status, utc_now_iso(), utc_now_iso(), task_id),
    )
    conn.commit()
    return _task_summary(conn, _get_own_task(conn, task_id, current.user["id"]))
