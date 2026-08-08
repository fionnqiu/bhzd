"""系统管理路由（蓝图 §6.6，PRD-04）：仅 system_admin + 管理端会话可访问。

关键决策（为什么）：
- 读取端点用 get_admin_user；所有变更端点用 _admin_csrf（CSRF 校验 + 管理端
  会话 + system_admin 三重校验合一），与蓝图 §4"变更类请求必须带
  x-csrf-token"对齐。
- Provider DTO 永不携带 api_key：只有 api_key_set 布尔位（PRD-06 §3.3"API
  Key 明文仅录入时可见一次"）。审计 before/after 也先经 DTO 脱敏。
- 同角色（primary/fallback/embedding/rerank）至多一个 provider：set-role
  与创建/更新里的角色赋值都在同一事务里先清后设，避免并发下出现两个主模型。
- 指标端点（PRD-06 §13.1）全部用 SQL 诚实计算：无数据的指标返回 null 并
  在 note 里说明，绝不编造数字。
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..agent import providers
from ..alerts import evaluate_alerts
from ..audit import audit
from ..db import utc_now_iso
from ..deps import CurrentUser, csrf_protect, get_admin_user, get_db
from ..errors import ApiError
from ..security import (
    encrypt_secret,
    hash_password,
    load_encryption_key,
    validate_provider_base_url,
)
from ..config import get_config

router = APIRouter()

_PROTOCOLS = ("xunfei_xingchen", "xunfei_spark", "chat_completions", "anthropic_messages")
_PROVIDER_ROLES = ("primary", "fallback", "embedding", "rerank", "none")
_USER_ROLES = ("student", "teacher", "content_admin", "system_admin")


def _admin_csrf(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> CurrentUser:
    """变更端点组合校验：CSRF 令牌 + 管理端会话 + system_admin 角色。"""
    current = csrf_protect(request, conn)
    if not current.is_admin_session or current.user["role"] != "system_admin":
        # /api/admin/* 仅认管理端会话（蓝图 §4 会话隔离）
        raise ApiError(403, "FORBIDDEN", "需要系统管理员权限")
    return current


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ================================================================ 模型供应商

def _provider_dto(row: sqlite3.Row) -> dict[str, Any]:
    """Provider 对外 DTO：密钥永不回显，只给 api_key_set 布尔位。"""
    last_test: dict[str, Any] | None = None
    if row["last_test_json"]:
        try:
            last_test = json.loads(row["last_test_json"])
        except json.JSONDecodeError:
            last_test = None
    try:
        extra = json.loads(row["extra_json"] or "{}")
    except json.JSONDecodeError:
        extra = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "protocol": row["protocol"],
        "base_url": row["base_url"],
        "model": row["model"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "timeout_seconds": row["timeout_seconds"],
        "extra": extra,
        "api_key_set": True,
        "last_test": last_test,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_provider_or_404(conn: sqlite3.Connection, provider_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM provider_configs WHERE id = ?", (provider_id,)
    ).fetchone()
    if row is None:
        raise ApiError(404, "PROVIDER_NOT_FOUND", "供应商配置不存在")
    return row


def _assign_role_exclusive(conn: sqlite3.Connection, provider_id: str, role: str) -> None:
    """把角色独占地赋给指定 provider：同角色其它行先降为 none（同事务）。"""
    now = utc_now_iso()
    if role != "none":
        conn.execute(
            "UPDATE provider_configs SET role = 'none', updated_at = ? WHERE role = ? AND id != ?",
            (now, role, provider_id),
        )
    conn.execute(
        "UPDATE provider_configs SET role = ?, updated_at = ? WHERE id = ?",
        (role, now, provider_id),
    )


class ProviderCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    protocol: str
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=500)
    role: str = "none"
    enabled: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    extra: dict[str, Any] = Field(default_factory=dict)


class ProviderUpdateIn(BaseModel):
    """更新时 api_key 可省略：省略或空串表示不更换密钥。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    protocol: str | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = None
    role: str | None = None
    enabled: bool | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    extra: dict[str, Any] | None = None


class ProviderModelDiscoveryIn(BaseModel):
    """One-shot credentials used to populate the new-provider model selector.

    This deliberately excludes model, role, and persistence fields: discovery
    must validate an administrator's current form without creating a provider
    row or retaining the API key in any audit payload.
    """

    model_config = ConfigDict(extra="forbid")

    # Keep sensitive input opaque until the route validates it. The shared
    # RequestValidationError handler logs rejected values, which would be an
    # unacceptable path for a malformed API key.
    protocol: Any
    base_url: Any
    api_key: Any


class ProviderTransientTestIn(BaseModel):
    """Unsaved connection values used only for a bounded live smoke check.

    ``Any`` keeps FastAPI's rejected-request logging path from coercing or
    reflecting an API key before the route can validate it as opaque input.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: Any
    base_url: Any
    api_key: Any
    model: Any
    role: Any = "none"


class SetRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str


def _validate_protocol_role(protocol: str, role: str) -> None:
    if protocol not in _PROTOCOLS:
        raise ApiError(400, "INVALID_PROTOCOL", "不支持的协议类型，可选：xunfei_xingchen / xunfei_spark / chat_completions / anthropic_messages")
    if role not in _PROVIDER_ROLES:
        raise ApiError(400, "INVALID_ROLE", "供应商角色仅支持 primary / fallback / embedding / rerank / none")


_MODEL_DISCOVERY_ERROR_RESPONSES: dict[str, tuple[int, str, str]] = {
    "auth_error": (400, "PROVIDER_AUTH_ERROR", "供应商认证失败，请检查 API Key 后重试"),
    "rate_limited": (429, "PROVIDER_RATE_LIMITED", "供应商暂时限制请求，请稍后重试"),
    "timeout": (504, "PROVIDER_TIMEOUT", "获取模型超时，请稍后重试"),
    "network_error": (502, "PROVIDER_NETWORK_ERROR", "暂时无法连接供应商，请稍后重试"),
    "server_error": (502, "PROVIDER_UNAVAILABLE", "供应商暂时不可用，请稍后重试"),
    "model_discovery_unsupported": (
        400,
        "MODEL_DISCOVERY_UNSUPPORTED",
        "当前供应商不支持获取模型，请手动填写模型名",
    ),
    "invalid_model_list_response": (
        502,
        "MODEL_LIST_INVALID",
        "供应商返回的模型列表不可用，请手动填写模型名",
    ),
    "model_list_response_too_large": (
        502,
        "MODEL_LIST_TOO_LARGE",
        "供应商返回的模型列表超出安全限制，请手动填写模型名",
    ),
    "model_list_limit_exceeded": (
        502,
        "MODEL_LIST_LIMIT_EXCEEDED",
        "可获取的模型数量超出安全限制，请缩小范围或手动填写模型名",
    ),
}


def _model_discovery_error(exc: providers.ProviderError) -> ApiError:
    """Translate adapter-only safe codes without exposing upstream exception text."""
    status, code, message = _MODEL_DISCOVERY_ERROR_RESPONSES.get(
        str(exc),
        (502, "MODEL_DISCOVERY_FAILED", "无法获取模型列表，请检查配置后重试"),
    )
    return ApiError(status, code, message)


def _provider_extra(row: sqlite3.Row) -> dict[str, Any]:
    """Load stored gateway metadata defensively; malformed legacy JSON is inert."""
    try:
        value = json.loads(row["extra_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _validate_model_discovery_base_url(base_url: str) -> str | None:
    """Apply stricter transport rules before a transient API key leaves the process."""
    error = validate_provider_base_url(base_url)
    if error is not None:
        return error
    parsed = urlparse(base_url.strip())
    if parsed.scheme != "https":
        return "获取模型仅支持 HTTPS 接口地址"
    if parsed.username is not None or parsed.password is not None:
        return "接口地址不允许包含账户信息"
    return None


def _transient_provider_test_values(
    body: ProviderTransientTestIn,
) -> tuple[str, str, str, str, str]:
    """Validate a form-only smoke request before its API key leaves the process.

    Model discovery and transient testing share the strict HTTPS/SSRF boundary.
    The returned tuple contains only normalized in-memory values and is never
    passed to audit helpers or provider persistence code.
    """
    if not isinstance(body.protocol, str) or body.protocol not in _PROTOCOLS:
        raise ApiError(400, "INVALID_PROTOCOL", "不支持的协议类型")
    if (
        not isinstance(body.base_url, str)
        or not body.base_url.strip()
        or len(body.base_url) > 500
    ):
        raise ApiError(400, "INVALID_BASE_URL", "接口地址格式不正确")
    if not isinstance(body.api_key, str) or not body.api_key or len(body.api_key) > 500:
        raise ApiError(400, "INVALID_API_KEY", "API Key 格式不正确")
    if not isinstance(body.model, str) or not body.model.strip() or len(body.model) > 100:
        raise ApiError(400, "INVALID_MODEL", "请先选择或填写模型名")
    if not isinstance(body.role, str) or body.role not in _PROVIDER_ROLES:
        raise ApiError(400, "INVALID_ROLE", "供应商角色格式不正确")
    url_error = _validate_model_discovery_base_url(body.base_url)
    if url_error is not None:
        raise ApiError(400, "INVALID_BASE_URL", url_error)
    return (
        body.protocol,
        body.base_url.strip(),
        body.api_key,
        body.model.strip(),
        body.role,
    )


async def _discover_provider_models(
    protocol: str,
    base_url: str,
    api_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke the adapter while preserving only its allowlisted error vocabulary."""
    try:
        return await providers.discover_models(protocol, base_url, api_key, extra)
    except providers.ProviderError as exc:
        raise _model_discovery_error(exc) from None
    except Exception:
        # decrypt/client faults must not reach FastAPI's generic logger because
        # third-party exceptions can embed request context or credentials.
        raise ApiError(502, "MODEL_DISCOVERY_FAILED", "无法获取模型列表，请检查配置后重试") from None


@router.get("/api/admin/providers")
def list_providers(
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM provider_configs ORDER BY created_at ASC"
    ).fetchall()
    items = [_provider_dto(row) for row in rows]
    return {"items": items, "total": len(items)}


@router.post("/api/admin/providers/discover-models")
async def discover_transient_provider_models(
    body: ProviderModelDiscoveryIn,
    admin: CurrentUser = Depends(_admin_csrf),
) -> dict[str, Any]:
    """Discover models from unsaved form values without writing a provider or audit row."""
    if not isinstance(body.protocol, str) or body.protocol not in _PROTOCOLS:
        raise ApiError(400, "INVALID_PROTOCOL", "不支持的协议类型")
    if (
        not isinstance(body.base_url, str)
        or not body.base_url.strip()
        or len(body.base_url) > 500
    ):
        raise ApiError(400, "INVALID_BASE_URL", "接口地址格式不正确")
    if not isinstance(body.api_key, str) or not body.api_key or len(body.api_key) > 500:
        raise ApiError(400, "INVALID_API_KEY", "API Key 格式不正确")
    url_error = _validate_model_discovery_base_url(body.base_url)
    if url_error is not None:
        raise ApiError(400, "INVALID_BASE_URL", url_error)
    return await _discover_provider_models(
        body.protocol,
        body.base_url.strip(),
        body.api_key,
    )


@router.post("/api/admin/providers/test-connection")
async def test_transient_provider_connectivity(
    body: ProviderTransientTestIn,
    admin: CurrentUser = Depends(_admin_csrf),
) -> dict[str, Any]:
    """Test an unsaved provider form without creating a row or audit record."""
    protocol, base_url, api_key, model, role = _transient_provider_test_values(body)
    # The adapter catches upstream failures and returns its existing safe result
    # shape. Do not persist this result: it represents an incomplete form, not
    # a durable provider configuration.
    return await providers.test_transient_provider(protocol, base_url, api_key, model, role)


@router.post("/api/admin/providers/{provider_id}/discover-models")
async def discover_saved_provider_models(
    provider_id: str,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Discover from the immutable saved row, never from a caller-supplied URL or key."""
    if await request.body():
        # A non-empty body could otherwise be mistaken for an override of a
        # stored credential.  Reject it before loading or decrypting the row.
        raise ApiError(
            400,
            "MODEL_DISCOVERY_BODY_FORBIDDEN",
            "已保存的供应商只能使用其已存配置获取模型",
        )
    row = _get_provider_or_404(conn, provider_id)
    if row["protocol"] not in _PROTOCOLS:
        raise ApiError(400, "INVALID_PROTOCOL", "已保存的供应商协议不受支持")
    url_error = _validate_model_discovery_base_url(row["base_url"])
    if url_error is not None:
        raise ApiError(400, "INVALID_BASE_URL", url_error)
    try:
        api_key = providers.decrypt_key(row)
    except Exception:
        # The encrypted token, its parser error, and the key material must all
        # remain server-only even if the local encryption configuration changed.
        raise ApiError(500, "MODEL_DISCOVERY_FAILED", "无法读取供应商密钥，请重新保存配置") from None
    return await _discover_provider_models(
        row["protocol"],
        row["base_url"],
        api_key,
        _provider_extra(row),
    )


@router.post("/api/admin/providers", status_code=201)
def create_provider(
    body: ProviderCreateIn,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _validate_protocol_role(body.protocol, body.role)
    url_error = validate_provider_base_url(body.base_url)
    if url_error is not None:
        # NF9：拒绝本机/内网/云元数据地址，防 SSRF 转发 API Key
        raise ApiError(400, "INVALID_BASE_URL", url_error)

    config = get_config()
    key = load_encryption_key(config.config_encryption_key or None)
    provider_id = uuid.uuid4().hex
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO provider_configs (id, name, protocol, base_url, model,"
        " api_key_encrypted, role, enabled, timeout_seconds, extra_json,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'none', ?, ?, ?, ?, ?)",
        (
            provider_id,
            body.name.strip(),
            body.protocol,
            body.base_url.strip(),
            body.model.strip(),
            encrypt_secret(body.api_key, key),  # AES-256-GCM（NF2），明文永不落库
            1 if body.enabled else 0,
            body.timeout_seconds,
            json.dumps(body.extra, ensure_ascii=False),
            now,
            now,
        ),
    )
    if body.role != "none":
        _assign_role_exclusive(conn, provider_id, body.role)
    row = _get_provider_or_404(conn, provider_id)
    dto = _provider_dto(row)
    audit(
        conn,
        admin.user,
        "provider.create",
        target_type="provider",
        target_id=provider_id,
        after=dto,  # DTO 已脱敏，审计快照天然不含密钥
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return dto


@router.put("/api/admin/providers/{provider_id}")
def update_provider(
    provider_id: str,
    body: ProviderUpdateIn,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_provider_or_404(conn, provider_id)
    before = _provider_dto(row)

    new_protocol = body.protocol if body.protocol is not None else row["protocol"]
    new_role = body.role if body.role is not None else row["role"]
    _validate_protocol_role(new_protocol, new_role)

    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.protocol is not None:
        fields["protocol"] = body.protocol
    if body.base_url is not None:
        url_error = validate_provider_base_url(body.base_url)
        if url_error is not None:
            raise ApiError(400, "INVALID_BASE_URL", url_error)
        fields["base_url"] = body.base_url.strip()
    if body.model is not None:
        fields["model"] = body.model.strip()
    if body.api_key:  # 空串/None 都表示不更换密钥（密钥只进不出）
        key = load_encryption_key(get_config().config_encryption_key or None)
        fields["api_key_encrypted"] = encrypt_secret(body.api_key, key)
    if body.enabled is not None:
        fields["enabled"] = 1 if body.enabled else 0
    if body.timeout_seconds is not None:
        fields["timeout_seconds"] = body.timeout_seconds
    if body.extra is not None:
        fields["extra_json"] = json.dumps(body.extra, ensure_ascii=False)

    if fields:
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{column} = ?" for column in fields)
        conn.execute(
            f"UPDATE provider_configs SET {assignments} WHERE id = ?",
            (*fields.values(), provider_id),
        )
    if body.role is not None and body.role != row["role"]:
        _assign_role_exclusive(conn, provider_id, body.role)

    updated = _get_provider_or_404(conn, provider_id)
    dto = _provider_dto(updated)
    audit(
        conn,
        admin.user,
        "provider.update",
        target_type="provider",
        target_id=provider_id,
        before=before,
        after=dto,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return dto


@router.delete("/api/admin/providers/{provider_id}")
def delete_provider(
    provider_id: str,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_provider_or_404(conn, provider_id)
    before = _provider_dto(row)
    conn.execute("DELETE FROM provider_configs WHERE id = ?", (provider_id,))
    # 删除属于高危操作：审计里留完整脱敏快照（NF8）
    audit(
        conn,
        admin.user,
        "provider.delete",
        target_type="provider",
        target_id=provider_id,
        before=before,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"message": "供应商配置已删除"}


@router.post("/api/admin/providers/{provider_id}/test")
def test_provider_connectivity(
    provider_id: str,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _get_provider_or_404(conn, provider_id)
    if not row["enabled"]:
        # A disabled configuration is intentionally inert; testing it would
        # create an unexpected outbound request despite the administrator's
        # explicit disable action.
        raise ApiError(400, "PROVIDER_NOT_TESTABLE", "已禁用的供应商不能执行连接测试")
    # 真实连通性测试：同步端点跑在线程池里，asyncio.run 不会撞到事件循环
    result = asyncio.run(providers.test_provider(row))
    conn.execute(
        "UPDATE provider_configs SET last_test_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(result, ensure_ascii=False), utc_now_iso(), provider_id),
    )
    audit(
        conn,
        admin.user,
        "provider.test",
        target_type="provider",
        target_id=provider_id,
        after=result,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.post("/api/admin/providers/{provider_id}/set-role")
def set_provider_role(
    provider_id: str,
    body: SetRoleIn,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    if body.role not in _PROVIDER_ROLES:
        raise ApiError(400, "INVALID_ROLE", "供应商角色仅支持 primary / fallback / embedding / rerank / none")
    row = _get_provider_or_404(conn, provider_id)
    before = _provider_dto(row)
    _assign_role_exclusive(conn, provider_id, body.role)
    updated = _get_provider_or_404(conn, provider_id)
    dto = _provider_dto(updated)
    audit(
        conn,
        admin.user,
        "provider.set_role",
        target_type="provider",
        target_id=provider_id,
        before={"role": before["role"]},
        after={"role": dto["role"]},
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return dto


# ================================================================ RAG 参数

# 字段校验规则：(类型, 下界, 上界) / (枚举值集合)——蓝图 §5 rag_settings + §6.6 范围
_RAG_INT_RANGES: dict[str, tuple[int, int]] = {
    "chunk_size": (100, 2000),
    "chunk_overlap": (0, 1000),
    "top_k": (1, 20),
    "max_citations": (1, 20),
}
_RAG_BOOL_FIELDS = ("title_inherit", "hybrid_search", "rerank_enabled", "require_manual_review")
_RAG_ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "refusal_policy": ("refuse", "generic_advice"),
    "student_visibility_default": ("admin", "teacher", "student"),
    "expired_doc_policy": ("remove", "keep"),
}
_RAG_TEXT_LIMITS: dict[str, int] = {
    "table_strategy": 20,
    "citation_format": 200,
    "prompt_template": 4000,
    "prompt_template_version": 50,
}


class RagSettingsPatch(BaseModel):
    """部分更新；未知字段直接拒绝，避免管理员误以为保存成功。"""

    model_config = ConfigDict(extra="forbid")

    chunk_size: int | None = None
    chunk_overlap: int | None = None
    title_inherit: bool | None = None
    table_strategy: str | None = None
    top_k: int | None = None
    score_threshold: float | None = None
    hybrid_search: bool | None = None
    rerank_enabled: bool | None = None
    citation_format: str | None = None
    refusal_policy: str | None = None
    max_citations: int | None = None
    prompt_template: str | None = None
    prompt_template_version: str | None = None
    require_manual_review: bool | None = None
    student_visibility_default: str | None = None
    expired_doc_policy: str | None = None


def _rag_settings_row(conn: sqlite3.Connection) -> sqlite3.Row:
    # 防御性兜底：未跑 seed 的库也保证单行存在（schema 默认值即安全默认）
    conn.execute(
        "INSERT OR IGNORE INTO rag_settings (id, updated_at) VALUES (1, ?)",
        (utc_now_iso(),),
    )
    conn.commit()
    return conn.execute("SELECT * FROM rag_settings WHERE id = 1").fetchone()


def _rag_settings_dto(row: sqlite3.Row) -> dict[str, Any]:
    dto = dict(row)
    for field in _RAG_BOOL_FIELDS:
        dto[field] = bool(dto[field])
    return dto


@router.get("/api/admin/rag-settings")
def get_rag_settings(
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _rag_settings_dto(_rag_settings_row(conn))


@router.patch("/api/admin/rag-settings")
def patch_rag_settings(
    body: RagSettingsPatch,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    row = _rag_settings_row(conn)
    before = _rag_settings_dto(row)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise ApiError(400, "EMPTY_PATCH", "没有需要修改的参数")

    updates: dict[str, Any] = {}
    for field, value in patch.items():
        if field in _RAG_INT_RANGES:
            low, high = _RAG_INT_RANGES[field]
            if not (low <= value <= high):
                raise ApiError(400, "INVALID_SETTING", f"{field} 必须在 {low} 到 {high} 之间")
            updates[field] = value
        elif field == "score_threshold":
            if not (0.0 <= value <= 1.0):
                raise ApiError(400, "INVALID_SETTING", "score_threshold 必须在 0 到 1 之间")
            updates[field] = value
        elif field in _RAG_BOOL_FIELDS:
            updates[field] = 1 if value else 0
        elif field in _RAG_ENUM_FIELDS:
            allowed = _RAG_ENUM_FIELDS[field]
            if value not in allowed:
                raise ApiError(400, "INVALID_SETTING", f"{field} 仅支持：{' / '.join(allowed)}")
            updates[field] = value
        elif field in _RAG_TEXT_LIMITS:
            limit = _RAG_TEXT_LIMITS[field]
            if not value or len(value) > limit:
                raise ApiError(400, "INVALID_SETTING", f"{field} 不能为空且长度不超过 {limit} 字符")
            updates[field] = value

    # 重叠区必须小于切片长度，否则切片器会死循环（校验用生效后的组合值）
    effective_chunk_size = updates.get("chunk_size", before["chunk_size"])
    effective_overlap = updates.get("chunk_overlap", before["chunk_overlap"])
    if effective_overlap >= effective_chunk_size:
        raise ApiError(400, "INVALID_SETTING", "chunk_overlap 必须小于 chunk_size")

    updates["updated_at"] = utc_now_iso()
    updates["updated_by"] = admin.user["id"]
    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(f"UPDATE rag_settings SET {assignments} WHERE id = 1", tuple(updates.values()))
    after = _rag_settings_dto(_rag_settings_row(conn))
    # 参数修改必须写审计（PRD-04 §4.2），before/after 全量快照便于回溯
    audit(
        conn,
        admin.user,
        "rag_settings.update",
        target_type="rag_settings",
        target_id="1",
        before=before,
        after=after,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return after


# ================================================================ 用户与权限

def _admin_user_dto(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "email_verified": row["email_verified_at"] is not None,
        "created_at": row["created_at"],
    }


def _revoke_user_sessions(conn: sqlite3.Connection, user_id: str) -> None:
    """禁用/重置密码时吊销该用户两张会话表的全部有效会话。"""
    now = utc_now_iso()
    for table in ("user_sessions", "admin_sessions"):
        conn.execute(
            f"UPDATE {table} SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, user_id),
        )


@router.get("/api/admin/users")
def list_users(
    role: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if role:
        if role not in _USER_ROLES:
            raise ApiError(400, "INVALID_ROLE", "角色仅支持 student / teacher / content_admin / system_admin")
        clauses.append("role = ?")
        params.append(role)
    if q:
        clauses.append("(email LIKE ? OR name LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM users{where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM users{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return {"items": [_admin_user_dto(row) for row in rows], "total": total}


class UserPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    status: str | None = None


@router.patch("/api/admin/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatchIn,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    if body.role is None and body.status is None:
        raise ApiError(400, "EMPTY_PATCH", "没有需要修改的内容")
    if body.role is not None and body.role not in _USER_ROLES:
        raise ApiError(400, "INVALID_ROLE", "角色仅支持 student / teacher / content_admin / system_admin")
    if body.status is not None and body.status not in ("active", "disabled"):
        raise ApiError(400, "INVALID_STATUS", "状态仅支持 active / disabled")

    is_self = target["id"] == admin.user["id"]
    if is_self and body.status == "disabled":
        # 自杀式操作直接拦下：最后一个管理员把自己禁用后系统将无人可管
        raise ApiError(400, "SELF_OPERATION_FORBIDDEN", "不能禁用当前登录的管理员账号")
    if is_self and body.role is not None and body.role != "system_admin":
        raise ApiError(400, "SELF_OPERATION_FORBIDDEN", "不能降低自己的管理员角色")

    before = {"role": target["role"], "status": target["status"]}
    updates: dict[str, Any] = {"updated_at": utc_now_iso()}
    if body.role is not None:
        updates["role"] = body.role
    if body.status is not None:
        updates["status"] = body.status
    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*updates.values(), user_id))
    if body.status == "disabled":
        # 禁用即终止会话（PRD-06 §3.4：禁用后禁止 Agent 与 RAG 调用）
        _revoke_user_sessions(conn, user_id)
    after = {
        "role": body.role if body.role is not None else target["role"],
        "status": body.status if body.status is not None else target["status"],
    }
    # 权限/状态变更必须写审计（PRD-04 §5.2）
    audit(
        conn,
        admin.user,
        "user.update",
        target_type="user",
        target_id=user_id,
        before=before,
        after=after,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    refreshed = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _admin_user_dto(refreshed)


@router.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    request: Request,
    admin: CurrentUser = Depends(_admin_csrf),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    # 临时密码只在本次响应出现一次；后缀保证满足"字母+数字且≥8位"策略
    temporary_password = f"{secrets.token_urlsafe(6)}Aa1"
    conn.execute(
        "UPDATE user_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
        (hash_password(temporary_password), utc_now_iso(), user_id),
    )
    _revoke_user_sessions(conn, user_id)
    # 审计只记动作，绝不记临时密码本身
    audit(
        conn,
        admin.user,
        "user.reset_password",
        target_type="user",
        target_id=user_id,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "temporary_password": temporary_password,
        "message": "临时密码已生成，仅本次展示，请转交用户并提醒其登录后立即修改",
    }


# ================================================================ 审计查询

@router.get("/api/admin/audit-logs")
def list_audit_logs(
    actor_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if actor_id:
        clauses.append("actor_id = ?")
        params.append(actor_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if target_type:
        clauses.append("target_type = ?")
        params.append(target_type)
    if from_time:
        # created_at 是 UTC ISO8601 字符串，字典序比较即时间比较（蓝图 §4）
        clauses.append("created_at >= ?")
        params.append(from_time)
    if to_time:
        clauses.append("created_at <= ?")
        params.append(to_time)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM audit_logs{where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM audit_logs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        for field in ("before_json", "after_json"):
            raw = item.pop(field)
            item[field.removesuffix("_json")] = json.loads(raw) if raw else None
        items.append(item)
    return {"items": items, "total": total}


# ================================================================ 运营指标（PRD-06 §13.1）

def _count_events(conn: sqlite3.Connection, name: str, extra_where: str = "") -> int:
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM analytics_events WHERE event_name = ?{extra_where}",
        (name,),
    ).fetchone()["n"]


def _build_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """逐指标诚实计算；任何无样本的指标返回 None（调用方拼 note 说明）。"""
    metrics: dict[str, Any] = {}

    # 1. Agent 工具调用成功率（按工具名，只统计已完结的调用）
    rows = conn.execute(
        "SELECT tool_name, COUNT(*) AS total,"
        " SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok"
        " FROM tool_calls WHERE status IN ('completed', 'failed') GROUP BY tool_name"
    ).fetchall()
    metrics["tool_call_success_rate"] = (
        {
            row["tool_name"]: {
                "total": row["total"],
                "success_rate": round(row["ok"] / row["total"], 4),
            }
            for row in rows
        }
        if rows
        else None
    )

    # 2. RAG 召回命中率（rag_retrieval_completed 的 props.hit_count > 0 占比）
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN COALESCE(json_extract(props_json, '$.hit_count'), 0) > 0"
        "     THEN 1 ELSE 0 END) AS hits"
        " FROM analytics_events WHERE event_name = 'rag_retrieval_completed'"
    ).fetchone()
    metrics["rag_retrieval_hit_rate"] = (
        round(row["hits"] / row["total"], 4) if row["total"] else None
    )

    # 3. RAG 无依据拒答率（rag_query_submitted 的 props.refused=true 占比）
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN json_extract(props_json, '$.refused') IN (1, 'true')"
        "     THEN 1 ELSE 0 END) AS refused"
        " FROM analytics_events WHERE event_name = 'rag_query_submitted'"
    ).fetchone()
    metrics["rag_refusal_rate"] = (
        round(row["refused"] / row["total"], 4) if row["total"] else None
    )

    # 4. 任务创建转化率：确认创建 / 预览生成
    previews = _count_events(conn, "task_preview_created")
    created = _count_events(conn, "task_created")
    metrics["task_creation_conversion"] = round(created / previews, 4) if previews else None

    # 5. 预设启动率：source=preset 的任务创建 / 预设点击
    clicked = _count_events(conn, "preset_clicked")
    preset_created = _count_events(
        conn, "task_created", " AND json_extract(props_json, '$.source') = 'preset'"
    )
    metrics["preset_start_rate"] = round(preset_created / clicked, 4) if clicked else None

    # 6. 诊断成功率：摘要落库数 / 上传事件数
    uploaded = _count_events(conn, "diagnostic_uploaded")
    summaries = conn.execute("SELECT COUNT(*) AS n FROM diagnostic_summaries").fetchone()["n"]
    metrics["diagnostic_success_rate"] = round(summaries / uploaded, 4) if uploaded else None

    # 7. 掌握度更新确认率：学生确认应用掌握度的提交占比
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(mastery_applied) AS applied FROM task_attempts"
    ).fetchone()
    metrics["mastery_confirm_rate"] = (
        round((row["applied"] or 0) / row["total"], 4) if row["total"] else None
    )

    # 8. 模型调用失败率（按 provider）：agent_runs 失败占比 + 最近连接测试状态
    rows = conn.execute(
        "SELECT p.id, p.name,"
        " (SELECT COUNT(*) FROM agent_runs r WHERE r.provider_id = p.id) AS runs_total,"
        " (SELECT COUNT(*) FROM agent_runs r WHERE r.provider_id = p.id"
        "   AND (r.status = 'failed' OR r.error IS NOT NULL)) AS runs_failed,"
        " p.last_test_json"
        " FROM provider_configs p ORDER BY p.created_at ASC"
    ).fetchall()
    if rows:
        by_provider: dict[str, Any] = {}
        for row in rows:
            last_test_ok: bool | None = None
            if row["last_test_json"]:
                try:
                    last_test_ok = bool(json.loads(row["last_test_json"]).get("ok"))
                except json.JSONDecodeError:
                    last_test_ok = None
            by_provider[row["id"]] = {
                "name": row["name"],
                "runs_total": row["runs_total"],
                "runs_failed": row["runs_failed"],
                "run_failure_rate": (
                    round(row["runs_failed"] / row["runs_total"], 4)
                    if row["runs_total"]
                    else None
                ),
                "last_test_ok": last_test_ok,
            }
        metrics["model_failure_rate_by_provider"] = by_provider
    else:
        metrics["model_failure_rate_by_provider"] = None

    return metrics


@router.get("/api/admin/metrics")
def get_metrics(
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    metrics = _build_metrics(conn)
    empty = [name for name, value in metrics.items() if value is None]
    if empty:
        note = f"以下指标暂无样本数据，返回 null（不代表故障）：{', '.join(empty)}"
    else:
        note = "所有指标均有样本数据；统计基于当前库内事件与运行记录如实计算"
    return {"metrics": metrics, "note": note}


# ================================================================ 告警（PRD-06 §13.2）

@router.get("/api/admin/alerts")
def get_alerts(
    admin: CurrentUser = Depends(get_admin_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """实时评估全部告警项并返回当前触发中的告警（健康时 alerts 为空列表）。

    按需计算、不落库不推送：MVP 尚无告警通道，管理端轮询本接口即闭环
    （详见 bhzd_py/alerts.py 模块说明）。
    """
    return {"alerts": evaluate_alerts(conn), "evaluated_at": utc_now_iso()}
