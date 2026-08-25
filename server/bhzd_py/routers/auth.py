"""认证路由（蓝图 §6.1，PRD-05 §4.1 + PRD-06 §3）。

关键决策（为什么）：
- 会话/验证/重置令牌库里只存 sha256，原始令牌只在签发响应或邮件里出现
  一次——配合 security.py 的设计，库泄露不可回推。CSRF 令牌例外：008 迁移
  起原始值落会话行（csrf_token 列），换取会话期内令牌稳定（多标签页不互顶），
  它本就只发给该会话持有者，无回推风险面。
- 重复邮箱、找回密码一律给统一话术：不暴露"该邮箱是否已注册/是否已验证"
  （PRD-06 §3.4 边界条件）。
- 未配置 SMTP 时，遗留验证重发和密码重置会把链接追加写入 mail_outbox.log，
  并仅在开发响应中返回令牌；生产必须配置 BHZD_SMTP_*，不得回显令牌。
- 邮箱验证不再是登录或业务能力的前置条件；保留历史验证接口仅用于兼容旧链接。
- 登出不强制 CSRF：它只靠 cookie 识别并吊销会话本身，最坏后果是被迫重新登录，
  而要求 CSRF 会让"令牌丢失后无法登出"成为死锁。
"""

from __future__ import annotations

import logging
import smtplib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .. import security
from ..audit import audit
from ..config import AppConfig, get_config
from ..db import utc_now_iso
from ..deps import (
    ADMIN_SESSION_COOKIE,
    USER_SESSION_COOKIE,
    CurrentUser,
    _load_any_session,
    _load_valid_session,
    csrf_protect,
    get_current_user,
    get_db,
)
from ..errors import ApiError
from ..security import (
    PasswordEncryptionMaterial,
    create_password_encryption_material,
    decrypt_password_envelope,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 令牌有效期（蓝图 §6.1）
_VERIFY_TOKEN_TTL = timedelta(hours=24)
_RESET_TOKEN_TTL = timedelta(minutes=30)
# 重发验证邮件限流：每用户每小时 3 封
_RESEND_LIMIT_PER_HOUR = 3

MSG_DUPLICATE_EMAIL = "该邮箱已被注册，可直接登录；如忘记密码请使用找回密码功能"
MSG_INVALID_CREDENTIALS = "邮箱或密码不正确"
MSG_PASSWORD_POLICY = "密码至少 8 位，且需同时包含字母和数字"


# ---------------------------------------------------------------- 请求模型

class PasswordEnvelope(BaseModel):
    """Browser-produced hybrid envelope; plaintext password fields are forbidden."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    key_id: str = Field(min_length=1, max_length=128, alias="keyId")
    encrypted_key: str = Field(min_length=1, max_length=8192, alias="encryptedKey")
    iv: str = Field(min_length=1, max_length=128)
    ciphertext: str = Field(min_length=1, max_length=65536)

class RegisterIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    email: EmailStr  # email-validator 做格式校验
    name: str = Field(min_length=1, max_length=50)
    password_envelope: PasswordEnvelope = Field(alias="passwordEnvelope")
    role: str = "student"
    # Deprecated: keep accepting this retired wire field so older teacher-registration clients
    # do not receive a 422 after the invite gate is removed; it is never authorized against.
    teacher_invite: str | None = Field(default=None, deprecated=True)


class VerifyEmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


class LoginIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    email: EmailStr
    password_envelope: PasswordEnvelope = Field(alias="passwordEnvelope")


class ForgotPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    token: str
    password_envelope: PasswordEnvelope = Field(alias="passwordEnvelope")


class ChangePasswordIn(BaseModel):
    """Current and replacement passwords, both sent through the encrypted envelope."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    current_password_envelope: PasswordEnvelope = Field(alias="currentPasswordEnvelope")
    new_password_envelope: PasswordEnvelope = Field(alias="newPasswordEnvelope")


class UpdateProfileIn(BaseModel):
    """自助资料更新：目前仅姓名（长度口径与注册 RegisterIn.name 一致）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------- 口令公钥与内部助手

def _password_material(request: Request) -> PasswordEncryptionMaterial:
    """Read the app-scoped key pair, lazily initializing minimal test apps.

    Production factories initialize this at startup.  The narrow fallback keeps
    isolated router tests deterministic without ever accepting plaintext when a
    test app omits the normal factory.
    """
    material = getattr(request.app.state, "password_encryption", None)
    if material is None:
        material = create_password_encryption_material()
        request.app.state.password_encryption = material
    return material


@router.get("/api/auth/password-key")
def password_key(request: Request, response: Response) -> dict[str, str]:
    """Publish the current RSA public key without allowing intermediary caching."""
    material = _password_material(request)
    response.headers["Cache-Control"] = "no-store"
    return {
        "keyId": material.key_id,
        "algorithm": "RSA-OAEP-256+A256GCM",
        "publicKeyPem": material.public_key_pem,
    }


def _decrypt_auth_password(request: Request, envelope: PasswordEnvelope) -> str:
    """Collapse invalid/stale envelopes to one safe, client-actionable error."""
    try:
        return decrypt_password_envelope(
            envelope.model_dump(by_alias=True), _password_material(request)
        )
    except ValueError as exc:
        raise ApiError(400, "INVALID_PASSWORD_ENCRYPTION", "Invalid password encryption.") from exc


# ---------------------------------------------------------------- 内部助手

def _user_dto(user: sqlite3.Row) -> dict[str, Any]:
    """蓝图 §6 通用 UserDTO；email_verified 由时间戳折成布尔值。"""
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "status": user["status"],
        "email_verified": user["email_verified_at"] is not None,
    }


def _check_password_policy(password: str) -> None:
    """口令策略：≥8 位且字母+数字（任务契约；不引入复杂度评分，保持可解释）。"""
    if (
        len(password) < 8
        or not any(c.isalpha() for c in password)
        or not any(c.isdigit() for c in password)
    ):
        raise ApiError(400, "WEAK_PASSWORD", MSG_PASSWORD_POLICY)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _password_matches(password_hash: str, password: str) -> bool:
    """校验口令的防御性包装。

    为什么不在 security.verify_password 之外再包一层都不行：旧算法哈希（如
    bcrypt）会触发 argon2-cffi 的 InvalidHashError，而它**不是** VerificationError
    的子类，security 的捕获列表盖不住（foundation 只读，不能去改它的 except）。
    对外语义不变——任何哈希异常都按"密码不正确"处理。
    """
    try:
        return verify_password(password_hash, password)
    except Exception:
        return False


def _deliver_mail(config: AppConfig, to: str, subject: str, body: str) -> str:
    """投递邮件；返回 "smtp"（已发出）/ "outbox"（未配置 SMTP，开发兜底）/ "failed"（SMTP 故障）。

    为什么 SMTP 故障不再 500：注册/重置账号本身是成功的，邮件只是投递环节，
    服务器不可达时让用户重试投递（resend 端点）比让整个注册失败更符合
    PRD-06 的韧性口径；故障时链接同样写入 outbox 存档，且不向响应回显令牌
    （避免生产环境验证链接经 API 泄露）。
    """
    if config.smtp_host:
        try:
            if config.smtp_secure:
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    config.smtp_host, config.smtp_port, timeout=10
                )
            else:
                server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
                server.starttls()  # 587 提交端口的常规握手
            try:
                if config.smtp_user:
                    server.login(config.smtp_user, config.smtp_pass)
                message = EmailMessage()
                message["From"] = config.mail_from
                message["To"] = to
                message["Subject"] = subject
                message.set_content(body)
                server.send_message(message)
            finally:
                server.quit()
            return "smtp"
        except Exception:
            # Never log the exception itself: SMTP failures can include supplied
            # connection details, and the body contains one-time URL tokens.
            logger.warning("SMTP delivery failed")
            if config.allow_dev_mail_outbox:
                # Development may retain the link for local test flows; production
                # must never turn a mail failure into a token-bearing local file.
                _write_outbox(config, to, subject, body)
            return "failed"
    if config.allow_dev_mail_outbox:
        # Development-only fallback: it makes offline verification practical but
        # is intentionally unavailable once production mode is selected.
        _write_outbox(config, to, subject, body)
        return "outbox"
    logger.error("SMTP is unavailable in production mode")
    return "failed"


def _write_outbox(config: AppConfig, to: str, subject: str, body: str) -> None:
    """把邮件内容追加写入本地发件箱日志（开发兜底与 SMTP 故障存档共用）。"""
    if not config.allow_dev_mail_outbox:
        # Keep the production restriction defensive even if a caller bypasses
        # _deliver_mail in the future.
        logger.error("Refused to write a production mail outbox")
        return
    outbox = Path(config.resolved_mail_outbox_path)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("a", encoding="utf-8") as fh:
        fh.write(f"[{utc_now_iso()}] To: {to} | Subject: {subject}\n{body}\n---\n")


def _create_token(conn: sqlite3.Connection, table: str, user_id: str, ttl: timedelta) -> str:
    """生成令牌并把 sha256 落库，返回原始令牌（只在此刻可见一次）。

    table 只允许本模块内部传入的两个固定表名，不存在注入面。
    """
    raw = generate_token()
    expires_at = (datetime.now(timezone.utc) + ttl).isoformat()
    conn.execute(
        f"INSERT INTO {table} (id, user_id, token_hash, expires_at, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, user_id, hash_token(raw), expires_at, utc_now_iso()),
    )
    return raw


def _consume_token(
    conn: sqlite3.Connection, table: str, raw_token: str
) -> sqlite3.Row | None:
    """按哈希查找未消费、未过期的令牌行；找到即标记消费并返回行。"""
    row = conn.execute(
        f"SELECT * FROM {table} WHERE token_hash = ? AND consumed_at IS NULL",
        (hash_token(raw_token),),
    ).fetchone()
    if row is None or row["expires_at"] <= utc_now_iso():
        return None
    conn.execute(
        f"UPDATE {table} SET consumed_at = ? WHERE id = ?", (utc_now_iso(), row["id"])
    )
    return row


def _send_verification_mail(
    conn: sqlite3.Connection, config: AppConfig, user: sqlite3.Row
) -> tuple[str | None, str]:
    """签发验证令牌并投递邮件；返回 (开发兜底令牌|None, 投递状态)。

    仅 "outbox"（未配置 SMTP 的开发模式）回显令牌；"failed" 不回显（防泄露），
    由调用方以 mail_delivered=false 告知用户改用重发。
    """
    raw = _create_token(conn, "email_verification_tokens", user["id"], _VERIFY_TOKEN_TTL)
    link = f"{config.public_origin}/verify-email?token={raw}"
    delivery = _deliver_mail(
        config,
        user["email"],
        "【标航智导】请验证你的邮箱",
        f"你好 {user['name']}：\n\n请点击以下链接完成邮箱验证（24 小时内有效）：\n{link}\n\n如非本人操作请忽略本邮件。",
    )
    conn.commit()
    return (raw if delivery == "outbox" and config.allow_dev_mail_outbox else None), delivery


def _create_session(
    conn: sqlite3.Connection,
    table: str,
    user_id: str,
    ttl_hours: int,
    request: Request,
) -> tuple[str, str]:
    """建会话行，返回 (原始会话令牌, 原始 CSRF 令牌)。

    会话令牌只存 sha256（泄露不可回推）；CSRF 令牌自 008 迁移起同时落
    原始值（csrf_token 列）与哈希（legacy 兼容列）——原始值落库是为了
    让 /api/auth/session 在会话期内反复返回同一枚令牌（多标签页不互顶），
    它本身就是发给该会话持有者的，不属于需要防回推的凭证。
    """
    raw_session = generate_token()
    raw_csrf = generate_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    conn.execute(
        f"INSERT INTO {table}"
        " (id, user_id, token_hash, csrf_token_hash, csrf_token, created_at, expires_at, ip, user_agent)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            user_id,
            hash_token(raw_session),
            hash_token(raw_csrf),
            raw_csrf,
            utc_now_iso(),
            expires_at,
            _client_ip(request),
            request.headers.get("user-agent"),
        ),
    )
    return raw_session, raw_csrf


def _set_session_cookie(
    response: Response, config: AppConfig, name: str, raw_token: str
) -> None:
    """统一会话 cookie 属性：HttpOnly + SameSite=Lax + Path=/（蓝图 §6.1）。"""
    response.set_cookie(
        name,
        raw_token,
        max_age=config.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        path="/",
        secure=config.secure_cookies,
    )


def _revoke_all_sessions(conn: sqlite3.Connection, user_id: str) -> None:
    """吊销用户在两张会话表里的全部有效会话（重置密码/禁用账号时调用）。"""
    now = utc_now_iso()
    for table in ("user_sessions", "admin_sessions"):
        conn.execute(
            f"UPDATE {table} SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, user_id),
        )


def _revoke_other_sessions(conn: sqlite3.Connection, current: CurrentUser) -> None:
    """Revoke every session except the one that authenticated this password change."""
    now = utc_now_iso()
    current_table = "admin_sessions" if current.is_admin_session else "user_sessions"
    for table in ("user_sessions", "admin_sessions"):
        if table == current_table:
            conn.execute(
                f"UPDATE {table} SET revoked_at = ? "
                "WHERE user_id = ? AND id != ? AND revoked_at IS NULL",
                (now, current.user["id"], current.session_id),
            )
        else:
            conn.execute(
                f"UPDATE {table} SET revoked_at = ? "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (now, current.user["id"]),
            )


# ---------------------------------------------------------------- 注册 / 历史邮箱链接兼容

@router.post("/api/auth/register", status_code=201)
def register(
    body: RegisterIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    password = _decrypt_auth_password(request, body.password_envelope)
    _check_password_policy(password)
    name = body.name.strip()
    if not name:
        raise ApiError(422, "VALIDATION_ERROR", "姓名不能为空")

    role = body.role or "student"
    if role not in ("student", "teacher"):
        # 系统管理员只能由管理员后台创建，绝不开放自助注册
        raise ApiError(403, "ROLE_NOT_ALLOWED", "该角色不支持自助注册，请联系系统管理员开通")

    email = body.email.lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        # 统一话术：不暴露该邮箱是否已验证（PRD-06 §3.4）
        raise ApiError(409, "EMAIL_EXISTS", MSG_DUPLICATE_EMAIL)

    now = utc_now_iso()
    user_id = uuid.uuid4().hex
    # 邮箱验证已取消为全局强制门槛；新账号直接进入可用状态，同时保留
    # 旧字段和兼容接口，避免历史客户端因 DTO 结构变化而失效。
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, school_id, email_verified_at,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 'active', NULL, ?, ?, ?)",
        (user_id, email, name, role, now, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at)"
        " VALUES (?, ?, 'argon2id', ?)",
        (user_id, hash_password(password), now),
    )
    # 注册不再通过发送验证邮件间接提交事务，必须在凭据落库后显式提交，
    # 否则下一次请求无法读取刚创建的账号和密码哈希。
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    result: dict[str, Any] = {
        "user": _user_dto(user),
        "message": "注册成功，请直接登录",
    }
    return result


@router.post("/api/auth/verify-email")
def verify_email(
    body: VerifyEmailIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    row = _consume_token(conn, "email_verification_tokens", body.token)
    if row is None:
        raise ApiError(400, "TOKEN_INVALID", "验证链接无效或已过期，请重新获取验证邮件")
    conn.execute(
        "UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?",
        (utc_now_iso(), utc_now_iso(), row["user_id"]),
    )
    conn.commit()
    return {"message": "邮箱验证成功，现在可以使用全部功能了"}


@router.post("/api/auth/resend-verification")
def resend_verification(
    current: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    user = current.user
    if user["email_verified_at"] is not None:
        raise ApiError(400, "ALREADY_VERIFIED", "邮箱已完成验证，无需重发")
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sent = conn.execute(
        "SELECT COUNT(*) AS n FROM email_verification_tokens"
        " WHERE user_id = ? AND created_at >= ?",
        (user["id"], since),
    ).fetchone()["n"]
    if sent >= _RESEND_LIMIT_PER_HOUR:
        raise ApiError(429, "RESEND_LIMITED", "验证邮件发送过于频繁，请一小时后再试")
    dev_token, delivery = _send_verification_mail(conn, get_config(), user)
    result: dict[str, Any] = {"message": "验证邮件已发送，请查收"}
    if dev_token is not None and get_config().allow_dev_mail_outbox:
        result["dev_verify_token"] = dev_token  # 开发兜底，见模块 docstring
    if delivery == "failed":
        result["mail_delivered"] = False
        result["message"] = "验证邮件发送失败，请稍后重试"
    return result


# ---------------------------------------------------------------- 登录 / 登出 / 会话

@router.post("/api/auth/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    config = get_config()
    password = _decrypt_auth_password(request, body.password_envelope)
    ip = _client_ip(request)
    email = body.email.lower()

    retry_after_seconds = security.ip_rate_limit_retry_after_seconds(conn, ip)
    if retry_after_seconds is not None:
        # Preserve the production threshold while returning an exact, safe
        # recovery interval that clients can turn into a disabled countdown.
        raise ApiError(
            429,
            "RATE_LIMITED",
            f"尝试过于频繁，请 {retry_after_seconds} 秒后再试",
            details={"retry_after_seconds": retry_after_seconds},
            headers={"Retry-After": str(retry_after_seconds)},
        )
    if security.is_login_locked(conn, email):
        raise ApiError(429, "LOGIN_LOCKED", security.MSG_ACCOUNT_LOCKED)

    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    credential = (
        conn.execute(
            "SELECT * FROM user_credentials WHERE user_id = ?", (user["id"],)
        ).fetchone()
        if user is not None
        else None
    )
    # _password_matches 对任何异常（含旧算法哈希不匹配）一律返回 False，
    # 对外只有"邮箱或密码不正确"，不暴露账号存在性与哈希细节
    password_ok = credential is not None and _password_matches(
        credential["password_hash"], password
    )
    if user is None or not password_ok:
        security.record_login_attempt(conn, email, ip, False)
        audit(
            conn,
            user if user is not None else None,
            "auth.login_failed",
            target_type="user",
            target_id=user["id"] if user is not None else None,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        raise ApiError(401, "INVALID_CREDENTIALS", MSG_INVALID_CREDENTIALS)

    if user["status"] != "active":
        security.record_login_attempt(conn, email, ip, False)
        audit(
            conn,
            user,
            "auth.login_failed",
            target_type="user",
            target_id=user["id"],
            after={"reason": "account_disabled"},
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        raise ApiError(403, "ACCOUNT_DISABLED", "账号已被禁用，如需帮助请联系管理员")

    security.record_login_attempt(conn, email, ip, True)
    ttl = config.session_ttl_hours
    if user["role"] == "system_admin":
        # 系统管理员签发双会话：管理端 cookie 用于 /api/admin/*，普通 cookie
        # 保留 Agent 等学生端能力（PRD-04 §5.1 矩阵允许管理员使用 Agent）
        raw_admin, raw_csrf = _create_session(conn, "admin_sessions", user["id"], ttl, request)
        raw_user, _ = _create_session(conn, "user_sessions", user["id"], ttl, request)
        _set_session_cookie(response, config, ADMIN_SESSION_COOKIE, raw_admin)
        _set_session_cookie(response, config, USER_SESSION_COOKIE, raw_user)
        csrf_for_client = raw_csrf  # csrf_protect 管理端会话优先，必须返回它的令牌
    else:
        raw_user, raw_csrf = _create_session(conn, "user_sessions", user["id"], ttl, request)
        _set_session_cookie(response, config, USER_SESSION_COOKIE, raw_user)
        csrf_for_client = raw_csrf
    conn.commit()
    audit(
        conn,
        user,
        "auth.login",
        target_type="user",
        target_id=user["id"],
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return {"user": _user_dto(user), "csrf_token": csrf_for_client}


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    now = utc_now_iso()
    for table, cookie in (
        ("admin_sessions", ADMIN_SESSION_COOKIE),
        ("user_sessions", USER_SESSION_COOKIE),
    ):
        token = request.cookies.get(cookie)
        if not token:
            continue
        session = _load_valid_session(conn, table, token)
        if session is None:
            continue
        conn.execute(
            f"UPDATE {table} SET revoked_at = ? WHERE id = ?", (now, session["id"])
        )
        audit(
            conn,
            session["user_id"],
            "auth.logout",
            target_type="user",
            target_id=session["user_id"],
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    conn.commit()
    # 无论服务端是否找到会话都清 cookie：让客户端一定能回到未登录态
    response.delete_cookie(USER_SESSION_COOKIE, path="/")
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return {"message": "已退出登录"}


@router.get("/api/auth/session")
def session_info(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    """返回当前会话的 {user, csrf_token}（管理端 cookie 优先）。

    CSRF 令牌在会话期内稳定：直接返回会话行上落库的原始令牌，不再轮换——
    旧轮换方案下两个标签页交替取会话会互相顶掉令牌（已发令牌随即失效）。
    仅当存量 legacy 会话（008 迁移前建立）没有原始令牌时，补发一枚并落库，
    之后同样保持稳定。
    """
    current = _load_any_session(request, conn)
    if current is None:
        raise ApiError(401, "UNAUTHORIZED", "请先登录")
    if current.csrf_token_raw:
        return {"user": _user_dto(current.user), "csrf_token": current.csrf_token_raw}
    # legacy 会话升级路径：补发原始令牌落库（哈希列同步更新，保持两列口径一致）
    raw_csrf = generate_token()
    table = "admin_sessions" if current.is_admin_session else "user_sessions"
    conn.execute(
        f"UPDATE {table} SET csrf_token = ?, csrf_token_hash = ? WHERE id = ?",
        (raw_csrf, hash_token(raw_csrf), current.session_id),
    )
    conn.commit()
    return {"user": _user_dto(current.user), "csrf_token": raw_csrf}


# ---------------------------------------------------------------- 找回 / 重置密码


@router.post("/api/auth/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str]:
    """Change the authenticated user's password after verifying the current one.

    The current session remains usable so the profile flow does not strand the user;
    all other sessions are revoked as credential-compromise containment.
    """
    current_password = _decrypt_auth_password(request, body.current_password_envelope)
    new_password = _decrypt_auth_password(request, body.new_password_envelope)
    credential = conn.execute(
        "SELECT password_hash FROM user_credentials WHERE user_id = ?",
        (current.user["id"],),
    ).fetchone()
    if credential is None or not _password_matches(credential["password_hash"], current_password):
        raise ApiError(400, "CURRENT_PASSWORD_INVALID", "原密码不正确")
    if current_password == new_password:
        raise ApiError(400, "PASSWORD_UNCHANGED", "新密码不能与原密码相同")
    _check_password_policy(new_password)
    conn.execute(
        "UPDATE user_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
        (hash_password(new_password), utc_now_iso(), current.user["id"]),
    )
    _revoke_other_sessions(conn, current)
    conn.commit()
    audit(
        conn,
        current.user,
        "auth.password_change",
        target_type="user",
        target_id=current.user["id"],
    )
    return {"message": "密码修改成功，其他设备已退出登录"}

@router.patch("/api/auth/profile")
def update_own_profile(
    body: UpdateProfileIn,
    current: CurrentUser = Depends(csrf_protect),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """三类账号共用的自助改名（csrf_protect 同时覆盖用户会话与管理端会话）。

    放在 auth 而非 profile.py：profile 路由整体挂在学生门户角色门上
    （require_student_portal_user），而改名是学生/教师/管理员共有的身份操作，
    与学习画像无关。
    """
    name = body.name.strip()
    # min_length=1 在 strip 之前判定，纯空白名需要显式拦截
    if not name:
        raise ApiError(422, "VALIDATION_ERROR", "姓名不能为空")
    user_id = current.user["id"]
    conn.execute(
        "UPDATE users SET name = ?, updated_at = ? WHERE id = ?",
        (name, utc_now_iso(), user_id),
    )
    conn.commit()
    audit(
        conn,
        current.user,
        "auth.update_name",
        target_type="user",
        target_id=user_id,
        before={"name": current.user["name"]},
        after={"name": name},
    )
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"user": _user_dto(row)}

@router.post("/api/auth/forgot-password")
def forgot_password(
    body: ForgotPasswordIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    config = get_config()
    email = body.email.lower()
    # 统一话术：无论邮箱是否存在都返回相同消息（PRD-06 §3.4 不暴露账号存在性）
    result: dict[str, Any] = {"message": "如果该邮箱已注册，重置邮件已发送，请查收"}
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        return result
    raw = _create_token(conn, "password_reset_tokens", user["id"], _RESET_TOKEN_TTL)
    link = f"{config.public_origin}/reset-password?token={raw}"
    delivery = _deliver_mail(
        config,
        user["email"],
        "【标航智导】重置你的密码",
        f"你好 {user['name']}：\n\n请点击以下链接重置密码（30 分钟内有效）：\n{link}\n\n如非本人操作请忽略本邮件。",
    )
    conn.commit()
    if delivery == "outbox" and config.allow_dev_mail_outbox:
        result["dev_reset_token"] = raw  # 开发兜底，见模块 docstring
    elif delivery == "failed":
        result["mail_delivered"] = False
    return result


@router.post("/api/auth/reset-password")
def reset_password(
    body: ResetPasswordIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    # Decrypt before consuming the one-time reset token so malformed browser
    # payloads cannot burn a valid link and force the user to request another.
    password = _decrypt_auth_password(request, body.password_envelope)
    _check_password_policy(password)
    row = _consume_token(conn, "password_reset_tokens", body.token)
    if row is None:
        raise ApiError(400, "TOKEN_INVALID", "重置链接无效或已过期，请重新发起找回密码")
    conn.execute(
        "UPDATE user_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
        (hash_password(password), utc_now_iso(), row["user_id"]),
    )
    # 重置即视为凭证泄露处置：吊销该用户所有端全部会话
    _revoke_all_sessions(conn, row["user_id"])
    conn.commit()
    audit(
        conn,
        row["user_id"],
        "auth.password_reset",
        target_type="user",
        target_id=row["user_id"],
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"message": "密码已重置，请使用新密码登录"}
