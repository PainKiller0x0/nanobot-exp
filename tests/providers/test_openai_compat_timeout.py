import asyncio
from unittest.mock import AsyncMock, patch, sentinel

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec


def _assert_openai_compat_timeout(timeout) -> None:
    assert timeout == 120.0


def test_openai_compat_provider_sets_sdk_timeout() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(kwargs["timeout"])
    assert kwargs["http_client"] is None


def test_openai_compat_provider_sets_timeout_on_local_http_client() -> None:
    spec = ProviderSpec(
        name="local",
        keywords=(),
        env_key="",
        is_local=True,
        default_api_base="http://127.0.0.1:11434/v1",
    )

    with (
        patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
        patch(
            "nanobot.providers.openai_compat_provider.httpx.AsyncClient",
            return_value=sentinel.http_client,
        ) as mock_http_client,
    ):
        OpenAICompatProvider(spec=spec)

    client_kwargs = mock_http_client.call_args.kwargs
    _assert_openai_compat_timeout(client_kwargs["timeout"])
    assert client_kwargs["limits"].keepalive_expiry == 0

    openai_kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(openai_kwargs["timeout"])
    assert openai_kwargs["http_client"] is sentinel.http_client


def test_openai_compat_provider_timeout_can_be_overridden_by_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", "45")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    assert mock_async_openai.call_args.kwargs["timeout"] == 45.0


def test_stream_idle_timeout_uses_image_timeout_for_explicit_image_prompt(monkeypatch) -> None:
    from nanobot.providers.openai_compat_provider import _stream_idle_timeout_s

    monkeypatch.delenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NANOBOT_IMAGE_STREAM_IDLE_TIMEOUT_S", raising=False)

    assert _stream_idle_timeout_s([
        {"role": "user", "content": "\u7ed9\u6211\u753b\u4e00\u5f20\u767d\u5e95\u7ea2\u8272\u5706\u70b9"},
    ]) == 180


def test_stream_idle_timeout_keeps_default_for_normal_chat(monkeypatch) -> None:
    from nanobot.providers.openai_compat_provider import _stream_idle_timeout_s

    monkeypatch.delenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NANOBOT_IMAGE_STREAM_IDLE_TIMEOUT_S", raising=False)

    assert _stream_idle_timeout_s([
        {"role": "user", "content": "\u5e2e\u6211\u770b\u770b\u8fd9\u4e2a\u62a5\u9519"},
    ]) == 90


def test_stream_idle_timeout_honors_image_env(monkeypatch) -> None:
    from nanobot.providers.openai_compat_provider import _stream_idle_timeout_s

    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "75")
    monkeypatch.setenv("NANOBOT_IMAGE_STREAM_IDLE_TIMEOUT_S", "240")

    assert _stream_idle_timeout_s([
        {"role": "user", "content": "please generate an image of a red dot"},
    ]) == 240
    assert _stream_idle_timeout_s([
        {"role": "user", "content": "please do not generate image, just describe it"},
    ]) == 75


@pytest.mark.asyncio
async def test_chat_stream_bypasses_stream_for_explicit_image_prompt(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_IMAGE_BACKGROUND", "0")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    provider._create_chat_completion_with_route_log = AsyncMock(
        return_value="![generated](http://150.158.121.88:8093/gemini-images/test.png)"
    )  # type: ignore[method-assign]
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    result = await provider.chat_stream(
        [{"role": "user", "content": "\u7ed9\u6211\u753b\u4e00\u5f20\u767d\u5e95\u7ea2\u8272\u5706\u70b9"}],
        tools=[{"type": "function", "function": {"name": "noop"}}],
        model="gemini-3.5-flash",
        max_tokens=128,
        temperature=0.2,
        reasoning_effort="none",
        tool_choice="auto",
        on_content_delta=on_delta,
    )

    assert result.content == "![generated](http://150.158.121.88:8093/gemini-images/test.png)"
    assert deltas == [result.content]
    provider._create_chat_completion_with_route_log.assert_awaited_once()
    kwargs = provider._create_chat_completion_with_route_log.await_args.args[0]
    assert "stream" not in kwargs
    assert kwargs["timeout"] == 180.0
    assert kwargs["model"] == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_chat_stream_runs_explicit_image_prompt_in_background() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/obp/v1")

    provider._create_chat_completion_with_route_log = AsyncMock(
        return_value="![generated](http://150.158.121.88:8093/gemini-images/test.png)"
    )  # type: ignore[method-assign]
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    result = await provider.chat_stream(
        [{"role": "user", "content": "\u7ed9\u6211\u753b\u4e00\u5f20\u767d\u5e95\u7ea2\u8272\u5706\u70b9"}],
        model="gemini-3.5-flash",
        max_tokens=128,
        temperature=0.2,
        on_content_delta=on_delta,
    )
    await asyncio.sleep(0)

    assert result.finish_reason == "queued"
    assert deltas[0].startswith("??????????")
    assert deltas[-1] == "![generated](http://150.158.121.88:8093/gemini-images/test.png)"
    provider._create_chat_completion_with_route_log.assert_awaited_once()


def test_obp_headers_mark_explicit_image_generation() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/obp/v1")

    kwargs = provider._with_obp_request_headers({
        "messages": [
            {"role": "user", "content": "\u7ed9\u6211\u753b\u4e00\u5f20\u767d\u5e95\u7ea2\u8272\u5706\u70b9"},
        ],
    })

    assert kwargs["extra_headers"]["X-OBP-Image-Generation"] == "1"


def test_obp_headers_do_not_mark_image_debug_discussion() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/obp/v1")

    kwargs = provider._with_obp_request_headers({
        "messages": [
            {"role": "user", "content": "\u753b\u56fe\u597d\u50cf\u5d29\u4e86\uff0c\u5e2e\u6211\u770b\u4e0b\u65e5\u5fd7"},
        ],
    })

    assert "X-OBP-Image-Generation" not in kwargs["extra_headers"]
