"""QQ deterministic fast-path command matchers.

These helpers intentionally avoid LLM calls for short operational requests such as
"内存怎么样" or "帮助". They only classify; execution remains in QQChannel.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_GENERIC_URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+")
_INBOX_SPECIAL_HOSTS = ("mp.weixin.qq.com", "yage-ai.kit.com", "jintiankansha.me")


def _compact(content: str) -> str:
    return re.sub(r"[\s，。！？!?、:：；;,.]+", "", (content or "").strip().lower())


def match_personal_ops_command(content: str) -> str | None:
    """Map short ops questions to deterministic local dashboard commands."""
    compact = _compact(content)
    if not compact:
        return None

    if any(k in compact for k in ("今天有什么要看", "今天看什么", "今日摘要", "今天摘要")):
        return "today"
    if (
        any(k in compact for k in ("你能做什么", "能力列表", "能力菜单", "菜单", "帮助"))
        and len(compact) <= 16
    ):
        return "menu"
    if "内存" in compact and len(compact) <= 24:
        return "system"
    if any(
        k in compact
        for k in ("系统状态", "服务状态", "服务健康", "服务还活着", "健康检查", "服务器状态")
    ):
        return "system"
    if any(k in compact for k in ("定时任务", "cron", "任务状态", "任务报错", "哪些任务在跑")):
        return "tasks"
    if any(k in compact for k in ("今天先看什么", "先看什么")) and not any(
        k in compact for k in ("收件箱", "待读", "稍后看")
    ):
        return "decision"
    if any(
        k in compact
        for k in ("今天怎么安排", "有什么建议", "决策建议", "下一步做什么", "现在该干嘛")
    ):
        return "decision"
    if any(
        k in compact for k in ("鸭哥", "微信文章", "rss文章", "今天文章", "文章有哪些", "文章更新")
    ):
        return "articles"
    if any(k in compact for k in ("lof", "qdii", "基金溢价", "溢价机会", "套利机会")):
        return "lof"
    return None


def match_knowledge_inbox_command(content: str) -> list[str] | None:
    """Map link/inbox prompts to the local knowledge inbox script argv."""
    text = (content or "").strip()
    compact = _compact(text)
    if not compact:
        return None

    urls = [u.rstrip("。.,，、；;!！?？") for u in _GENERIC_URL_RE.findall(text)]
    if not urls:
        if any(
            k in compact
            for k in ("待读简报", "收件箱简报", "稍后看简报", "收件箱今天先看什么", "待读先看什么")
        ):
            return ["brief", "--limit", "8"]
        if any(k in compact for k in ("收件箱", "待读列表", "链接清单", "稍后看清单")):
            return ["list", "--limit", "8"]
        return None

    url = urls[0]
    host = urlparse(url).netloc.lower()
    explicit_inbox = any(
        k in compact
        for k in (
            "收一下",
            "存一下",
            "加入收件箱",
            "放收件箱",
            "放到收件箱",
            "稍后看",
            "待读",
            "链接收件箱",
        )
    )
    decision = any(
        k in compact
        for k in (
            "值得看",
            "值不值得",
            "要不要看",
            "要不要读",
            "该不该看",
            "帮我判断",
            "帮我看看",
            "决策",
        )
    )
    only_url = text == url or text.strip(" \t\r\n。.,，、；;!！?？") == url

    # WeChat/Yage links have dedicated handlers. Do not steal them unless the
    # user explicitly asks to put the link into the generic inbox.
    if any(special in host for special in _INBOX_SPECIAL_HOSTS) and not (
        explicit_inbox or only_url
    ):
        return None
    if decision:
        question = _GENERIC_URL_RE.sub("", text).strip()
        return ["decide", url, "--question", question[:180] or "这个值得看吗"]
    if explicit_inbox or only_url:
        return ["capture", url]
    return None
