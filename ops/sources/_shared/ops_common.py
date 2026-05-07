"""Small shared helpers for Nanobot ops skill scripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SHANGHAI = timezone(timedelta(hours=8))
MISSING = object()


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def short(text: Any, limit: int = 52) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "..."


def parse_dt(value: Any, default_tz=SHANGHAI) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    if " +08:00" in text and "T" not in text:
        candidates.append(text.replace(" +08:00", "+08:00").replace(" ", "T", 1))
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt.astimezone(SHANGHAI)
    return None


def fmt_time(value: Any, pattern: str = "%H:%M", default: str = "-") -> str:
    dt = parse_dt(value)
    return dt.strftime(pattern) if dt else default


HOLIDAY_DATA_DIR = Path("/root/.nanobot/workspace/skills/weather-expert")


def holiday_info(check_date: date | None = None, env_var: str = "OPS_HOLIDAY_FILE") -> dict[str, Any]:
    check_date = check_date or now_shanghai().date()
    paths: list[Path] = []
    if env_path := os.environ.get(env_var, "").strip():
        paths.append(Path(env_path))
    paths.extend([HOLIDAY_DATA_DIR / f"holidays_{check_date.year}.json", HOLIDAY_DATA_DIR / "holidays_cache.json"])

    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        days = data.get("holiday") or data.get("holidays") or {}
        for key in (check_date.strftime("%m-%d"), check_date.isoformat()):
            item = days.get(key)
            if isinstance(item, dict):
                return item
    return {}


def is_cn_workday(check_date: date | None = None, env_var: str = "OPS_HOLIDAY_FILE") -> bool:
    check_date = check_date or now_shanghai().date()
    info = holiday_info(check_date, env_var=env_var)
    if info.get("holiday") is True:
        return False
    if info and (info.get("wage") == 1 or info.get("after") or info.get("before") or "\u8865\u73ed" in str(info.get("name", ""))):
        return True
    return check_date.weekday() < 5


class JsonHttpClient:
    def __init__(self, base_urls: list[str], timeout: float = 8, post_timeout: float | None = None):
        self.base_urls = [base.rstrip("/") for base in base_urls if base]
        self.timeout = timeout
        self.post_timeout = post_timeout or timeout

    def urls(self, path: str) -> list[str]:
        if path.startswith("http"):
            return [path]
        return [base + path for base in self.base_urls]

    def request(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expect_json: bool = True,
        default: Any = MISSING,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json" if expect_json else "*/*"}
        timeout = self.timeout
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            timeout = self.post_timeout

        last_exc: Exception | None = None
        for url in self.urls(path):
            req = Request(url, data=data, method=method, headers=headers)
            try:
                with urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if expect_json else raw
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_exc = exc
                continue
        if default is not MISSING:
            return default
        raise RuntimeError(f"请求失败：{path} - {last_exc}") from last_exc

    def get_json(self, path: str, default: Any = MISSING) -> Any:
        return self.request(path, default=default)

    def post_json(self, path: str, payload: dict[str, Any] | None = None, default: Any = MISSING) -> Any:
        return self.request(path, method="POST", payload=payload or {}, default=default)

    def get_text(self, path: str, default: Any = MISSING) -> str:
        return self.request(path, expect_json=False, default=default)


def extract_json_array(text: Any) -> list[Any]:
    """Parse a JSON array from plain text or a fenced LLM response."""
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    value = json.loads(cleaned)
    return value if isinstance(value, list) else []


def normalize_sentence(value: Any) -> str:
    """Normalize one human-facing sentence while dropping timestamp-like noise."""
    text = str(value or "").strip()
    if not text or re.fullmatch(r"\d{10,}", text):
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.rstrip("。；;，,") + "。" if text and text[-1] not in "。！？!?" else text


def markdown_link_text(text: Any) -> str:
    return str(text or "").replace("[", "【").replace("]", "】").replace("\n", " ")


def post_chat_completion_content(
    url: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 512,
    timeout: float = 24,
    extra: dict[str, Any] | None = None,
) -> str:
    """Call an OpenAI-compatible chat endpoint and return the first message content."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if extra:
        payload.update(extra)
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()


# --- Article push helpers ---
NBRAW_SIGNED_PREFIX = "NBRAW1-SHA256:"
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u200b\u200c\u200d\ufeff]")
SOURCE_LINK_LABEL_RE = re.compile(r"^(文章原文|原文|原文链接|原文地址)\s*(\(.+\))?$", re.IGNORECASE)
TRAILING_SOURCE_LINK_RE = re.compile(
    r"\n*(?:---\s*\n+)?\[(?:文章原文|原文|原文链接|Original)\]\(https?://[^)]+\)\s*$",
    re.IGNORECASE,
)


def load_json_dict(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def strip_control_chars(text: Any) -> str:
    return CONTROL_CHARS_RE.sub("", str(text or ""))


def collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def markdown_signal_text(markdown: str) -> str:
    """Return text-only content for conservative article heuristics."""
    text = strip_control_chars(markdown)
    text = re.sub(r"<img\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\(https?://[^)]+\)", r" \1 ", text)
    text = re.sub(r"https?://[^\s)]+", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def wechat_paid_teaser_tail(text: str) -> str | None:
    match = re.search(r"以下进入正文\s*[:：]?", text)
    if not match:
        return None
    tail = text[match.end() :]
    tail = re.sub(
        r"(文章原文|原文链接|原文地址|原文|Original:?|Open Link)",
        " ",
        tail,
        flags=re.IGNORECASE,
    )
    tail = re.sub(r"[\s:：,，.。;；!！?？·\-—_|\[\]【】（）()]+", "", tail)
    return tail.strip()


def is_wechat_paid_teaser(markdown: str) -> bool:
    """Detect WeChat paid-article diversion snippets without blocking normal articles."""
    text = markdown_signal_text(markdown)
    if not text:
        return False
    tail = wechat_paid_teaser_tail(text)
    if tail is None or len(tail) > 80:
        return False
    markers = [
        "以下进入正文" in text,
        "文中多处有链接" in text,
        "画中画" in text,
        "文中文" in text,
        bool(re.search(r"全文.{0,20}(字|文字).{0,20}共分", text)),
        bool(re.search(r"(本文下面|每一条留言).{0,20}我都会看到", text)),
    ]
    return len(text) <= 1800 and sum(1 for ok in markers if ok) >= 3


def strip_markdown_images(markdown: str) -> str:
    text = re.sub(r"<img\b[^>]*>", "", markdown, flags=re.IGNORECASE)
    return re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)


def remove_naked_urls_preserving_markdown_links(markdown: str) -> str:
    protected_links: list[str] = []

    def protect_link(match: re.Match[str]) -> str:
        protected_links.append(match.group(0))
        return f"__NBMDLINK_{len(protected_links) - 1}__"

    text = re.sub(r"\[[^\]]+]\(https?://[^)]+\)", protect_link, markdown)
    text = re.sub(r"https?://[^\s)]+", "", text)
    for idx, original in enumerate(protected_links):
        text = text.replace(f"__NBMDLINK_{idx}__", original)
    return text


def strip_html_tags(markdown: str) -> str:
    return re.sub(r"</?[^>]+>", "", markdown)


def strip_source_link_lines(markdown: str) -> str:
    skip_values = {
        "文章原文",
        "原文",
        "原文链接",
        "Original",
        "Original:",
        "Open Link",
        "Original: Open Link",
    }
    kept: list[str] = []
    for line in markdown.splitlines():
        text = line.strip()
        if SOURCE_LINK_LABEL_RE.match(text) or text in skip_values:
            continue
        kept.append(line)
    return "\n".join(kept)


def article_meta_lines(source: str = "", published: str = "") -> list[str]:
    lines: list[str] = []
    if source:
        lines.append(f"· 来源 / Source: {source}")
    if published:
        lines.append(f"· 发布时间 / Published: {published}")
    return lines


def strip_duplicate_title(markdown: str, title: str) -> str:
    if not title:
        return markdown.strip()
    return re.sub(rf"^\s*[\[【]?\s*{re.escape(title)}\s*[\]】]?\s*\n+", "", markdown).strip()


def format_paid_teaser_notice(article: dict[str, Any]) -> str:
    title = str(article.get("title") or "").strip() or "未命名文章"
    link = str(article.get("link") or "").strip()
    source = str(article.get("subscription_name") or "").strip()
    published = str(article.get("published_at_local") or article.get("published_at") or "").strip()

    parts = [title]
    meta = article_meta_lines(source, published)
    if meta:
        parts.append("\n".join(meta))
    parts.append(
        "这篇看起来是付费文章导流 / 试读片段，RSS 没有抓到完整正文。\n\n"
        "我不转发试读原文，避免把导流内容当成完整文章。\n\n"
        "如果你想读全文，可以打开原文购买 / 阅读。"
    )
    if link:
        parts.append(f"---\n\n[文章原文]({link})")
    return "\n\n".join(parts).strip()


def clean_article_markdown(markdown: str, title: str = "") -> str:
    text = strip_control_chars(markdown)
    text = strip_markdown_images(text)
    text = remove_naked_urls_preserving_markdown_links(text)
    text = strip_html_tags(text)
    text = strip_source_link_lines(text)
    text = collapse_blank_lines(text)
    return strip_duplicate_title(text, title)


def format_article_push_body(article: dict[str, Any]) -> str:
    raw_markdown = str(article.get("article_markdown") or "").strip()
    if is_wechat_paid_teaser(raw_markdown):
        return format_paid_teaser_notice(article)

    title = str(article.get("title") or "").strip()
    link = str(article.get("link") or "").strip()
    source = str(article.get("subscription_name") or "").strip()
    published = str(article.get("published_at_local") or article.get("published_at") or "").strip()

    head = title or "未命名文章"
    markdown = clean_article_markdown(raw_markdown, title)
    meta = "\n".join(article_meta_lines(source, published)).strip()

    parts = [head]
    if meta:
        parts.append(meta)
    if markdown:
        parts.append(markdown)
    body = "\n\n".join(parts).strip()
    body = TRAILING_SOURCE_LINK_RE.sub("", body).strip()
    if link:
        body = f"{body}\n\n---\n\n[文章原文]({link})"
    return body.strip()


def sign_nbraw_sha256(body: str, prefix: str = NBRAW_SIGNED_PREFIX) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{prefix}{digest}\n\n{body}"
# --- End article push helpers ---

