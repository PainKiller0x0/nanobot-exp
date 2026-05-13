"""QQ streaming runtime for nanobot-exp.

The QQ channel owns the low-level botpy HTTP frame sender.  This module owns the
streaming state machine: delta buffering, first-frame timing, final reset, and
fallback-to-text behavior.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from nanobot.exp.qq import signatures as qq_signatures
from nanobot.exp.qq import streaming as qq_streaming

SendStreamFrame = Callable[..., Awaitable[str | None]]
SendTextOnly = Callable[..., Awaitable[None]]


async def _flush_delta_stream_state(
    *,
    config: Any,
    send_stream_frame: SendStreamFrame,
    stream_key: str,
    chat_id: str,
    is_group: bool,
    msg_id: str | None,
    state: dict[str, Any],
    logger: Any | None,
) -> None:
    pending = str(state.get("pending") or "")
    if not pending.strip():
        return
    index = int(state.get("index") or 0)
    qq_stream_id = state.get("qq_stream_id")
    new_id = await send_stream_frame(
        chat_id=chat_id,
        is_group=is_group,
        msg_id=msg_id,
        content=pending,
        state=1,
        index=index,
        reset=False,
        stream_id=str(qq_stream_id) if qq_stream_id else None,
    )
    if new_id:
        state["qq_stream_id"] = new_id
    state["pending"] = ""
    state["index"] = index + 1
    state["last_flush_at"] = time.monotonic()
    if not state.get("first_frame_sent"):
        state["first_frame_sent"] = True
        started_at = float(state.get("started_at") or state["last_flush_at"])
        if logger is not None:
            logger.info(
                "QQ delta stream first frame stream_key={} chat_id={} first_frame_ms={} chars={}",
                stream_key,
                chat_id,
                int((state["last_flush_at"] - started_at) * 1000),
                len(pending),
            )


async def send_delta(
    *,
    config: Any,
    stream_states: dict[str, dict[str, Any]],
    chat_type_cache: dict[str, str],
    send_stream_frame: SendStreamFrame,
    send_text_only: SendTextOnly,
    chat_id: str,
    delta: str,
    metadata: dict[str, Any] | None = None,
    logger: Any | None = None,
) -> None:
    metadata = metadata or {}
    if not qq_streaming.supports_streaming(config):
        return
    stream_key = str(metadata.get("_stream_id") or chat_id)
    is_end = bool(metadata.get("_stream_end"))
    msg_id = metadata.get("message_id") or metadata.get("msg_id")
    msg_id = str(msg_id) if msg_id else None
    is_group = chat_type_cache.get(str(chat_id)) == "group"

    state = stream_states.get(stream_key)
    if state is None:
        now = time.monotonic()
        state = {
            "content": "",
            "pending": "",
            "qq_stream_id": None,
            "index": 0,
            "started_at": now,
            "last_flush_at": now,
            "disabled": False,
            "first_frame_sent": False,
        }
        stream_states[stream_key] = state
        if logger is not None:
            logger.info("QQ delta stream start stream_key={} chat_id={}", stream_key, chat_id)

    if delta:
        state["content"] = str(state.get("content") or "") + delta
        state["pending"] = str(state.get("pending") or "") + delta

    if not msg_id:
        if is_end:
            stream_states.pop(stream_key, None)
        if logger is not None:
            logger.warning(
                "QQ delta stream skipped without msg_id stream_key={} chat_id={}",
                stream_key,
                chat_id,
            )
        return

    try:
        if not is_end:
            if state.get("disabled"):
                return
            pending = str(state.get("pending") or "")
            if not pending.strip():
                return
            threshold, interval = qq_streaming.delta_flush_policy(
                config,
                first_frame_sent=bool(state.get("first_frame_sent")),
            )
            elapsed = time.monotonic() - float(state.get("last_flush_at") or time.monotonic())
            if len(pending) < threshold and elapsed < interval:
                return
            await _flush_delta_stream_state(
                config=config,
                send_stream_frame=send_stream_frame,
                stream_key=stream_key,
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                state=state,
                logger=logger,
            )
            return

        content = str(state.get("content") or "").strip()
        if not content:
            stream_states.pop(stream_key, None)
            return
        if not state.get("disabled") and str(state.get("pending") or "").strip():
            await _flush_delta_stream_state(
                config=config,
                send_stream_frame=send_stream_frame,
                stream_key=stream_key,
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                state=state,
                logger=logger,
            )
        qq_stream_id = state.get("qq_stream_id")
        if not state.get("disabled") and qq_stream_id:
            await send_stream_frame(
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=content,
                state=10,
                index=1,
                reset=True,
                stream_id=str(qq_stream_id),
            )
            if logger is not None:
                logger.info(
                    "QQ delta stream done stream_key={} chat_id={} frames={} chars={}",
                    stream_key,
                    chat_id,
                    int(state.get("index") or 0),
                    len(content),
                )
        else:
            await send_text_only(
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=content,
            )
            if logger is not None:
                logger.info(
                    "QQ delta stream fallback text sent stream_key={} chat_id={}",
                    stream_key,
                    chat_id,
                )
    except Exception as e:
        state["disabled"] = True
        if logger is not None:
            logger.warning(
                "QQ delta stream failed stream_key={} chat_id={} err={}",
                stream_key,
                chat_id,
                e,
            )
        if is_end and str(state.get("content") or "").strip():
            await send_text_only(
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=str(state.get("content") or ""),
            )
    finally:
        if is_end:
            stream_states.pop(stream_key, None)


async def send_text_streaming(
    *,
    config: Any,
    send_stream_frame: SendStreamFrame,
    chat_id: str,
    is_group: bool,
    msg_id: str | None,
    content: str,
    logger: Any | None = None,
) -> None:
    content = qq_signatures.strip_silent_marker(content)
    if not content:
        return

    chunks = qq_streaming.split_stream_chunks(config, content)
    stream_id: str | None = None
    interval = max(0.0, float(getattr(config, "stream_interval_sec", 0.0) or 0.0))
    if logger is not None:
        logger.info(
            "QQ stream send start chat_id={} chunks={} chars={}",
            chat_id,
            len(chunks),
            len(content),
        )

    for index, chunk in enumerate(chunks):
        new_id = await send_stream_frame(
            chat_id=chat_id,
            is_group=is_group,
            msg_id=msg_id,
            content=chunk,
            state=1,
            index=index,
            reset=False,
            stream_id=stream_id,
        )
        if new_id:
            stream_id = new_id
        if interval and index + 1 < len(chunks):
            await asyncio.sleep(interval)

    await send_stream_frame(
        chat_id=chat_id,
        is_group=is_group,
        msg_id=msg_id,
        content=content,
        state=10,
        index=1,
        reset=True,
        stream_id=stream_id,
    )
    if logger is not None:
        logger.info("QQ stream send done chat_id={} stream_id={}", chat_id, stream_id)


__all__ = ["send_delta", "send_text_streaming"]
