"""Agent 任务卡数据契约测试。"""

from __future__ import annotations

from bhzd_py.tools.task_tools import build_task_card


def test_agent_task_card_default_rubric_matches_deterministic_scorer_contract():
    """默认任务卡保存列表评分项，避免旧对象形 rubric 导致页面或评分器崩溃。"""
    rubric = build_task_card({})["rubric"]

    assert isinstance(rubric, list)
    assert rubric
    assert all({"key", "expected", "weight"}.issubset(item) for item in rubric)


def test_agent_task_card_normalizes_legacy_rules_object():
    """旧版预览对象在写任务前被归一为当前评分列表，保证历史调用兼容。"""
    rubric = build_task_card(
        {
            "rubric": {
                "full_score": 100,
                "rules": [{"rule": "边界完整", "score": 100}],
            }
        }
    )["rubric"]

    assert rubric == [{"key": "边界完整", "expected": "边界完整", "weight": 100}]
