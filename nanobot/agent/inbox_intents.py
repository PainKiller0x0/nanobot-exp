"""Intent matching helpers for knowledge inbox direct replies."""

from __future__ import annotations

import re
from typing import Any

from nanobot.agent.direct_reply_common import compact_text

URL_RE = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)
TRAILING_PUNCT = " \t\r\n,，。；;！!？?）)]】》>\"'"

CAPTURE_PREFIXES = (
    "收一下",
    "存一下",
    "收藏",
    "稍后看",
    "加入收件箱",
    "放进收件箱",
)
CAPTURE_COMPACT_MARKERS = (
    "收一下",
    "存一下",
    "收藏",
    "稍后看",
    "加入收件箱",
    "放进收件箱",
)
DECIDE_COMPACT_MARKERS = (
    "这个值得看吗",
    "值得看吗",
    "要不要读",
    "值得读吗",
    "帮我判断",
    "帮我看看",
)
LIST_QUERIES = {
    "收件箱",
    "知识收件箱",
    "待读列表",
    "稍后看列表",
    "最近收了什么",
}
BRIEF_QUERIES = {
    "待读简报",
    "收件箱简报",
    "今天先看什么资料",
}


def extract_inbox_intent(text: str) -> dict[str, Any] | None:
    """Return a small command description when the message targets the inbox."""
    raw = (text or "").strip()
    compact = compact_text(raw)
    if not compact:
        return None
    if compact in LIST_QUERIES:
        return {"action": "list"}
    if compact in BRIEF_QUERIES:
        return {"action": "brief"}

    url = extract_url(raw)
    if not url:
        return None

    if any(marker in compact for marker in DECIDE_COMPACT_MARKERS):
        return {"action": "decide", "url": url, "question": raw}

    raw_without_punct = raw.strip().rstrip(TRAILING_PUNCT).strip()
    if raw_without_punct == url:
        return {"action": "capture", "url": url}

    if raw.startswith(CAPTURE_PREFIXES) or any(
        marker in compact for marker in CAPTURE_COMPACT_MARKERS
    ):
        return {"action": "capture", "url": url}

    return None


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(TRAILING_PUNCT)


__all__ = [
    "extract_inbox_intent",
    "extract_url",
]
