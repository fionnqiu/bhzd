"""安全基元测试：argon2id、AES-256-GCM、base_url 校验（NF9）、限流/锁定（NF5）。"""

from __future__ import annotations

import base64
import secrets

import pytest

from bhzd_py.db import apply_migrations, connect
from bhzd_py.security import (
    create_password_encryption_material,
    decrypt_password_envelope,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    ip_rate_limit_retry_after_seconds,
    is_ip_rate_limited,
    is_login_locked,
    load_encryption_key,
    record_login_attempt,
    token_hash_matches,
    validate_provider_base_url,
    verify_password,
)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def test_argon2_roundtrip():
    digest = hash_password("S3cret!密码")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, "S3cret!密码") is True
    assert verify_password(digest, "wrong-password") is False


def test_aes_gcm_roundtrip_and_wrong_key():
    key = secrets.token_bytes(32)
    token = encrypt_secret("sk-live-provider-key", key)
    assert decrypt_secret(token, key) == "sk-live-provider-key"
    # GCM 的完整性校验：错误密钥必须在解密时直接失败，而不是解出乱码
    with pytest.raises(Exception):
        decrypt_secret(token, secrets.token_bytes(32))


def test_encryption_key_parsing():
    raw = secrets.token_bytes(32)
    assert load_encryption_key(raw.hex()) == raw
    assert load_encryption_key(base64.b64encode(raw).decode()) == raw
    with pytest.raises(ValueError):
        load_encryption_key("not-a-key")
    with pytest.raises(ValueError):
        load_encryption_key(base64.b64encode(b"too-short").decode())


def test_password_envelope_roundtrip_and_rejects_tampering():
    """The client-wire encryption has one safe failure mode for bad inputs."""
    material = create_password_encryption_material()
    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, b"Passw0rd1", None)
    encrypted_key = material.private_key.public_key().encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    envelope = {
        "keyId": material.key_id,
        "encryptedKey": base64.b64encode(encrypted_key).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    assert decrypt_password_envelope(envelope, material) == "Passw0rd1"

    envelope["ciphertext"] = "not-base64"
    with pytest.raises(ValueError, match="Invalid password encryption envelope"):
        decrypt_password_envelope(envelope, material)


def test_token_hashing_and_compare():
    assert token_hash_matches(hash_token("abc"), "abc") is True
    assert token_hash_matches(hash_token("abc"), "abd") is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "https://spark-api.xf-yun.com/v3.5/chat",
        # 自定义端口明确放行：很多推理网关不用 80/443（见 security 模块注释）
        "http://gateway.example.com:8080/openai",
    ],
)
def test_base_url_accepts_public_endpoints(url):
    assert validate_provider_base_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:11434/v1",
        "http://0.0.0.0:9000",
        "http://10.1.2.3",
        "http://172.16.0.8",
        "http://192.168.1.10",
        # 云元数据地址是 SSRF 的头号目标，必须拦
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com",
        "not-a-url",
        "https://foo.localhost",
    ],
)
def test_base_url_rejects_unsafe_endpoints(url):
    message = validate_provider_base_url(url)
    assert message is not None
    assert isinstance(message, str) and message  # 面向用户的中文消息


def test_login_rate_limit_and_lockout(tmp_db_path):
    conn = connect(tmp_db_path)
    try:
        apply_migrations(conn)

        # 同一 IP 一分钟内 5 次尝试触发限流
        for _ in range(4):
            record_login_attempt(conn, "a@b.c", "1.2.3.4", False)
        assert is_ip_rate_limited(conn, "1.2.3.4") is False
        record_login_attempt(conn, "a@b.c", "1.2.3.4", False)
        assert is_ip_rate_limited(conn, "1.2.3.4") is True
        retry_after = ip_rate_limit_retry_after_seconds(conn, "1.2.3.4")
        # The helper is intentionally bounded to the same one-minute window as
        # the guard, so a client can safely use it for a countdown.
        assert retry_after is not None and 1 <= retry_after <= 60
        assert ip_rate_limit_retry_after_seconds(conn, "5.6.7.8") is None
        assert is_ip_rate_limited(conn, "5.6.7.8") is False  # 其他 IP 不受牵连

        # 连续失败 10 次锁定 15 分钟；一次成功登录即解除历史失败计数
        for _ in range(10):
            record_login_attempt(conn, "victim@bhzd.local", None, False)
        assert is_login_locked(conn, "victim@bhzd.local") is True
        record_login_attempt(conn, "victim@bhzd.local", None, True)
        assert is_login_locked(conn, "victim@bhzd.local") is False
        assert is_login_locked(conn, "other@bhzd.local") is False
    finally:
        conn.close()
