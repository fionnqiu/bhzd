"""受控学习域 Agent 能力网关。

所有自动写入都在这里做属主校验、状态机、幂等和限流；工具层只负责把
Agent 参数投影为网关调用，避免模型获得通用 SQL、Shell 或文件系统入口。
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .. import audit
from ..db import utc_now_iso

_STATUS_PROGRESS = {
    "not_started": 0.0,
    "in_progress": 0.5,
    "paused": 0.5,
    "submitted": 0.9,
    "completed": 1.0,
}
_TRANSITIONS = {
    "not_started": {"in_progress"},
    "in_progress": {"paused", "submitted"},
    "paused": {"in_progress"},
    "submitted": {"completed"},
    "completed": {"completed"},
}
_SAFE_ERROR = "学习操作未完成，请稍后重试"
_REVIEW_TEXT_LIMIT = 2_000


class LearningCapabilityError(RuntimeError):
    """Expected, user-safe capability rejection."""


def _user_id(user: Any) -> str:
    value = user.get("id") if isinstance(user, dict) else user["id"]
    if not isinstance(value, str) or not value:
        raise LearningCapabilityError("当前用户无效")
    return value


def _limit_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _setting(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM agent_learning_capability_settings WHERE capability = 'learning'"
    ).fetchone()
    if row is None:
        raise LearningCapabilityError("学习自动操作能力未启用")
    return row


def _begin_action(
    conn: sqlite3.Connection,
    user_id: str,
    capability: str,
    key: str,
    run_id: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """Claim an idempotency key before any write; the same key returns its result."""
    setting = _setting(conn)
    if not setting["enabled"]:
        raise LearningCapabilityError("学习自动操作能力已关闭")
    key = _limit_text(key, 128)
    if not key:
        raise LearningCapabilityError("缺少幂等键")
    existing = conn.execute(
        "SELECT status, result_json FROM agent_learning_actions "
        "WHERE user_id = ? AND capability = ? AND idempotency_key = ?",
        (user_id, capability, key),
    ).fetchone()
    if existing is not None:
        if existing["status"] == "completed":
            try:
                return key, json.loads(existing["result_json"] or "{}")
            except json.JSONDecodeError:
                return key, {"already_completed": True}
        raise LearningCapabilityError("相同操作正在处理，请稍后重试")
    cutoff = utc_now_iso()
    # ISO timestamps sort lexically, and SQLite's datetime() handles the UTC
    # values written by this project; count only new actions so an idempotent
    # replay remains available even after the rolling budget is exhausted.
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_learning_actions "
        "WHERE user_id = ? AND created_at >= datetime(?, '-' || ? || ' seconds')",
        (user_id, cutoff, int(setting["window_seconds"])),
    ).fetchone()["n"]
    if count >= int(setting["per_user_limit"]):
        raise LearningCapabilityError("自动操作次数已达上限，请稍后再试")
    action_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO agent_learning_actions "
        "(id, user_id, capability, idempotency_key, run_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'running', ?)",
        (action_id, user_id, capability, key, run_id, utc_now_iso()),
    )
    return action_id, None


def _finish_action(
    conn: sqlite3.Connection, action_id: str, result: dict[str, Any], *, ok: bool = True
) -> None:
    conn.execute(
        "UPDATE agent_learning_actions SET status = ?, result_json = ?, completed_at = ? WHERE id = ?",
        ("completed" if ok else "failed", json.dumps(result, ensure_ascii=False, default=str), utc_now_iso(), action_id),
    )


def _task(conn: sqlite3.Connection, task_id: str, user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None or row["user_id"] != user_id:
        raise LearningCapabilityError("任务不存在")
    if row["status"] == "archived":
        raise LearningCapabilityError("任务已归档，仅可查看历史记录")
    return row


def _audit(conn: sqlite3.Connection, user_id: str, action: str, target: str, after: dict[str, Any]) -> None:
    # Audit is append-only and stores only bounded, non-secret result metadata.
    try:
        audit.audit(conn, user_id, action, "learning_task", target, after=after, commit=False)
    except Exception:
        # Audit failure must never turn a successful learning mutation into a
        # partially committed state; the caller's transaction will roll back.
        raise


def _event(conn: sqlite3.Connection, run_id: str | None, title: str, detail: str) -> None:
    """Emit a bounded learner-safe event when the action belongs to an Agent run."""
    if not run_id:
        return
    try:
        from . import events

        events.emit_progress(conn, run_id, phase="learning", status="completed", title=title, detail=detail)
    except Exception:
        # Event delivery must not turn a committed learning write into a retry.
        conn.rollback()


def auto_create_task(
    conn: sqlite3.Connection,
    user: Any,
    args: dict[str, Any],
    *,
    run_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Create one student-owned task with reviewed, normalized content."""
    user_id = _user_id(user)
    title = _limit_text(args.get("title"), 200)
    if not title:
        raise LearningCapabilityError("任务标题不能为空")
    action_id, replay = _begin_action(conn, user_id, "learning.task.auto_create", str(args.get("idempotency_key") or ""), run_id)
    if replay is not None:
        return {**replay, "already_completed": True}
    try:
        # Keep this gateway independent from the registry import graph.  The
        # compact normalization mirrors task_tools' reviewed card contract and
        # prevents a direct gateway import from creating a circular registry import.
        points = args.get("knowledge_points") or [{"title": "学习目标", "content": _limit_text(args.get("goal") or args.get("description"), 8000) or title}]
        exercises = args.get("exercises") or args.get("practice") or []
        normalized_points = [
            {"title": _limit_text(item.get("title"), 200), "content": _limit_text(item.get("content"), 8000)}
            for item in points if isinstance(item, dict) and _limit_text(item.get("title"), 200) and _limit_text(item.get("content"), 8000)
        ][:10]
        normalized_exercises = [
            {"question": _limit_text(item.get("question"), 4000), "type": _limit_text(item.get("type") or "open_ended", 32),
             "options": item.get("options") if isinstance(item.get("options"), list) else [],
             "reference_answer": _limit_text(item.get("reference_answer"), 8000)}
            for item in exercises if isinstance(item, dict) and _limit_text(item.get("question"), 4000)
        ][:20]
        card = {"title": title, "description": _limit_text(args.get("description") or args.get("goal"), 8000),
                "data_type": args.get("data_type"), "cap_ids": [str(item)[:128] for item in (args.get("cap_ids") or [])[:20]],
                "knowledge_points": normalized_points, "exercises": normalized_exercises}
        now = utc_now_iso()
        task_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO learning_tasks "
            "(id, user_id, title, goal, data_type, cap_ids_json, source, status, "
            "steps_json, resources_json, counts_toward_mastery, created_by, created_at, updated_at, "
            "automation_actor, automation_run_id) VALUES (?, ?, ?, ?, ?, ?, 'agent', 'not_started', '[]', '[]', ?, ?, ?, ?, 'agent_auto', ?)",
            (task_id, user_id, card["title"], card["description"], card.get("data_type"),
             json.dumps(card.get("cap_ids") or [], ensure_ascii=False),
             1 if args.get("counts_toward_mastery", True) else 0, user_id, now, now, run_id),
        )
        for index, point in enumerate(card["knowledge_points"]):
            conn.execute("INSERT INTO task_knowledge_points (id, task_id, title, content, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (uuid.uuid4().hex, task_id, point["title"], point["content"], index, now, now))
        for index, exercise in enumerate(card["exercises"]):
            conn.execute("INSERT INTO task_exercises (id, task_id, question, type, options_json, reference_answer, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (uuid.uuid4().hex, task_id, exercise["question"], exercise["type"], json.dumps(exercise["options"], ensure_ascii=False), exercise["reference_answer"], index, now))
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'done', content_generated_at = ? WHERE id = ?",
            (now, task_id),
        )
        result = {"task_id": task_id, "title": card["title"], "status": "not_started", "progress": 0.0}
        _finish_action(conn, action_id, result)
        if commit:
            conn.commit()
        _audit(conn, user_id, "agent_learning_task_created", task_id, result)
        _event(conn, run_id, "学习任务已生成", "已创建一项学习任务")
        return result
    except Exception:
        conn.rollback()
        raise


def record_progress(
    conn: sqlite3.Connection,
    user: Any,
    args: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply only the learner task state transitions allowed by the task domain."""
    user_id = _user_id(user)
    task_id = _limit_text(args.get("task_id"), 128)
    target = _limit_text(args.get("status") or args.get("action"), 32)
    if target == "start":
        target = "in_progress"
    if target == "pause":
        target = "paused"
    if target == "submit":
        target = "submitted"
    if target == "complete":
        target = "completed"
    if target not in _STATUS_PROGRESS:
        raise LearningCapabilityError("不支持的学习状态")
    action_id, replay = _begin_action(conn, user_id, "learning.progress.record", str(args.get("idempotency_key") or ""), run_id)
    if replay is not None:
        return {**replay, "already_completed": True}
    try:
        row = _task(conn, task_id, user_id)
        if target not in _TRANSITIONS.get(row["status"], set()):
            raise LearningCapabilityError(f"当前状态不允许变更为 {target}")
        progress = float(args.get("progress", _STATUS_PROGRESS[target]))
        if not 0 <= progress <= 1:
            raise LearningCapabilityError("进度必须在 0 到 1 之间")
        now = utc_now_iso()
        conn.execute("UPDATE learning_tasks SET status = ?, progress = ?, updated_at = ? WHERE id = ?", (target, progress, now, task_id))
        result = {"task_id": task_id, "status": target, "progress": progress}
        _finish_action(conn, action_id, result)
        conn.commit()
        _audit(conn, user_id, "agent_learning_progress_recorded", task_id, result)
        _event(conn, run_id, "学习进度已更新", f"任务状态已更新为 {target}")
        return result
    except Exception:
        conn.rollback()
        raise


def sync_mastery(
    conn: sqlite3.Connection,
    user: Any,
    args: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Derive mastery only from latest, successfully graded exercises."""
    user_id = _user_id(user)
    task_id = _limit_text(args.get("task_id"), 128)
    action_id, replay = _begin_action(conn, user_id, "learning.mastery.sync", str(args.get("idempotency_key") or ""), run_id)
    if replay is not None:
        return {**replay, "already_completed": True}
    try:
        row = _task(conn, task_id, user_id)
        if not row["counts_toward_mastery"]:
            result = {"task_id": task_id, "applied": [], "eligible_exercises": 0}
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM task_exercises WHERE task_id = ?", (task_id,)
            ).fetchone()["n"]
            submissions = conn.execute(
                "SELECT s.exercise_id, s.score FROM task_exercise_submissions s "
                "JOIN (SELECT exercise_id, MAX(created_at) AS latest FROM task_exercise_submissions "
                "WHERE student_id = ? AND grade_status = 'done' AND score IS NOT NULL "
                "AND manual_review_required = 0 GROUP BY exercise_id) latest "
                "ON latest.exercise_id = s.exercise_id AND latest.latest = s.created_at "
                "JOIN task_exercises e ON e.id = s.exercise_id WHERE e.task_id = ? AND s.student_id = ?",
                (user_id, task_id, user_id),
            ).fetchall()
            cap_ids = json.loads(row["cap_ids_json"] or "[]")
            scores = [float(item["score"]) / 100 for item in submissions]
            applied: list[dict[str, Any]] = []
            # A partial set of successful grades is not enough evidence for a
            # task-level mastery update; pending/failed/manual-review rows keep
            # the action retryable and leave mastery untouched.
            if not total or len(scores) != int(total):
                raise LearningCapabilityError("全部练习评分完成后才能同步掌握度")
            if scores and cap_ids:
                from ..mastery import service

                delta = service.exercise_delta(sum(scores) / len(scores))
                applied = service.apply_updates(conn, user_id, [{"cap_id": cap, "delta": delta} for cap in cap_ids], source="exercise", ref_id=action_id, commit=False)
            result = {"task_id": task_id, "applied": applied, "eligible_exercises": len(scores)}
        _finish_action(conn, action_id, result)
        conn.commit()
        _audit(conn, user_id, "agent_learning_mastery_synced", task_id, {"eligible_exercises": result["eligible_exercises"], "applied_count": len(result["applied"])})
        _event(conn, run_id, "技能掌握度已同步", f"依据 {result['eligible_exercises']} 道已评分练习")
        return result
    except Exception:
        conn.rollback()
        raise


def _run_async(coro: Any) -> Any:
    """Run provider coroutine from both sync workers and an active event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _parse_grade(text: str) -> tuple[int, str]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise LearningCapabilityError(_SAFE_ERROR)
    try:
        payload = json.loads(match.group(0))
        score = max(0, min(100, int(payload["score"])))
        feedback = _limit_text(payload.get("feedback"), _REVIEW_TEXT_LIMIT)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise LearningCapabilityError(_SAFE_ERROR) from None
    if not feedback:
        raise LearningCapabilityError(_SAFE_ERROR)
    return score, feedback


def review_exercise(
    conn: sqlite3.Connection,
    user: Any,
    args: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Ask the dedicated grader and append an immutable review record."""
    user_id = _user_id(user)
    submission_id = _limit_text(args.get("submission_id"), 128)
    action_id, replay = _begin_action(conn, user_id, "learning.exercise.review", str(args.get("idempotency_key") or ""), run_id)
    if replay is not None:
        return {**replay, "already_completed": True}
    try:
        submission = conn.execute(
            "SELECT s.*, e.question, e.reference_answer, t.id AS task_id, t.user_id "
            "FROM task_exercise_submissions s JOIN task_exercises e ON e.id = s.exercise_id "
            "JOIN learning_tasks t ON t.id = e.task_id WHERE s.id = ? AND s.student_id = ?",
            (submission_id, user_id),
        ).fetchone()
        if submission is None:
            raise LearningCapabilityError("练习提交不存在")
        from . import providers

        response = _run_async(providers.complete([
            {"role": "system", "content": '只返回 JSON：{"score":0-100,"feedback":"简短中文评语"}。'},
            {"role": "user", "content": f"题目：{submission['question']}\n参考答案：{submission['reference_answer'] or ''}\n学生答案：{submission['answer']}"},
        ], role="grader"))
        if not response or not response.get("text"):
            raise LearningCapabilityError(_SAFE_ERROR)
        score, feedback = _parse_grade(str(response["text"]))
        now = utc_now_iso()
        # Existing completed scores are historical facts; never overwrite them.
        if submission["grade_status"] != "done" or submission["score"] is None:
            conn.execute("UPDATE task_exercise_submissions SET grade_status = 'done', score = ?, feedback = ?, graded_at = ? WHERE id = ?", (score, feedback, now, submission_id))
        review_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO task_exercise_reviews "
            "(id, submission_id, task_id, user_id, score, feedback, provider_role, provider_id, run_id, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'grader', ?, ?, ?, ?)",
            (review_id, submission_id, submission["task_id"], user_id, score, feedback, response.get("provider_id"), run_id, str(args.get("idempotency_key")), now),
        )
        result = {"review_id": review_id, "submission_id": submission_id, "score": score, "feedback": feedback, "provider_role": "grader"}
        _finish_action(conn, action_id, result)
        conn.commit()
        _audit(conn, user_id, "agent_learning_exercise_reviewed", submission["task_id"], {"submission_id": submission_id, "score": score, "review_id": review_id})
        _event(conn, run_id, "练习已完成评阅", "已生成评分和改进建议")
        return result
    except Exception:
        conn.rollback()
        raise


def record_completed_review(
    conn: sqlite3.Connection,
    user: Any,
    submission_id: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Project an existing dedicated-grader result into the review history.

    The grading worker already called the configured ``grader`` provider.  An
    event-triggered review therefore stores that bounded feedback directly and
    avoids a second model call for the same submission.
    """

    user_id = _user_id(user)
    key = f"graded:{submission_id}"
    action_id, replay = _begin_action(conn, user_id, "learning.exercise.review", key, run_id)
    if replay is not None:
        return {**replay, "already_completed": True}
    try:
        row = conn.execute(
            "SELECT s.id, s.score, s.feedback, s.grade_status, e.task_id "
            "FROM task_exercise_submissions s JOIN task_exercises e ON e.id = s.exercise_id "
            "WHERE s.id = ? AND s.student_id = ?",
            (submission_id, user_id),
        ).fetchone()
        if row is None or row["grade_status"] != "done" or row["score"] is None:
            conn.rollback()
            return None
        now = utc_now_iso()
        review_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO task_exercise_reviews "
            "(id, submission_id, task_id, user_id, score, feedback, provider_role, run_id, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'grader', ?, ?, ?)",
            (review_id, submission_id, row["task_id"], user_id, row["score"], row["feedback"] or "已完成评分", run_id, key, now),
        )
        result = {
            "review_id": review_id,
            "submission_id": submission_id,
            "score": row["score"],
            "feedback": row["feedback"] or "已完成评分",
            "provider_role": "grader",
        }
        _finish_action(conn, action_id, result)
        _audit(conn, user_id, "agent_learning_exercise_reviewed", row["task_id"], {"submission_id": submission_id, "score": row["score"], "review_id": review_id})
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def create_remediation_task(
    conn: sqlite3.Connection,
    user: Any,
    *,
    task_id: str,
    submission_id: str,
    score: int,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Create one bounded follow-up task after a low score on an Agent task."""

    task = conn.execute(
        "SELECT title, goal, data_type, cap_ids_json, automation_actor "
        "FROM learning_tasks WHERE id = ? AND user_id = ?",
        (task_id, _user_id(user)),
    ).fetchone()
    if task is None or task["automation_actor"] != "agent_auto" or score >= 60:
        return None
    try:
        cap_ids = json.loads(task["cap_ids_json"] or "[]")
    except json.JSONDecodeError:
        cap_ids = []
    return auto_create_task(
        conn,
        user,
        {
            "title": f"补强：{task['title']}",
            "goal": f"针对上次练习得分 {score} 分的薄弱点进行复盘",
            "data_type": task["data_type"],
            "cap_ids": cap_ids,
            "knowledge_points": [{"title": "错误复盘", "content": "对照评分反馈重新梳理关键判断依据。"}],
            "exercises": [{"question": "请重新说明本题的判断依据", "reference_answer": "结合规范逐步说明判断依据"}],
            "idempotency_key": f"remediation:{submission_id}",
        },
        run_id=run_id,
    )
