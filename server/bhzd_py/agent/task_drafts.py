"""Agent 学习任务草稿：LLM 生成、持久化与显式同步落库。

为什么独立成模块：草稿生命周期（编排器生成 → 回答底部按钮预览 → 卡片
按钮同步）横跨编排器与 tasks 路由，放任哪一侧都会形成反向依赖。

设计要点：
- 卡内容与旧确认门任务卡同一存储契约：都经 task_tools.build_task_card
  归一化校验，LLM 只提供文案字段（title/goal/knowledge_points/exercises/
  est_minutes），data_type 与 cap_ids 始终来自确定性计划与图谱工具结果；
- 模型不可用或输出不合法时回退模板卡，链路对离线/降级环境保持可用；
- 同步幂等：status='synced' 后直接返回既有 task_ids，重复点击、刷新
  或重放都不会重复建任务；每次状态变化都重发 task.draft 完整投影事件，
  SSE 回放取最后一条即当前状态。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from typing import Any

from ..db import utc_now_iso
from ..tools import task_tools
from ..tools.registry import emit_telemetry
from . import composer, events, prompts

logger = logging.getLogger(__name__)

# 修订类请求才把上一版草稿交给模型参照；全新任务请求给旧卡会把生成带偏
_REVISION_CUE_RE = re.compile(r"修改|调整|更新|换成|改\s*一\s*下")


def _card_args_from_llm(base_args: dict[str, Any], llm_card: dict[str, Any] | None) -> dict[str, Any]:
    """只合并 LLM 的文案字段；接地字段（data_type/cap_ids/stages）不动。"""

    merged = dict(base_args)
    if llm_card:
        for key in ("title", "goal", "knowledge_points", "exercises", "est_minutes"):
            if llm_card.get(key) is not None:
                merged[key] = llm_card[key]
    return merged


def _build_cards(
    task_args: dict[str, Any], llm_payload: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], str]:
    """把（可能含 LLM 文案的）参数归一化成任务卡列表。

    返回 (cards, generator)。任何一卡校验失败只回退该卡为模板卡，
    不让一张坏卡拖垮整批；generator 记录内容来源供落库时标注。
    """

    raw_stages = task_args.get("stages")
    stage_args_list = (
        [stage for stage in raw_stages if isinstance(stage, dict)]
        if isinstance(raw_stages, list) and raw_stages
        else [task_args]
    )
    llm_cards: list[dict[str, Any]] = []
    if llm_payload:
        raw_llm_stages = llm_payload.get("stages")
        if isinstance(raw_llm_stages, list):
            llm_cards = [item for item in raw_llm_stages if isinstance(item, dict)]
        elif llm_payload.get("title") or llm_payload.get("knowledge_points"):
            llm_cards = [llm_payload]
    cards: list[dict[str, Any]] = []
    used_provider = False
    for index, stage in enumerate(stage_args_list):
        llm_card = llm_cards[index] if index < len(llm_cards) else None
        try:
            card = task_tools.build_task_card(_card_args_from_llm(stage, llm_card))
        except ValueError:
            # 单卡不合法（如选择题缺选项）只丢弃 LLM 文案，保留确定性字段
            logger.warning("任务草稿第 %s 卡校验失败，回退模板卡", index + 1, exc_info=True)
            card = task_tools.build_task_card(stage)
            llm_card = None
        if llm_card:
            used_provider = True
        cards.append(card)
    return cards, ("provider" if used_provider else "template")


def _evidence_context(results: dict[str, Any]) -> dict[str, Any]:
    """从读工具结果提取给模型的证据：能力标签 + 资料切片（限幅防溢出）。"""

    cap_hints: list[str] = []
    evidence: list[dict[str, str]] = []
    for result in results.values():
        if not isinstance(result, dict):
            continue
        for node in result.get("nodes") or []:
            if isinstance(node, dict):
                label = str(node.get("label") or node.get("id") or "").strip()
                if label and label not in cap_hints:
                    cap_hints.append(label)
        for hit in result.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title") or hit.get("document_title") or "").strip()
            excerpt = str(hit.get("chunk") or hit.get("text") or hit.get("excerpt") or "").strip()
            if title or excerpt:
                evidence.append({"title": title[:120], "excerpt": excerpt[:300]})
    return {"cap_hints": cap_hints[:8], "evidence": evidence[:5]}


def build_draft_messages(
    task_args: dict[str, Any],
    results: dict[str, Any],
    *,
    previous_cards: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """组装草稿生成请求：系统提示 + 目标/阶段/证据（不含任何模型自有发挥）。"""

    context = _evidence_context(results)
    stages = [s for s in task_args.get("stages") or [] if isinstance(s, dict)]
    payload: dict[str, Any] = {
        "学习目标": task_args.get("goal") or task_args.get("description") or "",
        "数据类型": task_args.get("data_type") or "未指定",
        "关联能力点": context["cap_hints"],
        "规范资料摘录": context["evidence"],
    }
    if stages:
        payload["阶段"] = [str(s.get("goal") or s.get("description") or "") for s in stages]
    if previous_cards:
        # 修订请求只给旧卡与证据，是否采纳修改意见由模型按学习目标判断
        payload["上一版任务卡"] = previous_cards
    return [
        {"role": "system", "content": prompts.TASK_DRAFT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _projection(draft_row: sqlite3.Row) -> dict[str, Any]:
    """task_drafts 行 → SSE/前端共用的完整状态投影（回放取最后一条）。"""

    try:
        card_payload = json.loads(draft_row["card_json"] or "{}")
    except json.JSONDecodeError:
        card_payload = {"cards": []}
    return {
        "id": draft_row["id"],
        "status": draft_row["status"],
        "source": draft_row["source"],
        "cards": [card for card in card_payload.get("cards") or [] if isinstance(card, dict)],
        "task_ids": json.loads(draft_row["task_ids_json"] or "[]"),
        "created_at": draft_row["created_at"],
        "synced_at": draft_row["synced_at"],
    }


def projections_by_run(
    db: sqlite3.Connection, conversation_id: str
) -> dict[str, dict[str, Any]]:
    """会话详情的历史草稿投影：run_id → 该 run 最新一张草稿的完整投影。"""

    rows = db.execute(
        """
        SELECT draft.* FROM task_drafts AS draft
        JOIN agent_runs AS run ON run.id = draft.run_id
        WHERE run.conversation_id = ?
        ORDER BY draft.created_at ASC, draft.rowid ASC
        """,
        (conversation_id,),
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        # 同一 run 可能先后生成多版草稿（继续修改），后写覆盖取最新
        result[row["run_id"]] = _projection(row)
    return result


def _latest_prior_cards(
    db: sqlite3.Connection, run_row: sqlite3.Row
) -> list[dict[str, Any]]:
    """取本会话上一版草稿卡，供「继续修改」场景让模型基于旧卡修订。"""

    row = db.execute(
        """
        SELECT card_json FROM task_drafts
        WHERE conversation_id = ? AND run_id != ? AND user_id = ?
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (run_row["conversation_id"], run_row["id"], run_row["user_id"]),
    ).fetchone()
    if row is None:
        return []
    try:
        payload = json.loads(row["card_json"] or "{}")
    except json.JSONDecodeError:
        return []
    return [card for card in payload.get("cards") or [] if isinstance(card, dict)]


async def generate_task_draft(
    db: sqlite3.Connection,
    *,
    run_row: sqlite3.Row,
    task_args: dict[str, Any],
    results: dict[str, Any],
) -> dict[str, Any]:
    """生成并持久化任务草稿，发出 task.draft 事件，返回其公开投影。

    LLM 调用失败/输出不合法不向上抛：草稿流程的职责是总能给出一张可
    预览、可同步的卡（回退模板），让回答底部按钮行为稳定。
    """

    llm_payload: dict[str, Any] | None = None
    try:
        # 仅修订类请求参照上一版草稿；全新任务请求给旧卡会把生成带偏
        goal_wording = str(task_args.get("goal") or task_args.get("description") or "")
        previous_cards = (
            _latest_prior_cards(db, run_row) if _REVISION_CUE_RE.search(goal_wording) else []
        )
        text = await composer.compose_text(
            build_draft_messages(task_args, results, previous_cards=previous_cards)
        )
        if text:
            llm_payload = task_tools._content_json(text)
            if llm_payload is None:
                logger.warning("任务草稿模型输出不是合法 JSON，回退模板卡")
    except Exception:
        # compose_text 内部已逐档降级；这里兜底防未来签名变化拖垮整轮运行
        logger.exception("任务草稿模型调用异常，回退模板卡")
    cards, generator = _build_cards(task_args, llm_payload)

    draft_id = uuid.uuid4().hex
    now = utc_now_iso()
    source = task_args.get("source") or "agent"
    db.execute(
        """
        INSERT INTO task_drafts
          (id, run_id, user_id, conversation_id, source, status, card_json, created_at)
        VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            draft_id,
            run_row["id"],
            run_row["user_id"],
            run_row["conversation_id"],
            source,
            json.dumps({"cards": cards, "generator": generator}, ensure_ascii=False, default=str),
            now,
        ),
    )
    db.commit()
    emit_telemetry(
        db,
        run_row["user_id"],
        "task_draft_created",
        {"draft_id": draft_id, "card_count": len(cards), "source": source, "generator": generator},
    )
    row = db.execute("SELECT * FROM task_drafts WHERE id = ?", (draft_id,)).fetchone()
    projection = _projection(row)
    events.emit(db, run_row["id"], events.TASK_DRAFT_UPDATED, {"draft": projection})
    return projection


def sync_task_draft(
    db: sqlite3.Connection, *, draft_row: sqlite3.Row, user_id: str
) -> dict[str, Any]:
    """把草稿落库为 learning_tasks（幂等）。

    卡片上的「同步到学习任务」按钮点击即学生对该内容的显式确认，因此
    这里直接写入而不再经过 pending_confirmations；已同步草稿重放既有
    结果，保证重复点击/双击/刷新不产生重复任务。
    """

    if draft_row["status"] == "synced":
        return {
            "draft_id": draft_row["id"],
            "status": "synced",
            "task_ids": json.loads(draft_row["task_ids_json"] or "[]"),
            "already_synced": True,
        }

    try:
        card_payload = json.loads(draft_row["card_json"] or "{}")
    except json.JSONDecodeError:
        card_payload = {}
    cards = [card for card in card_payload.get("cards") or [] if isinstance(card, dict)]
    if not cards:
        # 损坏草稿不落空任务：模板卡兜底保持按钮可用，同时保留草稿行供排查
        cards = [task_tools.build_task_card({})]

    source = draft_row["source"] or "agent"
    if source not in ("agent", "preset", "teacher", "diagnostic"):
        source = "agent"
    now = utc_now_iso()
    created: list[dict[str, Any]] = []
    try:
        for card in cards:
            task_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO learning_tasks
                  (id, user_id, title, goal, data_type, cap_ids_json,
                   source, status, steps_json, resources_json, rubric_json,
                   counts_toward_mastery, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'not_started', '[]', '[]', NULL, 1, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    card["title"],
                    card.get("description") or card.get("goal"),
                    card.get("data_type"),
                    json.dumps(card.get("cap_ids") or [], ensure_ascii=False),
                    source,
                    user_id,
                    now,
                    now,
                ),
            )
            # 卡内容即学生预览并确认的内容，按已审核内容落库（同确认门契约）
            task_tools._persist_task_content_rows(
                db,
                task_id,
                card["knowledge_points"],
                card["exercises"],
                now,
            )
            created.append({"task_id": task_id, "title": card["title"]})
        task_ids = [item["task_id"] for item in created]
        db.execute(
            "UPDATE task_drafts SET status = 'synced', task_ids_json = ?, synced_at = ? "
            "WHERE id = ?",
            (json.dumps(task_ids, ensure_ascii=False), now, draft_row["id"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    emit_telemetry(
        db, user_id, "task_created", {"task_ids": task_ids, "source": source, "via": "task_draft"}
    )
    # 同步后的完整投影重发一次：同一 run 的 SSE 重连/历史回放据此把卡片
    # 置为已同步，无需额外的状态查询接口。
    updated = db.execute("SELECT * FROM task_drafts WHERE id = ?", (draft_row["id"],)).fetchone()
    events.emit(db, draft_row["run_id"], events.TASK_DRAFT_UPDATED, {"draft": _projection(updated)})
    return {
        "draft_id": draft_row["id"],
        "status": "synced",
        "task_ids": task_ids,
        "tasks": created,
        "already_synced": False,
    }
