"""健康检查端点冒烟：应用可创建、lifespan 迁移跑通、/api/health 200。"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bhzd_py import __version__
from bhzd_py.app import create_app
from bhzd_py.config import DEVELOPMENT_MAIL_FROM, get_config, reset_config_cache


def _set_valid_production_env(monkeypatch, database_path: str) -> None:
    """Supply deliberately fake-but-complete values without touching real services."""
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("BHZD_DATABASE_PATH", database_path)
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    monkeypatch.setenv("BHZD_TEACHER_INVITE_CODE", "test-only-private-teacher-invite")
    monkeypatch.setenv("BHZD_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BHZD_SMTP_PORT", "2525")
    monkeypatch.setenv("BHZD_MAIL_FROM", "BHZD Test <noreply@example.test>")
    monkeypatch.setenv("BHZD_PUBLIC_ORIGIN", "https://app.example.test")
    monkeypatch.setenv("BHZD_CORS_ORIGINS", "https://app.example.test")
    reset_config_cache()


def test_health_endpoint(tmp_db_path):
    # 用上下文管理器进 lifespan：顺带验证启动迁移在临时库上无报错
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_production_startup_fails_closed_before_migrations(tmp_db_path, monkeypatch):
    """An incomplete production profile must not create or migrate a database."""
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("BHZD_DATABASE_PATH", tmp_db_path)
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", "")
    monkeypatch.setenv("BHZD_TEACHER_INVITE_CODE", "bhzd-teacher-2026")
    monkeypatch.setenv("BHZD_SMTP_HOST", "")
    monkeypatch.setenv("BHZD_MAIL_FROM", "")
    monkeypatch.setenv("BHZD_PUBLIC_ORIGIN", "http://127.0.0.1:5173")
    monkeypatch.setenv("BHZD_CORS_ORIGINS", "http://127.0.0.1:5173")
    reset_config_cache()

    with pytest.raises(ValueError, match="Invalid production configuration"):
        with TestClient(create_app()):
            pass
    assert not Path(tmp_db_path).exists()
    reset_config_cache()


def test_valid_production_profile_starts_and_uses_secure_cookie_policy(tmp_db_path, monkeypatch):
    """A complete explicit production profile remains startable without SMTP traffic."""
    _set_valid_production_env(monkeypatch, tmp_db_path)
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
    assert get_config().secure_cookies is True
    reset_config_cache()


def test_production_rejects_the_development_mail_sender(tmp_db_path, monkeypatch):
    """Copying the local mail sender cannot silently satisfy production validation."""
    _set_valid_production_env(monkeypatch, tmp_db_path)
    monkeypatch.setenv("BHZD_MAIL_FROM", DEVELOPMENT_MAIL_FROM)
    reset_config_cache()

    with pytest.raises(ValueError, match="BHZD_MAIL_FROM"):
        with TestClient(create_app()):
            pass
    reset_config_cache()
