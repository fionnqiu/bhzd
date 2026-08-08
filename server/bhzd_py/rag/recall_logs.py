"""召回记录写入（迁移 007 recall_logs 表的唯一写入口）。

为什么单独成模块：学生端问答（routers/rag_query.py）与管理端召回测试台
（routers/rag_admin.py）都要写召回记录，收敛到一个 helper 保证字段语义一致；
资料详情页的"召回记录"端点据此表展示某资料被哪些查询命中过。

设计红线：召回记录是观测性数据，写库失败绝不能拖垮问答/测试主流程，
因此本模块对所有异常静默降级（记 warning 日志），永不向上抛错。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Iterable

from ..db import utc_now_iso

logger = logging.getLogger(__name__)

# 单次查询最多落库的命中条数：防止大 top_k 刷爆记录表
MAX_LOGS_PER_QUERY = 20


def record_recall_logs(
    db: sqlite3.Connection,
    *,
    query: str,
    user_id: str | None,
    channel: str,
    hits: Iterable[dict],
) -> int:
    """把一次查询返回的命中写入 recall_logs，返回写入条数（失败返回 0）。

    hits 元素需含 document_id / score，可选 chunk_id（学生端引用不含
    chunk_id，该列允许为空）。channel 取值：student_query / search_test。
    """
    try:
        now = utc_now_iso()
        count = 0
        for hit in list(hits)[:MAX_LOGS_PER_QUERY]:
            db.execute(
                """
                INSERT INTO recall_logs (id, document_id, chunk_id, query, user_id,
                                         channel, score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    hit.get("document_id"),
                    hit.get("chunk_id"),
                    query,
                    user_id,
                    channel,
                    hit.get("score"),
                    now,
                ),
            )
            count += 1
        db.commit()
        return count
    except Exception as exc:  # 观测性数据失败不阻断主流程（见模块 docstring）
        logger.warning("召回记录写入失败（已忽略，不影响主流程）：%s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
