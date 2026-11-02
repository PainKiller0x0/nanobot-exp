"""Signed outbound delivery policy for QQ.

This module owns nanobot-exp's anti-tamper and article-delivery ACK flow.
QQChannel should stay focused on botpy send/receive mechanics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

from nanobot.exp.qq import rss_sidecar as qq_rss_sidecar
from nanobot.exp.qq import signatures as qq_signatures

RunWechatSigned = Callable[..., Awaitable[str | None]]
RunYageSigned = Callable[..., Awaitable[str | None]]


@dataclass(frozen=True)
class PreparedOutboundContent:
    content: str
    is_signed_payload: bool
    wechat_ack: tuple[int, int] | None = None
    blocked: bool = False
    suppressed: bool = False
    reason: str = ""


def _valid_signed_payload(raw: str | None) -> bool:
    return bool(raw and raw.startswith(qq_signatures.SIGNED_PAYLOAD_PREFIX))


async def _verify_signed_payload(
    content: str,
    *,
    logger: Any | None,
) -> str | None:
    # QQ sidecar verification is HTTP-bound and historically synchronous.
    # Keep it off the event loop so article pushes do not stall other QQ sends.
    return await asyncio.to_thread(
        qq_signatures.verify_and_unwrap_signed_payload,
        content,
        logger=logger,
    )


async def _recover_wechat_by_digest(
    session: aiohttp.ClientSession | None,
    expected_digest: str,
    *,
    run_wechat_signed: RunWechatSigned,
    timeout_sec: float,
    logger: Any | None,
) -> tuple[str | None, int | None]:
    if not expected_digest:
        return None, None
    recovered_raw, recovered_sub = await qq_rss_sidecar.recover_wechat_by_digest(
        session,
        expected_digest,
        timeout_sec=timeout_sec,
        logger=logger,
    )
    if _valid_signed_payload(recovered_raw):
        return recovered_raw, recovered_sub

    # Fallback for older sidecar deployments or local tests.
    for sid in (1, 2, 3):
        recovered_raw = await run_wechat_signed(sid, timeout_sec=timeout_sec, force=True)
        if not _valid_signed_payload(recovered_raw):
            continue
        got_digest = qq_signatures.extract_signed_digest(recovered_raw or "") or ""
        if got_digest == expected_digest:
            return recovered_raw, sid
    return None, None


async def _unwrap_or_recover_signed_payload(
    content: str,
    *,
    session: aiohttp.ClientSession | None,
    run_wechat_signed: RunWechatSigned,
    run_yage_signed: RunYageSigned,
    chat_id: str,
    logger: Any | None,
    timeout_sec: float = 45.0,
) -> str | None:
    safe_content = await _verify_signed_payload(content, logger=logger)
    if safe_content is not None:
        return safe_content

    # Cron/tool transport may reconstruct or strip parts of the signed payload.
    expected_digest = qq_signatures.extract_signed_digest(content)

    sub_id = qq_signatures.extract_wechat_subscription_id(content)
    if sub_id is not None:
        recovered_wechat = await run_wechat_signed(sub_id, timeout_sec=timeout_sec, force=True)
        if _valid_signed_payload(recovered_wechat):
            recovered_body = await _verify_signed_payload(
                recovered_wechat or "",
                logger=logger,
            )
            if recovered_body and recovered_body.strip():
                if logger is not None:
                    logger.warning(
                        "QQ signature mismatch self-healed via fresh wechat fetch "
                        "chat_id={} sub={}",
                        chat_id,
                        sub_id,
                    )
                return recovered_body

    if expected_digest:
        recovered_wechat, recovered_sub = await _recover_wechat_by_digest(
            session,
            expected_digest,
            run_wechat_signed=run_wechat_signed,
            timeout_sec=timeout_sec,
            logger=logger,
        )
        if _valid_signed_payload(recovered_wechat):
            recovered_body = await _verify_signed_payload(
                recovered_wechat or "",
                logger=logger,
            )
            if recovered_body and recovered_body.strip():
                if logger is not None:
                    logger.warning(
                        "QQ signature mismatch self-healed via digest recovery "
                        "chat_id={} sub={}",
                        chat_id,
                        recovered_sub,
                    )
                return recovered_body

    recovered_yage = await run_yage_signed(timeout_sec=timeout_sec, force_latest=True)
    if _valid_signed_payload(recovered_yage):
        recovered_body = await _verify_signed_payload(
            recovered_yage or "",
            logger=logger,
        )
        if recovered_body and recovered_body.strip():
            if logger is not None:
                logger.warning(
                    "QQ signature mismatch self-healed via fresh yage fetch chat_id={}",
                    chat_id,
                )
            return recovered_body

    return None


async def prepare_outbound_content(
    content: str,
    *,
    session: aiohttp.ClientSession | None,
    run_wechat_signed: RunWechatSigned,
    run_yage_signed: RunYageSigned,
    chat_id: str,
    logger: Any | None = None,
) -> PreparedOutboundContent:
    stripped_content = qq_signatures.strip_silent_marker(content)
    if stripped_content != content and not stripped_content:
        return PreparedOutboundContent(
            content="",
            is_signed_payload=False,
            suppressed=True,
            reason="silent_marker",
        )

    is_signed_payload = stripped_content.startswith(qq_signatures.SIGNED_PAYLOAD_PREFIX)
    requires_signature = qq_signatures.requires_signed_payload(stripped_content)
    if requires_signature and not is_signed_payload:
        return PreparedOutboundContent(
            content="",
            is_signed_payload=False,
            blocked=True,
            reason="missing_signature",
        )

    safe_content = stripped_content
    if is_signed_payload:
        recovered = await _unwrap_or_recover_signed_payload(
            stripped_content,
            session=session,
            run_wechat_signed=run_wechat_signed,
            run_yage_signed=run_yage_signed,
            chat_id=chat_id,
            logger=logger,
        )
        if not recovered or not recovered.strip():
            return PreparedOutboundContent(
                content="",
                is_signed_payload=True,
                blocked=True,
                reason="signature_validation_failed",
            )
        safe_content = recovered

    safe_content, wechat_ack = qq_signatures.extract_wechat_ack_marker(safe_content)
    safe_content = qq_signatures.strip_silent_marker(safe_content)
    if not safe_content.strip():
        return PreparedOutboundContent(
            content="",
            is_signed_payload=is_signed_payload,
            wechat_ack=wechat_ack,
            suppressed=True,
            reason="empty_after_strip",
        )

    return PreparedOutboundContent(
        content=safe_content,
        is_signed_payload=is_signed_payload,
        wechat_ack=wechat_ack,
    )


async def ack_delivery(
    session: aiohttp.ClientSession | None,
    body: str,
    wechat_ack: tuple[int, int] | None,
    *,
    chat_id: str,
    logger: Any | None = None,
) -> None:
    source_url = qq_signatures.extract_yage_source_url(body)
    if source_url:
        result = await qq_rss_sidecar.ack_yage_delivery(
            session,
            source_url,
            timeout_sec=10.0,
            logger=logger,
        )
        if result is None:
            if logger is not None:
                logger.warning("QQ yage delivery ack sidecar unavailable chat_id={}", chat_id)
        elif str(result.get("status") or "").lower() == "error":
            if logger is not None:
                logger.warning(
                    "QQ yage delivery ack failed chat_id={} reason={}",
                    chat_id,
                    result.get("reason") or "unknown",
                )
        elif result.get("updated") and logger is not None:
            logger.info(
                "QQ yage delivery ack updated chat_id={} prev={} new={}",
                chat_id,
                result.get("prev") or "(empty)",
                source_url,
            )

    if not wechat_ack:
        return
    sub_id, entry_id = wechat_ack
    if sub_id < 0 or entry_id <= 0:
        return
    result = await qq_rss_sidecar.ack_wechat_delivery(
        session,
        sub_id,
        entry_id,
        timeout_sec=10.0,
        logger=logger,
    )
    if result is None:
        if logger is not None:
            logger.warning("QQ wechat delivery ack sidecar unavailable chat_id={}", chat_id)
        return
    if str(result.get("status") or "").lower() == "error":
        if logger is not None:
            logger.warning(
                "QQ wechat delivery ack failed chat_id={} reason={}",
                chat_id,
                result.get("reason") or "unknown",
            )
        return
    if result.get("updated") and logger is not None:
        logger.info(
            "QQ wechat delivery ack updated chat_id={} key={} prev={} new={}",
            chat_id,
            result.get("key") or f"sub:{sub_id}",
            result.get("prev") or 0,
            entry_id,
        )


__all__ = ["PreparedOutboundContent", "ack_delivery", "prepare_outbound_content"]
