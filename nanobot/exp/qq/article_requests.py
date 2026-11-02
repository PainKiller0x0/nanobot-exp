"""Article request parsing for the QQ downstream adapter.

These helpers classify user intent for RSS-backed articles.  Keeping this rule
set outside qq.py makes the upstream botpy adapter easier to compare and update.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

CN_WECHAT = "\u5fae\u4fe1"
CN_OFFICIAL = "\u516c\u4f17\u53f7"
CN_ARTICLE = "\u6587\u7ae0"
CN_POST = "\u63a8\u6587"
CN_IN_ARTICLE = "\u6587\u4e2d"
WECHAT_QUESTION_HINTS = (
    "\u662f\u5426",
    "\u6709\u6ca1\u6709",
    "\u63d0\u5230",
    "\u8bb2\u4e86\u4ec0\u4e48",
    "\u662f\u4ec0\u4e48",
    "\u5565",
    "\u603b\u7ed3",
    "\u6982\u62ec",
)
WECHAT_TITLE_HINTS = (
    "\u6700\u65b0\u7684\u6587\u7ae0\u540d",
    "\u6700\u65b0\u6587\u7ae0\u540d",
    "\u6700\u65b0\u6807\u9898",
    "\u6700\u65b0\u4e00\u7bc7",
    "\u6700\u65b0\u6587\u7ae0",
)

YAGE_HINT = "\u9e2d\u54e5"
YAGE_LATEST_HINTS = ("\u6700\u65b0", "\u53d1\u6211", "\u770b\u770b", "\u6765\u7bc7")
YAGE_ARTICLE_HINTS = ("\u6587\u7ae0", "\u8981\u95fb", "\u624b\u8bb0", "yage")
YAGE_RECENT_HINTS = (
    "\u6628\u5929",
    "\u6628\u665a",
    "\u4e0a\u4e00\u7bc7",
    "\u4e0a\u4e00\u671f",
    "\u4e0a\u671f",
    "\u8fd1\u671f",
)
YAGE_ACTION_HINTS = (
    "\u7ed9\u6211",
    "\u53d1\u6211",
    "\u53d1\u4e00\u7bc7",
    "\u63a8\u9001",
    "\u63a8\u4e00\u4e0b",
    "\u6765\u4e00\u7bc7",
    "\u6765\u4e2a",
    "\u770b\u770b",
    "\u770b\u4e0b",
    "\u67e5\u4e00\u4e0b",
    "\u5e2e\u6211\u627e",
    "\u5e2e\u6211\u62ff",
)
CN_NUM_MAP = {
    "\u4e00": 1,
    "\u4e8c": 2,
    "\u4e09": 3,
    "\u56db": 4,
    "\u4e94": 5,
    "\u516d": 6,
    "\u4e03": 7,
    "\u516b": 8,
    "\u4e5d": 9,
    "\u5341": 10,
    "\u4e24": 2,
}


def extract_wechat_question(content: str) -> str | None:
    text = (content or "").strip()
    lower = text.lower()
    if not text:
        return None
    if CN_WECHAT not in text and CN_OFFICIAL not in text and "wechat" not in lower and "weixin" not in lower:
        return None
    if (
        CN_ARTICLE not in text
        and CN_POST not in text
        and CN_IN_ARTICLE not in text
        and "article" not in lower
        and "post" not in lower
    ):
        return None
    if any(k in text for k in WECHAT_QUESTION_HINTS):
        parts = re.split(r"[:\uFF1A]", text, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        return text
    if "?" in text or "\uFF1F" in text:
        return text
    return None


def is_wechat_title_query(content: str) -> bool:
    text = (content or "").strip()
    lower = text.lower()
    if not text:
        return False
    if CN_WECHAT not in text and CN_OFFICIAL not in text and "wechat" not in lower and "weixin" not in lower:
        return False
    return any(hint in text for hint in WECHAT_TITLE_HINTS) or "latest title" in lower or "latest article" in lower


def cn_num_to_int(text: str) -> int | None:
    t = (text or "").strip()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    if t in CN_NUM_MAP:
        return CN_NUM_MAP[t]
    if len(t) == 2 and t[0] == "\u5341" and t[1] in CN_NUM_MAP:
        return 10 + CN_NUM_MAP[t[1]]
    if len(t) == 2 and t[1] == "\u5341" and t[0] in CN_NUM_MAP:
        return CN_NUM_MAP[t[0]] * 10
    return None


def parse_yage_selector(content: str, *, now: datetime | None = None) -> tuple[int | None, str | None]:
    text = (content or "").strip()
    if not text:
        return None, None
    now = now or datetime.now()

    # Explicit date: 2026-04-12 / 2026年4月12日 / 4月12号
    m = re.search(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return None, f"{y:04d}-{mo:02d}-{d:02d}"
    m2 = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", text)
    if m2:
        mo, d = int(m2.group(1)), int(m2.group(2))
        return None, f"{now.year:04d}-{mo:02d}-{d:02d}"
    # Fallback short date: 04-10 / 4/10
    m2b = re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?!\d)", text)
    if m2b:
        mo, d = int(m2b.group(1)), int(m2b.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return None, f"{now.year:04d}-{mo:02d}-{d:02d}"

    # Relative date
    if "\u6628\u5929" in text or "\u6628\u665a" in text:
        day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return None, day
    if "\u524d\u5929" in text:
        day = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        return None, day

    # Rank selectors
    if "\u5012\u6570\u7b2c\u4e8c" in text or "\u7b2c\u4e8c\u65b0" in text or "\u4e0a\u4e00\u7bc7" in text:
        return 2, None
    m3 = re.search(r"\u7b2c([0-9一二三四五六七八九十两]+)(?:\u65b0|\u7bc7|\u6761)", text)
    if m3:
        n = cn_num_to_int(m3.group(1))
        if n and n > 0:
            return n, None
    if "\u6700\u65b0" in text:
        return 1, None
    return None, None


def is_yage_request(content: str) -> bool:
    text = (content or "").strip()
    lower = text.lower()
    if not text:
        return False
    if YAGE_HINT not in text and "yage" not in lower:
        return False
    # Avoid accidental auto-push in casual discussion.
    has_action_intent = any(k in text for k in YAGE_ACTION_HINTS) or "send me" in lower or "show me" in lower
    has_time_intent = any(k in text for k in YAGE_LATEST_HINTS) or any(k in text for k in YAGE_RECENT_HINTS)
    has_article_intent = any(k in text for k in YAGE_ARTICLE_HINTS) or "article" in lower or "post" in lower
    # Request-like patterns: explicit action OR interrogative wording.
    has_question_tone = (
        ("?" in text)
        or ("\uFF1F" in text)
        or text.endswith(("\u5417", "\u5462", "\u561b"))
        or ("\u6700\u65b0" in text and YAGE_HINT in text)
    )
    has_date_pattern = bool(
        re.search(r"(20\d{2})[年/\-](\d{1,2})[月/\-](\d{1,2})", text)
        or re.search(r"(\d{1,2})月(\d{1,2})[日号]?", text)
        or re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?!\d)", text)
    )
    # Trigger when it looks like a request and has article/time/date intent.
    if not (has_action_intent or has_question_tone):
        return False
    if (not has_article_intent) and (not has_time_intent) and (not has_date_pattern):
        return False
    return True
