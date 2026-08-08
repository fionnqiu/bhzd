"""pytest 公共夹具：每测试独立临时数据库，避免污染仓库 var/ 与彼此状态。"""

from __future__ import annotations

import pytest

from bhzd_py.config import reset_config_cache


@pytest.fixture()
def tmp_db_path(tmp_path, monkeypatch):
    """把 BHZD_DATABASE_PATH 指向 tmp_path 下的新库，并重载配置缓存。

    为什么走环境变量而不是直接传路径：config/seed/app 全链路都以环境为
    唯一事实来源，夹具沿同一条路注入，测到的才是真实解析行为。
    """
    path = str(tmp_path / "test.sqlite")
    monkeypatch.setenv("BHZD_DATABASE_PATH", path)
    reset_config_cache()
    yield path
    reset_config_cache()


@pytest.fixture()
def clean_admin_env(monkeypatch):
    """屏蔽 .env.local 里可能存在的管理员/密钥变量，保证 seed 测试可重复。"""
    monkeypatch.setenv("BHZD_ADMIN_PASSWORD", "")
    monkeypatch.setenv("BHZD_ADMIN_PASSWORD_HASH", "")
    monkeypatch.setenv("BHZD_ADMIN_EMAIL", "admin@bhzd.local")
    reset_config_cache()
    yield
    reset_config_cache()
