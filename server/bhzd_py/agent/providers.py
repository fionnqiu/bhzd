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
  ``_error_label`` 产生的安全短码（不含 URL/请求体，讯飞签名 URL 含签名，
  因此异常对象本身绝不进日志）。
- 正常 HTTP/讯飞调用使用 provider 行上的 ``timeout_seconds``；管理员连接测试
  另有短时总预算，避免交互操作被慢供应商长期占用。
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import aclosing
import hashlib
import hmac
import json
import logging
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover - 依赖在 pyproject 中，防御性兜底
    websockets = None  # type: ignore[assignment]

from ..config import get_config
from ..db import connect as db_connect
from ..db import utc_now_iso
from ..security import decrypt_secret, load_encryption_key

logger = logging.getLogger(__name__)

# 测试钩子：测试用 httpx.MockTransport 替换网络出口，生产永远为 None。
# 放在模块级而非参数透传，是为了让公开接口签名保持稳定（其它域已按签名编码）。
_TEST_TRANSPORT: httpx.AsyncBaseTransport | None = None

_PROTOCOLS = ("chat_completions", "anthropic_messages", "xunfei_spark", "xunfei_xingchen")

# A provider's saved role determines the smallest request that can prove its
# configured capability. An enabled but unassigned provider uses the neutral
# chat probe, avoiding unsafe guesses about embedding/rerank capability from a model name.
_SMOKE_CAPABILITY_BY_ROLE = {
    "primary": "chat",
    "fallback": "chat",
    "embedding": "embedding",
    "rerank": "rerank",
    "none": "chat",
}
# A connectivity check is an interactive admin action, not a normal model run.
# Keep it short even when the saved runtime timeout permits several minutes.
_PROVIDER_TEST_TIMEOUT_SECONDS = 8.0
# A chat probe only needs one actual output token. Structured rerank validation
# retains a larger budget because it must receive a complete JSON ordering.
_PROVIDER_TEST_CHAT_MAX_TOKENS = 1
_PROVIDER_TEST_STRUCTURED_MAX_TOKENS = 16
# Returning after the first token must not inherit the normal WebSocket close wait.
_PROVIDER_TEST_STREAM_CLOSE_TIMEOUT_SECONDS = 0.25
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

# 讯飞星火：模型名 → (API 版本路径, domain)，沿用旧栈已验证的路由表
_SPARK_MODEL_ROUTES: dict[str, tuple[str, str]] = {
    "generalv3.5": ("v3.5", "generalv3.5"),
    "generalv3": ("v3.1", "generalv3"),
    "generalv2": ("v2.1", "generalv2"),
    "general": ("v1.1", "general"),
    "4.0Ultra": ("v4.0", "4.0Ultra"),
    "pro-128k": ("v3.5", "pro-128k"),
    "max-32k": ("v3.5", "max-32k"),
    "lite": ("v1.1", "lite"),
}


class ProviderError(RuntimeError):
    """provider 调用失败；消息只能是本模块构造的安全短码（可进日志/管理端）。"""


# ---------------------------------------------------------------- 公共查询/解密

def get_enabled_provider(db: sqlite3.Connection, role: str) -> sqlite3.Row | None:
    """取指定角色（primary/fallback/embedding/rerank）的启用 provider 行。

    set-role 接口保证同角色至多一行；ORDER BY 只是防御性兜底。
    """
    return db.execute(
        "SELECT * FROM provider_configs WHERE role = ? AND enabled = 1"
        " ORDER BY updated_at DESC LIMIT 1",
        (role,),
    ).fetchone()


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
        if re.fullmatch(r"xunfei_error_\d+", label):
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
) -> dict[str, Any]:
    body: dict[str, Any] = {"model": row["model"], "messages": messages, "stream": stream}
    extra = _extra(row)
    # 温度/最大 token 等采样参数只有显式配置才下发，避免覆盖服务端默认
    for key in ("temperature", "max_tokens", "top_p"):
        if key in extra:
            body[key] = extra[key]
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
) -> dict[str, Any]:
    resp = await client.post(
        _cc_url(row, "chat/completions"),
        headers=_cc_headers(row, api_key),
        json=_cc_body(
            row,
            messages,
            stream=False,
            max_tokens_override=max_tokens_override,
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
        ),
    ) as resp:
        _raise_for_status(resp)
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            choice = (chunk.get("choices") or [{}])[0]
            delta_payload = choice.get("delta") or {}
            # Some gateways emit reasoning_content beside content for the same
            # token. Forwarding only content keeps the stream answer-only.
            delta = delta_payload.get("content")
            if delta:
                yield {"delta": str(delta)}
            usage = _normalize_usage(chunk.get("usage"))
            if usage:
                yield {"usage": usage}


# ---------------------------------------------------------------- anthropic_messages 协议

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
) -> dict[str, Any]:
    extra = _extra(row)
    # Anthropic 协议里 system 是顶层字段而非消息角色，必须剥离
    system_parts = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
    chat = [m for m in messages if m.get("role") != "system"]
    body: dict[str, Any] = {
        "model": row["model"],
        "max_tokens": (
            max_tokens_override
            if max_tokens_override is not None
            else int(extra.get("max_tokens", 2048))
        ),  # This protocol requires an explicit output budget.
        "messages": [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in chat
        ],
        "stream": stream,
    }
    if system_parts:
        body["system"] = "\n".join(p for p in system_parts if p)
    if "temperature" in extra:
        body["temperature"] = extra["temperature"]
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
) -> dict[str, Any]:
    resp = await client.post(
        _anthropic_url(row),
        headers=_anthropic_headers(api_key),
        json=_anthropic_body(
            row,
            messages,
            stream=False,
            max_tokens_override=max_tokens_override,
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
                if text:
                    yield {"delta": str(text)}
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

    Only HTTP protocols with a verified list contract are queried.  Xunfei's
    configured runtime uses signed WebSockets and has no account-entitlement
    catalog contract here, so it intentionally reports unsupported without
    making an outbound request.  Every raised error is a stable safe code; no
    URL, request headers, upstream body, or entered API key is retained.
    """
    if protocol in ("xunfei_spark", "xunfei_xingchen"):
        return {"supported": False, "models": []}
    if protocol not in ("chat_completions", "anthropic_messages"):
        raise ProviderError("unsupported_protocol")

    try:
        async with _new_model_discovery_client() as client:
            if protocol == "chat_completions":
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


# ---------------------------------------------------------------- 讯飞 WebSocket 协议（星火/星辰）

def _signed_ws_url(base_url: str, path: str, api_key: str) -> str:
    """构造讯飞 HMAC-SHA256 签名 WebSocket URL。

    签名知识沿用旧栈（已生产验证）：api_key 形如 "APIKey:APISecret"；
    signature_origin 固定为 host/date/request-line 三行。签名单次有效窗口
    由对端控制，因此每次调用都重新取 UTC 时间签名。
    """
    parsed = urlparse(base_url)
    host = parsed.netloc or parsed.path
    key, _, secret = api_key.partition(":")
    if not secret:
        # 单 token 配置：以 key 本身充当签名材料（与旧栈行为一致）
        secret = key
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), signature_origin.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    authorization = base64.b64encode(
        json.dumps(
            {
                "api_key": key,
                "algorithm": "hmac-sha256",
                "headers": "host date request-line",
                "signature": signature,
            }
        ).encode("utf-8")
    ).decode("ascii")
    query = urlencode({"authorization": authorization, "date": date, "host": host})
    return urlunparse(("wss", host, path, "", query, ""))


def _spark_route(model: str, extra: dict[str, Any]) -> tuple[str, str]:
    """星火模型 → (API 版本, domain)；extra 里的 version/domain 可覆盖默认值。"""
    mapped = _SPARK_MODEL_ROUTES.get(model)
    version = str(extra.get("version") or (mapped[0] if mapped else "v3.5"))
    domain = str(extra.get("domain") or (mapped[1] if mapped else model))
    return version, domain


def _xunfei_frame(
    row: sqlite3.Row,
    messages: list[dict],
    domain: str,
    *,
    max_tokens_override: int | None = None,
) -> dict[str, Any]:
    """星火/星辰共用同一帧族，仅路径与 domain 不同。"""
    extra = _extra(row)
    return {
        "header": {
            "app_id": str(extra.get("app_id", "")),
            "uid": str(extra.get("uid", "")),
        },
        "parameter": {
            "chat": {
                "domain": domain,
                "max_tokens": (
                    max_tokens_override
                    if max_tokens_override is not None
                    else int(extra.get("max_tokens", 2048))
                ),  # Probes use a short cap while runtime requests keep their saved limit.
                "temperature": float(extra.get("temperature", 0.5)),
            }
        },
        "payload": {
            "message": {
                "text": [
                    {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
                    for m in messages
                ]
            }
        },
    }


async def _xunfei_stream(
    row: sqlite3.Row,
    api_key: str,
    messages: list[dict],
    *,
    timeout_seconds: float | None = None,
    max_tokens_override: int | None = None,
    close_timeout_seconds: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if websockets is None:  # pragma: no cover
        raise ProviderError("provider_unavailable")
    extra = _extra(row)
    if row["protocol"] == "xunfei_spark":
        version, domain = _spark_route(row["model"], extra)
        path = f"/{version}/chat"  # 官方星火 WS 路径：/{version}/chat
    else:
        domain = str(extra.get("domain") or row["model"])
        path = "/v1/wss/spark/chat"  # 星辰固定路径
    url = _signed_ws_url(row["base_url"], path, api_key)
    frame = _xunfei_frame(
        row,
        messages,
        domain,
        max_tokens_override=max_tokens_override,
    )
    timeout = _bounded_row_timeout(row, timeout_seconds)
    usage: dict[str, int | None] = {"prompt_tokens": None, "completion_tokens": None}
    # asyncio.timeout 包住整个 WS 会话：对端不回包时必须在行超时内退出
    async with asyncio.timeout(timeout):
        async with websockets.connect(  # type: ignore[union-attr]
            url,
            open_timeout=min(timeout, 10.0),
            close_timeout=(
                min(close_timeout_seconds, timeout)
                if close_timeout_seconds is not None
                else 5
            ),
        ) as ws:
            await ws.send(json.dumps(frame, ensure_ascii=False))
            async for raw in ws:
                packet = json.loads(raw)
                header = packet.get("header") or {}
                code = header.get("code", 0)
                if code not in (0, "0", None):
                    # 对端错误码是数字，无敏感信息
                    raise ProviderError(f"xunfei_error_{code}")
                payload = packet.get("payload") or {}
                choices = payload.get("choices") or {}
                for item in choices.get("text") or []:
                    content = item.get("content")
                    if content:
                        yield {"delta": str(content)}
                raw_usage = payload.get("usage") or {}
                if isinstance(raw_usage.get("text"), dict):  # 部分帧把 usage 嵌在 usage.text
                    raw_usage = raw_usage["text"]
                if raw_usage:
                    prompt = raw_usage.get("prompt_tokens", raw_usage.get("text_in"))
                    completion = raw_usage.get("completion_tokens", raw_usage.get("text_out"))
                    if prompt is not None:
                        usage["prompt_tokens"] = int(prompt)
                    if completion is not None:
                        usage["completion_tokens"] = int(completion)
                if header.get("status") == 2:  # 讯飞协议：status=2 为最后一帧
                    break
    normalized = _normalize_usage(usage)
    if normalized:
        yield {"usage": normalized}


# ---------------------------------------------------------------- 调度层

async def _complete_strict(
    row: sqlite3.Row,
    messages: list[dict],
    *,
    timeout_seconds: float | None = None,
    max_tokens_override: int | None = None,
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
            )
    if protocol == "anthropic_messages":
        async with _new_client(row, timeout_seconds=timeout_seconds) as client:
            return await _anthropic_complete(
                client,
                row,
                api_key,
                messages,
                max_tokens_override=max_tokens_override,
            )
    if protocol in ("xunfei_spark", "xunfei_xingchen"):
        text_parts: list[str] = []
        usage: dict[str, Any] | None = None
        async for event in _xunfei_stream(
            row,
            api_key,
            messages,
            timeout_seconds=timeout_seconds,
            max_tokens_override=max_tokens_override,
        ):
            if "delta" in event:
                text_parts.append(event["delta"])
            elif "usage" in event:
                usage = event["usage"]
        return {
            "text": "".join(text_parts),
            "model": row["model"],
            "usage": usage,
            "provider_id": row["id"],
        }
    raise ProviderError(f"unknown_protocol_{protocol}")


async def _stream_strict(row: sqlite3.Row, messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """单 provider 流式调用；事件为 {"delta"} / {"usage"}。"""
    api_key = _provider_api_key(row)
    protocol = row["protocol"]
    if protocol == "chat_completions":
        async with _new_client(row) as client:
            async for event in _cc_stream(client, row, api_key, messages):
                yield event
    elif protocol == "anthropic_messages":
        async with _new_client(row) as client:
            async for event in _anthropic_stream(client, row, api_key, messages):
                yield event
    elif protocol in ("xunfei_spark", "xunfei_xingchen"):
        async for event in _xunfei_stream(row, api_key, messages):
            yield event
    else:
        raise ProviderError(f"unknown_protocol_{protocol}")


def _candidate_rows(role: str) -> list[sqlite3.Row]:
    """按回退顺序取候选 provider 行（行数据已物化，连接可立即关闭）。"""
    conn = db_connect(get_config().resolved_database_path)
    try:
        rows: list[sqlite3.Row] = []
        primary_row = get_enabled_provider(conn, role)
        if primary_row is not None:
            rows.append(primary_row)
        if role == "primary":
            # 回退链只对对话主角色有意义（PRD-04 §3.3：一主一备）
            fallback_row = get_enabled_provider(conn, "fallback")
            if fallback_row is not None:
                rows.append(fallback_row)
        return rows
    finally:
        conn.close()


async def complete(messages: list[dict], *, role: str = "primary") -> dict | None:
    """非流式调用 LLM。

    返回 ``{"text", "model", "usage", "provider_id"}``；
    无可用 provider 或全部调用失败（已按 primary→fallback 尝试回退）返回
    ``None``，调用方据此走模板降级合成。
    """
    for row in _candidate_rows(role):
        try:
            return await _complete_strict(row, messages)
        except Exception as exc:
            _log_failure(row, exc)
    return None


async def stream_deltas(
    messages: list[dict], *, role: str = "primary"
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
    for row in _candidate_rows(role):
        try:
            # Capture identity before consuming deltas so a mid-stream failure
            # after emitted text still attributes its terminal usage correctly.
            final_model = row["model"]
            final_provider_id = row["id"]
            async for event in _stream_strict(row, messages):
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
    if protocol in ("xunfei_spark", "xunfei_xingchen"):
        await _first_text_delta(
            _xunfei_stream(
                row,
                api_key,
                messages,
                timeout_seconds=_PROVIDER_TEST_TIMEOUT_SECONDS,
                max_tokens_override=_PROVIDER_TEST_CHAT_MAX_TOKENS,
                close_timeout_seconds=_PROVIDER_TEST_STREAM_CLOSE_TIMEOUT_SECONDS,
            )
        )
        return
    raise ProviderError(f"unknown_protocol_{protocol}")


async def _first_text_delta(events: AsyncIterator[dict[str, Any]]) -> None:
    """Consume a probe stream only until a provider proves it can emit text."""
    # Explicitly close the generator on success so an HTTP/SSE or WebSocket stream
    # cannot keep this interactive request open while the provider finishes its reply.
    async with aclosing(events):
        async for event in events:
            delta = event.get("delta")
            if isinstance(delta, str) and delta.strip():
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
        # The outer deadline also covers WebSocket setup and future adapters that
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
