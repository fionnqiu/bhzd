"""Focused regression tests for intent routing that does not need orchestration."""

from __future__ import annotations

import pytest

from bhzd_py.agent import intents


@pytest.mark.parametrize(
    "text",
    [
        "你能直接帮我生成学习任务吗？",
        "请创建一个学习任务",
        "帮我生成练习任务",
    ],
)
def test_task_creation_requests_use_the_existing_clarification_flow(text: str):
    """Route explicit task requests before the generic question classifier.

    These requests do not provide a data type or scenario, so their converted
    intent must retain the normal clarification slots instead of invoking RAG.
    """

    intent = intents.detect(text)

    assert intent.kind == intents.KIND_TASK_CONVERT
    assert intent.missing == ["data_type", "scenario"]
    assert intents.next_question(intent) == intents.QUESTION_DATA_TYPE


@pytest.mark.parametrize(
    "text",
    [
        "如何生成学习任务？",
        "创建学习任务的方法是什么？",
    ],
)
def test_task_generation_explanations_remain_rag_questions(text: str):
    """Keep explanatory questions out of the imperative task-creation path."""

    assert intents.detect(text).kind == intents.KIND_RAG_QUESTION


@pytest.mark.parametrize(
    "text",
    ["你还记得之前我问过什么吗？", "我们前面聊过什么？", "请回顾这次对话"],
)
def test_conversation_recall_routes_to_private_direct_chat(text: str):
    """Recall wording must not send private chat history through public RAG."""

    assert intents.detect(text).kind == intents.KIND_CONVERSATION_RECALL
