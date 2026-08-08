"""provider 抽象层测试（蓝图 §1/§6.6，agent/providers.py）。

网络出口全部经 httpx.MockTransport 接管（providers._TEST_TRANSPORT 钩子），
不引入 respx 等额外依赖，也不触碰真实网络；异步接口用 asyncio.run 驱动
（pytest 9 环境无 anyio 插件，同步测试内自旋事件循环即可）。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac as hmac_module
import json
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from bhzd_py.agent import providers
from bhzd_py.config import get_config, reset_config_cache
from bhzd_py.db import apply_migrations, connect, utc_now_iso
from bhzd_py.security import encrypt_secret, load_encryption_key

MESSAGES = [{"role": "user", "content": "你好"}]


@pytest.fixture()
def db(tmp_db_path, monkeypatch):
    """临时库 + 固定加密密钥；测试结束复位传输钩子与配置缓存。"""
    monkeypatch.setenv("BHZD_CONFIG_ENCRYPTION_KEY", secrets.token_hex(32))
    reset_config_cache()
    conn = connect(get_config().resolved_database_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    yield
    providers._TEST_TRANSPORT = None
    reset_config_cache()


def _add_provider(
    *,
    protocol: str = "chat_completions",
    role: str = "primary",
    base_url: str = "https://primary.example.com/v1",
    model: str = "demo-model",
    api_key: str = "sk-test",
    enabled: int = 1,
    timeout_seconds: float = 10,
    extra: dict | None = None,
) -> str:
    conn = connect(get_config().resolved_database_path)
    try:
        provider_id = uuid.uuid4().hex
        key = load_encryption_key(get_config().config_encryption_key)
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO provider_configs (id, name, protocol, base_url, model,"
            " api_key_encrypted, role, enabled, timeout_seconds, extra_json,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                provider_id,
                f"测试-{role}",
                protocol,
                base_url,
                model,
                encrypt_secret(api_key, key),
                role,
                enabled,
                timeout_seconds,
                json.dumps(extra or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
        return provider_id
    finally:
        conn.close()


def _use_transport(handler) -> None:
    providers._TEST_TRANSPORT = httpx.MockTransport(handler)


def _provider_row(provider_id: str):
    """Fetch the exact saved row because connection tests bypass role lookup."""
    conn = connect(get_config().resolved_database_path)
    try:
        row = conn.execute(
            "SELECT * FROM provider_configs WHERE id = ?", (provider_id,)
        ).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


# ---------------------------------------------------------------- 基础查询/解密

def test_get_enabled_provider_and_decrypt(db):
    provider_id = _add_provider(role="primary", api_key="sk-roundtrip")
    conn = connect(get_config().resolved_database_path)
    try:
        row = providers.get_enabled_provider(conn, "primary")
        assert row is not None and row["id"] == provider_id
        # 禁用与角色不匹配都查不到
        assert providers.get_enabled_provider(conn, "fallback") is None
    finally:
        conn.close()
    assert providers.decrypt_key(row) == "sk-roundtrip"

    _add_provider(role="fallback", enabled=0, base_url="https://fb.example.com/v1")
    conn = connect(get_config().resolved_database_path)
    try:
        assert providers.get_enabled_provider(conn, "fallback") is None  # enabled=0
    finally:
        conn.close()


# ---------------------------------------------------------------- chat_completions 协议

def test_chat_completions_payload_and_parse(db):
    provider_id = _add_provider(role="primary", api_key="sk-payload")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "你好，世界"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )

    _use_transport(handler)
    result = asyncio.run(providers.complete(MESSAGES))
    assert result is not None
    assert result["text"] == "你好，世界"
    assert result["model"] == "demo-model"
    assert result["provider_id"] == provider_id
    assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}
    # 端点/鉴权/请求体符合 OpenAI 兼容协议
    assert captured["url"] == "https://primary.example.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-payload"
    assert captured["json"]["model"] == "demo-model"
    assert captured["json"]["messages"] == MESSAGES


def test_complete_failover_primary_to_fallback(db):
    _add_provider(role="primary", base_url="https://primary.example.com/v1")
    fallback_id = _add_provider(role="fallback", base_url="https://fallback.example.com/v1", model="fb-model")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary.example.com":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "回退答案"}}], "usage": None},
        )

    _use_transport(handler)
    result = asyncio.run(providers.complete(MESSAGES))
    assert result is not None
    assert result["text"] == "回退答案"
    assert result["provider_id"] == fallback_id
    assert result["usage"] is None


def test_complete_returns_none_when_all_fail(db):
    _add_provider(role="primary", base_url="https://primary.example.com/v1")
    _add_provider(role="fallback", base_url="https://fallback.example.com/v1")
    _use_transport(lambda request: httpx.Response(500, json={}))
    assert asyncio.run(providers.complete(MESSAGES)) is None


def test_complete_returns_none_without_provider(db):
    assert asyncio.run(providers.complete(MESSAGES)) is None


def test_stream_deltas_yields_tokens_then_done(db):
    provider_id = _add_provider(role="primary")
    sse_body = (
        'data: {"choices": [{"delta": {"content": "你"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "好"}}]}\n\n'
        'data: {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}\n\n'
        "data: [DONE]\n\n"
    )
    _use_transport(
        lambda request: httpx.Response(
            200, content=sse_body.encode("utf-8"), headers={"content-type": "text/event-stream"}
        )
    )

    async def collect():
        return [event async for event in providers.stream_deltas(MESSAGES)]

    events = asyncio.run(collect())
    assert events[0] == {"delta": "你"}
    assert events[1] == {"delta": "好"}
    assert events[-1] == {
        "done": True,
        "model": "demo-model",
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        "provider_id": provider_id,
    }


# ---------------------------------------------------------------- anthropic_messages 协议

def test_anthropic_complete_maps_usage_and_system(db):
    _add_provider(
        role="primary",
        protocol="anthropic_messages",
        base_url="https://api.anthropic.example.com",
        api_key="sk-ant",
    )
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Anthropic 回答"}],
                "usage": {"input_tokens": 11, "output_tokens": 4},
            },
        )

    _use_transport(handler)
    messages = [{"role": "system", "content": "设定"}, *MESSAGES]
    result = asyncio.run(providers.complete(messages))
    assert result is not None
    assert result["text"] == "Anthropic 回答"
    assert result["usage"] == {"prompt_tokens": 11, "completion_tokens": 4}
    # base 不带 /v1 时自动补全端点；system 提升为顶层字段而非消息
    assert captured["url"] == "https://api.anthropic.example.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["system"] == "设定"
    assert all(m["role"] != "system" for m in captured["json"]["messages"])


# ---------------------------------------------------------------- 保存前模型发现

def test_discover_chat_models_uses_bearer_safe_headers_and_fixed_timeout(db):
    """OpenAI-compatible catalogs may add gateway metadata but never replace auth."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["tenant"] = request.headers.get("x-tenant")
        captured["cookie"] = request.headers.get("cookie")
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-demo", "display_name": "Demo model"},
                    {"id": "gpt-demo", "display_name": "Duplicate"},
                    {"id": "gpt-plain"},
                    {"id": 42},
                ]
            },
        )

    _use_transport(handler)
    api_key = "sk-discovery-private"
    result = asyncio.run(
        providers.discover_models(
            "chat_completions",
            "https://catalog.example.test/v1",
            api_key,
            extra={
                "headers": {
                    "X-Tenant": "school-a",
                    "Authorization": "Bearer must-not-replace-input-key",
                    "Cookie": "must-not-forward",
                    "X-Invalid": "line-one\r\nline-two",
                }
            },
        )
    )

    assert result == {
        "supported": True,
        "models": [
            {"id": "gpt-demo", "label": "Demo model"},
            {"id": "gpt-plain", "label": "gpt-plain"},
        ],
    }
    assert captured["method"] == "GET"
    assert captured["url"] == "https://catalog.example.test/v1/models"
    assert captured["authorization"] == f"Bearer {api_key}"
    assert captured["tenant"] == "school-a"
    assert captured["cookie"] is None
    timeout = captured["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["connect"] == 10.0
    assert api_key not in json.dumps(result)


def test_discover_anthropic_models_uses_normalized_path_and_bounded_pagination(db):
    """Anthropic pagination must use cursor IDs and retain only bounded model metadata."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        after_id = request.url.params.get("after_id")
        if after_id is None:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-first", "display_name": "Claude First"}],
                    "has_more": True,
                    "last_id": "claude-first",
                },
            )
        assert after_id == "claude-first"
        return httpx.Response(
            200,
            json={
                "data": [{"id": "claude-second", "display_name": "Claude Second"}],
                "has_more": False,
                "last_id": "claude-second",
            },
        )

    _use_transport(handler)
    result = asyncio.run(
        providers.discover_models(
            "anthropic_messages",
            "https://api.anthropic.example.test/v1/",
            "sk-ant-private",
        )
    )

    assert result == {
        "supported": True,
        "models": [
            {"id": "claude-first", "label": "Claude First"},
            {"id": "claude-second", "label": "Claude Second"},
        ],
    }
    assert len(calls) == 2
    assert str(calls[0].url) == "https://api.anthropic.example.test/v1/models?limit=100"
    assert calls[0].headers["x-api-key"] == "sk-ant-private"
    assert calls[0].headers["anthropic-version"] == "2023-06-01"
    assert calls[1].url.params["after_id"] == "claude-first"


@pytest.mark.parametrize("protocol", ["xunfei_spark", "xunfei_xingchen"])
def test_discover_xunfei_models_returns_unsupported_without_network(db, protocol):
    """The signed WebSocket adapters do not have an account model-list contract yet."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    _use_transport(handler)
    assert asyncio.run(
        providers.discover_models(protocol, "https://xf.example.test", "xf-secret")
    ) == {"supported": False, "models": []}
    assert called is False


def test_discover_models_uses_safe_error_codes_and_never_echoes_provider_content(db):
    """HTTP bodies and transport exception text can contain secrets, so only codes escape."""
    api_key = "sk-discovery-never-echo"
    provider_body = f"credential={api_key} url=https://catalog.example.test/private"

    _use_transport(lambda _request: httpx.Response(401, text=provider_body))
    with pytest.raises(providers.ProviderError) as auth_error:
        asyncio.run(
            providers.discover_models(
                "chat_completions", "https://catalog.example.test/v1", api_key
            )
        )
    assert str(auth_error.value) == "auth_error"
    assert api_key not in str(auth_error.value)
    assert "catalog.example.test" not in str(auth_error.value)

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out with {api_key}")

    _use_transport(timeout_handler)
    with pytest.raises(providers.ProviderError) as timeout_error:
        asyncio.run(
            providers.discover_models(
                "chat_completions", "https://catalog.example.test/v1", api_key
            )
        )
    assert str(timeout_error.value) == "timeout"
    assert api_key not in str(timeout_error.value)


def test_discover_models_does_not_follow_provider_redirects(db):
    """A validated base URL must not become an unvalidated redirect destination."""
    calls = 0

    def redirect_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "https://other.example.test/models"})

    _use_transport(redirect_handler)
    with pytest.raises(providers.ProviderError, match="http_302"):
        asyncio.run(
            providers.discover_models(
                "chat_completions", "https://catalog.example.test/v1", "sk-test"
            )
        )
    assert calls == 1


def test_discover_models_rejects_oversized_or_unbounded_catalogs(db, monkeypatch):
    """Both raw response bytes and normalized model options have explicit hard caps."""
    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_MAX_RESPONSE_BYTES", 8)
    _use_transport(lambda _request: httpx.Response(200, json={"data": [{"id": "too-large"}]}))
    with pytest.raises(providers.ProviderError, match="model_list_response_too_large"):
        asyncio.run(
            providers.discover_models(
                "chat_completions", "https://catalog.example.test/v1", "sk-test"
            )
        )

    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_MAX_RESPONSE_BYTES", 512 * 1024)
    oversized_models = [
        {"id": f"model-{index}"} for index in range(providers._MODEL_DISCOVERY_MAX_MODELS + 1)
    ]
    _use_transport(lambda _request: httpx.Response(200, json={"data": oversized_models}))
    with pytest.raises(providers.ProviderError, match="model_list_limit_exceeded"):
        asyncio.run(
            providers.discover_models(
                "chat_completions", "https://catalog.example.test/v1", "sk-test"
            )
        )


def test_discover_anthropic_models_stops_after_the_bounded_page_limit(db):
    """A provider cannot keep the admin request paging forever with ``has_more``."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "data": [{"id": f"claude-{calls}"}],
                "has_more": True,
                "last_id": f"claude-{calls}",
            },
        )

    _use_transport(handler)
    with pytest.raises(providers.ProviderError, match="model_list_limit_exceeded"):
        asyncio.run(
            providers.discover_models(
                "anthropic_messages", "https://api.anthropic.example.test", "sk-test"
            )
        )
    assert calls == providers._MODEL_DISCOVERY_MAX_PAGES


# ---------------------------------------------------------------- 嵌入

def test_embed_texts_none_without_embedding_provider(db):
    _add_provider(role="primary")  # 只有对话角色，没有 embedding 角色
    assert asyncio.run(providers.embed_texts(["文本"])) is None


def test_embed_texts_returns_vectors(db):
    _add_provider(role="embedding", base_url="https://emb.example.com/v1", model="emb-model")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://emb.example.com/v1/embeddings"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {"model": "emb-model", "input": ["甲", "乙"]}
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.3]},
                    {"index": 0, "embedding": [0.1, 0.4]},  # 乱序返回须按 index 归位
                ]
            },
        )

    _use_transport(handler)
    vectors = asyncio.run(providers.embed_texts(["甲", "乙"]))
    assert vectors == [[0.1, 0.4], [0.2, 0.3]]


# ---------------------------------------------------------------- 角色化连接测试

@pytest.mark.parametrize("role", ["primary", "fallback", "none"])
def test_provider_smoke_uses_first_chat_delta_for_chat_capable_roles(db, role):
    """Chat roles, including an unassigned row, prove reachability with one SSE delta."""
    provider_id = _add_provider(
        role=role,
        api_key="sk-private-chat-key",
        timeout_seconds=300,
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            content=(
                'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    _use_transport(handler)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))
    assert result["ok"] is True
    assert result["role"] == role
    assert result["error"] is None
    assert set(result) == {"ok", "role", "latency_ms", "model", "error", "tested_at"}
    assert captured["path"] == "/v1/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["messages"] == [
        {"role": "user", "content": "health-check"}
    ]
    # The test route only needs proof of a usable stream, so it avoids waiting
    # for a full generated response or the provider's terminal event.
    assert body["stream"] is True
    assert body["max_tokens"] == providers._PROVIDER_TEST_CHAT_MAX_TOKENS
    timeout = captured["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["connect"] == 8.0
    # Admin results/audit snapshots must retain metadata, never a key or prompt.
    result_json = json.dumps(result)
    assert "sk-private-chat-key" not in result_json
    assert "health-check" not in result_json


def test_provider_smoke_uses_first_anthropic_delta(db):
    """Anthropic's SSE probe follows the same one-token, first-delta contract."""
    provider_id = _add_provider(
        protocol="anthropic_messages",
        role="primary",
        base_url="https://anthropic.example.test",
        timeout_seconds=300,
        extra={"max_tokens": 2048},
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            content=(
                'event: content_block_delta\n'
                'data: {"type": "content_block_delta", "delta": {"text": "ok"}}\n\n'
            ).encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    _use_transport(handler)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))

    assert result["ok"] is True
    assert captured["path"] == "/v1/messages"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["stream"] is True
    assert body["max_tokens"] == providers._PROVIDER_TEST_CHAT_MAX_TOKENS
    timeout = captured["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["read"] == 8.0


def test_provider_smoke_closes_chat_stream_after_first_effective_delta(db):
    """The probe must not wait for trailing tokens after the first useful delta."""
    provider_id = _add_provider(role="primary", timeout_seconds=300)
    captured: dict[str, object] = {}

    class FirstDeltaThenBlocks(httpx.AsyncByteStream):
        """Expose a second never-ending chunk so early stream closure is observable."""

        def __init__(self) -> None:
            self.closed = False
            self.requested_second_chunk = False

        async def __aiter__(self):
            # Whitespace is not enough to declare the configured model usable.
            yield (
                b'data: {"choices": [{"delta": {"content": " "}}]}\n\n'
                b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
            )
            self.requested_second_chunk = True
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            self.closed = True

    response_stream = FirstDeltaThenBlocks()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            stream=response_stream,
            headers={"content-type": "text/event-stream"},
        )

    _use_transport(handler)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))

    assert result["ok"] is True
    assert captured["body"] == {
        "model": "demo-model",
        "messages": [{"role": "user", "content": "health-check"}],
        "stream": True,
        "max_tokens": providers._PROVIDER_TEST_CHAT_MAX_TOKENS,
        "stream_options": {"include_usage": True},
    }
    assert response_stream.closed is True
    assert response_stream.requested_second_chunk is False


def test_provider_smoke_returns_timeout_after_its_wall_clock_budget(db, monkeypatch):
    """The outer deadline stops adapters that do not use the shared HTTP client."""
    provider_id = _add_provider(role="primary", timeout_seconds=300)

    async def slow_smoke(_row):
        await asyncio.sleep(1)

    monkeypatch.setattr(providers, "_PROVIDER_TEST_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(providers, "_smoke_chat", slow_smoke)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))

    assert result["ok"] is False
    assert result["error"] == "timeout"
    assert result["latency_ms"] < 500


def test_provider_smoke_uses_embeddings_for_embedding_role(db):
    provider_id = _add_provider(
        role="embedding",
        base_url="https://embedding.example.test/v1",
        model="embedding-model",
        api_key="sk-private-embedding-key",
        timeout_seconds=300,
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.2, -0.1]}]})

    _use_transport(handler)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))
    assert result["ok"] is True
    assert result["role"] == "embedding"
    assert captured["path"] == "/v1/embeddings"
    assert captured["body"] == {"model": "embedding-model", "input": ["health-check"]}
    timeout = captured["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["write"] == 8.0
    assert "sk-private-embedding-key" not in json.dumps(result)


def test_provider_smoke_uses_json_order_for_rerank_role(db):
    provider_id = _add_provider(
        role="rerank",
        base_url="https://rerank.example.test/v1",
        api_key="sk-private-rerank-key",
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 0]"}}]})

    _use_transport(handler)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))
    assert result["ok"] is True
    assert result["role"] == "rerank"
    assert captured["path"] == "/v1/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert len(messages) == 2
    assert "candidate indices" in messages[0]["content"]
    assert "sk-private-rerank-key" not in json.dumps(result)
    assert "[1, 0]" not in json.dumps(result)


def test_provider_smoke_redacts_untrusted_provider_error(db, monkeypatch):
    provider_id = _add_provider(role="primary", api_key="sk-private-redaction-key")

    async def unsafe_smoke(_row):
        # Simulate a future buggy adapter; the public result must still be safe.
        raise providers.ProviderError("unexpected-secret-value")

    monkeypatch.setattr(providers, "_smoke_chat", unsafe_smoke)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))
    assert result["ok"] is False
    assert result["error"] == "provider_error"
    result_json = json.dumps(result)
    assert "unexpected-secret-value" not in result_json
    assert "sk-private-redaction-key" not in result_json


# ---------------------------------------------------------------- 讯飞签名（纯函数，免网络）

def test_provider_smoke_passes_short_budget_to_xunfei(db, monkeypatch):
    """The WebSocket adapter receives the same short test budget as HTTP adapters."""
    provider_id = _add_provider(
        protocol="xunfei_spark",
        role="primary",
        timeout_seconds=300,
        extra={"max_tokens": 2048},
    )
    captured: dict[str, object] = {}

    async def fake_xunfei_stream(
        _row,
        _api_key,
        _messages,
        *,
        timeout_seconds=None,
        max_tokens_override=None,
        close_timeout_seconds=None,
    ):
        captured["timeout_seconds"] = timeout_seconds
        captured["max_tokens_override"] = max_tokens_override
        captured["close_timeout_seconds"] = close_timeout_seconds
        yield {"delta": "ok"}

    monkeypatch.setattr(providers, "_xunfei_stream", fake_xunfei_stream)
    result = asyncio.run(providers.test_provider(_provider_row(provider_id)))

    assert result["ok"] is True
    assert captured == {
        "timeout_seconds": 8.0,
        "max_tokens_override": providers._PROVIDER_TEST_CHAT_MAX_TOKENS,
        "close_timeout_seconds": providers._PROVIDER_TEST_STREAM_CLOSE_TIMEOUT_SECONDS,
    }


def test_xunfei_frame_uses_short_override_without_changing_runtime_default(db):
    """The test-only cap must not overwrite a saved Xunfei generation limit."""
    provider_id = _add_provider(
        protocol="xunfei_spark",
        extra={"max_tokens": 2048},
    )
    row = _provider_row(provider_id)
    runtime_frame = providers._xunfei_frame(row, MESSAGES, "generalv3.5")
    smoke_frame = providers._xunfei_frame(
        row,
        MESSAGES,
        "generalv3.5",
        max_tokens_override=16,
    )

    assert runtime_frame["parameter"]["chat"]["max_tokens"] == 2048
    assert smoke_frame["parameter"]["chat"]["max_tokens"] == 16


def test_xunfei_signed_ws_url_signature(db):
    url = providers._signed_ws_url(
        "https://spark-api.xf-yun.com", "/v3.5/chat", "mykey:mysecret"
    )
    parsed = urlparse(url)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "spark-api.xf-yun.com"
    assert parsed.path == "/v3.5/chat"
    query = parse_qs(parsed.query)
    date = query["date"][0]
    authorization = json.loads(base64.b64decode(query["authorization"][0]).decode("utf-8"))
    assert authorization["api_key"] == "mykey"
    assert authorization["algorithm"] == "hmac-sha256"
    # 用相同算法独立重算签名，验证签名内容正确
    signature_origin = f"host: spark-api.xf-yun.com\ndate: {date}\nGET /v3.5/chat HTTP/1.1"
    expected = base64.b64encode(
        hmac_module.new(b"mysecret", signature_origin.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    assert authorization["signature"] == expected

    # 单 token 配置：key 本身充当签名材料（与旧栈行为一致）
    url_single = providers._signed_ws_url("https://spark-api.xf-yun.com", "/v1/chat", "onlykey")
    query_single = parse_qs(urlparse(url_single).query)
    auth_single = json.loads(base64.b64decode(query_single["authorization"][0]).decode("utf-8"))
    assert auth_single["api_key"] == "onlykey"
    assert auth_single["signature"]  # 仍能产出签名而非报错
