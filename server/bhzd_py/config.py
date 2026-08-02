"""应用配置（蓝图 §3）：pydantic-settings，环境变量统一 `BHZD_` 前缀。

设计要点（为什么这么做）：
- 仓库根由包路径推导（server/bhzd_py/config.py → 上两级），保证无论从哪个
  工作目录启动，数据目录/数据库默认路径都稳定指向 `<repo>/data` 与 `<repo>/var`。
- `BHZD_DATABASE_PATH` 是新的规范名，优先级高于旧名 `BHZD_DATABASE_URL`
  （sqlite:/// 形式仅作兼容回退），这样测试用 `BHZD_DATABASE_PATH` 覆盖时
  不会被 .env.local 里的旧变量意外抢走。
- 相对路径一律相对仓库根解析，避免 cwd 差异导致的"幽灵库文件"。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# server/bhzd_py/config.py → parents[2] 为仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]

# This value is intentionally public for local demos.  Production validation
# rejects it so a copied example file can never silently open teacher signup.
DEVELOPMENT_TEACHER_INVITE_CODE = "bhzd-teacher-2026"
# A copied local sender must not become a production identity merely because an
# SMTP host was supplied.  Development can use it for offline outbox flows.
DEVELOPMENT_MAIL_FROM = "标航智导 <noreply@bhzd.local>"


def _resolve(path: str) -> str:
    """把相对路径解析为相对仓库根的绝对路径；`:memory:` 原样保留。"""
    if path == ":memory:":
        return path
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p)


def _is_https_origin(value: str) -> bool:
    """Return whether *value* is an origin suitable for production CORS.

    Cookie-authenticated cross-origin calls must name a concrete HTTPS origin.
    Accepting a path, wildcard, or credentials here would make the deployment
    policy ambiguous and can accidentally widen the browser trust boundary.
    """
    parsed = urlparse(value.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and parsed.path in ("", "/")
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and "*" not in parsed.netloc
    )


class AppConfig(BaseSettings):
    """运行配置；所有字段均可被同名大写、`BHZD_` 前缀的环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_prefix="BHZD_",
        # 仓库根的 .env/.env.local 是本地开发约定；环境变量优先级高于文件
        env_file=(str(REPO_ROOT / ".env"), str(REPO_ROOT / ".env.local")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    host: str = "127.0.0.1"
    port: int = 8787
    public_origin: str = "http://127.0.0.1:5173"  # 旧名 BHZD_PUBLIC_ORIGIN，沿用
    cors_origins: str = ""  # 逗号分隔；空 = 仅放行 public_origin（默认同源策略）

    # ---- 存储 ----
    database_path: str = ""  # BHZD_DATABASE_PATH；空 = <repo>/var/bhzd.sqlite
    database_url: str = ""  # 旧名 BHZD_DATABASE_URL（sqlite:///...），仅兼容回退
    data_dir: str = ""  # BHZD_DATA_DIR；空 = <repo>/data
    upload_dir: str = ""  # BHZD_UPLOAD_DIR；空 = <repo>/var/uploads
    mail_outbox_path: str = ""  # 空 = <repo>/var/mail_outbox.log
    vector_store_url: str = ""  # 旧名保留：自定义向量库预留位

    # ---- 密钥与初始管理员 ----
    config_encryption_key: str = ""  # hex 或 base64 的 32B；空 = 开发临时 key（security 模块告警）
    admin_email: str = "admin@bhzd.local"
    admin_password: str = ""  # 空 = seed 时生成随机密码并打印一次
    admin_password_hash: str = ""  # 旧名 BHZD_ADMIN_PASSWORD_HASH，优先于明文密码

    # ---- 邮件（缺 SMTP 时验证/重置链接写 mail_outbox）----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_secure: bool = False
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_from: str = DEVELOPMENT_MAIL_FROM

    # ---- 注册 ----
    # 教师自注册邀请码（学生注册不需要）。默认值仅用于开发/演示，
    # 生产环境必须通过 BHZD_TEACHER_INVITE_CODE 覆盖为私有值，否则任何人都能注册教师。
    teacher_invite_code: str = DEVELOPMENT_TEACHER_INVITE_CODE

    # ---- 行为开关 ----
    demo_mode: bool = False
    session_ttl_hours: int = 72

    # NODE_ENV 不带 BHZD_ 前缀，是旧栈沿用名，单独映射
    node_env: str = Field(default="development", validation_alias="NODE_ENV")

    # ---- 解析后的派生属性 ----

    @property
    def resolved_database_path(self) -> str:
        """数据库文件最终路径：BHZD_DATABASE_PATH > 旧 BHZD_DATABASE_URL > 默认。"""
        if self.database_path:
            return _resolve(self.database_path)
        if self.database_url.startswith("sqlite:///"):
            return _resolve(self.database_url[len("sqlite:///"):])
        return str(REPO_ROOT / "var" / "bhzd.sqlite")

    @property
    def resolved_data_dir(self) -> str:
        return _resolve(self.data_dir) if self.data_dir else str(REPO_ROOT / "data")

    @property
    def resolved_upload_dir(self) -> str:
        return _resolve(self.upload_dir) if self.upload_dir else str(REPO_ROOT / "var" / "uploads")

    @property
    def resolved_mail_outbox_path(self) -> str:
        if self.mail_outbox_path:
            return _resolve(self.mail_outbox_path)
        return str(REPO_ROOT / "var" / "mail_outbox.log")

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS 放行源列表；默认同源部署只需放行前端开发源。"""
        raw = self.cors_origins.strip()
        if raw:
            return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
        return [self.public_origin.rstrip("/")]

    @property
    def secure_cookies(self) -> bool:
        """生产环境才给会话 cookie 加 Secure 属性。"""
        return self.is_production

    @property
    def is_production(self) -> bool:
        """Normalize the legacy NODE_ENV spelling before applying safeguards."""
        return self.node_env.strip().lower() == "production"

    @property
    def allow_dev_mail_outbox(self) -> bool:
        """Outbox and token echoes are development conveniences, never production."""
        return not self.is_production

    def validate_runtime_configuration(self) -> None:
        """Fail closed before migrations when a production safety prerequisite is absent.

        The application intentionally keeps permissive defaults for isolated local
        development.  A production process must instead be explicit about every
        secret-bearing or browser-facing boundary so a copied `.env.example`
        cannot become a deployable-but-insecure configuration.
        """
        if not self.is_production:
            return

        errors: list[str] = []
        if not self.config_encryption_key.strip():
            errors.append("BHZD_CONFIG_ENCRYPTION_KEY is required")
        else:
            # Import lazily to keep configuration usable in standalone tooling and
            # to reuse the exact 32-byte parsing rules used for provider secrets.
            from .security import load_encryption_key

            try:
                load_encryption_key(self.config_encryption_key)
            except ValueError:
                errors.append("BHZD_CONFIG_ENCRYPTION_KEY must encode 32 bytes")

        invite = self.teacher_invite_code.strip()
        if (
            len(invite) < 16
            or invite == DEVELOPMENT_TEACHER_INVITE_CODE
        ):
            errors.append("BHZD_TEACHER_INVITE_CODE must be a private value of at least 16 characters")

        if not self.smtp_host.strip():
            errors.append("BHZD_SMTP_HOST is required")
        if not self.mail_from.strip() or self.mail_from.strip() == DEVELOPMENT_MAIL_FROM:
            errors.append("BHZD_MAIL_FROM must be an explicit production sender")

        if not _is_https_origin(self.public_origin):
            errors.append("BHZD_PUBLIC_ORIGIN must be a concrete HTTPS origin")
        for origin in self.cors_origin_list:
            if not _is_https_origin(origin):
                errors.append("BHZD_CORS_ORIGINS must contain only concrete HTTPS origins")
                break

        if errors:
            # Do not include any supplied values: this error reaches process logs
            # and must remain safe even when a secret was malformed.
            raise ValueError("Invalid production configuration: " + "; ".join(errors))


@lru_cache
def get_config() -> AppConfig:
    """进程级配置单例；测试改环境变量后须调 `reset_config_cache()`。"""
    return AppConfig()


def reset_config_cache() -> None:
    """清掉配置缓存（测试隔离用；生产代码不应调用）。"""
    get_config.cache_clear()


def apply_environ(source: dict[str, str]) -> None:
    """以显式字典覆盖环境变量并重载配置（seed/脚本入口用）。"""
    for key, value in source.items():
        os.environ[key] = value
    reset_config_cache()
