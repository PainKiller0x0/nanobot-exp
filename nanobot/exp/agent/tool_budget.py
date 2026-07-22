"""Downstream tool-advertising budget helpers.

Gemini Web receives OpenAI tool schemas as plain text, so advertising every
Nanobot tool on every casual turn adds a large fixed prompt cost. Keep tools for
contextual/task turns, but skip them for short standalone chat.
"""

from __future__ import annotations

import os
import re
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

_IMAGE_TOOL_NAMES = frozenset({"generate_image"})
_IMAGE_REQUEST_NEGATIVE_MARKERS = (
    "do not generate image",
    "don't generate image",
    "not generate image",
    "just describe",
    "\u753b\u56fe\u5d29",
    "\u751f\u56fe\u5931\u8d25",
    "\u751f\u6210\u56fe\u7247\u5931\u8d25",
    "\u5e2e\u6211\u770b\u4e0b\u65e5\u5fd7",
    "\u770b\u4e0b\u65e5\u5fd7",
    "\u62a5\u9519",
)
_IMAGE_REQUEST_MARKERS = (
    "generate an image",
    "create an image",
    "draw an image",
    "make an image",
    "generate a picture",
    "create a picture",
    "draw a picture",
    "\u7ed9\u6211\u753b",
    "\u5e2e\u6211\u753b",
    "\u753b\u4e00\u5f20",
    "\u753b\u5f20",
    "\u751f\u6210\u4e00\u5f20\u56fe",
    "\u751f\u6210\u56fe\u7247",
    "\u521b\u5efa\u56fe\u7247",
    "\u51fa\u4e00\u5f20\u56fe",
)


def _explicit_image_generation_request(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered or any(marker in lowered for marker in _IMAGE_REQUEST_NEGATIVE_MARKERS):
        return False
    return any(marker in lowered for marker in _IMAGE_REQUEST_MARKERS)


def _tool_name(definition: dict[str, Any]) -> str:
    function = definition.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "").strip().lower()
    return str(definition.get("name") or "").strip().lower()


def _hide_non_explicit_image_tools(
    tool_definitions: list[dict[str, Any]], text: str
) -> list[dict[str, Any]]:
    if _explicit_image_generation_request(text):
        return tool_definitions
    return [
        definition
        for definition in tool_definitions
        if _tool_name(definition) not in _IMAGE_TOOL_NAMES
    ]


# A vague word such as "look" is common in normal conversation. Advertising
# every tool for it turns a chat reply into a full workbench request. Require a
# clear instruction plus an operational verb, or a direct status question.
_EXPLICIT_TOOL_ACTION_RE = re.compile(
    "(?:\\u5e2e\\u6211|\\u8bf7\\u4f60|\\u9ebb\\u70e6|\\u7ed9\\u6211|"
    "\\u80fd\\u4e0d\\u80fd|\\u53ef\\u4ee5).{0,16}(?:"
    "\\u67e5|\\u68c0\\u67e5|\\u641c|\\u641c\\u7d22|\\u6253\\u5f00|"
    "\\u8bfb\\u53d6|\\u5237\\u65b0|\\u90e8\\u7f72|\\u4fee\\u590d|\\u6539|"
    "\\u6536\\u4e00\\u4e0b|\\u63a8\\u9001|\\u8fd0\\u884c|\\u6267\\u884c)",
    re.I,
)
_DIRECT_STATUS_QUERY_RE = re.compile(
    "(?:\\u5185\\u5b58|\\u670d\\u52a1|\\u72b6\\u6001|\\u65e5\\u5fd7|log|"
    "\\u5929\\u6c14|\\u65b0\\u95fb|\\u70ed\\u641c|lof|etf|rss|cron).{0,16}"
    "(?:\\u600e\\u4e48\\u6837|\\u600e\\u6837|\\u591a\\u5c11|\\u6709\\u6ca1\\u6709|"
    "\\u662f\\u4ec0\\u4e48|\\u51fa\\u95ee\\u9898|\\u597d\\u4e86\\u5417)",
    re.I,
)
_DIRECT_OPERATION_RE = re.compile(
    "^\\s*(?:\\u67e5|\\u68c0\\u67e5|\\u641c\\u7d22|\\u6253\\u5f00|\\u8bfb\\u53d6|"
    "\\u5237\\u65b0|\\u90e8\\u7f72|\\u4fee\\u590d|\\u8fd0\\u884c|\\u6267\\u884c)"
    ".{0,24}(?:\\u65e5\\u5fd7|log|\\u670d\\u52a1|\\u5185\\u5b58|\\u5929\\u6c14|"
    "\\u65b0\\u95fb|\\u7f51\\u9875|\\u94fe\\u63a5|\\u6587\\u4ef6|\\u4ee3\\u7801|"
    "\\u4ed3\\u5e93|github|rss|lof|etf|cron)",
    re.I,
)


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
    if "http://" in lowered or "https://" in lowered:
        return True
    return bool(
        _EXPLICIT_TOOL_ACTION_RE.search(text)
        or _DIRECT_STATUS_QUERY_RE.search(text)
        or _DIRECT_OPERATION_RE.search(text)
    )


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
    text = current_user_text if current_user_text is not None else _latest_user_text(messages)
    if _has_active_tool_context(messages):
        return _hide_non_explicit_image_tools(tool_definitions, text), "active tool context"
    if _has_attachment(text):
        return _hide_non_explicit_image_tools(tool_definitions, text), "attachment turn"
    if _has_tool_marker(text):
        return _hide_non_explicit_image_tools(tool_definitions, text), "tool marker"

    _, reason = replay_budget_for_message(text, default_budget=16000, light_budget=4500)
    if should_omit_tool_ads(reason) and not _explicit_image_generation_request(text):
        return None, reason
    return _hide_non_explicit_image_tools(tool_definitions, text), reason


def latest_user_text_for_observability(messages: list[dict[str, Any]]) -> str:
    return _latest_user_text(messages)
