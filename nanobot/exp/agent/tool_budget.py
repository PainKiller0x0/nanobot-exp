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
    "(?:\\u5e2e\\u6211|\\u8bf7\\u4f60|\\u9ebb\\u70e6|\\u7ed9\\u6211|\\u8bf7\\u901a\\u8fc7|"
    "\\u80fd\\u4e0d\\u80fd|\\u53ef\\u4ee5).{0,16}(?:"
    "\\u67e5|\\u68c0\\u67e5|\\u641c|\\u641c\\u7d22|\\u6253\\u5f00|\\u5173\\u95ed|\\u5173\\u6389|"
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
    "^\\s*(?:\\u67e5|\\u68c0\\u67e5|\\u641c\\u7d22|\\u6253\\u5f00|\\u5173\\u95ed|\\u5173\\u6389|\\u8bfb\\u53d6|"
    "\\u5237\\u65b0|\\u90e8\\u7f72|\\u4fee\\u590d|\\u8fd0\\u884c|\\u6267\\u884c)"
    ".{0,24}(?:\\u65e5\\u5fd7|log|\\u670d\\u52a1|\\u5185\\u5b58|\\u5929\\u6c14|"
    "\\u65b0\\u95fb|\\u7f51\\u9875|\\u94fe\\u63a5|\\u6587\\u4ef6|\\u4ee3\\u7801|\\u706f|"
    "\\u4ed3\\u5e93|github|rss|lof|etf|cron)",
    re.I,
)
_ENGLISH_TASK_REQUEST_RE = re.compile(
    r"\b(?:task|files?|inspect(?:ion)?|delegate|pending)\b|"
    r"\b(?:check|read|open|run|test|build|deploy|execute|review)\b"
    r".{0,48}\b(?:files?|directories|directory|folders|folder|workspace|project|"
    r"repositories|repository|repo|logs?|services?|tests?|scripts?|code)\b",
    re.I,
)
_HA_DEVICE_RE = (
    r"(?:\u706f|\u7a7a\u8c03|\u7a97\u5e18|\u63d2\u5ea7|\u5f00\u5173|"
    r"\u7535\u89c6|\u98ce\u6247|\u52a0\u6e7f\u5668|\u51c0\u5316\u5668|"
    r"\u70ed\u6c34\u5668|\u95e8\u9501|light|lamp|switch|climate|cover|fan|plug|lock)"
)
_HA_ACTION_RE = (
    r"(?:\u6253\u5f00|\u5f00\u542f|\u5f00\u706f|\u5f00\u4e00\u4e0b|\u5f00\u4e0b|\u5f00|"
    r"\u5173\u95ed|\u5173\u6389|\u5173\u4e0a|\u5173\u706f|\u5173\u4e00\u4e0b|"
    r"\u5173\u4e0b|\u5173|\u7184\u706d)"
)
_HA_DEVICE_CONTROL_RE = re.compile(
    r"^\s*(?:(?:\u8bf7\u4f60\u5e2e\u6211|\u8bf7\u5e2e\u6211|\u8bf7\u4f60|"
    r"\u9ebb\u70e6|\u5e2e\u6211|\u80fd\u4e0d\u80fd|\u53ef\u4ee5|\u8bf7)?\s*)?"
    r"(?:(?:\u901a\u8fc7|\u4f7f\u7528|\u8c03\u7528)\s*(?:home\s*assistant|ha)\s*)?"
    r"(?:"
    r"(?:\u628a|\u5c06)\s*.{0,48}?" + _HA_DEVICE_RE + r".{0,16}?" + _HA_ACTION_RE
    + r"|" + _HA_ACTION_RE
    + r"[^\u3002\uff01\uff1f!?\uff0c,\uff1b;]{0,32}?" + _HA_DEVICE_RE
    + r")",
    re.I,
)


_HA_CLIMATE_TEMPERATURE_CONTROL_RE = re.compile(
    r"^\s*(?:(?:\u8bf7(?:\u4f60)?(?:\u5e2e\u6211)?|\u9ebb\u70e6(?:\u4f60)?|"
    r"\u5e2e\u6211|(?:\u8bf7)?\u901a\u8fc7\s*(?:home\s*assistant|ha))\s*)?"
    r"(?:(?:\u628a|\u5c06)\s*[^\uff0c,\u3002\uff1b;!?]{0,18}?)?"
    r"(?:\u7a7a\u8c03|climate)\s*(?:\u6e29\u5ea6)?\s*"
    r"(?:\u8c03\u5230|\u8c03\u6210|\u8bbe\u4e3a|\u8bbe\u6210|"
    r"\u8bbe\u5b9a(?:\u5230|\u4e3a)|\u6539\u5230|\u5347\u5230|\u964d\u5230)"
    r"\s*\d{1,2}(?:\.\d+)?\s*(?:\u5ea6|\u00b0\s*C?)?",
    re.I,
)

_HA_CLIMATE_FEATURE_CONTROL_RE = re.compile(
    r"^\s*(?:(?:请(?:你)?|帮我|麻烦(?:你)?)\s*)?(?:(?:把|将)\s*)?"
    r"(?:深圳泊寓(?:客厅)?\s*)?(?:空调|空调伴侣|climate)[^。！？!?]{0,20}"
    r"(?:模式|运行模式|风速|风力|风量|风向|扫风|摆风)[^。！？!?]{0,10}"
    r"(?:调|改|设|切|转|开|关|设置)"
    r"|^\s*(?:(?:请|帮我|麻烦(?:你)?)\s*)?(?:把|将)?\s*"
    r"(?:深圳泊寓(?:客厅)?\s*)?(?:空调|空调伴侣|climate)"
    r"[^。！？!?]{0,12}(?:调到|调成|改成|设为|设置为|切换到|切到)"
    r"\s*(?:自动|制冷|除湿|抽湿|制热|送风|通风|关闭|auto|cool|dry|heat|fan_only|off)"
    r"|^\s*(?:(?:请|帮我|麻烦(?:你)?)\s*)?(?:打开|开启|关闭|停止|调整|调节)"
    r"\s*(?:深圳泊寓(?:客厅)?\s*)?(?:空调|空调伴侣|climate)[^。！？!?]{0,12}"
    r"(?:模式|运行模式|风速|风力|风量|风向|扫风|摆风)"
    r"|^\s*(?:(?:请|帮我|麻烦(?:你)?)\s*)?(?:把|将)?\s*"
    r"(?:风速|风力|风量|风向|扫风|摆风)\s*(?:调|改|设|切|转|开|关|设置)",
    re.I,
)
_HA_CLIMATE_FEATURE_QUERY_RE = re.compile(
    r"^\s*(?:(?:请|帮我|麻烦(?:你)?)\s*)?(?:查|查询|查看|看下|看一下|告诉我)"
    r".{0,16}(?:空调|空调伴侣|climate).{0,16}(?:支持|当前|现在|有哪些|什么|状态|选项)"
    r"|^\s*(?:深圳泊寓.{0,8})?(?:空调|空调伴侣|climate).{0,12}"
    r"(?:支持|当前|现在|什么|哪些).{0,10}(?:模式|风力|风速|风向|扫风|状态)",
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
        or _ENGLISH_TASK_REQUEST_RE.search(text)
    )


_PERSONAL_ARCHIVE_MARKERS = (
    "261014",
    "personal_condition",
    "personal-condition-archive",
    "\u4eba\u751f\u5b58\u6863",
    "\u4e2a\u4eba\u6863\u6848",
    "\u4e2a\u4eba\u8fd1\u51b5",
    "\u8fd1\u51b5",
    "\u5173\u7cfb",
    "\u884c\u4e3a\u6a21\u5f0f",
    "\u6c9f\u901a\u504f\u597d",
    "\u957f\u671f\u5174\u8da3",
    "\u751f\u6d3b\u7cfb\u7edf",
    "\u65e5\u8bb0\u89c4\u8303",
)


def _is_personal_archive_turn(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _PERSONAL_ARCHIVE_MARKERS)


def _read_file_only(tool_definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [definition for definition in tool_definitions if _tool_name(definition) == "read_file"]


def _home_assistant_climate_tools_only(
    tool_definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        definition
        for definition in tool_definitions
        if _tool_name(definition) == "home_assistant_shenzhen_climate_control"
    ]

def _home_assistant_tools_only(
    tool_definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        definition
        for definition in tool_definitions
        if _tool_name(definition).startswith("mcp_home_assistant_")
    ]


def _hide_home_assistant_tools(
    tool_definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        definition
        for definition in tool_definitions
        if not _tool_name(definition).startswith("mcp_home_assistant_")
    ]


def tool_definitions_for_turn(
    tool_definitions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    current_user_text: str | None = None,
    force_tools: bool = False,
) -> tuple[list[dict[str, Any]] | None, str]:
    """Return tool definitions for this turn and a short observability reason."""
    if not tool_definitions:
        return [], "no tools registered"
    if not adaptive_tools_enabled():
        return tool_definitions, "adaptive tool ads disabled"
    text = current_user_text if current_user_text is not None else _latest_user_text(messages)
    if _has_active_tool_context(messages):
        return _hide_non_explicit_image_tools(tool_definitions, text), "active tool context"
    if _is_personal_archive_turn(text):
        read_file_tools = _read_file_only(tool_definitions)
        if read_file_tools:
            return read_file_tools, "personal archive context"
        return None, "personal archive read tool unavailable"
    if _HA_CLIMATE_FEATURE_CONTROL_RE.search(text) or _HA_CLIMATE_FEATURE_QUERY_RE.search(text):
        climate_tools = _home_assistant_climate_tools_only(tool_definitions)
        if climate_tools:
            return climate_tools, "home assistant climate control"
    if _HA_CLIMATE_TEMPERATURE_CONTROL_RE.search(text):
        home_assistant_tools = _home_assistant_tools_only(tool_definitions)
        if home_assistant_tools:
            return home_assistant_tools, "home assistant climate temperature"
    if _HA_DEVICE_CONTROL_RE.search(text):
        home_assistant_tools = _home_assistant_tools_only(tool_definitions)
        if home_assistant_tools:
            return home_assistant_tools, "home assistant control"
    if _has_attachment(text):
        without_home_assistant = _hide_home_assistant_tools(tool_definitions)
        return _hide_non_explicit_image_tools(without_home_assistant, text), "attachment turn"
    if _has_tool_marker(text):
        without_home_assistant = _hide_home_assistant_tools(tool_definitions)
        return _hide_non_explicit_image_tools(without_home_assistant, text), "tool marker"
    if force_tools:
        without_home_assistant = _hide_home_assistant_tools(tool_definitions)
        return _hide_non_explicit_image_tools(without_home_assistant, text), "goal continuation"

    _, reason = replay_budget_for_message(text, default_budget=16000, light_budget=4500)
    if should_omit_tool_ads(reason) and not _explicit_image_generation_request(text):
        return None, reason
    without_home_assistant = _hide_home_assistant_tools(tool_definitions)
    return _hide_non_explicit_image_tools(without_home_assistant, text), reason


def latest_user_text_for_observability(messages: list[dict[str, Any]]) -> str:
    return _latest_user_text(messages)
