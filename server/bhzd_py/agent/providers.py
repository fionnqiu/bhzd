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

安全红线（为什么这么设计）：
- API Key 只经 ``decrypt_key`` 在内存中短暂出现，永不写日志；日志只记录
  ``_error_label`` 产生的安全短码（不含 URL/请求体，讯飞签名 URL 含签名，
  因此异常对象本身绝不进日志）。
- 所有 HTTP 调用使用 provider 行上的 ``timeout_seconds``；讯飞 WebSocket
  用 ``asyncio.timeout`` 包住整个会话，防止对端挂起拖死编排循环。
"""

from __future__ import annotations

import asyncio
import base64
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
# configured capability.  Unassigned/disabled rows are rejected by the admin
# route before any network request is attempted.
_SMOKE_CAPABILITY_BY_ROLE = {
    "primary": "chat",
    "fallback": "chat",
    "embedding": "embedding",
    "rerank": "rerank",
}
_SAFE_PROVIDER_ERROR_CODES = {
    "auth_error",
    "rate_limited",
    "server_error",
    "provider_unavailable",
    "unsupported_protocol",
    "unsupported_provider_role",
    "embedding_not_supported",
    "invalid_embedding_response",
    "invalid_chat_response",
    "invalid_rerank_response",
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


def _new_client(row: sqlite3.Row) -> httpx.AsyncClient:
    """按行上的超时配置创建 AsyncClient；测试经 _TEST_TRANSPORT 接管网络。"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(float(row["timeout_seconds"])),
        transport=_TEST_TRANSPORT,
    )


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


def _cc_body(row: sqlite3.Row, messages: list[dict], *, stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"model": row["model"], "messages": messages, "stream": stream}
    extra = _extra(row)
    # 温度/最大 token 等采样参数只有显式配置才下发，避免覆盖服务端默认
    for key in ("temperature", "max_tokens", "top_p"):
        if key in extra:
            body[key] = extra[key]
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


async def _embed_strict(row: sqlite3.Row, texts: list[str]) -> list[list[float]]:
    """Call the exact provider row's embedding endpoint without role lookup.

    Admin smoke tests must verify the row being edited, even when it has not
    yet been enabled or is transitioning between roles.  Keeping this strict
    primitive separate also prevents ``embed_texts`` and the smoke path from
    drifting into different wire contracts.
    """
    if row["protocol"] != "chat_completions":
        raise ProviderError("embedding_not_supported")
    api_key = decrypt_key(row)
    async with _new_client(row) as client:
        resp = await client.post(
            _cc_url(row, "embeddings"),
            headers=_cc_headers(row, api_key),
            json={"model": row["model"], "input": texts},
        )
        _raise_for_status(resp)
        return _parse_embedding_vectors(resp.json())


async def _cc_complete(
    client: httpx.AsyncClient, row: sqlite3.Row, api_key: str, messages: list[dict]
) -> dict[str, Any]:
    resp = await client.post(
        _cc_url(row, "chat/completions"),
        headers=_cc_headers(row, api_key),
        json=_cc_body(row, messages, stream=False),
    )
    _raise_for_status(resp)
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    return {
        "text": text,
        "model": row["model"],
        "usage": _normalize_usage(data.get("usage")),
        "provider_id": row["id"],
    }


async def _cc_stream(
    client: httpx.AsyncClient, row: sqlite3.Row, api_key: str, messages: list[dict]
) -> AsyncIterator[dict[str, Any]]:
    async with client.stream(
        "POST",
        _cc_url(row, "chat/completions"),
        headers=_cc_headers(row, api_key),
        json=_cc_body(row, messages, stream=True),
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
            delta = ((choice.get("delta") or {}).get("content"))
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


def _anthropic_body(row: sqlite3.Row, messages: list[dict], *, stream: bool) -> dict[str, Any]:
    extra = _extra(row)
    # Anthropic 协议里 system 是顶层字段而非消息角色，必须剥离
    system_parts = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
    chat = [m for m in messages if m.get("role") != "system"]
    body: dict[str, Any] = {
        "model": row["model"],
        "max_tokens": int(extra.get("max_tokens", 2048)),  # 该协议必填
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
    client: httpx.AsyncClient, row: sqlite3.Row, api_key: str, messages: list[dict]
) -> dict[str, Any]:
    resp = await client.post(
        _anthropic_url(row),
        headers=_anthropic_headers(api_key),
        json=_anthropic_body(row, messages, stream=False),
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
    client: httpx.AsyncClient, row: sqlite3.Row, api_key: str, messages: list[dict]
) -> AsyncIterator[dict[str, Any]]:
    async with client.stream(
        "POST",
        _anthropic_url(row),
        headers=_anthropic_headers(api_key),
        json=_anthropic_body(row, messages, stream=True),
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
        normalized = _normalize_usage(usage)
        if normalized:
            yield {"usage": normalized}


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


def _xunfei_frame(row: sqlite3.Row, messages: list[dict], domain: str) -> dict[str, Any]:
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
                "max_tokens": int(extra.get("max_tokens", 2048)),
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
    row: sqlite3.Row, api_key: str, messages: list[dict]
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
    frame = _xunfei_frame(row, messages, domain)
    timeout = float(row["timeout_seconds"])
    usage: dict[str, int | None] = {"prompt_tokens": None, "completion_tokens": None}
    # asyncio.timeout 包住整个 WS 会话：对端不回包时必须在行超时内退出
    async with asyncio.timeout(timeout):
        async with websockets.connect(  # type: ignore[union-attr]
            url, open_timeout=min(timeout, 10.0), close_timeout=5
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

async def _complete_strict(row: sqlite3.Row, messages: list[dict]) -> dict[str, Any]:
    """单次调用（不兜底）；失败抛 ProviderError/网络异常，由上层决定回退。"""
    api_key = decrypt_key(row)
    protocol = row["protocol"]
    if protocol == "chat_completions":
        async with _new_client(row) as client:
            return await _cc_complete(client, row, api_key, messages)
    if protocol == "anthropic_messages":
        async with _new_client(row) as client:
            return await _anthropic_complete(client, row, api_key, messages)
    if protocol in ("xunfei_spark", "xunfei_xingchen"):
        text_parts: list[str] = []
        usage: dict[str, Any] | None = None
        async for event in _xunfei_stream(row, api_key, messages):
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


async def _stream_strict(
    row: sqlite3.Row, messages: list[dict]
) -> AsyncIterator[dict[str, Any]]:
    """单 provider 流式调用；事件为 {"delta"} / {"usage"}。"""
    api_key = decrypt_key(row)
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
    """Prove that a chat-capable provider accepts a harmless minimal prompt."""
    result = await _complete_strict(row, [{"role": "user", "content": "health-check"}])
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise ProviderError("invalid_chat_response")


async def _smoke_rerank(row: sqlite3.Row) -> None:
    """Prove the chat-based rerank contract used by the RAG retriever."""
    result = await _complete_strict(row, _RERANK_SMOKE_MESSAGES)
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
        if capability == "chat":
            await _smoke_chat(row)
        elif capability == "embedding":
            await _embed_strict(row, ["health-check"])
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
