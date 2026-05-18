"""Deterministic direct replies for the lightweight knowledge inbox skill."""

from __future__ import annotations

from typing import Any

from nanobot.agent import inbox_intents
from nanobot.agent.inbox_tool import clip_text as _clip
from nanobot.agent.inbox_tool import run_tool as _run_tool

_DASHBOARD_URL = "http://150.158.121.88:8093/inbox"


def extract_inbox_intent(text: str) -> dict[str, Any] | None:
    return inbox_intents.extract_inbox_intent(text)


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
    elif action == "backread-list":
        output = _run_tool(["backread-list", "--limit", "8"], user_id=user_id)
    elif action == "backread":
        output = _run_tool(["backread", str(intent.get("query") or ""), "--full"], user_id=user_id)
    elif action == "list":
        output = _run_tool(["list", "--limit", "8"], user_id=user_id)
    else:
        return "知识收件箱暂时没识别这个动作。"

    output = output.strip() or "知识收件箱已处理。"
    if action != "backread":
        output = _clip(output)
    if "知识收件箱失败" in output:
        return output
    return f"{output}\n\n看板：{_DASHBOARD_URL}\n（未调用 LLM）"
