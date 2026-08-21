"""Student Agent task previews and confirmation-gated creation.

Task cards are assembled deterministically before confirmation.  This keeps the
four learner-facing fields stable from the preview through durable persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from typing import Any

from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from .registry import ToolContext, ToolSpec, emit_telemetry

logger = logging.getLogger(__name__)

# Published teacher copies share one durable lesson.  These process-local
# locks serialize workers for the same parent while allowing unrelated tasks
# to call the configured provider concurrently; SQLite remains the source of
# truth for the copied rows and status transitions.
_CONTENT_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_CONTENT_LOCKS_GUARD = threading.Lock()
# A lifespan can be entered more than once in a test process (or by a local
# reload helper).  Remember rows already re-claimed by this process so a second
# startup does not enqueue a duplicate provider call while the first worker is
# still active.  A real process restart starts with an empty set and therefore
# recovers rows left by the previous process.
_CONTENT_RECOVERY_CLAIMS: set[tuple[str, str]] = set()

_DATA_TYPE_LABELS = {
    "text": "文本",
    "image": "图像",
    "audio": "语音",
    "video": "视频",
}

_EXERCISE_TYPE_ALIASES = {
    "choice": "multiple_choice",
    "single_choice": "multiple_choice",
    "boolean": "true_false",
    "truefalse": "true_false",
}
_SUPPORTED_EXERCISE_TYPES = frozenset({"open_ended", "multiple_choice", "true_false"})

# These values are intentionally user-safe labels, not provider identifiers.
# A teacher only needs to know whether content came from a configured model,
# the deterministic fallback, or reviewed/manual work; revealing upstream
# endpoint or exception details would make a retry status unsafe to display.
_CONTENT_SOURCE_PROVIDER = "provider"
_CONTENT_SOURCE_TEMPLATE = "template"
_CONTENT_SOURCE_MANUAL = "manual"
_CONTENT_SOURCE_COPIED = "copied"


def _student_rule_text(value: Any) -> str:
    """Project reviewed rule data into bounded learner-readable text.

    Teaching-unit rules may be structured provenance objects rather than a
    sentence.  Only reviewed statements are exposed to learners; arbitrary
    ``str(dict)``/``repr`` output would leak implementation metadata and make
    the generated lesson unreadable.
    """

    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, (dict, list)):
        return ""

    statements: list[str] = []

    def collect(item: Any, *, include_statement: bool = False) -> None:
        if isinstance(item, str):
            if include_statement and item.strip():
                statements.append(item.strip())
            return
        if isinstance(item, list):
            for child in item:
                collect(child, include_statement=include_statement)
            return
        if not isinstance(item, dict):
            return
        # ``statement`` is the reviewed prose field used by both external
        # facts and project policy.  Nested policy definitions are traversed
        # as well, so future units can add statement-bearing rule groups.
        if isinstance(item.get("statement"), str) and item["statement"].strip():
            statements.append(item["statement"].strip())
        for key, child in item.items():
            if key == "statement":
                continue
            if key in {"external_format_facts", "project_policy"} or isinstance(child, (dict, list)):
                collect(child)

    collect(value)
    return "\n".join(dict.fromkeys(statements))


def _mark_task_content_done(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    source: str,
    now: str | None = None,
    message: str | None = None,
) -> None:
    """Persist a terminal, explainable content result in one update.

    The state is written with the lesson rows, rather than inferred from a
    background log, so a refresh after process restart still tells the teacher
    whether they should review template fallback content.
    """

    completed_at = now or utc_now_iso()
    conn.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = ?, "
        "content_generation_source = ?, content_failure_reason = NULL, "
        "content_generation_message = ?, "
        "content_last_attempt_at = COALESCE(content_last_attempt_at, ?) WHERE id = ?",
        (completed_at, source, message, completed_at, task_id),
    )


def _mark_task_content_failed(
    conn: sqlite3.Connection, task_id: str, reason: str
) -> None:
    """Record only a stable recovery message, never an upstream exception body."""

    conn.execute(
        "UPDATE learning_tasks SET content_status = 'failed', content_generation_source = 'none', "
        "content_failure_reason = ?, content_generation_message = NULL WHERE id = ?",
        (reason, task_id),
    )


def _cap_names(cap_ids: list[str]) -> list[dict[str, str]]:
    """cap_id → 名称（graphx 惰性查询；未就绪时以 id 代名称，不阻断组卡）。"""
    # The graph module is optional during lightweight test/startup paths, so
    # keep its lazy import explicitly nullable for both runtime and type checks.
    gx_reason: Any = None
    try:
        from ..graphx import reason as gx_reason  # B4，惰性导入
    except ImportError:
        pass
    named: list[dict[str, str]] = []
    for cap_id in cap_ids:
        label = cap_id
        if gx_reason is not None:
            try:
                detail = gx_reason.node_detail(cap_id)
                if isinstance(detail, dict) and detail.get("label"):
                    label = str(detail["label"])
            except Exception:
                logger.warning("能力节点 %s 查询失败，以 id 代名称", cap_id)
        named.append({"cap_id": cap_id, "name": label})
    return named


def graph_learning_context(cap_id: str) -> dict[str, Any] | None:
    """Return the reviewed local teaching context for one graph capability.

    A graph CAP is only an index entry.  The returned teaching-unit projection
    is deliberately filtered to the same published/student-visible contract as
    the graph API, so automatic lessons never turn catalogue metadata or draft
    course material into student-facing content.
    """

    try:
        from ..diagnosis.engine import load_teaching_units
        from ..graphx import reason

        detail = reason.node_detail(cap_id)
    except Exception:
        logger.warning("图谱学习上下文读取失败: %s", cap_id, exc_info=True)
        return None
    if not isinstance(detail, dict) or detail.get("type") != "CAP":
        return None

    units_by_id = {
        str(unit["id"]): unit
        for unit in load_teaching_units()
        if isinstance(unit, dict) and isinstance(unit.get("id"), str)
    }
    teaching_units: list[dict[str, Any]] = []
    seen_unit_ids: set[str] = set()
    for graph_task in detail.get("tasks") or []:
        if not isinstance(graph_task, dict):
            continue
        for link in graph_task.get("teaching_unit_links") or []:
            if not isinstance(link, dict):
                continue
            unit_id = link.get("unit_id")
            unit = units_by_id.get(unit_id) if isinstance(unit_id, str) else None
            if (
                unit is None
                or unit_id in seen_unit_ids
                or not link.get("consumable")
                or not link.get("student_visible")
                or not link.get("in_student_visible_index")
                or link.get("review_status") != "published"
                or unit.get("review_status") != "published"
                or not unit.get("student_visible")
            ):
                continue
            seen_unit_ids.add(unit_id)
            teaching_units.append(unit)

    label = str(detail.get("label") or cap_id).strip()
    description = str(detail.get("description") or "").strip()
    data_types = detail.get("data_types")
    data_type = data_types[0] if isinstance(data_types, list) and data_types else None
    return {
        "cap_id": cap_id,
        "label": label,
        "description": description,
        "data_type": data_type if isinstance(data_type, str) else None,
        "teaching_units": teaching_units,
        "resources": [
            {"type": "teaching_unit", "ref_id": unit["id"], "title": unit.get("title")}
            for unit in teaching_units
        ],
    }


def _task_teaching_units(task: sqlite3.Row) -> list[dict[str, Any]]:
    """Resolve persisted reviewed teaching-unit references for deterministic fallbacks.

    The worker reads the task's saved references instead of a fresh graph query.
    This makes retries reproduce the lesson originally confirmed for a learner
    even when the graph catalogue changes after task creation.
    """

    try:
        resources = json.loads(task["resources_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        resources = []
    unit_ids = [
        item.get("ref_id")
        for item in resources
        if isinstance(item, dict)
        and item.get("type") == "teaching_unit"
        and isinstance(item.get("ref_id"), str)
    ]
    if not unit_ids:
        return []
    try:
        from ..diagnosis.engine import load_teaching_units

        units_by_id = {
            str(unit["id"]): unit
            for unit in load_teaching_units()
            if isinstance(unit, dict) and isinstance(unit.get("id"), str)
        }
    except Exception:
        logger.warning("教学单元读取失败，保留通用兜底", exc_info=True)
        return []
    return [units_by_id[unit_id] for unit_id in unit_ids if unit_id in units_by_id]


def _normalized_knowledge_points(raw: Any) -> list[dict[str, str]]:
    """Validate the reviewed learning-content shape before it is persisted."""

    if not isinstance(raw, list):
        raise ValueError("学习内容必须是列表")
    normalized: list[dict[str, str]] = []
    for item in raw[:10]:
        if not isinstance(item, dict):
            raise ValueError("学习内容项必须包含标题和正文")
        title = str(item.get("title") or "").strip()[:200]
        content = str(item.get("content") or "").strip()[:8000]
        if not title or not content:
            raise ValueError("学习内容项必须包含标题和正文")
        normalized.append({"title": title, "content": content})
    return normalized


def _default_task_content(
    title: str,
    description: str,
    *,
    teaching_units: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Build a concrete local lesson when a reviewed teaching unit is available.

    Provider outages are common enough that graph-created lessons need a useful
    offline path.  Unit text is reviewed project material, whereas the old
    title-only fallback could only repeat a CAP identifier and a generic prompt.
    """

    for unit in teaching_units or []:
        objectives = [
            str(item).strip() for item in unit.get("learning_objectives") or [] if str(item).strip()
        ]
        rule = _student_rule_text(unit.get("rule_explanation"))
        exercise = unit.get("exercise") if isinstance(unit.get("exercise"), dict) else {}
        action = str(exercise.get("student_action") or "").strip()
        answer = exercise.get("answer")
        answer_text = json.dumps(answer, ensure_ascii=False) if answer is not None else "；".join(objectives)
        unit_title = str(unit.get("title") or title).strip()
        points = [
            {
                "title": f"{unit_title}学习目标",
                "content": "；".join(objectives) or description or title,
            }
        ]
        if rule:
            points.append({"title": f"{unit_title}判定规则", "content": rule})
        return (
            points,
            [
                {
                    "question": action or f"请说明完成“{unit_title}”时需要遵守的规则。",
                    "type": "open_ended",
                    "options": [],
                    "reference_answer": answer_text or "应依据学习目标和判定规则完成作答。",
                }
            ],
        )

    focus = description or title
    return (
        [
            {
                "title": f"{title}核心要点",
                "content": f"围绕 {focus} 梳理学习目标、关键规则和常见错误。",
            }
        ],
        [
            {
                "question": f"请用自己的话说明完成“{focus}”时最重要的检查点。",
                "type": "open_ended",
                "options": [],
                "reference_answer": "应覆盖任务目标、关键规则和质量检查点。",
            }
        ],
    )


def _normalized_exercises(raw: Any, *, require_choice_options: bool = True) -> list[dict[str, Any]]:
    """Normalize exercises so the student UI always gets a usable control."""

    if not isinstance(raw, list):
        raise ValueError("练习必须是列表")
    normalized: list[dict[str, Any]] = []
    for item in raw[:20]:
        if not isinstance(item, dict):
            raise ValueError("练习项必须包含题目")
        question = str(item.get("question") or "").strip()[:4000]
        if not question:
            raise ValueError("练习项必须包含题目")
        raw_type = str(item.get("type") or "open_ended").strip().casefold().replace("-", "_")
        kind = _EXERCISE_TYPE_ALIASES.get(raw_type, raw_type)
        if kind not in _SUPPORTED_EXERCISE_TYPES:
            kind = "open_ended"
        raw_options = item.get("options")
        if raw_options is not None and not isinstance(raw_options, list):
            raise ValueError("选择题选项必须是列表")
        options = [str(option).strip() for option in (raw_options or []) if str(option).strip()]
        if kind == "multiple_choice" and not options:
            if require_choice_options:
                raise ValueError("选择题至少需要一个选项")
            # Provider output without options cannot render as a choice control;
            # retain the question as a text response instead of failing the task.
            kind = "open_ended"
        if kind == "true_false" and not options:
            options = ["正确", "错误"]
        normalized.append(
            {
                "question": question,
                "type": kind,
                "options": options,
                "reference_answer": str(item.get("reference_answer") or "").strip()[:4000],
            }
        )
    return normalized


def _task_card_content(
    args: dict[str, Any], title: str, description: str
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Return the canonical reviewed content displayed in a four-field task card."""

    has_points = "knowledge_points" in args or "learning_content" in args
    has_exercises = "exercises" in args or "practice" in args
    default_points, default_exercises = _default_task_content(title, description)
    points_raw = (
        args.get("knowledge_points")
        if "knowledge_points" in args
        else args.get("learning_content", [])
    )
    exercises_raw = args.get("exercises") if "exercises" in args else args.get("practice", [])
    return (
        _normalized_knowledge_points(points_raw if has_points else default_points),
        _normalized_exercises(exercises_raw if has_exercises else default_exercises),
    )


def _persist_task_content_rows(
    conn: sqlite3.Connection,
    task_id: str,
    knowledge_points: list[dict[str, str]],
    exercises: list[dict[str, Any]],
    now: str,
    *,
    generation_source: str = _CONTENT_SOURCE_MANUAL,
    generation_message: str | None = None,
) -> dict[str, Any]:
    """Write one reviewed/generated lesson without committing the caller transaction."""

    for index, point in enumerate(knowledge_points):
        conn.execute(
            "INSERT INTO task_knowledge_points "
            "(id, task_id, title, content, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                task_id,
                point["title"],
                point["content"],
                index,
                now,
                now,
            ),
        )
    for index, exercise in enumerate(exercises):
        options = exercise["options"]
        conn.execute(
            "INSERT INTO task_exercises "
            "(id, task_id, question, type, options_json, reference_answer, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                task_id,
                exercise["question"],
                exercise["type"],
                json.dumps(options, ensure_ascii=False) if options else None,
                exercise["reference_answer"],
                index,
                now,
            ),
        )
    # A reviewed empty array is deliberate too: this terminal marker prevents a
    # detached generator from silently replacing a card the learner confirmed.
    _mark_task_content_done(
        conn,
        task_id,
        source=generation_source,
        now=now,
        message=generation_message,
    )
    return {
        "knowledge_points": len(knowledge_points),
        "exercises": len(exercises),
        "status": "done",
    }


def build_task_card(args: dict[str, Any]) -> dict[str, Any]:
    """组装四字段 TaskCard（不落库）。历史步骤/rubric 不再自动生成。"""
    data_type = args.get("data_type")
    label = _DATA_TYPE_LABELS.get(data_type or "", "")
    title = args.get("title") or (f"{label}标注练习任务" if label else "标注练习任务")
    goal = args.get("description") or args.get("goal") or "掌握该任务对应的标注规范并能独立完成练习"
    cap_ids = list(args.get("cap_ids") or [])
    points, exercises = _task_card_content(args, title, goal)
    return {
        "title": title,
        "goal": goal,
        "description": goal,
        "data_type": data_type,
        "cap_ids": cap_ids,
        "cap_names": _cap_names(cap_ids),
        "knowledge_points": points,
        "exercises": exercises,
        "est_minutes": args.get("est_minutes") or 45,
    }


def task_preview_handler(ctx: ToolContext) -> dict[str, Any]:
    raw_stages = ctx.args.get("stages")
    cards = (
        [build_task_card(stage) for stage in raw_stages if isinstance(stage, dict)]
        if isinstance(raw_stages, list) and len(raw_stages) > 1
        else None
    )
    card = build_task_card(ctx.args) if cards is None else None
    single_card = card or {}
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_preview_created",
        {
            # A staged preview deliberately has no wrapper card.  Read the
            # common data type from its first independent task instead of
            # dereferencing the single-task shape during telemetry emission.
            "data_type": (cards[0] if cards else single_card).get("data_type"),
            "cap_count": sum(len(item.get("cap_ids") or []) for item in cards)
            if cards is not None
            else len(single_card.get("cap_ids") or []),
        },
    )
    return {"card": card, "stages": cards} if cards is not None else {"card": card}


def task_create_preview(ctx: ToolContext) -> dict[str, Any]:
    """确认门预览载荷：展示一张或多张四字段任务卡。"""
    raw_stages = ctx.args.get("stages")
    if isinstance(raw_stages, list) and len(raw_stages) > 1:
        cards = [build_task_card(stage) for stage in raw_stages if isinstance(stage, dict)]
        return {
            "action": "task.create",
            "summary": f"将创建 {len(cards)} 个分阶段学习任务",
            "stages": cards,
        }
    card = build_task_card(ctx.args)
    return {
        "action": "task.create",
        "summary": f"将创建学习任务「{card['title']}」",
        "card": card,
    }


def task_create_apply(ctx: ToolContext) -> dict[str, Any]:
    """确认后原子写入一张或多张 learning_tasks（source 默认 agent）。"""
    raw_stages = ctx.args.get("stages")
    stage_args = (
        [stage for stage in raw_stages if isinstance(stage, dict)]
        if isinstance(raw_stages, list) and raw_stages
        else [ctx.args]
    )
    now = utc_now_iso()
    counts_toward_mastery = 1 if ctx.args.get("counts_toward_mastery", True) else 0
    source = ctx.args.get("source") or "agent"
    if source not in ("agent", "preset", "teacher", "diagnostic"):
        source = "agent"
    created: list[dict[str, Any]] = []
    try:
        for stage in stage_args:
            card = build_task_card(stage)
            task_id = uuid.uuid4().hex
            ctx.db.execute(
                """
                INSERT INTO learning_tasks
                  (id, user_id, title, goal, data_type, cap_ids_json,
                   source, status, steps_json, resources_json, rubric_json,
                   counts_toward_mastery, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'not_started', '[]', '[]', NULL, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    ctx.user_row["id"],
                    card["title"],
                    card["description"],
                    card.get("data_type"),
                    json.dumps(card["cap_ids"], ensure_ascii=False),
                    source,
                    counts_toward_mastery,
                    ctx.user_row["id"],
                    now,
                    now,
                ),
            )
            # Keep every reviewed stage self-contained before the batch is
            # visible, so no later worker can replace its confirmed detail.
            _persist_task_content_rows(
                ctx.db,
                task_id,
                card["knowledge_points"],
                card["exercises"],
                now,
            )
            created.append(
                {
                    "task_id": task_id,
                    "title": card["title"],
                    "card": card,
                }
            )
        # Commit the complete batch before workers are queued so a provider
        # never observes only a subset of a multi-stage confirmation.
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        raise
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_created",
        {"task_ids": [item["task_id"] for item in created], "source": source},
    )
    if len(created) == 1:
        return created[0]
    return {
        "task_ids": [item["task_id"] for item in created],
        "tasks": created,
        "count": len(created),
    }


def mark_task_content_generating(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    force: bool = False,
    retry: bool = False,
) -> bool:
    """Atomically mark a task for generation without committing its caller's transaction.

    ``force`` is used for a new teacher-task version or an explicit content
    retry. Normal creation is idempotent: a second request cannot enqueue a
    duplicate worker after the task has already reached ``generating``/``done``.
    """

    try:
        # Claim in one conditional UPDATE.  A SELECT followed by UPDATE lets
        # two request threads both observe ``none`` and enqueue duplicate
        # provider calls before either transaction commits.
        predicate = "id = ?" if force else "id = ? AND COALESCE(content_status, 'none') = 'none'"
        cursor = conn.execute(
            "UPDATE learning_tasks SET content_status = 'generating', "
            "content_generated_at = NULL, content_generation_source = 'none', "
            "content_failure_reason = NULL, content_generation_message = NULL, "
            "content_last_attempt_at = ?, content_generation_retry_count = "
            "COALESCE(content_generation_retry_count, 0) + ? WHERE " + predicate,
            (utc_now_iso(), 1 if retry else 0, task_id),
        )
    except sqlite3.Error:
        # Older rolling deployments may not have the additive content columns
        # yet; leave those rows usable instead of breaking task creation.
        logger.warning("task content status column unavailable", exc_info=True)
        return False
    return cursor.rowcount == 1


def _content_recovery_key(conn: sqlite3.Connection, task_id: str) -> tuple[str, str]:
    """Build a process-scoped recovery key without exposing credentials."""

    database_path = _connection_database_path(conn)
    # In-memory databases have no filesystem identity; the connection id keeps
    # independent test/app instances from suppressing one another's recovery.
    identity = database_path or f":memory:{id(conn)}"
    return identity, task_id


def _release_content_recovery_claim(conn: sqlite3.Connection, task_id: str) -> None:
    """Allow a later explicit retry to be considered for startup recovery."""

    with _CONTENT_LOCKS_GUARD:
        _CONTENT_RECOVERY_CLAIMS.discard(_content_recovery_key(conn, task_id))


def recover_interrupted_task_content(conn: sqlite3.Connection) -> list[str]:
    """Re-queue content workers that were interrupted by a process restart.

    The additive content columns were introduced by migration 018.  During a
    rolling deployment an older database may not have them yet; startup must
    remain available and emit a diagnostic rather than failing the whole app.
    Rows are first reset and committed, then claimed through the same atomic
    queue path used by normal creation.  The process-local claim set makes
    repeated lifespan entries idempotent while a fresh process still retries
    every row left in ``generating``.
    """

    try:
        rows = conn.execute(
            "SELECT id FROM learning_tasks WHERE content_status = 'generating' "
            "ORDER BY updated_at ASC, id ASC"
        ).fetchall()
    except sqlite3.Error:
        logger.warning(
            "task content recovery skipped: migration columns are unavailable",
            exc_info=True,
        )
        return []

    candidates: list[str] = []
    with _CONTENT_LOCKS_GUARD:
        for row in rows:
            key = _content_recovery_key(conn, str(row["id"]))
            if key in _CONTENT_RECOVERY_CLAIMS:
                continue
            _CONTENT_RECOVERY_CLAIMS.add(key)
            candidates.append(str(row["id"]))
    if not candidates:
        return []

    reset_ids: list[str] = []
    try:
        for task_id in candidates:
            updated = conn.execute(
                "UPDATE learning_tasks SET content_status = 'none', "
                "content_generated_at = NULL "
                "WHERE id = ? AND content_status = 'generating'",
                (task_id,),
            )
            if updated.rowcount == 1:
                reset_ids.append(task_id)
            else:
                _release_content_recovery_claim(conn, task_id)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        for task_id in candidates:
            _release_content_recovery_claim(conn, task_id)
        logger.warning("task content recovery reset failed", exc_info=True)
        return []

    queued: list[str] = []
    for task_id in reset_ids:
        try:
            # Preserve the recovery claim until the new worker is accepted;
            # otherwise a concurrent lifespan could enqueue the same row.
            if queue_task_content(conn, task_id, _preserve_recovery_claim=True):
                queued.append(task_id)
            else:
                _release_content_recovery_claim(conn, task_id)
        except Exception:
            _release_content_recovery_claim(conn, task_id)
            logger.warning("task content recovery enqueue failed", exc_info=True)
    return queued


def _connection_database_path(conn: sqlite3.Connection) -> str | None:
    """Return the concrete SQLite file used by a caller connection.

    Background generation can outlive the request and pytest swaps the
    database path between fixtures.  Capturing ``PRAGMA database_list`` at
    enqueue time prevents a worker from consulting a later global config and
    accidentally opening a different database.
    """

    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    path = row[2]
    return str(path) if path else None


def schedule_task_content(task_id: str, *, database_path: str | None = None) -> None:
    """Run content generation on the process-level Agent loop after commit.

    Request-local ``asyncio.create_task`` is unsafe under Starlette's sync
    threadpool and TestClient portals.  Reusing the long-lived orchestrator
    loop gives all creation paths the same cancellation-safe worker contract.
    """

    from ..agent.orchestrator import spawn

    async def worker() -> None:
        await generate_task_content(task_id, database_path=database_path)

    spawn(worker())


def queue_task_content(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    force: bool = False,
    retry: bool = False,
    _preserve_recovery_claim: bool = False,
) -> bool:
    """Commit a generation marker and enqueue exactly one background worker."""

    if not _preserve_recovery_claim:
        # A normal create/retry supersedes any prior startup claim for this row.
        _release_content_recovery_claim(conn, task_id)
    if not mark_task_content_generating(conn, task_id, force=force, retry=retry):
        return False
    conn.commit()
    database_path = _connection_database_path(conn)
    try:
        schedule_task_content(task_id, database_path=database_path)
    except Exception:
        # A supervisor/loop failure must remain visible and retryable rather
        # than leaving the task permanently stuck in ``generating``.
        logger.warning("task content worker could not be scheduled", exc_info=True)
        _mark_task_content_failed(conn, task_id, "学习内容任务未能启动，请稍后重试")
        conn.commit()
        _release_content_recovery_claim(conn, task_id)
        return False
    return True


def _content_json(text: str) -> dict[str, Any] | None:
    """Extract the first provider JSON object despite harmless wrapper text.

    Models sometimes add a ``json`` fence or a short explanation before/after
    the object.  ``raw_decode`` keeps parsing strict for the target object
    while ignoring only those non-target characters.
    """

    if not isinstance(text, str):
        return None
    candidate = text.lstrip("\ufeff").strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else None
    return None


async def _generate_task_content_uncached(
    task_id: str, *, database_path: str | None = None
) -> dict[str, Any]:
    """Generate durable knowledge points and exercises for one learning task.

    The worker owns a fresh SQLite connection because it can outlive the HTTP
    request.  When no provider is configured, a small deterministic draft keeps
    the learner flow usable offline; provider failures are still reflected as a
    failed status only when persistence itself cannot complete.
    """

    # Prefer the path captured from the enqueueing request; config is only the
    # fallback for direct/manual invocations that do not have a connection.
    conn = db_connect(database_path or get_config().resolved_database_path)
    try:
        task = conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            return {"knowledge_points": 0, "exercises": 0, "status": "missing"}
        # A teacher can add authored content while an automatic worker is in
        # flight.  Preserve that explicit content instead of deleting it when
        # the generated response arrives a moment later.
        existing_counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM task_knowledge_points WHERE task_id = ?) AS points, "
            "(SELECT COUNT(*) FROM task_exercises WHERE task_id = ?) AS exercises",
            (task_id, task_id),
        ).fetchone()
        if existing_counts["points"] or existing_counts["exercises"]:
            # A worker can be interrupted after manual content is committed but
            # before the status transition.  Reconcile the durable marker here
            # so recovery never leaves a usable lesson stuck at ``none``.
            now = utc_now_iso()
            existing_source = (
                str(task["content_generation_source"] or "none")
                if "content_generation_source" in task.keys()
                else "none"
            )
            _mark_task_content_done(
                conn,
                task_id,
                source=existing_source if existing_source != "none" else _CONTENT_SOURCE_MANUAL,
                now=now,
            )
            conn.commit()
            return {
                "knowledge_points": int(existing_counts["points"]),
                "exercises": int(existing_counts["exercises"]),
                "status": "done",
            }
        now = utc_now_iso()
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'generating', "
            "content_last_attempt_at = COALESCE(content_last_attempt_at, ?) WHERE id = ?",
            (now, task_id),
        )
        conn.commit()
        title = str(task["title"] or "学习任务")
        description = str(task["goal"] or "").strip()
        cap_ids = json.loads(task["cap_ids_json"] or "[]")
        cap_text = ", ".join(str(item) for item in cap_ids) if isinstance(cap_ids, list) else ""
        teaching_units = _task_teaching_units(task)
        unit_context = [
            {
                "title": unit.get("title"),
                "learning_objectives": unit.get("learning_objectives", []),
                "rule_explanation": _student_rule_text(unit.get("rule_explanation")),
                "exercise": (
                    unit.get("exercise", {}).get("student_action", "")
                    if isinstance(unit.get("exercise"), dict)
                    else ""
                ),
            }
            for unit in teaching_units
        ]
        knowledge_points: list[dict[str, Any]] = []
        exercises: list[dict[str, Any]] = []
        provider_issue: str | None = None
        try:
            from ..agent.providers import complete

            response = await complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "只返回 JSON，格式为 {knowledge_points:[{title,content}], "
                            "exercises:[{question,type,options,reference_answer}]}。"
                        ),
                    },
                    {
                        "role": "user",
                        # A staged Agent request stores each stage's wording in
                        # ``goal``. Supplying it here keeps generated content
                        # specific to that stage rather than only its shared title.
                        "content": (
                            f"任务名称：{title}\n"
                            f"任务描述：{description or title}\n"
                            f"能力节点：{cap_text}\n"
                            f"已审核教学材料：{json.dumps(unit_context, ensure_ascii=False)}"
                        ),
                    },
                ],
                role="primary",
                # Provider selection must use the same database snapshot as
                # the detached content worker, not a later global config.
                database_path=database_path,
            )
            payload = _content_json(response.get("text", "")) if response else None
            if payload:
                knowledge_points = [
                    item
                    for item in payload.get("knowledge_points", [])
                    if isinstance(item, dict) and item.get("title") and item.get("content")
                ][:10]
                exercises = [
                    item
                    for item in payload.get("exercises", [])
                    if isinstance(item, dict) and item.get("question")
                ][:20]
            else:
                provider_issue = "模型返回内容不完整"
        except Exception:
            # The full exception may include a provider URL or other upstream
            # detail. Log it for operators, but retain only a stable summary in
            # the task row because teachers see that row directly.
            logger.warning("task content provider failed; using deterministic draft", exc_info=True)
            provider_issue = "模型服务暂不可用"

        default_points, default_exercises = _default_task_content(
            title, description, teaching_units=teaching_units
        )
        used_template = not knowledge_points or not exercises
        if not knowledge_points:
            knowledge_points = default_points
        if not exercises:
            exercises = default_exercises

        # Manual teacher/student CRUD can finish while the provider call above
        # is in flight.  Re-check immediately before replacing rows so an
        # authored lesson is never lost to a late automatic result.
        latest = conn.execute(
            "SELECT content_status FROM learning_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        latest_counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM task_knowledge_points WHERE task_id = ?) AS points, "
            "(SELECT COUNT(*) FROM task_exercises WHERE task_id = ?) AS exercises",
            (task_id, task_id),
        ).fetchone()
        if latest is None:
            return {"knowledge_points": 0, "exercises": 0, "status": "missing"}
        if latest_counts["points"] or latest_counts["exercises"]:
            now = utc_now_iso()
            latest_source = (
                str(task["content_generation_source"] or "none")
                if "content_generation_source" in task.keys()
                else "none"
            )
            _mark_task_content_done(
                conn,
                task_id,
                source=latest_source if latest_source != "none" else _CONTENT_SOURCE_MANUAL,
                now=now,
            )
            conn.commit()
            return {
                "knowledge_points": int(latest_counts["points"]),
                "exercises": int(latest_counts["exercises"]),
                "status": "done",
            }

        # Provider output uses the same storage contract as reviewed Agent
        # content. Missing choice options degrade to text input so a malformed
        # provider response never creates an unusable selection exercise.
        result = _persist_task_content_rows(
            conn,
            task_id,
            _normalized_knowledge_points(knowledge_points),
            _normalized_exercises(exercises, require_choice_options=False),
            now,
            generation_source=(
                _CONTENT_SOURCE_TEMPLATE if used_template else _CONTENT_SOURCE_PROVIDER
            ),
            generation_message=(
                f"{provider_issue or '模型返回内容不完整'}，已使用本地模板补全，请审核后发布"
                if used_template
                else None
            ),
        )
        conn.commit()
        return result
    except Exception:
        logger.warning("task content persistence failed", exc_info=True)
        try:
            _mark_task_content_failed(conn, task_id, "学习内容保存失败，请稍后重试")
            conn.commit()
        except Exception:
            logger.warning("task content failure status could not be persisted", exc_info=True)
        return {"knowledge_points": 0, "exercises": 0, "status": "failed"}
    finally:
        # Terminal workers no longer need the startup de-duplication claim;
        # clearing it also permits a later explicit retry to be recovered.
        _release_content_recovery_claim(conn, task_id)
        conn.close()


def _content_counts(conn: sqlite3.Connection, task_id: str) -> tuple[int, int]:
    """Return persisted lesson row counts used for idempotent fan-out copies."""

    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM task_knowledge_points WHERE task_id = ?) AS points, "
        "(SELECT COUNT(*) FROM task_exercises WHERE task_id = ?) AS exercises",
        (task_id, task_id),
    ).fetchone()
    return int(row["points"]), int(row["exercises"])


def _content_source_task_id(conn: sqlite3.Connection, task: sqlite3.Row) -> str:
    """Resolve a published student copy to its teacher source task.

    Teacher version rows also use ``parent_task_id`` for history, but they do
    not have a class assignment.  Restricting reuse to class-bound rows keeps a
    changed teacher version from accidentally inheriting an older lesson.
    """

    parent_id = task["parent_task_id"] if "parent_task_id" in task.keys() else None
    class_id = task["class_id"] if "class_id" in task.keys() else None
    if not parent_id or not class_id:
        return str(task["id"])
    parent = conn.execute(
        "SELECT id FROM learning_tasks WHERE id = ? AND source = 'teacher'",
        (parent_id,),
    ).fetchone()
    return str(parent["id"]) if parent is not None else str(task["id"])


def _content_lock(database_path: str, source_task_id: str) -> threading.Lock:
    """Get the process-local lock that serializes one parent lesson."""

    key = (database_path, source_task_id)
    with _CONTENT_LOCKS_GUARD:
        return _CONTENT_LOCKS.setdefault(key, threading.Lock())


async def _acquire_content_lock(lock: threading.Lock) -> None:
    """Wait without blocking the background event loop used by other tasks."""

    while not lock.acquire(blocking=False):
        await asyncio.sleep(0.005)


def _copy_task_content(
    conn: sqlite3.Connection, source_task_id: str, target_task_id: str
) -> dict[str, Any]:
    """Copy a completed source lesson to one student row exactly once."""

    points, exercises = _content_counts(conn, target_task_id)
    if points or exercises:
        now = utc_now_iso()
        _mark_task_content_done(
            conn,
            target_task_id,
            source=_CONTENT_SOURCE_COPIED,
            now=now,
        )
        conn.commit()
        return {"knowledge_points": points, "exercises": exercises, "status": "done"}
    source_points = conn.execute(
        "SELECT * FROM task_knowledge_points WHERE task_id = ? ORDER BY sort_order, id",
        (source_task_id,),
    ).fetchall()
    source_exercises = conn.execute(
        "SELECT * FROM task_exercises WHERE task_id = ? ORDER BY sort_order, id",
        (source_task_id,),
    ).fetchall()
    if not source_points and not source_exercises:
        _mark_task_content_failed(
            conn,
            target_task_id,
            "源任务尚未生成可复制的学习内容，请稍后重试",
        )
        conn.commit()
        return {"knowledge_points": 0, "exercises": 0, "status": "failed"}
    now = utc_now_iso()
    for point in source_points:
        conn.execute(
            "INSERT INTO task_knowledge_points "
            "(id, task_id, title, content, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                target_task_id,
                point["title"],
                point["content"],
                point["sort_order"],
                now,
                now,
            ),
        )
    for exercise in source_exercises:
        conn.execute(
            "INSERT INTO task_exercises "
            "(id, task_id, question, type, options_json, reference_answer, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                target_task_id,
                exercise["question"],
                exercise["type"],
                exercise["options_json"],
                exercise["reference_answer"],
                exercise["sort_order"],
                now,
            ),
        )
    _mark_task_content_done(
        conn,
        target_task_id,
        source=_CONTENT_SOURCE_COPIED,
        now=now,
    )
    conn.commit()
    return {
        "knowledge_points": len(source_points),
        "exercises": len(source_exercises),
        "status": "done",
    }


async def generate_task_content(
    task_id: str, *, database_path: str | None = None
) -> dict[str, Any]:
    """Generate one lesson, reusing a teacher source for published copies.

    The source worker still calls the configured primary provider immediately;
    only the durable fan-out work is deduplicated.  A process-local lock closes
    the race where several copy workers start before the source rows commit.
    """

    resolved_path = database_path or get_config().resolved_database_path
    conn = db_connect(resolved_path)
    try:
        task = conn.execute("SELECT * FROM learning_tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            return {"knowledge_points": 0, "exercises": 0, "status": "missing"}
        points, exercises = _content_counts(conn, task_id)
        if points or exercises:
            # Content rows are authoritative even if a prior worker crashed
            # before persisting the status marker.
            now = utc_now_iso()
            current_source = (
                str(task["content_generation_source"] or "none")
                if "content_generation_source" in task.keys()
                else "none"
            )
            _mark_task_content_done(
                conn,
                task_id,
                source=current_source if current_source != "none" else _CONTENT_SOURCE_MANUAL,
                now=now,
            )
            conn.commit()
            return {"knowledge_points": points, "exercises": exercises, "status": "done"}
        source_task_id = _content_source_task_id(conn, task)
        lock = _content_lock(resolved_path, source_task_id)
        await _acquire_content_lock(lock)
        try:
            # Re-read after waiting: another copy may have completed while this
            # worker was queued on the same parent lock.
            points, exercises = _content_counts(conn, task_id)
            if points or exercises:
                now = utc_now_iso()
                current_source = (
                    str(task["content_generation_source"] or "none")
                    if "content_generation_source" in task.keys()
                    else "none"
                )
                _mark_task_content_done(
                    conn,
                    task_id,
                    source=current_source if current_source != "none" else _CONTENT_SOURCE_MANUAL,
                    now=now,
                )
                conn.commit()
                return {"knowledge_points": points, "exercises": exercises, "status": "done"}
            if source_task_id == task_id:
                return await _generate_task_content_uncached(task_id, database_path=resolved_path)
            source_counts = _content_counts(conn, source_task_id)
            if not any(source_counts):
                source_result = await _generate_task_content_uncached(
                    source_task_id, database_path=resolved_path
                )
                if source_result.get("status") != "done":
                    _mark_task_content_failed(
                        conn,
                        task_id,
                        "源任务学习内容生成失败，请稍后重试",
                    )
                    conn.commit()
                    return {"knowledge_points": 0, "exercises": 0, "status": "failed"}
            return _copy_task_content(conn, source_task_id, task_id)
        finally:
            lock.release()
    except Exception:
        logger.warning("task content fan-out persistence failed", exc_info=True)
        try:
            _mark_task_content_failed(conn, task_id, "学习内容复制失败，请稍后重试")
            conn.commit()
        except Exception:
            logger.warning(
                "task content fan-out failure status could not be persisted", exc_info=True
            )
        return {"knowledge_points": 0, "exercises": 0, "status": "failed"}
    finally:
        # Release the process-local startup claim after a terminal result so a
        # future force/retry can participate in the same recovery contract.
        _release_content_recovery_claim(conn, task_id)
        conn.close()


PREVIEW_SPEC = ToolSpec(
    name="task.preview",
    permission="read",
    auto_execute=True,
    description="组装学习任务卡预览（不落库）",
    handler=task_preview_handler,
)

CREATE_SPEC = ToolSpec(
    name="task.create",
    permission="write",
    auto_execute=False,
    description="确认后创建学习任务（learning_tasks）",
    preview=task_create_preview,
    apply=task_create_apply,
)
