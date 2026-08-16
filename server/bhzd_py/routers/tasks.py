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
import asyncio
import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db, require_student_portal_user
from ..errors import ApiError
from ..mastery import service as mastery_service

logger = logging.getLogger(__name__)

# Keep references to detached grading workers until they finish.  Without this
# set an event loop is allowed to garbage-collect a task before it writes its
# terminal status, leaving a submission stuck at ``grading``.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

def _task_portal_boundary(
    request: Request,
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Keep learner routes student-scoped while allowing the internal grader hook.

    The router-level dependency is intentional: it prevents a teacher session
    from reaching student task state even when the SPA guard is bypassed. The
    one exception is the internal grading trigger, which is explicitly limited
    to administrator roles and still performs its own status validation.
    """

    if request.url.path == "/api/internal/grade-submission":
        if current.user["role"] in {"system_admin", "content_admin"}:
            return current
        raise ApiError(403, "FORBIDDEN", "无权执行内部评阅")
    return require_student_portal_user(current)


# Student-owned task state must enforce the same boundary as the student shell,
# rather than relying only on the client-side route guard.
router = APIRouter(dependencies=[Depends(_task_portal_boundary)])

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
    return _json_value(row[key], default)


def _json_value(raw: Any, default: Any) -> Any:
    """安全解析持久化 JSON；旧数据异常时保留接口可用而非让详情页白屏。"""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _student_rubric(rubric: Any) -> list[dict[str, Any]] | None:
    """构造学生可见评分项，永不把内部答案键随任务详情返回。

    评分仍使用数据库中的完整 rubric；此 DTO 仅保留出题和学习引导所需字段。
    对早期错误保存的对象形 rubric 返回空列表，避免前端把对象当列表遍历。
    """
    if rubric is None:
        return None
    if not isinstance(rubric, list):
        return []

    visible: list[dict[str, Any]] = []
    for item in rubric:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key is None or not str(key).strip():
            continue
        public_item: dict[str, Any] = {"key": str(key)}
        if item.get("hint") is not None:
            public_item["hint"] = str(item["hint"])
        try:
            public_item["weight"] = float(item.get("weight", 1.0))
        except (TypeError, ValueError):
            # 权重只是学生端的展示信息，异常值不应使任务详情不可读。
            pass
        visible.append(public_item)
    return visible


# practice_json may also hold scoring fixtures for completeness scoring. Those
# names must not cross the student detail boundary, including inside raw sample
# objects that the page renders as JSON.
_PRACTICE_ANSWER_KEYS = {
    "answer",
    "answers",
    "answerkey",
    "correctanswer",
    "expected",
    "expectedanswer",
    "groundtruth",
    "referenceanswer",
    "solution",
    "solutions",
}

# Keep one canonical set of learner-facing question kinds.  Legacy practice
# rows may contain aliases, so normalization happens at the API boundary while
# the stored scoring fixture remains untouched for historical attempts.
_EXERCISE_TYPES = {"open_ended", "multiple_choice", "true_false"}


def _exercise_type(value: Any) -> str:
    """Normalize authored question types without leaking answer metadata."""

    normalized = str(value or "open_ended").strip().casefold().replace("-", "_")
    aliases = {
        "boolean": "true_false",
        "truefalse": "true_false",
        "判断": "true_false",
        "判断题": "true_false",
        "choice": "multiple_choice",
        "single_choice": "multiple_choice",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _EXERCISE_TYPES else "open_ended"


def _is_practice_answer_key(key: Any) -> bool:
    """Recognize common answer-key spellings despite case, spacing, or separators."""
    normalized = re.sub(r"[\s_-]+", "", str(key)).casefold()
    return normalized in _PRACTICE_ANSWER_KEYS


def _student_sample(value: Any) -> Any:
    """Copy a display sample while recursively dropping fields that disclose answers."""
    if isinstance(value, list):
        return [_student_sample(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _student_sample(item)
            for key, item in value.items()
            if not _is_practice_answer_key(key)
        }
    return value


def _student_practice(practice: Any) -> dict[str, Any] | None:
    """Build the student-safe practice DTO without altering the stored scoring fixture.

    The page only consumes questions, samples, and checklist. Whitelisting those
    display fields prevents top-level answers/expected maps from leaking, while
    sample sanitization keeps authored inputs visible without exposing nested keys.
    """
    if practice is None:
        return None
    if not isinstance(practice, dict):
        return {}

    visible: dict[str, Any] = {}
    raw_questions = practice.get("questions")
    if isinstance(raw_questions, list):
        questions: list[dict[str, Any]] = []
        for raw_question in raw_questions:
            if not isinstance(raw_question, dict):
                continue
            question: dict[str, Any] = {
                key: str(raw_question[key])
                for key in ("key", "prompt", "question", "title", "hint")
                if raw_question.get(key) is not None
            }
            question_type = _exercise_type(raw_question.get("type"))
            question["type"] = question_type
            raw_options = raw_question.get("options")
            if isinstance(raw_options, list):
                options = [str(option).strip() for option in raw_options if str(option).strip()]
                if question_type == "true_false" and not options:
                    options = ["正确", "错误"]
                if options:
                    question["options"] = options[:20]
            elif question_type == "true_false":
                question["options"] = ["正确", "错误"]
            if question:
                questions.append(question)
        visible["questions"] = questions

    raw_samples = practice.get("samples")
    if isinstance(raw_samples, list):
        visible["samples"] = [_student_sample(sample) for sample in raw_samples]

    raw_checklist = practice.get("checklist")
    if isinstance(raw_checklist, list):
        # Checklist entries are display text only; structured objects could hide
        # a fixture value when coerced to a string by the frontend.
        visible["checklist"] = [
            str(item) for item in raw_checklist if isinstance(item, (str, int, float, bool))
        ]
    return visible


def _latest_score(conn: sqlite3.Connection, task_id: str) -> float | None:
    row = conn.execute(
        "SELECT score FROM task_attempts WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return float(row["score"]) if row and row["score"] is not None else None


def _latest_attempt(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    """取最后一次提交，统一详情恢复与确认掌握度的“当前尝试”语义。"""
    return conn.execute(
        "SELECT * FROM task_attempts WHERE task_id = ? "
        "ORDER BY attempt_number DESC, created_at DESC, id DESC LIMIT 1",
        (task_id,),
    ).fetchone()


def _task_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """列表项 DTO：任务行 + 进度 + 最近得分。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "goal": row["goal"],
        # ``goal`` is the historical column; ``description`` is the active
        # task-language contract used by new clients.
        "description": row["goal"],
        "data_type": row["data_type"],
        "cap_ids": _task_json(row, "cap_ids_json", []),
        "source": row["source"],
        "status": row["status"],
        "progress": _PROGRESS_BY_STATUS.get(row["status"], 0.0),
        "latest_score": _latest_score(conn, row["id"]),
        "counts_toward_mastery": bool(row["counts_toward_mastery"]),
        "due_at": row["due_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "content_status": row["content_status"] if "content_status" in row.keys() else "none",
    }


def _task_content_status(row: sqlite3.Row) -> str:
    """Read the additive content state while remaining compatible with old rows."""

    return str(row["content_status"] or "none") if "content_status" in row.keys() else "none"


def _knowledge_point_dto(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _exercise_dto(
    row: sqlite3.Row,
    submission: sqlite3.Row | None = None,
) -> dict[str, Any]:
    """Return an exercise without its private reference answer."""

    options = _json_value(row["options_json"], None)
    result: dict[str, Any] = {
        "id": row["id"],
        "question": row["question"],
        "type": _exercise_type(row["type"]),
        "options": (
            [str(option) for option in options if str(option).strip()]
            if isinstance(options, list)
            else (["正确", "错误"] if _exercise_type(row["type"]) == "true_false" else None)
        ),
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
    }
    if submission is not None:
        result["submission"] = {
            "id": submission["id"],
            "answer": submission["answer"],
            "grade_status": submission["grade_status"],
            "score": submission["score"],
            "feedback": submission["feedback"],
            "graded_at": submission["graded_at"],
            "created_at": submission["created_at"],
        }
    else:
        result["submission"] = None
    return result


def _student_content(
    conn: sqlite3.Connection,
    task_id: str,
    student_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points = conn.execute(
        "SELECT * FROM task_knowledge_points WHERE task_id = ? ORDER BY sort_order, id",
        (task_id,),
    ).fetchall()
    exercises = conn.execute(
        "SELECT * FROM task_exercises WHERE task_id = ? ORDER BY sort_order, id",
        (task_id,),
    ).fetchall()
    visible_exercises: list[dict[str, Any]] = []
    for exercise in exercises:
        submission = conn.execute(
            "SELECT * FROM task_exercise_submissions "
            "WHERE exercise_id = ? AND student_id = ? "
            # ``created_at`` has second-level SQLite precision and UUIDs are
            # random, so rowid is the only stable tie-breaker for two rapid
            # submissions from the same student.
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (exercise["id"], student_id),
        ).fetchone()
        visible_exercises.append(_exercise_dto(exercise, submission))
    return [_knowledge_point_dto(point) for point in points], visible_exercises


def _parse_grade_response(value: Any) -> tuple[int, str]:
    """Normalize provider output into a bounded score and safe feedback text."""

    text = str(value or "").strip()
    payload: Any = None
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"(?:score|得分)\s*[:：]\s*(\d{1,3})", text, re.IGNORECASE)
        score = int(match.group(1)) if match else 0
        return max(0, min(100, score)), text[:2000]
    if isinstance(payload, dict):
        score_value = payload.get("score", payload.get("得分", 0))
        feedback = payload.get("feedback", payload.get("评语", payload.get("comment", "")))
    else:
        score_value, feedback = 0, text
    try:
        score = int(float(score_value))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score)), str(feedback or "")[:2000]


async def _grade_submission_async(submission_id: str) -> None:
    """Grade one submission off-request and always persist a terminal state."""

    conn = db_connect(get_config().resolved_database_path)
    try:
        submission = conn.execute(
            "SELECT s.*, e.question, e.type, e.reference_answer FROM task_exercise_submissions s "
            "JOIN task_exercises e ON e.id = s.exercise_id WHERE s.id = ?",
            (submission_id,),
        ).fetchone()
        if submission is None:
            return
        conn.execute(
            "UPDATE task_exercise_submissions SET grade_status = 'grading' WHERE id = ?",
            (submission_id,),
        )
        conn.commit()
        # Closed-choice questions have an exact authored answer.  Grade them
        # locally so a radio/select submission does not depend on an LLM
        # provider and remains deterministic in offline deployments.
        if _exercise_type(submission["type"]) in {"multiple_choice", "true_false"}:
            expected = " ".join(str(submission["reference_answer"] or "").split()).casefold()
            got = " ".join(str(submission["answer"] or "").split()).casefold()
            score = 100 if expected and got == expected else 0
            feedback = "答案正确" if score else "请对照学习内容重新判断"
            conn.execute(
                "UPDATE task_exercise_submissions SET grade_status = 'done', score = ?, "
                "feedback = ?, graded_at = ? WHERE id = ?",
                (score, feedback, dt.datetime.now(dt.timezone.utc).isoformat(), submission_id),
            )
            conn.commit()
            return
        from ..agent import providers

        response = await providers.complete(
            [
                {
                    "role": "system",
                    "content": "请只返回 JSON：{\"score\":0-100,\"feedback\":\"简短中文评语\"}。",
                },
                {
                    "role": "user",
                    "content": (
                        f"题目：{submission['question']}\n参考答案：{submission['reference_answer'] or ''}\n"
                        f"学生答案：{submission['answer']}"
                    ),
                },
            ],
            role="grader",
        )
        if not response or not response.get("text"):
            raise RuntimeError("grader_unavailable")
        score, feedback = _parse_grade_response(response["text"])
        conn.execute(
            "UPDATE task_exercise_submissions SET grade_status = 'done', score = ?, "
            "feedback = ?, graded_at = ? WHERE id = ?",
            (score, feedback, dt.datetime.now(dt.timezone.utc).isoformat(), submission_id),
        )
        conn.commit()
    except Exception:
        logger.warning("task exercise grading failed", exc_info=True)
        try:
            conn.execute(
                "UPDATE task_exercise_submissions SET grade_status = 'failed' WHERE id = ?",
                (submission_id,),
            )
            conn.commit()
        except Exception:
            logger.warning("task exercise failure status could not be persisted", exc_info=True)
    finally:
        conn.close()


def _schedule_background(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _mastery_preview_for_score(
    conn: sqlite3.Connection,
    task_row: sqlite3.Row,
    user_id: str,
    score: float | None,
) -> list[dict]:
    """按当前掌握度计算待确认尝试的预览，保持刷新后的展示与实际应用一致。"""
    cap_ids = _task_json(task_row, "cap_ids_json", [])
    if (
        score is None
        or not task_row["counts_toward_mastery"]
        or not isinstance(cap_ids, list)
        or not cap_ids
    ):
        return []

    delta = mastery_service.exercise_delta(float(score))
    return mastery_service.preview_from_deltas(
        conn,
        user_id,
        [
            {"cap_id": str(cap_id), "delta": delta}
            for cap_id in cap_ids
        ],
    )


def _attempt_detail(
    conn: sqlite3.Connection,
    task_row: sqlite3.Row,
    user_id: str,
    attempt: sqlite3.Row | None,
) -> dict | None:
    """将最近提交还原为页面可恢复的反馈状态。

    feedback 是提交后才产生的学习反馈；它与详情 rubric 分开返回，因此评分答案
    不会在开始作答前泄露。预览不持久化，而是以当前掌握度重算，确保刷新后确认
    的结果与 apply-mastery 的真实写入一致。
    """
    if attempt is None:
        return None

    answers = _json_value(attempt["submission_json"], {})
    feedback = _json_value(attempt["feedback_json"], [])
    mastery_applied = bool(attempt["mastery_applied"])
    can_apply = not mastery_applied and task_row["status"] == "submitted"
    return {
        "id": attempt["id"],
        "attempt_number": attempt["attempt_number"],
        "score": float(attempt["score"]) if attempt["score"] is not None else None,
        "mastery_applied": mastery_applied,
        "created_at": attempt["created_at"],
        "answers": answers if isinstance(answers, dict) else {},
        "feedback": feedback if isinstance(feedback, list) else [],
        "mastery_preview": _mastery_preview_for_score(
            conn,
            task_row,
            user_id,
            float(attempt["score"]) if can_apply and attempt["score"] is not None else None,
        ),
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
    raw_rubric = _task_json(task_row, "rubric_json", None)
    # A few early Agent cards stored a rubric object. Filter to actual rows so
    # those records safely use completeness scoring instead of crashing on .get.
    rubric = [item for item in raw_rubric if isinstance(item, dict)] if isinstance(raw_rubric, list) else []
    if rubric:
        total_weight = 0.0
        earned = 0.0
        feedback: list[dict] = []
        for item in rubric:
            key = str(item.get("key"))
            expected = item.get("expected")
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
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
    if not isinstance(practice, dict):
        practice = {}
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
    description: str | None = None
    data_type: str | None = None
    cap_ids: list[str] = []
    steps: list[dict] = []
    resources: list[dict] = []
    source: str | None = None  # 缺省 'agent'（学生手动建任务视同 Agent 直出）


class TaskPatchBody(BaseModel):
    title: str | None = None
    goal: str | None = None
    description: str | None = None
    steps: list[dict] | None = None
    status: str | None = None  # 仅接受目标状态：paused / in_progress / not_started


class SubmitBody(BaseModel):
    answers: dict[str, Any] | list[dict[str, Any]]


class ApplyMasteryBody(BaseModel):
    attempt_id: str


class BatchBody(BaseModel):
    ids: list[str]
    action: str  # 目前仅支持 'archive'（PRD-01 §6.1 批量操作）


class KnowledgePointBody(BaseModel):
    title: str
    content: str
    sort_order: int = 0


class ExerciseBody(BaseModel):
    question: str
    type: str = "open_ended"
    options: list[str] | None = None
    reference_answer: str | None = None
    sort_order: int = 0


class ExerciseSubmitBody(BaseModel):
    answer: str


class StartLearningBody(BaseModel):
    cap_node_id: str
    # Creation always queues content.  This legacy flag remains only to make
    # an explicit retry of a previously failed generation distinguishable.
    generate_content: bool = False
    # Task-detail retries need to target the task the learner is viewing.  The
    # graph entry point omits this field and keeps the original capability-based
    # create-or-reuse behavior.
    task_id: str | None = None


class InternalGradeBody(BaseModel):
    submission_id: str


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
          (id, user_id, title, goal, data_type, cap_ids_json, source,
           status, steps_json, resources_json, counts_toward_mastery, created_by,
           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?, 1, ?, ?, ?)
        """,
        (
            task_id,
            current.user["id"],
            body.title.strip(),
            body.description if body.description is not None else body.goal,
            body.data_type,
            json.dumps(body.cap_ids, ensure_ascii=False),
            source,
            # Steps remain a read-only legacy column; newly created tasks no
            # longer manufacture an operation checklist.
            "[]",
            # New tasks keep the legacy resources column empty.  Historical
            # rows are still exposed by task_detail for backward compatibility.
            "[]",
            current.user["id"],
            now,
            now,
        ),
    )
    conn.commit()
    _track(conn, current.user["id"], "task_created", {"task_id": task_id, "source": source})
    # All direct learner-created tasks, including preset/diagnostic handoffs,
    # enter the same asynchronous content-generation lifecycle immediately.
    from ..tools.task_tools import queue_task_content

    queue_task_content(conn, task_id)
    row = _get_own_task(conn, task_id, current.user["id"])
    return _task_summary(conn, row)


@router.get("/api/tasks/{task_id}")
def task_detail(
    task_id: str,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生任务详情：学习内容、无答案键的评分项和可恢复的最近提交。"""
    row = _get_own_task(conn, task_id, current.user["id"])
    # Historical rows may predate automatic content generation.  Queue them
    # on first detail read so no learner has to press a manual generate button.
    if _task_content_status(row) == "none":
        from ..tools.task_tools import queue_task_content

        queue_task_content(conn, task_id)
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
    latest_attempt = _latest_attempt(conn, task_id)
    knowledge_points, exercises = _student_content(conn, task_id, current.user["id"])
    return {
        **_task_summary(conn, row),
        "steps": _task_json(row, "steps_json", []),
        "resources": _task_json(row, "resources_json", []),
        # The stored rubric retains expected values for deterministic grading;
        # the student DTO intentionally strips them before leaving the server.
        "rubric": _student_rubric(_task_json(row, "rubric_json", None)),
        "practice": _student_practice(_task_json(row, "practice_json", None)),
        "caps": caps,
        "linked": linked,
        "teacher_id": row["teacher_id"],
        "class_id": row["class_id"],
        "version": row["version"],
        "parent_task_id": row["parent_task_id"],
        "attempts": [dict(a) for a in attempts],
        "latest_attempt": _attempt_detail(conn, row, current.user["id"], latest_attempt),
        "content_status": _task_content_status(row),
        "content_generated_at": row["content_generated_at"]
        if "content_generated_at" in row.keys()
        else None,
        "knowledge_points": knowledge_points,
        "exercises": exercises,
    }


@router.get("/api/tasks/{task_id}/knowledge-points")
def list_knowledge_points(
    task_id: str,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_own_task(conn, task_id, current.user["id"])
    items = conn.execute(
        "SELECT * FROM task_knowledge_points WHERE task_id = ? ORDER BY sort_order, id",
        (row["id"],),
    ).fetchall()
    return {"items": [_knowledge_point_dto(item) for item in items], "total": len(items)}


@router.post("/api/tasks/{task_id}/knowledge-points", status_code=201)
def create_knowledge_point(
    task_id: str,
    body: KnowledgePointBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_own_task(conn, task_id, current.user["id"])
    if not body.title.strip() or not body.content.strip():
        raise ApiError(400, "VALIDATION_ERROR", "知识点标题和内容不能为空")
    point_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO task_knowledge_points "
        "(id, task_id, title, content, sort_order, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (point_id, row["id"], body.title.strip(), body.content.strip(), body.sort_order, now, now),
    )
    conn.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = COALESCE(content_generated_at, ?) "
        "WHERE id = ?",
        (now, task_id),
    )
    conn.commit()
    return _knowledge_point_dto(
        conn.execute("SELECT * FROM task_knowledge_points WHERE id = ?", (point_id,)).fetchone()
    )


@router.get("/api/tasks/{task_id}/exercises")
def list_exercises(
    task_id: str,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_own_task(conn, task_id, current.user["id"])
    _, items = _student_content(conn, row["id"], current.user["id"])
    return {"items": items, "total": len(items)}


@router.post("/api/tasks/{task_id}/exercises", status_code=201)
def create_exercise(
    task_id: str,
    body: ExerciseBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_own_task(conn, task_id, current.user["id"])
    if not body.question.strip():
        raise ApiError(400, "VALIDATION_ERROR", "练习题不能为空")
    kind = _exercise_type(body.type)
    if kind != body.type:
        raise ApiError(400, "VALIDATION_ERROR", "练习题类型不受支持")
    options = [str(option).strip() for option in (body.options or []) if str(option).strip()]
    if kind == "true_false" and not options:
        options = ["正确", "错误"]
    if kind == "multiple_choice" and not options:
        raise ApiError(400, "VALIDATION_ERROR", "选择题必须提供选项")
    exercise_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO task_exercises "
        "(id, task_id, question, type, options_json, reference_answer, sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            exercise_id,
            row["id"],
            body.question.strip(),
            kind,
            json.dumps(options, ensure_ascii=False) if options else None,
            body.reference_answer.strip() if body.reference_answer else None,
            body.sort_order,
            now,
        ),
    )
    conn.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = COALESCE(content_generated_at, ?) "
        "WHERE id = ?",
        (now, task_id),
    )
    conn.commit()
    exercise = conn.execute("SELECT * FROM task_exercises WHERE id = ?", (exercise_id,)).fetchone()
    return _exercise_dto(exercise)


@router.post("/api/tasks/{task_id}/exercises/{exercise_id}/submit", status_code=202)
async def submit_exercise(
    task_id: str,
    exercise_id: str,
    body: ExerciseSubmitBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _get_own_task(conn, task_id, current.user["id"])
    exercise = conn.execute(
        "SELECT * FROM task_exercises WHERE id = ? AND task_id = ?",
        (exercise_id, task_id),
    ).fetchone()
    if exercise is None:
        raise ApiError(404, "EXERCISE_NOT_FOUND", "练习题不存在")
    if not body.answer.strip():
        raise ApiError(400, "VALIDATION_ERROR", "答案不能为空")
    submission_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO task_exercise_submissions "
        "(id, exercise_id, student_id, answer, grade_status) VALUES (?, ?, ?, ?, 'pending')",
        (submission_id, exercise_id, current.user["id"], body.answer.strip()),
    )
    conn.commit()
    _schedule_background(_grade_submission_async(submission_id))
    return {"submission_id": submission_id, "grade_status": "pending"}


@router.post("/api/tasks/start-learning")
async def start_learning(
    body: StartLearningBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create/reuse a graph task and schedule content generation off-request."""

    if body.task_id:
        task = _get_own_task(conn, body.task_id, current.user["id"])
        task_caps = _task_json(task, "cap_ids_json", []) or []
        if body.cap_node_id not in task_caps:
            raise ApiError(422, "TASK_CAP_MISMATCH", "任务不包含指定的能力节点")
    else:
        rows = conn.execute(
            "SELECT * FROM learning_tasks WHERE user_id = ? AND status != 'archived' "
            "ORDER BY updated_at DESC",
            (current.user["id"],),
        ).fetchall()
        task = next(
            (
                row
                for row in rows
                if body.cap_node_id in (_task_json(row, "cap_ids_json", []) or [])
            ),
            None,
        )
    if task is None:
        task_id = uuid.uuid4().hex
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO learning_tasks "
            "(id, user_id, title, goal, cap_ids_json, source, status, steps_json, resources_json, "
            "counts_toward_mastery, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'agent', 'not_started', ?, '[]', 1, ?, ?, ?)",
            (
                task_id,
                current.user["id"],
                f"学习能力 {body.cap_node_id}",
                f"掌握能力 {body.cap_node_id}",
                json.dumps([body.cap_node_id], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                current.user["id"],
                now,
                now,
            ),
        )
        conn.commit()
        task = _get_own_task(conn, task_id, current.user["id"])
    task_id = task["id"]
    # A newly created/reused task must begin generation without a second user
    # click.  Queue through the durable worker so the request portal cannot
    # cancel generation and the worker keeps this request's database path.
    content_status = _task_content_status(task)
    if content_status == "none" or (body.generate_content and content_status == "failed"):
        from ..tools.task_tools import queue_task_content

        queue_task_content(conn, task_id, force=content_status == "failed")
        task = _get_own_task(conn, task_id, current.user["id"])
    return {"task_id": task_id, "content_status": _task_content_status(task)}


@router.post("/api/internal/grade-submission")
async def grade_submission_internal(
    body: InternalGradeBody,
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    if current.user["role"] not in {"system_admin", "content_admin"}:
        raise ApiError(403, "FORBIDDEN", "无权执行内部评阅")
    _schedule_background(_grade_submission_async(body.submission_id))
    return {"submission_id": body.submission_id, "grade_status": "pending"}


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
    if body.description is not None or body.goal is not None:
        updates["goal"] = body.description if body.description is not None else body.goal
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

    # Reuse the detail recovery calculation so immediate and post-refresh previews agree.
    mastery_preview = _mastery_preview_for_score(conn, row, current.user["id"], score)
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
    latest_attempt = _latest_attempt(conn, task_id)
    if latest_attempt is None or latest_attempt["id"] != attempt["id"]:
        # A later resubmission supersedes prior previews; applying an old one
        # would make the persisted result differ from the detail page's current state.
        raise ApiError(409, "ATTEMPT_NOT_CURRENT", "请确认最近一次提交的掌握度变化")
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
        applied = mastery_service.apply_updates(
            conn,
            current.user["id"],
            [
                {"cap_id": cid, "delta": delta}
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
