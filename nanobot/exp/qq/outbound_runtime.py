"""Outbound QQ send orchestration for nanobot-exp.

QQChannel owns the low-level botpy adapters. This module owns the policy around
media fallback, signed article delivery, streaming preference, chunking, and ACK.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import aiohttp

from nanobot.bus.events import OutboundMessage
from nanobot.exp.qq import signed_delivery
from nanobot.utils.helpers import split_message

SendMedia = Callable[..., Awaitable[bool]]
SendTextOnly = Callable[..., Awaitable[None]]
SendTextStreaming = Callable[..., Awaitable[None]]
ShouldStreamText = Callable[..., bool]
RunWechatSigned = Callable[..., Awaitable[str | None]]
RunYageSigned = Callable[..., Awaitable[str | None]]
ReportSignatureBlocked = Callable[..., Awaitable[None]]


def attachment_failure_name(media_ref: str) -> str:
    """Return a short display filename for media failure notices."""
    return os.path.basename(urlparse(media_ref).path) or os.path.basename(media_ref) or "file"


async def send_outbound(
    msg: OutboundMessage,
    *,
    session: aiohttp.ClientSession | None,
    chat_type_cache: dict[str, str],
    text_chunk_max_len: int,
    send_media: SendMedia,
    send_text_only: SendTextOnly,
    send_text_streaming: SendTextStreaming,
    should_stream_text: ShouldStreamText,
    run_wechat_signed: RunWechatSigned,
    run_yage_signed: RunYageSigned,
    report_signature_blocked: ReportSignatureBlocked,
    logger: Any | None = None,
) -> None:
    """Send attachments first, then text, preserving QQ channel delivery policy."""
    msg_id = msg.metadata.get("message_id")
    chat_type = chat_type_cache.get(msg.chat_id, "c2c")
    is_group = chat_type == "group"

    for media_ref in msg.media or []:
        ok = await send_media(
            chat_id=msg.chat_id,
            media_ref=media_ref,
            msg_id=msg_id,
            is_group=is_group,
        )
        if not ok:
            await send_text_only(
                chat_id=msg.chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=f"[Attachment send failed: {attachment_failure_name(media_ref)}]",
            )

    if not (msg.content and msg.content.strip()):
        return

    prepared = await signed_delivery.prepare_outbound_content(
        msg.content,
        session=session,
        run_wechat_signed=run_wechat_signed,
        run_yage_signed=run_yage_signed,
        chat_id=msg.chat_id,
        logger=logger,
    )
    if prepared.suppressed:
        if logger is not None:
            logger.info("QQ outbound suppressed reason={} chat_id={}", prepared.reason, msg.chat_id)
        return
    if prepared.blocked:
        if logger is not None:
            logger.warning(
                "QQ outbound blocked reason={} chat_id={}",
                prepared.reason,
                msg.chat_id,
            )
        await report_signature_blocked(
            source_chat_id=msg.chat_id,
            source_is_group=is_group,
            source_msg_id=msg_id,
        )
        return

    safe_content = prepared.content
    is_signed_payload = prepared.is_signed_payload
    wechat_ack = prepared.wechat_ack

    if is_signed_payload:
        try:
            await send_text_only(
                chat_id=msg.chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=safe_content,
            )
            await signed_delivery.ack_delivery(
                session,
                safe_content,
                wechat_ack,
                chat_id=msg.chat_id,
                logger=logger,
            )
            return
        except Exception as e:
            if logger is not None:
                logger.warning(
                    "QQ signed payload one-shot send failed, fallback to chunking chat_id={} err={}",
                    msg.chat_id,
                    e,
                )

    if should_stream_text(
        msg_id=msg_id,
        is_signed_payload=is_signed_payload,
        content=safe_content,
    ):
        try:
            await send_text_streaming(
                chat_id=msg.chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=safe_content,
            )
            return
        except Exception as e:
            if logger is not None:
                logger.warning(
                    "QQ stream send failed, fallback to normal chunking chat_id={} err={}",
                    msg.chat_id,
                    e,
                )

    max_len = max(200, int(text_chunk_max_len or 1200))
    for chunk in split_message(safe_content, max_len):
        if not chunk:
            continue
        try:
            await send_text_only(
                chat_id=msg.chat_id,
                is_group=is_group,
                msg_id=msg_id,
                content=chunk,
            )
        except Exception as e:
            if logger is not None:
                logger.error("QQ text send failed chat_id={} err={}", msg.chat_id, e)
            return
    if is_signed_payload:
        await signed_delivery.ack_delivery(
            session,
            safe_content,
            wechat_ack,
            chat_id=msg.chat_id,
            logger=logger,
        )


__all__ = [
    "attachment_failure_name",
    "send_outbound",
]
