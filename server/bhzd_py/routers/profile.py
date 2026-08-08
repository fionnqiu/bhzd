"""个人中心路由（蓝图 §6.3，PRD-01 §9）+ 入学测评闭环（v3.0 §11.1）+ 学生入班小端点。

模块要点（为什么）：
- 入学测评状态完全由 learning_profiles 行的 onboarding_json 派生
  （completed_at → completed；skipped → skipped；无行 → not_started），
  不另设状态列，避免两处事实漂移。
- 收藏资料走 008 迁移的 favorites 表，(user_id, item_type, item_id) 唯一约束
  支撑"重复收藏幂等 upsert"。
- join-by-code 放在这里而不是新开模块：它是学生侧唯一与班级相关的动作，
  体量一个函数，单开文件只增加导航成本（任务书明确允许放 profile.py）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..audit import audit
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_current_user, get_db, require_student_portal_user
from ..errors import ApiError
from ..mastery import service as mastery_service
from ..seed import assessment as assessment_seed

# Profile, onboarding, and class self-enrollment are learner workflows.
router = APIRouter(dependencies=[Depends(require_student_portal_user)])

# favorites.item_type 与 008 迁移 CHECK 约束保持一致（这里先拦，给中文提示而非 500）
FAVORITE_ITEM_TYPES = ("rag_document", "citation", "teaching_unit", "graph_node")


def _scenario_names() -> dict[str, str]:
    """SCN id → 场景中文名（graphx 缺席降级空映射；'' 由调用方映射为"通用"）。"""
    try:
        from ..graphx import reason

        return {
            n["id"]: n.get("name") or n["id"]
            for n in reason.get_graph()["nodes"]
            if n.get("type") == "SCN"
        }
    except Exception:
        return {}


@router.get("/api/profile/mastery")
def profile_mastery(
    scenario_id: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """本人掌握度列表（能力中文名 + 场景中文名；'' → 通用）。"""
    items = mastery_service.get_mastery(conn, current.user["id"], scenario_id)
    scn_names = _scenario_names()
    for item in items:
        item["scenario_name"] = (
            "通用" if item["scenario_id"] == "" else scn_names.get(item["scenario_id"], item["scenario_id"])
        )
    return {"items": items, "total": len(items)}


@router.get("/api/profile/mastery/trend")
def mastery_trend(
    cap_id: str | None = None,
    days: int = 30,
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """本人掌握度变化时间序列（mastery_events），供成长趋势图使用。

    days 上限 365：趋势图没有看一年前逐次事件的场景，限制窗口避免全表扫。
    按时间升序返回（图表从左到右），date 取 created_at 的日期部分便于按天聚合。
    """
    days = max(1, min(days, 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    clauses = ["user_id = ?", "created_at >= ?"]
    params: list[Any] = [current.user["id"], since]
    if cap_id:
        clauses.append("cap_id = ?")
        params.append(cap_id)
    rows = conn.execute(
        f"""
        SELECT cap_id, scenario_id, old_score, new_score, source, created_at
        FROM mastery_events
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at ASC, id ASC
        """,
        params,
    ).fetchall()
    items = [
        {
            "date": row["created_at"][:10],
            "cap_id": row["cap_id"],
            "scenario_id": row["scenario_id"],
            "old_score": row["old_score"],
            "new_score": row["new_score"],
            "source": row["source"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": len(items), "days": days, "cap_id": cap_id}


@router.get("/api/profile")
def profile_overview(
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """个人中心聚合：任务统计 / 最近诊断摘要 / 成长时间线 / 收藏资料（PRD-01 §9）。"""
    user_id = current.user["id"]
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM learning_tasks WHERE user_id = ? GROUP BY status",
        (user_id,),
    ).fetchall()
    task_counts = {row["status"]: row["n"] for row in status_rows}

    summaries = conn.execute(
        """
        SELECT id, file_format, error_count, created_at
        FROM diagnostic_summaries WHERE user_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 5
        """,
        (user_id,),
    ).fetchall()

    events = conn.execute(
        """
        SELECT cap_id, scenario_id, old_score, new_score, source, created_at
        FROM mastery_events WHERE user_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 50
        """,
        (user_id,),
    ).fetchall()
    names = mastery_service._cap_names()  # 复用同一拼接逻辑（图谱降级一致）
    growth = [
        {
            "cap_id": e["cap_id"],
            "cap_name": names.get(e["cap_id"], e["cap_id"]),
            "scenario_id": e["scenario_id"],
            "old_score": e["old_score"],
            "new_score": e["new_score"],
            "source": e["source"],
            "created_at": e["created_at"],
        }
        for e in events
    ]

    # 收藏资料真实数据（008 起有 favorites 表）；聚合页只带最近 20 条保持轻量
    favorites = _list_favorites(conn, user_id, limit=20)

    return {
        "user": {
            "id": current.user["id"],
            "email": current.user["email"],
            "name": current.user["name"],
            "role": current.user["role"],
        },
        "task_counts": task_counts,
        "recent_diagnostic_summaries": [dict(s) for s in summaries],
        "growth": growth,
        "favorites": favorites,
        "settings": {"share_diagnostics": _read_share_flag(conn, user_id)},
    }


# ---------------------------------------------------------------- 收藏资料（PRD-01 §9）


def _favorite_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "item_type": row["item_type"],
        "item_id": row["item_id"],
        "title": row["title"],
        "meta": json.loads(row["meta_json"] or "{}"),
        "created_at": row["created_at"],
    }


def _list_favorites(conn: sqlite3.Connection, user_id: str, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM favorites WHERE user_id = ?
        ORDER BY created_at DESC, id DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [_favorite_dto(row) for row in rows]


class FavoriteBody(BaseModel):
    item_type: str
    item_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    meta: dict[str, Any] = {}


@router.get("/api/profile/favorites")
def list_favorites(
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """本人收藏列表（最新在前）。"""
    items = _list_favorites(conn, current.user["id"])
    return {"items": items, "total": len(items)}


@router.post("/api/profile/favorites")
def add_favorite(
    body: FavoriteBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """收藏一条资料；同一条目重复收藏按 upsert 幂等（更新标题/元数据，不产生重复行）。"""
    if body.item_type not in FAVORITE_ITEM_TYPES:
        raise ApiError(
            400,
            "ITEM_TYPE_INVALID",
            "收藏类型只能是 rag_document / citation / teaching_unit / graph_node",
        )
    if not body.title.strip():
        raise ApiError(400, "VALIDATION_ERROR", "收藏标题不能为空")
    if not body.item_id.strip():
        raise ApiError(400, "VALIDATION_ERROR", "收藏条目 id 不能为空")
    user_id = current.user["id"]
    existing = conn.execute(
        "SELECT * FROM favorites WHERE user_id = ? AND item_type = ? AND item_id = ?",
        (user_id, body.item_type, body.item_id),
    ).fetchone()
    if existing is not None:
        # 幂等去重：只刷新展示信息，保留原 id 与首次收藏时间
        conn.execute(
            "UPDATE favorites SET title = ?, meta_json = ? WHERE id = ?",
            (body.title.strip(), json.dumps(body.meta, ensure_ascii=False), existing["id"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM favorites WHERE id = ?", (existing["id"],)).fetchone()
        return {"favorite": _favorite_dto(row), "created": False}
    favorite_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO favorites (id, user_id, item_type, item_id, title, meta_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            favorite_id,
            user_id,
            body.item_type,
            body.item_id,
            body.title.strip(),
            json.dumps(body.meta, ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM favorites WHERE id = ?", (favorite_id,)).fetchone()
    return {"favorite": _favorite_dto(row), "created": True}


@router.delete("/api/profile/favorites/{favorite_id}")
def delete_favorite(
    favorite_id: str,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """删除本人收藏；他人收藏统一 404（不暴露存在性，与任务域口径一致）。"""
    row = conn.execute("SELECT * FROM favorites WHERE id = ?", (favorite_id,)).fetchone()
    if row is None or row["user_id"] != current.user["id"]:
        raise ApiError(404, "FAVORITE_NOT_FOUND", "收藏不存在")
    conn.execute("DELETE FROM favorites WHERE id = ?", (favorite_id,))
    conn.commit()
    return {"message": "已取消收藏"}


# ---------------------------------------------------------------- 入学测评（v3.0 §11.1）


def _load_onboarding(conn: sqlite3.Connection, user_id: str) -> tuple[sqlite3.Row | None, dict]:
    """读 learning_profiles 行并解析 onboarding_json（坏 JSON 按空 dict 容错）。"""
    row = conn.execute(
        "SELECT * FROM learning_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None or not row["onboarding_json"]:
        return row, {}
    try:
        return row, json.loads(row["onboarding_json"])
    except json.JSONDecodeError:
        return row, {}


def _onboarding_status(onboarding: dict) -> str:
    """状态派生单点：completed_at 优先于 skipped（都缺即未开始）。"""
    if onboarding.get("completed_at"):
        return "completed"
    if onboarding.get("skipped"):
        return "skipped"
    return "not_started"


def _upsert_onboarding(
    conn: sqlite3.Connection,
    user_id: str,
    onboarding: dict,
    *,
    goal: str | None = None,
    major: str | None = None,
) -> None:
    """写回 onboarding_json；行不存在时建行（goal/major 同步到独立列，供筛选统计）。"""
    now = utc_now_iso()
    payload = json.dumps(onboarding, ensure_ascii=False)
    existing = conn.execute(
        "SELECT user_id FROM learning_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO learning_profiles
              (user_id, goal_text, major, target_cert, onboarding_json, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (user_id, goal, major, payload, now, now),
        )
    else:
        conn.execute(
            """
            UPDATE learning_profiles
            SET onboarding_json = ?,
                goal_text = COALESCE(?, goal_text),
                major = COALESCE(?, major),
                updated_at = ?
            WHERE user_id = ?
            """,
            (payload, goal, major, now, user_id),
        )
    conn.commit()


class AssessmentSubmitBody(BaseModel):
    answers: dict[str, int] = {}
    goal: str | None = Field(default=None, max_length=200)
    major: str | None = Field(default=None, max_length=100)


@router.get("/api/onboarding/assessment")
def get_assessment(
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """入学测评题目（**不含答案**）+ 当前状态（not_started/completed/skipped）。"""
    _, onboarding = _load_onboarding(conn, current.user["id"])
    status = _onboarding_status(onboarding)
    questions = assessment_seed.public_questions()
    result: dict[str, Any] = {
        "status": status,
        "questions": questions,
        "total": len(questions),
    }
    if status == "completed":
        # 已完成时回带成绩摘要，前端可直接展示上次结果而不必重答
        result["result"] = {
            "score": onboarding.get("score"),
            "correct": onboarding.get("correct"),
            "completed_at": onboarding.get("completed_at"),
        }
    return result


@router.post("/api/onboarding/assessment")
def submit_assessment(
    body: AssessmentSubmitBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """提交测评答案 → 确定性评分 + 写初始掌握度（source='assessment'，clamp 0..1）。

    已完成过的账号拒绝重复提交（409）：重复提交会重复累加掌握度增量，
    入学测评的定位是"一次性初始定位"，复测应走练习/诊断链路。
    """
    user_id = current.user["id"]
    _, onboarding = _load_onboarding(conn, user_id)
    if _onboarding_status(onboarding) == "completed":
        raise ApiError(409, "ASSESSMENT_COMPLETED", "入学测评已完成，无需重复提交")

    results, correct = assessment_seed.score_answers(body.answers)
    total = len(results)
    score = round(correct / total, 6) if total else 0.0
    # 每题对应一个能力节点的初始掌握度：答对 +0.4，答错 +0.1 基线（任务契约）
    applied = mastery_service.apply_updates(
        conn,
        user_id,
        [{"cap_id": r["cap_id"], "scenario_id": "", "delta": r["delta"]} for r in results],
        source=assessment_seed.ASSESSMENT_SOURCE,
    )

    completed_at = utc_now_iso()
    new_onboarding = {
        **({k: v for k, v in onboarding.items() if k != "skipped"}),
        "goal": body.goal or onboarding.get("goal"),
        "major": body.major or onboarding.get("major"),
        "completed_at": completed_at,
        "score": score,
        "correct": correct,
    }
    _upsert_onboarding(conn, user_id, new_onboarding, goal=body.goal, major=body.major)
    return {
        "score": score,
        "correct": correct,
        "total": total,
        "mastery_applied": applied,
        "status": "completed",
    }


@router.post("/api/onboarding/skip")
def skip_assessment(
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """跳过入学测评（幂等）：onboarding_json 标记 skipped，前端据此不再强制测评。"""
    user_id = current.user["id"]
    _, onboarding = _load_onboarding(conn, user_id)
    status = _onboarding_status(onboarding)
    if status == "completed":
        raise ApiError(409, "ASSESSMENT_COMPLETED", "入学测评已完成，无需跳过")
    if status == "skipped":
        return {"status": "skipped", "message": "已跳过入学测评"}
    onboarding["skipped"] = True
    onboarding["skipped_at"] = utc_now_iso()
    _upsert_onboarding(conn, user_id, onboarding)
    return {"status": "skipped", "message": "已跳过入学测评"}


class JoinClassBody(BaseModel):
    invite_code: str


@router.post("/api/student/join-class")
def join_class(
    body: JoinClassBody,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生凭邀请码入班（幂等：已入班直接返回；离班后重入重置 joined_at）。"""
    clazz = conn.execute(
        "SELECT * FROM classes WHERE invite_code = ?", (body.invite_code.strip(),)
    ).fetchone()
    if clazz is None:
        raise ApiError(404, "INVITE_CODE_INVALID", "邀请码无效，请向教师确认后再试")
    existing = conn.execute(
        "SELECT * FROM class_enrollments WHERE class_id = ? AND student_id = ?",
        (clazz["id"], current.user["id"]),
    ).fetchone()
    if existing is not None and existing["left_at"] is None:
        return {"class_id": clazz["id"], "class_name": clazz["name"], "already_enrolled": True}
    if existing is not None:
        conn.execute(
            "UPDATE class_enrollments SET joined_at = ?, left_at = NULL "
            "WHERE class_id = ? AND student_id = ?",
            (utc_now_iso(), clazz["id"], current.user["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO class_enrollments (class_id, student_id, joined_at) VALUES (?, ?, ?)",
            (clazz["id"], current.user["id"], utc_now_iso()),
        )
    conn.commit()
    audit(
        conn,
        current.user,
        "class.join",
        target_type="class",
        target_id=clazz["id"],
        after={"via": "invite_code"},
    )
    return {"class_id": clazz["id"], "class_name": clazz["name"], "already_enrolled": False}


# ---------------------------------------------------------------- 个人设置（PRD-06 §15 #2）


class ProfileSettingsPatch(BaseModel):
    """个人设置变更体；目前仅诊断分享开关，逐字段可空便于扩展。"""

    share_diagnostics: bool | None = None


def _read_share_flag(conn: sqlite3.Connection, user_id: str) -> bool:
    row = conn.execute(
        "SELECT share_diagnostics FROM learning_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    return bool(row["share_diagnostics"]) if row is not None else False


@router.patch("/api/profile")
def update_profile_settings(
    body: ProfileSettingsPatch,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """学生自助设置：share_diagnostics=授权任课教师查看自己的诊断详情（默认关闭）。

    这是 PRD-06 待确认项 #2 采纳的产品决策（默认仅聚合、授权后看详情）；
    教师端两个诊断明细端点直接读 learning_profiles.share_diagnostics。
    """
    if body.share_diagnostics is None:
        raise ApiError(422, "VALIDATION_ERROR", "没有需要更新的设置项")
    user_id = current.user["id"]
    now = utc_now_iso()
    exists = conn.execute(
        "SELECT user_id FROM learning_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if exists is not None:
        conn.execute(
            "UPDATE learning_profiles SET share_diagnostics = ?, updated_at = ? WHERE user_id = ?",
            (int(body.share_diagnostics), now, user_id),
        )
    else:
        # 无画像行的老用户：补建行，其他字段维持默认
        conn.execute(
            "INSERT INTO learning_profiles (user_id, share_diagnostics, onboarding_json, created_at, updated_at) "
            "VALUES (?, ?, '{}', ?, ?)",
            (user_id, int(body.share_diagnostics), now, now),
        )
    conn.commit()
    audit(
        conn,
        current.user,
        "profile.share_diagnostics",
        target_type="user",
        target_id=user_id,
        after={"share_diagnostics": body.share_diagnostics},
    )
    return {"settings": {"share_diagnostics": body.share_diagnostics}}
