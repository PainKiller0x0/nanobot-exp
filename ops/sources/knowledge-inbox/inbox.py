#!/usr/bin/env python3
"""Lightweight knowledge inbox and decision packet tool for Nanobot."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

SHANGHAI = timezone(timedelta(hours=8))
DATA_DIR = Path(os.environ.get("NANOBOT_INBOX_DIR", "/root/.nanobot/data/knowledge-inbox"))
ITEMS_FILE = DATA_DIR / "items.json"
MD_DIR = DATA_DIR / "markdown"
MAX_FETCH_BYTES = 2_000_000
TIMEOUT_SECS = 15
RENDER_TIMEOUT_SECS = int(os.environ.get("NANOBOT_INBOX_RENDER_TIMEOUT_SECS", "90"))
BROWSER_OPERATOR_PATH = Path(
    os.environ.get(
        "NANOBOT_INBOX_BROWSER_OPERATOR",
        "/root/.nanobot/workspace/skills/browser-operator/browser_once.py",
    )
)
RENDER_GATEWAY_URL = os.environ.get(
    "NANOBOT_INBOX_RENDER_GATEWAY",
    "http://host.containers.internal:8093/api/internal/render-text",
)
RENDER_TOKEN_FILE = Path(
    os.environ.get(
        "NANOBOT_INBOX_RENDER_TOKEN_FILE",
        "/root/.nanobot/data/knowledge-inbox/render_token",
    )
)
LLM_TIMEOUT_SECS = float(os.environ.get("NANOBOT_INBOX_LLM_TIMEOUT_SECS", "14"))
LLM_SETTINGS_PATH = Path(
    os.environ.get(
        "NANOBOT_INBOX_LLM_SETTINGS",
        "/root/.nanobot/workspace/wechat_rss_service/settings.json",
    )
)
USER_AGENT = "NanobotKnowledgeInbox/1.0 (+local personal assistant)"
WECHAT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
WECHAT_HOSTS = {"mp.weixin.qq.com"}
WECHAT_ENV_MARKERS = ("环境异常", "当前环境异常", "完成验证后即可继续访问", "去验证")

INTEREST_KEYWORDS = {
    "ai", "llm", "agent", "openai", "claude", "gemini", "rust", "python", "nanobot",
    "sidecar", "podman", "k8s", "k3s", "memory", "内存", "服务器", "自动化", "工具",
    "基金", "lof", "qdii", "溢价", "套利", "美股", "市场", "投资", "经济",
    "效率", "认知", "决策", "系统", "长期", "风险", "职业", "人生",
}
AD_KEYWORDS = {
    "广告", "推广", "赞助", "优惠", "折扣", "返现", "扫码", "领取", "课程", "训练营", "社群",
    "付费", "下单", "购买", "咨询", "私域", "带货", "种草", "招商", "加盟", "限时",
}


def now_local() -> datetime:
    return datetime.now(SHANGHAI)


def ensure_dirs() -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)


def load_items() -> dict[str, dict[str, Any]]:
    if not ITEMS_FILE.exists():
        return {}
    try:
        data = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    if isinstance(data, list):
        return {str(v.get("id")): v for v in data if isinstance(v, dict) and v.get("id")}
    return {}


def save_items(items: dict[str, dict[str, Any]]) -> None:
    ensure_dirs()
    tmp = ITEMS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(ITEMS_FILE)


def clean_ws(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"[\t\r\f\v ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def short(text: Any, limit: int = 80) -> str:
    s = clean_ws(str(text or "")).replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def valid_url(value: str) -> str:
    url = (value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("只支持 http/https URL")
    return url


def is_wechat_article_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.netloc.lower() in WECHAT_HOSTS


def is_feishu_docx_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    return parsed.scheme == "https" and (host == "feishu.cn" or host.endswith(".feishu.cn")) and "/docx/" in parsed.path


def looks_like_wechat_env_block(title: str, markdown: str) -> bool:
    text = clean_ws(f"{title}\n{markdown}")
    return "环境异常" in text and any(marker in text for marker in WECHAT_ENV_MARKERS)


def request_headers_for_url(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
    }
    if is_wechat_article_url(url):
        # WeChat blocks the custom bot UA with an environment check page. A normal
        # browser UA returns the article HTML for public links, which we then parse
        # locally into Markdown.
        headers.update({
            "User-Agent": WECHAT_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://mp.weixin.qq.com/",
        })
    return headers


def load_free_longcat_settings() -> dict[str, str] | None:
    if os.environ.get("NANOBOT_INBOX_LLM_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return None
    try:
        raw = json.loads(LLM_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else raw
    if not isinstance(llm, dict) or not llm.get("enabled", False):
        return None
    api_base = str(llm.get("api_base") or "").strip()
    api_key = str(llm.get("api_key") or "").strip()
    model = str(llm.get("model") or "").strip()
    if not api_base or not api_key or not model:
        return None
    if "longcat" not in api_base.lower() or "longcat-flash-lite" not in model.lower():
        return None
    return {"api_base": api_base, "api_key": api_key, "model": model}


def chat_completions_url(api_base: str) -> str:
    url = api_base.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return url


def plain_markdown_for_summary(markdown: str, limit: int = 7000) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`\-]+", " ", text)
    text = clean_ws(text)
    return text[:limit]


def summarize_with_longcat(title: str, markdown: str) -> str:
    settings = load_free_longcat_settings()
    if not settings:
        return ""
    body = plain_markdown_for_summary(markdown)
    if len(body) < 600:
        return ""
    prompt = (
        "请用中文为下面文章做一个给个人知识收件箱看的摘要。\n"
        "要求：3条短 bullet；不要复述链接；不要输出标题；总字数控制在180字以内；"
        "重点说明核心观点、为什么值得看、我可以怎么用。\n\n"
        f"标题：{title}\n\n正文：\n{body}"
    )
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": "你是一个克制、准确的中文阅读摘要助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 260,
        "stream": False,
    }
    req = Request(
        chat_completions_url(settings["api_base"]),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=LLM_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return ""
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return clean_ws(content)[:360]


class MarkdownHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False
        self.link_href: str | None = None
        self.link_text: list[str] = []

    def _append(self, text: str) -> None:
        text = clean_ws(text)
        if not text:
            return
        if self.link_href is not None:
            self.link_text.append(text)
        else:
            if self.parts and not self.parts[-1].endswith(("\n", " ")):
                self.parts.append(" ")
            self.parts.append(text)

    def _newline(self, count: int = 1) -> None:
        if not self.parts:
            return
        joined_tail = "".join(self.parts[-3:])
        if joined_tail.endswith("\n" * count):
            return
        self.parts.append("\n" * count)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {k.lower(): v or "" for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").lower()
            val = attrs_map.get("content") or ""
            if key and val:
                self.meta[key] = clean_ws(val)
            return
        if tag in {"h1", "h2", "h3"}:
            self._newline(2)
            self.parts.append("## " if tag != "h1" else "# ")
        elif tag in {"p", "div", "section", "article", "blockquote"}:
            self._newline(2)
        elif tag == "li":
            self._newline(1)
            self.parts.append("- ")
        elif tag == "br":
            self._newline(1)
        elif tag == "a":
            href = attrs_map.get("href", "").strip()
            self.link_href = urljoin(self.base_url, href) if href else ""
            self.link_text = []
        elif tag == "img":
            src = attrs_map.get("src", "").strip()
            alt = clean_ws(attrs_map.get("alt", "图片")) or "图片"
            if src:
                self._append(f"![{alt}]({urljoin(self.base_url, src)})")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
            return
        if tag == "a" and self.link_href is not None:
            text = clean_ws(" ".join(self.link_text))
            href = self.link_href
            self.link_href = None
            self.link_text = []
            if text and href:
                self._append(f"[{text}]({href})")
            elif text:
                self._append(text)
            return
        if tag in {"p", "div", "section", "article", "blockquote", "li", "h1", "h2", "h3"}:
            self._newline(2)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        self._append(data)

    def result(self) -> tuple[str, str, str]:
        title = clean_ws(" ".join(self.title_parts))
        title = self.meta.get("og:title") or self.meta.get("twitter:title") or title
        desc = self.meta.get("description") or self.meta.get("og:description") or self.meta.get("twitter:description") or ""
        markdown = clean_ws("".join(self.parts))
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return title, clean_ws(desc), markdown.strip()


@dataclass
class FetchedPage:
    url: str
    final_url: str
    title: str
    description: str
    markdown: str
    content_type: str
    source_status: str = "ok"
    source_message: str = ""


def rendered_text_to_markdown(text: str, source_url: str) -> tuple[str, str]:
    ui_noise = {
        "docs",
        "feishu docs",
        "modified today",
        "log in or sign up",
        "comments",
        "help center",
        "keyboard shortcuts",
    }
    lines: list[str] = []
    seen_streak = 0
    previous = ""
    for raw in (text or "").replace("\u200b", "").splitlines():
        line = clean_ws(raw)
        if not line:
            continue
        low = line.lower()
        if low in ui_noise or re.fullmatch(r"comments\s*\(\d+\)", low) or low.startswith("last updated:"):
            continue
        if line == previous:
            seen_streak += 1
            if seen_streak > 1:
                continue
        else:
            seen_streak = 0
        previous = line
        lines.append(line)

    title = next((line for line in lines if not line.startswith("发布时间：")), "")
    body_lines = [line for line in lines if line != title]
    markdown = "\n\n".join(body_lines).strip()
    if source_url and f"]({source_url})" not in markdown:
        markdown = f"{markdown}\n\n[打开原文]({source_url})".strip()
    return title, markdown


def fetch_with_rendered_browser(url: str) -> FetchedPage | None:
    if os.environ.get("NANOBOT_INBOX_RENDER_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return None
    if not BROWSER_OPERATOR_PATH.exists():
        return None

    payload: dict[str, Any] = {}
    rendered_text = ""
    attempts = 1 if is_feishu_docx_url(url) else 2
    for attempt in range(attempts):
        if is_feishu_docx_url(url):
            cmd = [
                sys.executable,
                str(BROWSER_OPERATOR_PATH),
                "feishu-text",
                url,
                "--limit",
                "60000",
                "--wait-ms",
                "8000",
                "--timeout",
                str(RENDER_TIMEOUT_SECS),
                "--output-limit",
                "70000",
            ]
        else:
            cmd = [
                sys.executable,
                str(BROWSER_OPERATOR_PATH),
                "deep-text",
                url,
                "--limit",
                "40000",
                "--scrolls",
                str(24 + attempt * 8),
                "--delay-ms",
                "450",
                "--wait-ms",
                str(8000 + attempt * 4000),
                "--timeout",
                str(RENDER_TIMEOUT_SECS),
                "--output-limit",
                "50000",
            ]
        try:
            completed = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=RENDER_TIMEOUT_SECS + 15,
                check=False,
            )
            payload = json.loads(completed.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
        if completed.returncode != 0 or not payload.get("ok"):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rendered_text = result.get("stdout") if isinstance(result, dict) else ""
        rendered_text = clean_ws(str(rendered_text or ""))
        if len(rendered_text) >= 80:
            break
    if len(rendered_text) < 80:
        return None

    title, markdown = rendered_text_to_markdown(rendered_text, url)
    if not title:
        title = short(markdown.splitlines()[0] if markdown else url, 90)
    source_message = "普通抓取遇到跳转循环，已用一次性浏览器渲染抓取正文。"
    return FetchedPage(
        url=url,
        final_url=str(payload.get("url") or url),
        title=title,
        description="",
        markdown=markdown,
        content_type="text/plain; rendered=browser",
        source_status="rendered",
        source_message=source_message,
    )


def read_render_token() -> str:
    try:
        return RENDER_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def fetch_with_render_gateway(url: str) -> FetchedPage | None:
    if os.environ.get("NANOBOT_INBOX_RENDER_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return None
    token = read_render_token()
    if not token or not RENDER_GATEWAY_URL:
        return None
    payload = {
        "url": url,
        "token": token,
        "limit": 40_000,
    }
    req = Request(
        RENDER_GATEWAY_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=RENDER_TIMEOUT_SECS + 25) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    rendered_text = clean_ws(str(data.get("text") or ""))
    if len(rendered_text) < 80:
        return None
    title, markdown = rendered_text_to_markdown(rendered_text, url)
    if not title:
        title = short(markdown.splitlines()[0] if markdown else url, 90)
    source_message = "普通抓取遇到跳转循环，已通过宿主机浏览器渲染服务抓取正文。"
    return FetchedPage(
        url=url,
        final_url=str(data.get("url") or url),
        title=title,
        description="",
        markdown=markdown,
        content_type="text/plain; rendered=gateway",
        source_status="rendered",
        source_message=source_message,
    )


def redirect_loop_fallback(url: str, exc: HTTPError) -> FetchedPage | None:
    if exc.code not in {301, 302, 303, 307, 308}:
        return None
    message = str(exc)
    if "infinite loop" not in message.lower():
        return None
    rendered = fetch_with_rendered_browser(url)
    if rendered is not None:
        return rendered
    rendered = fetch_with_render_gateway(url)
    if rendered is not None:
        return rendered
    host = urlparse(url).netloc or "目标网页"
    title = f"需要登录或权限的网页：{host}"
    description = "目标网页反复跳转到登录/验证页，已保存链接，正文需要手动打开。"
    markdown = "\n".join([
        f"> {description}",
        "",
        f"- 原始链接：{url}",
        "- 抓取状态：302 redirect loop",
        f"- 说明：{short(message, 220)}",
        "",
        f"[打开原文]({url})",
    ])
    return FetchedPage(
        url=url,
        final_url=url,
        title=title,
        description=description,
        markdown=markdown,
        content_type="text/plain; status=redirect-loop",
        source_status="redirect_loop",
        source_message=description,
    )


def fetch_url(url: str) -> FetchedPage:
    url = valid_url(url)
    req = Request(url, headers=request_headers_for_url(url))
    try:
        with urlopen(req, timeout=TIMEOUT_SECS) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_FETCH_BYTES + 1)
            final_url = resp.geturl()
    except HTTPError as exc:
        fallback = redirect_loop_fallback(url, exc)
        if fallback is not None:
            return fallback
        raise RuntimeError(f"抓取失败：{exc}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"抓取失败：{exc}") from exc
    if len(raw) > MAX_FETCH_BYTES:
        raw = raw[:MAX_FETCH_BYTES]
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    if match:
        charset = match.group(1)
    text = raw.decode(charset, errors="replace")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        parser = MarkdownHTMLParser(final_url)
        parser.feed(text)
        title, desc, markdown = parser.result()
    else:
        title, desc, markdown = "", "", clean_ws(text)
    if not title:
        title = short(markdown.splitlines()[0] if markdown else final_url, 90)
    return FetchedPage(url=url, final_url=final_url, title=title, description=desc, markdown=markdown, content_type=content_type)


def item_id_for_url(url: str) -> str:
    parsed = urlparse(url)
    host = re.sub(r"[^a-zA-Z0-9]+", "-", parsed.netloc.lower()).strip("-")[:18]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{now_local().strftime('%Y%m%d')}-{host}-{digest}"


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+.-]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    counts: dict[str, int] = {}
    stop = {"https", "http", "com", "www", "the", "and", "for", "with", "this", "that", "from", "一个", "我们", "他们", "这个", "不是", "什么", "如果", "因为", "所以", "但是", "然后", "可以", "没有"}
    for token in tokens:
        if token in stop or len(token) > 24:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    return [k for k, _ in ranked[:limit]]


def extract_links(markdown: str, limit: int = 8) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for text, url in re.findall(r"\[([^\]]{1,80})\]\((https?://[^)\s]+)\)", markdown):
        links.append({"text": clean_ws(text), "url": url})
        if len(links) >= limit:
            break
    return links


def first_sentences(text: str, limit: int = 220) -> str:
    body = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", text)
    body = re.sub(r"[#>*_`\-]+", " ", body)
    body = clean_ws(body).replace("\n", " ")
    if not body:
        return ""
    parts = re.split(r"(?<=[。！？.!?])\s+", body)
    out = ""
    for part in parts:
        if not part:
            continue
        if len(out) + len(part) > limit:
            break
        out = (out + " " + part).strip()
    return short(out or body, limit)



PROFILE_VERSION = "taste-v0.2"
HIGH_TRUST_SOURCES = ("记忆承载", "记忆承载3", "碧树西风", "鸭哥 AI 要闻", "鸭哥AI要闻")
MEDIUM_TRUST_HOSTS = {"github.com", "linux.do"}
MEDIUM_TRUST_SOURCES = ("Share - Computing Life", "Computing Life", "技术博客")
COGNITIVE_KEYWORDS = {"认知", "模型", "系统", "底层", "框架", "决策", "人生", "职业", "长期", "选择", "努力", "反馈", "风险"}
HORIZON_KEYWORDS = {"趋势", "未来", "视野", "周期", "变化", "机会", "行业", "创业", "产品", "可能性"}
MONEY_CONCRETE_KEYWORDS = {"lof", "qdii", "溢价", "套利", "估值", "限额", "成交额", "折价", "费率", "基金", "股票", "债券"}
AI_ANCHOR_KEYWORDS = {"ai", "llm", "agent", "openai", "deepseek", "claude", "gemini", "minimax", "longcat"}
AI_DETAIL_KEYWORDS = {"价格", "api", "发布", "产品", "创业", "模型", "能力", "上下文", "tool", "function calling"}
AI_PRIORITY_KEYWORDS = AI_ANCHOR_KEYWORDS | AI_DETAIL_KEYWORDS
AI_GOSSIP_KEYWORDS = {"八卦", "绯闻", "饭圈", "综艺", "撕逼", "热搜", "瓜"}
PAID_COST_KEYWORDS = {"付费", "购买"}


@dataclass
class ScoreResult:
    score: int
    label: str
    reasons: list[str]
    base_score: int
    base_label: str
    base_reasons: list[str]
    preference_adjustment: int
    preference_reasons: list[str]
    preference_samples: int
    profile_version: str = PROFILE_VERSION


def decision_label_for_score(score: int) -> str:
    if score >= 75:
        return "值得优先看"
    if score >= 58:
        return "可以稍后看"
    if score >= 42:
        return "只需扫一眼"
    return "大概率可跳过"


def hit_any(text: str, keywords: set[str] | tuple[str, ...]) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    ascii_tokens = set(re.findall(r"[a-z][a-z0-9_+.-]{1,}", low))
    for keyword in keywords:
        k = keyword.lower()
        if re.fullmatch(r"[a-z0-9_+.-]+", k):
            if k in ascii_tokens:
                hits.append(keyword)
        elif k in low:
            hits.append(keyword)
    return sorted(set(hits))


def ai_priority_hits(text: str) -> list[str]:
    """AI only counts when an AI anchor and a concrete product/model signal co-exist."""
    anchors = hit_any(text, AI_ANCHOR_KEYWORDS)
    details = hit_any(text, AI_DETAIL_KEYWORDS)
    provider_hits = [x for x in anchors if x.lower() not in {"ai", "llm", "agent"}]
    if anchors and (details or provider_hits):
        return sorted(set(anchors + details))
    return []


def same_url(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left.split("#", 1)[0].rstrip("/") == right.split("#", 1)[0].rstrip("/")


def source_tier(title: str, description: str, markdown: str, url: str = "") -> tuple[str, str]:
    text = f"{title}\n{description}\n{markdown[:2500]}"
    for source in HIGH_TRUST_SOURCES:
        if source in text:
            return "high", source
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in MEDIUM_TRUST_HOSTS or any(host.endswith("." + item) for item in MEDIUM_TRUST_HOSTS):
        return "medium", host
    for source in MEDIUM_TRUST_SOURCES:
        if source.lower() in text.lower():
            return "medium", source
    return "normal", host or "未知来源"


def preference_features(title: str, description: str, markdown: str, url: str = "", note: str = "") -> set[str]:
    text = f"{title}\n{description}\n{markdown[:5000]}\n{note}".lower()
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    tier, source = source_tier(title, description, f"{markdown}\n{note}", url)
    features = {f"source-tier:{tier}"}
    if host:
        features.add(f"host:{host}")
    if source and source != "未知来源":
        features.add(f"source:{source.lower()}")
    if hit_any(text, COGNITIVE_KEYWORDS):
        features.add("topic:cognitive-model")
    if hit_any(text, HORIZON_KEYWORDS):
        features.add("topic:horizon")
    if len(hit_any(text, MONEY_CONCRETE_KEYWORDS)) >= 2:
        features.add("topic:money-concrete")
    if ai_priority_hits(text):
        features.add("topic:ai-product")
    if hit_any(text, AI_GOSSIP_KEYWORDS):
        features.add("topic:ai-gossip")
    if len(clean_ws(markdown)) >= 2500:
        features.add("content:longform")
        if tier == "high":
            features.add("content:trusted-longform")
    if hit_any(text, PAID_COST_KEYWORDS):
        features.add("cost:paid")
    return features


def feature_weight(feature: str) -> float:
    if feature.startswith("source:") or feature.startswith("host:"):
        return 2.0
    if feature.startswith("topic:"):
        return 1.5
    if feature == "content:trusted-longform":
        return 1.3
    if feature.startswith("content:"):
        return 0.8
    if feature.startswith("cost:"):
        return 0.5
    return 0.4


def score_learning_adjustment(
    title: str,
    description: str,
    markdown: str,
    url: str,
    items: dict[str, dict[str, Any]] | None,
) -> tuple[int, list[str], int]:
    if not items:
        return 0, [], 0
    current = preference_features(title, description, markdown, url)
    weighted_sum = 0.0
    weight_sum = 0.0
    evidence: list[str] = []
    samples = 0
    for item in items.values():
        if item.get("manual_score") is None:
            continue
        item_url = str(item.get("final_url") or item.get("url") or "")
        if same_url(url, item_url):
            continue
        try:
            manual = int(item.get("manual_score"))
            base = int(item.get("auto_base_score", item.get("auto_decision_score", item.get("decision_score", manual))))
        except (TypeError, ValueError):
            continue
        delta = manual - base
        if abs(delta) < 6:
            continue
        sample_features = preference_features(
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            "",
            str(item.get("final_url") or item.get("url") or ""),
            str(item.get("manual_score_note") or "") + "\n" + "\n".join(str(x) for x in item.get("keywords") or []),
        )
        matched = current & sample_features
        if not matched:
            continue
        similarity = sum(feature_weight(feature) for feature in matched)
        if similarity < 1.5:
            continue
        samples += 1
        influence = min(1.0, similarity / 4.0)
        weighted_sum += delta * influence
        weight_sum += influence
        evidence.extend(sorted(matched))
    if samples == 0 or weight_sum <= 0:
        return 0, [], 0

    avg_delta = weighted_sum / weight_sum
    confidence = 0.35 if samples == 1 else 0.65 if samples < 5 else 1.0
    limit = 8 if samples == 1 else 14 if samples < 5 else 22
    adjustment = int(round(max(-limit, min(limit, avg_delta * confidence))))
    if adjustment == 0:
        return 0, [], samples

    readable: list[str] = []
    labels = {
        "topic:cognitive-model": "认知模型类内容",
        "topic:horizon": "打开视野/趋势类内容",
        "topic:money-concrete": "具体投资机会/风险内容",
        "topic:ai-product": "AI 产品/模型/API 内容",
        "content:longform": "长文",
        "content:trusted-longform": "可信来源长文",
        "cost:paid": "付费/阅读成本内容",
    }
    for feature in sorted(set(evidence)):
        if feature in labels:
            readable.append(labels[feature])
        elif feature.startswith("source:"):
            readable.append("相似来源")
        elif feature.startswith("host:"):
            readable.append("相似站点")
    readable = list(dict.fromkeys(readable))[:4]
    sign = "+" if adjustment > 0 else ""
    reason = f"个人偏好学习 {sign}{adjustment}：基于 {samples} 条手动评分样本"
    if readable:
        reason += "，匹配 " + "、".join(readable)
    return adjustment, [reason], samples


def score_page(
    title: str,
    description: str,
    markdown: str,
    url: str = "",
    items: dict[str, dict[str, Any]] | None = None,
) -> ScoreResult:
    text = f"{title}\n{description}\n{markdown[:5000]}".lower()

    score = 45
    reasons: list[str] = []
    content_len = len(clean_ws(markdown))
    tier, source = source_tier(title, description, markdown, url)
    if tier == "high":
        score += 18
        reasons.append(f"高信任来源：{source}")
    elif tier == "medium":
        score += 6
        reasons.append(f"中信任来源：{source}")

    cognitive_hits = hit_any(text, COGNITIVE_KEYWORDS)
    horizon_hits = hit_any(text, HORIZON_KEYWORDS)
    money_hits = hit_any(text, MONEY_CONCRETE_KEYWORDS)
    ai_hits = ai_priority_hits(f"{title}\n{description}\n{markdown[:1500]}")
    gossip_hits = hit_any(text, AI_GOSSIP_KEYWORDS)
    matched_interest = sorted({kw for kw in INTEREST_KEYWORDS if hit_any(text, {kw})})
    matched_ads = sorted({kw for kw in AD_KEYWORDS if hit_any(text, {kw})})

    if cognitive_hits:
        score += 12
        reasons.append("贴合你的核心偏好：认知模型/底层框架")
    if horizon_hits:
        score += 8
        reasons.append("有打开视野或趋势判断价值")
    if len(money_hits) >= 2:
        score += 10
        reasons.append("投资相关且包含具体机会/数据/风险信号")
    elif any(kw in text for kw in ("投资", "市场", "经济")):
        score += 2
        reasons.append("泛投资/市场内容，仅小幅加权")
    if ai_hits and not gossip_hits:
        score += 8
        reasons.append("AI 模型/价格/API/产品趋势相关")
    if gossip_hits:
        score -= 10
        reasons.append("包含 AI 八卦/热搜类信号，降权")

    # Interest keywords are a secondary signal now; avoid letting raw keyword count dominate taste.
    if matched_interest:
        add = min(10, 2 + len(matched_interest))
        score += add
        reasons.append("命中长期关注词：" + "、".join(matched_interest[:6]))

    if content_len >= 2500:
        if tier == "high":
            score += 10
            reasons.append("可信来源长文，长度视为信息密度信号")
        elif cognitive_hits or horizon_hits:
            score += 5
            reasons.append("长文且有认知/趋势主题，小幅加分")
        else:
            reasons.append("长文阅读成本较高，不因字数直接加分")
    elif content_len < 500:
        score -= 12
        reasons.append("正文偏短，可能只是入口页或摘要")

    link_count = len(re.findall(r"\]\(https?://", markdown))
    if link_count >= 5 and (ai_hits or len(money_hits) >= 2 or tier != "normal"):
        score += 4
        reasons.append("包含资料链接，适合后续整理")

    paid_only = bool(matched_ads) and set(matched_ads).issubset(PAID_COST_KEYWORDS)
    if paid_only and content_len >= 2500:
        reasons.append("付费/购买只作为阅读成本提示，不按广告扣分")
    elif matched_ads:
        score -= min(30, 10 + len(matched_ads) * 4)
        reasons.append("疑似营销/广告信号：" + "、".join(matched_ads[:6]))

    if re.search(r"404|not found|access denied|forbidden", title.lower() + markdown[:300].lower()):
        score -= 30
        reasons.append("页面可能不可读或权限受限")

    base_score = max(0, min(94, score))
    base_label = decision_label_for_score(base_score)
    if not reasons:
        reasons.append("没有明显强信号，建议按标题兴趣决定")

    preference_adjustment, preference_reasons, preference_samples = score_learning_adjustment(
        title, description, markdown, url, items
    )
    final_score = max(0, min(96, base_score + preference_adjustment))
    final_label = decision_label_for_score(final_score)
    final_reasons = list(reasons)
    final_reasons.extend(preference_reasons)
    return ScoreResult(
        score=final_score,
        label=final_label,
        reasons=final_reasons,
        base_score=base_score,
        base_label=base_label,
        base_reasons=reasons,
        preference_adjustment=preference_adjustment,
        preference_reasons=preference_reasons,
        preference_samples=preference_samples,
    )

def write_markdown(item: dict[str, Any], markdown: str) -> Path:
    path = MD_DIR / f"{item['id']}.md"
    header = [
        f"# {item.get('title') or 'Untitled'}",
        "",
        f"- URL: {item.get('url')}",
        f"- Final URL: {item.get('final_url')}",
        f"- Captured: {item.get('captured_at')}",
        f"- Decision: {item.get('decision_label')} ({item.get('decision_score')}/100)",
        "",
        "---",
        "",
    ]
    path.write_text("\n".join(header) + markdown.strip() + "\n", encoding="utf-8")
    return path


def capture(url: str, note: str = "", tags: list[str] | None = None, force: bool = False) -> dict[str, Any]:
    ensure_dirs()
    page = fetch_url(url)
    wechat_blocked = is_wechat_article_url(page.final_url or page.url) and looks_like_wechat_env_block(page.title, page.markdown)
    if wechat_blocked:
        raise RuntimeError("微信文章解析失败：微信返回环境验证页，未保存空文章")
    items = load_items()
    existing = next((v for v in items.values() if v.get("url") == page.url or v.get("final_url") == page.final_url), None)
    item_id = existing.get("id") if existing and not force else item_id_for_url(page.final_url or page.url)
    score_result = score_page(
        page.title,
        page.description,
        page.markdown,
        page.final_url or page.url,
        items,
    )
    auto_score = score_result.score
    auto_label = score_result.label
    auto_reasons = list(score_result.reasons)
    score, label, reasons = auto_score, auto_label, list(auto_reasons)
    manual_score = existing.get("manual_score") if existing else None
    if manual_score is not None:
        try:
            score = max(0, min(100, int(manual_score)))
            label = decision_label_for_score(score)
            reasons = [f"手动评分覆盖：{score}/100"] + auto_reasons[:2]
        except (TypeError, ValueError):
            manual_score = None
    keywords = extract_keywords(f"{page.title}\n{page.description}\n{page.markdown}")
    extractive_summary = first_sentences(page.description or page.markdown)
    llm_summary = summarize_with_longcat(page.title, page.markdown)
    item = {
        "id": item_id,
        "url": page.url,
        "final_url": page.final_url,
        "host": urlparse(page.final_url or page.url).netloc,
        "title": page.title,
        "description": page.description,
        "summary": llm_summary or extractive_summary,
        "summary_source": "longcat_free" if llm_summary else "extractive",
        "extractive_summary": extractive_summary,
        "captured_at": now_local().isoformat(timespec="seconds"),
        "content_type": page.content_type,
        "content_chars": len(page.markdown),
        "profile_version": score_result.profile_version,
        "auto_base_score": score_result.base_score,
        "auto_base_label": score_result.base_label,
        "auto_base_reasons": score_result.base_reasons,
        "preference_adjustment": score_result.preference_adjustment,
        "preference_reasons": score_result.preference_reasons,
        "preference_samples": score_result.preference_samples,
        "auto_decision_score": auto_score,
        "auto_decision_label": auto_label,
        "auto_decision_reasons": auto_reasons,
        "decision_score": score,
        "decision_label": label,
        "decision_reasons": reasons,
        "keywords": keywords,
        "links": extract_links(page.markdown),
        "note": note,
        "tags": tags or [],
        "source_status": page.source_status,
        "source_message": page.source_message,
    }
    if existing and manual_score is not None:
        item["manual_score"] = score
        item["manual_score_note"] = existing.get("manual_score_note", "")
        item["manual_score_at"] = existing.get("manual_score_at", "")
    md_path = write_markdown(item, page.markdown)
    item["markdown_path"] = str(md_path)
    items[item_id] = item
    save_items(items)
    return item


def sorted_items(limit: int = 10) -> list[dict[str, Any]]:
    items = list(load_items().values())
    items.sort(key=lambda x: str(x.get("captured_at") or ""), reverse=True)
    return items[:limit]


def find_item(ref: str) -> dict[str, Any] | None:
    items = load_items()
    if ref in items:
        return items[ref]
    for item in items.values():
        if str(item.get("id", "")).startswith(ref):
            return item
    return None



RSS_BASE_URL_CANDIDATES = [
    os.environ.get("WECHAT_RSS_BASE_URL", "").strip(),
    "http://127.0.0.1:8091",
    "http://wechat-rss-sidecar:8091",
]
BACKREAD_WEB_BASE = os.environ.get("NANOBOT_BACKREAD_WEB_BASE", "http://150.158.121.88:8093")


def rss_request(path: str, *, expect_json: bool = True, timeout: int = 12) -> Any:
    last_error: Exception | None = None
    for base_url in RSS_BASE_URL_CANDIDATES:
        if not base_url:
            continue
        req = Request(base_url.rstrip("/") + path, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read(MAX_FETCH_BYTES).decode("utf-8", errors="replace")
                return json.loads(body) if expect_json else body
        except Exception as exc:  # noqa: BLE001 - try the next sidecar address.
            last_error = exc
    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error
    raise RuntimeError("RSS sidecar base URL not configured")


def rss_timeline(days: int = 7, limit: int = 80) -> list[dict[str, Any]]:
    params = urlencode({"days": max(1, min(days, 30)), "limit": max(1, min(limit, 200))})
    payload = rss_request(f"/api/timeline?{params}")
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    rows = [x for x in items if isinstance(x, dict)]
    rows.sort(
        key=lambda x: (
            str(x.get("published_at") or ""),
            str(x.get("published_at_local") or ""),
            str(x.get("inserted_at") or ""),
            int(x.get("id") or 0),
        ),
        reverse=True,
    )
    return rows


def rss_article(entry_id: int) -> dict[str, Any]:
    raw = rss_request(f"/api/articles/{entry_id}")
    item = raw.get("item") if isinstance(raw, dict) else {}
    if not isinstance(item, dict):
        item = {}
    try:
        markdown = str(rss_request(f"/api/articles/{entry_id}/markdown", expect_json=False)).strip()
    except Exception:
        markdown = ""
    if not markdown:
        markdown = str(
            item.get("article_markdown")
            or item.get("content_markdown")
            or item.get("summary")
            or ""
        ).strip()
    return {"item": item, "markdown": markdown}


def compact_match_text(text: Any) -> str:
    return re.sub(r"[\s，。！？!?、:：；;,.\-_/\\|\[\]()（）【】《》<>\"'`]+", "", str(text or "").lower())


def match_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+.-]{1,}|\d+|[\u4e00-\u9fff]{2,}", text.lower())
    stop = {"这个", "那个", "一下", "一篇", "文章", "补读", "补看", "帮我", "看看", "清单", "列表"}
    return [t for t in tokens if t not in stop]


def clip_multiline(text: Any, limit: int = 1200) -> str:
    value = clean_ws(str(text or ""))
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 20)].rstrip() + "\n...（已截断）"


def backread_candidates(days: int = 7, limit: int = 80) -> tuple[list[dict[str, Any]], str | None]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    rss_error: str | None = None
    try:
        for item in rss_timeline(days=days, limit=limit):
            entry_id = str(item.get("id") or "").strip()
            title = clean_ws(str(item.get("title") or ""))
            if not entry_id or not title:
                continue
            url = str(item.get("link") or item.get("url") or "").strip()
            dedupe = f"rss:{entry_id}" if entry_id else compact_match_text(title + url)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            candidates.append({
                "kind": "rss",
                "id": entry_id,
                "ref": f"rss:{entry_id}",
                "title": title,
                "source": item.get("subscription_name") or item.get("source") or "RSS",
                "time": item.get("published_at_local") or item.get("published_at") or item.get("inserted_at") or "",
                "url": url,
                "summary": item.get("summary") or item.get("description") or "",
            })
    except Exception as exc:  # noqa: BLE001 - inbox fallback should still work.
        rss_error = str(exc)

    for item in sorted_items(limit):
        title = clean_ws(str(item.get("title") or item.get("url") or ""))
        if not title:
            continue
        item_id = str(item.get("id") or "")
        url = str(item.get("final_url") or item.get("url") or "")
        dedupe = compact_match_text(url or title)
        if dedupe and dedupe in seen:
            continue
        if dedupe:
            seen.add(dedupe)
        candidates.append({
            "kind": "inbox",
            "id": item_id,
            "ref": item_id,
            "title": title,
            "source": item.get("host") or "知识收件箱",
            "time": item.get("captured_at") or "",
            "url": url,
            "summary": item.get("summary") or item.get("description") or "",
            "item": item,
        })
    return candidates[: max(1, min(limit, 200))], rss_error


def score_backread_candidate(query: str, candidate: dict[str, Any]) -> int:
    raw = (query or "").strip()
    if not raw:
        return 0
    q = compact_match_text(raw)
    ident = compact_match_text(candidate.get("id"))
    ref = compact_match_text(candidate.get("ref"))
    title = compact_match_text(candidate.get("title"))
    source = compact_match_text(candidate.get("source"))
    url = compact_match_text(candidate.get("url"))
    hay = f"{title}{source}{url}{ident}{ref}"
    score = 0
    if q and q in {ident, ref}:
        score += 240
    elif q and (ident.startswith(q) or ref.startswith(q)):
        score += 180
    if q and q in title:
        score += 130 + min(40, len(q))
    elif q and q in hay:
        score += 80
    for token in match_tokens(raw):
        t = compact_match_text(token)
        if not t:
            continue
        if t in title:
            score += 35
        elif t in source:
            score += 22
        elif t in hay:
            score += 12
    return score


def resolve_backread_target(ref: str, *, days: int = 7, limit: int = 80) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    candidates, warning = backread_candidates(days=days, limit=limit)
    query = (ref or "").strip()
    if not query:
        return None, candidates, warning
    if query.isdigit():
        idx = int(query)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1], candidates, warning
    exact = compact_match_text(query)
    for candidate in candidates:
        if exact in {compact_match_text(candidate.get("ref")), compact_match_text(candidate.get("id"))}:
            return candidate, candidates, warning
    ranked = sorted(
        ((score_backread_candidate(query, candidate), candidate) for candidate in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if ranked and ranked[0][0] > 0:
        return ranked[0][1], candidates, warning
    return None, candidates, warning


def render_backread_list(days: int = 7, limit: int = 8) -> str:
    candidates, warning = backread_candidates(days=days, limit=max(limit * 3, 30))
    shown = candidates[: max(1, min(limit, 20))]
    if not shown:
        msg = "📭 最近没有找到可补读内容。"
        if warning:
            msg += f"\nRSS 读取提示：{short(warning, 120)}"
        return msg
    lines = [f"📚 补读清单（最近 {days} 天）"]
    for idx, item in enumerate(shown, 1):
        source = clean_ws(str(item.get("source") or item.get("kind") or "-"))
        title = short(item.get("title"), 42)
        time = short(item.get("time"), 32)
        lines.append(f"{idx}. [{source}] {title}")
        lines.append(f"   {time} · {item.get('ref')}")
    if warning:
        lines.append(f"RSS 提示：{short(warning, 120)}")
    lines.append("用法：补读 1 / 补读 标题关键词")
    return "\n".join(lines)


def render_backread(ref: str, *, days: int = 7, limit: int = 80, chars: int = 1400) -> str:
    target, candidates, warning = resolve_backread_target(ref, days=days, limit=limit)
    if not target:
        lines = [f"没找到可补读内容：{ref}"]
        if warning:
            lines.append(f"RSS 读取提示：{short(warning, 120)}")
        if candidates:
            lines.append("可以先发“补读清单”，或换一个标题关键词。")
        return "\n".join(lines)

    kind = target.get("kind")
    title = clean_ws(str(target.get("title") or "未命名"))
    source = clean_ws(str(target.get("source") or kind or "-"))
    time = clean_ws(str(target.get("time") or ""))
    url = clean_ws(str(target.get("url") or ""))
    body = ""
    detail_url = ""
    if kind == "rss":
        entry_id = int(target.get("id") or 0)
        try:
            article = rss_article(entry_id)
            item = article.get("item") or {}
            if isinstance(item, dict):
                title = clean_ws(str(item.get("title") or title))
                source = clean_ws(str(item.get("subscription_name") or source))
                time = clean_ws(str(item.get("published_at_local") or item.get("published_at") or time))
                url = clean_ws(str(item.get("link") or url))
            body = str(article.get("markdown") or "").strip()
        except Exception as exc:  # noqa: BLE001 - still return timeline metadata.
            body = clean_ws(str(target.get("summary") or ""))
            detail_url = f"RSS 正文读取失败：{short(exc, 120)}"
        detail_url = detail_url or f"{BACKREAD_WEB_BASE.rstrip('/')}/rss/"
    else:
        item = target.get("item") if isinstance(target.get("item"), dict) else find_item(str(target.get("id") or ""))
        if item:
            path = Path(str(item.get("markdown_path") or ""))
            if path.exists():
                body = path.read_text(encoding="utf-8", errors="replace")
            else:
                body = clean_ws(str(item.get("summary") or item.get("description") or ""))
        detail_url = f"{BACKREAD_WEB_BASE.rstrip('/')}/inbox"

    plain_body = plain_markdown_for_summary(body or target.get("summary") or "", limit=4000)
    plain_body = re.sub(r"^[\s.。…·]+", "", plain_body)
    summary = first_sentences(plain_body, limit=260)
    preview = clip_multiline(body or target.get("summary") or "", chars)
    lines = [f"📖 补读：{title}", f"来源：{source}"]
    if time:
        lines.append(f"时间：{time}")
    lines.append(f"编号：{target.get('ref')}")
    if url:
        lines.append(f"原文：[打开链接]({url})")
    if detail_url:
        lines.append(f"看板：{detail_url}")
    if summary:
        lines.extend(["", "摘要：", summary])
    if preview:
        lines.extend(["", "预览：", preview])
    return "\n".join(lines)

def resolve_item_key(ref: str, items: dict[str, dict[str, Any]]) -> str | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref in items:
        return ref
    exact = [key for key, item in items.items() if str(item.get("id") or "") == ref]
    if len(exact) == 1:
        return exact[0]
    matches = sorted({
        key
        for key, item in items.items()
        if key.startswith(ref) or str(item.get("id") or "").startswith(ref)
    })
    if len(matches) == 1:
        return matches[0]
    return None


def safe_unlink_markdown(item: dict[str, Any]) -> bool:
    raw = str(item.get("markdown_path") or "").strip()
    if not raw:
        return False
    path = Path(raw)
    if not path.is_absolute():
        path = DATA_DIR / path
    try:
        resolved = path.resolve(strict=True)
        data_root = DATA_DIR.resolve(strict=True)
    except OSError:
        return False
    if not resolved.is_file() or data_root not in (resolved, *resolved.parents):
        return False
    try:
        resolved.unlink()
        return True
    except OSError:
        return False


def delete_item(ref: str, keep_markdown: bool = False) -> tuple[dict[str, Any], bool]:
    items = load_items()
    key = resolve_item_key(ref, items)
    if key is None:
        raise ValueError(f"没找到唯一匹配的收件箱条目：{ref}")
    item = items.pop(key)
    save_items(items)
    markdown_deleted = False if keep_markdown else safe_unlink_markdown(item)
    return item, markdown_deleted


def rate_item(ref: str, score: int, note: str = "") -> dict[str, Any]:
    score = max(0, min(100, int(score)))
    items = load_items()
    key = resolve_item_key(ref, items)
    if not key:
        raise RuntimeError(f"没找到这个收件箱条目：{ref}")
    item = items[key]
    if "auto_decision_score" not in item:
        item["auto_decision_score"] = item.get("decision_score")
        item["auto_decision_label"] = item.get("decision_label")
        item["auto_decision_reasons"] = item.get("decision_reasons") or []
    if "auto_base_score" not in item:
        item["auto_base_score"] = item.get("auto_decision_score", item.get("decision_score"))
        item["auto_base_label"] = item.get("auto_decision_label", item.get("decision_label"))
        item["auto_base_reasons"] = item.get("auto_decision_reasons") or item.get("decision_reasons") or []
    if "profile_version" not in item:
        item["profile_version"] = PROFILE_VERSION
    item["manual_score"] = score
    item["manual_score_note"] = clean_ws(note)
    item["manual_score_at"] = now_local().isoformat(timespec="seconds")
    item["decision_score"] = score
    item["decision_label"] = decision_label_for_score(score)
    reasons = [f"手动评分覆盖：{score}/100"]
    if note:
        reasons.append(f"备注：{clean_ws(note)}")
    auto_reasons = item.get("auto_decision_reasons") or []
    reasons.extend(str(reason) for reason in auto_reasons[:2])
    item["decision_reasons"] = reasons
    save_items(items)
    path = Path(str(item.get("markdown_path") or ""))
    if path.exists():
        body = path.read_text(encoding="utf-8", errors="replace")
        body = re.sub(
            r"- Decision: .+?\n",
            f"- Decision: {item.get('decision_label')} ({item.get('decision_score')}/100)\n",
            body,
            count=1,
        )
        path.write_text(body, encoding="utf-8")
    return item


def render_item(item: dict[str, Any], verbose: bool = False) -> str:
    lines = [
        f"📥 已入收件箱：{item.get('title') or '未命名'}",
        f"ID：{item.get('id')}",
        f"判断：{item.get('decision_label')}（{item.get('decision_score')}/100）",
    ]
    if item.get("auto_base_score") is not None:
        try:
            pref = int(item.get("preference_adjustment") or 0)
            lines.append(f"拆分：基础 {int(item.get('auto_base_score'))}/100；偏好修正 {pref:+d}")
        except (TypeError, ValueError):
            pass
    if item.get("manual_score") is not None:
        manual_note = clean_ws(str(item.get("manual_score_note") or ""))
        suffix = f"；{manual_note}" if manual_note else ""
        lines.append(f"人工评分：{item.get('manual_score')}/100{suffix}")
    if item.get("summary"):
        summary = str(item.get("summary") or "").strip()
        if "\n" in summary:
            lines.append("摘要：\n" + summary)
        else:
            lines.append(f"摘要：{summary}")
    reasons = item.get("decision_reasons") or []
    if reasons:
        lines.append("理由：" + "；".join(str(x) for x in reasons[:3]))
    return "\n".join(lines)


def render_list(limit: int) -> str:
    items = sorted_items(limit)
    if not items:
        return "📭 收件箱还是空的。发一个链接并说“收一下”就能存起来。"
    lines = [f"📚 最近收件箱（{len(items)} 条）"]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. {short(item.get('title'), 36)}")
        lines.append(f"   {item.get('decision_label')} {item.get('decision_score')}/100 · {item.get('id')}")
    return "\n".join(lines)


def render_read(ref: str, chars: int = 900) -> str:
    item = find_item(ref)
    if not item:
        return f"没找到这个收件箱条目：{ref}"
    path = Path(str(item.get("markdown_path") or ""))
    body = ""
    if path.exists():
        body = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join([
        render_item(item, verbose=True),
        "",
        "预览：",
        short(body, chars),
    ])


def render_delete(ref: str, keep_markdown: bool = False) -> str:
    item, markdown_deleted = delete_item(ref, keep_markdown=keep_markdown)
    lines = [
        f"🗑️ 已删除收件箱条目：{item.get('title') or '未命名'}",
        f"ID：{item.get('id')}",
    ]
    if keep_markdown:
        lines.append("Markdown：已保留")
    else:
        lines.append("Markdown：" + ("已删除" if markdown_deleted else "未找到或已跳过"))
    return "\n".join(lines)


def render_rate(ref: str, score: int, note: str = "") -> str:
    item = rate_item(ref, score, note=note)
    auto_score = item.get("auto_decision_score")
    suffix = f"；自动评分原为 {auto_score}/100" if auto_score is not None else ""
    return "\n".join([
        f"✅ 已更新评分：{item.get('title') or '未命名'}",
        f"ID：{item.get('id')}",
        f"当前判断：{item.get('decision_label')}（{item.get('decision_score')}/100）{suffix}",
    ])


def render_decide(target: str, question: str = "") -> str:
    if re.match(r"^https?://", target or ""):
        item = capture(target)
    else:
        item = find_item(target)
        if not item:
            return f"没找到这个条目：{target}"
    lines = [
        f"🧠 决策包：{item.get('title') or '未命名'}",
        f"结论：{item.get('decision_label')}（{item.get('decision_score')}/100）",
    ]
    if question:
        lines.append(f"你的问题：{question}")
    if item.get("summary"):
        lines.append(f"核心内容：{item.get('summary')}")
    reasons = item.get("decision_reasons") or []
    if reasons:
        lines.append("依据：")
        lines.extend(f"- {r}" for r in reasons[:4])
    score = int(item.get("decision_score") or 0)
    if score >= 75:
        action = "今天优先读，读完可以让 nanobot 帮你提炼行动项。"
    elif score >= 58:
        action = "先放待读，碎片时间看；不需要立刻打断当前事情。"
    elif score >= 42:
        action = "扫标题和小结即可，除非它正好回答你手头的问题。"
    else:
        action = "可以先跳过，除非你就是想验证它为什么低价值。"
    lines.append(f"建议动作：{action}")
    links = item.get("links") or []
    if links:
        lines.append("原文链接保留：")
        for link in links[:3]:
            lines.append(f"- [{short(link.get('text'), 28)}]({link.get('url')})")
    return "\n".join(lines)


def render_brief(limit: int = 8) -> str:
    items = sorted_items(limit)
    if not items:
        return "📭 暂无待读材料。"
    priority = [x for x in items if int(x.get("decision_score") or 0) >= 75]
    maybe = [x for x in items if 58 <= int(x.get("decision_score") or 0) < 75]
    lines = ["🧺 待读决策简报", f"最近 {len(items)} 条；优先 {len(priority)} 条，稍后 {len(maybe)} 条"]
    if priority:
        lines.append("先看：")
        for item in priority[:3]:
            lines.append(f"- {short(item.get('title'), 38)}（{item.get('decision_score')}/100）")
    if maybe:
        lines.append("稍后：")
        for item in maybe[:3]:
            lines.append(f"- {short(item.get('title'), 38)}（{item.get('decision_score')}/100）")
    low = [x for x in items if int(x.get("decision_score") or 0) < 58]
    if low:
        lines.append(f"可跳过/扫一眼：{len(low)} 条")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nanobot knowledge inbox")
    sub = parser.add_subparsers(dest="command", required=True)

    p_capture = sub.add_parser("capture")
    p_capture.add_argument("url")
    p_capture.add_argument("--note", default="")
    p_capture.add_argument("--tag", action="append", default=[])
    p_capture.add_argument("--force", action="store_true")

    p_decide = sub.add_parser("decide")
    p_decide.add_argument("target")
    p_decide.add_argument("--question", default="")

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=8)

    p_read = sub.add_parser("read")
    p_read.add_argument("ref")
    p_read.add_argument("--chars", type=int, default=900)

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("ref")
    p_delete.add_argument("--keep-markdown", action="store_true")

    p_rate = sub.add_parser("rate")
    p_rate.add_argument("ref")
    p_rate.add_argument("score", type=int)
    p_rate.add_argument("--note", default="")

    p_brief = sub.add_parser("brief")
    p_brief.add_argument("--limit", type=int, default=8)

    p_backread_list = sub.add_parser("backread-list")
    p_backread_list.add_argument("--days", type=int, default=7)
    p_backread_list.add_argument("--limit", type=int, default=8)

    p_backread = sub.add_parser("backread")
    p_backread.add_argument("ref")
    p_backread.add_argument("--days", type=int, default=7)
    p_backread.add_argument("--limit", type=int, default=80)
    p_backread.add_argument("--chars", type=int, default=1400)

    args = parser.parse_args()
    try:
        if args.command == "capture":
            item = capture(args.url, note=args.note, tags=args.tag, force=args.force)
            print(render_item(item))
        elif args.command == "decide":
            print(render_decide(args.target, question=args.question))
        elif args.command == "list":
            print(render_list(max(1, min(args.limit, 30))))
        elif args.command == "read":
            print(render_read(args.ref, chars=max(200, min(args.chars, 5000))))
        elif args.command == "delete":
            print(render_delete(args.ref, keep_markdown=args.keep_markdown))
        elif args.command == "rate":
            print(render_rate(args.ref, args.score, note=args.note))
        elif args.command == "brief":
            print(render_brief(max(1, min(args.limit, 30))))
        elif args.command == "backread-list":
            print(render_backread_list(days=max(1, min(args.days, 30)), limit=max(1, min(args.limit, 20))))
        elif args.command == "backread":
            print(render_backread(
                args.ref,
                days=max(1, min(args.days, 30)),
                limit=max(10, min(args.limit, 200)),
                chars=max(400, min(args.chars, 5000)),
            ))
    except Exception as exc:  # noqa: BLE001 - QQ should receive a compact failure.
        print(f"知识收件箱失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
