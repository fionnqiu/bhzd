"""预设学习路由（蓝图 §6.3，PRD-01 §4）。

关键决策（为什么）：
- 预设内容是代码内置数据（seed/presets.py，随版本发布），路由只负责
  过滤、拼接图谱/单元信息与个性化排序，不做内容存储。
- "开始学习"走确认门（蓝图 §6.3 action=task.create）：这里只生成
  pending_confirmations + 预览卡，真正的 learning_tasks 写入由 Agent 域的
  confirmations 确认端点执行——预览载荷里带齐建任务所需的全部字段。
- 个性化（PRD-01 §4.4）：已掌握（≥0.8）能力标记并整体折叠，含薄弱能力的
  路径优先展示，让学生先看到"最该补的"。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends

from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db, require_student_portal_user
from ..diagnosis.engine import load_teaching_units
from ..errors import ApiError
from ..mastery.service import MASTERED_THRESHOLD, WEAK_THRESHOLD
from ..seed.presets import get_presets

# Presets create learner-owned plans, so direct API requests share the shell policy.
router = APIRouter(dependencies=[Depends(require_student_portal_user)])

CONFIRM_TTL_MINUTES = 30  # 普通写确认门 30min（PRD-06 §6.4）
SYSTEM_CONVERSATION_TITLE = "预设学习"  # 预设启动复用的系统会话标题


def _track(conn: sqlite3.Connection, user_id: str | None, name: str, props: dict) -> None:
    """埋点（telemetry 缺席兜底直写；失败吞掉，见 diagnostics 同名函数）。"""
    try:
        try:
            from .. import telemetry  # type: ignore

            track = (
                getattr(telemetry, "emit_event", None)
                or getattr(telemetry, "track", None)
                or getattr(telemetry, "track_event", None)
            )
            if track is not None:
                # emit_event(db, user_id, name, props) 为 B1 当前接口；全位置参数调用
                track(conn, user_id, name, props)
                return
        except ImportError:
            pass
        conn.execute(
            "INSERT INTO analytics_events (user_id, event_name, props_json, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, json.dumps(props, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    except Exception:
        pass


def _cap_names() -> dict[str, str]:
    """cap_id → 中文名（graphx 缺席降级空映射）。"""
    try:
        from ..graphx import reason

        return {
            n["id"]: n.get("name") or n["id"]
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "CAP"
        }
    except Exception:
        return {}


def _user_mastery(conn: sqlite3.Connection, user_id: str) -> dict[str, float]:
    """Return unified mastery scores used to personalize preset steps."""
    rows = conn.execute(
        "SELECT cap_id, score FROM mastery WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {row["cap_id"]: float(row["score"]) for row in rows}


def _mastery_status(score: float | None) -> str:
    """与图谱页配色同一套口径（v3.0 §7.3.3）：已掌握/待加强/初学。"""
    if score is None:
        return "beginner"
    if score >= MASTERED_THRESHOLD:
        return "mastered"
    if score < 0.4:
        return "weak"
    return "beginner"


def _unit_index() -> dict[str, dict]:
    return {u["id"]: u for u in load_teaching_units()}


def _preset_dto(preset: dict, mastery: dict[str, float]) -> dict:
    """PresetDTO + 个性化字段（caps 带掌握状态、mastered_collapsed 折叠标记）。"""
    names = _cap_names()
    units = _unit_index()
    caps = [
        {
            "cap_id": cid,
            "cap_name": names.get(cid, cid),
            "mastery_status": _mastery_status(mastery.get(cid)),
            "score": mastery.get(cid),
        }
        for cid in preset["cap_ids"]
    ]
    mastered_count = sum(1 for c in caps if c["mastery_status"] == "mastered")
    weak_count = sum(
        1
        for c in caps
        if c["score"] is not None and c["score"] < WEAK_THRESHOLD
    )
    return {
        "id": preset["id"],
        "title": preset["title"],
        "description": preset["description"],
        "data_type": preset["data_type"],
        "goal": preset["goal"],
        "difficulty": preset["difficulty"],
        "est_minutes": preset["est_minutes"],
        "cap_ids": preset["cap_ids"],
        "unit_ids": preset["unit_ids"],
        "recommended_for": preset["recommended_for"],
        "caps": caps,
        "units": [
            {"unit_id": uid, "title": units.get(uid, {}).get("title", uid)}
            for uid in preset["unit_ids"]
        ],
        # 全部能力已掌握 → 前端默认折叠该路径的能力区（PRD-01 §4.4）
        "mastered_collapsed": bool(caps) and mastered_count == len(caps),
        "weak_count": weak_count,
    }


def _get_preset_or_404(preset_id: str) -> dict:
    for preset in get_presets():
        if preset["id"] == preset_id:
            return preset
    raise ApiError(404, "PRESET_NOT_FOUND", "预设学习路径不存在")


@router.get("/api/presets")
def list_presets(
    data_type: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """预设列表：数据类型筛选 + 薄弱优先排序。

    Goal/difficulty remain in the DTO because groupOf() and card copy use them,
    but they are intentionally not user-facing query dimensions.
    """
    mastery = _user_mastery(conn, current.user["id"])
    items = []
    for preset in get_presets():
        if data_type and preset["data_type"] != data_type:
            continue
        items.append(_preset_dto(preset, mastery))
    # 薄弱优先 → 未掌握多者优先 → 难度低者优先（学习路径由浅入深）
    items.sort(
        key=lambda p: (
            -p["weak_count"],
            sum(1 for c in p["caps"] if c["mastery_status"] != "mastered"),
            p["difficulty"],
            p["id"],
        )
    )
    return {"items": items, "total": len(items)}


@router.get("/api/presets/{preset_id}")
def preset_detail(
    preset_id: str,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """预设详情：DTO + 关联单元（标题/目标/时长）+ 能力（含前置）。"""
    preset = _get_preset_or_404(preset_id)
    mastery = _user_mastery(conn, current.user["id"])
    dto = _preset_dto(preset, mastery)
    units = _unit_index()
    dto["units"] = [
        {
            "unit_id": uid,
            "title": units.get(uid, {}).get("title", uid),
            "data_type": units.get(uid, {}).get("data_type"),
            "goals": units.get(uid, {}).get("goals", []),
        }
        for uid in preset["unit_ids"]
    ]
    return dto


@router.post("/api/presets/{preset_id}/start", status_code=201)
def start_preset(
    preset_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """开始预设学习：生成首个任务预览 + pending_confirmation（确认后才真正建任务）。"""
    preset = _get_preset_or_404(preset_id)
    units = _unit_index()
    first_unit = units.get(preset["unit_ids"][0]) if preset["unit_ids"] else None

    # 首个任务卡只保留任务正文四字段；历史单元目标作为描述素材，
    # 不再转换成操作步骤或资源绑定。
    if first_unit:
        title = f"{preset['title']}·第1课：{first_unit.get('title', preset['title'])}"
        description = "；".join(first_unit.get("goals") or []) or first_unit.get("title", "开始学习")
    else:
        title = preset["title"]
        description = preset["description"]
    # 预览载荷必须带齐 task.create 所需的全部字段（Agent 确认端点原样落库）
    preview = {
        "title": title,
        "goal": preset["goal"] or description,
        "description": description,
        "data_type": preset["data_type"] if preset["data_type"] != "general" else None,
        "cap_ids": preset["cap_ids"],
        "source": "preset",
        "preset_id": preset["id"],
        "counts_toward_mastery": 1,
    }

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=CONFIRM_TTL_MINUTES)).isoformat()
    # 复用（或创建）该生的"预设学习"系统会话，避免每次启动都开新会话
    conversation = conn.execute(
        "SELECT id FROM conversations WHERE user_id = ? AND title = ? AND deleted_at IS NULL "
        "ORDER BY created_at LIMIT 1",
        (current.user["id"], SYSTEM_CONVERSATION_TITLE),
    ).fetchone()
    if conversation is None:
        conversation_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, data_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                current.user["id"],
                SYSTEM_CONVERSATION_TITLE,
                preset["data_type"],
                utc_now_iso(),
                utc_now_iso(),
            ),
        )
    else:
        conversation_id = conversation["id"]
    run_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO agent_runs (id, conversation_id, user_id, status, input_text,
                                data_type, created_at)
        VALUES (?, ?, ?, 'waiting_confirmation', ?, ?, ?)
        """,
        (
            run_id,
            conversation_id,
            current.user["id"],
            f"开始预设学习:{preset_id}",
            preset["data_type"],
            utc_now_iso(),
        ),
    )
    tool_call_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO tool_calls (id, run_id, tool_name, permission, status, args_json,
                                is_write, created_at)
        VALUES (?, ?, 'task.create', 'write', 'awaiting_confirmation', ?, 1, ?)
        """,
        (tool_call_id, run_id, json.dumps(preview, ensure_ascii=False), utc_now_iso()),
    )
    confirmation_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO pending_confirmations
          (id, run_id, user_id, tool_call_id, action_type, preview_json, status,
           expires_at, created_at)
        VALUES (?, ?, ?, ?, 'task.create', ?, 'pending', ?, ?)
        """,
        (
            confirmation_id,
            run_id,
            current.user["id"],
            tool_call_id,
            json.dumps(preview, ensure_ascii=False),
            expires_at,
            utc_now_iso(),
        ),
    )
    conn.commit()
    _track(conn, current.user["id"], "preset_clicked", {"preset_id": preset_id})
    return {
        "confirmation": {
            "id": confirmation_id,
            "action_type": "task.create",
            "status": "pending",
            "expires_at": expires_at,
            "run_id": run_id,
        },
        "preview": preview,
    }
