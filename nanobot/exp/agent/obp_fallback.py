"""OBP fallback adapter for AgentRunner.

This is nanobot-exp runtime glue: when the primary provider times out or returns
a timeout-like error, route a small no-tools request through the local OBP bridge.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse


class OBPFallbackClient:
    """Cached OpenAI-compatible fallback client configured by environment."""

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._key: tuple[str, str, str, str] | None = None

    def provider(self, *, env: Mapping[str, str] | None = None) -> tuple[LLMProvider, str] | None:
        source = os.environ if env is None else env
        base = source.get("NANOBOT_OBP_FALLBACK_BASE", "").strip()
        if not base:
            return None
        model = source.get("NANOBOT_OBP_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
        api_key = (
            source.get("NANOBOT_OBP_FALLBACK_API_KEY", "").strip()
            or source.get("OBP_PROXY_TOKEN", "").strip()
            or "no-key"
        )
        source_name = (
            source.get("NANOBOT_OBP_FALLBACK_SOURCE", "").strip()
            or source.get("NANOBOT_OBP_SOURCE", "").strip()
            or "default-nanobot-fallback"
        )
        key = (base, model, api_key, source_name)
        if self._provider is None or self._key != key:
            from nanobot.providers import openai_compat_provider

            self._provider = openai_compat_provider.OpenAICompatProvider(
                api_key=api_key,
                api_base=base,
                default_model=model,
                extra_headers={"X-OBP-Source": source_name},
            )
            self._key = key
        return self._provider, model

    async def request(
        self,
        primary_kwargs: dict[str, Any],
        *,
        reason: str,
        logger: Any,
        env: Mapping[str, str] | None = None,
    ) -> LLMResponse | None:
        source = os.environ if env is None else env
        fallback = self.provider(env=source)
        if fallback is None:
            return None
        provider, model = fallback
        fallback_kwargs = self.prepare_kwargs(primary_kwargs, env=source, model=model)
        timeout_s = _float_env("NANOBOT_OBP_FALLBACK_TIMEOUT_S", 35.0, env=source)
        logger.warning("Primary LLM {}; using OBP fallback model={}", reason, model)
        try:
            response = await asyncio.wait_for(
                provider.chat_with_retry(**fallback_kwargs),
                timeout=max(1.0, timeout_s),
            )
        except asyncio.TimeoutError:
            logger.warning("OBP fallback timed out after {}s", timeout_s)
            return None
        except Exception as exc:  # noqa: BLE001 - fallback must never mask primary error handling.
            logger.warning("OBP fallback failed: {}: {}", type(exc).__name__, exc)
            return None

        if response.finish_reason == "error":
            logger.warning("OBP fallback returned error: {}", (response.content or "")[:160])
            return None
        logger.info("OBP fallback succeeded model={}", model)
        return response

    @staticmethod
    def prepare_kwargs(
        primary_kwargs: dict[str, Any],
        *,
        env: Mapping[str, str] | None = None,
        model: str,
    ) -> dict[str, Any]:
        source = os.environ if env is None else env
        fallback_kwargs = dict(primary_kwargs)
        fallback_kwargs["model"] = model
        fallback_kwargs["retry_mode"] = "standard"
        fallback_kwargs["tools"] = None
        fallback_kwargs.pop("tool_choice", None)
        fallback_kwargs.pop("reasoning_effort", None)
        fallback_kwargs.pop("on_retry_wait", None)

        max_tokens_cap = max(1, _int_env("NANOBOT_OBP_FALLBACK_MAX_TOKENS", 1024, env=source))
        try:
            requested_max = int(fallback_kwargs.get("max_tokens") or max_tokens_cap)
        except (TypeError, ValueError):
            requested_max = max_tokens_cap
        fallback_kwargs["max_tokens"] = max(1, min(requested_max, max_tokens_cap))
        return fallback_kwargs


def _float_env(name: str, default: float, *, env: Mapping[str, str]) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int, *, env: Mapping[str, str]) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


__all__ = ["OBPFallbackClient"]
