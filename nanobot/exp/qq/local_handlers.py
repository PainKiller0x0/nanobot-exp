"""QQ local command handlers for nanobot-exp.

This module owns deterministic no-LLM shortcuts for personal ops and the
knowledge inbox.  ``nanobot.channels.qq`` only wires message metadata and the QQ
transport callback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nanobot.exp.qq import fast_paths, local_commands
from nanobot.utils.helpers import split_message

SendTextOnly = Callable[..., Awaitable[None]]


def _chunk_limit(text_chunk_max_len: int | None) -> int:
    return max(200, int(text_chunk_max_len or 1200))


async def _send_reply_chunks(
    *,
    reply: str,
    chat_id: str,
    is_group: bool,
    message_id: str,
    text_chunk_max_len: int | None,
    send_text_only: SendTextOnly,
) -> None:
    for chunk in split_message(reply, _chunk_limit(text_chunk_max_len)):
        if chunk.strip():
            await send_text_only(
                chat_id=chat_id,
                is_group=is_group,
                msg_id=message_id,
                content=chunk,
            )


async def try_handle_personal_ops_query(
    *,
    chat_id: str,
    is_group: bool,
    message_id: str,
    content: str,
    text_chunk_max_len: int | None,
    send_text_only: SendTextOnly,
    logger: Any | None = None,
) -> bool:
    """Handle short operational questions without involving the LLM."""
    command = fast_paths.match_personal_ops_command(content)
    if not command:
        return False

    reply = await local_commands.run_personal_ops_command(command)
    await _send_reply_chunks(
        reply=reply,
        chat_id=chat_id,
        is_group=is_group,
        message_id=message_id,
        text_chunk_max_len=text_chunk_max_len,
        send_text_only=send_text_only,
    )
    if logger is not None:
        logger.info("QQ personal ops fast path handled command={} message_id={}", command, message_id)
    return True


async def try_handle_knowledge_inbox_query(
    *,
    chat_id: str,
    is_group: bool,
    message_id: str,
    content: str,
    text_chunk_max_len: int | None,
    send_text_only: SendTextOnly,
    logger: Any | None = None,
) -> bool:
    """Handle knowledge inbox capture/list/decision shortcuts without LLM calls."""
    args = fast_paths.match_knowledge_inbox_command(content)
    if not args:
        return False

    reply = await local_commands.run_knowledge_inbox_command(args)
    await _send_reply_chunks(
        reply=reply,
        chat_id=chat_id,
        is_group=is_group,
        message_id=message_id,
        text_chunk_max_len=text_chunk_max_len,
        send_text_only=send_text_only,
    )
    if logger is not None:
        logger.info("QQ knowledge inbox fast path handled args={} message_id={}", args, message_id)
    return True


__all__ = ["try_handle_knowledge_inbox_query", "try_handle_personal_ops_query"]
