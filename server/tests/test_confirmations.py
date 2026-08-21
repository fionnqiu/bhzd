"""确认门 API 测试：confirm 生效 / cancel 不落写 / 过期 410 / 重复处理 409。"""

from __future__ import annotations

import json

import pytest

from bhzd_py.agent import confirmation_state
from bhzd_py.routers import confirmations as confirmation_router
from bhzd_py.tools import registry

from _agent_helpers import (
    csrf_headers,
    install_stub_tools,
    make_auth_client,
    open_db,
    wait_run_status,
)

_GATE_INPUT = "帮我诊断标注结果"  # 带诊断附件 → 计划直达 diagnostic.save_summary 写门
_GATE_BODY = {
    "input": _GATE_INPUT,
    # 任务类意图已改为任务草稿链路（无写门）；诊断流仍走确认门，
    # 因此确认机制的 API 契约用它覆盖。
    "attachment": {"diagnostic_token": "tok-1"},
}


@pytest.fixture()
def client(tmp_db_path, monkeypatch):
    install_stub_tools(monkeypatch)
    client, user_id = make_auth_client(tmp_db_path)
    client.test_user_id = user_id  # type: ignore[attr-defined]
    yield client
    client.close()


def _open_gate(client, tmp_db_path) -> tuple[str, str]:
    """启动一轮直达写确认门的运行，返回 (run_id, confirmation_id)。"""
    response = client.post("/api/runs", json=_GATE_BODY,
                           headers=csrf_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    wait_run_status(tmp_db_path, run_id, ("waiting_confirmation",))
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["run"]["status"] == "waiting_confirmation"
    assert len(detail["confirmations"]) == 1
    confirmation = detail["confirmations"][0]
    assert confirmation["action_type"] == "diagnostic.save_summary"
    assert confirmation["preview"]["action"] == "diagnostic.save_summary"  # 预览载荷
    return run_id, confirmation["id"]


def test_confirm_applies_and_completes(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    response = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["result"]["applied"] == "diagnostic.save_summary"  # stub apply 真被执行

    # 续跑完成整轮
    wait_run_status(tmp_db_path, run_id, ("completed",))

    conn = open_db(tmp_db_path)
    try:
        confirmation = conn.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (confirmation_id,)
        ).fetchone()
        assert confirmation["status"] == "confirmed"
        tool_call = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        assert tool_call["status"] == "completed"
        events = [
            r["event_type"]
            for r in conn.execute(
                "SELECT event_type FROM agent_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        ]
        assert "tool.call.completed" in events
        assert events[-1] == "run.completed"
    finally:
        conn.close()


def test_cancel_applies_nothing(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    response = client.post(
        f"/api/confirmations/{confirmation_id}/cancel", headers=csrf_headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    conn = open_db(tmp_db_path)
    try:
        run = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["status"] == "completed"
        # 取消不改变学习状态：没有任何学习任务落库
        task_count = conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"]
        assert task_count == 0
        tool_call = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        assert tool_call["status"] == "cancelled"
        plan = conn.execute(
            "SELECT plan_json FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        steps = json.loads(plan["plan_json"])["steps"]
        assert next(step for step in steps if step["tool"] == "diagnostic.save_summary")["status"] == "cancelled"
        notice = conn.execute(
            "SELECT content FROM messages WHERE run_id = ? AND role = 'assistant'",
            (run_id,),
        ).fetchone()
        assert notice["content"] == "已取消，未做任何更改。"
    finally:
        conn.close()


def test_expired_confirmation_returns_410(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    # 直接把过期时间拨到过去，模拟 PRD-06 §6.4 过期场景
    conn = open_db(tmp_db_path)
    try:
        conn.execute(
            "UPDATE pending_confirmations SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (confirmation_id,),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "CONFIRMATION_EXPIRED"

    conn = open_db(tmp_db_path)
    try:
        row = conn.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (confirmation_id,)
        ).fetchone()
        assert row["status"] == "expired"
        tool = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        assert tool["status"] == "cancelled"
        run = conn.execute(
            "SELECT status, plan_json FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["status"] == "completed"
        steps = json.loads(run["plan_json"])["steps"]
        assert next(step for step in steps if step["tool"] == "diagnostic.save_summary")["status"] == "cancelled"
        terminal_events = conn.execute(
            """
            SELECT event_type, payload_json FROM agent_events
            WHERE run_id = ?
              AND event_type IN ('tool.call.completed', 'plan.updated', 'run.completed')
            ORDER BY seq
            """,
            (run_id,),
        ).fetchall()
        assert [event["event_type"] for event in terminal_events[-3:]] == [
            "tool.call.completed",
            "plan.updated",
            "run.completed",
        ]
        assert sum(event["event_type"] == "run.completed" for event in terminal_events) == 1
        assert json.loads(terminal_events[-3]["payload_json"])["result"]["reason"] == "confirmation_expired"
    finally:
        conn.close()


def test_expire_endpoint_requires_csrf_and_is_idempotent(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    # Expiry is a state-changing operation even though it performs no write tool.
    denied = client.post(f"/api/confirmations/{confirmation_id}/expire")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

    early = client.post(
        f"/api/confirmations/{confirmation_id}/expire", headers=csrf_headers()
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "CONFIRMATION_NOT_EXPIRED"

    conn = open_db(tmp_db_path)
    try:
        conn.execute(
            "UPDATE pending_confirmations SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (confirmation_id,),
        )
        conn.commit()
    finally:
        conn.close()

    first = client.post(
        f"/api/confirmations/{confirmation_id}/expire", headers=csrf_headers()
    )
    second = client.post(
        f"/api/confirmations/{confirmation_id}/expire", headers=csrf_headers()
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "expired"

    conn = open_db(tmp_db_path)
    try:
        events = conn.execute(
            "SELECT event_type FROM agent_events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        # The repeat reads the durable expiry result; it must not emit a second
        # terminal sequence that would make an SSE client finalize twice.
        assert sum(event["event_type"] == "run.completed" for event in events) == 1
        assert sum(event["event_type"] == "tool.call.completed" for event in events) >= 2
        assert events[-1]["event_type"] == "run.completed"
    finally:
        conn.close()


def test_claimed_confirmation_rejects_double_click_and_cancel(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    # ``running`` is the durable claim written by the first tab immediately
    # before apply().  Simulating that window verifies both losing requests
    # receive 409 without executing or cancelling the claimed write.
    conn = open_db(tmp_db_path)
    try:
        conn.execute(
            "UPDATE tool_calls SET status = 'running' WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()

    confirm = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    cancel = client.post(
        f"/api/confirmations/{confirmation_id}/cancel", headers=csrf_headers()
    )
    assert confirm.status_code == cancel.status_code == 409
    assert confirm.json()["error"]["code"] == "CONFIRMATION_IN_PROGRESS"
    assert cancel.json()["error"]["code"] == "CONFIRMATION_IN_PROGRESS"

    conn = open_db(tmp_db_path)
    try:
        tool = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        confirmation = conn.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (confirmation_id,)
        ).fetchone()
        assert tool["status"] == "running"
        assert confirmation["status"] == "pending"
        assert conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"] == 0
    finally:
        conn.close()


def test_double_confirm_409_and_owner_check(client, tmp_db_path):
    run_id, confirmation_id = _open_gate(client, tmp_db_path)
    assert client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    ).status_code == 200
    wait_run_status(tmp_db_path, run_id, ("completed",))
    # 重复确认 → 409
    second = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    assert second.status_code == 409

    # 他人确认单 → 404
    other_run, other_confirmation = _open_gate(client, tmp_db_path)
    other, _ = make_auth_client(tmp_db_path, email="other@test.local")
    try:
        assert other.post(
            f"/api/confirmations/{other_confirmation}/confirm",
            headers=csrf_headers(),
        ).status_code == 404
    finally:
        other.close()


def test_confirm_cannot_cross_deadline_between_precheck_and_claim(
    client, tmp_db_path, monkeypatch
):
    """The claim predicate, not the earlier route read, decides the deadline."""

    run_id, confirmation_id = _open_gate(client, tmp_db_path)
    original_claim = confirmation_router.claim_confirmation_tool

    def expire_before_claim(db, row):
        # This models the narrow interval after the route's first time check.
        conn = open_db(tmp_db_path)
        try:
            conn.execute(
                "UPDATE pending_confirmations SET expires_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", confirmation_id),
            )
            conn.commit()
        finally:
            conn.close()
        return original_claim(db, row)

    monkeypatch.setattr(confirmation_router, "claim_confirmation_tool", expire_before_claim)
    response = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "CONFIRMATION_EXPIRED"

    conn = open_db(tmp_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM learning_tasks").fetchone()["c"] == 0
        tool = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        assert tool["status"] == "cancelled"
    finally:
        conn.close()


def test_cancel_cannot_cross_deadline_between_precheck_and_transition(
    client, tmp_db_path, monkeypatch
):
    """Cancellation shares the confirmation claim's atomic deadline boundary."""

    run_id, confirmation_id = _open_gate(client, tmp_db_path)
    original_cancel = confirmation_router.cancel_pending_confirmation

    def expire_before_cancel(db, row, notice):
        conn = open_db(tmp_db_path)
        try:
            conn.execute(
                "UPDATE pending_confirmations SET expires_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", confirmation_id),
            )
            conn.commit()
        finally:
            conn.close()
        return original_cancel(db, row, notice)

    monkeypatch.setattr(
        confirmation_router, "cancel_pending_confirmation", expire_before_cancel
    )
    response = client.post(
        f"/api/confirmations/{confirmation_id}/cancel", headers=csrf_headers()
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "CONFIRMATION_EXPIRED"

    conn = open_db(tmp_db_path)
    try:
        run = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["status"] == "completed"
        tool = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_name = 'diagnostic.save_summary'",
            (run_id,),
        ).fetchone()
        assert tool["status"] == "cancelled"
    finally:
        conn.close()


def test_apply_failure_resolves_plan_gate_and_terminal_events(
    client, tmp_db_path, monkeypatch
):
    """A failed write must not leave either the plan or confirmation card waiting."""

    run_id, confirmation_id = _open_gate(client, tmp_db_path)

    def fail_apply(_ctx):
        raise RuntimeError("test-only apply failure")

    monkeypatch.setattr(registry.TOOLS["diagnostic.save_summary"], "apply", fail_apply)
    response = client.post(
        f"/api/confirmations/{confirmation_id}/confirm", headers=csrf_headers()
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"

    conn = open_db(tmp_db_path)
    try:
        confirmation = conn.execute(
            "SELECT status FROM pending_confirmations WHERE id = ?", (confirmation_id,)
        ).fetchone()
        assert confirmation["status"] == "cancelled"
        run = conn.execute(
            "SELECT status, plan_json FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["status"] == "failed"
        steps = json.loads(run["plan_json"])["steps"]
        assert next(step for step in steps if step["tool"] == "diagnostic.save_summary")["status"] == "failed"
        terminal = conn.execute(
            """
            SELECT event_type FROM agent_events
            WHERE run_id = ?
              AND event_type IN ('tool.call.completed', 'plan.updated', 'run.failed')
            ORDER BY seq
            """,
            (run_id,),
        ).fetchall()
        assert [event["event_type"] for event in terminal[-3:]] == [
            "tool.call.completed",
            "plan.updated",
            "run.failed",
        ]
    finally:
        conn.close()


def test_expiry_commits_terminal_events_with_terminal_state(
    client, tmp_db_path, monkeypatch
):
    """A concurrent SSE reader must see waiting state until the full sequence exists."""

    run_id, confirmation_id = _open_gate(client, tmp_db_path)
    db = open_db(tmp_db_path)
    try:
        db.execute(
            "UPDATE pending_confirmations SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", confirmation_id),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM pending_confirmations WHERE id = ?", (confirmation_id,)
        ).fetchone()
        assert row is not None

        original_emit = confirmation_state.events.emit
        observed: list[tuple[str, bool, str]] = []

        def observe_emit(local_db, event_run_id, event_type, payload, *, commit=True):
            reader = open_db(tmp_db_path)
            try:
                visible = reader.execute(
                    "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                assert visible is not None
                observed.append((event_type, commit, visible["status"]))
            finally:
                reader.close()
            return original_emit(
                local_db, event_run_id, event_type, payload, commit=commit
            )

        monkeypatch.setattr(confirmation_state.events, "emit", observe_emit)
        assert confirmation_state.expire_pending_confirmation(db, row) is True
    finally:
        db.close()

    assert [event_type for event_type, _, _ in observed] == [
        "tool.call.completed",
        "plan.updated",
        "run.completed",
    ]
    assert all(commit is False for _, commit, _ in observed)
    assert all(status == "waiting_confirmation" for _, _, status in observed)
