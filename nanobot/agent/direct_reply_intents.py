"""Intent matching helpers for deterministic direct replies."""

from __future__ import annotations

from typing import Any

from nanobot.agent.direct_reply_common import compact_text

MEMORY_WORD = "内存"
ACK_WORDS = {
    "ok",
    "okay",
    "嗯",
    "嗯嗯",
    "好",
    "好的",
    "好可以",
    "可以",
    "行",
    "行的",
    "没问题",
    "收到",
    "了解",
    "明白",
}

CASUAL_REPLIES = {
    "有点意思": "有点意思，展开说说？",
    "有点意思的": "有点意思，展开说说？",
    "我先不告诉你": "行，那我先保持好奇。",
}

ACTION_HINTS = (
    "要不要",
    "是否",
    "确认",
    "选择",
    "需要我",
    "我可以",
    "要我",
    "继续吗",
    "执行吗",
    "运行吗",
    "重启吗",
    "删除吗",
    "提交吗",
    "推送吗",
    "部署吗",
    "安装吗",
    "同步吗",
    "reply",
    "choose",
)


def casual_reply(text: str) -> str | None:
    return CASUAL_REPLIES.get(compact_text(text))


def is_memory_query(text: str) -> bool:
    compact = compact_text(text)
    if not compact:
        return False
    exact = {
        MEMORY_WORD,
        f"{MEMORY_WORD}怎么样",
        f"{MEMORY_WORD}情况",
        f"{MEMORY_WORD}占用",
        f"服务器{MEMORY_WORD}",
        f"nanobot{MEMORY_WORD}",
    }
    if compact in exact:
        return True
    return (
        MEMORY_WORD in compact
        and len(compact) <= 18
        and compact.startswith(("看下", "看看", "查下", "查一下"))
    )


def is_capability_status_query(text: str) -> bool:
    compact = compact_text(text)
    exact = {
        "能力状态",
        "能力健康",
        "服务状态",
        "服务还活着吗",
        "sidecar状态",
        "sidecars状态",
        "看下服务",
        "查下服务",
    }
    return compact in exact


def is_today_brief_query(text: str) -> bool:
    compact = compact_text(text)
    exact = {
        "今天先看什么",
        "今天有什么要看",
        "今日摘要",
        "今天摘要",
        "今天怎么安排",
        "有什么建议",
    }
    return compact in exact


def is_evolution_query(text: str) -> bool:
    compact = compact_text(text)
    exact = {
        "你最近进化了吗",
        "最近进化了吗",
        "进化日志",
        "进化报告",
        "你变强了吗",
        "你有什么变化",
    }
    return compact in exact or ("进化" in compact and len(compact) <= 18)


def is_ack(text: str) -> bool:
    return compact_text(text) in ACK_WORDS


def can_direct_ack(history: list[dict[str, Any]]) -> bool:
    """Avoid swallowing confirmations for pending questions or proposed actions."""
    last_assistant = ""
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        if isinstance(content, str):
            last_assistant = content
            break
    if not last_assistant:
        return True
    compact = compact_text(last_assistant)
    return not any(hint in compact for hint in ACTION_HINTS)


__all__ = [
    "can_direct_ack",
    "casual_reply",
    "is_ack",
    "is_capability_status_query",
    "is_evolution_query",
    "is_memory_query",
    "is_today_brief_query",
]
