"""provider 抽象层测试（蓝图 §1/§6.6，agent/providers.py）。

网络出口全部经 httpx.MockTransport 接管（providers._TEST_TRANSPORT 钩子），
不引入 respx 等额外依赖，也不触碰真实网络；异步接口用 asyncio.run 驱动
（pytest 9 环境无 anyio 插件，同步测试内自旋事件循环即可）。
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid

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

def test_get_provider_by_role_prefers_grader_and_falls_back_to_primary(db):
    """A dedicated grader wins; an absent grader resolves to the enabled primary row."""

    primary_id = _add_provider(role="primary", base_url="https://primary.example.com/v1")
    conn = connect(get_config().resolved_database_path)
    try:
        fallback_row = providers.get_provider_by_role(conn, "grader")
        assert fallback_row is not None
        assert fallback_row["id"] == primary_id
        assert fallback_row["role"] == "primary"
    finally:
        conn.close()

    grader_id = _add_provider(
        role="grader",
        base_url="https://grader.example.com/v1",
        model="grader-model",
    )
    conn = connect(get_config().resolved_database_path)
    try:
        grader_row = providers.get_provider_by_role(conn, "grader")
        assert grader_row is not None
        assert grader_row["id"] == grader_id
        assert grader_row["role"] == "grader"
    finally:
        conn.close()


def test_complete_grader_role_uses_primary_when_grader_is_unset(db):
    """Runtime grader calls share the helper's primary fallback contract."""

    primary_id = _add_provider(role="primary", base_url="https://primary.example.com/v1")
    _use_transport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "graded"}}]},
        )
    )

    result = asyncio.run(providers.complete(MESSAGES, role="grader"))
    assert result is not None
    assert result["provider_id"] == primary_id
    assert result["text"] == "graded"


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


def test_responses_complete_maps_instructions_and_usage(db):
    """Responses uses input/instructions and maps input/output token usage."""

    provider_id = _add_provider(
        role="primary",
        protocol="responses",
        base_url="https://api.openai.example.test/v1",
        model="o4-mini",
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "output_text": "Responses answer",
                "usage": {"input_tokens": 9, "output_tokens": 4},
            },
        )

    _use_transport(handler)
    result = asyncio.run(
        providers.complete([{"role": "system", "content": "Be concise"}, *MESSAGES])
    )
    assert result == {
        "text": "Responses answer",
        "model": "o4-mini",
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        "provider_id": provider_id,
    }
    assert captured["url"] == "https://api.openai.example.test/v1/responses"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["instructions"] == "Be concise"
    assert body["input"][0]["content"] == "你好"


def test_responses_stream_maps_delta_and_completed_usage(db):
    """Responses SSE completion must work even when the visible delta is empty."""

    provider_id = _add_provider(
        role="primary",
        protocol="responses",
        base_url="https://api.openai.example.test/v1",
        model="o4-mini",
    )
    sse_body = (
        'data: {"type":"response.output_text.delta","delta":"答案"}\n\n'
        'data: {"type":"response.output_text.delta","delta":""}\n\n'
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":2,"output_tokens":1}}}\n\n'
    )
    _use_transport(
        lambda request: httpx.Response(
            200,
            content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )
    )

    async def collect():
        return [event async for event in providers.stream_deltas(MESSAGES)]

    events = asyncio.run(collect())
    assert events[0] == {"delta": "答案"}
    assert {"delta": ""} in events
    assert {"done": True, "model": "o4-mini", "usage": {"prompt_tokens": 2, "completion_tokens": 1}, "provider_id": provider_id} == events[-1]


def test_first_text_delta_accepts_empty_delta_and_done_but_rejects_empty_stream():
    async def events_with_empty_delta():
        yield {"delta": ""}

    async def events_with_done():
        yield {"done": True}

    async def no_events():
        if False:
            yield {}

    asyncio.run(providers._first_text_delta(events_with_empty_delta()))
    asyncio.run(providers._first_text_delta(events_with_done()))
    with pytest.raises(providers.ProviderError, match="invalid_chat_response"):
        asyncio.run(providers._first_text_delta(no_events()))


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


def test_discover_responses_models_uses_openai_catalog_contract(db):
    """Responses shares the OpenAI model catalog but uses the Responses runtime endpoint."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"data": [{"id": "o4-mini"}]})

    _use_transport(handler)
    result = asyncio.run(
        providers.discover_models(
            "responses", "https://api.openai.example.test/v1", "sk-responses"
        )
    )
    assert result == {"supported": True, "models": [{"id": "o4-mini", "label": "o4-mini"}]}
    assert captured["url"] == "https://api.openai.example.test/v1/models"


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


def test_chat_completion_reasoning_content_is_ignored(db):
    """Explicit reasoning fields never become the provider text contract."""

    _add_provider(role="primary")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "visible answer",
                            "reasoning_content": "private reasoning",
                            "analysis": "private analysis",
                        }
                    }
                ]
            },
        )

    _use_transport(handler)
    result = asyncio.run(providers.complete(MESSAGES))
    assert result is not None
    assert result["text"] == "visible answer"


def test_chat_stream_reasoning_deltas_are_ignored(db):
    """Streaming adapters forward content deltas but drop reasoning-only frames."""

    _add_provider(role="primary")
    sse_body = (
        'data: {"choices": [{"delta": {"reasoning_content": "private"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "visible"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    _use_transport(
        lambda request: httpx.Response(
            200,
            content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )
    )

    async def collect():
        return [event async for event in providers.stream_deltas(MESSAGES)]

    events = asyncio.run(collect())
    assert events[0] == {"delta": "visible"}


def test_multimodal_messages_are_mapped_per_provider_protocol(db):
    """Images/audio use native blocks while unsupported video becomes text."""

    provider_id = _add_provider(role="primary")
    row = _provider_row(provider_id)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述附件"},
                {
                    "type": "media_attachment",
                    "filename": "photo.png",
                    "mime_type": "image/png",
                    "data": "aW1hZ2U=",
                },
            ],
        }
    ]

    openai_body = providers._cc_body(row, messages, stream=False)
    assert openai_body["messages"][0]["content"] == [
        {"type": "text", "text": "请描述附件"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
        },
    ]

    audio = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "转写音频"},
                {
                    "type": "media_attachment",
                    "filename": "voice.mp3",
                    "mime_type": "audio/mpeg",
                    "data": "YXVkaW8=",
                },
            ],
        }
    ]
    audio_body = providers._cc_body(row, audio, stream=False)
    assert audio_body["messages"][0]["content"][1] == {
        "type": "input_audio",
        "input_audio": {"data": "YXVkaW8=", "format": "mp3"},
    }

    anthropic_body = providers._anthropic_body(row, messages, stream=False)
    assert anthropic_body["messages"][0]["content"][1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "aW1hZ2U=",
        },
    }

    video = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "分析视频"},
                {
                    "type": "media_attachment",
                    "filename": "clip.mp4",
                    "mime_type": "video/mp4",
                    "data": "dmVkaW8=",
                },
            ],
        }
    ]
    responses_body = providers._responses_body(row, video, stream=False)
    responses_text = " ".join(
        block.get("text", "")
        for block in responses_body["input"][0]["content"]
        if isinstance(block, dict)
    )
    assert "clip.mp4" in responses_text
    assert "dmVkaW8=" not in responses_text


def test_rag_sampling_overrides_are_forwarded_to_each_protocol_body(db):
    """RAG page values reach chat, Responses, and Anthropic request payloads."""
    sampling = {"temperature": 0.65, "top_p": 0.8}
    messages = [{"role": "user", "content": "test"}]

    chat_row = _provider_row(_add_provider(protocol="chat_completions"))
    chat = providers._cc_body(chat_row, messages, stream=False, sampling=sampling)
    assert chat["temperature"] == 0.65
    assert chat["top_p"] == 0.8

    responses_row = _provider_row(_add_provider(protocol="responses"))
    responses = providers._responses_body(
        responses_row, messages, stream=True, sampling=sampling
    )
    assert responses["temperature"] == 0.65
    assert responses["top_p"] == 0.8

    anthropic_row = _provider_row(_add_provider(protocol="anthropic_messages"))
    anthropic = providers._anthropic_body(
        anthropic_row, messages, stream=False, sampling=sampling
    )
    assert anthropic["temperature"] == 0.65
    assert anthropic["top_p"] == 0.8

    # A malformed internal override is ignored rather than sent upstream.
    safe = providers._cc_body(
        chat_row,
        messages,
        stream=False,
        sampling={"temperature": "bad", "top_p": float("nan")},
    )
    assert "temperature" not in safe
    assert "top_p" not in safe


def test_media_candidate_selection_requires_declared_model_input_and_wire_support(db):
    """A text-only chat model must not win a media run merely by accepting JSON."""

    _add_provider(role="primary", extra={"model_inputs": ["text"]})
    fallback_id = _add_provider(
        role="fallback",
        base_url="https://fallback.example.com/v1",
        extra={"model_inputs": ["text", "image"]},
    )
    image = [("image", "image/png")]
    video = [("video", "video/mp4")]

    assert [row["id"] for row in providers._candidate_rows("primary", image)] == [fallback_id]
    assert providers._candidate_rows("primary", video) == []

    conn = connect(get_config().resolved_database_path)
    try:
        class Attachment:
            kind = "image"
            mime_type = "image/png"

        assert providers.has_compatible_media_provider(conn, [Attachment()])
        conn.execute(
            "UPDATE provider_configs SET extra_json = ? WHERE id = ?",
            (json.dumps({"model_inputs": ["text"]}), fallback_id),
        )
        conn.commit()
        assert not providers.has_compatible_media_provider(conn, [Attachment()])
    finally:
        conn.close()
