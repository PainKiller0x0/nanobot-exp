"""QQ adapter for the Rust RSS sidecar.

This module keeps QQChannel's interface small: callers ask for a latest/ask
payload or a signed article payload.  The implementation prefers the Rust
wechat-rss-rs HTTP API and lets qq.py fall back to legacy Python scripts only
when the Rust API is unreachable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import aiohttp

BASE_URLS = (
    "http://wechat-rss-sidecar:8091",
    "http://172.17.0.1:8091",
    "http://127.0.0.1:8091",
)


def _argv_params(args: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
    if not args:
        return None
    command = str(args[0] or "").strip()
    if command not in {"latest", "ask"}:
        return None
    params: dict[str, Any] = {}
    i = 1
    while i < len(args):
        key = str(args[i] or "").strip()
        if key == "--refresh":
            params["refresh"] = "true"
            i += 1
            continue
        if not key.startswith("--"):
            i += 1
            continue
        if i + 1 >= len(args):
            break
        value = args[i + 1]
        normalized = key[2:].replace("-", "_")
        if normalized in {
            "days",
            "limit",
            "subscription_id",
            "sample_fetches",
            "sample_interval",
            "question",
            "entry_id",
        }:
            params[normalized] = value
        i += 2
    path = "/api/latest" if command == "latest" else "/api/ask"
    return path, params


async def _get_json(
    session: aiohttp.ClientSession | None,
    path: str,
    params: dict[str, Any],
    *,
    timeout_sec: float,
    logger: Any | None = None,
) -> dict[str, Any] | None:
    if session is None:
        return None
    timeout = aiohttp.ClientTimeout(total=max(1.0, timeout_sec))
    last_error: Exception | None = None
    for base_url in BASE_URLS:
        try:
            async with session.get(
                f"{base_url.rstrip('/')}{path}",
                params={k: v for k, v in params.items() if v is not None},
                timeout=timeout,
            ) as resp:
                if resp.status == 404:
                    return None
                if resp.status >= 500:
                    last_error = RuntimeError(f"http {resp.status}")
                    continue
                data = await resp.json(content_type=None)
                return data if isinstance(data, dict) else None
        except Exception as exc:  # pragma: no cover - live network fallback path
            last_error = exc
            continue
    if logger is not None and last_error is not None:
        logger.warning("qq rss rust adapter failed path={} err={}", path, last_error)
    return None


async def run_client_json(
    session: aiohttp.ClientSession | None,
    args: Sequence[str],
    *,
    timeout_sec: float = 30.0,
    logger: Any | None = None,
) -> dict[str, Any] | None:
    parsed = _argv_params(args)
    if parsed is None:
        return None
    path, params = parsed
    return await _get_json(session, path, params, timeout_sec=timeout_sec, logger=logger)


async def wechat_signed(
    session: aiohttp.ClientSession | None,
    subscription_id: int,
    *,
    timeout_sec: float = 45.0,
    force: bool = True,
    logger: Any | None = None,
) -> str | None:
    if subscription_id <= 0:
        return None
    payload = await _get_json(
        session,
        "/api/push/wechat-signed",
        {"subscription_id": subscription_id, "force": str(bool(force)).lower()},
        timeout_sec=timeout_sec,
        logger=logger,
    )
    if payload is None:
        return None
    if str(payload.get("status") or "").lower() == "empty":
        return ""
    return str(payload.get("signed_payload") or "")


async def yage_signed(
    session: aiohttp.ClientSession | None,
    *,
    timeout_sec: float = 45.0,
    nth: int | None = None,
    target_date: str | None = None,
    force_latest: bool = False,
    logger: Any | None = None,
) -> str | None:
    params: dict[str, Any] = {"latest": str(bool(force_latest)).lower()}
    if nth and nth > 1:
        params["nth"] = nth
    if target_date:
        params["date"] = target_date
    payload = await _get_json(
        session,
        "/api/push/yage-signed",
        params,
        timeout_sec=timeout_sec,
        logger=logger,
    )
    if payload is None:
        return None
    if str(payload.get("status") or "").lower() == "empty":
        return ""
    return str(payload.get("signed_payload") or "")


__all__ = ["run_client_json", "wechat_signed", "yage_signed"]
