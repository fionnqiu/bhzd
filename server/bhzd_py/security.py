"""安全基元：口令散列、配置加密、令牌、登录限流/锁定、provider base_url 校验。

关键决策（为什么）：
- 口令用 argon2id：蓝图 §5 注释与 NF 系列要求；argon2-cffi 的 PasswordHasher
  默认参数即为 argon2id。
- provider API Key 用 AES-256-GCM：GCM 自带完整性校验，篡改密文会在解密时
  直接报错（NF2"明文永不出库/日志"的存储侧落实）。
- 所有令牌（会话/CSRF/验证/重置）只落 sha256 哈希：库泄露时令牌不可回推，
  比对用 hmac.compare_digest 防时序侧信道。
- base_url 校验是 NF9 的 SSRF 防线：拒绝内网/环回/云元数据地址，防止管理员
  误配或恶意配置把 API Key 转发到内网服务。注意这里**不做 DNS 解析**（避免
  启动期阻塞与 DNS rebinding 之外的可用性问题），只拦字面 IP 与已知主机名；
  非常用端口（非 80/443）不拦截，仅在校验说明中标注。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import logging
import math
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerificationError, VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import utc_now_iso

logger = logging.getLogger(__name__)

# ---- 登录限流/锁定参数（NF5 / 蓝图 §6.1）----
# 登录限流阈值（NF5）：默认 5 次/分/IP；测试与演示环境可用环境变量放宽，
# 生产不设置即为安全默认值。用模块级常量形式保留，便于测试 monkeypatch。
RATE_LIMIT_ATTEMPTS_PER_MINUTE = int(os.environ.get("BHZD_LOGIN_RATE_LIMIT_PER_MINUTE", "5"))
LOCKOUT_THRESHOLD_FAILURES = 10
LOCKOUT_DURATION_MINUTES = 15

MSG_TOO_MANY_ATTEMPTS = "尝试过于频繁，请一分钟后再试"
MSG_ACCOUNT_LOCKED = f"连续失败次数过多，账号已锁定 {LOCKOUT_DURATION_MINUTES} 分钟，请稍后再试"

_password_hasher = PasswordHasher()  # 默认即 argon2id

# 进程内缓存的临时开发密钥：保证同一次进程内加解密自洽，重启即失效
_ephemeral_key: bytes | None = None


# ---------------------------------------------------------------- 口令散列

def hash_password(password: str) -> str:
    """argon2id 散列口令。"""
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验口令；任何异常（含哈希损坏）一律视为不通过，不向外泄露细节。"""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, Argon2Error):
        return False


# ---------------------------------------------------------------- 配置加密

def load_encryption_key(raw: str | None) -> bytes:
    """把 BHZD_CONFIG_ENCRYPTION_KEY（hex 或 base64 的 32B）解析为密钥字节。

    未配置时生成进程级临时密钥并打出醒目告警——仅用于开发/演示，重启后旧
    密文将无法解密，生产环境必须显式配置。
    """
    global _ephemeral_key
    if raw:
        key: bytes | None = None
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            try:
                key = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                key = None
        if key is None or len(key) != 32:
            raise ValueError(
                "BHZD_CONFIG_ENCRYPTION_KEY 必须是 hex 或 base64 编码的 32 字节密钥"
            )
        return key
    if _ephemeral_key is None:
        _ephemeral_key = secrets.token_bytes(32)
        logger.warning(
            "未配置 BHZD_CONFIG_ENCRYPTION_KEY：已生成临时开发密钥。"
            "重启后已加密的 provider 密钥将无法解密，生产环境请务必配置固定密钥！"
        )
    return _ephemeral_key


def encrypt_secret(plaintext: str, key: bytes) -> str:
    """AES-256-GCM 加密，返回 base64(nonce || 密文) 便于落库存储。"""
    nonce = secrets.token_bytes(12)  # GCM 标准 96 位 nonce
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(token: str, key: bytes) -> str:
    """解密 `encrypt_secret` 的产物；密钥错误或密文被篡改会抛异常。"""
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


# ---------------------------------------------------------------- 请求口令信封

@dataclass(frozen=True)
class PasswordEncryptionMaterial:
    """The short-lived server key pair that unwraps browser password envelopes.

    This is deliberately separate from ``config_encryption_key``.  The latter
    encrypts provider credentials at rest; this material only keeps an ordinary
    user's password out of browser request JSON before TLS terminates it.
    """

    key_id: str
    public_key_pem: str
    private_key: rsa.RSAPrivateKey


def create_password_encryption_material() -> PasswordEncryptionMaterial:
    """Create the RSA half of the hybrid password-envelope protocol.

    RSA only wraps a random AES key because encrypting the password itself with
    RSA would impose a brittle size limit and needlessly be more expensive.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_id = base64.urlsafe_b64encode(hashlib.sha256(public_der).digest()[:16]).decode("ascii").rstrip("=")
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return PasswordEncryptionMaterial(
        key_id=key_id,
        public_key_pem=public_key_pem,
        private_key=private_key,
    )


def decrypt_password_envelope(
    envelope: dict[str, str], material: PasswordEncryptionMaterial
) -> str:
    """Decrypt a browser ``RSA-OAEP-256 + AES-GCM`` password envelope.

    All malformed, stale, or tampered envelopes intentionally collapse to one
    error.  That avoids revealing key rotation or cryptographic details through
    an authentication endpoint while preserving a clear client retry path.
    """
    if envelope.get("keyId") != material.key_id:
        raise ValueError("Invalid password encryption envelope.")
    try:
        encrypted_key = base64.b64decode(envelope["encryptedKey"], validate=True)
        iv = base64.b64decode(envelope["iv"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        aes_key = material.private_key.decrypt(
            encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        if len(aes_key) != 32 or len(iv) != 12:
            raise ValueError("Invalid password encryption envelope.")
        plaintext = AESGCM(aes_key).decrypt(iv, ciphertext, None)
        return plaintext.decode("utf-8")
    except (KeyError, TypeError, ValueError, binascii.Error, InvalidTag, UnicodeDecodeError) as exc:
        raise ValueError("Invalid password encryption envelope.") from exc


# ---------------------------------------------------------------- 令牌

def generate_token() -> str:
    """生成高熵随机令牌（会话/CSRF/验证/重置通用）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """令牌 sha256 十六进制摘要：入库/比对只用它，原始令牌永不落库。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_hash_matches(stored_hash: str, presented_token: str) -> bool:
    """恒定时间比对令牌哈希，防时序侧信道。"""
    return hmac.compare_digest(stored_hash, hash_token(presented_token))


# ---------------------------------------------------------------- 登录限流/锁定

def record_login_attempt(
    conn: sqlite3.Connection, email: str, ip: str | None, success: bool
) -> None:
    """记录一次登录尝试（login_attempts 表，NF5 审计与限流的数据源）。"""
    conn.execute(
        "INSERT INTO login_attempts (email, ip, success, created_at) VALUES (?, ?, ?, ?)",
        (email, ip, 1 if success else 0, utc_now_iso()),
    )
    conn.commit()


def is_ip_rate_limited(conn: sqlite3.Connection, ip: str | None) -> bool:
    """同一 IP 一分钟内尝试超过 5 次即限流（成功失败都计数，防探测）。"""
    if not ip:
        return False
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE ip = ? AND created_at >= ?",
        (ip, since),
    ).fetchone()
    return row["n"] >= RATE_LIMIT_ATTEMPTS_PER_MINUTE


def ip_rate_limit_retry_after_seconds(conn: sqlite3.Connection, ip: str | None) -> int | None:
    """Return the bounded wait for an IP rate limit, or ``None`` when clear.

    The count and expiry lookup use the same one-minute window as the guard so
    the browser never receives a generic wait message that disagrees with the
    next allowed login attempt.  Malformed historical timestamps fail closed
    to a short full window instead of leaking an implementation error.
    """

    if not ip:
        return None
    now = datetime.now(timezone.utc)
    since = (now - timedelta(minutes=1)).isoformat()
    rows = conn.execute(
        "SELECT created_at FROM login_attempts WHERE ip = ? AND created_at >= ? "
        "ORDER BY created_at ASC",
        (ip, since),
    ).fetchall()
    if len(rows) < RATE_LIMIT_ATTEMPTS_PER_MINUTE:
        return None
    try:
        oldest = datetime.fromisoformat(str(rows[0]["created_at"]))
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        remaining = (oldest.astimezone(timezone.utc) + timedelta(minutes=1) - now).total_seconds()
    except (TypeError, ValueError, IndexError):
        return 60
    return max(1, min(60, math.ceil(remaining)))


def is_login_locked(conn: sqlite3.Connection, email: str) -> bool:
    """该邮箱最近 15 分钟内失败满 10 次即锁定。

    注意：以"最近一次成功之后"的失败数计，避免历史旧失败造成永久误锁。
    """
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    ).isoformat()
    last_success = conn.execute(
        "SELECT MAX(created_at) AS t FROM login_attempts WHERE email = ? AND success = 1",
        (email,),
    ).fetchone()["t"]
    window_start = max(since, last_success or "")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_attempts "
        "WHERE email = ? AND success = 0 AND created_at >= ?",
        (email, window_start),
    ).fetchone()
    return row["n"] >= LOCKOUT_THRESHOLD_FAILURES


# ---------------------------------------------------------------- base_url 安全校验（NF9）

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """环回/私有(RFC1918)/链路本地(含 169.254.169.254)/未指定/组播一律拒绝。"""
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def validate_provider_base_url(base_url: str) -> str | None:
    """校验 provider base_url 是否允许出网调用。

    返回 `None` 表示通过；否则返回面向用户的中文错误消息。
    仅允许 http/https；拒绝环回、RFC1918 私网、链路本地（含云元数据地址
    169.254.169.254）与已知本机主机名。非 80/443 的自定义端口**允许**，
    因为很多推理网关使用自定义端口，误伤比放行更影响可用性。
    """
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in ("http", "https"):
        return "接口地址仅支持 http 或 https 协议"
    hostname = parsed.hostname
    if not hostname:
        return "接口地址缺少有效的主机名"
    host = hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return "接口地址不允许指向本机（localhost），请填写公网服务地址"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 非字面 IP 的域名：不做 DNS 解析（见模块 docstring），仅放行
        return None
    if _is_forbidden_ip(ip):
        return "接口地址不允许指向内网、环回或链路本地地址（含云元数据地址）"
    return None
