"""掌握度域：mastery 读取/预览/落库（蓝图 §12，PRD-06 §8.3/8.4）。

Pinned 公开签名（任务契约，签名不可改）：
- preview_from_deltas(db, user_id, deltas) -> list[dict]
- apply_updates(db, user_id, updates, *, source, ref_id=None) -> list[dict]
- get_mastery(db, user_id) -> list[dict]
- weak_caps(db, user_id, limit=5, threshold=0.6) -> list[dict]

公式（蓝图 §12 / PRD-06 §8.3，全站唯一事实来源，router/诊断引擎都从这里取）：
- 练习：new = clamp(old + 0.15*score - 0.1*(1-score))，即 delta = +0.15*s − 0.1*(1−s)
- 诊断扣分：major −0.2 / minor −0.05，按 cap 聚合
- 一律 clamp [0,1]；掌握度按用户与能力唯一归属，不再按业务场景拆分
- 每次实际落库都写 mastery_events 历史（PRD-06 §8.4 按时间序列保留）
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from ..db import utc_now_iso

# ---- 公式常数（蓝图 §12）----
EXERCISE_GAIN = 0.15  # 练习得分增益系数
EXERCISE_MISS = 0.1  # 未得分部分的惩罚系数
DIAG_MAJOR_DELTA = -0.2  # 诊断 major 错误单条扣分
DIAG_MINOR_DELTA = -0.05  # 诊断 minor 错误单条扣分
WEAK_THRESHOLD = 0.6  # 薄弱能力阈值（PRD 口径）
MASTERED_THRESHOLD = 0.8  # 已掌握阈值（PRD-01 §4.4 折叠口径）

SOURCE_EXERCISE = "exercise"
SOURCE_DIAGNOSTIC = "diagnostic"


def clamp_score(value: float) -> float:
    """掌握度只允许落在 [0,1]（PRD-06 §8.4：低于 0 钳到 0，高于 1 钳到 1）。"""
    return max(0.0, min(1.0, value))


def exercise_delta(score: float) -> float:
    """练习分数对应的掌握度增量：+0.15*score − 0.1*(1−score)。"""
    return EXERCISE_GAIN * score - EXERCISE_MISS * (1.0 - score)


def diagnostic_deltas(errors: list[dict]) -> list[dict]:
    """把诊断错误列表聚合为每 cap 一条的 delta（major −0.2 / minor −0.05）。

    为什么聚合到 cap 粒度：mastery 主键是 (user, cap)，同一 cap
    多条错误要合并成一次更新，否则 preview 与 apply 的 old/new 会对不上。
    """
    per_cap: dict[str, float] = {}
    order: list[str] = []  # 保持首次出现顺序，输出确定性
    for error in errors:
        cap_id = error.get("cap_id")
        if not cap_id:
            continue
        if cap_id not in per_cap:
            per_cap[cap_id] = 0.0
            order.append(cap_id)
        per_cap[cap_id] += (
            DIAG_MAJOR_DELTA if error.get("severity") == "major" else DIAG_MINOR_DELTA
        )
    return [
        {"cap_id": cap_id, "delta": round(per_cap[cap_id], 6)}
        for cap_id in order
    ]


def _current_score(db: sqlite3.Connection, user_id: str, cap_id: str) -> float:
    """读当前掌握度；无记录按 0.0 起算（未测评能力从 0 开始累计）。"""
    row = db.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = ?",
        (user_id, cap_id),
    ).fetchone()
    return float(row["score"]) if row else 0.0


def preview_from_deltas(db: sqlite3.Connection, user_id: str, deltas: list[dict]) -> list[dict]:
    """预览增量应用后的新旧分数（**不落库**）。

    输入 deltas: [{cap_id, delta}]；输出在其基础上补
    old_score/new_score（clamp 后），供确认门展示"掌握度变化预览"
    （PRD-01 §7 保存诊断摘要前必须展示预览）。
    """
    preview: list[dict[str, Any]] = []
    for item in deltas:
        cap_id = item["cap_id"]
        old = _current_score(db, user_id, cap_id)
        new = clamp_score(old + float(item.get("delta", 0.0)))
        preview.append(
            {
                "cap_id": cap_id,
                "delta": float(item.get("delta", 0.0)),
                "old_score": old,
                "new_score": new,
            }
        )
    return preview


def apply_updates(
    db: sqlite3.Connection,
    user_id: str,
    updates: list[dict],
    *,
    source: str,
    ref_id: str | None = None,
    commit: bool = True,
) -> list[dict]:
    """实际落库：upsert mastery + 每条写 mastery_events，返回应用结果（含新旧分）。

    只在用户确认后调用（确认门口径：诊断确认/练习确认才更新，PRD-06 §8.3）。
    与 preview_from_deltas 共用同一套 old+delta→clamp 计算，保证预览即所得。
    """
    applied: list[dict[str, Any]] = []
    now = utc_now_iso()
    for item in updates:
        cap_id = item["cap_id"]
        old = _current_score(db, user_id, cap_id)
        new = clamp_score(old + float(item.get("delta", 0.0)))
        db.execute(
            """
            INSERT INTO mastery (user_id, cap_id, score, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (user_id, cap_id)
            DO UPDATE SET score = excluded.score, source = excluded.source,
                          updated_at = excluded.updated_at
            """,
            (user_id, cap_id, new, source, now),
        )
        db.execute(
            """
            INSERT INTO mastery_events
              (id, user_id, cap_id, old_score, new_score, source, ref_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, user_id, cap_id, old, new, source, ref_id, now),
        )
        applied.append(
            {
                "cap_id": cap_id,
                "delta": float(item.get("delta", 0.0)),
                "old_score": old,
                "new_score": new,
            }
        )
    # Agent capability writes pass commit=False so mastery rows, action state,
    # and audit record share one transaction. Existing callers retain the
    # original commit-on-success behavior.
    if commit:
        db.commit()
    return applied


def _cap_names() -> dict[str, str]:
    """从 graphx 取 cap_id → 中文名映射；图谱不可用时降级为空映射（名称退回 cap_id）。

    为什么容忍失败：掌握度是用户数据，图谱文件是内容数据；内容缺失不应
    让用户数据接口整体 500。
    """
    try:
        from ..graphx import reason

        return {
            node["id"]: node.get("name") or node["id"]
            for node in reason.get_graph()["nodes"]
            if node.get("type") == "CAP"
        }
    except Exception:
        return {}


def get_mastery(db: sqlite3.Connection, user_id: str) -> list[dict]:
    """用户掌握度列表，拼接图谱中的能力中文名。"""
    rows = db.execute(
        "SELECT * FROM mastery WHERE user_id = ? ORDER BY cap_id",
        (user_id,),
    ).fetchall()
    names = _cap_names()
    return [
        {
            "cap_id": row["cap_id"],
            "cap_name": names.get(row["cap_id"], row["cap_id"]),
            "score": float(row["score"]),
            "source": row["source"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def weak_caps(
    db: sqlite3.Connection, user_id: str, limit: int = 5, threshold: float = WEAK_THRESHOLD
) -> list[dict]:
    """薄弱能力：score < threshold，按分数升序（最弱在前），拼中文名。

    只统计**有记录**的能力——没测评过的能力不算"薄弱"，避免把未学习
    误报成薄弱。
    """
    rows = db.execute(
        """
        SELECT * FROM mastery
        WHERE user_id = ? AND score < ?
        ORDER BY score ASC, cap_id ASC
        LIMIT ?
        """,
        (user_id, threshold, limit),
    ).fetchall()
    names = _cap_names()
    return [
        {
            "cap_id": row["cap_id"],
            "cap_name": names.get(row["cap_id"], row["cap_id"]),
            "score": float(row["score"]),
            "source": row["source"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
