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
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Awaitable, Callable, Coroutine

from ..config import get_config
from ..db import utc_now_iso
from ..tools import registry
from ..tools.registry import ToolContext
from . import (
    composer,
    conversation_memory,
    events,
    graph_runtime,
    intents,
    media,
    prompts,
    task_drafts,
)

logger = logging.getLogger(__name__)

# 确认门过期时间（PRD-06 §6.4）：普通写 30min；删除/归档 10min
_CONFIRM_TTL_SECONDS = 30 * 60
_ARCHIVE_TTL_SECONDS = 10 * 60
_ARCHIVE_ACTIONS = {"rag.archive_document"}

_MESSAGE_CHUNK = 40  # message.delta 单帧上限（契约：≤40 字符）

_RUN_TERMINAL = ("completed", "failed", "cancelled")

# Only generic L3 profiles can influence a normal learner task.  Response-style
# and language profiles may mention a data type incidentally, so they are kept
# out of this lookup instead of being treated as task-scope choices.
_L3_TASK_PREFERENCE_KINDS = frozenset({
    intents.KIND_LEARN_GOAL,
    intents.KIND_PRESET_START,
    intents.KIND_TASK_CONVERT,
})
_L3_PREFERENCE_CUE_RE = re.compile(
    r"(?:current\s+learner\s+preference\s*[:：]|"
    r"当前(?:学习者|用户)偏好\s*[:：]|"
    r"\b(?:i\s+)?(?:prefer|like|want|need)\b|"
    r"我(?:喜欢|希望|偏好)|请(?:用|给我))",
    re.IGNORECASE,
)
_L3_UNSAFE_CONTENT_RE = re.compile(
    r"(?:"
    r"\b(?:password|passwd|passphrase|secret|credential|api[-_ ]?key|"
    r"access[-_ ]?token|refresh[-_ ]?token|session[-_ ]?id|bearer|"
    r"authorization|csrf|cookie|private[-_ ]?key|client[-_ ]?secret|"
    r"token|jwt)\b|"
    r"\b(?:chain[-_ ]?of[-_ ]?thought|thought[-_ ]?process|system[-_ ]?prompt|"
    r"developer[-_ ]?message|tool[-_ ]?(?:call|result|arguments?)|"
    r"function[-_ ]?call|traceback|stack[-_ ]?trace)\b|"
    r"\{\s*[\"'](?:args|arguments|tool_name|result|function)[\"']\s*:|"
    r"<\s*/?\s*(?:think|analysis|reasoning)\b|"
    r"密码|密钥|令牌|私钥|授权头|推理过程|思维链|系统提示|"
    r"工具调用|工具参数|工具结果|内部指令"
    r")",
    re.IGNORECASE,
)

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
) -> tuple[str | None, str | None]:
    """Return only the remaining data-type selections used by task planning."""

    conversation_data_type = conversation["data_type"] if conversation else None
    return (
        run["data_type"],
        conversation_data_type,
    )


def _has_data_type_signal(text: str | None) -> bool:
    """Return whether text explicitly names any supported annotation type.

    ``intents.detect`` intentionally returns ``None`` for an ambiguous phrase
    such as ``图像或视频``.  That is still an explicit user selection attempt,
    so it must block a historical preference from silently choosing one side.
    ASCII keywords use word boundaries to avoid treating words such as
    ``context`` as the ``text`` type.
    """

    normalized = (text or "").casefold()
    for keywords in intents.DATA_TYPE_KEYWORDS.values():
        for keyword in keywords:
            candidate = keyword.casefold()
            if candidate.isascii() and candidate.isalnum():
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])",
                    normalized,
                ):
                    return True
            elif candidate in normalized:
                return True
    return False


def _l3_preferred_data_type(
    db: sqlite3.Connection, *, user_id: str
) -> str | None:
    """Read one safe, explicitly sourced generic L3 preference as an enum.

    L3 is a private profile layer, not a prompt transcript.  The query requires
    an active ``profile:general`` item with a user-message provenance link, and
    the return value is reduced to a canonical data-type enum.  Preference text
    (especially legacy or poisoned rows) never leaves this function.
    """

    if not get_config().private_memory_enabled:
        return None
    try:
        rows = db.execute(
            """
            SELECT memory.content
            FROM private_memory_items AS memory
            WHERE memory.user_id = ?
              AND memory.layer = 'l3'
              AND memory.kind = 'profile'
              AND memory.memory_key = 'profile:general'
              AND memory.status = 'active'
              AND EXISTS (
                  SELECT 1
                  FROM private_memory_sources AS source
                  JOIN messages AS message ON message.id = source.message_id
                  JOIN conversations AS source_conversation
                    ON source_conversation.id = message.conversation_id
                  WHERE source.memory_id = memory.id
                    AND message.role = 'user'
                    AND source_conversation.user_id = memory.user_id
              )
            ORDER BY memory.created_at DESC, memory.rowid DESC
            LIMIT 12
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.Error:
        # Deployments upgrading from pre-layered-memory schemas should keep
        # task planning available; an absent optional table means no preference.
        logger.warning("L3 task preference lookup failed", exc_info=True)
        return None

    for row in rows:
        content = row["content"]
        if not isinstance(content, str):
            continue
        candidate = " ".join(content.strip().split())
        if (
            not candidate
            or len(candidate) > 512
            or _L3_UNSAFE_CONTENT_RE.search(candidate)
            or not _L3_PREFERENCE_CUE_RE.search(candidate)
        ):
            continue
        # Standalone JSON is treated as an execution payload even when its
        # field names are unfamiliar; no structured value should become a task
        # preference by accident.
        payload_candidate = candidate.strip()
        if payload_candidate.startswith(("{", "[")):
            try:
                json.loads(payload_candidate)
            except (TypeError, ValueError):
                pass
            else:
                continue
        # This detector is deliberately applied only to the private profile
        # text and returns an enum; the original content is never prompt input.
        preference_body = re.sub(
            r"^(?:current\s+learner\s+preference|当前(?:学习者|用户)偏好)\s*[:：]\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        data_type = intents.detect(preference_body).data_type
        if data_type in intents.DATA_TYPE_KEYWORDS:
            return data_type
    return None


def _apply_l3_task_preference(
    db: sqlite3.Connection,
    intent: intents.Intent,
    *,
    user_id: str,
    task_text: str,
    current_text: str,
) -> intents.Intent:
    """Fill an omitted learner task type from a safe explicit L3 preference."""

    if (
        intent.kind not in _L3_TASK_PREFERENCE_KINDS
        or intent.data_type is not None
        or _has_data_type_signal(task_text)
        or _has_data_type_signal(current_text)
    ):
        return intent
    preferred = _l3_preferred_data_type(db, user_id=user_id)
    if preferred is None:
        return intent
    # Keep the current request as the task goal; only the missing enum slot is
    # filled, so an historical preference cannot overwrite current wording.
    return intents.apply_context(intent, data_type=preferred, prefer_context=True)


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
    run_data_type, conversation_data_type = _context_values(run, conversation)
    # A fresh recognized intent deliberately skips the clarification tier,
    # preventing a new request from inheriting old data-type slots.
    # For data type, a current explicit signal must remain visible; otherwise
    # an old conversation default would silently defeat a new choice.
    conversation_data_type_for_scope = (
        None
        if not resumed and _has_data_type_signal(run["input_text"])
        else conversation_data_type
    )
    resolved = intents.apply_context(
        detected,
        data_type=conversation_data_type_for_scope,
        prefer_context=not resumed,
    )
    resolved = intents.apply_context(
        resolved,
        data_type=run_data_type,
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
        if role == "assistant":
            # L1-L3 extraction opens its own connection after the reply is
            # durable, so embedding/provider latency can never postpone the
            # completed run or its final SSE event.
            conversation_memory.schedule_layered_capture(
                database_path=get_config().resolved_database_path,
                user_id=owner["user_id"],
                conversation_id=conversation_id,
                run_id=run_id,
            )
    return message_id


def _load_chat_history(
    db: sqlite3.Connection, conversation_id: str, *, limit: int = 30
) -> list[dict[str, Any]]:
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
    elif phase == "confirmation":
        activity_id = f"confirmation:{run_id}"
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


_STAGE_MARKER_RE = re.compile(
    r"(?:第\s*[一二三四五六七八九十\d]+\s*阶段|阶段\s*[一二三四五六七八九十\d]+)",
    re.IGNORECASE,
)


def _extract_task_stages(text: str, *, base_title: str, data_type: str | None) -> list[dict[str, Any]]:
    """Extract explicit multi-stage wording into independent task arguments.

    This is deliberately conservative: only explicit stage markers (or a
    ``分阶段`` phrase with multiple semicolon-separated clauses) fan out. A
    normal long task remains one task, so an inferred paragraph cannot surprise
    the learner with several writes behind one confirmation.
    """

    source = text.strip()
    matches = list(_STAGE_MARKER_RE.finditer(source))
    segments: list[str] = []
    if len(matches) >= 2:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            segment = source[match.end() : end].strip(" ：:，,；;。\n\t")
            if segment:
                segments.append(segment)
    elif "分阶段" in source or "多阶段" in source:
        segments = [part.strip(" ：:，,；;。\n\t") for part in re.split(r"[；;]", source) if part.strip()]
        if len(segments) < 2:
            segments = []
    if len(segments) < 2:
        return []
    return [
        {
            "title": f"{base_title}·阶段{index + 1}",
            "goal": segment,
            "description": segment,
            "data_type": data_type,
        }
        for index, segment in enumerate(segments)
    ]

def _build_plan(
    intent: intents.Intent,
    run: sqlite3.Row,
    conversation: sqlite3.Row | None,
    attachment: dict[str, Any] | None,
    *,
    goal_text: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """按意图生成确定性计划，返回 (steps, task_draft_args)。

    steps: {id,title,tool,args,status}。task_draft_args 仅任务类意图非空：
    任务卡不再经 task.preview/task.create 写门，改由收尾阶段据这些参数
    生成 LLM 任务草稿（回答底部按钮预览、显式同步落库）。

    ``goal_text`` preserves the first-turn task wording when a later short
    clarification answer supplies only a missing data-type slot.
    """

    question = goal_text or run["input_text"]
    # ``_resolve_initial_intent`` has already applied run > clarification >
    # conversation > current-input precedence.  Re-applying conversation here
    # would overwrite a just-answered clarification slot.
    data_type = intent.data_type

    def step(idx: int, title: str, tool: str, args: dict) -> dict[str, Any]:
        return {"id": f"s{idx}", "title": title, "tool": tool,
                "args": args, "status": "pending"}

    if intent.kind == intents.KIND_RAG_QUESTION:
        # 纯问答 ≤3 步（蓝图 §10.3）
        return ([
            step(1, "召回相关资料", "rag.search",
                 {"query": question,
                  "filters": {"data_type": data_type}}),
            step(2, "基于资料生成回答", "rag.answer",
                 {"question": question, "data_type": data_type}),
        ], None)

    if intent.kind == intents.KIND_AGENT_IDENTITY:
        # Identity turns complete through direct chat before planning. Preserve
        # the empty result here so a future caller cannot fall into task/RAG.
        return ([], None)

    if intent.kind == intents.KIND_DIAGNOSE_UPLOAD:
        token = (attachment or {}).get("diagnostic_token")
        # 诊断 ≥ [格式校验/规则诊断(缓存报告), 补强路径, 保存摘要]
        return ([
            step(1, "读取诊断报告", "diagnostic.preview",
                 {"diagnostic_token": token}),
            step(2, "生成补强路径", "graph.reason",
                 {"action": "pre_path", "target_id": None}),
            step(3, "保存诊断摘要与掌握度", "diagnostic.save_summary",
                 {"diagnostic_token": token}),
        ], None)

    # learn_goal / preset_start / task_convert / teacher_task：
    # 读步骤只保留 RAG 召回作为草稿生成的证据链；图谱定位按产品决策
    # 彻底移出任务计划（任务卡不再关联能力点）。任务卡生成移出计划步骤，
    # 由 _finalize 用 task_draft_args 生成草稿（PRD 交互变更：
    # 回答底部按钮打开预览卡，卡上按钮直接同步/继续修改）。
    source = {
        intents.KIND_PRESET_START: "preset",
        intents.KIND_TEACHER_TASK: "teacher",
    }.get(intent.kind, "agent")
    label = {"text": "文本", "image": "图像", "audio": "语音",
             "video": "视频"}.get(data_type or "", "")
    title = f"{label}标注练习任务" if label else "标注练习任务"
    task_draft_args: dict[str, Any] = {
        "title": title,
        "goal": question,
        "description": question,
        "data_type": data_type,
        "source": source,
        # Preserve the existing draft-preview UX unless the learner explicitly
        # asks for immediate creation ("直接/自动创建").
        "auto_create": bool(re.search(r"(?:直接|自动)(?:地)?(?:创建|生成|安排)", question)),
    }
    stages = _extract_task_stages(question, base_title=title, data_type=data_type)
    if stages:
        task_draft_args["stages"] = stages
    return ([
            step(1, "检索相关规范资料", "rag.search",
                 {"query": question,
                  "filters": {"data_type": data_type}}),
    ], task_draft_args)


def _enrich_step_args(
    step: dict[str, Any], steps: list[dict[str, Any]],
    results: dict[str, Any],
) -> None:
    """把上游步骤结果注入当前步骤参数（计划数据流）。

    - task.preview/task.create：补图谱定位到的 cap_ids；资源不再成为任务前置条件；
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
                        # Each stage is an independent task card, so carry the
                        # same evidence-backed capability hints into every
                        # stage rather than leaving only the batch wrapper
                        # annotated.
                        for stage in args.get("stages") or []:
                            if isinstance(stage, dict) and not stage.get("cap_ids"):
                                stage["cap_ids"] = list(caps)
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
    db, config, user, run, conv, step, spec, *, is_write: bool = False
) -> Any:
    """执行读工具并发布可回放的安全生命周期事件。

    The database keeps the original arguments/results for the planner, while
    SSE receives only the execution kind and bounded summaries.  This is the
    contract the cockpit uses to show real work without exposing prompts or
    provider payloads.
    """
    input_summary = events.summarize_tool_input(step["args"], title=step["title"])
    execution_kind = events.execution_kind(spec.name)
    permission = "write" if is_write else "read"
    tool_call_id = _insert_tool_call(db, run["id"], spec.name, permission, step["args"])
    step["tool_call_id"] = tool_call_id
    _emit_progress(
        db,
        run["id"],
        phase="tool",
        status="running",
        title=f"正在执行：{step['title']}",
        detail=(f"调用受控学习工具 {spec.name}" if is_write else f"调用只读工具 {spec.name}"),
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
        "permission": permission,
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
        "is_write": 1 if is_write else 0,
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
        detail=(f"受控学习工具 {spec.name}，耗时 {duration_ms} ms" if is_write else f"只读工具 {spec.name}，耗时 {duration_ms} ms"),
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
    sampling: dict[str, float] | None = None,
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
    # Sampling controls belong to the RAG management surface.  Apply them
    # only when this synthesis is grounded in a RAG tool result; general
    # knowledge fallback and ordinary chat retain provider defaults.
    effective_sampling = None if use_general_knowledge else sampling
    usage_capture = composer.UsageCapture()
    streamed: list[str] = []
    if effective_sampling:
        stream = composer.stream_text(
            messages,
            usage_capture=usage_capture,
            sampling=effective_sampling,
        )
    else:
        stream = composer.stream_text(messages, usage_capture=usage_capture)
    async for delta in stream:
        streamed.append(delta)
        if on_delta is not None:
            # The callback persists the chunk before this iterator requests the
            # next one, which is what makes final-composition output live.
            await on_delta(delta)
    if streamed:
        text = "".join(streamed)
        return text, usage_capture.value, composer.compact_summary(text)
    if effective_sampling:
        text = await composer.compose_text(
            messages,
            usage_capture=usage_capture,
            sampling=effective_sampling,
        )
    else:
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
    # 降级回复与摘要卡同文：执行过程已由对话内的步骤流承载，最终消息只保留
    # 干净结论；若沿用 template_plan_summary 会把 ✓ 步骤清单与工具原始 JSON
    # （如 graph.reason 的空结果）再次倒进对话气泡。
    fallback = composer.template_compact_plan_summary(plan, results)
    draft_result = results.get("task_draft")
    if isinstance(draft_result, dict) and draft_result.get("cards"):
        # 模板降级时模型不会介绍任务卡，这里补一段草稿说明与按钮引导
        fallback = f"{fallback}\n{composer.template_task_draft_summary(draft_result['cards'])}"
    return (fallback, usage_capture.value, fallback)


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
    db: sqlite3.Connection,
    run: sqlite3.Row,
    conversation_id: str,
    *,
    media_attachments: list[media.MediaAttachment] | None = None,
) -> bool:
    """Try an LLM answer for a chat or clarification turn; return True if handled.

    The caller owns the deterministic fallback when no configured provider
    produces text, so this helper only completes the run after a real reply.
    """

    history = _load_chat_history(db, conversation_id)
    if media_attachments:
        # The durable user row contains text only. Replace that current-turn
        # entry in memory with text plus all temporary files so binary content
        # never reaches persisted messages or replayable events.
        multimodal_content: list[dict[str, Any]] = [{"type": "text", "text": run["input_text"]}]
        for item in media_attachments:
            composer.append_attachment_user_content(
                multimodal_content,
                filename=item.filename,
                mime_type=item.mime_type,
                content=item.content,
                kind=item.kind,
                extracted_text=item.extracted_text,
            )
        if (
            history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == run["input_text"]
        ):
            history[-1] = {"role": "user", "content": multimodal_content}
        else:
            history.append({"role": "user", "content": multimodal_content})
    elif not history or history[-1].get("content") != run["input_text"]:
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
        if spec.auto_execute:
            # Domain write tools marked auto_execute stay inside the durable
            # tool-call/event boundary; their gateway enforces typed inputs,
            # ownership, idempotency, and the operator kill switch.
            results[step["id"]] = _execute_read_step(
                db, config, user, run, conv, step, spec,
                is_write=spec.permission == "write",
            )
        else:
            stopped = _open_write_gate(db, config, user, run, conv, step, spec)
            _persist_plan(db, run["id"], steps)
            if stopped:
                return False
            results[step["id"]] = None
    _persist_plan(db, run["id"], steps)
    return True


def _persist_plan(db: sqlite3.Connection, run_id: str, steps: list[dict[str, Any]]) -> None:
    existing_graph: dict[str, Any] = {}
    row = db.execute("SELECT plan_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    try:
        previous = json.loads(row["plan_json"] or "{}") if row else {}
        if isinstance(previous, dict) and isinstance(previous.get("graph"), dict):
            existing_graph = previous["graph"]
    except json.JSONDecodeError:
        existing_graph = {}
    plan = {"steps": steps}
    if existing_graph:
        # Graph-only metadata (routing, task draft args, fused evidence) must
        # survive the business plan rewrite performed after every tool step.
        plan["graph"] = existing_graph
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

# ---------------------------------------------------------------------------
# 任务需求澄清（intake）：生成学习任务前的 LLM 自由追问
# ---------------------------------------------------------------------------

# 追问硬封顶：模型可以自由决定问什么，但最多 3 轮后必须生成（PRD 交互决策）
_INTAKE_MAX_ROUNDS = 3
_INTAKE_KINDS = frozenset({intents.KIND_LEARN_GOAL, intents.KIND_TASK_CONVERT})
# 澄清轮内的短回答（"框选"/"零基础"）多为 unknown；其余已识别意图视为新请求，
# 澄清状态随上一轮 run 自然失效（就近原则，与规则澄清一致）。
_INTAKE_CONTINUATION_KINDS = frozenset({
    intents.KIND_UNKNOWN,
    intents.KIND_LEARN_GOAL,
    intents.KIND_TASK_CONVERT,
})


def _persist_intake(db: sqlite3.Connection, run_id: str, state: dict[str, Any]) -> None:
    """Persist one intake state so the next request can continue the dialogue."""

    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps({"task_intake": state}, ensure_ascii=False), run_id),
    )
    db.commit()


def _load_latest_intake(db: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any] | None:
    """Return only the immediately preceding completed run's intake state.

    Same proximity rule as ``_load_latest_clarification``: a newer unrelated
    run must not let an older intake hijack the current request.
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
    if previous is None or previous["status"] != "completed" or not previous["plan_json"]:
        return None
    try:
        payload = json.loads(previous["plan_json"])
    except json.JSONDecodeError:
        return None
    state = payload.get("task_intake")
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("rounds"), int)
        or not isinstance(state.get("origin"), str)
        or not isinstance(state.get("started_rowid"), int)
    ):
        return None
    return state


def _parse_intake_reply(text: str) -> tuple[bool, str]:
    """READY 开头 → (True, 理解复述)；否则 (False, 问题原文)。"""

    normalized = text.strip()
    match = re.match(
        r"^READY\s*[：:]\s*(?P<summary>.+)$", normalized, re.IGNORECASE | re.DOTALL
    )
    if match:
        return True, match.group("summary").strip()[:600]
    return False, normalized


def _collect_intake_requirement(
    db: sqlite3.Connection,
    conversation_id: str,
    state: dict[str, Any],
    *,
    ready_summary: str | None = None,
) -> str:
    """把澄清过程整合为生成依据：原始请求 + 各轮补充 + READY 复述。

    用 agent_runs.input_text 而不是 messages：编排单测与直接插入的运行
    没有用户消息行，但运行行始终存在。
    """

    rows = db.execute(
        """
        SELECT input_text FROM agent_runs
        WHERE conversation_id = ? AND rowid >= ?
        ORDER BY rowid ASC
        """,
        (conversation_id, state["started_rowid"]),
    ).fetchall()
    seen: list[str] = []
    for row in rows:
        text = (row["input_text"] or "").strip()
        if text and text != state["origin"] and text not in seen:
            seen.append(text)
    parts = [f"原始需求：{state['origin']}"]
    if seen:
        parts.append("补充说明：" + "；".join(seen)[:800])
    if ready_summary:
        parts.append(f"需求确认：{ready_summary}")
    return "\n".join(parts)


def _is_task_revision(db: sqlite3.Connection, run: sqlite3.Row) -> bool:
    """修订话术 + 会话内已有草稿 → 跳过澄清直接重新生成。"""

    if not task_drafts.revision_cue(run["input_text"]):
        return False
    row = db.execute(
        "SELECT 1 FROM task_drafts WHERE conversation_id = ? LIMIT 1",
        (run["conversation_id"],),
    ).fetchone()
    return row is not None


async def _handle_task_intake(
    db: sqlite3.Connection,
    run: sqlite3.Row,
    goal_text: str,
) -> tuple[str, str | None]:
    """任务意图的 LLM 澄清门。

    返回 ("completed", None)：已输出澄清问题，本轮结束；
    ("legacy", None)：模型不可用，调用方回退既有规则追问/生成路径；
    ("ready", requirement)：可以生成，requirement 为整合后的生成依据。
    """

    intake = _load_latest_intake(db, run)
    if intake is None:
        started_rowid = db.execute(
            "SELECT rowid FROM agent_runs WHERE id = ?", (run["id"],)
        ).fetchone()["rowid"]
        intake = {"rounds": 0, "origin": goal_text, "started_rowid": started_rowid}
    # 硬封顶：无论模型还想问什么，第 4 轮直接生成
    if intake["rounds"] >= _INTAKE_MAX_ROUNDS:
        return "ready", _collect_intake_requirement(db, run["conversation_id"], intake)
    history = _load_chat_history(db, run["conversation_id"])
    messages = [{"role": "system", "content": prompts.TASK_INTAKE_SYSTEM}, *history]
    text = await composer.compose_text(messages)
    if not text:
        return "legacy", None
    ready, payload = _parse_intake_reply(text)
    if ready:
        return "ready", _collect_intake_requirement(
            db, run["conversation_id"], intake, ready_summary=payload
        )

    intake["rounds"] += 1
    _persist_intake(db, run["id"], intake)
    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="running",
        title="正在了解你的学习需求",
    )
    await _emit_assistant_text(db, run["id"], run["conversation_id"], payload)
    _emit_progress(
        db,
        run["id"],
        phase="synthesis",
        status="completed",
        title="需求澄清问题已生成",
    )
    _finalize_run(
        db,
        run["id"],
        event_type=events.RUN_COMPLETED,
        payload={"summary": payload},
        status="completed",
    )
    return "completed", None



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
    task_draft_args: dict[str, Any] | None = None,
    graphrag_evidence: dict[str, Any] | None = None,
) -> None:
    """全部步骤走完后的收尾：草稿/证据 → 最终消息 → run.completed。

    GraphRAG evidence is a read-only query-time projection.  It is added to
    the private synthesis input only after the exploration subgraph has
    completed, so the browser still receives the existing redacted events.
    """
    results = _collect_results(db, steps)
    if isinstance(graphrag_evidence, dict) and graphrag_evidence:
        results = {**results, "graphrag": graphrag_evidence}
    streamed = False

    # 任务类意图：先出任务草稿（LLM 生成 + 模板回退），再合成最终回答，
    # 让回答能介绍这张卡；草稿事件先行，前端按钮随回答流式出现。
    if task_draft_args is not None:
        _emit_progress(
            db,
            run["id"],
            phase="synthesis",
            status="running",
            title="正在生成学习任务草稿",
            detail="正在把学习目标整理成任务卡",
        )
        draft_projection = None
        try:
            draft_projection = await task_drafts.generate_task_draft(
                db, run_row=run, task_args=task_draft_args, results=results
            )
        except Exception:
            # 草稿失败不拖垮整轮：回答仍照常给出，仅少一张可同步的卡
            logger.exception("运行 %s 任务草稿生成失败", run["id"])
        _emit_progress(
            db,
            run["id"],
            phase="synthesis",
            status="completed" if draft_projection else "failed",
            title=("学习任务草稿已生成" if draft_projection else "学习任务草稿生成失败"),
        )
        if draft_projection:
            # 合成回答的证据里加入草稿卡，模型才能把卡内容整理进回答
            results = {**results, "task_draft": {"cards": draft_projection["cards"]}}
            # The approved low-risk policy lets an explicit immediate-create
            # request write normalized cards. Ordinary drafts deliberately
            # wait for the learner's later save command without logging a
            # false failure for that normal path.
            if task_draft_args.get("auto_create"):
                try:
                    actor = db.execute(
                        "SELECT * FROM users WHERE id = ?", (run["user_id"],)
                    ).fetchone()
                    if actor is None:
                        raise LookupError("agent_user_not_found")
                    auto_step = {
                        "id": "learning-task-auto-create",
                        "title": "同步学习任务",
                        "tool": "learning.task.auto_create",
                        "args": {
                            "cards": draft_projection["cards"],
                            "idempotency_key": f"{run['id']}:task-draft",
                        },
                        "status": "pending",
                    }
                    auto_result = _execute_read_step(
                        db, get_config(), actor, run, conv, auto_step,
                        spec=registry.get("learning.task.auto_create"), is_write=True,
                    )
                    results = {**results, "learning_task_auto_create": auto_result}
                except Exception:
                    logger.exception("运行 %s 自动同步学习任务失败", run["id"])

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
    sampling: dict[str, float] | None = None
    if any(step.get("tool") in {"rag.answer", "rag.search"} for step in steps):
        try:
            # Load the persisted RAG knobs at synthesis time so an admin edit
            # affects the next answer without copying settings into run data.
            from ..rag.retriever import load_settings

            settings = load_settings(db)
            sampling = {"temperature": settings.temperature, "top_p": settings.top_p}
        except Exception:
            sampling = None
    text, usage, summary = await _compose_final_text(
        user_input,
        steps,
        results,
        private_memory_context=memory_context,
        on_delta=_forward_delta,
        sampling=sampling,
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
    auto_create_succeeded = bool(
        isinstance(results.get("learning_task_auto_create"), dict)
        and not results["learning_task_auto_create"].get("error")
        and results["learning_task_auto_create"].get("task_ids")
    )
    if (
        task_draft_args is not None
        and draft_projection
        and draft_projection["status"] == "draft"
        and not auto_create_succeeded
    ):
        # A generated draft is not the durable learning task. Keep the run
        # paused until the learner explicitly says “保存” or uses the card
        # action; only the sync endpoint can emit the terminal completion.
        _emit_progress(
            db,
            run["id"],
            phase="confirmation",
            status="waiting_confirmation",
            title="等待保存到系统",
            detail="学习任务草稿已生成，保存成功后本轮才完成",
        )
        _update_run(db, run["id"], status="waiting_confirmation")
        return
    payload: dict[str, Any] = {"summary": summary}
    _finalize_run(
        db,
        run["id"],
        event_type=events.RUN_COMPLETED,
        payload=payload,
        status="completed",
    )


async def execute_run(run_id: str, db_path: str) -> None:
    """Start a student run through the native durable LangGraph workflow."""

    await graph_runtime.run_student_graph(run_id, db_path)


async def continue_run(run_id: str, db_path: str) -> None:
    """Resume a confirmed student graph through its checkpoint thread."""

    await graph_runtime.resume_student_graph(run_id, db_path)
