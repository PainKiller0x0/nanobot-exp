"""Deterministic fast replies that do not need an LLM call."""

from __future__ import annotations

from typing import Any

from nanobot.agent import inbox_reply, memory_reply, system_reply
from nanobot.agent.capability_reply import (
    format_capability_menu,
    format_capability_status,
    format_evolution_brief,
    format_today_brief,
)
from nanobot.agent.direct_reply_common import compact_text as _compact_text
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.command.help_panel import is_capability_menu_query

_MEMORY_WORD = "\u5185\u5b58"
_ACK_WORDS = {
    "ok",
    "okay",
    "\u55ef",
    "\u55ef\u55ef",
    "\u597d",
    "\u597d\u7684",
    "\u597d\u53ef\u4ee5",
    "\u53ef\u4ee5",
    "\u884c",
    "\u884c\u7684",
    "\u6ca1\u95ee\u9898",
    "\u6536\u5230",
    "\u4e86\u89e3",
    "\u660e\u767d",
}

_CASUAL_REPLIES = {
    "\u6709\u70b9\u610f\u601d": "\u6709\u70b9\u610f\u601d\uff0c\u5c55\u5f00\u8bf4\u8bf4\uff1f",
    "\u6709\u70b9\u610f\u601d\u7684": "\u6709\u70b9\u610f\u601d\uff0c\u5c55\u5f00\u8bf4\u8bf4\uff1f",
    "\u6211\u5148\u4e0d\u544a\u8bc9\u4f60": "\u884c\uff0c\u90a3\u6211\u5148\u4fdd\u6301\u597d\u5947\u3002",
}

_ACTION_HINTS = (
    "\u8981\u4e0d\u8981",
    "\u662f\u5426",
    "\u786e\u8ba4",
    "\u9009\u62e9",
    "\u9700\u8981\u6211",
    "\u6211\u53ef\u4ee5",
    "\u8981\u6211",
    "\u7ee7\u7eed\u5417",
    "\u6267\u884c\u5417",
    "\u8fd0\u884c\u5417",
    "\u91cd\u542f\u5417",
    "\u5220\u9664\u5417",
    "\u63d0\u4ea4\u5417",
    "\u63a8\u9001\u5417",
    "\u90e8\u7f72\u5417",
    "\u5b89\u88c5\u5417",
    "\u540c\u6b65\u5417",
    "reply",
    "choose",
)


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
    if _is_memory_query(text):
        return _outbound(msg, system_reply.format_memory_report(model, start_time, last_usage or {}))
    if is_capability_menu_query(_compact_text(text)):
        return _outbound(msg, format_capability_menu())
    if _is_capability_status_query(text):
        return _outbound(msg, format_capability_status())
    if _is_today_brief_query(text):
        return _outbound(msg, format_today_brief())
    if _is_evolution_query(text):
        return _outbound(msg, format_evolution_brief())
    if _is_ack(text) and _can_direct_ack(history or []):
        return _outbound(msg, "\u597d\uff0c\u6211\u5728\u3002")
    if casual := _casual_reply(text):
        return _outbound(msg, casual)
    return None


def _outbound(msg: InboundMessage, content: str) -> OutboundMessage:
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=content,
        metadata={**(msg.metadata or {}), "_direct_reply": True},
    )


def _casual_reply(text: str) -> str | None:
    return _CASUAL_REPLIES.get(_compact_text(text))


def _is_memory_query(text: str) -> bool:
    compact = _compact_text(text)
    if not compact:
        return False
    exact = {
        _MEMORY_WORD,
        f"{_MEMORY_WORD}\u600e\u4e48\u6837",
        f"{_MEMORY_WORD}\u60c5\u51b5",
        f"{_MEMORY_WORD}\u5360\u7528",
        f"\u670d\u52a1\u5668{_MEMORY_WORD}",
        f"nanobot{_MEMORY_WORD}",
    }
    if compact in exact:
        return True
    return (
        _MEMORY_WORD in compact
        and len(compact) <= 18
        and compact.startswith(
            (
                "\u770b\u4e0b",
                "\u770b\u770b",
                "\u67e5\u4e0b",
                "\u67e5\u4e00\u4e0b",
            )
        )
    )


def _is_capability_status_query(text: str) -> bool:
    compact = _compact_text(text)
    exact = {
        "\u80fd\u529b\u72b6\u6001",
        "\u80fd\u529b\u5065\u5eb7",
        "\u670d\u52a1\u72b6\u6001",
        "\u670d\u52a1\u8fd8\u6d3b\u7740\u5417",
        "sidecar\u72b6\u6001",
        "sidecars\u72b6\u6001",
        "\u770b\u4e0b\u670d\u52a1",
        "\u67e5\u4e0b\u670d\u52a1",
    }
    return compact in exact


def _is_today_brief_query(text: str) -> bool:
    compact = _compact_text(text)
    exact = {
        "\u4eca\u5929\u5148\u770b\u4ec0\u4e48",
        "\u4eca\u5929\u6709\u4ec0\u4e48\u8981\u770b",
        "\u4eca\u65e5\u6458\u8981",
        "\u4eca\u5929\u6458\u8981",
        "\u4eca\u5929\u600e\u4e48\u5b89\u6392",
        "\u6709\u4ec0\u4e48\u5efa\u8bae",
    }
    return compact in exact


def _is_evolution_query(text: str) -> bool:
    compact = _compact_text(text)
    exact = {
        "\u4f60\u6700\u8fd1\u8fdb\u5316\u4e86\u5417",
        "\u6700\u8fd1\u8fdb\u5316\u4e86\u5417",
        "\u8fdb\u5316\u65e5\u5fd7",
        "\u8fdb\u5316\u62a5\u544a",
        "\u4f60\u53d8\u5f3a\u4e86\u5417",
        "\u4f60\u6709\u4ec0\u4e48\u53d8\u5316",
    }
    return compact in exact or ("\u8fdb\u5316" in compact and len(compact) <= 18)


def _is_ack(text: str) -> bool:
    compact = _compact_text(text)
    return compact in _ACK_WORDS


def _can_direct_ack(history: list[dict[str, Any]]) -> bool:
    """Avoid swallowing confirmations for pending questions or proposed actions."""
    last_assistant = ""
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        if isinstance(content, str):
            last_assistant = content
            break
    if not last_assistant:
        return True
    compact = _compact_text(last_assistant)
    return not any(hint in compact for hint in _ACTION_HINTS)
