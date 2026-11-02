"""QQ deterministic fast-path command matchers.

These helpers intentionally avoid LLM calls for short operational requests such as
"内存怎么样" or "帮助". They only classify; execution remains in QQChannel.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_GENERIC_URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+")
_INBOX_SPECIAL_HOSTS = ("mp.weixin.qq.com", "yage-ai.kit.com", "jintiankansha.me")
_BACKREAD_RE = re.compile(r"^(?:帮我|给我|麻烦)?(?:补读|补看|回看|再看一下)\s*[:：]?\s*(.*?)\s*$")
_OPS_QUERY_PREFIXES = {
    "",
    "帮我",
    "给我",
    "麻烦",
    "麻烦你",
    "请",
    "查",
    "查一下",
    "查查",
    "看",
    "看下",
    "看一下",
    "看看",
    "帮我查",
    "帮我看",
    "帮我看看",
    "给我查",
    "给我看",
    "我想知道",
    "告诉我",
}
_OPS_QUERY_SUFFIXES = {"", "吗", "嘛", "呢", "吧", "一下", "下", "看看", "怎么样", "如何", "咋样"}


def _compact(content: str) -> str:
    return re.sub(r"[\s，。！？!?、:：；;,.]+", "", (content or "").strip().lower())


def _matches_ops_intent(compact: str, phrases: tuple[str, ...], *, max_len: int = 24) -> bool:
    """Return True only for concise command-like ops questions.

    Fast paths must not steal normal chat. A sentence that merely mentions
    "系统状态" or "帮助" should still go to the LLM unless it looks like a
    deliberate short command.
    """
    if compact in phrases:
        return True
    if len(compact) > max_len:
        return False

    for phrase in phrases:
        if phrase not in compact:
            continue
        before, _, after = compact.partition(phrase)
        if before in _OPS_QUERY_PREFIXES and after in _OPS_QUERY_SUFFIXES:
            return True
    return False


def match_personal_ops_command(content: str) -> str | None:
    """Map short ops questions to deterministic local dashboard commands."""
    compact = _compact(content)
    if not compact:
        return None
    if _GENERIC_URL_RE.search(content or ""):
        return None

    if _matches_ops_intent(compact, ("今天有什么要看", "今天看什么", "今日摘要", "今天摘要", "今日简报", "早报")):
        return "today"
    if _matches_ops_intent(compact, ("文章怎么读", "哪篇值得看", "文章优先级", "阅读消化")):
        return "reading"
    if _matches_ops_intent(compact, ("有没有异常", "异常雷达", "服务哪里不对", "哪里不对劲")):
        return "anomalies"
    if _matches_ops_intent(compact, ("obp花了多少钱", "模型成本", "成本怎么样", "按来源消耗", "花了多少钱")):
        return "cost"
    if _matches_ops_intent(compact, ("睡前总结", "今天收束", "收束一下", "睡前收束")):
        return "night"
    if _matches_ops_intent(compact, ("本周总结", "自省周报", "进化了什么", "本周复盘")):
        return "weekly"
    if _matches_ops_intent(compact, ("决策日志", "最近决策", "记录的决策")):
        return "decision-log"
    if _matches_ops_intent(
        compact,
        ("你能做什么", "你可以做什么", "你有什么功能", "能力列表", "能力菜单", "菜单", "帮助", "help"),
        max_len=16,
    ):
        return "menu"
    if _matches_ops_intent(
        compact,
        ("内存", "内存怎么样", "内存占用", "系统内存", "服务器内存", "内存还好吗"),
        max_len=16,
    ):
        return "system"
    if _matches_ops_intent(
        compact,
        ("系统状态", "服务状态", "服务健康", "服务还活着", "健康检查", "服务器状态", "系统还好吗"),
        max_len=18,
    ):
        return "system"
    if _matches_ops_intent(compact, ("定时任务", "cron", "cron状态", "任务状态", "任务报错", "哪些任务在跑")):
        return "tasks"
    if _matches_ops_intent(compact, ("今天先看什么", "先看什么")) and not any(
        k in compact for k in ("收件箱", "待读", "稍后看")
    ):
        return "decision"
    if _matches_ops_intent(compact, ("今天怎么安排", "有什么建议", "决策建议", "下一步做什么", "现在该干嘛")):
        return "decision"
    if _matches_ops_intent(compact, ("鸭哥", "微信文章", "rss文章", "今天文章", "文章有哪些", "文章更新")):
        return "articles"
    if _matches_ops_intent(
        compact,
        ("lof", "lof看板", "lof机会", "lof套利", "lof怎么样", "qdii", "基金溢价", "溢价机会", "套利机会"),
    ):
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
        rating = re.search(r"(?:收件箱评分|收件箱打分)\s*([A-Za-z0-9_-]{8,})\s*(\d{1,3})", text)
        if rating:
            score = max(0, min(100, int(rating.group(2))))
            return ["rate", rating.group(1), str(score)]
        if any(
            k in compact
            for k in ("待读简报", "收件箱简报", "稍后看简报", "收件箱今天先看什么", "待读先看什么")
        ):
            return ["brief", "--limit", "8"]
        if compact in {"补读", "补读清单", "补读列表", "可补读清单", "明天可补读"}:
            return ["backread-list", "--limit", "8"]
        backread = _BACKREAD_RE.match(text)
        if backread:
            query = backread.group(1).strip(" ，,。:：")
            if query in {"", "清单", "列表"}:
                return ["backread-list", "--limit", "8"]
            return ["backread", query, "--full"]
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
