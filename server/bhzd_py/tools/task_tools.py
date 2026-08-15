"""task.preview（read）与 task.create（write，确认门）（蓝图 §9）。

任务卡内容是**确定性组装**：标题/目标/步骤/评分规则来自参数与数据
（课程检索、图谱节点名），不由 LLM 生成——LLM 只负责在最终消息里
解释这张卡（PRD-06 §6.1：Agent 可生成任务卡预览，但不可编造规范）。
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

# Task scoring persists a list of {key, expected, weight, hint?}. Keeping the
# default in that same shape prevents Agent-created tasks from storing a visual
# rubric object that the task page and deterministic scorer cannot consume.
_DEFAULT_RUBRIC: list[dict[str, Any]] = [
    {
        "key": "规范符合性",
        "expected": "符合规范定义",
        "weight": 60,
        "hint": "逐项核对规范定义和示例。",
    },
    {
        "key": "完整性",
        "expected": "完整无遗漏",
        "weight": 40,
        "hint": "检查边界、字段和必填项是否遗漏。",
    },
]


def _cap_names(cap_ids: list[str]) -> list[dict[str, str]]:
    """cap_id → 名称（graphx 惰性查询；未就绪时以 id 代名称，不阻断组卡）。"""
    try:
        from ..graphx import reason as gx_reason  # B4，惰性导入
    except ImportError:
        gx_reason = None
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


def _task_rubric(raw: Any) -> list[dict[str, Any]]:
    """规范化 Agent 输入及旧版 rules 对象为任务评分器需要的列表契约。"""
    candidates = raw
    if isinstance(raw, dict):
        candidates = raw.get("rules")
    if not isinstance(candidates, list):
        return [dict(item) for item in _DEFAULT_RUBRIC]

    rubric: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = item.get("key") or item.get("criterion") or item.get("rule")
        if key is None or not str(key).strip():
            continue
        # Older cards call these description/score; normalize them once before
        # persistence so the student page and scorer share one stable shape.
        expected = item.get("expected", item.get("description", item.get("rule", str(key))))
        weight = item.get("weight", item.get("points", item.get("score", 1.0)))
        rubric.append(
            {
                "key": str(key),
                "expected": expected,
                "weight": weight,
                **({"hint": str(item["hint"])} if item.get("hint") is not None else {}),
            }
        )
    return rubric or [dict(item) for item in _DEFAULT_RUBRIC]


def build_task_card(args: dict[str, Any]) -> dict[str, Any]:
    """组装 TaskCard（不落库）。步骤至少 2 步（契约要求）。"""
    data_type = args.get("data_type")
    label = _DATA_TYPE_LABELS.get(data_type or "", "")
    title = args.get("title") or (f"{label}标注练习任务" if label else "标注练习任务")
    goal = args.get("goal") or "掌握该任务对应的标注规范并能独立完成练习"
    cap_ids = list(args.get("cap_ids") or [])
    steps = args.get("steps") or [
        {"title": "学习规范", "description": "阅读关联资料与教学单元，明确标注规则"},
        {"title": "完成练习", "description": "按规范完成一组标注练习样本"},
        {"title": "自查常见错误", "description": "对照评分规则自查并修正"},
    ]
    rubric = _task_rubric(args.get("rubric"))
    return {
        "title": title,
        "goal": goal,
        "data_type": data_type,
        "cap_ids": cap_ids,
        "cap_names": _cap_names(cap_ids),
        "steps": steps if len(steps) >= 2 else steps + [{"title": "完成练习", "description": "按规范完成练习"}],
        "est_minutes": args.get("est_minutes") or 45,
        "rubric": rubric,
    }


def task_preview_handler(ctx: ToolContext) -> dict[str, Any]:
    card = build_task_card(ctx.args)
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_preview_created",
        {
            "data_type": card.get("data_type"),
            "cap_count": len(card.get("cap_ids") or []),
        },
    )
    return {"card": card}


def task_create_preview(ctx: ToolContext) -> dict[str, Any]:
    """确认门预览载荷：展示将创建的任务卡全文（PRD-06 §6.4：名称/目标/步骤/关联能力）。"""
    card = build_task_card(ctx.args)
    return {
        "action": "task.create",
        "summary": f"将创建学习任务「{card['title']}」",
        "card": card,
    }


def task_create_apply(ctx: ToolContext) -> dict[str, Any]:
    """确认后写 learning_tasks（source 默认 agent；状态 not_started）。"""
    card = build_task_card(ctx.args)
    task_id = uuid.uuid4().hex
    now = utc_now_iso()
    counts_toward_mastery = 1 if ctx.args.get("counts_toward_mastery", True) else 0
    source = ctx.args.get("source") or "agent"
    if source not in ("agent", "preset", "teacher", "diagnostic"):
        source = "agent"
    ctx.db.execute(
        """
        INSERT INTO learning_tasks
          (id, user_id, title, goal, data_type, cap_ids_json,
           source, status, steps_json, resources_json, rubric_json,
           counts_toward_mastery, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            ctx.user_row["id"],
            card["title"],
            card["goal"],
            card.get("data_type"),
            json.dumps(card["cap_ids"], ensure_ascii=False),
            source,
            json.dumps(card["steps"], ensure_ascii=False),
            # The legacy column remains in the schema, but current Agent tasks
            # intentionally have no catalog attachment.
            "[]",
            json.dumps(card["rubric"], ensure_ascii=False),
            counts_toward_mastery,
            ctx.user_row["id"],
            now,
            now,
        ),
    )
    ctx.db.commit()
    # The confirmation write is complete before content generation is queued;
    # this keeps the worker on the durable background loop from racing an
    # uncommitted task row while still returning the task immediately.
    queue_task_content(ctx.db, task_id)
    emit_telemetry(
        ctx.db,
        ctx.user_row["id"],
        "task_created",
        {"task_id": task_id, "source": source},
    )
    return {"task_id": task_id, "title": card["title"], "card": card}


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
                        "content": f"任务：{title}\n能力节点：{cap_text}",
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

        if not knowledge_points:
            knowledge_points = [
                {
                    "title": f"{title}核心概念",
                    "content": f"围绕 {title} 梳理定义、步骤和常见错误。",
                }
            ]
        if not exercises:
            exercises = [
                {
                    "question": f"请用自己的话说明完成“{title}”时最重要的检查点。",
                    "type": "open_ended",
                    "options": None,
                    "reference_answer": "应覆盖任务目标、关键步骤和质量检查点。",
                }
            ]

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

        for index, item in enumerate(knowledge_points):
            conn.execute(
                "INSERT INTO task_knowledge_points "
                "(id, task_id, title, content, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    task_id,
                    str(item["title"])[:200],
                    str(item["content"])[:8000],
                    index,
                    now,
                    now,
                ),
            )
        for index, item in enumerate(exercises):
            options = item.get("options")
            conn.execute(
                "INSERT INTO task_exercises "
                "(id, task_id, question, type, options_json, reference_answer, sort_order, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    task_id,
                    str(item["question"])[:4000],
                    str(item.get("type") or "open_ended"),
                    json.dumps(options, ensure_ascii=False) if isinstance(options, list) else None,
                    str(item.get("reference_answer") or "")[:4000],
                    index,
                    now,
                ),
            )
        conn.execute(
            "UPDATE learning_tasks SET content_status = 'done', "
            "content_generated_at = ? WHERE id = ?",
            (now, task_id),
        )
        conn.commit()
        return {
            "knowledge_points": len(knowledge_points),
            "exercises": len(exercises),
            "status": "done",
        }
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
        "UPDATE learning_tasks SET content_status = 'done', "
        "content_generated_at = ? WHERE id = ?",
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
                return await _generate_task_content_uncached(
                    task_id, database_path=resolved_path
                )
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
            logger.warning("task content fan-out failure status could not be persisted", exc_info=True)
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
