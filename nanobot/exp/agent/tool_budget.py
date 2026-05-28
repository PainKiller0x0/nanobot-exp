"""Downstream tool-advertising budget helpers.

Gemini Web receives OpenAI tool schemas as plain text, so advertising every
Nanobot tool on every casual turn adds a large fixed prompt cost. Keep tools for
contextual/task turns, but skip them for short standalone chat.
"""

from __future__ import annotations

import os
from typing import Any

from nanobot.exp.agent.history_budget import (
    replay_budget_for_message,
    should_omit_tool_ads,
)

_TOOL_MARKERS = (
    "查",
    "搜",
    "搜索",
    "看下",
    "看一下",
    "帮我看",
    "打开",
    "链接",
    "网页",
    "网站",
    "http://",
    "https://",
    "天气预报",
    "预报",
    "新闻",
    "热搜",
    "基金",
    "lof",
    "etf",
    "rss",
    "文章",
    "订阅",
    "收件箱",
    "补读",
    "内存",
    "状态",
    "服务",
    "日志",
    "log",
    "报错",
    "github",
    "代码",
    "服务器",
    "cron",
    "任务",
    "提醒",
    "部署",
    "回测",
)

_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def adaptive_tools_enabled() -> bool:
    raw = os.getenv("NANOBOT_ADAPTIVE_TOOL_ADS", "1").strip().lower()
    return raw not in _FALSE_VALUES


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            if item.get("type") in {"text", "input_text", "output_text"}:
                parts.append(str(item.get("text") or ""))
            elif item.get("type") in {"image_url", "input_image", "file", "input_file"}:
                parts.append("[attachment]")
        return "\n".join(part for part in parts if part)
    return str(content)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _content_to_text(message.get("content"))
    return ""


def _has_active_tool_context(messages: list[dict[str, Any]]) -> bool:
    """True when the current model turn is continuing an in-flight tool loop.

    Old tool calls in earlier history should not force every later casual chat
    turn to advertise all tool schemas again. Only messages after the latest
    user turn can represent the active tool loop for this request.
    """
    latest_user_idx = -1
    for idx, message in enumerate(messages):
        if message.get("role") == "user":
            latest_user_idx = idx
    tail = messages[latest_user_idx + 1 :] if latest_user_idx >= 0 else messages
    for message in tail:
        if message.get("role") == "tool" or message.get("tool_calls"):
            return True
    return False


def _has_attachment(text: str) -> bool:
    return "[attachment]" in text or "[Image URL:" in text or "[File:" in text


def _has_tool_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered or marker in text for marker in _TOOL_MARKERS)


def tool_definitions_for_turn(
    tool_definitions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    current_user_text: str | None = None,
) -> tuple[list[dict[str, Any]] | None, str]:
    """Return tool definitions for this turn and a short observability reason."""
    if not tool_definitions:
        return [], "no tools registered"
    if not adaptive_tools_enabled():
        return tool_definitions, "adaptive tool ads disabled"
    if _has_active_tool_context(messages):
        return tool_definitions, "active tool context"

    text = current_user_text if current_user_text is not None else _latest_user_text(messages)
    if _has_attachment(text):
        return tool_definitions, "attachment turn"
    if _has_tool_marker(text):
        return tool_definitions, "tool marker"

    _, reason = replay_budget_for_message(text, default_budget=16000, light_budget=4500)
    if should_omit_tool_ads(reason):
        return None, reason
    return tool_definitions, reason


def latest_user_text_for_observability(messages: list[dict[str, Any]]) -> str:
    return _latest_user_text(messages)
