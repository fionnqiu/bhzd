"""系统管理域测试（蓝图 §6.6）：provider 管理、RAG 参数、用户权限、审计、指标。

夹具策略（为什么）：system_admin 直接 INSERT 进库（argon2 哈希），不依赖
seed 链路（seed 会牵到并行开发中的 rag/ 模块）；加密密钥每测试随机生成，
加解密都在同进程内完成，互不影响。
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import uuid
from base64 import b64encode

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bhzd_py.agent import providers
from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.errors import register_error_handlers
from bhzd_py.routers import admin, auth
from bhzd_py.security import hash_password

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "AdminPass123"
STUDENT_EMAIL = "student@example.com"
STUDENT_PASSWORD = "Student123"


def _build_app() -> FastAPI:
    """只挂 auth + admin 的最小应用（理由见 test_auth._build_app：与并行开发的
    兄弟 router 解耦，Wave4 再测全量 create_app 装配）。"""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(admin.router)
    return app


def _password_envelope(client: TestClient, password: str) -> dict[str, str]:
    """Use the public endpoint so admin callers exercise the browser wire contract."""
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


def _login(client: TestClient, email: str, password: str):
    """Keep every admin-domain login aligned with the plaintext-free auth API."""
    return client.post(
        "/api/auth/login",
        json={"email": email, "passwordEnvelope": _password_envelope(client, password)},
    )


def _db():
    return connect(get_config().resolved_database_path)


def _insert_user(email: str, name: str, role: str, password: str) -> str:
    conn = _db()
    try:
        user_id = uuid.uuid4().hex
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO users (id, email, name, role, status, email_verified_at,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (user_id, email, name, role, now, now, now),
        )
        conn.execute(
            "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at)"
            " VALUES (?, ?, 'argon2id', ?)",
            (user_id, hash_password(password), now),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


@pytest.fixture()
def app_and_admin(tmp_db_path, monkeypatch):
    """全新应用 + 临时库 + 已登录的管理员客户端（含 CSRF 头）。"""
    monkeypatch.setenv("BHZD_SMTP_HOST", "")
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    reset_config_cache()
    conn = _db()
    try:
        apply_migrations(conn)
        conn.execute(
            "INSERT OR IGNORE INTO rag_settings (id, updated_at) VALUES (1, ?)",
            (utc_now_iso(),),
        )
        conn.commit()
    finally:
        conn.close()
    admin_id = _insert_user(ADMIN_EMAIL, "系统管理员", "system_admin", ADMIN_PASSWORD)
    app = _build_app()
    with TestClient(app) as client:
        resp = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        assert resp.status_code == 200, resp.text
        # 系统管理员登录必须同时拿到两种 cookie（蓝图 §6.1 矩阵）
        assert "bhzd_admin_session" in resp.cookies
        assert "bhzd_session" in resp.cookies
        client.headers["x-csrf-token"] = resp.json()["csrf_token"]
        yield app, client, admin_id
    reset_config_cache()


@pytest.fixture()
def admin_client(app_and_admin):
    return app_and_admin[1]


def _create_provider(client: TestClient, name: str = "主模型", **overrides):
    payload = {
        "name": name,
        "protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "model": "demo-model",
        "api_key": "sk-test-key-123",
    }
    payload.update(overrides)
    return client.post("/api/admin/providers", json=payload)


# ---------------------------------------------------------------- provider 管理

def test_provider_create_rejects_forbidden_base_url(admin_client):
    # NF9：云元数据地址与 localhost 必须被拒绝
    resp = _create_provider(admin_client, base_url="http://169.254.169.254/latest")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_BASE_URL"
    resp = _create_provider(admin_client, base_url="http://localhost:8080/v1")
    assert resp.status_code == 400
    resp = _create_provider(admin_client, base_url="http://192.168.1.10:9000/v1")
    assert resp.status_code == 400


def test_transient_model_discovery_returns_models_without_persisting_key_or_audit(
    admin_client, monkeypatch
):
    """The new-provider selector may use a key once but must not save configuration state."""
    captured: dict[str, object] = {}

    async def fake_discover(protocol, base_url, api_key, extra=None):
        captured.update(
            {
                "protocol": protocol,
                "base_url": base_url,
                "api_key": api_key,
                "extra": extra,
            }
        )
        return {"supported": True, "models": [{"id": "demo-model", "label": "Demo model"}]}

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    api_key = "sk-transient-discovery-key"
    response = admin_client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "chat_completions",
            "base_url": "https://catalog.example.com/v1",
            "api_key": api_key,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "supported": True,
        "models": [{"id": "demo-model", "label": "Demo model"}],
    }
    assert captured == {
        "protocol": "chat_completions",
        "base_url": "https://catalog.example.com/v1",
        "api_key": api_key,
        "extra": None,
    }
    assert api_key not in response.text

    conn = _db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM provider_configs").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM audit_logs WHERE target_type = 'provider'").fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_transient_provider_test_uses_current_form_without_persisting_key_or_result(
    admin_client, monkeypatch
):
    """The drawer can prove an unsaved connection without creating provider state."""
    captured: dict[str, object] = {}

    async def fake_test(protocol, base_url, api_key, model, role="none", extra=None):
        captured.update(
            {
                "protocol": protocol,
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "role": role,
                "extra": extra,
            }
        )
        return {
            "ok": True,
            "role": role,
            "latency_ms": 8,
            "model": model,
            "error": None,
            "tested_at": "2026-08-08T00:00:00+00:00",
        }

    monkeypatch.setattr(providers, "test_transient_provider", fake_test)
    api_key = "sk-transient-test-key"
    response = admin_client.post(
        "/api/admin/providers/test-connection",
        json={
            "protocol": "chat_completions",
            "base_url": "https://form.example.com/v1",
            "api_key": api_key,
            "model": "form-model",
            "role": "none",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert captured == {
        "protocol": "chat_completions",
        "base_url": "https://form.example.com/v1",
        "api_key": api_key,
        "model": "form-model",
        "role": "none",
        "extra": None,
    }
    assert api_key not in response.text
    conn = _db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM provider_configs").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM audit_logs WHERE target_type = 'provider'").fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_transient_provider_test_rejects_unsafe_form_before_adapter(admin_client, monkeypatch):
    called = False

    async def fake_test(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(providers, "test_transient_provider", fake_test)
    response = admin_client.post(
        "/api/admin/providers/test-connection",
        json={
            "protocol": "chat_completions",
            "base_url": "http://127.0.0.1:9000/v1",
            "api_key": "sk-form-key",
            "model": "form-model",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BASE_URL"
    assert called is False


@pytest.mark.parametrize(
    "base_url",
    [
        "http://catalog.example.com/v1",
        "https://username:password@catalog.example.com/v1",
        "https://@catalog.example.com/v1",
        "https://127.0.0.1/v1",
    ],
)
def test_transient_model_discovery_rejects_unsafe_urls_before_adapter(
    admin_client, monkeypatch, base_url
):
    """Discovery is stricter than saved runtime config because it immediately sends a key."""
    called = False

    async def fake_discover(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"supported": True, "models": []}

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    response = admin_client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "chat_completions",
            "base_url": base_url,
            "api_key": "sk-discovery-key",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BASE_URL"
    assert called is False


@pytest.mark.parametrize("api_key", ["k" * 501, {"secret": "sk-object-secret"}])
def test_transient_model_discovery_rejects_an_invalid_key_without_echoing_it(
    admin_client, monkeypatch, caplog, api_key
):
    """Route validation rejects malformed keys before the shared validation logger sees them."""
    called = False

    async def fake_discover(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"supported": True, "models": []}

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    caplog.set_level(logging.INFO, logger="bhzd_py.errors")
    response = admin_client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "chat_completions",
            "base_url": "https://catalog.example.com/v1",
            "api_key": api_key,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_API_KEY"
    assert "sk-object-secret" not in response.text
    assert "sk-object-secret" not in caplog.text
    assert called is False


def test_saved_model_discovery_uses_only_the_stored_configuration(admin_client, monkeypatch):
    """Editing users cannot substitute a URL or key when discovering a saved provider's models."""
    created = _create_provider(
        admin_client,
        base_url="https://stored.example.com/v1",
        api_key="sk-stored-discovery-key",
        extra={"headers": {"X-Tenant": "school-a"}},
    ).json()
    captured: dict[str, object] = {}

    async def fake_discover(protocol, base_url, api_key, extra=None):
        captured.update(
            {
                "protocol": protocol,
                "base_url": base_url,
                "api_key": api_key,
                "extra": extra,
            }
        )
        return {"supported": True, "models": [{"id": "stored-model", "label": "Stored"}]}

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    response = admin_client.post(f"/api/admin/providers/{created['id']}/discover-models")

    assert response.status_code == 200, response.text
    assert response.json()["models"] == [{"id": "stored-model", "label": "Stored"}]
    assert captured == {
        "protocol": "chat_completions",
        "base_url": "https://stored.example.com/v1",
        "api_key": "sk-stored-discovery-key",
        "extra": {"headers": {"X-Tenant": "school-a"}},
    }
    assert "sk-stored-discovery-key" not in response.text

    response = admin_client.post(
        f"/api/admin/providers/{created['id']}/discover-models",
        json={"base_url": "https://attacker.example/v1", "api_key": "attacker-key"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_DISCOVERY_BODY_FORBIDDEN"
    assert captured["base_url"] == "https://stored.example.com/v1"
    assert captured["api_key"] == "sk-stored-discovery-key"

    conn = _db()
    try:
        audit_rows = conn.execute(
            "SELECT action, before_json, after_json FROM audit_logs WHERE target_id = ?",
            (created["id"],),
        ).fetchall()
    finally:
        conn.close()
    assert [row["action"] for row in audit_rows] == ["provider.create"]
    audit_text = "".join(f"{row['before_json']}{row['after_json']}" for row in audit_rows)
    assert "sk-stored-discovery-key" not in audit_text
    assert "attacker-key" not in audit_text


def test_saved_model_discovery_revalidates_legacy_transport_before_decrypting(
    admin_client, monkeypatch
):
    """A row allowed by legacy CRUD rules cannot send its key over plain HTTP discovery."""
    created = _create_provider(
        admin_client,
        base_url="http://legacy-public-gateway.example.com/v1",
        api_key="sk-legacy-key",
    ).json()
    called = False

    async def fake_discover(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"supported": True, "models": []}

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    response = admin_client.post(f"/api/admin/providers/{created['id']}/discover-models")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BASE_URL"
    assert called is False


def test_model_discovery_maps_provider_errors_without_exposing_upstream_text(admin_client, monkeypatch):
    """ProviderError content is internal-only even when a future adapter returns unsafe text."""
    raw_failure = "credential=sk-secret url=https://catalog.example.com/private"

    async def fake_discover(*_args, **_kwargs):
        raise providers.ProviderError(raw_failure)

    monkeypatch.setattr(providers, "discover_models", fake_discover)
    response = admin_client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "chat_completions",
            "base_url": "https://catalog.example.com/v1",
            "api_key": "sk-secret",
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_DISCOVERY_FAILED"
    assert "sk-secret" not in response.text
    assert "catalog.example.com/private" not in response.text
    assert raw_failure not in response.text


def test_model_discovery_rejects_retired_protocol_without_network(admin_client):
    """Retired protocols fail validation before any outbound model lookup."""
    response = admin_client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "legacy_ws",
            "base_url": "https://legacy.example.com",
            "api_key": "legacy-key",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_PROTOCOL"


def test_credential_bearing_provider_helpers_require_csrf(app_and_admin):
    """Discovery and transient testing are mutations for CSRF purposes."""
    _, client, _ = app_and_admin
    created = _create_provider(client).json()
    del client.headers["x-csrf-token"]

    transient = client.post(
        "/api/admin/providers/discover-models",
        json={
            "protocol": "chat_completions",
            "base_url": "https://catalog.example.com/v1",
            "api_key": "sk-key",
        },
    )
    transient_test = client.post(
        "/api/admin/providers/test-connection",
        json={
            "protocol": "chat_completions",
            "base_url": "https://catalog.example.com/v1",
            "api_key": "sk-key",
            "model": "demo-model",
        },
    )
    saved = client.post(f"/api/admin/providers/{created['id']}/discover-models")

    assert transient.status_code == 403
    assert transient.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    assert transient_test.status_code == 403
    assert transient_test.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    assert saved.status_code == 403
    assert saved.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


def test_provider_crud_and_key_never_echoed(admin_client):
    resp = _create_provider(admin_client)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["api_key_set"] is True
    assert created["api_key_masked"] == "********"
    assert "api_key" not in created
    assert created["role"] == "none"

    resp = admin_client.get("/api/admin/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert "api_key" not in body["items"][0]
    assert body["items"][0]["api_key_masked"] == "********"
    # 整个响应体的序列化里也不得出现密钥明文
    assert "sk-test-key-123" not in resp.text

    resp = admin_client.put(
        f"/api/admin/providers/{created['id']}", json={"name": "新名字", "timeout_seconds": 15}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名字"
    assert resp.json()["timeout_seconds"] == 15
    assert resp.json()["api_key_masked"] == "********"

    # 管理端流式探测已被移除，旧接口不得继续触发供应商调用。
    assert admin_client.post(f"/api/admin/providers/{created['id']}/stream-test").status_code == 404

    resp = admin_client.delete(f"/api/admin/providers/{created['id']}")
    assert resp.status_code == 200
    assert admin_client.get("/api/admin/providers").json()["total"] == 0

    # 每个变更都应有审计行
    conn = _db()
    try:
        actions = [
            row["action"]
            for row in conn.execute(
                "SELECT action FROM audit_logs WHERE target_type = 'provider'"
            )
        ]
    finally:
        conn.close()
    assert actions == ["provider.create", "provider.update", "provider.delete"]


def test_provider_set_role_uniqueness(admin_client):
    first = _create_provider(admin_client, name="A").json()
    second = _create_provider(admin_client, name="B").json()

    resp = admin_client.post(f"/api/admin/providers/{first['id']}/set-role", json={"role": "primary"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "primary"

    # B 设为 primary 后，A 必须被清成 none（至多一个主模型）
    resp = admin_client.post(f"/api/admin/providers/{second['id']}/set-role", json={"role": "primary"})
    assert resp.status_code == 200
    roles = {p["name"]: p["role"] for p in admin_client.get("/api/admin/providers").json()["items"]}
    assert roles == {"A": "none", "B": "primary"}

    # none 仅清除自身角色
    resp = admin_client.post(f"/api/admin/providers/{second['id']}/set-role", json={"role": "none"})
    assert resp.json()["role"] == "none"
    # 非法角色被拒绝
    assert admin_client.post(
        f"/api/admin/providers/{second['id']}/set-role", json={"role": "super"}
    ).status_code == 400


def test_provider_supports_multiple_roles_and_reassigns_one_role_only(admin_client):
    """One model can serve several roles while each role has one owner."""
    first = _create_provider(
        admin_client,
        name="模型A",
        roles=["primary", "embedding"],
    ).json()
    assert first["roles"] == ["primary", "embedding"]
    assert first["role"] == "primary"

    second = _create_provider(
        admin_client,
        name="模型B",
        roles=["fallback"],
    ).json()
    updated = admin_client.put(
        f"/api/admin/providers/{second['id']}",
        json={"roles": ["primary", "fallback"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["roles"] == ["primary", "fallback"]

    listed = {
        item["name"]: item
        for item in admin_client.get("/api/admin/providers").json()["items"]
    }
    # Only the conflicting primary assignment transfers; A keeps embedding.
    assert listed["模型A"]["roles"] == ["embedding"]
    assert listed["模型A"]["role"] == "embedding"
    assert listed["模型B"]["roles"] == ["primary", "fallback"]


def test_provider_legacy_set_role_adds_without_dropping_other_roles(admin_client):
    """The scalar compatibility endpoint must not erase a multi-role row."""
    provider = _create_provider(
        admin_client,
        roles=["primary", "embedding"],
    ).json()
    response = admin_client.post(
        f"/api/admin/providers/{provider['id']}/set-role",
        json={"role": "rerank"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["primary", "embedding", "rerank"]

    cleared = admin_client.post(
        f"/api/admin/providers/{provider['id']}/set-role",
        json={"role": "none"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["roles"] == []


def test_provider_test_endpoint_records_last_test(admin_client, monkeypatch):
    # 真实网络出口由 providers 单测覆盖；这里替换为可控实现，验证端点接线与落库
    async def fake_test(row):
        return {
            "ok": True,
            "role": row["role"],
            "latency_ms": 12,
            "model": row["model"],
            "error": None,
            "tested_at": "2026-07-31T00:00:00+00:00",
        }

    monkeypatch.setattr(providers, "test_provider", fake_test)
    created = _create_provider(admin_client, role="primary").json()
    resp = admin_client.post(f"/api/admin/providers/{created['id']}/test")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert resp.json()["role"] == "primary"
    assert resp.json()["latency_ms"] == 12
    listed = admin_client.get("/api/admin/providers").json()["items"][0]
    assert listed["last_test"]["ok"] is True
    assert listed["last_test"]["role"] == "primary"


def test_provider_test_endpoint_reuses_server_stored_key(admin_client, monkeypatch):
    """Connection tests decrypt the saved credential server-side, never from form input."""
    captured: dict[str, str] = {}

    async def fake_test(row):
        captured["api_key"] = providers.decrypt_key(row)
        return {
            "ok": True,
            "role": row["role"],
            "latency_ms": 5,
            "model": row["model"],
            "error": None,
            "tested_at": "2026-08-08T00:00:00+00:00",
        }

    monkeypatch.setattr(providers, "test_provider", fake_test)
    secret = "sk-server-stored-test-key"
    created = _create_provider(admin_client, api_key=secret).json()
    response = admin_client.post(f"/api/admin/providers/{created['id']}/test")

    assert response.status_code == 200, response.text
    assert captured == {"api_key": secret}
    assert secret not in response.text


def test_saved_provider_model_probe_reuses_key_without_persisting_selection(admin_client, monkeypatch):
    """Editing a model probes the selected value, not the stale database row."""
    captured: dict[str, object] = {}

    async def fake_transient(protocol, base_url, api_key, model, role="none", extra=None):
        captured.update(
            {
                "protocol": protocol,
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "role": role,
                "extra": extra,
            }
        )
        return {
            "ok": True,
            "role": role,
            "latency_ms": 7,
            "model": model,
            "error": None,
            "tested_at": "2026-08-10T00:00:00+00:00",
        }

    monkeypatch.setattr(providers, "test_transient_provider", fake_transient)
    secret = "sk-saved-model-probe"
    created = _create_provider(admin_client, api_key=secret, model="old-model", role="primary").json()

    response = admin_client.post(
        f"/api/admin/providers/{created['id']}/test-connection",
        json={"model": "new-model"},
    )

    assert response.status_code == 200, response.text
    assert captured["api_key"] == secret
    assert captured["model"] == "new-model"
    assert captured["role"] == "primary"
    assert secret not in response.text
    listed = admin_client.get("/api/admin/providers").json()["items"][0]
    assert listed["model"] == "old-model"
    assert listed["last_test"] is None


def test_provider_test_allows_enabled_unassigned_role_and_rejects_disabled(admin_client, monkeypatch):
    """An enabled unassigned config delegates capability choice to the provider adapter."""
    calls: list[tuple[str, str]] = []

    async def fake_test(row):
        # Preserve the received role so this route test proves `none` reaches
        # the adapter, while the adapter owns the neutral chat probe choice.
        calls.append((str(row["id"]), str(row["role"])))
        return {"ok": True, "role": row["role"]}

    monkeypatch.setattr(providers, "test_provider", fake_test)
    unassigned = _create_provider(admin_client).json()
    response = admin_client.post(f"/api/admin/providers/{unassigned['id']}/test")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["role"] == "none"
    assert calls == [(unassigned["id"], "none")]

    disabled = _create_provider(admin_client, name="disabled", role="primary", enabled=False).json()
    response = admin_client.post(f"/api/admin/providers/{disabled['id']}/test")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROVIDER_NOT_TESTABLE"
    # Disabling a provider remains a hard outbound-request boundary.
    assert calls == [(unassigned["id"], "none")]


def test_admin_mutations_require_csrf(app_and_admin):
    _, client, _ = app_and_admin
    del client.headers["x-csrf-token"]
    resp = _create_provider(client)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


def test_admin_endpoints_reject_non_admin(tmp_db_path, monkeypatch):
    # 学生会话访问 /api/admin/* 必须 401（无管理端 cookie）
    monkeypatch.setenv("BHZD_SMTP_HOST", "")
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    reset_config_cache()
    conn = _db()
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    _insert_user(STUDENT_EMAIL, "学生", "student", STUDENT_PASSWORD)
    with TestClient(_build_app()) as client:
        resp = _login(client, STUDENT_EMAIL, STUDENT_PASSWORD)
        assert resp.status_code == 200
        assert client.get("/api/admin/providers").status_code == 401
    reset_config_cache()


# ---------------------------------------------------------------- RAG 参数

def test_rag_settings_get_and_patch_with_audit(admin_client):
    resp = admin_client.get("/api/admin/rag-settings")
    assert resp.status_code == 200
    defaults = resp.json()
    assert defaults["chunk_size"] == 500
    assert defaults["title_inherit"] is True  # 0/1 折成布尔
    assert defaults["query_rewrite_enabled"] is False
    assert defaults["temperature"] == 0.3
    assert defaults["top_p"] == 0.9
    assert "table_strategy" not in defaults  # retired setting stays DB-only for compatibility
    assert "prompt_template" not in defaults
    assert "require_manual_review" not in defaults

    resp = admin_client.patch(
        "/api/admin/rag-settings",
        json={
            "chunk_size": 800,
            "top_k": 10,
            "score_threshold": 0.5,
            "temperature": 0.2,
            "top_p": 0.85,
            "query_rewrite_enabled": True,
        },
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["chunk_size"] == 800
    assert updated["top_k"] == 10
    assert updated["query_rewrite_enabled"] is True
    assert updated["temperature"] == 0.2
    assert updated["top_p"] == 0.85
    assert "table_strategy" not in updated

    conn = _db()
    try:
        row = conn.execute(
            "SELECT before_json, after_json FROM audit_logs WHERE action = 'rag_settings.update'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert '"chunk_size": 500' in row["before_json"]
    assert '"chunk_size": 800' in row["after_json"]


def test_rag_settings_patch_range_validation(admin_client):
    assert admin_client.patch("/api/admin/rag-settings", json={"chunk_size": 50}).status_code == 400
    assert admin_client.patch("/api/admin/rag-settings", json={"chunk_size": 5000}).status_code == 400
    assert admin_client.patch("/api/admin/rag-settings", json={"top_k": 0}).status_code == 400
    assert admin_client.patch("/api/admin/rag-settings", json={"score_threshold": 1.5}).status_code == 400
    # Retired generation settings are rejected instead of silently persisted.
    assert admin_client.patch(
        "/api/admin/rag-settings", json={"refusal_policy": "always_answer"}
    ).status_code == 422
    assert admin_client.patch("/api/admin/rag-settings", json={"temperature": 2.1}).status_code == 400
    assert admin_client.patch("/api/admin/rag-settings", json={"top_p": -0.1}).status_code == 400
    # 重叠区不得大于等于切片长度（否则切片器死循环）
    assert admin_client.patch(
        "/api/admin/rag-settings", json={"chunk_size": 200, "chunk_overlap": 200}
    ).status_code == 400
    # 未知字段直接拒绝
    assert admin_client.patch("/api/admin/rag-settings", json={"unknown_field": 1}).status_code == 422
    # Removed settings must not silently re-enter the management contract.
    assert admin_client.patch("/api/admin/rag-settings", json={"table_strategy": "flatten"}).status_code == 422


# ---------------------------------------------------------------- 用户与权限

def test_users_list_filter_and_patch_disable_revokes_sessions(app_and_admin):
    app, admin_client, _ = app_and_admin
    student_id = _insert_user(STUDENT_EMAIL, "学生一", "student", STUDENT_PASSWORD)

    # 学生先在独立客户端登录（持有有效会话）
    with TestClient(app) as student_client:
        resp = _login(student_client, STUDENT_EMAIL, STUDENT_PASSWORD)
        assert resp.status_code == 200
        assert student_client.get("/api/auth/session").status_code == 200

        # 管理员禁用该学生 → 学生会话立即失效（PRD-06 §3.4）
        resp = admin_client.patch(f"/api/admin/users/{student_id}", json={"status": "disabled"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"
        assert student_client.get("/api/auth/session").status_code == 401

    # 列表过滤：role + q
    resp = admin_client.get("/api/admin/users", params={"role": "student", "q": "student@"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == STUDENT_EMAIL

    # 禁用动作写入审计
    resp = admin_client.get("/api/admin/audit-logs", params={"action": "user.update"})
    assert resp.json()["total"] >= 1


def test_users_bulk_status_and_role_filtered_csv_export(app_and_admin):
    """Bulk status changes stay audited and CSV export excludes credential material."""

    _, admin_client, _ = app_and_admin
    first_id = _insert_user("bulk-one@test.local", "批量一", "student", STUDENT_PASSWORD)
    second_id = _insert_user("bulk-two@test.local", "=公式用户", "student", STUDENT_PASSWORD)

    response = admin_client.patch(
        "/api/admin/users/bulk-status",
        json={"user_ids": [first_id, second_id], "status": "disabled"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2
    assert response.json()["skipped"] == 0

    exported = admin_client.get(
        "/api/admin/users/export.csv", params={"role": "student", "q": "bulk-"}
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment" in exported.headers["content-disposition"]
    assert "id,name,email,role,status,email_verified,created_at" in exported.text
    assert "bulk-one@test.local" in exported.text
    # Spreadsheet formula injection is neutralized and no password/hash field is exported.
    assert "'=公式用户" in exported.text
    assert "password_hash" not in exported.text

    audit_rows = admin_client.get("/api/admin/audit-logs", params={"action": "user.update"})
    assert audit_rows.json()["total"] >= 2


def test_users_bulk_status_rejects_self_disable_without_partial_update(app_and_admin):
    """A batch containing the current administrator is rejected before any row changes."""

    _, admin_client, admin_id = app_and_admin
    student_id = _insert_user("bulk-safe@test.local", "批量安全", "student", STUDENT_PASSWORD)
    response = admin_client.patch(
        "/api/admin/users/bulk",
        json={"user_ids": [student_id, admin_id], "status": "disabled"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SELF_OPERATION_FORBIDDEN"
    student = admin_client.get("/api/admin/users", params={"q": "bulk-safe@"}).json()["items"][0]
    assert student["status"] == "active"


def test_admin_cannot_disable_or_demote_self(app_and_admin):
    _, admin_client, admin_id = app_and_admin
    resp = admin_client.patch(f"/api/admin/users/{admin_id}", json={"status": "disabled"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SELF_OPERATION_FORBIDDEN"
    resp = admin_client.patch(f"/api/admin/users/{admin_id}", json={"role": "teacher"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SELF_OPERATION_FORBIDDEN"


def test_admin_reset_password_returns_temp_once_and_revokes(app_and_admin):
    app, admin_client, _ = app_and_admin
    student_id = _insert_user(STUDENT_EMAIL, "学生二", "student", STUDENT_PASSWORD)
    with TestClient(app) as student_client:
        assert _login(student_client, STUDENT_EMAIL, STUDENT_PASSWORD).status_code == 200

        resp = admin_client.post(f"/api/admin/users/{student_id}/reset-password")
        assert resp.status_code == 200, resp.text
        temp_password = resp.json()["temporary_password"]

        # 旧会话被吊销；旧密码失效；临时密码可登录
        assert student_client.get("/api/auth/session").status_code == 401
        assert _login(student_client, STUDENT_EMAIL, STUDENT_PASSWORD).status_code == 401
        resp = _login(student_client, STUDENT_EMAIL, temp_password)
        assert resp.status_code == 200


# ---------------------------------------------------------------- 审计查询

def test_audit_logs_filters(app_and_admin):
    _, admin_client, admin_id = app_and_admin
    _create_provider(admin_client)

    resp = admin_client.get("/api/admin/audit-logs", params={"action": "provider.create"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["actor_id"] == admin_id
    assert item["actor_role"] == "system_admin"
    assert item["target_type"] == "provider"
    assert item["after"]["name"] == "主模型"  # before/after 已解析为 JSON
    # 审计快照不得包含密钥密文之外的任何密钥材料
    assert "sk-test-key-123" not in resp.text

    # 不匹配的条件过滤为空
    resp = admin_client.get("/api/admin/audit-logs", params={"action": "provider.delete"})
    assert resp.json()["total"] == 0
    # actor_id 过滤
    resp = admin_client.get("/api/admin/audit-logs", params={"actor_id": admin_id})
    assert resp.json()["total"] >= 1


# ---------------------------------------------------------------- 运营指标

def test_metrics_structure_and_honest_nulls(admin_client):
    resp = admin_client.get("/api/admin/metrics")
    assert resp.status_code == 200
    body = resp.json()
    expected_keys = {
        "tool_call_success_rate",
        "rag_retrieval_hit_rate",
        "rag_refusal_rate",
        "task_creation_conversion",
        "preset_start_rate",
        "diagnostic_success_rate",
        "mastery_confirm_rate",
        "model_failure_rate_by_provider",
        "login_success_today",
        "login_failure_today",
        "active_sessions",
        "api_success_rate_24h",
        "provider_latency_avg_ms",
    }
    assert set(body["metrics"].keys()) == expected_keys
    # Counts are honest zeroes in an empty database; rates remain null without samples.
    # The admin fixture itself performs one successful login before this read.
    assert body["metrics"]["login_success_today"] >= 1
    assert body["metrics"]["login_failure_today"] == 0
    assert body["metrics"]["active_sessions"] >= 1
    assert body["metrics"]["api_success_rate_24h"] is None
    assert body["metrics"]["provider_latency_avg_ms"] is None
    assert all(
        value is None
        for name, value in body["metrics"].items()
        if name not in {"login_success_today", "login_failure_today", "active_sessions"}
    )
    assert "null" in body["note"]


def test_metrics_computed_from_real_data(admin_client):
    conn = _db()
    try:
        now = utc_now_iso()
        events = [
            ("task_preview_created", "{}"),
            ("task_preview_created", "{}"),
            ("task_created", '{"source": "preset"}'),
            ("preset_clicked", "{}"),
            ("rag_retrieval_completed", '{"hit_count": 3}'),
            ("rag_retrieval_completed", '{"hit_count": 0}'),
        ]
        for name, props in events:
            conn.execute(
                "INSERT INTO analytics_events (user_id, event_name, props_json, created_at)"
                " VALUES (NULL, ?, ?, ?)",
                (name, props, now),
            )
        conn.commit()
    finally:
        conn.close()

    body = admin_client.get("/api/admin/metrics").json()
    assert body["metrics"]["task_creation_conversion"] == 0.5
    assert body["metrics"]["preset_start_rate"] == 1.0
    assert body["metrics"]["rag_retrieval_hit_rate"] == 0.5
    # 无数据的指标仍为 null
    assert body["metrics"]["mastery_confirm_rate"] is None


def test_alerts_dashboard_degrades_when_optional_schema_is_unavailable(admin_client, monkeypatch):
    """Security page remains usable while an older deployment is being migrated."""

    def raise_schema_error(_conn):
        raise sqlite3.OperationalError("no such table: optional_alert_source")

    monkeypatch.setattr(admin, "evaluate_alerts", raise_schema_error)
    response = admin_client.get("/api/admin/alerts")
    assert response.status_code == 200, response.text
    assert response.json()["alerts"] == []
