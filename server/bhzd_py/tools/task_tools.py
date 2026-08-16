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
    title: str, description: str
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Provide a reviewable baseline when an Agent request omits either content field."""

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
    conn.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = ? WHERE id = ?",
        (now, task_id),
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
    conn: sqlite3.Connection, task_id: str, *, force: bool = False
) -> bool:
    """Atomically mark a task for generation without committing its caller's transaction.

    ``force`` is used for a new teacher-task version or an explicit content
    edit.  Normal creation is idempotent: a retry cannot enqueue a second
    worker after the task has already reached ``generating``/``done``.
    """

    try:
        # Claim in one conditional UPDATE.  A SELECT followed by UPDATE lets
        # two request threads both observe ``none`` and enqueue duplicate
        # provider calls before either transaction commits.
        predicate = "id = ?" if force else "id = ? AND COALESCE(content_status, 'none') = 'none'"
        cursor = conn.execute(
            "UPDATE learning_tasks SET content_status = 'generating', "
            "content_generated_at = NULL WHERE " + predicate,
            (task_id,),
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
    _preserve_recovery_claim: bool = False,
) -> bool:
    """Commit a generation marker and enqueue exactly one background worker."""

    if not _preserve_recovery_claim:
        # A normal create/retry supersedes any prior startup claim for this row.
        _release_content_recovery_claim(conn, task_id)
    if not mark_task_content_generating(conn, task_id, force=force):
        return False
    conn.commit()
    database_path = _connection_database_path(conn)
    try:
        schedule_task_content(task_id, database_path=database_path)
    except Exception:
        # A supervisor/loop failure must remain visible and retryable rather
        # than leaving the task permanently stuck in ``generating``.
        logger.warning("task content worker could not be scheduled", exc_info=True)
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'failed' WHERE id = ?",
            (task_id,),
        )
        conn.commit()
        _release_content_recovery_claim(conn, task_id)
        return False
    return True


def _content_json(text: str) -> dict[str, Any] | None:
    """Parse a provider JSON object, tolerating a fenced response."""

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").split("\n", 1)[-1]
    try:
        payload = json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
            conn.execute(
                "UPDATE learning_tasks SET content_status = 'done', "
                "content_generated_at = COALESCE(content_generated_at, ?) "
                "WHERE id = ?",
                (now, task_id),
            )
            conn.commit()
            return {
                "knowledge_points": int(existing_counts["points"]),
                "exercises": int(existing_counts["exercises"]),
                "status": "done",
            }
        now = utc_now_iso()
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'generating' WHERE id = ?",
            (task_id,),
        )
        conn.commit()
        title = str(task["title"] or "学习任务")
        description = str(task["goal"] or "").strip()
        cap_ids = json.loads(task["cap_ids_json"] or "[]")
        cap_text = ", ".join(str(item) for item in cap_ids) if isinstance(cap_ids, list) else ""
        knowledge_points: list[dict[str, Any]] = []
        exercises: list[dict[str, Any]] = []
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
                            f"能力节点：{cap_text}"
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
        except Exception:
            logger.warning("task content provider failed; using deterministic draft", exc_info=True)

        default_points, default_exercises = _default_task_content(title, description)
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
            conn.execute(
                "UPDATE learning_tasks SET content_status = 'done', "
                "content_generated_at = COALESCE(content_generated_at, ?) "
                "WHERE id = ?",
                (now, task_id),
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
        )
        conn.commit()
        return result
    except Exception:
        logger.warning("task content persistence failed", exc_info=True)
        try:
            conn.execute(
                "UPDATE learning_tasks SET content_status = 'failed' WHERE id = ?",
                (task_id,),
            )
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
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'done', "
            "content_generated_at = COALESCE(content_generated_at, ?) "
            "WHERE id = ?",
            (now, target_task_id),
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
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'failed' WHERE id = ?",
            (target_task_id,),
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
    conn.execute(
        "UPDATE learning_tasks SET content_status = 'done', content_generated_at = ? WHERE id = ?",
        (now, target_task_id),
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
            conn.execute(
                "UPDATE learning_tasks SET content_status = 'done', "
                "content_generated_at = COALESCE(content_generated_at, ?) "
                "WHERE id = ?",
                (now, task_id),
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
                conn.execute(
                    "UPDATE learning_tasks SET content_status = 'done', "
                    "content_generated_at = COALESCE(content_generated_at, ?) "
                    "WHERE id = ?",
                    (now, task_id),
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
                    conn.execute(
                        "UPDATE learning_tasks SET content_status = 'failed' WHERE id = ?",
                        (task_id,),
                    )
                    conn.commit()
                    return {"knowledge_points": 0, "exercises": 0, "status": "failed"}
            return _copy_task_content(conn, source_task_id, task_id)
        finally:
            lock.release()
    except Exception:
        logger.warning("task content fan-out persistence failed", exc_info=True)
        try:
            conn.execute(
                "UPDATE learning_tasks SET content_status = 'failed' WHERE id = ?",
                (task_id,),
            )
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
