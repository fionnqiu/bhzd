"""Agent 编排器：意图 → 计划 → 工具循环 → SSE 的状态机（蓝图 §10）。

关键约束（为什么这么写）：
- execute_run / continue_run 由 spawn() 投递到**进程级后台 loop**（独立守护
  线程）并从 db_path 自开连接——Starlette TestClient 每个请求一个独立
  portal（响应结束 loop 即关闭，其上 create_task 的任务会被取消），
  uvicorn 重载同理；编排是跨请求存活的状态机，必须比请求活得久。
- 写工具永远不在编排器里 apply：编排器只生成 preview + 确认记录并
  STOP（PRD-06 §6.1 未确认不得写入）；apply 由 confirmations 路由在
  用户确认后同步执行，再以 continue_run 续跑计划。
- 所有跨域依赖（providers/graphx/rag/...）都在工具或 composer 内惰性
  导入，本模块自身零硬依赖，离线可测。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from typing import Any, Awaitable, Callable, Coroutine

from ..config import get_config
from ..db import connect, utc_now_iso
from ..tools import registry
from ..tools.registry import ToolContext
from . import composer, conversation_memory, events, intents, prompts

logger = logging.getLogger(__name__)

# 确认门过期时间（PRD-06 §6.4）：普通写 30min；删除/归档 10min
_CONFIRM_TTL_SECONDS = 30 * 60
_ARCHIVE_TTL_SECONDS = 10 * 60
_ARCHIVE_ACTIONS = {"rag.archive_document"}

_MESSAGE_CHUNK = 40  # message.delta 单帧上限（契约：≤40 字符）

_RUN_TERMINAL = ("completed", "failed", "cancelled")

# 运行失败给学生看的统一中文文案（堆栈只进服务端日志，PRD-01 §3.5）
_GENERIC_ERROR = "处理本次请求时出现问题，请稍后重试"


# ---------------------------------------------------------------------------
# 后台执行：进程级事件循环 + 守护线程
# ---------------------------------------------------------------------------

_BG_LOOP: asyncio.AbstractEventLoop | None = None
_BG_LOCK = threading.Lock()
# 持有 future 引用，避免 GC 提前回收未完成任务
_BG_FUTURES: set[Any] = set()


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    global _BG_LOOP
    with _BG_LOCK:
        if _BG_LOOP is None or _BG_LOOP.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="bhzd-agent-bg", daemon=True
            )
            thread.start()
            _BG_LOOP = loop
    return _BG_LOOP


def spawn(coro: Coroutine[Any, Any, None]) -> None:
    """把编排协程投递到后台 loop（替代请求 loop 上的 asyncio.create_task）。

    见模块 docstring：TestClient 的 per-request portal 会在响应结束时
    取消挂起任务，编排必须独立于请求生命周期。
    """
    loop = _ensure_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    _BG_FUTURES.add(future)
    future.add_done_callback(_BG_FUTURES.discard)


# ---------------------------------------------------------------------------
# 行加载与消息持久化
# ---------------------------------------------------------------------------

def _load_run_context(db: sqlite3.Connection, run_id: str):
    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(f"run 不存在: {run_id}")
    conv = db.execute(
        "SELECT * FROM conversations WHERE id = ?", (run["conversation_id"],)
    ).fetchone()
    user = db.execute("SELECT * FROM users WHERE id = ?", (run["user_id"],)).fetchone()
    return run, conv, user


def _load_latest_clarification(
    db: sqlite3.Connection, run: sqlite3.Row
) -> intents.ClarificationState | None:
    """Return only the immediately preceding completed clarification in this chat.

    A short answer is meaningful only as a continuation of the latest completed
    run.  Ordering by SQLite's insertion rowid avoids timestamp ties in quick
    successive requests and deliberately prevents an older clarification from
    leaking through a newer, unrelated completed request.
    """

    previous = db.execute(
        """
        SELECT status, plan_json
        FROM agent_runs
        WHERE conversation_id = ?
          AND rowid < (SELECT rowid FROM agent_runs WHERE id = ?)
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (run["conversation_id"], run["id"]),
    ).fetchone()
    # Never skip a newer failed or confirmation-waiting run to revive an older
    # question: only the directly preceding completed clarification is safe.
    if previous is None or previous["status"] != "completed" or not previous["plan_json"]:
        return None
    try:
        payload = json.loads(previous["plan_json"])
    except json.JSONDecodeError:
        return None
    return intents.ClarificationState.from_payload(payload.get("clarification"))


def _context_values(
    run: sqlite3.Row, conversation: sqlite3.Row | None
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return run and conversation selections without losing their priority.

    Clarification state sits between the two sources, so collapsing them early
    would incorrectly let an older conversation override a just-answered slot.
    """

    conversation_data_type = conversation["data_type"] if conversation else None
    conversation_scenario = conversation["scenario_id"] if conversation else None
    return (
        run["data_type"],
        run["scenario_id"],
        conversation_data_type,
        conversation_scenario,
    )


def _resolve_initial_intent(
    db: sqlite3.Connection,
    run: sqlite3.Row,
    conversation: sqlite3.Row | None,
    attachment: dict[str, Any] | None,
) -> tuple[intents.Intent, str]:
    """Detect this input, optionally resume one clarification, then apply scope.

    ``resume_clarification`` accepts a recognized learn-goal phrase only when
    the persisted question explicitly awaits that goal.  A scoped request such
    as ``我想学图像标注`` intentionally starts cleanly instead.
    """

    detected = intents.detect(
        run["input_text"],
        has_attachment=bool(attachment and attachment.get("diagnostic_token")),
    )
    goal_text = run["input_text"]
    previous = _load_latest_clarification(db, run)
    resumed = False
    if previous is not None:
        continuation = intents.resume_clarification(
            previous, detected, run["input_text"]
        )
        if continuation is not None:
            detected, goal_text = continuation
            resumed = True
    run_data_type, run_scenario_id, conversation_data_type, conversation_scenario_id = (
        _context_values(run, conversation)
    )
    # Scope precedence is explicit run > clarification > conversation > current
    # input.  A fresh recognized intent deliberately skips the clarification
    # tier, which is what prevents a new request from inheriting old slots.
    resolved = intents.apply_context(
        detected,
        data_type=conversation_data_type,
        scenario_id=conversation_scenario_id,
        prefer_context=not resumed,
    )
    resolved = intents.apply_context(
        resolved,
        data_type=run_data_type,
        scenario_id=run_scenario_id,
        prefer_context=True,
    )
    return resolved, goal_text


def _persist_message(
    db: sqlite3.Connection, conversation_id: str, run_id: str | None,
    role: str, content: str,
) -> str:
    message_id = uuid.uuid4().hex
    created_at = utc_now_iso()
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, conversation_id, run_id, role, content, created_at),
    )
    db.commit()
    owner = db.execute(
        "SELECT user_id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if owner is not None:
        # Index only after the source message commits, so memory can never
        # reference a message that failed durable persistence.
        conversation_memory.index_message(
            db,
            message_id=message_id,
            user_id=owner["user_id"],
            conversation_id=conversation_id,
            run_id=run_id,
            role=role,
            content=content,
            created_at=created_at,
        )
    return message_id


def _load_chat_history(
    db: sqlite3.Connection, conversation_id: str, *, limit: int = 30
) -> list[dict[str, str]]:
    """Return the most recent persisted chat turns for one conversation."""

    rows = db.execute(
        """
        SELECT role, content FROM messages
        WHERE conversation_id = ? AND role IN ('user', 'assistant', 'system')
        ORDER BY created_at ASC, rowid ASC
        """,
        (conversation_id,),
    ).fetchall()
    return [
        {"role": row["role"], "content": row["content"]}
        for row in rows[-limit:]
    ]


def _update_run(
    db: sqlite3.Connection, run_id: str, *, commit: bool = True, **fields: Any
) -> None:
    """Update agent_runs using internal column names only."""
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.execute(
        f"UPDATE agent_runs SET {assignments} WHERE id = ?",
        (*fields.values(), run_id),
    )
    if commit:
        db.commit()


def _finalize_run(
    db: sqlite3.Connection,
    run_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
    error: str | None = None,
) -> None:
    """Commit a terminal run state together with its replayable SSE event.

    The SSE reader uses a separate SQLite connection. Keeping the run row and
    terminal event in one transaction means recovery cannot observe an emitted
    completion while the corresponding run still reports ``running``.
    """

    fields: dict[str, Any] = {"status": status, "completed_at": utc_now_iso()}
    if error is not None:
        fields["error"] = error
    _update_run(db, run_id, commit=False, **fields)
    events.emit(db, run_id, event_type, payload, commit=False)
    db.commit()


async def _emit_message_delta(
    db: sqlite3.Connection, run_id: str, delta: str
) -> None:
    """Persist a provider chunk before asking it for the next chunk.

    Keeping the commit inside the iteration is intentional: the SSE endpoint
    reads durable events from a separate SQLite connection, so batching until
    completion would make a provider stream look like a single final reply.
    """

    for index in range(0, len(delta), _MESSAGE_CHUNK):
        events.emit(
            db,
            run_id,
            events.MESSAGE_DELTA,
            {"delta": delta[index:index + _MESSAGE_CHUNK]},
        )
        await asyncio.sleep(0)


async def _emit_assistant_text(
    db: sqlite3.Connection, run_id: str, conversation_id: str, text: str
) -> None:
    """Emit a finished fallback reply and persist its single chat record."""

    await _emit_message_delta(db, run_id, text)
    _persist_message(db, conversation_id, run_id, "assistant", text)


def _emit_progress(
    db: sqlite3.Connection,
    run_id: str,
    *,
    phase: str,
    status: str,
    title: str,
    detail: str | None = None,
) -> None:
    """Publish a bounded, replayable progress update for this run."""

    # Intent classification is an internal decision, not an observable action.
    # Keep this boundary here so a future orchestration branch cannot restore a
    # student-visible thinking frame by accidentally reusing this helper.
    if phase == "understanding":
        return

    # Only observable plan and response lifecycles get a stable learner-facing
    # key. Tool calls have their own IDs, while retrieval/system details remain
    # transport-only; model interpretation is deliberately never persisted as
    # a student-visible progress activity.
    activity_id = f"planning:{run_id}" if phase == "planning" else None
    if phase == "synthesis":
        activity_id = f"answer:{run_id}"
    events.emit_progress(
        db,
        run_id,
        phase=phase,
        status=status,
        title=title,
        detail=detail,
        activity_id=activity_id,
    )


# ---------------------------------------------------------------------------
# 计划构建（蓝图 §10.3 计划边界 / PRD-06 §6.3）
# ---------------------------------------------------------------------------

def _build_plan(
    intent: intents.Intent,
    run: sqlite3.Row,
    conversation: sqlite3.Row | None,
    attachment: dict[str, Any] | None,
    *,
    goal_text: str | None = None,
) -> list[dict[str, Any]]:
    """按意图生成确定性计划。步骤：{id,title,tool,args,status}。

    ``goal_text`` preserves the first-turn task wording when a later short
    clarification answer supplies only a missing slot such as a scenario.
    """

    question = goal_text or run["input_text"]
    # ``_resolve_initial_intent`` has already applied run > clarification >
    # conversation > current-input precedence.  Re-applying conversation here
    # would overwrite a just-answered clarification slot.
    scenario_id = intent.scenario_id
    data_type = intent.data_type

    def step(idx: int, title: str, tool: str, args: dict) -> dict[str, Any]:
        return {"id": f"s{idx}", "title": title, "tool": tool,
                "args": args, "status": "pending"}

    if intent.kind == intents.KIND_RAG_QUESTION:
        # 纯问答 ≤3 步（蓝图 §10.3）
        return [
            step(1, "召回相关资料", "rag.search",
                 {"query": question,
                  "filters": {"data_type": data_type, "scenario_id": scenario_id}}),
            step(2, "基于资料生成回答", "rag.answer",
                 {"question": question, "scenario_id": scenario_id,
                  "data_type": data_type}),
        ]

    if intent.kind == intents.KIND_AGENT_IDENTITY:
        # Identity turns complete through direct chat before planning. Preserve
        # the empty result here so a future caller cannot fall into task/RAG.
        return []

    if intent.kind == intents.KIND_DIAGNOSE_UPLOAD:
        token = (attachment or {}).get("diagnostic_token")
        # 诊断 ≥ [格式校验/规则诊断(缓存报告), 补强路径, 保存摘要]
        return [
            step(1, "读取诊断报告", "diagnostic.preview",
                 {"diagnostic_token": token}),
            step(2, "生成补强路径", "graph.reason",
                 {"action": "pre_path", "target_id": None}),
            step(3, "保存诊断摘要与掌握度", "diagnostic.save_summary",
                 {"diagnostic_token": token}),
        ]

    # learn_goal / preset_start / task_convert / teacher_task：
    # 任务转化 ≥ [RAG 召回, 图谱定位, 任务卡生成]（蓝图 §10.3）
    source = {
        intents.KIND_PRESET_START: "preset",
        intents.KIND_TEACHER_TASK: "teacher",
    }.get(intent.kind, "agent")
    label = {"text": "文本", "image": "图像", "audio": "语音",
             "video": "视频"}.get(data_type or "", "")
    title = f"{label}标注练习任务" if label else "标注练习任务"
    task_args = {
        "title": title,
        "goal": question,
        "data_type": data_type,
        "scenario_id": scenario_id,
    }
    return [
        step(1, "检索相关规范资料", "rag.search",
             {"query": question,
              "filters": {"data_type": data_type, "scenario_id": scenario_id}}),
        step(2, "定位关联能力", "graph.reason",
             {"action": "locate", "query": question, "data_type": data_type,
              "scenario_id": scenario_id}),
        step(3, "生成任务卡预览", "task.preview", dict(task_args)),
        step(4, "创建学习任务", "task.create", {**task_args, "source": source}),
    ]


def _enrich_step_args(
    step: dict[str, Any], steps: list[dict[str, Any]],
    results: dict[str, Any],
) -> None:
    """把上游步骤结果注入当前步骤参数（计划数据流）。

    - task.preview/task.create：补 RAG 命中的资源与图谱定位到的 cap_ids；
    - graph.reason(pre_path)：补诊断报告里的首个薄弱能力作为 target_id。
    只填缺省值，不覆盖计划构建时已有的显式参数。
    """
    tool = step["tool"]
    args = step["args"]
    if tool in ("task.preview", "task.create"):
        if not args.get("cap_ids"):
            for other in steps:
                if other["tool"] == "graph.reason":
                    caps = (results.get(other["id"]) or {}).get("cap_ids")
                    if caps:
                        args["cap_ids"] = caps
        if not args.get("resources"):
            for other in steps:
                if other["tool"] == "rag.search":
                    hits = (results.get(other["id"]) or {}).get("hits") or []
                    resources = []
                    for hit in hits[:3]:
                        if isinstance(hit, dict):
                            resources.append({
                                "type": "rag",
                                "title": hit.get("title")
                                or hit.get("document_title") or "召回资料",
                                "ref_id": hit.get("document_id"),
                            })
                    if resources:
                        args["resources"] = resources
    elif tool == "graph.reason" and args.get("action") == "pre_path":
        if not args.get("target_id"):
            for other in steps:
                if other["tool"] == "diagnostic.preview":
                    report = (results.get(other["id"]) or {}).get("report") or {}
                    weak = report.get("weak_cap_ids") or []
                    if weak:
                        args["target_id"] = weak[0]


# ---------------------------------------------------------------------------
# 工具执行（读直跑 / 写确认门）
# ---------------------------------------------------------------------------

def _confirmation_ttl(tool_name: str) -> int:
    return _ARCHIVE_TTL_SECONDS if tool_name in _ARCHIVE_ACTIONS else _CONFIRM_TTL_SECONDS


def _insert_tool_call(
    db: sqlite3.Connection, run_id: str, spec_name: str, permission: str,
    args: dict, status: str = "requested",
) -> str:
    tool_call_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO tool_calls
          (id, run_id, tool_name, permission, status, args_json, is_write, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tool_call_id, run_id, spec_name, permission, status,
            json.dumps(args, ensure_ascii=False, default=str),
            1 if permission == "write" else 0,
            utc_now_iso(),
        )
    )
    db.commit()
    return tool_call_id


def _make_ctx(db, config, user, run, conv, args) -> ToolContext:
    return ToolContext(db=db, config=config, user_row=user, run_row=run,
                       conversation_row=conv, args=args)


def _execute_read_step(
    db, config, user, run, conv, step, spec
) -> Any:
    """执行读工具并发布可回放的安全生命周期事件。

    The database keeps the original arguments/results for the planner, while
    SSE receives only the execution kind and bounded summaries.  This is the
    contract the cockpit uses to show real work without exposing prompts or
    provider payloads.
    """
    input_summary = events.summarize_tool_input(step["args"], title=step["title"])
    execution_kind = events.execution_kind(spec.name)
    tool_call_id = _insert_tool_call(db, run["id"], spec.name, "read", step["args"])
    step["tool_call_id"] = tool_call_id
    _emit_progress(
        db,
        run["id"],
        phase="tool",
        status="running",
        title=f"正在执行：{step['title']}",
        detail=f"调用只读工具 {spec.name}",
    )
    if spec.name == "rag.search":
        _emit_progress(
            db,
            run["id"],
            phase="retrieval",
            status="running",
            title="正在检索相关资料",
            detail="正在从知识库中查找匹配内容",
        )
    events.emit(db, run["id"], events.TOOL_CALL_REQUESTED, {
        "tool_call_id": tool_call_id, "tool": spec.name,
        "permission": "read",
        "execution_kind": execution_kind,
        "input_summary": input_summary,
        # Keep the legacy key for older clients; both values are already safe.
        "args_summary": input_summary,
    })
    ctx = _make_ctx(db, config, user, run, conv, step["args"])
    started = time.perf_counter()
    status = "completed"
    try:
        result = spec.handler(ctx)
        if isinstance(result, dict) and result.get("error"):
            # 工具以中文错误字典表达失败（如"图谱模块未就绪"），不抛异常
            status = "failed"
    except Exception:
        logger.exception("读工具 %s 执行异常", spec.name)
        result = {"error": _GENERIC_ERROR}
        status = "failed"
    duration_ms = int((time.perf_counter() - started) * 1000)
    db.execute(
        """
        UPDATE tool_calls SET status = ?, result_json = ?, duration_ms = ?,
               completed_at = ? WHERE id = ?
        """,
        (status, json.dumps(result, ensure_ascii=False, default=str),
         duration_ms, utc_now_iso(), tool_call_id),
    )
    db.commit()
    events.emit(db, run["id"], events.TOOL_CALL_COMPLETED, {
        "tool_call_id": tool_call_id, "tool": spec.name, "status": status,
        "duration_ms": duration_ms,
        "is_write": 0,
        "execution_kind": execution_kind,
        "output_summary": events.summarize_tool_result(result, status=status),
        # Result cards still need a typed payload.  Redaction happens before
        # the event crosses the SSE boundary; the private DB keeps raw JSON.
        "result": events.public_tool_result(spec.name, result),
    })
    _emit_progress(
        db,
        run["id"],
        phase="tool",
        status=status,
        title=(f"已完成：{step['title']}" if status == "completed"
               else f"未完成：{step['title']}"),
        detail=f"只读工具 {spec.name}，耗时 {duration_ms} ms",
    )
    if spec.name == "rag.search":
        hit_count = result.get("hit_count", 0) if isinstance(result, dict) else 0
        safe_hit_count = hit_count if isinstance(hit_count, int) and hit_count >= 0 else 0
        _emit_progress(
            db,
            run["id"],
            phase="retrieval",
            status=status,
            title=("资料检索完成" if status == "completed" else "资料检索未完成"),
            detail=f"找到 {safe_hit_count} 条相关资料，耗时 {duration_ms} ms",
        )
    step["status"] = "completed" if status == "completed" else "failed"
    return result


def _open_write_gate(db, config, user, run, conv, step, spec) -> bool:
    """写工具确认门：生成预览 + pending_confirmations 行，run 转入等待。

    返回 True 表示已停在确认门；preview 自身失败（如角色不足/前置状态
    不满足）时按步骤失败处理并返回 False 让计划继续收尾。
    """
    input_summary = events.summarize_tool_input(step["args"], title=step["title"])
    execution_kind = events.execution_kind(spec.name)
    tool_call_id = _insert_tool_call(db, run["id"], spec.name, "write", step["args"])
    step["tool_call_id"] = tool_call_id
    _emit_progress(
        db,
        run["id"],
        phase="tool",
        status="running",
        title=f"正在准备：{step['title']}",
        detail=f"准备写入工具 {spec.name} 的确认预览",
    )
    events.emit(db, run["id"], events.TOOL_CALL_REQUESTED, {
        "tool_call_id": tool_call_id, "tool": spec.name,
        "permission": "write",
        "execution_kind": execution_kind,
        "input_summary": input_summary,
        "args_summary": input_summary,
    })
    ctx = _make_ctx(db, config, user, run, conv, step["args"])
    try:
        preview_payload = spec.preview(ctx)
    except Exception:
        logger.exception("写工具 %s 预览生成异常", spec.name)
        preview_payload = {"error": _GENERIC_ERROR}
    if isinstance(preview_payload, dict) and preview_payload.get("error"):
        db.execute(
            "UPDATE tool_calls SET status = 'failed', result_json = ?, "
            "completed_at = ? WHERE id = ?",
            (json.dumps(preview_payload, ensure_ascii=False),
             utc_now_iso(), tool_call_id),
        )
        db.commit()
        events.emit(db, run["id"], events.TOOL_CALL_COMPLETED, {
            "tool_call_id": tool_call_id, "tool": spec.name, "status": "failed",
            "duration_ms": 0,
            "is_write": 1,
            "execution_kind": execution_kind,
            "output_summary": events.summarize_tool_result(
                preview_payload, status="failed"
            ),
            "result": events.public_tool_result(spec.name, preview_payload),
        })
        _emit_progress(
            db,
            run["id"],
            phase="tool",
            status="failed",
            title=f"未完成：{step['title']}",
            detail=f"写入工具 {spec.name} 未能生成确认预览",
        )
        step["status"] = "failed"
        return False

    confirmation_id = uuid.uuid4().hex
    now = utc_now_iso()
    expires_at = _iso_after_seconds(_confirmation_ttl(spec.name))
    db.execute(
        """
        INSERT INTO pending_confirmations
          (id, run_id, user_id, tool_call_id, action_type, preview_json,
           status, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (confirmation_id, run["id"], user["id"], tool_call_id, spec.name,
         json.dumps(preview_payload, ensure_ascii=False, default=str),
         expires_at, now),
    )
    db.execute(
        "UPDATE tool_calls SET status = 'awaiting_confirmation' WHERE id = ?",
        (tool_call_id,),
    )
    _update_run(db, run["id"], status="waiting_confirmation")
    db.commit()
    step["status"] = "waiting"
    _emit_progress(
        db,
        run["id"],
        phase="tool",
        status="waiting_confirmation",
        title=f"等待确认：{step['title']}",
        detail="该操作会写入学习数据，确认前不会执行",
    )
    events.emit(db, run["id"], events.CONFIRMATION_REQUIRED, {
        "confirmation": {
            "id": confirmation_id,
            "run_id": run["id"],
            "tool_call_id": tool_call_id,
            "action_type": spec.name,
            # Preview cards are intentionally typed, but their values still
            # pass through the same event redaction boundary as tool results.
            "preview": events.redact_tool_payload(preview_payload),
            "status": "pending",
            "expires_at": expires_at,
            "created_at": now,
        }
    })
    # A write tool has reached a real lifecycle boundary, but has not executed
    # yet.  Emitting this state lets the UI show "waiting for confirmation"
    # without pretending that the write already happened.
    events.emit(db, run["id"], events.TOOL_CALL_COMPLETED, {
        "tool_call_id": tool_call_id,
        "tool": spec.name,
        "status": "awaiting_confirmation",
        "duration_ms": 0,
        "is_write": 1,
        "execution_kind": execution_kind,
        "output_summary": "等待确认，尚未执行写入",
    })
    return True


def _iso_after_seconds(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# 收尾：最终 assistant 消息 + run.completed / run.failed
# ---------------------------------------------------------------------------


def _needs_general_knowledge_fallback(
    steps: list[dict[str, Any]], results: dict[str, Any]
) -> bool:
    """Return whether a knowledge-question run lacks usable RAG evidence.

    ``rag.search`` also appears in task-planning runs, where a weak search must
    not turn task creation into an ungrounded answer.  A ``rag.answer`` step is
    therefore the explicit boundary that identifies the knowledge-question flow.
    Tool errors are excluded: an unavailable RAG subsystem is not proof that the
    knowledge base lacks material, while an explicit refusal or an empty/weak
    successful retrieval is.
    """

    rag_answer_steps = [step for step in steps if step.get("tool") == "rag.answer"]
    if not rag_answer_steps:
        return False

    for step in rag_answer_steps:
        result = results.get(step.get("id"))
        if isinstance(result, dict) and result.get("refused") is True:
            return True

    # A later answer with real citations is authoritative over a stale or
    # independently re-run search result.  This protects the normal grounded
    # path when the corpus changes between the two read-tool calls.
    if any(
        isinstance(results.get(step.get("id")), dict)
        and results[step["id"]].get("answer")
        and results[step["id"]].get("citations")
        for step in rag_answer_steps
    ):
        return False

    for step in steps:
        if step.get("tool") != "rag.search":
            continue
        result = results.get(step.get("id"))
        if not isinstance(result, dict) or result.get("error"):
            continue
        if result.get("below_threshold") is True:
            return True
        hits = result.get("hits")
        if isinstance(hits, list) and not hits:
            return True
        if result.get("hit_count") == 0:
            return True
    return False


async def _compose_final_text(
    user_input: str,
    steps: list[dict[str, Any]],
    results: dict[str, Any],
    *,
    private_memory_context: str | None = None,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any] | None, str]:
    """LLM 可用→流式/整段合成；不可用→模板渲染工具结果（PRD-06 §11.1）。

    流式失败的补偿：stream_text 若中段异常，composer 已记录日志并停止，
    此时已产出的增量仍被使用（不回退模板，避免同一条消息重复出现）。
    """
    use_general_knowledge = _needs_general_knowledge_fallback(steps, results)
    messages = (
        composer.build_general_knowledge_messages(user_input, private_memory_context)
        if use_general_knowledge
        else composer.build_compose_messages(user_input, results)
    )
    usage_capture = composer.UsageCapture()
    streamed: list[str] = []
    async for delta in composer.stream_text(messages, usage_capture=usage_capture):
        streamed.append(delta)
        if on_delta is not None:
            # The callback persists the chunk before this iterator requests the
            # next one, which is what makes final-composition output live.
            await on_delta(delta)
    if streamed:
        text = "".join(streamed)
        return text, usage_capture.value, composer.compact_summary(text)
    text = await composer.compose_text(messages, usage_capture=usage_capture)
    if text:
        return text, usage_capture.value, composer.compact_summary(text)
    if use_general_knowledge:
        # The RAG tool explicitly established insufficient evidence, so its
        # refusal is not an acceptable substitute after both model roles fail.
        # Returning a separate availability message keeps the source claim
        # truthful and avoids attaching a general-knowledge disclosure without
        # an actual model answer.
        unavailable = prompts.GENERAL_KNOWLEDGE_UNAVAILABLE
        return (
            unavailable,
            usage_capture.value,
            composer.compact_summary(unavailable),
        )
    plan = {"steps": steps}
    # 单工具结果的问答轮用工具摘要（含答案原文），多步任务轮用计划总结
    rag_answer = next(
        (results[s["id"]] for s in steps
         if s["tool"] == "rag.answer" and results.get(s["id"])),
        None,
    )
    if rag_answer is not None:
        base = composer.template_tool_summary("rag.answer", rag_answer)
        others = [s for s in steps
                  if s["tool"] != "rag.answer" and s["status"] == "failed"]
        if others:
            base += "\n" + composer.template_plan_summary(
                {"steps": others}, results)
        return base, usage_capture.value, composer.compact_summary(base)
    return (
        composer.template_plan_summary(plan, results),
        usage_capture.value,
        composer.template_compact_plan_summary(plan, results),
    )


def _collect_results(db: sqlite3.Connection, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """从 tool_calls 行重建 step_id → result 映射（continue_run 跨任务续跑时，
    内存里的 results 已丢失，以数据库为准）。"""
    results: dict[str, Any] = {}
    for step in steps:
        tool_call_id = step.get("tool_call_id")
        if not tool_call_id:
            continue
        row = db.execute(
            "SELECT status, result_json FROM tool_calls WHERE id = ?",
            (tool_call_id,),
        ).fetchone()
        if row and row["result_json"]:
            try:
                results[step["id"]] = json.loads(row["result_json"])
            except json.JSONDecodeError:
                results[step["id"]] = {"error": "结果解析失败"}
    return results


def _scenario_suggestion(
    intent: intents.Intent, conversation: sqlite3.Row | None
) -> dict[str, str] | None:
    """场景切换建议（PRD-06 §7.3：识别到他场景关键词只建议，不自动切）。"""
    if conversation is None or not intent.scenario_id:
        return None
    current = conversation["scenario_id"]
    if current and current != intent.scenario_id:
        return {
            "type": "scenario_switch",
            "suggested_scenario_id": intent.scenario_id,
            "message": "检测到您的目标更接近另一个场景，可在会话设置中切换后继续。",
        }
    return None


def _emit_citations_if_any(
    db: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]],
    results: dict[str, Any],
) -> None:
    """rag.answer 结果带引用时发 citation.attached（蓝图 §7）。"""
    for step in steps:
        if step["tool"] != "rag.answer":
            continue
        result = results.get(step["id"]) or {}
        # A refusal has no evidentiary basis, even if an adapter accidentally
        # carries stale citation data alongside it.  Do not expose that data as
        # support for a general-knowledge fallback answer.
        if result.get("refused"):
            continue
        citations = result.get("citations") or []
        if citations:
            events.emit(db, run_id, events.CITATION_ATTACHED,
                        {"citations": citations})


def _emit_usage_if_any(
    db: sqlite3.Connection, run_id: str, usage: dict[str, Any] | None
) -> None:
    """Persist and publish usage captured by this exact final composition."""

    if not usage:
        return
    payload: dict[str, Any] = {"model": usage.get("model")}
    raw = usage.get("usage")
    if isinstance(raw, dict):
        for key in ("prompt_tokens", "completion_tokens"):
            if key in raw:
                payload[key] = raw[key]
    events.emit(db, run_id, events.RUN_USAGE, payload)
    if usage.get("model"):
        db.execute(
            "UPDATE agent_runs SET usage_json = ?, provider_id = ? WHERE id = ?",
            (json.dumps(raw or {}, ensure_ascii=False),
             usage.get("provider_id"), run_id),
        )
        db.commit()


async def _complete_direct_chat(
    db: sqlite3.Connection, run: sqlite3.Row, conversation_id: str
) -> bool:
    """Try an LLM answer for a chat or clarification turn; return True if handled.

    The caller owns the deterministic fallback when no configured provider
    produces text, so this helper only completes the run after a real reply.
    """

    history = _load_chat_history(db, conversation_id)
    if not history or history[-1].get("content") != run["input_text"]:
        history.append({"role": "user", "content": run["input_text"]})
    memory_context = conversation_memory.format_context(
        conversation_memory.retrieve_context(
            db,
            user_id=run["user_id"],
            conversation_id=conversation_id,
            query=run["input_text"],
            exclude_run_id=run["id"],
        )
    )
    usage_capture = composer.UsageCapture()
    _emit_progress(
        db,
        run["id"],
        phase="system",
        status="running",
        title="正在生成回答",
        detail="正在组织适合当前问题的回复",
    )
    pieces: list[str] = []
    async for delta in composer.stream_direct_chat_text(
        history,
        private_memory_context=memory_context,
        usage_capture=usage_capture,
    ):
        if not pieces:
            # A provider can be unavailable before yielding output. Delay the
            # visible start until text exists so a rule fallback has no stale
            # model activity to reconcile.
            _emit_progress(
                db,
                run["id"],
                phase="synthesis",
                status="running",
                title="正在生成回答",
                detail="正在组织适合当前问题的回复",
            )
        pieces.append(delta)
        await _emit_message_delta(db, run["id"], delta)
    text = "".join(pieces)
    if not text:
        return False
    _persist_message(db, conversation_id, run["id"], "assistant", text)
    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="completed",
        title="回答已生成",
    )
    _emit_usage_if_any(db, run["id"], usage_capture.value)
    _finalize_run(
        db,
        run["id"],
        event_type=events.RUN_COMPLETED,
        payload={"summary": composer.compact_summary(text)},
        status="completed",
    )
    return True


async def _complete_identity_fallback(
    db: sqlite3.Connection, run: sqlite3.Row
) -> None:
    """Finish an identity turn safely when neither configured chat model replies."""

    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="running",
        title="正在提供助手说明",
    )
    await _emit_assistant_text(
        db, run["id"], run["conversation_id"], prompts.IDENTITY_FALLBACK
    )
    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="completed",
        title="助手说明已生成",
    )
    _finalize_run(
        db,
        run["id"],
        event_type=events.RUN_COMPLETED,
        payload={"summary": composer.compact_summary(prompts.IDENTITY_FALLBACK)},
        status="completed",
    )


def _fail_run(db: sqlite3.Connection, run_id: str, message: str) -> None:
    _emit_progress(
        db,
        run_id,
        phase="system",
        status="failed",
        title="本次处理未能完成",
        detail="请稍后重试",
    )
    _finalize_run(
        db,
        run_id,
        event_type=events.RUN_FAILED,
        payload={"error": message},
        status="failed",
        error=message,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def _run_steps(
    db: sqlite3.Connection, config, user, run, conv,
    steps: list[dict[str, Any]], start_index: int,
) -> bool:
    """从 start_index 起执行计划；遇写确认门停下返回 False，全部走完返回 True。"""
    results = _collect_results(db, steps)
    for index in range(start_index, len(steps)):
        step = steps[index]
        if step["status"] in ("completed", "failed"):
            continue
        try:
            spec = registry.get(step["tool"])
        except KeyError:
            logger.error("计划引用了未注册工具: %s", step["tool"])
            step["status"] = "failed"
            results[step["id"]] = {"error": f"工具 {step['tool']} 未注册"}
            _emit_progress(
                db,
                run["id"],
                phase="tool",
                status="failed",
                title=f"未完成：{step['title']}",
                detail="所需工具暂不可用",
            )
            continue
        _enrich_step_args(step, steps, results)
        if spec.permission == "read" and spec.auto_execute:
            results[step["id"]] = _execute_read_step(db, config, user, run, conv, step, spec)
        else:
            stopped = _open_write_gate(db, config, user, run, conv, step, spec)
            _persist_plan(db, run["id"], steps)
            if stopped:
                return False
            results[step["id"]] = None
    _persist_plan(db, run["id"], steps)
    return True


def _persist_plan(db: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]) -> None:
    plan = {"steps": steps}
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(plan, ensure_ascii=False, default=str), run_id),
    )
    db.commit()


def _persist_clarification(
    db: sqlite3.Connection,
    run_id: str,
    state: intents.ClarificationState,
    attachment: dict[str, Any] | None,
) -> None:
    """Persist the minimal continuation state before ending a question-only run.

    The attachment remains in the envelope because a diagnostic request may
    still need its token after one clarification turn.
    """

    payload: dict[str, Any] = {"clarification": state.to_payload()}
    if attachment:
        payload["attachment"] = attachment
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False, default=str), run_id),
    )
    db.commit()


def _emit_plan_updated(db: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]) -> None:
    payload_steps: list[dict[str, Any]] = []
    for step in steps:
        item = {"id": step["id"], "title": step["title"], "status": step["status"]}
        tool = step.get("tool")
        # Older persisted plans can lack a tool name, so expose it only when
        # present and keep the original three-field replay contract intact.
        if isinstance(tool, str) and tool:
            item["tool"] = tool
        payload_steps.append(item)
    events.emit(db, run_id, events.PLAN_UPDATED, {"steps": payload_steps})


async def _finalize(
    db: sqlite3.Connection, run, conv, intent: intents.Intent,
    steps: list[dict[str, Any]],
    *,
    goal_text: str | None = None,
) -> None:
    """全部步骤走完后的收尾：最终消息 → 引用/用量事件 → run.completed。"""
    results = _collect_results(db, steps)
    streamed = False

    async def _forward_delta(delta: str) -> None:
        nonlocal streamed
        streamed = True
        await _emit_message_delta(db, run["id"], delta)

    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="running",
        title="正在整理执行结果",
        detail="正在生成最终回复",
    )
    user_input = goal_text or run["input_text"]
    memory_context = None
    if _needs_general_knowledge_fallback(steps, results):
        # Grounded answers remain constrained to tool results; only the
        # model-knowledge fallback receives private conversational context.
        memory_context = conversation_memory.format_context(
            conversation_memory.retrieve_context(
                db,
                user_id=run["user_id"],
                conversation_id=run["conversation_id"],
                query=user_input,
                exclude_run_id=run["id"],
            )
        )
    text, usage, summary = await _compose_final_text(
        user_input,
        steps,
        results,
        private_memory_context=memory_context,
        on_delta=_forward_delta,
    )
    if streamed:
        # Streamed chunks have already been persisted as message.delta events;
        # only the durable chat record remains so a replay never duplicates it.
        _persist_message(db, run["conversation_id"], run["id"], "assistant", text)
    else:
        # Template and non-stream providers retain the previous bounded-delta
        # behavior while sharing the same single-message persistence contract.
        await _emit_assistant_text(db, run["id"], run["conversation_id"], text)
    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="completed",
        title="最终回复已生成",
    )
    _emit_citations_if_any(db, run["id"], steps, results)
    _emit_usage_if_any(db, run["id"], usage)
    suggestion = _scenario_suggestion(intent, conv)
    payload: dict[str, Any] = {"summary": summary}
    if suggestion:
        payload["suggestion"] = suggestion
    _finalize_run(
        db,
        run["id"],
        event_type=events.RUN_COMPLETED,
        payload=payload,
        status="completed",
    )


async def execute_run(run_id: str, db_path: str) -> None:
    """启动一轮运行（POST /api/runs 后由 asyncio.create_task 调用）。"""
    db = connect(db_path)
    try:
        run, conv, user = _load_run_context(db, run_id)
        events.emit(db, run_id, events.RUN_STARTED,
                    {"run_id": run_id, "conversation_id": run["conversation_id"]})

        # router 可能把 attachment 预置在 plan_json 里（schema 无附件列的变通）
        attachment = None
        if run["plan_json"]:
            try:
                attachment = json.loads(run["plan_json"]).get("attachment")
            except json.JSONDecodeError:
                attachment = None

        intent, goal_text = _resolve_initial_intent(db, run, conv, attachment)

        is_identity_turn = intent.kind == intents.KIND_AGENT_IDENTITY
        is_recall_turn = intent.kind == intents.KIND_CONVERSATION_RECALL
        needs_direct_chat = is_identity_turn or is_recall_turn or intents.next_question(intent) is not None or (
            intent.kind == intents.KIND_DIAGNOSE_UPLOAD
            and not (attachment and attachment.get("diagnostic_token"))
        )
        if needs_direct_chat:
            if await _complete_direct_chat(db, run, run["conversation_id"]):
                return
            if is_identity_turn:
                # Do not let an unavailable provider reclassify an identity
                # question as a planning request and trigger RAG tools.
                await _complete_identity_fallback(db, run)
                return
            if is_recall_turn:
                await _emit_assistant_text(
                    db,
                    run["id"],
                    run["conversation_id"],
                    prompts.CONVERSATION_RECALL_UNAVAILABLE,
                )
                _finalize_run(
                    db,
                    run["id"],
                    event_type=events.RUN_COMPLETED,
                    payload={"summary": prompts.CONVERSATION_RECALL_UNAVAILABLE},
                    status="completed",
                )
                return
            _emit_progress(
                db,
                run_id,
                phase="system",
                status="completed",
                title="已切换到规则引导",
                detail="当前将提供明确的下一步建议",
            )

        # 信息不足：每轮只追问一个最关键问题（PRD-06 §6.2），本轮即完成
        question = intents.next_question(intent)
        if question:
            # Store the original request and slots before publishing the
            # question, so the next request can safely resume after a reload.
            _persist_clarification(
                db, run_id, intents.make_clarification(intent, goal_text), attachment
            )
            _emit_progress(
                db,
                run_id,
                phase="synthesis",
                status="running",
                title="正在准备下一步问题",
            )
            await _emit_assistant_text(db, run_id, run["conversation_id"], question)
            _emit_progress(
                db,
                run_id,
                phase="synthesis",
                status="completed",
                title="下一步问题已生成",
            )
            _finalize_run(
                db,
                run_id,
                event_type=events.RUN_COMPLETED,
                payload={"summary": question},
                status="completed",
            )
            return

        if intent.kind == intents.KIND_DIAGNOSE_UPLOAD and not (
            attachment and attachment.get("diagnostic_token")
        ):
            # 想诊断但没带文件：引导上传（话术表无对应行，用上传面板引导文案）
            notice = "请先上传需要诊断的标注结果文件（支持 JSON / TextGrid / COCO / VOC），我会先做格式校验。"
            _emit_progress(
                db,
                run_id,
                phase="synthesis",
                status="running",
                title="正在准备上传指引",
            )
            await _emit_assistant_text(db, run_id, run["conversation_id"], notice)
            _emit_progress(
                db,
                run_id,
                phase="synthesis",
                status="completed",
                title="上传指引已生成",
            )
            _finalize_run(
                db,
                run_id,
                event_type=events.RUN_COMPLETED,
                payload={"summary": notice},
                status="completed",
            )
            return

        _emit_progress(
            db,
            run_id,
            phase="planning",
            status="running",
            title="正在制定执行计划",
            detail="正在安排可验证的处理步骤",
        )
        steps = _build_plan(intent, run, conv, attachment, goal_text=goal_text)
        _persist_plan(db, run_id, steps)
        _emit_plan_updated(db, run_id, steps)
        _emit_progress(
            db,
            run_id,
            phase="planning",
            status="completed",
            title="执行计划已生成",
            detail=f"已安排 {len(steps)} 个步骤",
        )
        # run 行记录本轮生效的场景/数据类型（显式 > 识别）；会话行不在这里改，
        # 场景切换只能由用户显式触发（PRD-06 §7.3）
        _update_run(db, run_id,
                    scenario_id=run["scenario_id"] or intent.scenario_id,
                    data_type=run["data_type"] or intent.data_type)

        finished = await _run_steps(db, get_config(), user, run, conv, steps, 0)
        if not finished:
            _emit_plan_updated(db, run_id, steps)
            return  # 停在写确认门，等待 confirmations 路由续跑
        _emit_plan_updated(db, run_id, steps)
        await _finalize(db, run, conv, intent, steps, goal_text=goal_text)
    except Exception:
        logger.exception("运行 %s 未处理异常", run_id)
        try:
            _fail_run(db, run_id, _GENERIC_ERROR)
        except Exception:
            logger.exception("运行 %s 失败态写入也失败", run_id)
    finally:
        db.close()


async def continue_run(run_id: str, db_path: str) -> None:
    """确认后的续跑（confirmations 路由 apply 成功后调用）。

    从计划里第一个未完成的步骤继续；已确认的写步骤以其 tool_call
    结果为准标记 completed。若遇下一个写门则再次停下等待。
    """
    db = connect(db_path)
    try:
        run, conv, user = _load_run_context(db, run_id)
        if run["status"] in _RUN_TERMINAL:
            return
        try:
            plan = json.loads(run["plan_json"] or "{}")
        except json.JSONDecodeError:
            plan = {}
        steps = plan.get("steps") or []
        if not steps:
            _fail_run(db, run_id, _GENERIC_ERROR)
            return

        # 定位刚被确认的写步骤：tool_call 已由确认路由置 completed
        start_index = len(steps)
        resumed_confirmation = False
        for index, step in enumerate(steps):
            if step["status"] == "waiting":
                step["status"] = "completed"
                resumed_confirmation = True
            if step["status"] not in ("completed", "failed"):
                start_index = index
                break
        else:
            start_index = len(steps)

        _update_run(db, run_id, status="running")
        if resumed_confirmation:
            _emit_progress(
                db,
                run_id,
                phase="tool",
                status="completed",
                title="写入操作已确认",
                detail="正在继续后续计划",
            )
        _emit_progress(
            db,
            run_id,
            phase="planning",
            status="running",
            title="正在继续执行计划",
            detail="已根据确认结果恢复未完成步骤",
        )
        run_data_type, run_scenario_id, conversation_data_type, conversation_scenario_id = (
            _context_values(run, conv)
        )
        intent = intents.apply_context(
            intents.detect(run["input_text"]),
            data_type=conversation_data_type,
            scenario_id=conversation_scenario_id,
            prefer_context=True,
        )
        intent = intents.apply_context(
            intent,
            data_type=run_data_type,
            scenario_id=run_scenario_id,
            prefer_context=True,
        )
        finished = await _run_steps(db, get_config(), user, run, conv, steps, start_index)
        if not finished:
            _emit_plan_updated(db, run_id, steps)
            return
        _emit_plan_updated(db, run_id, steps)
        await _finalize(db, run, conv, intent, steps)
    except Exception:
        logger.exception("续跑 %s 未处理异常", run_id)
        try:
            _fail_run(db, run_id, _GENERIC_ERROR)
        except Exception:
            logger.exception("续跑 %s 失败态写入也失败", run_id)
    finally:
        db.close()
