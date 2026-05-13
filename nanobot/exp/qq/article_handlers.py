"""QQ article intent handlers for nanobot-exp.

These helpers handle downstream RSS/Yage/WeChat article shortcuts.  They are
kept outside ``nanobot.channels.qq`` so the botpy channel remains easy to diff
against upstream while personal sidecar behavior stays modular.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nanobot.bus.events import OutboundMessage
from nanobot.exp.qq import article_requests

PublishOutbound = Callable[[OutboundMessage], Awaitable[None]]
RunYageSigned = Callable[..., Awaitable[str | None]]
RunSidecarJson = Callable[..., Awaitable[dict[str, Any] | None]]
IsAllowed = Callable[[str], bool]


async def _publish_qq(
    publish_outbound: PublishOutbound,
    *,
    chat_id: str,
    content: str,
    message_id: str | None,
) -> None:
    await publish_outbound(
        OutboundMessage(
            channel="qq",
            chat_id=chat_id,
            content=content,
            metadata={"message_id": message_id},
        )
    )


async def try_handle_yage_raw(
    *,
    chat_id: str,
    content: str,
    message_id: str | None,
    run_yage_signed: RunYageSigned,
    publish_outbound: PublishOutbound,
    logger: Any | None = None,
) -> bool:
    """Send the matched Yage article directly through QQ when requested."""
    if not article_requests.is_yage_request(content):
        return False

    nth, target_date = article_requests.parse_yage_selector(content)
    raw = await run_yage_signed(
        timeout_sec=45.0,
        nth=nth,
        target_date=target_date,
        force_latest=bool((nth is None and target_date is None) or (nth == 1 and not target_date)),
    )
    if raw is None:
        await _publish_qq(
            publish_outbound,
            chat_id=chat_id,
            content="鸭哥文章抓取失败，请稍后重试。",
            message_id=message_id,
        )
        return True
    if not raw.strip():
        not_found_hint = ""
        if target_date:
            not_found_hint = f" (date={target_date})"
        elif nth and nth > 1:
            not_found_hint = f" (nth={nth})"
        await _publish_qq(
            publish_outbound,
            chat_id=chat_id,
            content=f"当前未抓取到匹配的鸭哥文章内容{not_found_hint}。",
            message_id=message_id,
        )
        return True

    await _publish_qq(
        publish_outbound,
        chat_id=chat_id,
        content=raw,
        message_id=message_id,
    )
    if logger is not None:
        logger.info("QQ yage raw handler sent signed latest article chat_id={}", chat_id)
    return True


async def try_handle_wechat_grounded(
    *,
    user_id: str,
    chat_id: str,
    content: str,
    message_id: str | None,
    is_allowed: IsAllowed,
    run_sidecar_json: RunSidecarJson,
    publish_outbound: PublishOutbound,
) -> bool:
    """Answer WeChat article title/question requests from the RSS sidecar cache."""
    if not is_allowed(user_id):
        return False

    title_query = article_requests.is_wechat_title_query(content)
    question = article_requests.extract_wechat_question(content)
    if not title_query and not question:
        return False

    if title_query and not question:
        latest = await run_sidecar_json(["latest", "--days", "7", "--limit", "50"])
        if not latest or latest.get("status") in {"empty", "error"}:
            reply = "已核验原文：未找到可用文章（NOT_FOUND_IN_ARTICLE）"
        else:
            reply = (
                f"最新文章：{latest.get('title') or ''}\n"
                f"entry_id: {latest.get('entry_id') or 0}\n"
                f"published_at: {latest.get('published_at') or ''}\n"
                f"link: {latest.get('link') or ''}"
            )
        await _publish_qq(
            publish_outbound,
            chat_id=chat_id,
            content=reply,
            message_id=message_id,
        )
        return True

    ask = await run_sidecar_json(["ask", "--question", question or content, "--days", "7", "--limit", "50"])
    if not ask:
        await _publish_qq(
            publish_outbound,
            chat_id=chat_id,
            content="已核验原文：未命中问题答案（NOT_FOUND_IN_ARTICLE）",
            message_id=message_id,
        )
        return True

    status = str(ask.get("status") or "").lower()
    if status != "ok":
        reply = (
            "已核验原文：未命中问题答案（NOT_FOUND_IN_ARTICLE）\n"
            f"entry_id: {ask.get('entry_id') or 0}\n"
            f"published_at: {ask.get('published_at') or ''}\n"
            f"link: {ask.get('link') or ''}"
        )
    else:
        answer = str(ask.get("answer") or "").strip()
        reply = (
            f"entry_id: {ask.get('entry_id') or 0}\n"
            f"published_at: {ask.get('published_at') or ''}\n"
            f"link: {ask.get('link') or ''}\n\n"
            f"{answer or 'NOT_FOUND_IN_ARTICLE'}"
        )
    await _publish_qq(
        publish_outbound,
        chat_id=chat_id,
        content=reply,
        message_id=message_id,
    )
    return True


__all__ = ["try_handle_wechat_grounded", "try_handle_yage_raw"]
