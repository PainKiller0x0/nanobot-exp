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
from nanobot.utils.output_sanitizer import strip_meta_instruction_tail

SendStreamFrame = Callable[..., Awaitable[str | None]]
SendTextOnly = Callable[..., Awaitable[None]]


_FIRST_FRAME_BOUNDARIES = frozenset("\n\u3002\uff01\uff1f!?\uff1b;\uff1a:.\u2026")
_FIRST_FRAME_OVERRUN_CHARS = 240


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
    flush_started_at = time.monotonic()
    is_first_frame = not state.get("first_frame_sent")
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
    flushed_at = time.monotonic()
    if new_id:
        state["qq_stream_id"] = new_id
    elif is_first_frame:
        state["disabled"] = True
    # A QQ stream frame may be visible even when the API response does not
    # return a stream id (for example, botpy reports a timeout after QQ has
    # accepted the frame). Remember the visible prefix so a later fallback
    # does not resend the same opening text as a separate normal message.
    state["flushed_content"] = str(state.get("flushed_content") or "") + pending
    state["pending"] = ""
    state["index"] = index + 1
    state["last_flush_at"] = flushed_at
    if is_first_frame:
        state["first_frame_sent"] = True
        started_at = float(state.get("started_at") or state["last_flush_at"])
        if logger is not None:
            first_frame_ms = int((state["last_flush_at"] - started_at) * 1000)
            pending_wait_ms = int((flush_started_at - started_at) * 1000)
            send_frame_ms = int((state["last_flush_at"] - flush_started_at) * 1000)
            turn_started = float(state.get("turn_started_perf") or 0)
            turn_first_frame_ms = int((state["last_flush_at"] - turn_started) * 1000) if turn_started > 0 else 0
            logger.info(
                "QQ delta stream first frame trace_id={} turn_id={} stream_key={} chat_id={} first_frame_ms={} pending_wait_ms={} send_frame_ms={} turn_first_frame_ms={} chars={}",
                state.get("trace_id", "") or "-",
                state.get("turn_id", ""),
                stream_key,
                chat_id,
                first_frame_ms,
                pending_wait_ms,
                send_frame_ms,
                turn_first_frame_ms,
                len(pending),
            )
            if not new_id:
                logger.warning(
                    "QQ delta stream first frame missing stream id; disabling append stream_key={} chat_id={} chars={}",
                    stream_key,
                    chat_id,
                    len(pending),
                )


def _can_flush_first_frame(pending: str, threshold: int) -> bool:
    if len(pending) < threshold:
        return False
    stripped = pending.rstrip()
    if not stripped:
        return False
    if stripped[-1] in _FIRST_FRAME_BOUNDARIES:
        return True
    return len(pending) >= threshold + _FIRST_FRAME_OVERRUN_CHARS


def _fallback_content_after_stream_attempt(content: str, state: dict[str, Any]) -> str:
    if not state.get("first_frame_sent"):
        return content
    flushed = str(state.get("flushed_content") or "")
    if flushed and content.startswith(flushed):
        return content[len(flushed):]
    return content


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
            "turn_id": metadata.get("_turn_id", ""),
            "trace_id": metadata.get("_trace_id", ""),
            "turn_started_perf": metadata.get("_turn_started_perf", 0),
        }
        stream_states[stream_key] = state
        if logger is not None:
            logger.info(
                "QQ delta stream start trace_id={} stream_key={} chat_id={}",
                state.get("trace_id", "") or "-",
                stream_key,
                chat_id,
            )

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
            if not state.get("first_frame_sent"):
                # Avoid the worst QQ UX: a visible half-sentence followed by a
                # second fallback bubble when QQ accepts the first frame but does
                # not return a usable stream id. By default, wait until the final
                # delta before creating the visible first frame.
                if bool(getattr(config, "stream_defer_first_frame_until_end", True)):
                    return
                # Treat short LLM replies as one-shot messages. QQ stream
                # creation is the slowest and most fragile part of short chats,
                # so only open a stream once the reply is clearly long enough.
                min_stream_chars = max(1, int(getattr(config, "stream_min_chars", 0) or 0))
                first_threshold = max(threshold, min_stream_chars)
                if not _can_flush_first_frame(pending, first_threshold):
                    return
            elif len(pending) < threshold and elapsed < interval:
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

        content = strip_meta_instruction_tail(str(state.get("content") or "")).strip()
        if not content:
            stream_states.pop(stream_key, None)
            return
        if not state.get("first_frame_sent"):
            min_stream_chars = max(1, int(getattr(config, "stream_min_chars", 0) or 0))
            if len(content) < min_stream_chars:
                await send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=msg_id,
                    content=content,
                )
                if logger is not None:
                    logger.info(
                        "QQ delta stream skipped for short reply stream_key={} chat_id={} chars={} min_chars={}",
                        stream_key,
                        chat_id,
                        len(content),
                        min_stream_chars,
                    )
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
                    "QQ delta stream done trace_id={} stream_key={} chat_id={} frames={} chars={}",
                    state.get("trace_id", "") or "-",
                    stream_key,
                    chat_id,
                    int(state.get("index") or 0),
                    len(content),
                )
        else:
            fallback_content = _fallback_content_after_stream_attempt(content, state)
            if fallback_content.strip():
                await send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=msg_id,
                    content=fallback_content,
                )
                if logger is not None:
                    logger.info(
                        "QQ delta stream fallback text sent stream_key={} chat_id={} chars={} skipped_prefix_chars={}",
                        stream_key,
                        chat_id,
                        len(fallback_content),
                        len(content) - len(fallback_content),
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
        fallback_content = strip_meta_instruction_tail(str(state.get("content") or ""))
        fallback_content = _fallback_content_after_stream_attempt(fallback_content, state)
        if is_end and fallback_content.strip():
            await send_text_only(
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=fallback_content,
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
    content = strip_meta_instruction_tail(qq_signatures.strip_silent_marker(content))
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
