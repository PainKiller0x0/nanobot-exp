#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

SIGNED_PREFIX = "NBRAW1-SHA256:"
BASE_DIR = "/root/.nanobot/workspace/skills/wechat-rss-sidecar"
CLIENT_PATH = f"{BASE_DIR}/client.py"
CACHE_FILE = f"{BASE_DIR}/wechat_push_cache.json"


def _run_latest(
    days: int,
    limit: int,
    subscription_id: int,
    refresh: bool,
    sample_fetches: int,
    sample_interval: float,
) -> dict | None:
    cmd: list[str] = [
        "python3",
        CLIENT_PATH,
        "latest",
        "--days",
        str(days),
        "--limit",
        str(limit),
        "--sample-fetches",
        str(sample_fetches),
        "--sample-interval",
        str(sample_interval),
    ]
    if subscription_id > 0:
        cmd.extend(["--subscription-id", str(subscription_id)])
    if refresh:
        cmd.append("--refresh")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    try:
        payload = json.loads(out)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _build_ack_marker(subscription_id: int, entry_id: int) -> str:
    # Machine-only marker, stripped by QQ channel before user-visible delivery.
    return f"<!-- NBACK_WECHAT sub:{subscription_id} entry:{entry_id} -->"



def _strip_control_chars(text: str) -> str:
    return re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u200b\u200c\u200d\ufeff]",
        "",
        text or "",
    )


def _signal_text(markdown: str) -> str:
    """Build text-only content for conservative paid-teaser detection."""
    text = _strip_control_chars(markdown)
    text = re.sub(r"<img\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\(https?://[^)]+\)", r" \1 ", text)
    text = re.sub(r"https?://[^\s)]+", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tail_after_body_marker(text: str) -> str | None:
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


def _is_paid_teaser(markdown: str) -> bool:
    """Detect WeChat paid-article diversion snippets without blocking normal articles."""
    text = _signal_text(markdown)
    if not text:
        return False

    tail = _tail_after_body_marker(text)
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
    marker_count = sum(1 for ok in markers if ok)

    # A real article can also mention "以下进入正文", so require a short body
    # plus multiple diversion/paywall-signature phrases.
    return len(text) <= 1800 and marker_count >= 3


def _build_paid_teaser_body(article: dict) -> str:
    title = (article.get("title") or "").strip() or "未命名文章"
    link = (article.get("link") or "").strip()
    source = (article.get("subscription_name") or "").strip()
    published = (article.get("published_at_local") or article.get("published_at") or "").strip()

    meta_lines: list[str] = []
    if source:
        meta_lines.append(f"· 来源 / Source: {source}")
    if published:
        meta_lines.append(f"· 发布时间 / Published: {published}")

    body_parts = [title]
    if meta_lines:
        body_parts.append("\n".join(meta_lines))
    body_parts.append(
        "这篇看起来是付费文章导流 / 试读片段，RSS 没有抓到完整正文。\n\n"
        "我不转发试读原文，避免把导流内容当成完整文章。\n\n"
        "如果你想读全文，可以打开原文购买 / 阅读。"
    )
    if link:
        body_parts.append(f"---\n\n[文章原文]({link})")
    return "\n\n".join(body_parts).strip()


def _build_body(article: dict) -> str:
    raw_markdown = (article.get("article_markdown") or "").strip()
    title = (article.get("title") or "").strip()
    link = (article.get("link") or "").strip()
    source = (article.get("subscription_name") or "").strip()
    published = (article.get("published_at_local") or article.get("published_at") or "").strip()

    if _is_paid_teaser(raw_markdown):
        return _build_paid_teaser_body(article)

    markdown = raw_markdown

    # Remove invisible/control chars that often appear in mirrored payload tails.
    markdown = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u200b\u200c\u200d\ufeff]",
        "",
        markdown,
    )

    # Remove noisy image tails commonly injected by WeChat mirrors.
    markdown = re.sub(r"<img\b[^>]*>", "", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"!\[[^\]]*]\([^)]+\)", "", markdown)

    # Keep markdown hyperlinks in body for better readability and navigation in QQ.
    # Protect markdown links first, then remove truly naked URLs.
    protected_links: list[str] = []

    def _protect_link(m: re.Match[str]) -> str:
        protected_links.append(m.group(0))
        return f"__NBMDLINK_{len(protected_links) - 1}__"

    markdown = re.sub(r"\[[^\]]+]\(https?://[^)]+\)", _protect_link, markdown)
    markdown = re.sub(r"https?://[^\s)]+", "", markdown)
    for i, original in enumerate(protected_links):
        markdown = markdown.replace(f"__NBMDLINK_{i}__", original)

    # Strip residual html tags that leak into payload.
    markdown = re.sub(r"</?[^>]+>", "", markdown)

    # Remove diversion/paywall footer placeholders.
    kept_lines: list[str] = []
    for ln in markdown.splitlines():
        t = ln.strip()
        if re.match(r"^(文章原文|原文|原文链接|原文地址)\s*(\(.+\))?$", t):
            continue
        if t in {
            "文章原文",
            "原文",
            "原文链接",
            "Original",
            "Original:",
            "Open Link",
            "Original: Open Link",
        }:
            continue
        kept_lines.append(ln)
    markdown = "\n".join(kept_lines)

    # Collapse extra blank lines after cleanup.
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()

    # Remove duplicated title line in markdown body if present.
    if title:
        markdown = re.sub(rf"^\s*[\[【]?\s*{re.escape(title)}\s*[\]】]?\s*\n+", "", markdown).strip()

    # Ensure title is visible for diversion/paywalled articles.
    if title:
        head = title
    else:
        head = "未命名文章"

    meta_lines: list[str] = []
    if source:
        meta_lines.append(f"· 来源 / Source: {source}")
    if published:
        meta_lines.append(f"· 发布时间 / Published: {published}")
    meta_block = "\n".join(meta_lines).strip()

    if markdown:
        if meta_block:
            markdown = f"{head}\n\n{meta_block}\n\n{markdown}".strip()
        else:
            markdown = f"{head}\n\n{markdown}".strip()
    elif not markdown and title:
        markdown = head
    elif not markdown:
        markdown = "未命名文章"

    # Remove any existing trailing source-link footer from upstream markdown.
    markdown = re.sub(
        r"\n*(?:---\s*\n+)?\[(?:文章原文|原文|原文链接|Original)\]\(https?://[^)]+\)\s*$",
        "",
        markdown,
        flags=re.IGNORECASE,
    ).strip()

    if link:
        # Keep exactly one markdown hyperlink footer for QQ rendering.
        markdown = f"{markdown}\n\n---\n\n[文章原文]({link})"
    return markdown.strip()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--subscription-id", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sample-fetches", type=int, default=3)
    parser.add_argument("--sample-interval", type=float, default=0.6)
    parser.add_argument("--force", action="store_true")
    args, _ = parser.parse_known_args(sys.argv[1:])

    latest = _run_latest(
        days=max(1, int(args.days or 7)),
        limit=max(1, int(args.limit or 50)),
        subscription_id=max(0, int(args.subscription_id or 0)),
        refresh=bool(args.refresh),
        sample_fetches=max(1, int(args.sample_fetches or 3)),
        sample_interval=float(args.sample_interval or 0.6),
    )
    if not latest:
        return
    if str(latest.get("status") or "") != "ok":
        return

    entry_id = int(latest.get("entry_id") or 0)
    if entry_id <= 0:
        return

    cache = _load_cache()
    cache_key = f"sub:{max(0, int(args.subscription_id or 0))}"
    if (not args.force) and int(cache.get(cache_key, 0) or 0) == entry_id:
        return

    body = _build_body(latest)
    if not body:
        return

    # Do not update cache here.
    # Cache is acknowledged only after QQ send succeeds (handled in qq.py),
    # preventing "cache advanced but message not delivered".
    ack_marker = _build_ack_marker(max(0, int(args.subscription_id or 0)), entry_id)
    body = f"{body}\n\n{ack_marker}".strip()

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    signed_payload = f"{SIGNED_PREFIX}{digest}\n\n{body}"
    sys.stdout.write(signed_payload)


if __name__ == "__main__":
    main()
