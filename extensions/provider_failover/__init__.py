"""Optional provider failover plugin (default disabled).

Enable with:
  NANOBOT_PROVIDER_FAILOVER_MODULE=extensions.provider_failover
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from loguru import logger

from nanobot.providers.base import LLMResponse

_STATE_ATTR = "_ext_provider_failover_state"


def _state(provider: Any) -> dict[str, Any]:
    state = getattr(provider, _STATE_ATTR, None)
    if isinstance(state, dict):
        return state
    state = {
        "active_until": 0.0,
        "consecutive_529": 0,
        "settings_cache": None,
        "settings_cache_at": 0.0,
        "fallback_provider": None,
        "fallback_sig": None,
        "lock": asyncio.Lock(),
    }
    setattr(provider, _STATE_ATTR, state)
    return state


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_529_overload_error(response: LLMResponse | None) -> bool:
    text = ((response.content if response else None) or "").lower()
    return (
        " 529" in text
        or '"529"' in text
        or "'529'" in text
        or ("http_code" in text and "529" in text)
        or "overloaded_error" in text
        or "??????????" in text
        or "??????" in text
    )


async def _load_settings(provider: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    now = time.time()
    cache = state.get("settings_cache")
    cache_at = float(state.get("settings_cache_at") or 0.0)
    if isinstance(cache, dict) and now - cache_at < 15:
        return cache

    settings_url = os.environ.get("NANOBOT_FAILOVER_SETTINGS_URL", "").strip()
    remote: dict[str, Any] = {}
    if settings_url:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(settings_url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        remote = data
        except Exception as e:
            logger.debug("Failover settings fetch failed: {}", e)

    api_base = (remote.get("api_base") if remote else None) or os.environ.get("NANOBOT_FALLBACK_API_BASE", "")
    model = (remote.get("model") if remote else None) or os.environ.get("NANOBOT_FALLBACK_MODEL", "")
    api_key = (remote.get("api_key") if remote else None) or os.environ.get("NANOBOT_FALLBACK_API_KEY", "")
    enabled = _parse_bool(
        (remote.get("enabled") if remote else None) or os.environ.get("NANOBOT_FALLBACK_ENABLED"),
        bool(api_base and model),
    )
    trigger_529 = _parse_int(
        (remote.get("trigger_529_count") if remote else None) or os.environ.get("NANOBOT_FALLBACK_TRIGGER_529_COUNT", 3),
        3,
    )
    recover_seconds = _parse_int(
        (remote.get("recover_seconds") if remote else None) or os.environ.get("NANOBOT_FALLBACK_RECOVER_SECONDS", 900),
        900,
    )

    if not enabled or not api_base or not model:
        state["settings_cache"] = None
        state["settings_cache_at"] = now
        return None

    cfg = {
        "enabled": True,
        "api_base": str(api_base).rstrip("/"),
        "api_key": str(api_key or ""),
        "model": str(model),
        "trigger_529_count": max(1, trigger_529),
        "recover_seconds": max(30, recover_seconds),
    }
    state["settings_cache"] = cfg
    state["settings_cache_at"] = now
    return cfg


async def _fallback_request(
    provider: Any,
    state: dict[str, Any],
    settings: dict[str, Any],
    *,
    stream: bool,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str | None,
    max_tokens: Any,
    temperature: Any,
    reasoning_effort: Any,
    tool_choice: str | dict[str, Any] | None,
    retry_mode: str,
    on_retry_wait: Any = None,
    on_content_delta: Any = None,
) -> LLMResponse:
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    lock = state["lock"]
    async with lock:
        sig = (settings["api_base"], settings["api_key"], settings["model"])
        if state.get("fallback_provider") is None or state.get("fallback_sig") != sig:
            p = OpenAICompatProvider(
                api_key=settings["api_key"] or None,
                api_base=settings["api_base"],
                default_model=settings["model"],
            )
            p.generation = provider.generation
            p._failover_plugin = None
            state["fallback_provider"] = p
            state["fallback_sig"] = sig
        fallback_provider = state["fallback_provider"]

    chosen_model = settings["model"] or model
    if stream:
        return await fallback_provider.chat_stream_with_retry(
            messages=messages,
            tools=tools,
            model=chosen_model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
            on_content_delta=on_content_delta,
        )
    return await fallback_provider.chat_with_retry(
        messages=messages,
        tools=tools,
        model=chosen_model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        tool_choice=tool_choice,
        retry_mode=retry_mode,
        on_retry_wait=on_retry_wait,
    )


async def maybe_failover(
    *,
    provider: Any,
    phase: str,
    stream: bool,
    response: LLMResponse | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str | None,
    max_tokens: Any,
    temperature: Any,
    reasoning_effort: Any,
    tool_choice: str | dict[str, Any] | None,
    retry_mode: str,
    on_retry_wait: Any = None,
    on_content_delta: Any = None,
) -> LLMResponse | None:
    state = _state(provider)
    settings = await _load_settings(provider, state)
    if not settings:
        return None

    now = time.time()
    if phase == "before" and now < float(state.get("active_until") or 0.0):
        logger.warning(
            "Failover active ({}s remaining): routing to backup model '{}'",
            int(float(state.get("active_until") or 0.0) - now),
            settings.get("model"),
        )
        return await _fallback_request(
            provider,
            state,
            settings,
            stream=stream,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
            on_content_delta=on_content_delta,
        )

    if phase != "after" or response is None:
        return None

    if response.finish_reason != "error" or not _is_529_overload_error(response):
        state["consecutive_529"] = 0
        return None

    state["consecutive_529"] = int(state.get("consecutive_529") or 0) + 1
    trigger = int(settings.get("trigger_529_count") or 3)
    if state["consecutive_529"] < trigger:
        return None

    recover_seconds = int(settings.get("recover_seconds") or 900)
    state["active_until"] = time.time() + recover_seconds
    state["consecutive_529"] = 0
    logger.warning(
        "Primary model hit 529 {} times; failover to '{}' for {}s",
        trigger,
        settings.get("model"),
        recover_seconds,
    )

    fallback_resp = await _fallback_request(
        provider,
        state,
        settings,
        stream=stream,
        messages=messages,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        tool_choice=tool_choice,
        retry_mode=retry_mode,
        on_retry_wait=on_retry_wait,
        on_content_delta=on_content_delta,
    )
    return fallback_resp if fallback_resp.finish_reason != "error" else None
PY
