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
from typing import Any, Coroutine

from ..config import get_config
from ..db import connect, utc_now_iso
from ..tools import registry
from ..tools.registry import ToolContext
from . import composer, events, intents

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
    db.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, conversation_id, run_id, role, content, utc_now_iso()),
    )
    db.commit()
    return message_id


def _update_run(db: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    """按列名更新 agent_runs（列名来自本模块内部常量，无注入面）。"""
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.execute(
        f"UPDATE agent_runs SET {assignments} WHERE id = ?",
        (*fields.values(), run_id),
    )
    db.commit()


async def _emit_assistant_text(
    db: sqlite3.Connection, run_id: str, conversation_id: str, text: str
) -> None:
    """把完整 assistant 文本按 ≤40 字符切块发 message.delta 并落库。"""
    for i in range(0, len(text), _MESSAGE_CHUNK):
        events.emit(db, run_id, events.MESSAGE_DELTA,
                    {"delta": text[i:i + _MESSAGE_CHUNK]})
        await asyncio.sleep(0)  # 让出事件循环，SSE 端能及时取走
    _persist_message(db, conversation_id, run_id, "assistant", text)


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
    """执行读工具：tool.call.requested → 执行 → tool.call.completed（含耗时）。"""
    args_summary = json.dumps(step["args"], ensure_ascii=False, default=str)[:200]
    tool_call_id = _insert_tool_call(db, run["id"], spec.name, "read", step["args"])
    step["tool_call_id"] = tool_call_id
    events.emit(db, run["id"], events.TOOL_CALL_REQUESTED, {
        "tool_call_id": tool_call_id, "tool": spec.name,
        "permission": "read", "args_summary": args_summary,
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
        "duration_ms": duration_ms, "is_write": 0, "result": result,
    })
    step["status"] = "completed" if status == "completed" else "failed"
    return result


def _open_write_gate(db, config, user, run, conv, step, spec) -> bool:
    """写工具确认门：生成预览 + pending_confirmations 行，run 转入等待。

    返回 True 表示已停在确认门；preview 自身失败（如角色不足/前置状态
    不满足）时按步骤失败处理并返回 False 让计划继续收尾。
    """
    args_summary = json.dumps(step["args"], ensure_ascii=False, default=str)[:200]
    tool_call_id = _insert_tool_call(db, run["id"], spec.name, "write", step["args"])
    step["tool_call_id"] = tool_call_id
    events.emit(db, run["id"], events.TOOL_CALL_REQUESTED, {
        "tool_call_id": tool_call_id, "tool": spec.name,
        "permission": "write", "args_summary": args_summary,
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
            "duration_ms": 0, "is_write": 1, "result": preview_payload,
        })
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
    events.emit(db, run["id"], events.CONFIRMATION_REQUIRED, {
        "confirmation": {
            "id": confirmation_id,
            "run_id": run["id"],
            "tool_call_id": tool_call_id,
            "action_type": spec.name,
            "preview": preview_payload,
            "status": "pending",
            "expires_at": expires_at,
            "created_at": now,
        }
    })
    return True


def _iso_after_seconds(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# 收尾：最终 assistant 消息 + run.completed / run.failed
# ---------------------------------------------------------------------------

async def _compose_final_text(
    user_input: str, steps: list[dict[str, Any]], results: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """LLM 可用→流式/整段合成；不可用→模板渲染工具结果（PRD-06 §11.1）。

    流式失败的补偿：stream_text 若中段异常，composer 已记录日志并停止，
    此时已产出的增量仍被使用（不回退模板，避免同一条消息重复出现）。
    """
    messages = composer.build_compose_messages(user_input, results)
    usage_capture = composer.UsageCapture()
    streamed: list[str] = []
    async for delta in composer.stream_text(messages, usage_capture=usage_capture):
        streamed.append(delta)
    if streamed:
        return "".join(streamed), usage_capture.value
    text = await composer.compose_text(messages, usage_capture=usage_capture)
    if text:
        return text, usage_capture.value
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
        return base, usage_capture.value
    return composer.template_plan_summary(plan, results), usage_capture.value


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


def _fail_run(db: sqlite3.Connection, run_id: str, message: str) -> None:
    events.emit(db, run_id, events.RUN_FAILED, {"error": message})
    _update_run(db, run_id, status="failed", error=message,
                completed_at=utc_now_iso())


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
    events.emit(db, run_id, events.PLAN_UPDATED, {
        "steps": [{"id": s["id"], "title": s["title"], "status": s["status"]}
                  for s in steps]
    })


async def _finalize(
    db: sqlite3.Connection, run, conv, intent: intents.Intent,
    steps: list[dict[str, Any]],
    *,
    goal_text: str | None = None,
) -> None:
    """全部步骤走完后的收尾：最终消息 → 引用/用量事件 → run.completed。"""
    results = _collect_results(db, steps)
    text, usage = await _compose_final_text(goal_text or run["input_text"], steps, results)
    await _emit_assistant_text(db, run["id"], run["conversation_id"], text)
    _emit_citations_if_any(db, run["id"], steps, results)
    _emit_usage_if_any(db, run["id"], usage)
    suggestion = _scenario_suggestion(intent, conv)
    payload: dict[str, Any] = {"summary": text[:200]}
    if suggestion:
        payload["suggestion"] = suggestion
    events.emit(db, run["id"], events.RUN_COMPLETED, payload)
    _update_run(db, run["id"], status="completed", completed_at=utc_now_iso())


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

        # 信息不足：每轮只追问一个最关键问题（PRD-06 §6.2），本轮即完成
        question = intents.next_question(intent)
        if question:
            # Store the original request and slots before publishing the
            # question, so the next request can safely resume after a reload.
            _persist_clarification(
                db, run_id, intents.make_clarification(intent, goal_text), attachment
            )
            await _emit_assistant_text(db, run_id, run["conversation_id"], question)
            events.emit(db, run_id, events.RUN_COMPLETED, {"summary": question})
            _update_run(db, run_id, status="completed", completed_at=utc_now_iso())
            return

        if intent.kind == intents.KIND_DIAGNOSE_UPLOAD and not (
            attachment and attachment.get("diagnostic_token")
        ):
            # 想诊断但没带文件：引导上传（话术表无对应行，用上传面板引导文案）
            notice = "请先上传需要诊断的标注结果文件（支持 JSON / TextGrid / COCO / VOC），我会先做格式校验。"
            await _emit_assistant_text(db, run_id, run["conversation_id"], notice)
            events.emit(db, run_id, events.RUN_COMPLETED, {"summary": notice})
            _update_run(db, run_id, status="completed", completed_at=utc_now_iso())
            return

        steps = _build_plan(intent, run, conv, attachment, goal_text=goal_text)
        _persist_plan(db, run_id, steps)
        _emit_plan_updated(db, run_id, steps)
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
        for index, step in enumerate(steps):
            if step["status"] == "waiting":
                step["status"] = "completed"
            if step["status"] not in ("completed", "failed"):
                start_index = index
                break
        else:
            start_index = len(steps)

        _update_run(db, run_id, status="running")
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
