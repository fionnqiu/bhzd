"""Private L0-L3 memory for model-only chat context.

L0 preserves the existing per-conversation message vectors.  L1 stores small,
safe message-derived facts, L2 stores a bounded task/scenario summary, and L3
stores the latest response-style preference.  Every durable layer is private to
one user and keeps source-message provenance so normal message deletion also
removes its derivatives.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from typing import Any, Iterable

from ..config import get_config
from ..db import connect
from ..rag.embeddings import embed_chunks
from ..rag.local_embed import bytes_to_array, cosine_similarity

logger = logging.getLogger(__name__)

_L0_ROLES = {"user", "assistant", "system"}
_RRF_K = 60
_ATOM_SPLIT_RE = re.compile(r"[.!?;\n]+")
_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_HIDDEN_TAG_RE = re.compile(
    r"<\s*(?P<closing>/\s*)?(?:think|analysis|reasoning)\b[^>]*>",
    re.IGNORECASE,
)
_INTERNAL_LABEL_RE = re.compile(
    r"^\s*(?:analysis|reasoning|chain[- ]of[- ]thought|"
    r"\u601d\u8003\u8fc7\u7a0b|\u63a8\u7406\u8fc7\u7a0b)\s*[:\uff1a]",
    re.IGNORECASE,
)
_TOOL_FIELD_RE = re.compile(
    r"[\"']?\b(?:tool(?:[_ -]?(?:call|result|name|input|output))?|"
    r"function(?:[_ -]?(?:call|name))?|arguments?|args|parameters?|params|"
    r"execution|trace|step[_ -]?id)\b[\"']?\s*[:=]",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:\b(?:sk|pk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b)",
    re.IGNORECASE,
)
# Bare ``token`` and ``JWT`` are common NLP/security lesson vocabulary.  Reject
# them only when a value is assigned, while known provider/JWT value formats
# remain blocked regardless of the surrounding wording.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|session[-_ ]?id|"
    r"auth(?:entication)?[-_ ]?token|token|jwt)\b\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# A false negative here would turn sensitive/internal material into durable
# model context.  The intentionally conservative pattern is preferable to
# retaining a harmless sentence that merely mentions one of these terms.
_FORBIDDEN_MEMORY_RE = re.compile(
    r"(?:"
    r"\b(?:password|passwd|passphrase|secret|credential|api[-_ ]?key|"
    r"access[-_ ]?token|refresh[-_ ]?token|session[-_ ]?id|bearer|"
    r"authorization|csrf|cookie|private[-_ ]?key|client[-_ ]?secret)\b|"
    r"\b(?:chain[-_ ]?of[-_ ]?thought|thought[-_ ]?process|system[-_ ]?prompt|"
    r"developer[-_ ]?message|tool[-_ ]?(?:call|result|arguments?)|"
    r"function[-_ ]?call|traceback|stack[-_ ]?trace)\b|"
    r"\u5bc6\u7801|\u5bc6\u94a5|\u4ee4\u724c|\u79c1\u94a5|\u6388\u6743\u5934|"
    r"\u51ed\u8bc1|\u8bbf\u95ee\u4ee4\u724c|\u4f1a\u8bdd\u6807\u8bc6|"
    r"\u63a8\u7406\u8fc7\u7a0b|\u601d\u7ef4\u94fe|\u7cfb\u7edf\u63d0\u793a|"
    r"\u5de5\u5177\u8c03\u7528|\u5de5\u5177\u53c2\u6570|\u5de5\u5177\u7ed3\u679c|"
    r"\u5185\u90e8\u6307\u4ee4|\u6267\u884c\u8f68\u8ff9"
    r")",
    re.IGNORECASE,
)
_PREFERENCE_RE = re.compile(
    r"(?:\b(?:prefer|like|want|need)\b|"
    r"\u6211\u559c\u6b22|\u6211\u5e0c\u671b|\u6211\u504f\u597d|\u8bf7\u7528|"
    r"\u8bf7\u7ed9\u6211)",
    re.IGNORECASE,
)
_STYLE_PREFERENCE_RE = re.compile(
    r"(?:\b(?:brief|concise|short|detailed|step[- ]by[- ]step|format|style)\b|"
    r"\u7b80\u6d01|\u7b80\u77ed|\u8be6\u7ec6|\u5206\u6b65|\u683c\u5f0f|\u98ce\u683c)",
    re.IGNORECASE,
)
_LANGUAGE_PREFERENCE_RE = re.compile(
    r"(?:\b(?:english|chinese|bilingual|language)\b|"
    r"\u4e2d\u6587|\u82f1\u6587|\u53cc\u8bed|\u8bed\u8a00)",
    re.IGNORECASE,
)


def _without_hidden_reasoning(content: str) -> str:
    """Remove model-only reasoning while retaining a visible final answer.

    A malformed opening marker is treated as the start of hidden content through
    the end of the message.  This fails closed instead of risking an incomplete
    streaming response leaking hidden reasoning into a durable memory record.
    """

    visible: list[str] = []
    cursor = 0
    hidden_depth = 0
    for marker in _HIDDEN_TAG_RE.finditer(content):
        if hidden_depth == 0:
            visible.append(content[cursor : marker.start()])
        if marker.group("closing"):
            hidden_depth = max(0, hidden_depth - 1)
        else:
            hidden_depth += 1
        cursor = marker.end()
    if hidden_depth == 0:
        visible.append(content[cursor:])
    return "".join(visible)


def _is_structured_execution_payload(text: str) -> bool:
    """Recognize tool payloads and standalone JSON before they enter memory."""

    if _TOOL_FIELD_RE.search(text):
        return True
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        if candidate.casefold().startswith(("json", "jsonc")):
            candidate = candidate[4:].lstrip()
    if not candidate.startswith(("{", "[")):
        return False
    try:
        decoded = json.loads(candidate)
    except (TypeError, ValueError):
        return False
    # A standalone JSON document is indistinguishable from a provider/tool
    # execution payload at this boundary.  Excluding it is safer than storing
    # arguments or results merely because their field names changed upstream.
    return isinstance(decoded, (dict, list))


def _safe_memory_text(content: str, *, max_chars: int | None = None) -> str | None:
    """Return only visible, non-sensitive text that may enter model context."""

    if not isinstance(content, str):
        return None
    text = " ".join(_without_hidden_reasoning(content).strip().split())
    if (
        len(text) < 3
        or _FORBIDDEN_MEMORY_RE.search(text)
        or _INTERNAL_LABEL_RE.search(text)
        or _SECRET_VALUE_RE.search(text)
        or _SECRET_ASSIGNMENT_RE.search(text)
        or _is_structured_execution_payload(text)
    ):
        return None
    # L1-L3 callers apply their own budgets.  L0 callers pass no limit so the
    # historical record remains complete after only the privacy transformation.
    return text[:max_chars].rstrip() if max_chars is not None else text


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
    """Index one persisted L0 chat message without blocking the chat on failure."""

    if not get_config().conversation_memory_enabled or role not in _L0_ROLES:
        return
    text = _safe_memory_text(content)
    if text is None:
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
                uuid.uuid4().hex,
                user_id,
                conversation_id,
                message_id,
                run_id,
                role,
                text,
                embeddings[0],
                model,
                created_at,
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
    """Index older persisted L0 turns once after the feature is upgraded."""

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


def _normalized_content(content: str) -> str:
    """Normalize the dedupe key without changing the text that reaches a model."""

    return " ".join(content.casefold().split())


def _atoms(content: str) -> list[str]:
    """Extract a few sentence-sized L1 candidates from one safe source message."""

    config = get_config()
    safe_source = _safe_memory_text(content, max_chars=config.private_memory_atom_char_limit * 4)
    if safe_source is None:
        return []
    selected: list[str] = []
    seen: set[str] = set()
    candidates = _ATOM_SPLIT_RE.split(safe_source) or [safe_source]
    for candidate in candidates:
        atom = _safe_memory_text(candidate, max_chars=config.private_memory_atom_char_limit)
        if atom is None:
            continue
        normalized = _normalized_content(atom)
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(atom)
        if len(selected) >= config.private_memory_atoms_per_message:
            break
    return selected


def _stable_key(prefix: str, content: str) -> str:
    """Keep deterministic keys short so identical facts can dedupe across chats."""

    digest = hashlib.sha256(_normalized_content(content).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _classify_l1(role: str, atom: str) -> tuple[str, str]:
    """Classify only response preferences for supersession; facts stay additive."""

    if role == "user" and _PREFERENCE_RE.search(atom):
        if _STYLE_PREFERENCE_RE.search(atom):
            return "preference", "preference:response_style"
        if _LANGUAGE_PREFERENCE_RE.search(atom):
            return "preference", "preference:language"
        return "preference", "preference:general"
    return "fact", _stable_key("fact", atom)


def _source_ids_belong_to_user(
    db: sqlite3.Connection, *, user_id: str, source_message_ids: Iterable[str]
) -> list[str]:
    """Verify provenance before writing, preventing caller-supplied cross-user links."""

    source_ids = list(dict.fromkeys(source_message_ids))
    if not source_ids:
        return []
    placeholders = ", ".join("?" for _ in source_ids)
    rows = db.execute(
        f"""
        SELECT m.id
        FROM messages AS m
        JOIN conversations AS c ON c.id = m.conversation_id
        WHERE m.id IN ({placeholders}) AND c.user_id = ?
        """,
        (*source_ids, user_id),
    ).fetchall()
    found = {row["id"] for row in rows}
    return source_ids if len(found) == len(source_ids) else []


def _find_active_duplicate(
    db: sqlite3.Connection, *, user_id: str, layer: str, normalized_content: str
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT id FROM private_memory_items
        WHERE user_id = ? AND layer = ? AND normalized_content = ? AND status = 'active'
        LIMIT 1
        """,
        (user_id, layer, normalized_content),
    ).fetchone()


def _find_active_key(
    db: sqlite3.Connection, *, user_id: str, layer: str, memory_key: str
) -> sqlite3.Row | None:
    """Return the newest active preference so delayed workers cannot rewind it."""

    return db.execute(
        """
        SELECT id, created_at FROM private_memory_items
        WHERE user_id = ? AND layer = ? AND memory_key = ? AND status = 'active'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (user_id, layer, memory_key),
    ).fetchone()


def _link_sources(
    db: sqlite3.Connection, *, memory_id: str, source_message_ids: Iterable[str]
) -> None:
    """Make dedupe idempotent while retaining every proven source occurrence."""

    db.executemany(
        """
        INSERT OR IGNORE INTO private_memory_sources (memory_id, message_id)
        VALUES (?, ?)
        """,
        [(memory_id, source_id) for source_id in source_message_ids],
    )


def _store_memory_item(
    db: sqlite3.Connection,
    *,
    user_id: str,
    layer: str,
    kind: str,
    memory_key: str,
    content: str,
    source_message_ids: Iterable[str],
    origin_conversation_id: str,
    origin_run_id: str | None,
    created_at: str,
) -> bool:
    """Persist one safe item, deduping exact text and superseding current preferences."""

    config = get_config()
    # Keep each stored item independently eligible for its configured context
    # budget; otherwise a single oversized item could be skipped forever.
    safe_content = _safe_memory_text(
        content,
        max_chars=min(
            config.private_memory_atom_char_limit,
            config.private_memory_context_char_limit,
        ),
    )
    sources = _source_ids_belong_to_user(
        db, user_id=user_id, source_message_ids=source_message_ids
    )
    if safe_content is None or not sources:
        return False
    normalized = _normalized_content(safe_content)
    duplicate = _find_active_duplicate(
        db, user_id=user_id, layer=layer, normalized_content=normalized
    )
    if duplicate is not None:
        _link_sources(db, memory_id=duplicate["id"], source_message_ids=sources)
        db.execute(
            "UPDATE private_memory_items SET updated_at = ? WHERE id = ?",
            (created_at, duplicate["id"]),
        )
        db.commit()
        return False

    if kind in {"preference", "profile"}:
        active = _find_active_key(
            db, user_id=user_id, layer=layer, memory_key=memory_key
        )
        if active is not None and active["created_at"] >= created_at:
            # A delayed background worker must not resurrect a preference from
            # an older conversation merely because it finished indexing later.
            return False

    embeddings, embedding_model = embed_chunks(db, [safe_content])
    if len(embeddings) != 1:
        raise ValueError("memory embedding did not return one vector")
    memory_id = uuid.uuid4().hex
    try:
        db.execute(
            """
            INSERT INTO private_memory_items
              (id, user_id, layer, kind, memory_key, content, normalized_content,
               origin_conversation_id, origin_run_id, status, superseded_by_id,
               embedding, embedding_model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?)
            """,
            (
                memory_id,
                user_id,
                layer,
                kind,
                memory_key,
                safe_content,
                normalized,
                origin_conversation_id,
                origin_run_id,
                embeddings[0],
                embedding_model,
                created_at,
                created_at,
            ),
        )
    except sqlite3.IntegrityError:
        # Concurrent background captures can race on the partial unique index.
        # Reusing the winner is safe and avoids duplicate private context.
        duplicate = _find_active_duplicate(
            db, user_id=user_id, layer=layer, normalized_content=normalized
        )
        if duplicate is None:
            raise
        _link_sources(db, memory_id=duplicate["id"], source_message_ids=sources)
        db.commit()
        return False

    _link_sources(db, memory_id=memory_id, source_message_ids=sources)
    if kind in {"preference", "profile"}:
        active = _find_active_key(
            db, user_id=user_id, layer=layer, memory_key=memory_key
        )
        if active is not None and active["id"] != memory_id:
            # SQLite serializes writes, but another worker can still finish in
            # the gap before this insert.  Keep the source record for audit and
            # mark this stale candidate inactive instead of allowing two truths.
            db.execute(
                """
                UPDATE private_memory_items
                SET status = 'superseded', superseded_by_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (active["id"], created_at, memory_id),
            )
            db.commit()
            return False
        # Latest explicit preference wins.  Facts and scenario summaries are
        # additive because a newer one does not prove an older one is obsolete.
        db.execute(
            """
            UPDATE private_memory_items
            SET status = 'superseded', superseded_by_id = ?, updated_at = ?
            WHERE user_id = ? AND layer = ? AND memory_key = ?
              AND status = 'active' AND id != ? AND created_at < ?
            """,
            (memory_id, created_at, user_id, layer, memory_key, memory_id, created_at),
        )
    db.commit()
    return True


def _scenario_summary(
    rows: Iterable[sqlite3.Row], atoms_by_message: dict[str, list[str]]
) -> tuple[str, list[str]] | None:
    """Make a deterministic L2 summary without invoking a second chat model."""

    user_atom: tuple[str, str] | None = None
    assistant_atom: tuple[str, str] | None = None
    for row in rows:
        atoms = atoms_by_message.get(row["id"], [])
        if not atoms:
            continue
        if row["role"] == "user" and user_atom is None:
            user_atom = (row["id"], atoms[0])
        elif row["role"] == "assistant" and assistant_atom is None:
            assistant_atom = (row["id"], atoms[0])
    parts: list[str] = []
    sources: list[str] = []
    if user_atom is not None:
        parts.append(f"Learner context: {user_atom[1]}")
        sources.append(user_atom[0])
    if assistant_atom is not None:
        parts.append(f"Assistant outcome: {assistant_atom[1]}")
        sources.append(assistant_atom[0])
    if not parts:
        return None
    return " | ".join(parts), sources


def capture_completed_response(
    db: sqlite3.Connection,
    *,
    user_id: str,
    conversation_id: str,
    run_id: str | None,
) -> int:
    """Derive L1-L3 after an assistant reply; all errors remain best-effort."""

    if not get_config().private_memory_enabled or not run_id:
        return 0
    try:
        rows = db.execute(
            """
            SELECT m.id, m.role, m.content, m.created_at
            FROM messages AS m
            JOIN conversations AS c ON c.id = m.conversation_id
            WHERE m.conversation_id = ? AND m.run_id = ? AND c.user_id = ?
              AND m.role IN ('user', 'assistant')
            ORDER BY m.created_at ASC, m.rowid ASC
            """,
            (conversation_id, run_id, user_id),
        ).fetchall()
        if not any(row["role"] == "assistant" for row in rows):
            return 0

        created = 0
        atoms_by_message: dict[str, list[str]] = {}
        for row in rows:
            atoms = _atoms(row["content"])
            atoms_by_message[row["id"]] = atoms
            for atom in atoms:
                kind, memory_key = _classify_l1(row["role"], atom)
                created += int(
                    _store_memory_item(
                        db,
                        user_id=user_id,
                        layer="l1",
                        kind=kind,
                        memory_key=memory_key,
                        content=atom,
                        source_message_ids=[row["id"]],
                        origin_conversation_id=conversation_id,
                        origin_run_id=run_id,
                        created_at=row["created_at"],
                    )
                )
                if kind == "preference":
                    # L3 is intentionally narrow: it exposes only the latest
                    # response preference rather than constructing a broad user
                    # profile from opaque model inference.
                    profile_key = "profile:" + memory_key.partition(":")[2]
                    created += int(
                        _store_memory_item(
                            db,
                            user_id=user_id,
                            layer="l3",
                            kind="profile",
                            memory_key=profile_key,
                            content=f"Current learner preference: {atom}",
                            source_message_ids=[row["id"]],
                            origin_conversation_id=conversation_id,
                            origin_run_id=run_id,
                            created_at=row["created_at"],
                        )
                    )

        summary = _scenario_summary(rows, atoms_by_message)
        if summary is not None:
            content, source_ids = summary
            created += int(
                _store_memory_item(
                    db,
                    user_id=user_id,
                    layer="l2",
                    kind="scenario",
                    memory_key=_stable_key("scenario", content),
                    content=content,
                    source_message_ids=source_ids,
                    origin_conversation_id=conversation_id,
                    origin_run_id=run_id,
                    created_at=rows[-1]["created_at"],
                )
            )
        return created
    except Exception:
        # This function runs in a separate connection after the response is
        # durable.  Roll back only derivative writes and never retry in-band.
        db.rollback()
        logger.warning("private layered memory capture failed", exc_info=True)
        return 0


def _capture_worker(
    database_path: str,
    user_id: str,
    conversation_id: str,
    run_id: str,
) -> None:
    """Open an isolated SQLite connection so extraction cannot hold the run's DB."""

    db: sqlite3.Connection | None = None
    try:
        db = connect(database_path)
        capture_completed_response(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
        )
    except Exception:
        logger.warning("private layered memory worker failed", exc_info=True)
    finally:
        if db is not None:
            db.close()


def schedule_layered_capture(
    *, database_path: str, user_id: str, conversation_id: str, run_id: str | None
) -> None:
    """Queue post-response extraction without delaying a successful assistant reply."""

    if not get_config().private_memory_enabled or not run_id or database_path == ":memory:":
        return
    thread = threading.Thread(
        target=_capture_worker,
        args=(database_path, user_id, conversation_id, run_id),
        name="bhzd-private-memory",
        daemon=True,
    )
    thread.start()


def _retrieve_l0_context(
    db: sqlite3.Connection,
    *,
    user_id: str,
    conversation_id: str,
    query: str,
    exclude_run_id: str | None,
) -> list[dict[str, str]]:
    """Keep existing vector-only current-conversation recall compatible."""

    config = get_config()
    if not config.conversation_memory_enabled:
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
            # The current user message is already the live prompt.  Excluding
            # its run prevents the model from receiving it twice as history.
            sql += " AND (run_id IS NULL OR run_id != ?)"
            params.append(exclude_run_id)
        rows = db.execute(sql, params).fetchall()
        query_embedding = bytes_to_array(embed_chunks(db, [query])[0][0])
    except Exception:
        logger.warning("conversation memory retrieval failed", exc_info=True)
        return []

    scored: list[tuple[float, sqlite3.Row, str]] = []
    for row in rows:
        # Legacy rows may predate the privacy gate.  Score their stored vector
        # for compatibility, but only carry a freshly sanitized copy forward.
        safe_content = _safe_memory_text(row["content"])
        if safe_content is None:
            continue
        scored.append(
            (
                cosine_similarity(query_embedding, bytes_to_array(row["embedding"])),
                row,
                safe_content,
            )
        )
    relevant = [item for item in scored if item[0] > 0]
    relevant.sort(key=lambda item: (-item[0], item[1]["created_at"]))
    selected = relevant[:config.conversation_memory_top_k]
    selected.sort(key=lambda item: item[1]["created_at"])
    return [
        {"role": row["role"], "content": safe_content}
        for _, row, safe_content in selected
    ]


def _fts_query(text: str) -> str | None:
    """Quote individual terms so untrusted chat text cannot alter MATCH syntax."""

    tokens = list(dict.fromkeys(token.casefold() for token in _FTS_TOKEN_RE.findall(text)))
    if not tokens:
        return None
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:16])


def _layered_base_sql(exclude_run_id: str | None) -> tuple[str, list[Any]]:
    """Share owner/run filters between lexical and vector candidate queries."""

    sql = " AND m.status = 'active'"
    params: list[Any] = []
    if exclude_run_id:
        sql += " AND (m.origin_run_id IS NULL OR m.origin_run_id != ?)"
        params.append(exclude_run_id)
    return sql, params


def _retrieve_layered_context(
    db: sqlite3.Connection,
    *,
    user_id: str,
    query: str,
    exclude_run_id: str | None,
) -> list[dict[str, str]]:
    """Use FTS plus compatible vectors and merge ranks with reciprocal-rank fusion."""

    config = get_config()
    if not config.private_memory_enabled:
        return []
    suffix, run_params = _layered_base_sql(exclude_run_id)
    records: dict[str, sqlite3.Row] = {}
    safe_content_by_id: dict[str, str] = {}
    scores: dict[str, float] = {}

    lexical_query = _fts_query(query)
    if lexical_query:
        try:
            keyword_rows = db.execute(
                f"""
                SELECT m.id, m.content, m.created_at, m.embedding, m.embedding_model
                FROM private_memory_fts
                JOIN private_memory_items AS m ON m.rowid = private_memory_fts.rowid
                WHERE private_memory_fts MATCH ? AND m.user_id = ?{suffix}
                ORDER BY bm25(private_memory_fts) ASC, m.created_at DESC
                LIMIT ?
                """,
                (lexical_query, user_id, *run_params, config.private_memory_candidate_limit),
            ).fetchall()
            for rank, row in enumerate(keyword_rows, start=1):
                safe_content = _safe_memory_text(
                    row["content"],
                    max_chars=config.private_memory_context_char_limit,
                )
                if safe_content is None:
                    continue
                records[row["id"]] = row
                safe_content_by_id[row["id"]] = safe_content
                scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (_RRF_K + rank)
        except Exception:
            # FTS can be unavailable during a partial upgrade.  Vector recall
            # still provides a useful best-effort path without surfacing a chat error.
            logger.warning("private memory keyword retrieval failed", exc_info=True)

    try:
        embeddings, embedding_model = embed_chunks(db, [query])
        if len(embeddings) != 1:
            raise ValueError("memory query embedding did not return one vector")
        query_embedding = bytes_to_array(embeddings[0])
        vector_rows = db.execute(
            f"""
            SELECT m.id, m.content, m.created_at, m.embedding, m.embedding_model
            FROM private_memory_items AS m
            WHERE m.user_id = ?{suffix} AND m.embedding_model = ?
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (user_id, *run_params, embedding_model, config.private_memory_candidate_limit),
        ).fetchall()
        ranked_vectors = [
            (cosine_similarity(query_embedding, bytes_to_array(row["embedding"])), row)
            for row in vector_rows
        ]
        ranked_vectors = [item for item in ranked_vectors if item[0] > 0]
        ranked_vectors.sort(key=lambda item: (-item[0], item[1]["created_at"]))
        for rank, (_, row) in enumerate(ranked_vectors, start=1):
            safe_content = _safe_memory_text(
                row["content"],
                max_chars=config.private_memory_context_char_limit,
            )
            if safe_content is None:
                continue
            records[row["id"]] = row
            safe_content_by_id[row["id"]] = safe_content
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (_RRF_K + rank)
    except Exception:
        # A provider/index failure must degrade to lexical recall, not prevent
        # the agent from answering the current request.
        logger.warning("private memory vector retrieval failed", exc_info=True)

    ranked = sorted(
        records.values(),
        key=lambda row: (-scores[row["id"]], row["created_at"], row["id"]),
    )
    selected: list[dict[str, str]] = []
    used_chars = 0
    for row in ranked:
        # Use the sanitized snapshot, never the legacy database value.
        content = safe_content_by_id[row["id"]]
        if len(selected) >= config.private_memory_top_k:
            break
        if used_chars + len(content) > config.private_memory_context_char_limit:
            continue
        selected.append({"role": "memory", "content": content})
        used_chars += len(content)
    return selected


def retrieve_context(
    db: sqlite3.Connection,
    *,
    user_id: str,
    conversation_id: str,
    query: str,
    exclude_run_id: str | None = None,
) -> list[dict[str, str]]:
    """Return bounded same-user L0 and cross-session layered private context."""

    text = query.strip()
    if not text:
        return []
    # L0 stays first so current dialogue continuity remains predictable.  The
    # layered half is separately bounded and owner-scoped before RRF scoring.
    return _retrieve_l0_context(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        query=text,
        exclude_run_id=exclude_run_id,
    ) + _retrieve_layered_context(
        db,
        user_id=user_id,
        query=text,
        exclude_run_id=exclude_run_id,
    )


def format_context(chunks: list[dict[str, str]]) -> str:
    """Render private memory as internal context, never as a citation payload."""

    safe_lines: list[str] = []
    for chunk in chunks:
        # Keep this final boundary defensive for callers that restore old rows
        # or assemble context outside ``retrieve_context``.
        safe_content = _safe_memory_text(chunk.get("content", ""))
        if safe_content is None:
            continue
        safe_lines.append(f"{chunk.get('role', 'memory')}: {safe_content}")
    return "\n".join(safe_lines)
