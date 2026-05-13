"""QQ-friendly formatters for local memory direct replies."""

from __future__ import annotations

from typing import Any

from nanobot.agent.direct_reply_common import short_text

DASHBOARD_URL = "http://150.158.121.88:8093/reflexio/"


def format_empty_memory() -> str:
    return "没找到要记住的内容。你可以这样说：记住 我喜欢 Rust sidecar。"


def format_memory_saved(content: str, data: dict[str, Any]) -> str:
    if not data.get("success"):
        return "本地记忆写入失败：" + str(data.get("msg") or data.get("error") or "Reflexio 不可用")
    return "\n".join(
        [
            "记住了（本地记忆，未调用 LLM）",
            f"- {content}",
            f"编号：#{data.get('id', '-')}",
            f"详情：{DASHBOARD_URL}",
        ]
    )


def format_memory_status(stats: dict[str, Any], recent: list[Any]) -> str:
    lines = [
        "本地记忆状态（未调用 LLM）",
        f"本地记忆：{stats.get('total_memories', '-')} 条；最新：{stats.get('latest_memory_at') or '-'}",
        f"历史交互：{stats.get('total_interactions', '-')} 条；旧事实：{stats.get('total_facts', '-')} 条",
        "模式：手动写入、本地 SQLite、默认不自动外传",
    ]
    if isinstance(recent, list) and recent:
        lines.append("最近记住：")
        for item in recent[:5]:
            if isinstance(item, dict):
                lines.append(
                    f"- {short_text(item.get('content'), 44)}（{item.get('category', 'note')}）"
                )
    else:
        lines.append("最近记住：暂无。你可以说：记住 我喜欢……")
    lines.append(f"看板：{DASHBOARD_URL}")
    return "\n".join(lines)


def format_memory_search(query: str, results: list[Any]) -> str:
    lines = [f"本地记忆搜索：{query}（未调用 LLM）"]
    if not isinstance(results, list) or not results:
        lines.append("没搜到。可以先说：记住 ……")
    else:
        for item in results[:8]:
            if isinstance(item, dict):
                lines.append(
                    f"- #{item.get('id', '-')} {short_text(item.get('content'), 54)}"
                    f"（{item.get('category', 'note')}，{item.get('created_at', '-')}）"
                )
    lines.append(f"看板：{DASHBOARD_URL}")
    return "\n".join(lines)


__all__ = [
    "DASHBOARD_URL",
    "format_empty_memory",
    "format_memory_saved",
    "format_memory_search",
    "format_memory_status",
]
