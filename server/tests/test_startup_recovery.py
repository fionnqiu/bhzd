"""Startup recovery tests for strict router registration and Agent run convergence."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from _agent_helpers import insert_run, insert_user, make_db, open_db
from bhzd_py import app as app_module
from bhzd_py.agent import events as agent_events
from bhzd_py.agent.recovery import INTERRUPTED_RUN_ERROR
from bhzd_py.db import utc_now_iso
from bhzd_py.tools import task_tools


class _BrokenRouterModule:
    """A router accessor that models an import failure inside a required domain."""

    @property
    def router(self):
        raise ImportError("simulated required router failure")


def _insert_waiting_confirmation(
    db,
    user_id: str,
    *,
    expires_at: str,
) -> tuple[str, str, str]:
    """Create a durable confirmation gate without starting the background worker."""

    run_id, _ = insert_run(db, user_id, "创建一个学习任务", status="waiting_confirmation")
    tool_call_id = uuid.uuid4().hex
    confirmation_id = uuid.uuid4().hex
    now = utc_now_iso()
    plan = {
        "steps": [
            {
                "id": "s1",
                "title": "创建学习任务",
                "tool": "task.create",
                "tool_call_id": tool_call_id,
                "status": "waiting",
            }
        ]
    }
    db.execute(
        "UPDATE agent_runs SET plan_json = ? WHERE id = ?",
        (json.dumps(plan, ensure_ascii=False), run_id),
    )
    db.execute(
        """
        INSERT INTO tool_calls
          (id, run_id, tool_name, permission, status, args_json, is_write, created_at)
        VALUES (?, ?, 'task.create', 'write', 'awaiting_confirmation', '{}', 1, ?)
        """,
        (tool_call_id, run_id, now),
    )
    db.execute(
        """
        INSERT INTO pending_confirmations
          (id, run_id, user_id, tool_call_id, action_type, preview_json,
           status, expires_at, created_at)
        VALUES (?, ?, ?, ?, 'task.create', '{}', 'pending', ?, ?)
        """,
        (confirmation_id, run_id, user_id, tool_call_id, expires_at, now),
    )
    db.commit()
    return run_id, tool_call_id, confirmation_id


def test_create_app_propagates_required_router_import_errors(monkeypatch):
    """A required API domain must fail startup rather than disappear behind 404s."""

    monkeypatch.setattr(app_module, "ROUTER_MODULES", (_BrokenRouterModule(),))
    with pytest.raises(ImportError, match="simulated required router failure"):
        app_module.create_app()


def test_lifespan_fails_a_crash_left_running_run(tmp_db_path):
    """A worker from the previous process cannot resume, so its run gets one safe terminal event."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "解释命名实体识别", status="running")
    finally:
        db.close()

    # A second startup is a realistic reload path; terminal rows must not gain
    # another ``run.failed`` event after the first recovery has converged them.
    with TestClient(app_module.create_app()):
        pass
    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        run = db.execute(
            "SELECT status, error, completed_at FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"] == INTERRUPTED_RUN_ERROR
        assert run["completed_at"] is not None
        events = db.execute(
            "SELECT event_type, payload_json FROM agent_events WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        assert [event["event_type"] for event in events] == [agent_events.RUN_FAILED]
        assert json.loads(events[0]["payload_json"])["error"] == INTERRUPTED_RUN_ERROR
    finally:
        db.close()


def test_lifespan_requeues_interrupted_learning_content_once(tmp_db_path, monkeypatch):
    """A crash-left content claim is reset and re-claimed exactly once per process."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "content-recovery@test.local")
        task_id = uuid.uuid4().hex
        now = utc_now_iso()
        db.execute(
            """
            INSERT INTO learning_tasks
              (id, user_id, title, goal, cap_ids_json, source, status,
               steps_json, resources_json, counts_toward_mastery, created_by,
               created_at, updated_at, content_status, content_generated_at)
            VALUES (?, ?, 'interrupted lesson', 'recover it', '[]', 'agent',
                    'not_started', '[]', '[]', 1, ?, ?, ?, 'generating', NULL)
            """,
            (task_id, user_id, user_id, now, now),
        )
        db.commit()
    finally:
        db.close()

    scheduled: list[tuple[str, str | None]] = []

    def capture(task_id: str, *, database_path: str | None = None):
        # Keep the worker detached so this test isolates startup's durable
        # reset/claim contract from provider timing.
        scheduled.append((task_id, database_path))

    monkeypatch.setattr(task_tools, "schedule_task_content", capture)
    monkeypatch.setattr(
        app_module,
        "_start_startup_maintenance",
        lambda _config, *, resume_rag_jobs: None,
    )

    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        status = db.execute(
            "SELECT content_status FROM learning_tasks WHERE id = ?", (task_id,)
        ).fetchone()["content_status"]
        database_path = db.execute("PRAGMA database_list").fetchone()[2]
    finally:
        db.close()
    assert status == "generating"
    assert scheduled == [(task_id, database_path)]

    # Re-entering the lifespan in the same process must not enqueue a second
    # provider worker for the claim that the first startup already accepted.
    with TestClient(app_module.create_app()):
        pass
    assert scheduled == [(task_id, database_path)]


def test_lifespan_requeues_a_rag_job_interrupted_after_its_claim(tmp_db_path, monkeypatch):
    """Startup must hand an interrupted RAG claim back to the durable worker queue."""
    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db, "rag-recovery@test.local", role="teacher")
        document_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex
        now = utc_now_iso()
        db.execute(
            """
            INSERT INTO rag_documents
              (id, title, file_type, source_type, source_name, version, license_status,
               visibility, status, process_version, created_by, created_at, updated_at)
            VALUES (?, 'startup recovery', 'md', 'standard', 'test', 'v1.0', 'authorized',
                    'teacher', 'parsing', 1, ?, ?, ?)
            """,
            (document_id, user_id, now, now),
        )
        db.execute(
            """
            INSERT INTO rag_jobs
              (id, document_id, stage, status, idempotency_key, params_json, created_at, started_at)
            VALUES (?, ?, 'parse', 'running', ?, '{}', ?, ?)
            """,
            (job_id, document_id, f"{document_id}:parse:1:test", now, now),
        )
        db.commit()
    finally:
        db.close()

    scheduled: list[bool] = []
    # Isolate the lifecycle contract from background work so the assertion
    # covers durable requeueing rather than parsing a fixture file.
    monkeypatch.setattr(
        app_module,
        "_start_startup_maintenance",
        lambda _config, *, resume_rag_jobs: scheduled.append(resume_rag_jobs),
    )
    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        assert db.execute("SELECT status FROM rag_jobs WHERE id = ?", (job_id,)).fetchone()[
            "status"
        ] == "queued"
        assert scheduled == [True]
    finally:
        db.close()


def test_lifespan_preserves_an_already_persisted_failure_event(tmp_db_path):
    """The startup reconciler must retain a prior safe failure reason verbatim."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "解释命名实体识别", status="running")
        agent_events.emit(
            db, run_id, agent_events.RUN_FAILED, {"error": "模型服务暂不可用"}
        )
    finally:
        db.close()

    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        run = db.execute(
            "SELECT status, error FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"] == "模型服务暂不可用"
        event_types = [
            row["event_type"]
            for row in db.execute(
                "SELECT event_type FROM agent_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        ]
        assert event_types == [agent_events.RUN_FAILED]
    finally:
        db.close()


def test_lifespan_replays_an_already_persisted_terminal_event(tmp_db_path):
    """A crash after event persistence must not add a contradictory terminal event."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        run_id, _ = insert_run(db, user_id, "解释命名实体识别", status="running")
        agent_events.emit(db, run_id, agent_events.RUN_COMPLETED, {"summary": "已完成"})
    finally:
        db.close()

    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        run = db.execute(
            "SELECT status, completed_at FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run is not None
        assert run["status"] == "completed"
        assert run["completed_at"] is not None
        event_types = [
            row["event_type"]
            for row in db.execute(
                "SELECT event_type FROM agent_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        ]
        assert event_types == [agent_events.RUN_COMPLETED]
    finally:
        db.close()


def test_lifespan_expires_only_due_confirmation_runs(tmp_db_path):
    """Expired gates use the shared state machine while a valid preview survives restart."""

    db = make_db(tmp_db_path)
    try:
        user_id = insert_user(db)
        expired_run, expired_tool, expired_confirmation = _insert_waiting_confirmation(
            db, user_id, expires_at="2000-01-01T00:00:00+00:00"
        )
        valid_run, valid_tool, valid_confirmation = _insert_waiting_confirmation(
            db, user_id, expires_at="2999-01-01T00:00:00+00:00"
        )
    finally:
        db.close()

    with TestClient(app_module.create_app()):
        pass

    db = open_db(tmp_db_path)
    try:
        expired = db.execute(
            "SELECT status FROM agent_runs WHERE id = ?", (expired_run,)
        ).fetchone()
        assert expired is not None and expired["status"] == "completed"
        assert db.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (expired_confirmation,)
        ).fetchone()["status"] == "expired"
        assert db.execute(
            "SELECT status FROM tool_calls WHERE id = ?", (expired_tool,)
        ).fetchone()["status"] == "cancelled"
        expired_steps = json.loads(
            db.execute(
                "SELECT plan_json FROM agent_runs WHERE id = ?", (expired_run,)
            ).fetchone()["plan_json"]
        )["steps"]
        assert expired_steps[0]["status"] == "cancelled"

        valid = db.execute(
            "SELECT status FROM agent_runs WHERE id = ?", (valid_run,)
        ).fetchone()
        assert valid is not None and valid["status"] == "waiting_confirmation"
        assert db.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (valid_confirmation,)
        ).fetchone()["status"] == "pending"
        assert db.execute(
            "SELECT status FROM tool_calls WHERE id = ?", (valid_tool,)
        ).fetchone()["status"] == "awaiting_confirmation"
        event_types = [
            row["event_type"]
            for row in db.execute(
                "SELECT event_type FROM agent_events WHERE run_id = ? ORDER BY seq",
                (valid_run,),
            ).fetchall()
        ]
        assert event_types == []
    finally:
        db.close()
