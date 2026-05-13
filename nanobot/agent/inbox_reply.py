"""Deterministic direct replies for the lightweight knowledge inbox skill."""

from __future__ import annotations

import re
from typing import Any

from nanobot.agent.direct_reply_common import compact_text
from nanobot.agent.inbox_tool import clip_text as _clip
from nanobot.agent.inbox_tool import run_tool as _run_tool

_URL_RE = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)
_TRAILING_PUNCT = " \t\r\n,，。；;！!？?）)]】》>\"'"

_CAPTURE_PREFIXES = (
    "收一下",
    "存一下",
    "收藏",
    "稍后看",
    "加入收件箱",
    "放进收件箱",
)
_CAPTURE_COMPACT_MARKERS = (
    "收一下",
    "存一下",
    "收藏",
    "稍后看",
    "加入收件箱",
    "放进收件箱",
)
_DECIDE_COMPACT_MARKERS = (
    "这个值得看吗",
    "值得看吗",
    "要不要读",
    "值得读吗",
    "帮我判断",
    "帮我看看",
)
_LIST_QUERIES = {
    "收件箱",
    "知识收件箱",
    "待读列表",
    "稍后看列表",
    "最近收了什么",
}
_BRIEF_QUERIES = {
    "待读简报",
    "收件箱简报",
    "今天先看什么资料",
}
_DASHBOARD_URL = "http://150.158.121.88:8093/inbox"


def extract_inbox_intent(text: str) -> dict[str, Any] | None:
    """Return a small command description when the message targets the inbox."""
    raw = (text or "").strip()
    compact = compact_text(raw)
    if not compact:
        return None
    if compact in _LIST_QUERIES:
        return {"action": "list"}
    if compact in _BRIEF_QUERIES:
        return {"action": "brief"}

    url = _extract_url(raw)
    if not url:
        return None

    if any(marker in compact for marker in _DECIDE_COMPACT_MARKERS):
        return {"action": "decide", "url": url, "question": raw}

    raw_without_punct = raw.strip().rstrip(_TRAILING_PUNCT).strip()
    if raw_without_punct == url:
        return {"action": "capture", "url": url}

    if raw.startswith(_CAPTURE_PREFIXES) or any(marker in compact for marker in _CAPTURE_COMPACT_MARKERS):
        return {"action": "capture", "url": url}

    return None


def handle_inbox_intent(intent: dict[str, Any], user_id: str | None = None) -> str:
    """Run the external skill and format a QQ-friendly response."""
    action = str(intent.get("action") or "")
    if action == "capture":
        output = _run_tool(["capture", str(intent.get("url") or "")], user_id=user_id)
    elif action == "decide":
        args = ["decide", str(intent.get("url") or "")]
        question = str(intent.get("question") or "").strip()
        if question:
            args.extend(["--question", question])
        output = _run_tool(args, user_id=user_id)
    elif action == "brief":
        output = _run_tool(["brief", "--limit", "8"], user_id=user_id)
    elif action == "list":
        output = _run_tool(["list", "--limit", "8"], user_id=user_id)
    else:
        return "知识收件箱暂时没识别这个动作。"

    output = _clip(output.strip() or "知识收件箱已处理。")
    if "知识收件箱失败" in output:
        return output
    return f"{output}\n\n看板：{_DASHBOARD_URL}\n（未调用 LLM）"


def _extract_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(_TRAILING_PUNCT)
