"""Permission contracts for Agent-triggered RAG administration tools."""

from __future__ import annotations

import uuid

import pytest

from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.tools import registry
from bhzd_py.tools.registry import ToolContext


@pytest.fixture()
def db(tmp_db_path):
    """Use the migrated schema because tool applies write RAG and audit rows directly."""
    conn = connect(tmp_db_path)
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


def _user(db, role: str):
    user_id = uuid.uuid4().hex
    now = utc_now_iso()
    db.execute(
        "INSERT INTO users (id, email, name, role, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (user_id, f"{role}-{user_id[:8]}@test.local", role, role, now, now),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _context(db, user, args: dict | None = None) -> ToolContext:
    return ToolContext(
        db=db,
        config=None,
        user_row=user,
        run_row=None,
        conversation_row=None,
        args=args or {},
    )


@pytest.fixture()
def teacher(db):
    return _user(db, "teacher")


@pytest.fixture()
def system_admin(db):
    return _user(db, "system_admin")


_RAG_ADMIN_SPECS = tuple(
    # The registry is the production composition boundary and provides the
    # supported import order for tools that register themselves there.
    registry.get(name)
    for name in (
        "rag.create_document",
        "rag.reindex_document",
        "rag.publish_document",
        "rag.archive_document",
        "rag.save_eval_case",
    )
)


def _management_row_counts(db) -> dict[str, int]:
    """Capture all tables a denied RAG tool could otherwise mutate."""
    return {
        table: db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("rag_documents", "rag_jobs", "eval_cases", "review_records", "audit_logs")
    }


@pytest.mark.parametrize("principal_fixture", ("teacher",))
@pytest.mark.parametrize("spec", _RAG_ADMIN_SPECS, ids=lambda spec: spec.name)
def test_non_system_admin_cannot_preview_or_apply_rag_admin_tools(
    db, request, principal_fixture, spec
):
    """Agent calls bypass HTTP dependencies, so every tool path enforces the role itself."""
    principal = request.getfixturevalue(principal_fixture)
    context = _context(db, principal)
    expected = {"error": "只有系统管理员可以执行资料管理操作"}
    before = _management_row_counts(db)

    assert spec.preview is not None and spec.apply is not None
    assert spec.preview(context) == expected
    assert spec.apply(context) == expected
    assert _management_row_counts(db) == before


def test_system_admin_can_apply_rag_document_creation(db, system_admin):
    """The role guard leaves the approved Agent apply path available to system administrators."""
    create_spec = registry.get("rag.create_document")
    assert create_spec.apply is not None
    result = create_spec.apply(
        _context(
            db,
            system_admin,
            {
                "title": "管理员创建的资料",
                "source_type": "standard",
                "source_name": "测试标准库",
                "version": "v1",
                "data_types": ["text"],
            },
        )
    )

    assert result["title"] == "管理员创建的资料"
    assert result["status"] == "draft"
    row = db.execute(
        "SELECT title, status, created_by FROM rag_documents WHERE id = ?", (result["document_id"],)
    ).fetchone()
    assert row["title"] == "管理员创建的资料"
    assert row["status"] == "draft"
    assert row["created_by"] == system_admin["id"]
