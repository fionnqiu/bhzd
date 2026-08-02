"""埋点端点测试（蓝图 §6.7/§8）：白名单接受/静默丢弃。"""

from __future__ import annotations

import json
import secrets
from base64 import b64encode

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect
from bhzd_py.errors import register_error_handlers
from bhzd_py.routers import auth, events

PASSWORD = "Passw0rd1"


@pytest.fixture()
def client(tmp_db_path, monkeypatch):
    monkeypatch.setenv("BHZD_SMTP_HOST", "")
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    reset_config_cache()
    conn = connect(get_config().resolved_database_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    # 最小应用：只挂 auth + events，与并行开发的兄弟 router 解耦（同 test_auth）
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(events.router)
    with TestClient(app) as test_client:
        yield test_client
    reset_config_cache()


def _password_envelope(client: TestClient, password: str) -> dict[str, str]:
    """Build the public-key envelope so event tests use the real auth boundary."""
    key_response = client.get("/api/auth/password-key")
    assert key_response.status_code == 200
    key = key_response.json()
    public_key = serialization.load_pem_public_key(key["publicKeyPem"].encode("ascii"))
    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    ciphertext = AESGCM(aes_key).encrypt(iv, password.encode("utf-8"), None)
    return {
        "keyId": key["keyId"],
        "encryptedKey": b64encode(encrypted_key).decode("ascii"),
        "iv": b64encode(iv).decode("ascii"),
        "ciphertext": b64encode(ciphertext).decode("ascii"),
    }


def _login_user(client: TestClient) -> str:
    """注册并登录一个学生，返回其用户 id。"""
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "events@example.com",
            "name": "埋点用户",
            "passwordEnvelope": _password_envelope(client, PASSWORD),
        },
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user"]["id"]
    resp = client.post(
        "/api/auth/login",
        json={"email": "events@example.com", "passwordEnvelope": _password_envelope(client, PASSWORD)},
    )
    assert resp.status_code == 200, resp.text
    return user_id


def test_events_whitelist_accept_and_drop(client):
    user_id = _login_user(client)
    resp = client.post(
        "/api/events",
        json={
            "events": [
                {"name": "preset_clicked", "props": {"preset_id": "PRESET-001"}},
                {"name": "rag_query_submitted", "props": {"question_len": 12}},
                {"name": "not_in_whitelist", "props": {}},  # 未知事件名：静默丢弃
                {"name": "drop_table_users", "props": {}},
            ]
        },
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 2}

    conn = connect(get_config().resolved_database_path)
    try:
        rows = conn.execute(
            "SELECT user_id, event_name, props_json FROM analytics_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert [row["event_name"] for row in rows] == ["preset_clicked", "rag_query_submitted"]
    assert all(row["user_id"] == user_id for row in rows)
    assert json.loads(rows[0]["props_json"])["preset_id"] == "PRESET-001"


def test_events_requires_login(client):
    resp = client.post("/api/events", json={"events": [{"name": "preset_clicked"}]})
    assert resp.status_code == 401


def test_events_empty_batch(client):
    _login_user(client)
    resp = client.post("/api/events", json={"events": []})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}
