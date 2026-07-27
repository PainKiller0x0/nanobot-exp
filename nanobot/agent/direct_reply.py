"""Deterministic fast replies that do not need an LLM call."""

from __future__ import annotations

from typing import Any

from nanobot.agent import direct_reply_intents as intents
from nanobot.agent import inbox_reply, memory_reply, system_reply
from nanobot.agent.capability_reply import (
    format_capability_menu,
    format_capability_status,
    format_evolution_brief,
    format_today_brief,
)
from nanobot.agent.direct_reply_common import compact_text as _compact_text
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.command.help_panel import HELP_ALIASES, build_help_text, is_capability_menu_query


def build_direct_reply(
    msg: InboundMessage,
    *,
    model: str,
    start_time: float,
    last_usage: dict[str, int] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> OutboundMessage | None:
    """Return a deterministic reply for cheap status/chitchat intents, if matched."""
    text = (msg.content or "").strip()
    if inbox_intent := inbox_reply.extract_inbox_intent(text):
        return _outbound(
            msg,
            inbox_reply.handle_inbox_intent(inbox_intent, msg.sender_id or msg.chat_id),
        )
    if memory := memory_reply.extract_memory_to_save(text):
        return _outbound(msg, memory_reply.remember_memory(memory, msg.sender_id or msg.chat_id))
    if memory_reply.is_memory_status_query(text):
        return _outbound(msg, memory_reply.format_memory_status())
    if memory_query := memory_reply.extract_memory_search(text):
        return _outbound(msg, memory_reply.search_memory(memory_query))
    if intents.is_memory_query(text):
        return _outbound(msg, system_reply.format_memory_report(model, start_time, last_usage or {}))
    if _compact_text(text) in HELP_ALIASES:
        return _outbound(msg, build_help_text())
    if is_capability_menu_query(_compact_text(text)):
        return _outbound(msg, format_capability_menu())
    if intents.is_capability_status_query(text):
        return _outbound(msg, format_capability_status())
    if intents.is_today_brief_query(text):
        return _outbound(msg, format_today_brief())
    if intents.is_evolution_query(text):
        return _outbound(msg, format_evolution_brief())
    if intents.is_ack(text) and intents.can_direct_ack(history or []):
        return _outbound(msg, "\u597d\uff0c\u6211\u5728\u3002")
    if casual := intents.casual_reply(text):
        return _outbound(msg, casual)
    return None


def _outbound(msg: InboundMessage, content: str) -> OutboundMessage:
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=content,
        metadata={**(msg.metadata or {}), "_direct_reply": True},
    )
