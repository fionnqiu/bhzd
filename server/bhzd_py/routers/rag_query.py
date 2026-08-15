"""学生端 RAG 问答路由（蓝图 §6.4，PRD-05 §4.3）。

权限：require_student_portal_user + csrf_protect；邮箱是否验证不再作为能力门槛。
学生强制 published_only=True——未发布资料永不进入学生召回（PRD-06 §4.4，AC4）；
教师/管理员可显式传 published_only=false 做预览（PRD-06 §15 #7）。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import get_config
from ..deps import (
    CurrentUser,
    csrf_protect,
    get_db,
    get_current_user,
    require_student_portal_user,
)
from ..rag.recall_logs import record_recall_logs
from ..rag.retriever import answer_question

logger = logging.getLogger(__name__)

# This is the learner Q&A surface.  Management preview remains isolated to the
# system-admin RAG APIs instead of granting teachers a student-portal bypass.
router = APIRouter(dependencies=[Depends(require_student_portal_user)])


class RagQueryBody(BaseModel):
    """POST /api/rag/query 请求体（蓝图 §6.4）。"""

    question: str
    data_type: str | None = None
    published_only: bool = True
    # Optional management-preview scope; student callers remain constrained by
    # the published-only guard while the selected document set narrows recall.
    document_ids: list[str] | None = None


def emit_telemetry(event_name: str, props: dict) -> None:
    """埋点上报：telemetry 模块由并发代理负责，缺失/异常一律静默跳过。"""
    try:
        from .. import telemetry

        telemetry.track(event_name, props)
    except Exception:
        pass


@router.post("/api/rag/query")
def rag_query(
    body: RagQueryBody,
    current: CurrentUser = Depends(get_current_user),
    _csrf: CurrentUser = Depends(csrf_protect),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """知识问答：召回 + 合成 + 引用；无可靠依据时拒答不编造（AC6）。"""
    question = body.question.strip()
    if not question:
        from ..errors import ApiError

        raise ApiError(422, "VALIDATION_ERROR", "问题不能为空")
    # Content admins retain learner access, but only system administrators can
    # opt into unpublished material because that is a RAG-management preview.
    published_only = (
        body.published_only if current.user["role"] == "system_admin" else True
    )
    emit_telemetry(
        "rag_query_submitted",
        {
            "user_id": current.user["id"],
            "data_type": body.data_type,
        },
    )
    answer = answer_question(
        db,
        get_config(),
        question,
        data_type=body.data_type,
        published_only=published_only,
        document_ids=body.document_ids,
    )
    # 召回记录（渠道 student_query）：引用即本次实际呈现给用户的命中，
    # 拒答时引用为空自然不落记录；写库失败不影响问答（helper 内部已兜底）
    record_recall_logs(
        db,
        query=question,
        user_id=current.user["id"],
        channel="student_query",
        hits=answer.citations,
    )
    emit_telemetry(
        "rag_retrieval_completed",
        {
            "user_id": current.user["id"],
            "refused": answer.refused,
            "citation_count": len(answer.citations),
        },
    )
    return asdict(answer)
