"""教师班级错误点分析。

错误点的事实来源是已发布教师任务的单题评分记录，而不是学生独立上传的
诊断文件。模型只负责把受限样本归纳成可读标签；频次、学生数和任务范围
始终由服务端根据证据索引重新计算，避免模型凭空制造统计数字。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from typing import Any

from ..db import utc_now_iso
from ..rag.embeddings import run_coro_sync

logger = logging.getLogger(__name__)

ERROR_SCORE_THRESHOLD = 60
MAJOR_SCORE_THRESHOLD = 40
MAX_SAMPLES = 80
MAX_ERRORS = 5
MAX_FIELD_LENGTH = 1200
_SLUG_RE = re.compile(r"[^\w.-]+", re.UNICODE)


def _placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def _database_path(conn: sqlite3.Connection) -> str | None:
    """Capture the request database so provider selection cannot drift across workers."""

    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return None
    return str(row[2]) if row is not None and row[2] else None


def _bounded_text(value: Any, limit: int = MAX_FIELD_LENGTH) -> str:
    """Strip control characters and cap model context supplied by user-authored text."""

    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def collect_error_samples(
    conn: sqlite3.Connection,
    *,
    teacher_id: str,
    class_ids: list[str],
    data_type: str | None = None,
    source: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Return latest low-score submissions from the teacher's published copies.

    ``parent_task_id IS NOT NULL`` is the durable publication marker.  The
    enrollment join keeps current class analytics from accidentally importing a
    different class' student history, while old copies remain queryable for the
    selected time window when a student is still enrolled.
    """

    if not class_ids:
        return []
    clauses = [
        f"t.class_id IN ({_placeholders(class_ids)})",
        "t.teacher_id = ?",
        "t.parent_task_id IS NOT NULL",
        "enr.left_at IS NULL",
        "s.grade_status = 'done'",
        "s.score IS NOT NULL",
    ]
    params: list[Any] = [*class_ids, teacher_id]
    if data_type:
        clauses.append("t.data_type = ?")
        params.append(data_type)
    if source:
        clauses.append("t.source = ?")
        params.append(source)
    if since:
        clauses.append("s.created_at >= ?")
        params.append(since)

    rows = conn.execute(
        f"""
        SELECT t.id AS task_id, t.title AS task_title, t.class_id,
               ex.id AS exercise_id, ex.question, ex.reference_answer,
               s.student_id, s.answer, s.score, s.feedback, s.created_at,
               s.rowid AS submission_rowid
        FROM learning_tasks AS t
        JOIN task_exercises AS ex ON ex.task_id = t.id
        JOIN task_exercise_submissions AS s
          ON s.exercise_id = ex.id AND s.student_id = t.user_id
        JOIN class_enrollments AS enr
          ON enr.class_id = t.class_id AND enr.student_id = t.user_id
        WHERE {" AND ".join(clauses)}
        ORDER BY s.created_at DESC, s.rowid DESC
        LIMIT ?
        """,
        (*params, MAX_SAMPLES * 4),
    ).fetchall()

    # A learner can retry a question.  One current submission per exercise is
    # the honest unit for a frequency chart; older attempts remain in history.
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["exercise_id"]), str(row["student_id"]))
        if key in seen:
            continue
        try:
            score = max(0, min(100, int(row["score"])))
        except (TypeError, ValueError):
            continue
        # Filter after deduplication's score parse: the query is ordered by
        # newest completed submission, so a successful retry suppresses an old
        # low-score record instead of leaving a stale error behind.
        if score >= ERROR_SCORE_THRESHOLD:
            seen.add(key)
            continue
        seen.add(key)
        samples.append(
            {
                "task_id": str(row["task_id"]),
                "task_title": _bounded_text(row["task_title"], 200),
                "class_id": str(row["class_id"]),
                "exercise_id": str(row["exercise_id"]),
                "question": _bounded_text(row["question"]),
                "reference_answer": _bounded_text(row["reference_answer"]),
                "answer": _bounded_text(row["answer"]),
                "score": score,
                "feedback": _bounded_text(row["feedback"]),
                # Kept in memory only; never returned to the browser or model.
                "student_id": str(row["student_id"]),
            }
        )
        if len(samples) >= MAX_SAMPLES:
            break

    # Older published tasks may only have a task-level attempt (before the
    # per-exercise grading tables were introduced). Include those rows when no
    # exercise exists so the analytics card does not go blank during migration.
    if len(samples) < MAX_SAMPLES:
        legacy_clauses = [
            f"t.class_id IN ({_placeholders(class_ids)})",
            "t.teacher_id = ?",
            "t.parent_task_id IS NOT NULL",
            "enr.left_at IS NULL",
            "a.user_id = t.user_id",
            "a.score IS NOT NULL",
            "NOT EXISTS (SELECT 1 FROM task_exercises AS old_ex WHERE old_ex.task_id = t.id)",
        ]
        legacy_params: list[Any] = [*class_ids, teacher_id]
        if data_type:
            legacy_clauses.append("t.data_type = ?")
            legacy_params.append(data_type)
        if source:
            legacy_clauses.append("t.source = ?")
            legacy_params.append(source)
        if since:
            legacy_clauses.append("a.created_at >= ?")
            legacy_params.append(since)
        legacy_rows = conn.execute(
            f"""
            SELECT t.id AS task_id, t.title AS task_title, t.class_id, t.user_id AS student_id,
                   a.id AS attempt_id, a.submission_json, a.feedback_json, a.score, a.created_at
            FROM learning_tasks AS t
            JOIN task_attempts AS a ON a.task_id = t.id
            JOIN class_enrollments AS enr
              ON enr.class_id = t.class_id AND enr.student_id = t.user_id
            WHERE {" AND ".join(legacy_clauses)}
            ORDER BY a.created_at DESC, a.rowid DESC
            LIMIT ?
            """,
            (*legacy_params, MAX_SAMPLES * 4),
        ).fetchall()
        seen_legacy: set[tuple[str, str]] = set()
        for row in legacy_rows:
            key = (str(row["task_id"]), str(row["student_id"]))
            if key in seen_legacy:
                continue
            try:
                answer = json.dumps(json.loads(row["submission_json"] or "{}"), ensure_ascii=False)
            except (TypeError, json.JSONDecodeError):
                answer = _bounded_text(row["submission_json"])
            try:
                feedback = json.dumps(json.loads(row["feedback_json"] or "{}"), ensure_ascii=False)
            except (TypeError, json.JSONDecodeError):
                feedback = _bounded_text(row["feedback_json"])
            try:
                raw_score = float(row["score"])
            except (TypeError, ValueError):
                continue
            score = raw_score * 100 if raw_score <= 1 else raw_score
            if score >= ERROR_SCORE_THRESHOLD:
                seen_legacy.add(key)
                continue
            seen_legacy.add(key)
            samples.append(
                {
                    "task_id": str(row["task_id"]),
                    "task_title": _bounded_text(row["task_title"], 200),
                    "class_id": str(row["class_id"]),
                    "exercise_id": f"legacy:{row['attempt_id']}",
                    "question": "任务整体作答",
                    "reference_answer": "",
                    "answer": _bounded_text(answer),
                    "score": max(0, min(100, int(round(score)))),
                    "feedback": _bounded_text(feedback),
                    "student_id": str(row["student_id"]),
                }
            )
            if len(samples) >= MAX_SAMPLES:
                break
    return samples


def _error_key(question: str) -> str:
    digest = hashlib.sha1(question.encode("utf-8", "ignore")).hexdigest()[:12]
    return f"question_{digest}"


def _aggregate_item(
    *,
    error_type: str,
    label: str,
    evidence: list[int],
    samples: list[dict[str, Any]],
    suggestion: str | None = None,
) -> dict[str, Any] | None:
    """Build a response item from server-owned evidence indices."""

    valid = sorted({index for index in evidence if 0 <= index < len(samples)})
    if not valid:
        return None
    evidence_samples = [samples[index] for index in valid]
    major = sum(1 for sample in evidence_samples if sample["score"] < MAJOR_SCORE_THRESHOLD)
    minor = len(evidence_samples) - major
    return {
        "error_type": error_type[:80],
        "label": _bounded_text(label, 160) or "未命名错误点",
        "count": len(evidence_samples),
        "major": major,
        "minor": minor,
        "affected_students": len({sample["student_id"] for sample in evidence_samples}),
        "task_ids": sorted({sample["task_id"] for sample in evidence_samples}),
        "suggestion": _bounded_text(suggestion, 300) if suggestion else None,
    }


def fallback_error_items(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic local fallback used when no provider is configured."""

    groups: dict[str, list[int]] = {}
    labels: dict[str, str] = {}
    for index, sample in enumerate(samples):
        question = sample["question"] or "未命名练习"
        # Include the task title for the local fallback.  This keeps two
        # unrelated legacy tasks from collapsing into one identical row while
        # AI-enabled runs can still merge semantically similar questions.
        key = _error_key(f"{sample['task_title']}::{question}")
        groups.setdefault(key, []).append(index)
        labels[key] = f"{sample['task_title']} · 题目：{question[:100]}"
    items = []
    for key, evidence in groups.items():
        item = _aggregate_item(
            error_type=key,
            label=labels[key],
            evidence=evidence,
            samples=samples,
            suggestion="围绕该练习的参考答案和评语安排针对性复习",
        )
        if item:
            items.append(item)
    return sorted(items, key=lambda item: (-item["count"], item["error_type"]))[:MAX_ERRORS]


def _extract_payload(text: Any) -> list[dict[str, Any]]:
    """Accept a strict object/array while tolerating harmless markdown fences."""

    candidate = str(text or "").strip().strip("`").strip()
    payload: Any = None
    try:
        payload = json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        decoder = json.JSONDecoder()
        for marker in ("{", "["):
            position = candidate.find(marker)
            if position < 0:
                continue
            try:
                payload, _ = decoder.raw_decode(candidate[position:])
                break
            except json.JSONDecodeError:
                continue
    if isinstance(payload, dict):
        payload = payload.get("errors")
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)][:MAX_ERRORS]


def _ai_items(
    samples: list[dict[str, Any]], conn: sqlite3.Connection
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ask the configured primary model for labels, then validate every claim."""

    context = [
        {
            "index": index,
            "task": sample["task_title"],
            "question": sample["question"],
            "reference_answer": sample["reference_answer"],
            "student_answer": sample["answer"],
            "score": sample["score"],
            "feedback": sample["feedback"],
        }
        for index, sample in enumerate(samples)
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是教师学情分析助手。只返回 JSON 对象，格式为 "
                '{"errors":[{"error_type":"短英文标识","label":"中文错误点",'
                '"severity":"major|minor","evidence":[0],"suggestion":"一句教学建议"}]}。'
                "只能引用给定 evidence index，不得编造次数、学生或任务。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"samples": context}, ensure_ascii=False),
        },
    ]
    try:
        from . import providers

        kwargs: dict[str, Any] = {"role": "primary"}
        database_path = _database_path(conn)
        if database_path:
            kwargs["database_path"] = database_path
        try:
            response = run_coro_sync(providers.complete(messages, **kwargs))
        except TypeError:
            # Lightweight provider doubles and older rolling workers may not
            # accept database_path; they still use the configured process DB.
            kwargs.pop("database_path", None)
            response = run_coro_sync(providers.complete(messages, **kwargs))
        if not response or not response.get("text"):
            return [], {}
        raw_items = _extract_payload(response["text"])
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            error_type = _SLUG_RE.sub("_", str(raw.get("error_type") or "").strip()).strip("_")
            label = _bounded_text(raw.get("label"), 160)
            evidence = raw.get("evidence")
            if not error_type or not label or not isinstance(evidence, list):
                continue
            indices = [
                value
                for value in evidence
                if isinstance(value, int) and not isinstance(value, bool)
            ]
            item = _aggregate_item(
                error_type=error_type,
                label=label,
                evidence=indices,
                samples=samples,
                suggestion=raw.get("suggestion"),
            )
            if item:
                items.append(item)
        if not items:
            return [], {}
        return (
            sorted(items, key=lambda item: (-item["count"], item["error_type"]))[:MAX_ERRORS],
            {
                "provider_model": response.get("model"),
                "provider_id": response.get("provider_id"),
            },
        )
    except Exception:
        logger.warning("teacher error analysis provider call failed", exc_info=True)
        return [], {}


def analyze_error_points(
    conn: sqlite3.Connection,
    *,
    teacher_id: str,
    class_ids: list[str],
    data_type: str | None = None,
    source: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Return AI-labelled error points with an honest deterministic fallback."""

    try:
        samples = collect_error_samples(
            conn,
            teacher_id=teacher_id,
            class_ids=class_ids,
            data_type=data_type,
            source=source,
            since=since,
        )
    except sqlite3.Error:
        # Keep the broader analytics page usable during a rolling migration or
        # on a legacy database that predates per-exercise submissions.
        logger.warning("teacher error analysis tables are unavailable", exc_info=True)
        return {
            "items": [],
            "source": "none",
            "sample_count": 0,
            "generated_at": None,
            "provider_model": None,
            "provider_id": None,
            "notice": "错误分析数据暂不可用",
        }
    if not samples:
        return {
            "items": [],
            "source": "none",
            "sample_count": 0,
            "generated_at": None,
            "provider_model": None,
            "provider_id": None,
            "notice": "暂无已发布任务的低分练习样本",
        }

    ai_items, provider_meta = _ai_items(samples, conn)
    if ai_items:
        return {
            "items": ai_items,
            "source": "ai",
            "sample_count": len(samples),
            "generated_at": utc_now_iso(),
            "provider_model": provider_meta.get("provider_model"),
            "provider_id": provider_meta.get("provider_id"),
            "notice": None,
        }

    return {
        "items": fallback_error_items(samples),
        "source": "fallback",
        "sample_count": len(samples),
        "generated_at": utc_now_iso(),
        "provider_model": None,
        "provider_id": None,
        "notice": "当前未获得可用模型分析，已按已发布任务低分题目生成本地统计",
    }
