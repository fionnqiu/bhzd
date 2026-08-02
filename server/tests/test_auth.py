"""认证域测试（蓝图 §6.1）：注册/验证/登录/会话/找回重置/限流锁定/角色邀请码。

夹具策略（为什么）：
- 强制清空 BHZD_SMTP_HOST：走 mail_outbox 开发兜底，验证/重置令牌经响应的
  dev_* 字段回显，测试无需读日志文件。
- 锁定/限流阈值是 security.py 的模块常量，用 monkeypatch 改小即可在数秒内
  触发锁定，不必真的打满 10 次失败。
"""

from __future__ import annotations

import secrets
import uuid
from base64 import b64encode
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from bhzd_py import security
from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.deps import CurrentUser, csrf_protect
from bhzd_py.errors import register_error_handlers
from bhzd_py.routers import auth
from bhzd_py.security import generate_token, hash_password, hash_token

INVITE_CODE = "test-teacher-invite"
PASSWORD = "Passw0rd1"


def _build_app() -> FastAPI:
    """只挂本域 router 的最小应用。

    为什么不用 create_app()：它会 import 全部兄弟 router，而 Wave2 并行开发
    期间其它域的半成品模块（SyntaxError 不在 app.py 的 ImportError 兜底
    范围内）会让整个应用起不来；本域测试必须与之解耦。Wave4 集成再测全量。

    /api/_probe 是仅测试用的 CSRF 探针端点：auth 域自身没有 csrf_protect 路由
    （登出刻意不强制 CSRF），令牌契约（稳定/可变更/防篡改）需要一个真实
    走 csrf_protect 依赖的端点来验证。
    """
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth.router)

    @app.post("/api/_probe")
    def _probe(current: CurrentUser = Depends(csrf_protect)):  # noqa: ARG001
        return {"ok": True}

    return app


@pytest.fixture()
def client(tmp_db_path, monkeypatch):
    """每测试一个全新应用 + 临时库；SMTP 强制为空（开发兜底模式）。"""
    monkeypatch.setenv("BHZD_SMTP_HOST", "")
    monkeypatch.setenv("BHZD_TEACHER_INVITE_CODE", INVITE_CODE)
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    reset_config_cache()
    conn = connect(get_config().resolved_database_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    with TestClient(_build_app()) as test_client:
        yield test_client
    reset_config_cache()


def _password_envelope(client: TestClient, password: str) -> dict[str, str]:
    """Build the real browser wire format so tests cannot mask plaintext regressions."""
    key_response = client.get("/api/auth/password-key")
    assert key_response.status_code == 200
    assert key_response.headers["cache-control"] == "no-store"
    key = key_response.json()
    public_key = serialization.load_pem_public_key(key["publicKeyPem"].encode("ascii"))
    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, password.encode("utf-8"), None)
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "keyId": key["keyId"],
        "encryptedKey": b64encode(encrypted_key).decode("ascii"),
        "iv": b64encode(iv).decode("ascii"),
        "ciphertext": b64encode(ciphertext).decode("ascii"),
    }


def _register(client: TestClient, email: str, password: str = PASSWORD, name: str = "测试用户", **extra):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "name": name,
            "passwordEnvelope": _password_envelope(client, password),
            **extra,
        },
    )


def _register_and_verify(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    resp = _register(client, email, password)
    assert resp.status_code == 201, resp.text
    token = resp.json()["dev_verify_token"]
    resp = client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text
    return {"email": email, "password": password}


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/api/auth/login",
        json={"email": email, "passwordEnvelope": _password_envelope(client, password)},
    )


def _db():
    return connect(get_config().resolved_database_path)


# ---------------------------------------------------------------- 完整流程

def test_full_register_verify_login_session_logout_flow(client):
    resp = _register(client, "flow@example.com")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "student"
    assert body["user"]["status"] == "active"
    assert body["user"]["email_verified"] is False
    # 未配置 SMTP 时回显开发令牌（生产响应无此字段）
    dev_token = body["dev_verify_token"]

    # 错误令牌不得通过
    resp = client.post("/api/auth/verify-email", json={"token": "wrong-token"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"

    resp = client.post("/api/auth/verify-email", json={"token": dev_token})
    assert resp.status_code == 200

    resp = _login(client, "flow@example.com")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["email"] == "flow@example.com"
    assert data["user"]["email_verified"] is True
    assert data["csrf_token"]
    assert "bhzd_session" in resp.cookies
    assert "bhzd_admin_session" not in resp.cookies  # 学生不签发管理端会话

    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    session_body = resp.json()
    assert session_body["user"]["email"] == "flow@example.com"
    assert session_body["csrf_token"]
    # 008 起令牌稳定：取会话返回的仍是登录时签发的那一枚，不再轮换
    assert session_body["csrf_token"] == data["csrf_token"]

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client.get("/api/auth/session").status_code == 401


# ---------------------------------------------------------------- CSRF 令牌稳定化（008）

def test_csrf_token_stable_across_session_gets(client):
    """新契约：多次 GET /api/auth/session 返回同一枚令牌（多标签页不互顶）。"""
    _register_and_verify(client, "stable@example.com")
    login_body = _login(client, "stable@example.com").json()
    first = client.get("/api/auth/session").json()["csrf_token"]
    second = client.get("/api/auth/session").json()["csrf_token"]
    assert first == login_body["csrf_token"]
    assert second == first

    # 稳定令牌可以反复用于变更请求（不像轮换时代"用后即刻被下次 GET 顶掉"）
    resp = client.post("/api/_probe", headers={"x-csrf-token": first})
    assert resp.status_code == 200
    resp = client.post("/api/_probe", headers={"x-csrf-token": first})
    assert resp.status_code == 200
    # 篡改的令牌必须被拒绝
    resp = client.post("/api/_probe", headers={"x-csrf-token": first[:-2] + "zz"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


def test_legacy_session_upgraded_on_session_get(client):
    """008 迁移前的存量会话（只有 csrf_token_hash）：旧哈希路径仍可用，
    首次 GET /api/auth/session 补发原始令牌落库，之后同样稳定。"""
    _register_and_verify(client, "legacy@example.com")
    # 手工建一条 legacy 会话：csrf_token 列为 NULL，只有哈希（模拟迁移前数据）
    conn = _db()
    raw_session, raw_csrf = generate_token(), generate_token()
    try:
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = 'legacy@example.com'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO user_sessions"
            " (id, user_id, token_hash, csrf_token_hash, csrf_token, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (
                uuid.uuid4().hex, user_id, hash_token(raw_session), hash_token(raw_csrf),
                utc_now_iso(),
                (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    client.cookies.set("bhzd_session", raw_session)

    # legacy 哈希比对路径：迁移前签发的令牌依旧能过 CSRF 校验
    resp = client.post("/api/_probe", headers={"x-csrf-token": raw_csrf})
    assert resp.status_code == 200

    # 首次取会话：补发原始令牌；再次取：返回同一枚（升级后进入稳定契约）
    upgraded = client.get("/api/auth/session").json()["csrf_token"]
    assert upgraded != raw_csrf
    assert client.get("/api/auth/session").json()["csrf_token"] == upgraded
    resp = client.post("/api/_probe", headers={"x-csrf-token": upgraded})
    assert resp.status_code == 200


def test_register_validation(client):
    # 非法邮箱格式（email-validator）
    assert _register(client, "not-an-email").status_code == 422
    # 口令策略：太短 / 纯字母 / 纯数字
    assert _register(client, "a@example.com", password="Ab1").status_code == 400
    assert _register(client, "a@example.com", password="abcdefgh").status_code == 400
    assert _register(client, "a@example.com", password="12345678").status_code == 400


def test_password_envelope_rejects_plaintext_and_tampering(client):
    """All user-supplied passwords must traverse the same encrypted contract."""
    plaintext = client.post(
        "/api/auth/register",
        json={"email": "plain@example.com", "name": "明文", "password": PASSWORD},
    )
    assert plaintext.status_code == 422

    plaintext_login = client.post(
        "/api/auth/login",
        json={"email": "plain@example.com", "password": PASSWORD},
    )
    assert plaintext_login.status_code == 422

    plaintext_reset = client.post(
        "/api/auth/reset-password",
        json={"token": "unused", "password": "NewPass123"},
    )
    assert plaintext_reset.status_code == 422

    malformed = client.post(
        "/api/auth/login",
        json={
            "email": "plain@example.com",
            "passwordEnvelope": {
                "keyId": "stale-key",
                "encryptedKey": "not-base64",
                "iv": "not-base64",
                "ciphertext": "not-base64",
            },
        },
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "INVALID_PASSWORD_ENCRYPTION"


def test_production_smtp_failure_never_echoes_tokens_or_writes_outbox(
    tmp_db_path, tmp_path, monkeypatch
):
    """Production keeps account flows safe when the configured SMTP service is down."""
    outbox_path = tmp_path / "must-not-exist.log"
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("BHZD_DATABASE_PATH", tmp_db_path)
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    monkeypatch.setenv("BHZD_TEACHER_INVITE_CODE", "test-only-private-teacher-invite")
    monkeypatch.setenv("BHZD_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BHZD_SMTP_PORT", "2525")
    monkeypatch.setenv("BHZD_SMTP_SECURE", "false")
    monkeypatch.setenv("BHZD_MAIL_FROM", "BHZD Test <noreply@example.test>")
    monkeypatch.setenv("BHZD_MAIL_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("BHZD_PUBLIC_ORIGIN", "https://app.example.test")
    monkeypatch.setenv("BHZD_CORS_ORIGINS", "https://app.example.test")
    reset_config_cache()
    conn = connect(get_config().resolved_database_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()

    def _smtp_unavailable(*_args, **_kwargs):
        # The fake transport prevents a test from attempting a real SMTP dial.
        raise OSError("test SMTP unavailable")

    monkeypatch.setattr(auth.smtplib, "SMTP", _smtp_unavailable)
    monkeypatch.setattr(auth.smtplib, "SMTP_SSL", _smtp_unavailable)
    with TestClient(_build_app()) as production_client:
        registered = _register(production_client, "production-mail@example.com")
        assert registered.status_code == 201, registered.text
        registration_body = registered.json()
        assert registration_body["mail_delivered"] is False
        assert "dev_verify_token" not in registration_body

        forgot = production_client.post(
            "/api/auth/forgot-password", json={"email": "production-mail@example.com"}
        )
        assert forgot.status_code == 200
        forgot_body = forgot.json()
        assert forgot_body["mail_delivered"] is False
        assert "dev_reset_token" not in forgot_body

    assert not outbox_path.exists()
    reset_config_cache()


def test_duplicate_email_uniform_message(client):
    # 未验证账号重复注册
    _register(client, "dup@example.com")
    resp_unverified = _register(client, "dup@example.com")
    assert resp_unverified.status_code == 409

    # 已验证账号重复注册：话术必须一致，不暴露验证状态（PRD-06 §3.4）
    _register_and_verify(client, "dup2@example.com")
    resp_verified = _register(client, "dup2@example.com")
    assert resp_verified.status_code == 409
    assert resp_verified.json()["error"]["message"] == resp_unverified.json()["error"]["message"]


def test_teacher_invite_code_required(client):
    # 教师角色无邀请码 / 错误邀请码 → 403
    assert _register(client, "t1@example.com", role="teacher").status_code == 403
    resp = _register(client, "t1@example.com", role="teacher", teacher_invite="wrong-code")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INVITE_CODE_INVALID"
    # 正确邀请码 → 201 且角色为 teacher
    resp = _register(client, "t1@example.com", role="teacher", teacher_invite=INVITE_CODE)
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "teacher"
    # 管理类角色不开放自助注册
    resp = _register(client, "evil@example.com", role="system_admin", teacher_invite=INVITE_CODE)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


# ---------------------------------------------------------------- 登录安全

def test_wrong_password_lockout(client, monkeypatch):
    # 阈值改小以便测试快速触发；IP 限流放大避免干扰锁定判定
    monkeypatch.setattr(security, "LOCKOUT_THRESHOLD_FAILURES", 3)
    monkeypatch.setattr(security, "RATE_LIMIT_ATTEMPTS_PER_MINUTE", 100)
    _register_and_verify(client, "lock@example.com")

    for _ in range(3):
        resp = _login(client, "lock@example.com", password="WrongPass1")
        assert resp.status_code == 401
    # 达到阈值：连正确密码也被锁定
    resp = _login(client, "lock@example.com")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "LOGIN_LOCKED"


def test_disabled_account_login_blocked(client):
    _register_and_verify(client, "disabled@example.com")
    conn = _db()
    try:
        conn.execute("UPDATE users SET status = 'disabled' WHERE email = 'disabled@example.com'")
        conn.commit()
    finally:
        conn.close()
    resp = _login(client, "disabled@example.com")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_legacy_hash_mismatch_is_invalid_not_error(client):
    # 旧算法（如 bcrypt）哈希：argon2 校验失败必须按"密码不正确"处理，不能 500
    conn = _db()
    try:
        user_id = uuid.uuid4().hex
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO users (id, email, name, role, status, created_at, updated_at)"
            " VALUES (?, 'legacy@example.com', '旧账号', 'student', 'active', ?, ?)",
            (user_id, now, now),
        )
        conn.execute(
            "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at)"
            " VALUES (?, '$2b$12$abcdefghijklmnopqrstuuVXZ9G1l5b5b5b5b5b5b5b5b5b5b5b5b5b', 'bcrypt', ?)",
            (user_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    resp = _login(client, "legacy@example.com")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_audit_rows_written(client):
    _register_and_verify(client, "audit@example.com")
    _login(client, "audit@example.com", password="WrongPass1")  # 失败
    _login(client, "audit@example.com")  # 成功
    client.post("/api/auth/logout")
    conn = _db()
    try:
        actions = {
            row["action"]
            for row in conn.execute(
                "SELECT action FROM audit_logs WHERE action LIKE 'auth.%'"
            )
        }
    finally:
        conn.close()
    assert {"auth.login_failed", "auth.login", "auth.logout"} <= actions


# ---------------------------------------------------------------- 找回 / 重置密码

def test_forgot_password_uniform_and_reset_revokes_sessions(client):
    _register_and_verify(client, "reset@example.com")
    assert _login(client, "reset@example.com").status_code == 200
    assert client.get("/api/auth/session").status_code == 200

    # 不存在的邮箱：同样的统一话术，且无 dev 字段泄露存在性
    resp = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    uniform_message = resp.json()["message"]
    assert "dev_reset_token" not in resp.json()

    resp = client.post("/api/auth/forgot-password", json={"email": "reset@example.com"})
    assert resp.status_code == 200
    assert resp.json()["message"] == uniform_message
    reset_token = resp.json()["dev_reset_token"]

    # 弱口令被拒绝
    resp = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "passwordEnvelope": _password_envelope(client, "weak")},
    )
    assert resp.status_code == 400

    resp = client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "passwordEnvelope": _password_envelope(client, "NewPass123"),
        },
    )
    assert resp.status_code == 200

    # 旧会话全部吊销；旧密码失效，新密码可登录
    assert client.get("/api/auth/session").status_code == 401
    assert _login(client, "reset@example.com").status_code == 401
    assert _login(client, "reset@example.com", password="NewPass123").status_code == 200

    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_logs WHERE action = 'auth.password_reset'"
        ).fetchone()
    finally:
        conn.close()
    assert row["n"] >= 1


# ---------------------------------------------------------------- 重发验证邮件

def test_resend_verification_rate_limit(client):
    _register(client, "resend@example.com")  # 注册本身已发 1 封
    assert _login(client, "resend@example.com").status_code == 200

    # 每小时上限 3 封（含注册那封）：第 2、3 封成功，第 4 次请求被限流
    assert client.post("/api/auth/resend-verification").status_code == 200
    assert client.post("/api/auth/resend-verification").status_code == 200
    resp = client.post("/api/auth/resend-verification")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RESEND_LIMITED"

    # 已验证后重发 → 400
    _register_and_verify(client, "resend2@example.com")
    assert _login(client, "resend2@example.com").status_code == 200
    resp = client.post("/api/auth/resend-verification")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "ALREADY_VERIFIED"


def test_resend_verification_requires_login(client):
    resp = client.post("/api/auth/resend-verification")
    assert resp.status_code == 401
