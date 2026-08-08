"""Private, current-conversation vector memory for model-only chat context.

This module intentionally owns a separate table from public RAG documents. A
conversation fragment is private application state, not source material that
may be cited or retrieved by other learners.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

from ..config import get_config
from ..rag.embeddings import embed_chunks
from ..rag.local_embed import bytes_to_array, cosine_similarity

logger = logging.getLogger(__name__)


def index_message(
    db: sqlite3.Connection,
    *,
    message_id: str,
    user_id: str,
    conversation_id: str,
    run_id: str | None,
    role: str,
    content: str,
    created_at: str,
) -> None:
    """Index one persisted chat message without turning memory failures into chat failures."""

    if not get_config().conversation_memory_enabled or role not in {"user", "assistant", "system"}:
        return
    text = content.strip()
    if not text:
        return
    try:
        embeddings, model = embed_chunks(db, [text])
        db.execute(
            """
            INSERT INTO conversation_memory_chunks
              (id, user_id, conversation_id, message_id, run_id, role, content,
               embedding, embedding_model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
              user_id = excluded.user_id,
              conversation_id = excluded.conversation_id,
              run_id = excluded.run_id,
              role = excluded.role,
              content = excluded.content,
              embedding = excluded.embedding,
              embedding_model = excluded.embedding_model,
              created_at = excluded.created_at
            """,
            (
                uuid.uuid4().hex, user_id, conversation_id, message_id, run_id,
                role, text, embeddings[0], model, created_at,
            ),
        )
        db.commit()
    except Exception:
        # A provider outage or a newly upgraded database must not discard a
        # durable user message or prevent the assistant from answering.
        logger.warning("conversation memory indexing failed", exc_info=True)


def backfill_conversation(
    db: sqlite3.Connection, *, user_id: str, conversation_id: str
) -> None:
    """Index older persisted turns once, so an in-progress chat is complete after upgrade."""

    if not get_config().conversation_memory_enabled:
        return
    try:
        rows = db.execute(
            """
            SELECT m.id, m.run_id, m.role, m.content, m.created_at
            FROM messages AS m
            JOIN conversations AS c ON c.id = m.conversation_id
            LEFT JOIN conversation_memory_chunks AS memory ON memory.message_id = m.id
            WHERE m.conversation_id = ?
              AND c.user_id = ?
              AND m.role IN ('user', 'assistant', 'system')
              AND memory.message_id IS NULL
            ORDER BY m.created_at ASC, m.rowid ASC
            """,
            (conversation_id, user_id),
        ).fetchall()
    except Exception:
        logger.warning("conversation memory backfill lookup failed", exc_info=True)
        return
    for row in rows:
        index_message(
            db,
            message_id=row["id"],
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=row["run_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )


def retrieve_context(
    db: sqlite3.Connection,
    *,
    user_id: str,
    conversation_id: str,
    query: str,
    exclude_run_id: str | None = None,
) -> list[dict[str, str]]:
    """Return relevant private turns from exactly one user's current conversation."""

    config = get_config()
    text = query.strip()
    if not config.conversation_memory_enabled or not text:
        return []
    backfill_conversation(db, user_id=user_id, conversation_id=conversation_id)
    try:
        params: list[Any] = [user_id, conversation_id]
        sql = """
            SELECT role, content, embedding, created_at
            FROM conversation_memory_chunks
            WHERE user_id = ? AND conversation_id = ?
        """
        if exclude_run_id:
            # The current user message is already present as the final model
            # prompt. Excluding its run prevents it from being echoed as memory.
            sql += " AND (run_id IS NULL OR run_id != ?)"
            params.append(exclude_run_id)
        rows = db.execute(sql, params).fetchall()
        query_embedding = bytes_to_array(embed_chunks(db, [text])[0][0])
    except Exception:
        logger.warning("conversation memory retrieval failed", exc_info=True)
        return []

    scored = [
        (cosine_similarity(query_embedding, bytes_to_array(row["embedding"])), row)
        for row in rows
    ]
    relevant = [item for item in scored if item[0] > 0]
    relevant.sort(key=lambda item: (-item[0], item[1]["created_at"]))
    selected = relevant[:config.conversation_memory_top_k]
    # Chronological context reads naturally and avoids implying a relevance
    # ranking to the model after scoring has selected the useful turns.
    selected.sort(key=lambda item: item[1]["created_at"])
    return [
        {"role": row["role"], "content": row["content"]}
        for _, row in selected
    ]


def format_context(chunks: list[dict[str, str]]) -> str:
    """Render private memory as internal system context, never as a citation payload."""

    return "\n".join(f"{chunk['role']}: {chunk['content']}" for chunk in chunks)
