"""LLM provider 抽象层（蓝图 §1/§6.6，PRD-04 §3.1）。

对外契约（其它域按此编码，签名不可变）：
- ``complete(messages, *, role="primary")``：非流式调用；失败自动回退
  （primary → fallback）；无可用 provider 或全部失败返回 ``None``，调用方
  据此降级为模板合成（PRD-06 §11.1）。
- ``stream_deltas(messages, *, role="primary")``：逐 token 产出
  ``{"delta": ...}``，结束产出 ``{"done": True, "model", "usage"}``；
  首段内容之前失败同样回退，已开始输出则不再切换（避免拼接两家文本）。
- ``embed_texts(texts)``：role='embedding' 的启用 provider；未配置或失败
  返回 ``None``（调用方降级本地哈希嵌入）。
- ``get_enabled_provider(db, role)`` / ``decrypt_key(row)``：行查询与密钥解密。
- ``discover_models(protocol, base_url, api_key, extra=None)``：在保存前短暂
  使用管理员刚输入的密钥拉取可选模型；结果只包含模型标识与展示名。
- ``test_transient_provider(...)``：在保存前短暂验证当前表单连接，不写库或
  保存管理员刚输入的密钥。

安全红线（为什么这么设计）：
- API Key 只经 ``decrypt_key`` 在内存中短暂出现，永不写日志；日志只记录
  ``_error_label`` 产生的安全短码（不含 URL/请求体，因此异常对象本身绝不进日志）。
- 正常 HTTP 调用使用 provider 行上的 ``timeout_seconds``；管理员连接测试
  另有短时总预算，避免交互操作被慢供应商长期占用。
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import logging
import math
import re
import sqlite3
import time
from typing import Any, AsyncIterator

import httpx

from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from ..security import decrypt_secret, load_encryption_key

logger = logging.getLogger(__name__)

# 测试钩子：测试用 httpx.MockTransport 替换网络出口，生产永远为 None。
# 放在模块级而非参数透传，是为了让公开接口签名保持稳定（其它域已按签名编码）。
_TEST_TRANSPORT: httpx.AsyncBaseTransport | None = None

# Keep the adapter surface deliberately small: all supported providers use an
# HTTP contract that can be mocked and audited consistently in local tests.
_PROTOCOLS = ("chat_completions", "anthropic_messages", "responses")

# A provider's saved role determines the smallest request that can prove its
# configured capability. An enabled but unassigned provider uses the neutral
# chat probe, avoiding unsafe guesses about embedding/rerank capability from a model name.
_SMOKE_CAPABILITY_BY_ROLE = {
    "primary": "chat",
    "fallback": "chat",
    "embedding": "embedding",
    "rerank": "rerank",
    "grader": "chat",
    "none": "chat",
}
# A connectivity check is an interactive admin action, not a normal model run.
# Keep it short even when the saved runtime timeout permits several minutes.
_PROVIDER_TEST_TIMEOUT_SECONDS = 8.0
# A chat probe only needs one actual output token. Structured rerank validation
# retains a larger budget because it must receive a complete JSON ordering.
# Some reasoning models emit an empty first delta while reserving their output
# budget; four tokens gives the probe room to reach a valid protocol event.
_PROVIDER_TEST_CHAT_MAX_TOKENS = 4
_PROVIDER_TEST_STRUCTURED_MAX_TOKENS = 16
# Returning after the first token must not inherit the normal HTTP stream close wait.
_PROVIDER_TEST_STREAM_CLOSE_TIMEOUT_SECONDS = 0.25


def _sampling_overrides(sampling: dict[str, Any] | None) -> dict[str, float]:
    """Return only finite RAG sampling values that are safe for provider bodies.

    The admin API owns range validation.  This second boundary keeps internal
    callers and older workers from forwarding malformed values to a provider,
    while leaving provider-specific defaults untouched when no override exists.
    """
    if not isinstance(sampling, dict):
        return {}
    overrides: dict[str, float] = {}
    for key in ("temperature", "top_p"):
        value = sampling.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            overrides[key] = numeric
    return overrides
_SAFE_PROVIDER_ERROR_CODES = {
    "auth_error",
    "rate_limited",
    "server_error",
    "provider_unavailable",
    "provider_error",
    "timeout",
    "network_error",
    "unsupported_protocol",
    "unsupported_provider_role",
    "embedding_not_supported",
    "invalid_embedding_response",
    "invalid_chat_response",
    "invalid_rerank_response",
    "model_discovery_unsupported",
    "invalid_model_list_response",
    "model_list_response_too_large",
    "model_list_limit_exceeded",
}

# Model discovery is an interactive configuration aid, not a long-running
# provider task.  Keep both its wall-clock wait and data volume bounded so a
# malformed or hostile upstream cannot tie up an admin request indefinitely.
_MODEL_DISCOVERY_TIMEOUT_SECONDS = 10.0
_MODEL_DISCOVERY_MAX_RESPONSE_BYTES = 512 * 1024
_MODEL_DISCOVERY_MAX_MODELS = 200
_MODEL_DISCOVERY_MAX_PAGES = 3
_MODEL_DISCOVERY_PAGE_SIZE = 100
_MODEL_DISCOVERY_MAX_ID_LENGTH = 200
_MODEL_DISCOVERY_MAX_LABEL_LENGTH = 240

# Runtime provider rows deliberately accept arbitrary extra headers for
# vendor gateways.  A transient discovery request must retain its Bearer
# credential and must not allow caller input to alter HTTP framing or cookies.
_DISCOVERY_BLOCKED_EXTRA_HEADERS = {
    "authorization",
    "connection",
    "content-length",
    "cookie",
    "host",
    "proxy-authorization",
    "set-cookie",
    "transfer-encoding",
}

class ProviderError(RuntimeError):
    """provider 调用失败；消息只能是本模块构造的安全短码（可进日志/管理端）。"""


# ---------------------------------------------------------------- 公共查询/解密

def get_enabled_provider(db: sqlite3.Connection, role: str) -> sqlite3.Row | None:
    """取指定角色的启用 provider 行。

    set-role 接口保证同角色至多一行；ORDER BY 只是防御性兜底。
    """
    return db.execute(
        "SELECT * FROM provider_configs WHERE role = ? AND enabled = 1"
        " ORDER BY updated_at DESC LIMIT 1",
        (role,),
    ).fetchone()


def get_provider_by_role(db: sqlite3.Connection, role: str) -> sqlite3.Row | None:
    """Resolve a runtime role with the safe grader-to-primary fallback.

    Grading is intentionally a separate administrator role, but an unset
    grader must not make ordinary exercise submissions fail.  Keeping the
    fallback here gives API routes and background workers one auditable rule.
    """

    row = get_enabled_provider(db, role)
    if row is None and role == "grader":
        return get_enabled_provider(db, "primary")
    return row


def decrypt_key(row: sqlite3.Row) -> str:
    """解密 provider 行的 API Key。仅内部使用；明文永不写日志/异常消息。"""
    key = load_encryption_key(get_config().config_encryption_key or None)
    return decrypt_secret(row["api_key_encrypted"], key)


def _provider_api_key(row: sqlite3.Row | dict[str, Any]) -> str:
    """Resolve a saved encrypted key or an explicitly transient form key in memory.

    The transient marker is created only by ``test_transient_provider`` and is
    never serialized, audited, or logged.  Keeping this branch here lets the
    existing adapter smoke checks exercise the same protocol code as saved rows.
    """
    transient_key = row.get("_transient_api_key") if isinstance(row, dict) else None
    if isinstance(transient_key, str):
        return transient_key
    return decrypt_key(row)


# ---------------------------------------------------------------- 内部工具

def _extra(row: sqlite3.Row) -> dict[str, Any]:
    """解析 extra_json（app_id/domain/max_tokens 等协议附加参数）。"""
    try:
        value = json.loads(row["extra_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


# A gateway accepting the Chat Completions schema does not prove that its
# configured model can inspect binary input. Keep that operator-declared model
# capability separate from the protocol blocks implemented by this adapter.
_MEDIA_INPUT_TYPES = frozenset({"image", "audio", "video"})
_PROTOCOL_MEDIA_INPUTS: dict[str, frozenset[str]] = {
    "chat_completions": frozenset({"image", "audio"}),
    "anthropic_messages": frozenset({"image"}),
    "responses": frozenset({"image"}),
}


def model_inputs(row: sqlite3.Row) -> frozenset[str]:
    """Return the allow-listed inputs declared for one saved model.

    Older provider rows predate ``extra.model_inputs``. Treating them as text
    only preserves ordinary chat while preventing a text model from receiving
    image/audio/video blocks merely because its gateway accepts their shape.
    """

    stored = _extra(row).get("model_inputs")
    if not isinstance(stored, list):
        return frozenset({"text"})
    return frozenset(value for value in stored if value in {"text", *_MEDIA_INPUT_TYPES})


def _supports_media_attachment(row: sqlite3.Row, kind: str, mime_type: str) -> bool:
    """Require both an explicit model declaration and a mapped wire format."""

    if kind not in _MEDIA_INPUT_TYPES:
        return True
    inputs = model_inputs(row)
    if "text" not in inputs or kind not in inputs:
        return False
    if kind not in _PROTOCOL_MEDIA_INPUTS.get(row["protocol"], frozenset()):
        return False
    # Chat Completions only has a portable audio mapping for WAV and MP3.
    return kind != "audio" or _audio_format(mime_type) is not None


def _candidate_rows_from_connection(db: sqlite3.Connection, role: str) -> list[sqlite3.Row]:
    """Load the standard primary/fallback order from an existing connection."""

    rows: list[sqlite3.Row] = []
    # Resolve grader through the same primary fallback used by direct callers;
    # this keeps complete()/stream_deltas() safe when no dedicated grader row exists.
    primary_row = get_provider_by_role(db, role)
    if primary_row is not None:
        rows.append(primary_row)
    if role in {"primary", "grader"}:
        # An unset grader already resolves through primary.  A dedicated grader
        # still needs the same bounded fallback so one unavailable scoring
        # provider cannot strand a learner's submitted answer indefinitely.
        fallback_row = get_enabled_provider(db, "fallback")
        if fallback_row is not None:
            rows.append(fallback_row)
    return rows


def has_compatible_media_provider(
    db: sqlite3.Connection, attachments: list[Any], *, role: str = "primary"
) -> bool:
    """Report whether one normal fallback candidate can process every media item.

    Document attachments are parsed into untrusted text before this boundary,
    so they intentionally do not require a multimodal model declaration.
    """

    requirements = [
        (str(getattr(item, "kind", "")), str(getattr(item, "mime_type", "")))
        for item in attachments
        if str(getattr(item, "kind", "")) in _MEDIA_INPUT_TYPES
    ]
    if not requirements:
        return True
    return any(
        all(_supports_media_attachment(row, kind, mime_type) for kind, mime_type in requirements)
        for row in _candidate_rows_from_connection(db, role)
    )


def _media_requirements_from_messages(messages: list[dict]) -> list[tuple[str, str]]:
    """Extract private media markers without exposing bytes to provider selection."""

    requirements: list[tuple[str, str]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "media_attachment":
                continue
            mime_type = str(block.get("mime_type") or "").split(";", 1)[0].lower()
            kind = mime_type.split("/", 1)[0]
            if kind in _MEDIA_INPUT_TYPES:
                requirements.append((kind, mime_type))
    return requirements


def _error_label(exc: Exception) -> str:
    """把异常映射为安全短码：绝不含 URL、密钥、请求体等敏感内容。"""
    if isinstance(exc, ProviderError):
        # ProviderError is an internal type, but retain an allowlist here so a
        # future call site cannot accidentally turn provider input into an API
        # error, audit payload, or log line.
        label = str(exc)
        if label in _SAFE_PROVIDER_ERROR_CODES:
            return label
        if re.fullmatch(r"http_[1-5]\d\d", label):
            return label
        return "provider_error"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.HTTPError):
        return "network_error"
    # Unknown adapter/parser failures are intentionally one code as their type
    # names are neither actionable to an administrator nor a stable contract.
    return "provider_error"


def _log_failure(row: sqlite3.Row, exc: Exception) -> None:
    """记录失败但不泄露密钥：只带安全短码与非敏感元数据。"""
    logger.warning(
        "LLM provider 调用失败: id=%s protocol=%s model=%s error=%s",
        row["id"],
        row["protocol"],
        row["model"],
        _error_label(exc),
    )


def _raise_for_status(resp: httpx.Response) -> None:
    """HTTP 状态码 → 安全短码异常（状态码本身不含敏感信息）。"""
    if resp.status_code == 200:
        return
    if resp.status_code in (401, 403):
        raise ProviderError("auth_error")
    if resp.status_code == 429:
        raise ProviderError("rate_limited")
    if 500 <= resp.status_code < 600:
        raise ProviderError("server_error")
    raise ProviderError(f"http_{resp.status_code}")


def _bounded_row_timeout(row: sqlite3.Row, limit_seconds: float | None = None) -> float:
    """Honor a shorter interactive budget without relaxing the saved runtime timeout."""
    configured_timeout = float(row["timeout_seconds"])
    return min(configured_timeout, limit_seconds) if limit_seconds is not None else configured_timeout


def _new_client(
    row: sqlite3.Row, *, timeout_seconds: float | None = None
) -> httpx.AsyncClient:
    """Create an HTTP client with the runtime timeout or a stricter local budget."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_bounded_row_timeout(row, timeout_seconds)),
        transport=_TEST_TRANSPORT,
    )


def _new_model_discovery_client() -> httpx.AsyncClient:
    """Create the deliberately short-lived client used before a provider is saved.

    Discovery receives a newly typed credential, so it must not inherit a
    configurable 300-second provider timeout or follow a redirect to a host
    that was not validated by the admin route.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_MODEL_DISCOVERY_TIMEOUT_SECONDS),
        follow_redirects=False,
        transport=_TEST_TRANSPORT,
    )


def _safe_discovery_extra_headers(extra: dict[str, Any] | None) -> dict[str, str]:
    """Keep gateway headers that cannot replace discovery authentication.

    The saved-provider path preserves legacy arbitrary headers.  For the
    one-shot discovery path, omit malformed/framing-sensitive headers rather
    than letting a transient form value override the supplied Bearer token.
    """
    if not isinstance(extra, dict):
        return {}
    raw_headers = extra.get("headers")
    if not isinstance(raw_headers, dict):
        return {}

    headers: dict[str, str] = {}
    for raw_name, raw_value in raw_headers.items():
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        lowered = name.lower()
        # RFC 9110 field names are visible ASCII tokens.  Rejecting control
        # characters also prevents a value from becoming a second header.
        if (
            not name
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
            or lowered in _DISCOVERY_BLOCKED_EXTRA_HEADERS
        ):
            continue
        value = str(raw_value)
        if "\r" in value or "\n" in value:
            continue
        headers[name] = value
    return headers


def _model_discovery_chat_headers(api_key: str, extra: dict[str, Any] | None) -> dict[str, str]:
    """Build OpenAI-compatible discovery headers without accepting auth overrides."""
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(_safe_discovery_extra_headers(extra))
    return headers


def _model_discovery_error_for_status(resp: httpx.Response) -> None:
    """Map list-endpoint statuses to stable codes with no provider body text."""
    if resp.status_code == 200:
        return
    if resp.status_code in (401, 403):
        raise ProviderError("auth_error")
    if resp.status_code in (404, 405, 501):
        # A generic gateway is allowed not to expose a model-catalog route.
        raise ProviderError("model_discovery_unsupported")
    if resp.status_code == 429:
        raise ProviderError("rate_limited")
    if 500 <= resp.status_code < 600:
        raise ProviderError("server_error")
    raise ProviderError(f"http_{resp.status_code}")


async def _model_discovery_json(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    params: dict[str, str] | None = None,
) -> Any:
    """Read one model-list payload with a hard byte cap before JSON parsing."""
    async with client.stream("GET", url, headers=headers, params=params) as resp:
        _model_discovery_error_for_status(resp)
        content_length = resp.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > _MODEL_DISCOVERY_MAX_RESPONSE_BYTES:
                    raise ProviderError("model_list_response_too_large")
            except ValueError:
                # A malformed response header is not useful to administrators;
                # the streamed body cap below remains the authoritative guard.
                pass

        chunks: list[bytes] = []
        total_bytes = 0
        async for chunk in resp.aiter_bytes():
            total_bytes += len(chunk)
            if total_bytes > _MODEL_DISCOVERY_MAX_RESPONSE_BYTES:
                raise ProviderError("model_list_response_too_large")
            chunks.append(chunk)

    try:
        return json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        raise ProviderError("invalid_model_list_response") from None


def _safe_model_text(value: Any, max_length: int) -> str | None:
    """Accept bounded display data only; model names are provider-controlled input."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_length or any(ord(char) < 32 for char in text):
        return None
    return text


def _model_options_from_payload(payload: Any) -> list[dict[str, str]]:
    """Normalize the common ``data[].id`` catalog shape used by both HTTP APIs."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ProviderError("invalid_model_list_response")

    raw_items = payload["data"]
    options: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        model_id = _safe_model_text(item.get("id"), _MODEL_DISCOVERY_MAX_ID_LENGTH)
        if model_id is None:
            continue
        label = (
            _safe_model_text(
                item.get("display_name", item.get("name", model_id)),
                _MODEL_DISCOVERY_MAX_LABEL_LENGTH,
            )
            or model_id
        )
        options.append({"id": model_id, "label": label})

    # An empty account catalog is valid.  Non-empty data with no usable IDs is
    # not: silently rendering an empty selector would conceal an upstream
    # contract mismatch.
    if raw_items and not options:
        raise ProviderError("invalid_model_list_response")
    return options


def _append_model_options(target: list[dict[str, str]], incoming: list[dict[str, str]]) -> None:
    """Merge pages while preserving provider order and rejecting silent truncation."""
    seen = {option["id"] for option in target}
    for option in incoming:
        if option["id"] in seen:
            continue
        if len(target) >= _MODEL_DISCOVERY_MAX_MODELS:
            raise ProviderError("model_list_limit_exceeded")
        target.append(option)
        seen.add(option["id"])


def _normalize_usage(raw: dict[str, Any] | None) -> dict[str, int | None] | None:
    """各协议 usage 统一为 {prompt_tokens, completion_tokens}；无数据返回 None。"""
    if not raw:
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": int(prompt) if prompt is not None else None,
        "completion_tokens": int(completion) if completion is not None else None,
    }

# ---------------------------------------------------------------- chat_completions 协议

def _cc_url(row: sqlite3.Row, suffix: str) -> str:
    # base_url 约定已含版本路径（如 https://host/v1），直接拼接端点名
    return f"{row['base_url'].rstrip('/')}/{suffix}"


def _cc_headers(row: sqlite3.Row, api_key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    extra_headers = _extra(row).get("headers")
    if isinstance(extra_headers, dict):  # 网关类服务常要求额外头
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    return headers


def _cc_body(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    stream: bool,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Translate the orchestrator's private media marker only at the provider
    # boundary. This keeps base64 bytes out of persistence, SSE, and logs while
    # allowing image/audio-capable OpenAI-compatible models to receive them.
    wire_messages = _openai_messages(messages)
    body: dict[str, Any] = {
        "model": row["model"],
        "messages": wire_messages,
        "stream": stream,
    }
    extra = _extra(row)
    # 温度/最大 token 等采样参数只有显式配置才下发，避免覆盖服务端默认
    for key in ("temperature", "max_tokens", "top_p"):
        if key in extra:
            body[key] = extra[key]
    # RAG settings are request-scoped overrides; provider configuration remains
    # the fallback for ordinary chat and for deployments without the new page.
    body.update(_sampling_overrides(sampling))
    if max_tokens_override is not None:
        # Smoke checks only need a valid reply, so never wait for a full runtime response.
        body["max_tokens"] = max_tokens_override
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _parse_embedding_vectors(payload: Any) -> list[list[float]]:
    """Validate an OpenAI-compatible embeddings payload before it reaches RAG.

    A 200 response is not enough for an embedding health check: accepting an
    empty or non-numeric vector would defer a bad configuration until document
    ingestion.  The raised code is deliberately generic so malformed provider
    bodies never escape into an admin response.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ProviderError("invalid_embedding_response")
    indexed_vectors: list[tuple[int, list[float]]] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            raise ProviderError("invalid_embedding_response")
        index = item.get("index", 0)
        values = item.get("embedding")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ProviderError("invalid_embedding_response")
        if not isinstance(values, list) or not values:
            raise ProviderError("invalid_embedding_response")
        vector: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProviderError("invalid_embedding_response")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ProviderError("invalid_embedding_response")
            vector.append(numeric)
        indexed_vectors.append((index, vector))
    if not indexed_vectors:
        raise ProviderError("invalid_embedding_response")
    return [vector for _, vector in sorted(indexed_vectors, key=lambda pair: pair[0])]


async def _embed_strict(
    row: sqlite3.Row,
    texts: list[str],
    *,
    timeout_seconds: float | None = None,
) -> list[list[float]]:
    """Call the exact provider row's embedding endpoint without role lookup.

    Admin smoke tests must verify the row being edited, even when it has not
    yet been enabled or is transitioning between roles.  Keeping this strict
    primitive separate also prevents ``embed_texts`` and the smoke path from
    drifting into different wire contracts.
    """
    if row["protocol"] != "chat_completions":
        raise ProviderError("embedding_not_supported")
    api_key = _provider_api_key(row)
    async with _new_client(row, timeout_seconds=timeout_seconds) as client:
        resp = await client.post(
            _cc_url(row, "embeddings"),
            headers=_cc_headers(row, api_key),
            json={"model": row["model"], "input": texts},
        )
        _raise_for_status(resp)
        return _parse_embedding_vectors(resp.json())


async def _cc_complete(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp = await client.post(
        _cc_url(row, "chat/completions"),
        headers=_cc_headers(row, api_key),
        json=_cc_body(
            row,
            messages,
            stream=False,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    )
    _raise_for_status(resp)
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    # OpenAI-compatible reasoning models may return chain-of-thought in a
    # sibling field. Only the user-facing content field crosses this adapter
    # boundary; reasoning_content/analysis fields are intentionally ignored.
    text = message.get("content") or ""
    return {
        "text": text,
        "model": row["model"],
        "usage": _normalize_usage(data.get("usage")),
        "provider_id": row["id"],
    }


async def _cc_stream(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    async with client.stream(
        "POST",
        _cc_url(row, "chat/completions"),
        headers=_cc_headers(row, api_key),
        json=_cc_body(
            row,
            messages,
            stream=True,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    ) as resp:
        _raise_for_status(resp)
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]":
                # Preserve an explicit completion marker so a probe can
                # accept providers that finish without a visible token.
                yield {"done": True}
                break
            chunk = json.loads(payload)
            choice = (chunk.get("choices") or [{}])[0]
            delta_payload = choice.get("delta") or {}
            # Some gateways emit reasoning_content beside content for the same
            # token. Forwarding only content keeps the stream answer-only.
            delta = delta_payload.get("content")
            if isinstance(delta, str):
                yield {"delta": str(delta)}
            usage = _normalize_usage(chunk.get("usage"))
            if usage:
                yield {"usage": usage}


# ---------------------------------------------------------------- Responses API 协议

def _responses_url(row: sqlite3.Row, suffix: str) -> str:
    """Build the OpenAI Responses endpoint from the configured versioned base."""

    return f"{row['base_url'].rstrip('/')}/{suffix}"


def _responses_content(content: Any) -> Any:
    """Map internal content into the Responses input shape.

    Text-only messages stay strings for broad gateway compatibility.  Media
    blocks use the documented ``input_text``/``input_image`` forms and fall
    back to a truthful text description when a block is not portable.
    """

    if not isinstance(content, list):
        return str(content or "")
    mapped: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            mapped.append({"type": "input_text", "text": block["text"]})
            continue
        if block.get("type") != "media_attachment":
            continue
        mime_type = str(block.get("mime_type") or "").split(";", 1)[0].lower()
        data = block.get("data")
        if mime_type.startswith("image/") and isinstance(data, str) and data:
            mapped.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{data}",
                }
            )
        else:
            mapped.append({"type": "input_text", "text": _media_fallback_text(block)})
    return mapped


def _responses_body(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    stream: bool,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a Responses request while preserving system instructions."""

    extra = _extra(row)
    system_parts = [
        _text_content(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
    ]
    body: dict[str, Any] = {
        "model": row["model"],
        "input": [
            {
                "role": message.get("role", "user"),
                "content": _responses_content(message.get("content", "")),
            }
            for message in messages
            if message.get("role") != "system"
        ],
        "stream": stream,
    }
    if system_parts:
        body["instructions"] = "\n".join(part for part in system_parts if part)
    if max_tokens_override is not None:
        body["max_output_tokens"] = max_tokens_override
    elif "max_tokens" in extra:
        body["max_output_tokens"] = extra["max_tokens"]
    if "temperature" in extra:
        body["temperature"] = extra["temperature"]
    # Responses uses the same sampling names as the admin RAG contract.
    body.update(_sampling_overrides(sampling))
    return body


def _responses_text(payload: dict[str, Any]) -> str:
    """Extract user-visible text without ever exposing reasoning fields."""

    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def _responses_complete(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call ``/responses`` and normalize its output into the adapter contract."""

    resp = await client.post(
        _responses_url(row, "responses"),
        headers=_cc_headers(row, api_key),
        json=_responses_body(
            row,
            messages,
            stream=False,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    )
    _raise_for_status(resp)
    payload = resp.json()
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        usage = {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
        }
    return {
        "text": _responses_text(payload if isinstance(payload, dict) else {}),
        "model": row["model"],
        "usage": _normalize_usage(usage),
        "provider_id": row["id"],
    }


async def _responses_stream(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Normalize Responses SSE events into delta/usage/completion events."""

    async with client.stream(
        "POST",
        _responses_url(row, "responses"),
        headers=_cc_headers(row, api_key),
        json=_responses_body(
            row,
            messages,
            stream=True,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    ) as resp:
        _raise_for_status(resp)
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]":
                yield {"done": True}
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str):
                    yield {"delta": delta}
            elif event_type == "response.completed":
                response = event.get("response") or {}
                usage = response.get("usage") or event.get("usage") or {}
                normalized = _normalize_usage(
                    {
                        "prompt_tokens": usage.get("input_tokens"),
                        "completion_tokens": usage.get("output_tokens"),
                    }
                )
                if normalized:
                    yield {"usage": normalized}
                yield {"done": True}


# ---------------------------------------------------------------- anthropic_messages 协议


def _media_fallback_text(block: dict[str, Any]) -> str:
    """Describe unsupported media without exposing its token or binary data."""

    mime_type = str(block.get("mime_type") or "media").split(";", 1)[0].lower()
    kind = mime_type.split("/", 1)[0] if "/" in mime_type else "media"
    filename = str(block.get("filename") or "附件")[:160]
    return f"[已附加{kind}文件：{filename}。当前模型接口不支持直接解析该媒体，请根据文字继续回答。]"


def _audio_format(mime_type: str) -> str | None:
    """Return the two audio formats accepted by Chat Completions input_audio."""

    normalized = mime_type.split(";", 1)[0].lower()
    return {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
    }.get(normalized)


def _openai_content(content: Any) -> Any:
    """Map internal text/media blocks to OpenAI Chat Completions content."""

    if not isinstance(content, list):
        return content
    mapped: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "media_attachment":
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                mapped.append({"type": "text", "text": block["text"]})
            continue
        mime_type = str(block.get("mime_type") or "").split(";", 1)[0].lower()
        data = block.get("data")
        if not isinstance(data, str) or not data:
            mapped.append({"type": "text", "text": _media_fallback_text(block)})
        elif mime_type.startswith("image/"):
            mapped.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{data}"},
                }
            )
        else:
            audio_format = _audio_format(mime_type)
            if mime_type.startswith("audio/") and audio_format:
                mapped.append(
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data, "format": audio_format},
                    }
                )
            else:
                # Chat Completions has no portable video block. Keep the user
                # request usable for providers that only understand text.
                mapped.append({"type": "text", "text": _media_fallback_text(block)})
    return mapped


def _openai_messages(messages: list[dict]) -> list[dict[str, Any]]:
    """Copy messages while converting only their content fields."""

    return [
        {**message, "content": _openai_content(message.get("content"))}
        for message in messages
    ]


def _anthropic_content(content: Any) -> Any:
    """Map internal blocks to Anthropic's text/image content block format."""

    if not isinstance(content, list):
        return content
    mapped: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            mapped.append({"type": "text", "text": block["text"]})
            continue
        if block.get("type") != "media_attachment":
            continue
        mime_type = str(block.get("mime_type") or "").split(";", 1)[0].lower()
        data = block.get("data")
        if mime_type.startswith("image/") and isinstance(data, str) and data:
            mapped.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime_type, "data": data},
                }
            )
        else:
            # Anthropic's Messages API currently has no portable audio/video
            # block, so retain a truthful text-only description instead.
            mapped.append({"type": "text", "text": _media_fallback_text(block)})
    return mapped


def _text_content(content: Any) -> str:
    """Project a message into safe text for protocols without multimodal input."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block.get("type") == "media_attachment":
            parts.append(_media_fallback_text(block))
    return "\n".join(parts)

def _anthropic_url(row: sqlite3.Row) -> str:
    # 官方端点是 {base}/v1/messages；base 已带 /v1 时不重复拼接
    base = row["base_url"].rstrip("/")
    return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"


def _anthropic_body(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    stream: bool,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = _extra(row)
    # Anthropic 协议里 system 是顶层字段而非消息角色，必须剥离
    system_parts = [
        _text_content(m.get("content", ""))
        for m in messages
        if m.get("role") == "system"
    ]
    chat = [m for m in messages if m.get("role") != "system"]
    body: dict[str, Any] = {
        "model": row["model"],
        "max_tokens": (
            max_tokens_override
            if max_tokens_override is not None
            else int(extra.get("max_tokens", 2048))
        ),  # This protocol requires an explicit output budget.
        "messages": [
            {
                "role": m.get("role", "user"),
                "content": _anthropic_content(m.get("content", "")),
            }
            for m in chat
        ],
        "stream": stream,
    }
    if system_parts:
        body["system"] = "\n".join(p for p in system_parts if p)
    if "temperature" in extra:
        body["temperature"] = extra["temperature"]
    body.update(_sampling_overrides(sampling))
    return body


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}


async def _anthropic_complete(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp = await client.post(
        _anthropic_url(row),
        headers=_anthropic_headers(api_key),
        json=_anthropic_body(
            row,
            messages,
            stream=False,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    )
    _raise_for_status(resp)
    data = resp.json()
    # 响应 content 是块数组，只拼接文本块（工具块本层不消费）
    text = "".join(
        str(block.get("text", ""))
        for block in data.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )
    raw_usage = data.get("usage") or {}
    usage = _normalize_usage(
        {
            "prompt_tokens": raw_usage.get("input_tokens"),
            "completion_tokens": raw_usage.get("output_tokens"),
        }
    )
    return {"text": text, "model": row["model"], "usage": usage, "provider_id": row["id"]}


async def _anthropic_stream(
    client: httpx.AsyncClient,
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    async with client.stream(
        "POST",
        _anthropic_url(row),
        headers=_anthropic_headers(api_key),
        json=_anthropic_body(
            row,
            messages,
            stream=True,
            max_tokens_override=max_tokens_override,
            sampling=sampling,
        ),
    ) as resp:
        _raise_for_status(resp)
        usage: dict[str, int | None] = {"prompt_tokens": None, "completion_tokens": None}
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            chunk = json.loads(line[len("data: "):].strip())
            event_type = chunk.get("type")
            if event_type == "content_block_delta":
                text = ((chunk.get("delta") or {}).get("text"))
                if isinstance(text, str):
                    yield {"delta": text}
            elif event_type == "message_start":
                # input_tokens 在消息开头给出
                start_usage = ((chunk.get("message") or {}).get("usage")) or {}
                if start_usage.get("input_tokens") is not None:
                    usage["prompt_tokens"] = int(start_usage["input_tokens"])
            elif event_type == "message_delta":
                # output_tokens 在消息收尾给出
                delta_usage = chunk.get("usage") or {}
                if delta_usage.get("output_tokens") is not None:
                    usage["completion_tokens"] = int(delta_usage["output_tokens"])
            elif event_type == "message_stop":
                yield {"done": True}
                break
        normalized = _normalize_usage(usage)
        if normalized:
            yield {"usage": normalized}


def _chat_completions_models_url(base_url: str) -> str:
    """Build the standard OpenAI-compatible catalog endpoint from a versioned base."""
    return f"{base_url.strip().rstrip('/')}/models"


def _anthropic_models_url(base_url: str) -> str:
    """Build Anthropic's catalog endpoint without duplicating an existing ``/v1``."""
    base = base_url.strip().rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


async def discover_models(
    protocol: str,
    base_url: str,
    api_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, bool | list[dict[str, str]]]:
    """Fetch a bounded remote model catalog before a provider configuration is saved.

    Only HTTP protocols with a verified list contract are queried.  Every
    raised error is a stable safe code; no URL, request headers, upstream body,
    or entered API key is retained.
    """
    if protocol not in ("chat_completions", "anthropic_messages", "responses"):
        raise ProviderError("unsupported_protocol")

    try:
        async with _new_model_discovery_client() as client:
            if protocol in ("chat_completions", "responses"):
                payload = await _model_discovery_json(
                    client,
                    _chat_completions_models_url(base_url),
                    _model_discovery_chat_headers(api_key, extra),
                )
                models: list[dict[str, str]] = []
                _append_model_options(models, _model_options_from_payload(payload))
                return {"supported": True, "models": models}

            models = []
            after_id: str | None = None
            for page_index in range(_MODEL_DISCOVERY_MAX_PAGES):
                params = {"limit": str(_MODEL_DISCOVERY_PAGE_SIZE)}
                if after_id is not None:
                    params["after_id"] = after_id
                payload = await _model_discovery_json(
                    client,
                    _anthropic_models_url(base_url),
                    _anthropic_headers(api_key),
                    params=params,
                )
                _append_model_options(models, _model_options_from_payload(payload))

                if not isinstance(payload, dict) or not isinstance(
                    payload.get("has_more", False), bool
                ):
                    raise ProviderError("invalid_model_list_response")
                if not payload.get("has_more"):
                    return {"supported": True, "models": models}

                next_after_id = _safe_model_text(
                    payload.get("last_id"), _MODEL_DISCOVERY_MAX_ID_LENGTH
                )
                if next_after_id is None or next_after_id == after_id:
                    raise ProviderError("invalid_model_list_response")
                if (
                    len(models) >= _MODEL_DISCOVERY_MAX_MODELS
                    or page_index == _MODEL_DISCOVERY_MAX_PAGES - 1
                ):
                    raise ProviderError("model_list_limit_exceeded")
                after_id = next_after_id

            # The loop always returns or raises.  Keep this defensive fallback
            # safe if pagination logic is changed later.
            raise ProviderError("model_list_limit_exceeded")
    except ProviderError:
        raise
    except (httpx.TimeoutException, TimeoutError):
        raise ProviderError("timeout") from None
    except httpx.HTTPError:
        raise ProviderError("network_error") from None
    except Exception:
        # Do not let malformed provider data or client-library messages reach
        # an API response or log path; they can include request context.
        raise ProviderError("provider_error") from None


# ---------------------------------------------------------------- 调度层

async def _complete_strict(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    timeout_seconds: float | None = None,
    max_tokens_override: int | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make one provider call without fallback, optionally under a stricter probe budget."""
    api_key = _provider_api_key(row)
    protocol = row["protocol"]
    if protocol == "chat_completions":
        async with _new_client(row, timeout_seconds=timeout_seconds) as client:
            return await _cc_complete(
                client,
                row,
                api_key,
                messages,
                max_tokens_override=max_tokens_override,
                sampling=sampling,
            )
    if protocol == "anthropic_messages":
        async with _new_client(row, timeout_seconds=timeout_seconds) as client:
            return await _anthropic_complete(
                client,
                row,
                api_key,
                messages,
                max_tokens_override=max_tokens_override,
                sampling=sampling,
            )
    if protocol == "responses":
        async with _new_client(row, timeout_seconds=timeout_seconds) as client:
            return await _responses_complete(
                client,
                row,
                api_key,
                messages,
                max_tokens_override=max_tokens_override,
                sampling=sampling,
            )
    raise ProviderError(f"unknown_protocol_{protocol}")


async def _stream_strict(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    sampling: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """单 provider 流式调用；事件为 {"delta"} / {"usage"}。"""
    api_key = _provider_api_key(row)
    protocol = row["protocol"]
    if protocol == "chat_completions":
        async with _new_client(row) as client:
            async for event in _cc_stream(client, row, api_key, messages, sampling=sampling):
                yield event
    elif protocol == "anthropic_messages":
        async with _new_client(row) as client:
            async for event in _anthropic_stream(client, row, api_key, messages, sampling=sampling):
                yield event
    elif protocol == "responses":
        async with _new_client(row) as client:
            async for event in _responses_stream(client, row, api_key, messages, sampling=sampling):
                yield event
    else:
        raise ProviderError(f"unknown_protocol_{protocol}")


def _candidate_rows(
    role: str,
    media_requirements: list[tuple[str, str]] | None = None,
    *,
    database_path: str | None = None,
) -> list[sqlite3.Row]:
    """Load fallback candidates and omit rows unable to process current media.

    Detached workers may carry a database path captured from their enqueueing
    request.  Accepting that path here keeps provider selection on the same
    SQLite file even when process configuration changes between requests.
    """

    conn = db_connect(database_path or get_config().resolved_database_path)
    try:
        rows = _candidate_rows_from_connection(conn, role)
        if not media_requirements:
            return rows
        # The route rejects an incompatible request before persistence. This
        # second filter keeps direct/internal calls on the same safe contract.
        return [
            row
            for row in rows
            if all(
                _supports_media_attachment(row, kind, mime_type)
                for kind, mime_type in media_requirements
            )
        ]
    finally:
        conn.close()


async def complete(
    messages: list[dict],
    *,
    role: str = "primary",
    database_path: str | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict | None:
    """非流式调用 LLM。

    返回 ``{"text", "model", "usage", "provider_id"}``；
    无可用 provider 或全部调用失败（已按 primary→fallback 尝试回退）返回
    ``None``，调用方据此走模板降级合成。
    """
    for row in _candidate_rows(
        role,
        _media_requirements_from_messages(messages),
        database_path=database_path,
    ):
        try:
            return await _complete_strict(row, messages, sampling=sampling)
        except Exception as exc:
            _log_failure(row, exc)
    return None


async def stream_deltas(
    messages: list[dict],
    *,
    role: str = "primary",
    sampling: dict[str, Any] | None = None,
) -> AsyncIterator[dict]:
    """逐 token 流式产出 ``{"delta": str}``；结束产出
    ``{"done": True, "model", "usage", "provider_id"}``。

    回退策略：首段内容产出之前失败可切换下一个候选 provider；一旦已向
    调用方输出过内容就不再切换（拼接两家模型的文本比失败更糟），直接收尾。
    """
    emitted_any = False
    final_model: str | None = None
    final_usage: dict[str, Any] | None = None
    final_provider_id: str | None = None
    for row in _candidate_rows(role, _media_requirements_from_messages(messages)):
        try:
            # Capture identity before consuming deltas so a mid-stream failure
            # after emitted text still attributes its terminal usage correctly.
            final_model = row["model"]
            final_provider_id = row["id"]
            async for event in _stream_strict(row, messages, sampling=sampling):
                if "delta" in event:
                    emitted_any = True
                    yield {"delta": event["delta"]}
                elif "usage" in event:
                    final_usage = event["usage"]
            break
        except Exception as exc:
            _log_failure(row, exc)
            if emitted_any:
                break
    yield {
        "done": True,
        "model": final_model,
        "usage": final_usage,
        "provider_id": final_provider_id,
    }


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """用 role='embedding' 的启用 provider 批量嵌入。

    未配置或调用失败返回 ``None``（调用方降级本地哈希嵌入，蓝图 §1）。
    仅 chat_completions 协议有标准 embeddings 端点；其余协议直接返回 None。
    """
    if not texts:
        return []
    conn = db_connect(get_config().resolved_database_path)
    try:
        row = get_enabled_provider(conn, "embedding")
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return await _embed_strict(row, texts)
    except Exception as exc:
        _log_failure(row, exc)
        return None


_RERANK_SMOKE_MESSAGES = [
    {
        "role": "system",
        "content": "Return only a JSON array ordering the two candidate indices by relevance.",
    },
    {
        "role": "user",
        "content": "Query: alpha\nCandidates:\n[0] alpha\n[1] beta",
    },
]


def _is_complete_rerank_order(text: str) -> bool:
    """Accept only a complete two-candidate JSON order for the smoke contract.

    The runtime retriever is deliberately more forgiving of partial model
    output.  A connection test should be stricter: it is the administrator's
    explicit proof that the selected provider can perform the configured
    rerank capability, without persisting the provider's response text.
    """
    match = re.search(r"\[[^\[\]]*\]", text, re.DOTALL)
    if match is None:
        return False
    try:
        values = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(values, list) or len(values) != 2:
        return False
    order: list[int] = []
    for value in values:
        if isinstance(value, bool):
            return False
        try:
            index = int(value)
        except (TypeError, ValueError):
            return False
        if index not in (0, 1) or index in order:
            return False
        order.append(index)
    return set(order) == {0, 1}


async def _smoke_chat(row: sqlite3.Row) -> None:
    """Prove chat reachability at first text token instead of full completion."""
    api_key = _provider_api_key(row)
    messages = [{"role": "user", "content": "health-check"}]
    protocol = row["protocol"]
    if protocol == "chat_completions":
        async with _new_client(row, timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS) as client:
            await _first_text_delta(
                _cc_stream(
                    client,
                    row,
                    api_key,
                    messages,
                    max_tokens_override=_PROVIDER_TEST_CHAT_MAX_TOKENS,
                )
            )
        return
    if protocol == "anthropic_messages":
        async with _new_client(row, timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS) as client:
            await _first_text_delta(
                _anthropic_stream(
                    client,
                    row,
                    api_key,
                    messages,
                    max_tokens_override=_PROVIDER_TEST_CHAT_MAX_TOKENS,
                )
            )
        return
    if protocol == "responses":
        async with _new_client(row, timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS) as client:
            await _first_text_delta(
                _responses_stream(
                    client,
                    row,
                    api_key,
                    messages,
                    max_tokens_override=_PROVIDER_TEST_CHAT_MAX_TOKENS,
                )
            )
        return
    raise ProviderError(f"unknown_protocol_{protocol}")


async def _first_text_delta(events: AsyncIterator[dict[str, Any]]) -> None:
    """Consume a probe until a protocol proves the configured model is usable.

    A present ``delta`` key is meaningful even when its value is empty: some
    reasoning models reserve the first event for hidden work.  A completion
    marker also proves the upstream understood the request.  An iterator that
    emits neither marker remains an invalid response rather than a false pass.
    """
    # Explicitly close the generator on success so an HTTP/SSE stream
    # cannot keep this interactive request open while the provider finishes its reply.
    async with aclosing(events):
        async for event in events:
            if "delta" in event or event.get("done"):
                return
    raise ProviderError("invalid_chat_response")


async def _smoke_rerank(row: sqlite3.Row) -> None:
    """Prove the chat-based rerank contract used by the RAG retriever."""
    result = await _complete_strict(
        row,
        _RERANK_SMOKE_MESSAGES,
        timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS,
        max_tokens_override=_PROVIDER_TEST_STRUCTURED_MAX_TOKENS,
    )
    if not isinstance(result, dict) or not _is_complete_rerank_order(str(result.get("text", ""))):
        raise ProviderError("invalid_rerank_response")


async def test_provider(row: sqlite3.Row) -> dict[str, Any]:
    """Run the smallest role-appropriate live provider capability check.

    The stored result intentionally contains only safe metadata.  In
    particular, it never retains the one-time prompt, the provider response,
    URL, request headers, or decrypted API key.
    """
    raw_role = str(row["role"])
    capability = _SMOKE_CAPABILITY_BY_ROLE.get(raw_role)
    reported_role = raw_role if capability is not None else "unknown"
    start = time.perf_counter()
    error: str | None = None
    try:
        # The outer deadline also covers HTTP setup and future adapters that
        # might not use the shared HTTP client helper.
        async with asyncio.timeout(_bounded_row_timeout(row, _PROVIDER_TEST_TIMEOUT_SECONDS)):
            if capability == "chat":
                await _smoke_chat(row)
            elif capability == "embedding":
                await _embed_strict(
                    row,
                    ["health-check"],
                    timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS,
                )
            elif capability == "rerank":
                await _smoke_rerank(row)
            else:
                raise ProviderError("unsupported_provider_role")
        ok = True
    except Exception as exc:
        ok = False
        error = _error_label(exc)
        _log_failure(row, exc)
    return {
        "ok": ok,
        "role": reported_role,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "model": row["model"],
        "error": error,
        "tested_at": utc_now_iso(),
    }


async def test_transient_provider(
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    role: str = "none",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the normal smoke contract against unsaved administrator form values.

    This synthetic row exists only for the duration of the coroutine.  It
    deliberately carries no database handle or encrypted-key field, so a
    connection test cannot create a provider, change its last-test status, or
    retain the one-time API key outside process memory.
    """
    transient_row: dict[str, Any] = {
        "id": "transient-provider-test",
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "role": role,
        "timeout_seconds": _PROVIDER_TEST_TIMEOUT_SECONDS,
        "extra_json": json.dumps(extra or {}, ensure_ascii=False),
        "_transient_api_key": api_key,
    }
    # Adapter helpers only depend on mapping-style provider fields. The saved
    # row annotation remains for their database callers, while this path keeps
    # the transient credential out of SQLite and the audit pipeline.
    return await test_provider(transient_row)  # type: ignore[arg-type]
