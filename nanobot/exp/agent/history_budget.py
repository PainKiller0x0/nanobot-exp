"""Downstream history replay budget helpers.

The goal is latency control, not memory deletion: summaries and persisted history
stay intact, while short standalone chat turns avoid replaying a huge raw tail.
"""

from __future__ import annotations

import os
import re

DEFAULT_LIGHT_REPLAY_TOKENS = 4_500
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}

_CONTEXT_MARKERS = (
    "继续",
    "接着",
    "刚才",
    "刚刚",
    "上面",
    "前面",
    "之前",
    "上次",
    "前面的",
    "后面",
    "这个",
    "那个",
    "这些",
    "那些",
    "这里",
    "那里",
    "它",
    "他们",
    "你说",
    "你刚",
    "不是",
    "不对",
    "还是",
    "记得",
    "记忆",
    "回忆",
)

_TASK_MARKERS = (
    "nanobot",
    "obp",
    "sidecar",
    "gemini",
    "deepseek",
    "longcat",
    "github",
    "git",
    "commit",
    "push",
    "action",
    "ci",
    "代码",
    "仓库",
    "服务器",
    "日志",
    "log",
    "报错",
    "bug",
    "修改",
    "修复",
    "修一下",
    "改一下",
    "改成",
    "改掉",
    "改代码",
    "改网页",
    "优化",
    "部署",
    "回测",
    "检查",
    "排查",
    "review",
    "实现",
    "功能",
    "网页",
    "接口",
    "api",
    "模型",
    "路由",
    "cron",
    "podman",
    "docker",
    "rss",
    "qq",
    "微信",
    "飞书",
    "截图",
    "图片",
    "文件",
    "查",
    "搜",
    "搜索",
    "看下",
    "看一下",
    "帮我看",
    "打开",
    "链接",
    "天气预报",
    "预报",
    "新闻",
    "热搜",
    "基金",
    "lof",
    "etf",
    "文章",
    "订阅",
    "收件箱",
    "补读",
    "内存",
    "状态",
    "服务",
    "提醒",
)

_URL_RE = re.compile(r"https?://|www\.", re.I)
_CODE_OR_PATH_RE = re.compile(
    r"```|`[^`]+`|[A-Za-z]:\\|/(root|tmp|opt|home)/|\.(py|rs|ts|js|json|toml|yaml|yml)\b",
    re.I,
)

_REPORT_REQUEST_RE = re.compile(
    r"(帮我|给我|替我|帮忙|麻烦|请你|能不能|可以).{0,12}日报|"
    r"日报.{0,12}(怎么写|写一下|写一份|生成|整理|模板|内容)",
    re.I,
)


def _configured_light_budget() -> int:
    raw = os.getenv("NANOBOT_LIGHT_REPLAY_TOKENS", "").strip()
    if raw:
        try:
            return max(512, int(raw))
        except ValueError:
            pass
    return DEFAULT_LIGHT_REPLAY_TOKENS


def light_system_prompt_enabled() -> bool:
    raw = os.getenv("NANOBOT_LIGHT_SYSTEM_PROMPT", "1").strip().lower()
    return raw not in _FALSE_VALUES


def replay_budget_for_message(
    content: str,
    *,
    default_budget: int,
    has_media: bool = False,
    light_budget: int | None = None,
) -> tuple[int, str]:
    """Return a safe replay budget and the reason for observability.

    This is intentionally conservative: anything that looks contextual,
    technical, long-form, or attachment-backed keeps the normal budget.
    """
    if default_budget <= 0:
        return default_budget, "replay disabled"

    budget = light_budget if light_budget is not None else _configured_light_budget()
    budget = max(512, min(default_budget, budget))
    text = (content or "").strip()
    lowered = text.lower()

    if has_media:
        return default_budget, "media turn"
    if not text:
        return budget, "empty short turn"
    if len(text) > 220:
        return default_budget, "long user turn"
    if text.count("\n") >= 2:
        return default_budget, "structured user turn"
    if _URL_RE.search(text):
        return default_budget, "url turn"
    if _CODE_OR_PATH_RE.search(text):
        return default_budget, "code or path turn"

    for marker in _CONTEXT_MARKERS:
        if marker in text:
            return default_budget, f"context marker: {marker}"
    if _REPORT_REQUEST_RE.search(text):
        return default_budget, "task marker: 日报请求"
    for marker in _TASK_MARKERS:
        if marker in lowered or marker in text:
            return default_budget, f"task marker: {marker}"

    return budget, "short standalone turn"
