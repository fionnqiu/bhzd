"""编排器单元测试：事件顺序 / 确认门停止 / 意图识别 / 模板降级（全离线）。"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from bhzd_py.agent import composer, conversation_memory, events, intents, orchestrator, prompts
from bhzd_py.db import utc_now_iso
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


def _visible_answer_progress(rows):
    """Return only progress rows that the student timeline may render."""

    return [
        row["payload"]
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
        and row["payload"].get("activity_id")
    ]


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


def _task_draft_card(db, run_id: str) -> dict:
    """Read the persisted task draft's first card, which is the plan's output contract."""

    row = db.execute(
        "SELECT card_json FROM task_drafts WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row is not None
    cards = json.loads(row["card_json"])["cards"]
    assert cards, "任务草稿至少包含一张任务卡"
    return cards[0]


def _capture_l3_data_type_preference(db, user_id: str, preference: str) -> None:
    """Store a durable user-originated L3 preference through its normal capture path."""

    run_id, conversation_id = insert_run(db, user_id, "记录学习偏好")
    now = utc_now_iso()
    db.executemany(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (uuid.uuid4().hex, conversation_id, run_id, "user", preference, now),
            (uuid.uuid4().hex, conversation_id, run_id, "assistant", "已记录你的学习偏好。", now),
        ],
    )
    db.commit()
    # Exercise the production L3 provenance path instead of seeding a profile
    # without the user message link required by the planner's privacy boundary.
    conversation_memory.capture_completed_response(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        run_id=run_id,
    )


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


def test_tool_activity_projection_classifies_and_redacts_payloads():
    """Learner events expose useful counts without exposing tool values."""

    assert events.execution_kind("shell.run") == "command"
    assert events.execution_kind("file.read") == "file"
    assert events.execution_kind("course.search") == "tool"
    assert "参数 2 项" in events.summarize_tool_input(
        {"query": "private", "token": "secret"}
    )
    assert events.summarize_tool_result(
        {"hits": [1, 2]}, status="completed"
    ) == "执行完成，返回 2 个检索结果"
    assert events.summarize_tool_result(
        {}, status="awaiting_confirmation"
    ) == "等待确认，尚未执行写入"
    assert events.public_tool_result("rag.search", {"hits": ["private excerpt"]}) is None
    assert events.public_tool_result("course.search", {"label": "课程"}) == {
        "label": "课程"
    }

    projected = events.redact_tool_payload(
        {"token": "top-secret", "nested": {"password": "pw"}, "label": "safe"}
    )
    assert projected == {
        "token": "[已隐藏]",
        "nested": {"password": "[已隐藏]"},
        "label": "safe",
    }


# ---------------------------------------------------------------------------
# intents.py
# ---------------------------------------------------------------------------

def test_intent_vehicle_audio_full():
    intent = intents.detect("我想学语音标注")
    assert intent.kind == intents.KIND_LEARN_GOAL
    assert intent.data_type == "audio"
    assert intent.missing == []
    assert intents.next_question(intent) is None


def test_intent_vague_goal_asks_data_type_first():
    intent = intents.detect("我想学标注")
    assert intent.kind == intents.KIND_LEARN_GOAL
    assert "data_type" in intent.missing
    # PRD-06 §6.2：优先追问数据类型，话术逐字
    assert intents.next_question(intent) == "你要学习的是文本、图像、语音还是视频标注？"


def test_intent_rag_question():
    intent = intents.detect("NER 标注的规范是什么？")
    assert intent.kind == intents.KIND_RAG_QUESTION
    assert intent.data_type == "text"
    assert intent.missing == []


@pytest.mark.parametrize("text", ["你是什么模型？", "你是谁？", "能做什么？"])
def test_intent_agent_identity_uses_direct_chat_kind(text):
    intent = intents.detect(text)
    assert intent.kind == intents.KIND_AGENT_IDENTITY
    assert intent.missing == []


def test_model_topic_without_agent_address_stays_rag_question():
    assert intents.detect("什么是模型？").kind == intents.KIND_RAG_QUESTION


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
    card = {
        "title": "语音标注练习任务",
        "description": "掌握唤醒词标注",
        "knowledge_points": [{"title": "规则"}],
        "exercises": [{"question": "判断边界"}],
    }
    text = composer.template_tool_summary("task.preview", {"card": card})
    assert "语音标注练习任务" in text
    assert "掌握唤醒词标注" in text
    assert "学习内容：1 项" in text
    assert "练习：1 题" in text


def test_template_summaries_list_the_actual_staged_preview_and_creation_results():
    """A batch confirmation must not be summarized as a single unnamed task."""

    stages = [
        {"title": "文本标注练习·阶段1", "description": "学习实体边界"},
        {"title": "文本标注练习·阶段2", "description": "完成实体练习"},
    ]
    preview = composer.template_tool_summary("task.preview", {"stages": stages})
    created = composer.template_tool_summary(
        "task.create",
        {
            "count": 2,
            "tasks": [
                {"task_id": "t1", "title": stages[0]["title"], "card": stages[0]},
                {"task_id": "t2", "title": stages[1]["title"], "card": stages[1]},
            ],
        },
    )

    assert "2 个分阶段学习任务预览" in preview
    assert "学习实体边界" in preview
    assert "2 个分阶段学习任务" in created
    assert "文本标注练习·阶段1" in created
    assert "文本标注练习·阶段2" in created
    assert composer.template_compact_tool_summary(
        "task.create", {"count": 2, "tasks": [{"card": stage} for stage in stages]}
    ) == "已创建 2 个分阶段学习任务。"


def test_explicit_stage_markers_produce_independent_descriptions():
    """Only explicit markers fan a learner request out into several tasks."""

    stages = orchestrator._extract_task_stages(
        "第一阶段：学习实体边界；第二阶段：完成实体边界练习",
        base_title="文本标注练习任务",
        data_type="text",
    )

    assert [(stage["title"], stage["description"]) for stage in stages] == [
        ("文本标注练习任务·阶段1", "学习实体边界"),
        ("文本标注练习任务·阶段2", "完成实体边界练习"),
    ]


def test_template_plan_summary_lists_steps():
    plan = {"steps": [{"id": "s1", "title": "召回相关资料", "status": "completed",
                       "tool": "rag.search"}]}
    text = composer.template_plan_summary(plan, {"s1": {"hits": [1, 2], "hit_count": 2}})
    assert "召回相关资料" in text and "命中 2 条" in text


def test_compact_summary_keeps_conclusions_but_drops_plan_markers():
    text = "✓ 召回资料\n命中 4 条相关内容。\n✓ 生成任务\n已生成学习任务。\n✓ 完成\n请继续练习。"

    compact = composer.compact_summary(text)

    assert compact == "命中 4 条相关内容。\n已生成学习任务。\n请继续练习。"
    assert len(compact.splitlines()) == 3


def test_template_compact_plan_summary_keeps_first_and_final_results():
    plan = {
        "steps": [
            {"id": "s1", "title": "召回资料", "status": "completed", "tool": "rag.search"},
            {"id": "s2", "title": "定位知识点", "status": "completed", "tool": "graph.reason"},
            {"id": "s3", "title": "生成任务", "status": "completed", "tool": "task.preview"},
            {"id": "s4", "title": "完成", "status": "completed"},
        ]
    }
    results = {
        "s1": {"hits": [{"id": "h1"}, {"id": "h2"}]},
        "s2": {"nodes": [{"id": "n1"}]},
        "s3": {"card": {"title": "NER 练习任务"}},
    }

    compact = composer.template_compact_plan_summary(plan, results)

    assert compact.splitlines() == [
        "资料检索完成：找到 2 条相关内容。",
        "知识图谱定位完成：找到 1 个相关节点。",
        "完成已完成。",
    ]


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
    visible = _visible_answer_progress(rows)
    # Clarifications do not create an execution plan until the learner supplies
    # the missing slot, and do not disclose a model-thinking activity.
    assert all(
        row["payload"]["phase"] != "understanding"
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
    )
    assert [(item["phase"], item["status"]) for item in visible] == [
        ("synthesis", "running"),
        ("synthesis", "completed"),
    ]
    assert {item["activity_id"] for item in visible} == {
        f"answer:{run_id}",
    }
    assert all(
        "activity_id" not in row["payload"]
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
        and row["payload"]["phase"] in {"tool", "retrieval", "system"}
    )
    # message.delta 单帧 ≤40 字符（契约）
    for row in rows:
        if row["event_type"] == events.MESSAGE_DELTA:
            assert len(row["payload"]["delta"]) <= 40


def test_goal_reply_reuses_captured_scope_and_becomes_the_plan_goal(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "嗨嗨")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))
    second_run = _insert_follow_up_run(db, user_id, conversation_id, "文本")
    asyncio.run(orchestrator.execute_run(second_run, tmp_db_path))
    third_run = _insert_follow_up_run(db, user_id, conversation_id, "学习规范")
    asyncio.run(orchestrator.execute_run(third_run, tmp_db_path))

    # This phrase is recognized as learn_goal, but answers the explicit goal
    # question rather than starting a new task with the old scope by accident.
    card = _task_draft_card(db, third_run)
    assert card["goal"] == "学习规范"
    assert card["data_type"] == "text"
    # 任务类意图不再停在 task.create 写门：草稿生成后本轮即完成
    assert db.execute(
        "SELECT status FROM agent_runs WHERE id = ?", (third_run,)
    ).fetchone()["status"] == "completed"


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

    new_run = _insert_follow_up_run(db, user_id, conversation_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(new_run, tmp_db_path))

    # A new request supplies its own scope, so the prior clarification must not
    # leak into this independent plan.
    card = _task_draft_card(db, new_run)
    assert card["goal"] == "我想学图像标注"
    assert card["data_type"] == "image"


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
    assert persisted["missing"] == ["goal"]
    assert persisted["awaiting_slot"] == "goal"


def test_new_recognized_intent_does_not_inherit_old_clarification(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    first_run, conversation_id = insert_run(db, user_id, "我想学标注")
    asyncio.run(orchestrator.execute_run(first_run, tmp_db_path))

    new_run = _insert_follow_up_run(db, user_id, conversation_id, "我想学图像标注")
    asyncio.run(orchestrator.execute_run(new_run, tmp_db_path))
    card = _task_draft_card(db, new_run)
    assert card["goal"] == "我想学图像标注"
    assert card["data_type"] == "image"


def test_l3_generic_preference_fills_omitted_student_task_type(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _capture_l3_data_type_preference(db, user_id, "我偏好音频标注练习。")

    run_id, _ = insert_run(db, user_id, "我想学客服标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    card = _task_draft_card(db, run_id)
    assert card["data_type"] == "audio"
    # The historical preference is reduced to an enum; it cannot replace the
    # current task wording or leak its original text into tool arguments.
    assert card["goal"] == "我想学客服标注"


def test_current_explicit_type_wins_over_conversation_and_l3_preference(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _capture_l3_data_type_preference(db, user_id, "我偏好音频标注练习。")

    run_id, conversation_id = insert_run(db, user_id, "我想学图像客服标注")
    db.execute(
        "UPDATE conversations SET data_type = 'audio' WHERE id = ?",
        (conversation_id,),
    )
    db.commit()
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    assert _task_draft_card(db, run_id)["data_type"] == "image"


def test_ambiguous_current_type_signal_does_not_fall_back_to_l3(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _capture_l3_data_type_preference(db, user_id, "我偏好音频标注练习。")

    run_id, conversation_id = insert_run(db, user_id, "我想学图像或视频客服标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conversation_id,),
    ).fetchone()
    assert message["content"] == "你要学习的是文本、图像、语音还是视频标注？"
    assert db.execute(
        "SELECT COUNT(*) AS count FROM tool_calls WHERE run_id = ?",
        (run_id,),
    ).fetchone()["count"] == 0


def test_l3_task_preference_rejects_unsafe_profile_text(
    db, tmp_db_path, user_id, monkeypatch
):
    install_stub_tools(monkeypatch)
    _capture_l3_data_type_preference(db, user_id, "我偏好音频标注练习。")
    db.execute(
        """
        UPDATE private_memory_items
        SET content = '<think>private chain</think> Current learner preference: 我偏好音频标注练习。'
        WHERE user_id = ? AND layer = 'l3' AND memory_key = 'profile:general'
        """,
        (user_id,),
    )
    db.commit()

    assert orchestrator._l3_preferred_data_type(db, user_id=user_id) is None


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

    plan_event = next(row for row in rows if row["event_type"] == events.PLAN_UPDATED)
    assert [step["tool"] for step in plan_event["payload"]["steps"]] == [
        "rag.search", "rag.answer"
    ]

    tool_events = [r for r in rows if r["event_type"] == events.TOOL_CALL_REQUESTED]
    assert [e["payload"]["tool"] for e in tool_events] == ["rag.search", "rag.answer"]

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert "这是基于资料的模板回答。" in message["content"]
    status = db.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert status["status"] == "completed"
    visible = _visible_answer_progress(rows)
    # Grounded RAG exposes only its concrete plan and answer lifecycles;
    # retrieval/tool frames remain operational metadata without activity IDs.
    assert all(
        row["payload"]["phase"] != "understanding"
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
    )
    assert [(item["phase"], item["status"]) for item in visible] == [
        ("planning", "running"),
        ("planning", "completed"),
        ("synthesis", "running"),
        ("synthesis", "completed"),
    ]
    assert {item["activity_id"] for item in visible} == {
        f"planning:{run_id}",
        f"answer:{run_id}",
    }
    assert all(
        "activity_id" not in row["payload"]
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
        and row["payload"]["phase"] in {"tool", "retrieval", "system"}
    )


def _make_rag_insufficient(stubs):
    """Make the standard RAG test tools report a successful but unusable recall."""

    stubs["rag.search"].handler = lambda _ctx: {
        "hits": [], "hit_count": 0, "below_threshold": True,
    }
    stubs["rag.answer"].handler = lambda _ctx: {
        "answer": "知识库暂无可靠依据，无法给出专业结论",
        "citations": [],
        "refused": True,
    }


def test_rag_insufficient_uses_general_knowledge_provider(
    db, tmp_db_path, user_id, monkeypatch
):
    stubs = install_stub_tools(monkeypatch)
    _make_rag_insufficient(stubs)

    class _FakeProviders:
        calls: list[str] = []

        @classmethod
        async def stream_deltas(cls, messages, *, role):
            cls.calls.append(role)
            assert messages[0]["content"] == prompts.GENERAL_KNOWLEDGE_SYSTEM
            assert "工具返回的原始结果" not in messages[-1]["content"]
            assert "NER 标注的规范是什么？" in messages[-1]["content"]
            yield {"delta": "NER 标注通常需要先明确实体边界和标签定义。"}
            yield {
                "done": True,
                "model": "general-model",
                "provider_id": "general-provider",
                "usage": {"prompt_tokens": 8, "completion_tokens": 12},
            }

    monkeypatch.setattr(composer, "_providers", lambda: _FakeProviders)
    run_id, conv_id = insert_run(db, user_id, "NER 标注的规范是什么？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == "NER 标注通常需要先明确实体边界和标签定义。"
    run = db.execute(
        "SELECT status, provider_id FROM agent_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert run["status"] == "completed"
    assert run["provider_id"] == "general-provider"
    assert _FakeProviders.calls == ["primary"]
    rows = fetch_events(tmp_db_path, run_id)
    assert events.CITATION_ATTACHED not in _event_types(rows)
    visible = _visible_answer_progress(rows)
    # The low-evidence fallback may use model knowledge, but it exposes only
    # plan/answer lifecycles rather than thinking or RAG internals.
    assert all(
        row["payload"]["phase"] != "understanding"
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
    )
    assert [(item["phase"], item["status"]) for item in visible] == [
        ("planning", "running"),
        ("planning", "completed"),
        ("synthesis", "running"),
        ("synthesis", "completed"),
    ]
    assert {item["activity_id"] for item in visible} == {
        f"planning:{run_id}",
        f"answer:{run_id}",
    }
    assert all(
        "activity_id" not in row["payload"]
        for row in rows
        if row["event_type"] == events.RUN_PROGRESS
        and row["payload"]["phase"] in {"tool", "retrieval", "system"}
    )


def test_rag_insufficient_uses_fallback_general_knowledge_provider(
    db, tmp_db_path, user_id, monkeypatch
):
    """A silent primary provider must let the configured fallback answer."""

    stubs = install_stub_tools(monkeypatch)
    _make_rag_insufficient(stubs)

    class _FallbackProviders:
        calls: list[str] = []

        @classmethod
        async def stream_deltas(cls, messages, *, role):
            cls.calls.append(role)
            assert messages[0]["content"] == prompts.GENERAL_KNOWLEDGE_SYSTEM
            if role == "primary":
                return
            yield {"delta": "NER 标注要先统一实体类别与边界规则。"}

    monkeypatch.setattr(composer, "_providers", lambda: _FallbackProviders)
    run_id, conv_id = insert_run(db, user_id, "NER 标注的规范是什么？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == "NER 标注要先统一实体类别与边界规则。"
    assert _FallbackProviders.calls == ["primary", "fallback"]
    assert events.CITATION_ATTACHED not in _event_types(fetch_events(tmp_db_path, run_id))


def test_rag_insufficient_reports_model_unavailable_when_providers_do_not_respond(
    db, tmp_db_path, user_id, monkeypatch
):
    stubs = install_stub_tools(monkeypatch)
    _make_rag_insufficient(stubs)

    class _UnavailableProviders:
        stream_roles: list[str] = []
        complete_roles: list[str] = []

        @classmethod
        async def stream_deltas(cls, _messages, *, role):
            cls.stream_roles.append(role)
            if False:
                yield {}

        @classmethod
        async def complete(cls, _messages, *, role):
            cls.complete_roles.append(role)
            return None

    monkeypatch.setattr(composer, "_providers", lambda: _UnavailableProviders)
    run_id, conv_id = insert_run(db, user_id, "NER 标注的规范是什么？")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert message["content"] == prompts.GENERAL_KNOWLEDGE_UNAVAILABLE
    assert "知识库" not in message["content"]
    assert "资料不足" not in message["content"]
    assert _UnavailableProviders.stream_roles == ["primary", "fallback"]
    assert _UnavailableProviders.complete_roles == ["primary", "fallback"]
    assert events.CITATION_ATTACHED not in _event_types(fetch_events(tmp_db_path, run_id))


def _insert_diagnose_run(db, user_id: str) -> tuple[str, str]:
    """插入一条诊断上传运行：其计划仍含 diagnostic.save_summary 写门。"""

    run_id, conv_id = insert_run(db, user_id, "帮我诊断标注结果")
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps({"attachment": {"diagnostic_token": "tok-1"}}), run_id),
    )
    db.commit()
    return run_id, conv_id


def test_task_intent_generates_draft_without_write_gate(db, tmp_db_path, user_id, monkeypatch):
    """任务类意图的新链路：读工具 → 任务草稿落库 + task.draft 事件，不再开写门。"""

    install_stub_tools(monkeypatch)
    run_id, conv_id = insert_run(db, user_id, "我想学车载唤醒词标注")
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert run["status"] == "completed"
    tool_names = {
        row["tool_name"]
        for row in db.execute(
            "SELECT tool_name FROM tool_calls WHERE run_id = ?", (run_id,)
        ).fetchall()
    }
    assert "task.create" not in tool_names
    assert "task.preview" not in tool_names
    assert db.execute(
        "SELECT COUNT(*) AS c FROM pending_confirmations WHERE run_id = ?", (run_id,)
    ).fetchone()["c"] == 0

    # 离线 composer → 模板卡回退，但草稿仍落库且可同步（链路不断）
    draft = db.execute(
        "SELECT * FROM task_drafts WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert draft is not None and draft["status"] == "draft"
    cards = json.loads(draft["card_json"])["cards"]
    assert cards and cards[0]["data_type"] == "audio"
    rows = fetch_events(tmp_db_path, run_id)
    draft_events = [
        row for row in rows if row["event_type"] == events.TASK_DRAFT_UPDATED
    ]
    assert draft_events
    assert draft_events[-1]["payload"]["draft"]["id"] == draft["id"]
    assert _event_types(rows)[-1] == events.RUN_COMPLETED
    message = db.execute(
        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
        (conv_id,),
    ).fetchone()
    assert "查看学习任务卡" in message["content"]


def test_run_stops_at_write_gate(db, tmp_db_path, user_id, monkeypatch):
    install_stub_tools(monkeypatch)
    run_id, _ = _insert_diagnose_run(db, user_id)
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    assert run["status"] == "waiting_confirmation"

    confirmation = db.execute(
        "SELECT * FROM pending_confirmations WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert confirmation is not None
    assert confirmation["action_type"] == "diagnostic.save_summary"
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
    assert by_name["diagnostic.save_summary"] == "awaiting_confirmation"
    assert by_name["diagnostic.preview"] == "completed"


def test_continue_run_after_confirm(db, tmp_db_path, user_id, monkeypatch):
    stubs = install_stub_tools(monkeypatch)
    run_id, conv_id = _insert_diagnose_run(db, user_id)
    asyncio.run(orchestrator.execute_run(run_id, tmp_db_path))

    # 模拟确认路由：同步 apply + tool_call 置 completed（confirmations.py 的行为）
    tool_call = db.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
        (run_id,),
    ).fetchone()
    run = db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conv = db.execute(
        "SELECT * FROM conversations WHERE id = ?", (run["conversation_id"],)
    ).fetchone()
    ctx = ToolContext(db=db, config=None, user_row=user, run_row=run,
                      conversation_row=conv, args=json.loads(tool_call["args_json"]))
    result = stubs["diagnostic.save_summary"].apply(ctx)
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
