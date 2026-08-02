"""编排器单元测试：事件顺序 / 确认门停止 / 意图识别 / 模板降级（全离线）。"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from bhzd_py.agent import composer, events, intents, orchestrator
from bhzd_py.tools.registry import ToolContext

from _agent_helpers import (
    fetch_events,
    insert_run,
    insert_user,
    install_stub_tools,
    make_db,
)


@pytest.fixture()
def db(tmp_db_path):
    conn = make_db(tmp_db_path)
    yield conn
    conn.close()


@pytest.fixture()
def user_id(db):
    return insert_user(db)


@pytest.fixture(autouse=True)
def _offline_composer(monkeypatch):
    """Keep orchestration contracts deterministic even if a local provider is configured."""

    monkeypatch.setattr(composer, "_providers", lambda: None)


def _event_types(rows):
    return [r["event_type"] for r in rows]


def _insert_follow_up_run(db, user_id: str, conversation_id: str, input_text: str) -> str:
    """Insert a later run in the same conversation to exercise durable clarification."""

    run_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text, created_at)
        VALUES (?, ?, ?, 'running', ?, datetime('now'))
        """,
        (run_id, conversation_id, user_id, input_text),
    )
    db.commit()
    return run_id


def _task_create_args(db, run_id: str) -> dict:
    """Read the pending write's frozen arguments, which are the plan's output contract."""

    row = db.execute(
        "SELECT args_json FROM tool_calls WHERE run_id = ? AND tool_name = 'task.create'",
        (run_id,),
    ).fetchone()
    assert row is not None
    return json.loads(row["args_json"])


# ---------------------------------------------------------------------------
# events.py
# ---------------------------------------------------------------------------

def test_emit_seq_monotonic(db, user_id):
    run_id, _ = insert_run(db, user_id, "测试")
    s1 = events.emit(db, run_id, events.RUN_STARTED, {})
    s2 = events.emit(db, run_id, events.MESSAGE_DELTA, {"delta": "你好"})
    s3 = events.emit(db, run_id, events.RUN_COMPLETED, {})
    assert (s1, s2, s3) == (1, 2, 3)
    assert len(events.list_events(db, run_id, after_seq=1)) == 2


# ---------------------------------------------------------------------------
# intents.py
# ---------------------------------------------------------------------------

def test_intent_vehicle_audio_full():
    intent = intents.detect("我想学车载唤醒词标注")
    assert intent.kind == intents.KIND_LEARN_GOAL
    assert intent.data_type == "audio"
    assert intent.scenario_id == "SCN-IN-VEHICLE-001"
    assert intent.missing == []
    assert intents.next_question(intent) is None


def test_intent_vague_goal_asks_data_type_first():
    intent = intents.detect("我想学标注")
    assert intent.kind == intents.KIND_LEARN_GOAL
    assert "data_type" in intent.missing and "scenario" in intent.missing
    # PRD-06 §6.2：优先追问数据类型，话术逐字
    assert intents.next_question(intent) == "你要学习的是文本、图像、语音还是视频标注？"


def test_intent_rag_question():
    intent = intents.detect("NER 标注的规范是什么？")
    assert intent.kind == intents.KIND_RAG_QUESTION
    assert intent.data_type == "text"
    assert intent.missing == []


def test_intent_scenario_synonyms():
    assert intents.detect("我想学智能客服语音转写").scenario_id == "SCN-CUSTOMER-SERVICE-001"
    assert intents.detect("我想学医疗文本 NER 标注").scenario_id == "SCN-MEDICAL-001"
    assert intents.detect("我想学内容安全文本审核").scenario_id == "SCN-CONTENT-SAFETY-001"
    assert intents.detect("我想学座舱语音标注").scenario_id == "SCN-IN-VEHICLE-001"


def test_intent_explicit_generic_closes_scenario_slot():
    intent = intents.detect("我想学语音标注，通用场景")
    assert intent.generic_scenario is True
    assert "scenario" not in intent.missing


def test_apply_context_can_keep_a_resumed_slot_over_conversation_default():
    resumed = intents.detect("语音客服")
    # ``prefer_context=False`` is used only for a resumed clarification: the
    # prior answer must not be silently replaced by an older chat preference.
    scoped = intents.apply_context(
        resumed,
        data_type="image",
        scenario_id="SCN-IN-VEHICLE-001",
        prefer_context=False,
    )
    assert scoped.data_type == "audio"
    assert scoped.scenario_id == "SCN-CUSTOMER-SERVICE-001"


# ---------------------------------------------------------------------------
# composer 模板降级（零 provider 离线）
# ---------------------------------------------------------------------------

def test_compose_text_returns_none_without_providers():
    assert asyncio.run(composer.compose_text([{"role": "user", "content": "hi"}])) is None


def test_stream_text_empty_without_providers():
    async def collect():
        return [d async for d in composer.stream_text([{"role": "user", "content": "hi"}])]

    assert asyncio.run(collect()) == []


def test_template_tool_summary_renders_task_card():
    card = {"title": "语音标注练习任务", "goal": "掌握唤醒词标注",
            "steps": [{"title": "学习规范"}, {"title": "完成练习"}], "est_minutes": 45}
    text = composer.template_tool_summary("task.preview", {"card": card})
    assert "语音标注练习任务" in text and "学习规范" in text and "45" in text


def test_template_plan_summary_lists_steps():
    plan = {"steps": [{"id": "s1", "title": "召回相关资料", "status": "completed",
                       "tool": "rag.search"}]}
    text = composer.template_plan_summary(plan, {"s1": {"hits": [1, 2], "hit_count": 2}})
    assert "召回相关资料" in text and "命中 2 条" in text


# ---------------------------------------------------------------------------
# 编排器：完整运行 / 追问 / 确认门
# ---------------------------------------------------------------------------

def test_run_clarifies_and_completes(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, conv_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    rows = fetch_events(tmp_db_path, run_id)
    types = _event_types(rows)
    assert types[0] == events.RUN_STARTED
    assert events.MESSAGE_DELTA in types
    assert types[-1] == events.RUN_COMPLETED
    # 追问轮不出计划
    assert events.PLAN_UPDATED not in types

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == "你要学习的是文本、图像、语音还是视频标注？"
    status = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert status["status"] == "completed"
    # message.delta 单帧 ≤40 字符（契约）
    for row in rows:
        if row["event_type"] == events.MESSAGE_DELTA:
            assert len(row["payload"]["delta"]) <= 40


def test_three_turn_clarification_reuses_goal_and_fills_one_slot_each_time(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))

    second_run = _insert_follow_up_run(db, user_id, conversation_id, "语音")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))
    second_plan = json.loads(
        db.execute("SELECT plan_json FROM agent_runs WHERE id = ?", (second_run,)).fetchone()["plan_json"]
    )
    assert second_plan["clarification"]["data_type"] == "audio"
    assert second_plan["clarification"]["awaiting_slot"] == "scenario"

    third_run = _insert_follow_up_run(db, user_id, conversation_id, "客服")
    asyncio.run(orchestrator.execute_run(third_run, tmp_db_path))
    args = _task_create_args(db, third_run)
    assert args["goal"] == "我想学标注"
    assert args["data_type"] == "audio"
    assert args["scenario_id"] == "SCN-CUSTOMER-SERVICE-001"
    assert db.execute("SELECT status FROM agent_runs WHERE id = ?", (third_run,)).fetchone()["status"] == "waiting_confirmation"


def test_goal_reply_reuses_captured_scope_and_becomes_the_plan_goal(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "嗨嗨")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    second_run = _insert_follow_up_run(db, user_id, conversation_id, "语音")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))
    third_run = _insert_follow_up_run(db, user_id, conversation_id, "客服")
    asyncio.run(orchestrator.execute_run(third_run, tmp_db_path))

    fourth_run = _insert_follow_up_run(db, user_id, conversation_id, "学习规范")
    asyncio.run(orchestrator.execute_run(fourth_run, tmp_db_path))

    # This phrase is recognized as learn_goal, but answers the explicit goal
    # question rather than starting a new task with the old scope by accident.
    args = _task_create_args(db, fourth_run)
    assert args["goal"] == "学习规范"
    assert args["data_type"] == "audio"
    assert args["scenario_id"] == "SCN-CUSTOMER-SERVICE-001"
    assert db.execute(
        "SELECT status FROM agent_runs WHERE id = ?", (fourth_run,)
    ).fetchone()["status"] == "waiting_confirmation"


def test_full_goal_after_goal_question_does_not_inherit_old_scope(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "嗨嗨")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    second_run = _insert_follow_up_run(db, user_id, conversation_id, "语音")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))
    third_run = _insert_follow_up_run(db, user_id, conversation_id, "客服")
    asyncio.run(orchestrator.execute_run(third_run, tmp_db_path))

    new_run = _insert_follow_up_run(
        db, user_id, conversation_id, "我想学图像标注，通用场景"
    )
    asyncio.run(orchestrator.execute_run(new_run, tmp_db_path))

    # A new request supplies its own scope, so the prior audio/customer-service
    # clarification must not leak into this independent plan.
    args = _task_create_args(db, new_run)
    assert args["goal"] == "我想学图像标注，通用场景"
    assert args["data_type"] == "image"
    assert args["scenario_id"] is None


def test_clarification_payload_preserves_and_validates_question_slot():
    payload = {
        "kind": intents.KIND_UNKNOWN,
        "data_type": "audio",
        "scenario_id": "SCN-CUSTOMER-SERVICE-001",
        "generic_scenario": False,
        "goal_text": "嗨嗨",
        "missing": ["goal"],
        "awaiting_slot": "goal",
    }

    state = intents.ClarificationState.from_payload(payload)
    assert state is not None
    assert state.missing == ["goal"]
    assert state.awaiting_slot == "goal"

    # A mismatched persisted question is unsafe to resume and must be rejected.
    assert intents.ClarificationState.from_payload(
        {**payload, "awaiting_slot": "scenario"}
    ) is None


@pytest.mark.parametrize("intervening_status", ("failed", "waiting_confirmation"))
def test_nonresumable_direct_previous_run_blocks_older_clarification(
    db, tmp_db_path, user_id, monkeypatch, intervening_status
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))

    intervening_run = _insert_follow_up_run(db, user_id, conversation_id, "无关请求")
    db.execute(
        "UPDATE agent_runs SET status = ? WHERE id = ?",
        (intervening_status, intervening_run),
    )
    db.commit()

    answer_run = _insert_follow_up_run(db, user_id, conversation_id, "语音")
    asyncio.run(orchestrator.execute_run(answer_run, tmp_db_path))

    # The direct predecessor is not a completed clarification, so no older
    # goal may be revived when the user sends a terse follow-up.
    persisted = json.loads(
        db.execute(
            "SELECT plan_json FROM agent_runs WHERE id = ?", (answer_run,)
        ).fetchone()["plan_json"]
    )["clarification"]
    assert persisted["kind"] == intents.KIND_UNKNOWN
    assert persisted["goal_text"] == "语音"
    assert persisted["data_type"] == "audio"
    assert persisted["missing"] == ["scenario", "goal"]
    assert persisted["awaiting_slot"] == "scenario"


def test_generic_answer_closes_scenario_without_a_fourth_question(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    second_run = _insert_follow_up_run(db, user_id, conversation_id, "语音")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))

    third_run = _insert_follow_up_run(db, user_id, conversation_id, "通用")
    asyncio.run(orchestrator.execute_run(third_run, tmp_db_path))
    args = _task_create_args(db, third_run)
    assert args["goal"] == "我想学标注"
    assert args["data_type"] == "audio"
    assert args["scenario_id"] is None
    assert db.execute("SELECT status FROM agent_runs WHERE id = ?", (third_run,)).fetchone()["status"] == "waiting_confirmation"


def test_new_recognized_intent_does_not_inherit_old_clarification(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))

    new_run = _insert_follow_up_run(db, user_id, conversation_id, "我想学图像标注，通用场景")
    asyncio.run(orchestrator.execute_run(new_run, tmp_db_path))
    args = _task_create_args(db, new_run)
    assert args["goal"] == "我想学图像标注，通用场景"
    assert args["data_type"] == "image"
    assert args["scenario_id"] is None


def test_scope_priority_is_run_then_clarification_then_conversation(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    # An existing chat preference must not replace the just-answered scenario,
    # while an explicit selection attached to this run remains authoritative.
    db.execute(
        "UPDATE conversations SET data_type = 'image', scenario_id = 'SCN-IN-VEHICLE-001' WHERE id = ?",
        (conversation_id,),
    )
    second_run = _insert_follow_up_run(db, user_id, conversation_id, "客服")
    db.execute("UPDATE agent_runs SET data_type = 'video' WHERE id = ?", (second_run,))
    db.commit()

    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))
    args = _task_create_args(db, second_run)
    assert args["goal"] == "我想学标注"
    assert args["data_type"] == "video"
    assert args["scenario_id"] == "SCN-CUSTOMER-SERVICE-001"


def test_concurrent_runs_keep_provider_usage_on_their_own_run(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)

    class _FakeProviders:
        @staticmethod
        async def stream_deltas(messages, *, role):
            goal = messages[-1]["content"]
            if "甲" in goal:
                # Yield control so the other run can finish and would overwrite
                # a module-global usage value in the old implementation.
                await asyncio.sleep(0.02)
                yield {"delta": "甲的回答"}
                yield {
                    "done": True,
                    "model": "model-a",
                    "provider_id": "provider-a",
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                }
            else:
                await asyncio.sleep(0)
                yield {"delta": "乙的回答"}
                yield {
                    "done": True,
                    "model": "model-b",
                    "provider_id": "provider-b",
                    "usage": {"prompt_tokens": 22, "completion_tokens": 4},
                }

        @staticmethod
        async def complete(messages, *, role):
            return None

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_a, _ = insert_run(db, user_id, "甲的问题是什么？")
    run_b, _ = insert_run(db, user_id, "乙的问题是什么？")

    async def _run_both():
        await asyncio.gather(
            orchestrator.execute_run(run_a, tmp_db_path),
            orchestrator.execute_run(run_b, tmp_db_path),
        )

    asyncio.run(_run_both())
    rows = db.execute(
        "SELECT id, provider_id, usage_json FROM agent_runs WHERE id IN (?, ?)",
        (run_a, run_b),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    assert by_id[run_a]["provider_id"] == "provider-a"
    assert json.loads(by_id[run_a]["usage_json"]) == {"prompt_tokens": 11, "completion_tokens": 3}
    assert by_id[run_b]["provider_id"] == "provider-b"
    assert json.loads(by_id[run_b]["usage_json"]) == {"prompt_tokens": 22, "completion_tokens": 4}
    usage_a = [row["payload"] for row in fetch_events(tmp_db_path, run_a) if row["event_type"] == events.RUN_USAGE]
    usage_b = [row["payload"] for row in fetch_events(tmp_db_path, run_b) if row["event_type"] == events.RUN_USAGE]
    assert usage_a == [{"model": "model-a", "prompt_tokens": 11, "completion_tokens": 3}]
    assert usage_b == [{"model": "model-b", "prompt_tokens": 22, "completion_tokens": 4}]


def test_run_rag_question_full_flow(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, conv_id = insert_run(db, user_id, "NER 标注的规范是什么？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    rows = fetch_events(tmp_db_path, run_id)
    types = _event_types(rows)

    def idx(t):
        return types.index(t)

    # 事件顺序：started → plan → 两个工具各 requested/completed → citation → completed
    assert idx(events.RUN_STARTED) < idx(events.PLAN_UPDATED)
    assert idx(events.PLAN_UPDATED) < idx(events.TOOL_CALL_REQUESTED)
    assert idx(events.TOOL_CALL_REQUESTED) < idx(events.TOOL_CALL_COMPLETED)
    assert events.CITATION_ATTACHED in types
    assert idx(events.CITATION_ATTACHED) < idx(events.RUN_COMPLETED)
    assert types[-1] == events.RUN_COMPLETED

    tool_events = [r for r in rows if r["event_type"] == events.TOOL_CALL_REQUESTED]
    assert [e["payload"]["tool"] for e in tool_events] == ["rag.search", "rag.answer"]

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert "这是基于资料的模板回答。" in message["content"]
    status = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert status["status"] == "completed"


def test_run_stops_at_write_gate(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, _ = insert_run(db, user_id, "我想学车载唤醒词标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert run["status"] == "waiting_confirmation"

    confirmation = db.execute(
        "SELECT * FROM pending_confirmations WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert confirmation is not None
    assert confirmation["action_type"] == "task.create"
    assert confirmation["status"] == "pending"

    rows = fetch_events(tmp_db_path, run_id)
    types = _event_types(rows)
    assert events.CONFIRMATION_REQUIRED in types
    assert events.RUN_COMPLETED not in types  # 停在确认门，未收尾
    # 读工具已执行、写工具未执行
    tool_calls = db.execute(
        "SELECT tool_name, status FROM tool_calls WHERE run_id = ?", (run_id,)
    ).fetchall()
    by_name = {t["tool_name"]: t["status"] for t in tool_calls}
    assert by_name["task.create"] == "awaiting_confirmation"
    assert by_name["rag.search"] == "completed"


def test_continue_run_after_confirm(db, tmp_db_path, user_id, monkeypatch):
    stubs = install_stub_tools(monkeypatch)
    run_id, conv_id = insert_run(db, user_id, "我想学车载唤醒词标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    # 模拟确认路由：同步 apply + tool_call 置 completed（confirmations.py 的行为）
    tool_call = db.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? AND tool_name = 'task.create'",
        (run_id,),
    ).fetchone()
    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conv = db.execute(
        "SELECT * FROM conversations WHERE id = ?", (run["conversation_id"],)
    ).fetchone()
    ctx = ToolContext(db=db, config=None, user_row=user, run_row=run,
                      conversation_row=conv, args=json.loads(tool_call["args_json"]))
    result = stubs["task.create"].apply(ctx)
    db.execute(
        "UPDATE tool_calls SET status = 'completed', result_json = ? WHERE id = ?",
        (json.dumps(result, ensure_ascii=False), tool_call["id"]),
    )
    db.commit()

    asyncio.run(orchestrator.continue_run(run_id, tmp_db_path))

    final = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert final["status"] == "completed"
    rows = fetch_events(tmp_db_path, run_id)
    assert _event_types(rows)[-1] == events.RUN_COMPLETED
    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message is not None and message["content"]


def test_unknown_input_asks_goal_question(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, conv_id = insert_run(db, user_id, "嗯嗯")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))
    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    # unknown：数据类型未知 → 仍先问数据类型（PRD-06 §6.2 优先级）
    assert message["content"] == "你要学习的是文本、图像、语音还是视频标注？"
