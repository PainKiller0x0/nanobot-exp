"""Downstream history replay budget helpers.

The goal is latency control, not memory deletion: summaries and persisted history
stay intact, while short standalone chat turns avoid replaying a huge raw tail.
"""

from __future__ import annotations

import os
import re

DEFAULT_LIGHT_REPLAY_TOKENS = 4_500

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
    "修",
    "改",
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
)

_URL_RE = re.compile(r"https?://|www\.", re.I)
_CODE_OR_PATH_RE = re.compile(
    r"```|`[^`]+`|[A-Za-z]:\\|/(root|tmp|opt|home)/|\.(py|rs|ts|js|json|toml|yaml|yml)\b",
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
    for marker in _TASK_MARKERS:
        if marker in lowered or marker in text:
            return default_budget, f"task marker: {marker}"

    return budget, "short standalone turn"
