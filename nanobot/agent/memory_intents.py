"""Intent matching and normalization helpers for local memory replies."""

from __future__ import annotations

import re

from nanobot.agent.direct_reply_common import compact_text

SAVE_PATTERNS = ('^\\s*(?:帮我)?记住[：:，,\\s]*(.+)$', '^\\s*(?:你)?记一下[：:，,\\s]*(.+)$', '^\\s*以后(?:你)?(?:要)?记得[：:，,\\s]*(.+)$')
SEARCH_PATTERNS = ('^\\s*(?:查|搜索|找)(?:一下)?记忆[：:，,\\s]*(.+)$', '^\\s*你(?:还)?记得(.+?)(?:吗|么)?[？?]?\\s*$')
STATUS_QUERIES = {'记忆状态', '本地记忆', '你都记得什么', '你记得什么', '记忆怎么样', '本地记忆状态', '记忆列表'}
EMPTY_SEARCH_WORDS = {'多少', '什么', '哪些'}
PREFERENCE_HINTS = ('偏好', '喜欢', '不喜欢', '习惯', '希望', '以后', '尽量', '不要', '优先')


def extract_memory_to_save(text: str) -> str | None:
    for pattern in SAVE_PATTERNS:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_content(match.group(1))
    return None


def extract_memory_search(text: str) -> str | None:
    compact = compact_text(text)
    if compact in STATUS_QUERIES:
        return None
    for pattern in SEARCH_PATTERNS:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            query = clean_content(match.group(1))
            if query and query not in EMPTY_SEARCH_WORDS:
                return query
    return None


def is_memory_status_query(text: str) -> bool:
    return compact_text(text) in STATUS_QUERIES


def guess_category(content: str) -> str:
    return "preference" if any(hint in content for hint in PREFERENCE_HINTS) else "note"


def clean_content(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())[:4000]


__all__ = [
    "clean_content",
    "extract_memory_search",
    "extract_memory_to_save",
    "guess_category",
    "is_memory_status_query",
]
