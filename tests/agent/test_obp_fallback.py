import pytest

from nanobot.exp.agent.obp_fallback import OBPFallbackClient
from nanobot.providers.base import LLMResponse


def test_prepare_kwargs_removes_tools_and_caps_tokens() -> None:
    kwargs = OBPFallbackClient.prepare_kwargs(
        {
            "model": "primary",
            "tools": [{"type": "function"}],
            "tool_choice": "auto",
            "reasoning_effort": "high",
            "on_retry_wait": object(),
            "max_tokens": 2048,
        },
        env={"NANOBOT_OBP_FALLBACK_MAX_TOKENS": "128"},
        model="LongCat-Flash-Chat",
    )

    assert kwargs["model"] == "LongCat-Flash-Chat"
    assert kwargs["tools"] is None
    assert kwargs["max_tokens"] == 128
    assert "tool_choice" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert "on_retry_wait" not in kwargs


def test_provider_is_disabled_without_base() -> None:
    assert OBPFallbackClient().provider(env={}) is None


@pytest.mark.asyncio
async def test_request_returns_none_when_disabled() -> None:
    class Logger:
        def warning(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

    result = await OBPFallbackClient().request({}, reason="timeout", logger=Logger(), env={})

    assert result is None


@pytest.mark.asyncio
async def test_request_returns_none_on_fallback_error_finish(monkeypatch) -> None:
    from nanobot.providers import openai_compat_provider

    class Logger:
        def warning(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

    class FakeProvider:
        def __init__(self, **kwargs):
            pass

        async def chat_with_retry(self, **kwargs):
            return LLMResponse(content="bad", finish_reason="error")

    monkeypatch.setattr(openai_compat_provider, "OpenAICompatProvider", FakeProvider)

    result = await OBPFallbackClient().request(
        {"messages": [], "max_tokens": 10},
        reason="timeout",
        logger=Logger(),
        env={"NANOBOT_OBP_FALLBACK_BASE": "http://obp.local/v1"},
    )

    assert result is None
