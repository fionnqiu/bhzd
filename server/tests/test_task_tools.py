"""Agent learning-task card and staged creation contracts."""

from __future__ import annotations

import json

import pytest

from bhzd_py.tools import task_tools
from bhzd_py.tools.registry import ToolContext

from _agent_helpers import insert_user, make_db


def test_agent_task_card_keeps_the_four_learning_fields_without_legacy_workflow_data():
    """New task cards must not quietly reintroduce steps, resources, or rubrics."""

    card = task_tools.build_task_card(
        {
            "title": "语音边界练习",
            "description": "掌握短语音边界的判断方法",
            "knowledge_points": [{"title": "边界", "content": "停顿不等于边界"}],
            "exercises": [
                {
                    "question": "请选择正确边界",
                    "type": "multiple_choice",
                    "options": ["连续语义单元", "任意停顿"],
                    "reference_answer": "连续语义单元",
                }
            ],
        }
    )

    assert card["title"] == "语音边界练习"
    assert card["description"] == "掌握短语音边界的判断方法"
    assert card["knowledge_points"] == [{"title": "边界", "content": "停顿不等于边界"}]
    assert card["exercises"] == [
        {
            "question": "请选择正确边界",
            "type": "multiple_choice",
            "options": ["连续语义单元", "任意停顿"],
            "reference_answer": "连续语义单元",
        }
    ]
    assert {"steps", "resources", "rubric"}.isdisjoint(card)


def test_agent_confirmation_persists_reviewed_content_without_queuing_generation(
    tmp_db_path, monkeypatch
):
    """A reviewed single-task card must be the durable student lesson."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        queued: list[str] = []
        monkeypatch.setattr(
            task_tools, "queue_task_content", lambda _db, task_id: queued.append(task_id)
        )
        ctx = ToolContext(
            db=db,
            config=None,
            user_row=user,
            run_row=None,
            conversation_row=None,
            args={
                "title": "语音边界练习",
                "description": "掌握短语音边界的判断方法",
                "data_type": "audio",
                "knowledge_points": [{"title": "边界", "content": "停顿不等于边界"}],
                "exercises": [
                    {
                        "question": "请选择正确边界",
                        "type": "choice",
                        "options": ["连续语义单元", "任意停顿"],
                        "reference_answer": "连续语义单元",
                    },
                    {"question": "停顿一定是边界。", "type": "boolean"},
                ],
            },
        )

        result = task_tools.task_create_apply(ctx)
        task_id = result["task_id"]

        assert queued == []
        task = db.execute(
            "SELECT content_status, content_generated_at FROM learning_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        assert task["content_status"] == "done"
        assert task["content_generated_at"]
        points = db.execute(
            "SELECT title, content, sort_order FROM task_knowledge_points WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        assert [(point["title"], point["content"], point["sort_order"]) for point in points] == [
            ("边界", "停顿不等于边界", 0)
        ]
        exercises = db.execute(
            "SELECT question, type, options_json, reference_answer, sort_order "
            "FROM task_exercises WHERE task_id = ? ORDER BY sort_order",
            (task_id,),
        ).fetchall()
        assert [
            (
                exercise["question"],
                exercise["type"],
                json.loads(exercise["options_json"]) if exercise["options_json"] else [],
                exercise["reference_answer"],
                exercise["sort_order"],
            )
            for exercise in exercises
        ] == [
            ("请选择正确边界", "multiple_choice", ["连续语义单元", "任意停顿"], "连续语义单元", 0),
            ("停顿一定是边界。", "true_false", ["正确", "错误"], "", 1),
        ]
    finally:
        db.close()


def test_agent_staged_preview_freezes_default_detail_for_each_stage(tmp_db_path, monkeypatch):
    """Stages without supplied detail receive distinct content before confirmation."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        queued: list[str] = []
        monkeypatch.setattr(
            task_tools, "queue_task_content", lambda _db, task_id: queued.append(task_id)
        )
        ctx = ToolContext(
            db=db,
            config=None,
            user_row=user,
            run_row=None,
            conversation_row=None,
            args={
                "stages": [
                    {"title": "文本标注·阶段1", "description": "学习实体边界", "data_type": "text"},
                    {"title": "文本标注·阶段2", "description": "完成边界复核", "data_type": "text"},
                ]
            },
        )

        preview = task_tools.task_create_preview(ctx)
        result = task_tools.task_create_apply(ctx)

        assert queued == []
        preview_cards = preview["stages"]
        created_cards = [item["card"] for item in result["tasks"]]
        assert created_cards == preview_cards
        assert all(card["knowledge_points"] and card["exercises"] for card in preview_cards)
        assert "学习实体边界" in preview_cards[0]["knowledge_points"][0]["content"]
        assert "完成边界复核" in preview_cards[1]["knowledge_points"][0]["content"]
        persisted = db.execute(
            "SELECT task_knowledge_points.task_id, task_knowledge_points.title, task_knowledge_points.content "
            "FROM task_knowledge_points "
            "JOIN learning_tasks ON learning_tasks.id = task_knowledge_points.task_id "
            "WHERE task_id IN (?, ?) ORDER BY learning_tasks.title, sort_order",
            tuple(result["task_ids"]),
        ).fetchall()
        assert [(row["title"], row["content"]) for row in persisted] == [
            (card["knowledge_points"][0]["title"], card["knowledge_points"][0]["content"])
            for card in preview_cards
        ]
    finally:
        db.close()


def test_explicit_stages_create_independent_detailed_tasks_with_their_own_content(
    tmp_db_path, monkeypatch
):
    """Each confirmed stage persists only its own detailed lesson and practice."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        queued: list[str] = []
        monkeypatch.setattr(
            task_tools, "queue_task_content", lambda _db, task_id: queued.append(task_id)
        )
        ctx = ToolContext(
            db=db,
            config=None,
            user_row=user,
            run_row=None,
            conversation_row=None,
            args={
                "source": "agent",
                "stages": [
                    {
                        "title": "文本标注练习任务·阶段1",
                        "description": "先学习实体边界规则",
                        "data_type": "text",
                        "knowledge_points": [{"title": "实体边界", "content": "标记完整实体范围"}],
                        "exercises": [
                            {
                                "question": "实体边界是否包含修饰词？",
                                "type": "true_false",
                                "reference_answer": "错误",
                            }
                        ],
                    },
                    {
                        "title": "文本标注练习任务·阶段2",
                        "description": "再完成实体边界练习",
                        "data_type": "text",
                        "knowledge_points": [{"title": "边界复核", "content": "逐项复核起止位置"}],
                        "exercises": [
                            {
                                "question": "选择正确的复核方式",
                                "type": "multiple_choice",
                                "options": ["核对起止位置", "只看标签名称"],
                                "reference_answer": "核对起止位置",
                            }
                        ],
                    },
                ],
            },
        )

        result = task_tools.task_create_apply(ctx)

        assert result["count"] == 2
        assert queued == []
        rows = db.execute(
            "SELECT id, title, goal, steps_json, resources_json, rubric_json, content_status FROM learning_tasks "
            "WHERE id IN (?, ?) ORDER BY title",
            tuple(result["task_ids"]),
        ).fetchall()
        assert [(row["title"], row["goal"]) for row in rows] == [
            ("文本标注练习任务·阶段1", "先学习实体边界规则"),
            ("文本标注练习任务·阶段2", "再完成实体边界练习"),
        ]
        assert all(row["steps_json"] == "[]" for row in rows)
        assert all(row["resources_json"] == "[]" for row in rows)
        assert all(row["rubric_json"] is None for row in rows)
        assert all(row["content_status"] == "done" for row in rows)
        content_by_title = {
            row["title"]: {
                "points": [
                    tuple(point)
                    for point in db.execute(
                        "SELECT title, content FROM task_knowledge_points WHERE task_id = ? ORDER BY sort_order",
                        (row["id"],),
                    ).fetchall()
                ],
                "exercises": [
                    tuple(exercise)
                    for exercise in db.execute(
                        "SELECT question, type FROM task_exercises WHERE task_id = ? ORDER BY sort_order",
                        (row["id"],),
                    ).fetchall()
                ],
            }
            for row in rows
        }
        assert content_by_title == {
            "文本标注练习任务·阶段1": {
                "points": [("实体边界", "标记完整实体范围")],
                "exercises": [("实体边界是否包含修饰词？", "true_false")],
            },
            "文本标注练习任务·阶段2": {
                "points": [("边界复核", "逐项复核起止位置")],
                "exercises": [("选择正确的复核方式", "multiple_choice")],
            },
        }
    finally:
        db.close()


def test_agent_stages_with_invalid_reviewed_content_roll_back_as_one_batch(tmp_db_path):
    """A malformed later stage must not leave an earlier task partially persisted."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        ctx = ToolContext(
            db=db,
            config=None,
            user_row=user,
            run_row=None,
            conversation_row=None,
            args={
                "stages": [
                    {
                        "title": "阶段1",
                        "description": "有效内容",
                        "knowledge_points": [{"title": "要点", "content": "正文"}],
                    },
                    {
                        "title": "阶段2",
                        "description": "无效选择题",
                        "exercises": [{"question": "没有选项", "type": "multiple_choice"}],
                    },
                ]
            },
        )

        with pytest.raises(ValueError, match="选择题至少需要一个选项"):
            task_tools.task_create_apply(ctx)

        assert db.execute("SELECT COUNT(*) FROM learning_tasks").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM task_knowledge_points").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM task_exercises").fetchone()[0] == 0
    finally:
        db.close()
