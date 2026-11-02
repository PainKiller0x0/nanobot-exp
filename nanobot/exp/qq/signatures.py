"""QQ signed-payload helpers.

The QQ channel delegates anti-tamper checks and delivery ACK parsing here so the
upstream adapter can stay focused on botpy send/receive mechanics.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from typing import Any

SIGNED_PAYLOAD_PREFIX = "NBRAW1-SHA256:"
SILENT_MARKER = "(NOOUTPUTKEEP_SILENT)"
SILENT_MARKER_ALT = "(NO_OUTPUT_KEEP_SILENT)"
SILENT_MARKER_RE = re.compile(r"[（(]\s*NO_?OUTPUT_?KEEP_?SILENT\s*[)）]", re.IGNORECASE)
YAGE_ARTICLE_RE = re.compile(r"^\s*\[鸭哥 AI 手记\]", re.MULTILINE)
YAGE_URL_IN_LINK_RE = re.compile(r"\((https?://yage-ai\.kit\.com/posts/[^)\s]+)\)")
YAGE_URL_BARE_RE = re.compile(r"https?://yage-ai\.kit\.com/posts/[^\s)\]]+")
YAGE_DATE_IN_URL_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
WECHAT_ACK_MARKER_RE = re.compile(r"<!--\s*NBACK_WECHAT\s+sub:(\d+)\s+entry:(\d+)\s*-->")


def strip_silent_marker(text: str) -> str:
    cleaned = text or ""
    cleaned = SILENT_MARKER_RE.sub("", cleaned)
    cleaned = cleaned.replace(SILENT_MARKER, "").replace(SILENT_MARKER_ALT, "")
    return cleaned.strip()


def requires_signed_payload(content: str) -> bool:
    """Detect high-risk article payloads that must be signed raw output."""
    text = (content or "").strip()
    if not text:
        return False
    if YAGE_ARTICLE_RE.search(text):
        return True
    if "yage-ai.kit.com/posts/" in text:
        return True
    return False


def verify_and_unwrap_signed_payload(
    content: str,
    *,
    verify_url: str = "http://172.17.0.1:8092/verify",
    timeout_sec: float = 15,
    logger: Any | None = None,
) -> str | None:
    """Verify signed payload through QQ-Sidecar-RS and return its body."""
    try:
        req = urllib.request.Request(
            verify_url,
            data=json.dumps({"content": content}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return data.get("body")
            return None
    except Exception as e:
        if logger is not None:
            logger.error("QQ sidecar verify error: {}", e)
        return None


def extract_yage_source_url(body: str) -> str | None:
    """Extract yage source URL from signed payload body."""
    text = (body or "").strip()
    if not text:
        return None
    m = YAGE_URL_IN_LINK_RE.search(text)
    if m:
        return m.group(1).strip()
    m = YAGE_URL_BARE_RE.search(text)
    if m:
        return m.group(0).strip()
    return None


def extract_date_from_url(url: str) -> datetime | None:
    m = YAGE_DATE_IN_URL_RE.search(url or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d")
    except Exception:
        return None


def should_ack_yage_url(previous_url: str, candidate_url: str) -> bool:
    """Only advance cache when candidate is same/newer, never roll back."""
    prev = (previous_url or "").strip()
    cand = (candidate_url or "").strip()
    if not cand:
        return False
    if not prev:
        return True
    if prev == cand:
        return False
    prev_dt = extract_date_from_url(prev)
    cand_dt = extract_date_from_url(cand)
    if prev_dt and cand_dt:
        return cand_dt >= prev_dt
    return False


def extract_wechat_ack_marker(body: str) -> tuple[str, tuple[int, int] | None]:
    """Strip internal wechat ACK marker from body and return ack tuple."""
    text = body or ""
    m = WECHAT_ACK_MARKER_RE.search(text)
    if not m:
        return text, None
    sub_id = int(m.group(1))
    entry_id = int(m.group(2))
    cleaned = WECHAT_ACK_MARKER_RE.sub("", text).strip()
    return cleaned, (sub_id, entry_id)


def extract_wechat_subscription_id(content: str) -> int | None:
    """Extract wechat subscription id from internal ACK marker."""
    text = content or ""
    m = WECHAT_ACK_MARKER_RE.search(text)
    if not m:
        return None
    try:
        sub_id = int(m.group(1))
        return sub_id if sub_id > 0 else None
    except Exception:
        return None


def extract_signed_digest(content: str) -> str | None:
    text = (content or "").strip()
    m = re.match(r"^NBRAW1-SHA256:([0-9a-fA-F]{64})", text)
    if not m:
        return None
    return m.group(1).lower()
