"""QQ text and stream transport helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from nanobot.exp.qq import signatures as qq_signatures


def build_text_payload(
    *,
    content: str,
    msg_id: str | None,
    msg_seq: int,
    use_markdown: bool,
) -> dict[str, Any] | None:
    """Build a QQ text payload, returning None for silent/empty content."""
    content = qq_signatures.strip_silent_marker(content)
    if not content:
        return None
    payload: dict[str, Any] = {
        "msg_type": 2 if use_markdown else 0,
        "msg_id": msg_id,
        "msg_seq": msg_seq,
    }
    if use_markdown:
        payload["markdown"] = {"content": content}
    else:
        payload["content"] = content
    return payload


def build_stream_payload(
    *,
    content: str,
    msg_id: str | None,
    msg_seq: int,
    state: int,
    index: int,
    reset: bool,
    stream_id: str | None = None,
) -> dict[str, Any]:
    """Build QQ's markdown stream payload."""
    stream_meta: dict[str, Any] = {
        "state": state,
        "index": index,
        "reset": reset,
    }
    if stream_id:
        stream_meta["id"] = stream_id
    return {
        "msg_type": 2,
        "msg_id": msg_id,
        "msg_seq": msg_seq,
        "markdown": {"content": content},
        "stream": stream_meta,
    }


def message_route(is_group: bool) -> tuple[str, str]:
    """Return (endpoint, id_key) for QQ message posting."""
    if is_group:
        return "/v2/groups/{group_openid}/messages", "group_openid"
    return "/v2/users/{openid}/messages", "openid"


def apply_botpy_http_timeout(client: Any, timeout: float, *, logger: Any | None = None) -> None:
    """Keep botpy sends from hanging longer than the QQ channel budget."""
    if not client or timeout <= 0:
        return
    try:
        api = getattr(client, "api", None)
        http = getattr(api, "_http", None)
        if http is not None:
            http.timeout = timeout
    except Exception as e:  # pragma: no cover - defensive only
        if logger is not None:
            logger.debug("QQ botpy timeout tune skipped: {}", e)


async def post_stream_payload(
    client: Any,
    route_cls: Any,
    *,
    chat_id: str,
    is_group: bool,
    payload: dict[str, Any],
    timeout_sec: float,
    logger: Any | None = None,
) -> Any | None:
    """Post QQ stream payload through raw botpy HTTP to avoid SDK kwarg filtering."""
    apply_botpy_http_timeout(client, timeout_sec, logger=logger)
    if not client or not getattr(client.api, "_http", None) or route_cls is None:
        raise RuntimeError("QQ raw HTTP client is not available for streaming")

    endpoint, id_key = message_route(is_group)
    route = route_cls("POST", endpoint, **{id_key: chat_id})
    return await client.api._http.request(route, json=payload)


async def post_text_payload(
    client: Any,
    *,
    chat_id: str,
    is_group: bool,
    msg_id: str | None,
    payload: dict[str, Any],
    timeout_sec: float,
    retry_on_empty_response: bool,
    retry_attempts: int,
    retry_delay_sec: float,
    logger: Any | None = None,
) -> Any | None:
    """Post text through botpy, retrying passive replies when botpy reports no response."""
    apply_botpy_http_timeout(client, timeout_sec, logger=logger)
    can_retry = bool(msg_id) and bool(retry_on_empty_response)
    attempts = 1 + max(0, retry_attempts if can_retry else 0)
    delay = max(0.0, retry_delay_sec)

    for attempt in range(1, attempts + 1):
        try:
            if is_group:
                result = await client.api.post_group_message(group_openid=chat_id, **payload)
            else:
                result = await client.api.post_c2c_message(openid=chat_id, **payload)
            if can_retry and result is None:
                raise asyncio.TimeoutError("QQ API returned no response")
            return result
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            if attempt >= attempts:
                if logger is not None:
                    logger.warning(
                        "QQ text send failed after {} attempt(s) chat_id={} msg_seq={} err={}",
                        attempts,
                        chat_id,
                        payload.get("msg_seq"),
                        e,
                    )
                raise
            if logger is not None:
                logger.warning(
                    "QQ text send attempt {}/{} failed chat_id={} msg_seq={} err={}; retrying same msg_seq",
                    attempt,
                    attempts,
                    chat_id,
                    payload.get("msg_seq"),
                    e,
                )
            if delay:
                await asyncio.sleep(delay)
    return None


__all__ = [
    "apply_botpy_http_timeout",
    "build_stream_payload",
    "build_text_payload",
    "message_route",
    "post_stream_payload",
    "post_text_payload",
]
