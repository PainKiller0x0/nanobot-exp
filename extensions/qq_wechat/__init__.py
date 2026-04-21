"""Optional QQ WeChat-sidecar plugin.

Enable with:
  NANOBOT_QQ_WECHAT_MODULE=extensions.qq_wechat
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage

_CN_WECHAT = "\u5fae\u4fe1"
_CN_OFFICIAL = "\u516c\u4f17\u53f7"
_CN_ARTICLE = "\u6587\u7ae0"
_CN_POST = "\u63a8\u6587"
_CN_IN_ARTICLE = "\u6587\u4e2d"

_WECHAT_QUESTION_HINTS = (
    "\u8bb2\u4e86\u4ec0\u4e48",
    "\u8bf4\u4e86\u4ec0\u4e48",
    "\u5199\u4e86\u4ec0\u4e48",
    "\u6838\u5fc3\u89c2\u70b9",
    "\u4e3b\u8981\u5185\u5bb9",
    "\u603b\u7ed3",
    "\u91cd\u70b9",
    "\u95ee",
    "\u95ee\u9898",
)
_WECHAT_TITLE_HINTS = (
    "\u6700\u65b0",
    "\u6807\u9898",
    "\u6700\u8fd1",
    "\u4eca\u5929",
    "\u8fd9\u5468",
    "\u6700\u8fd1\u4e00\u7bc7",
)

_WECHAT_CACHE_FILE = "/root/.nanobot/workspace/skills/wechat-rss-sidecar/wechat_push_cache.json"
_WECHAT_ACK_MARKER_RE = re.compile(r"<!--\s*NBACK_WECHAT\s+sub:(\d+)\s+entry:(\d+)\s*-->")


def _extract_wechat_question(content: str) -> str | None:
    text = (content or "").strip()
    lower = text.lower()
    if not text:
        return None
    if _CN_WECHAT not in text and _CN_OFFICIAL not in text and "wechat" not in lower and "weixin" not in lower:
        return None
    if (
        _CN_ARTICLE not in text
        and _CN_POST not in text
        and _CN_IN_ARTICLE not in text
        and "article" not in lower
        and "post" not in lower
    ):
        return None
    if any(k in text for k in _WECHAT_QUESTION_HINTS):
        parts = re.split(r"[:\uFF1A]", text, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        return text
    if "?" in text or "\uFF1F" in text:
        return text
    return None


def _is_wechat_title_query(content: str) -> bool:
    text = (content or "").strip()
    lower = text.lower()
    if not text:
        return False
    if _CN_WECHAT not in text and _CN_OFFICIAL not in text and "wechat" not in lower and "weixin" not in lower:
        return False
    return any(hint in text for hint in _WECHAT_TITLE_HINTS) or "latest title" in lower or "latest article" in lower


async def _run_sidecar_json(args: list[str], timeout_sec: float = 30.0) -> dict[str, Any] | None:
    cmd = [
        "python3",
        "/root/.nanobot/workspace/skills/wechat-rss-sidecar/client.py",
        *args,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        logger.warning("qq wechat guard timeout: {}", " ".join(cmd))
        return None
    except Exception as e:
        logger.warning("qq wechat guard exec failed: {} err={}", " ".join(cmd), e)
        return None

    out = (stdout or b"").decode("utf-8", errors="ignore").strip()
    err = (stderr or b"").decode("utf-8", errors="ignore").strip()
    if proc.returncode != 0:
        logger.warning(
            "qq wechat guard non-zero: rc={} cmd={} err={}",
            proc.returncode,
            " ".join(cmd),
            err,
        )
        return None
    if not out:
        logger.warning("qq wechat guard empty output: {}", " ".join(cmd))
        return None
    try:
        return json.loads(out)
    except Exception:
        logger.warning("qq wechat guard invalid json: cmd={} out_head={}", " ".join(cmd), out[:200])
        return None


async def try_handle_wechat_grounded(
    *, channel: Any, user_id: str, chat_id: str, content: str, message_id: str
) -> bool:
    if not channel.is_allowed(user_id):
        return False

    title_query = _is_wechat_title_query(content)
    question = _extract_wechat_question(content)
    if not title_query and not question:
        return False

    if title_query and not question:
        latest = await _run_sidecar_json(["latest", "--days", "7", "--limit", "50"])
        if not latest or latest.get("status") in {"empty", "error"}:
            reply = "\u5df2\u6838\u9a8c\u539f\u6587\uff1a\u672a\u627e\u5230\u53ef\u7528\u6587\u7ae0\uff08NOT_FOUND_IN_ARTICLE\uff09"
        else:
            reply = (
                f"\u6700\u65b0\u6587\u7ae0\uff1a{latest.get('title') or ''}\n"
                f"entry_id: {latest.get('entry_id') or 0}\n"
                f"published_at: {latest.get('published_at') or ''}\n"
                f"link: {latest.get('link') or ''}"
            )
        await channel.bus.publish_outbound(
            OutboundMessage(
                channel="qq",
                chat_id=chat_id,
                content=reply,
                metadata={"message_id": message_id},
            )
        )
        return True

    ask = await _run_sidecar_json(
        ["ask", "--question", question or content, "--days", "7", "--limit", "50"]
    )
    if not ask:
        await channel.bus.publish_outbound(
            OutboundMessage(
                channel="qq",
                chat_id=chat_id,
                content="\u5df2\u6838\u9a8c\u539f\u6587\uff1a\u672a\u547d\u4e2d\u95ee\u9898\u7b54\u6848\uff08NOT_FOUND_IN_ARTICLE\uff09",
                metadata={"message_id": message_id},
            )
        )
        return True

    status = str(ask.get("status") or "").lower()
    if status != "ok":
        reply = (
            "\u5df2\u6838\u9a8c\u539f\u6587\uff1a\u672a\u547d\u4e2d\u95ee\u9898\u7b54\u6848\uff08NOT_FOUND_IN_ARTICLE\uff09\n"
            f"entry_id: {ask.get('entry_id') or 0}\n"
            f"published_at: {ask.get('published_at') or ''}\n"
            f"link: {ask.get('link') or ''}"
        )
    else:
        answer = str(ask.get("answer") or "").strip()
        reply = (
            f"entry_id: {ask.get('entry_id') or 0}\n"
            f"published_at: {ask.get('published_at') or ''}\n"
            f"link: {ask.get('link') or ''}\n\n"
            f"{answer or 'NOT_FOUND_IN_ARTICLE'}"
        )
    await channel.bus.publish_outbound(
        OutboundMessage(
            channel="qq",
            chat_id=chat_id,
            content=reply,
            metadata={"message_id": message_id},
        )
    )
    return True


def extract_wechat_ack_marker(*, channel: Any, body: str) -> tuple[str, tuple[int, int] | None]:
    text = body or ""
    m = _WECHAT_ACK_MARKER_RE.search(text)
    if not m:
        return text, None
    sub_id = int(m.group(1))
    entry_id = int(m.group(2))
    cleaned = _WECHAT_ACK_MARKER_RE.sub("", text).strip()
    return cleaned, (sub_id, entry_id)


async def ack_wechat_delivery(*, channel: Any, ack: tuple[int, int] | None, chat_id: str) -> bool:
    if not ack:
        return True
    sub_id, entry_id = ack
    if sub_id < 0 or entry_id <= 0:
        return True
    cache_key = f"sub:{sub_id}"

    def _write_cache() -> tuple[bool, int]:
        cache: dict[str, Any] = {}
        if os.path.exists(_WECHAT_CACHE_FILE):
            try:
                with open(_WECHAT_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        cache = data
            except Exception:
                cache = {}
        prev = int(cache.get(cache_key, 0) or 0)
        if entry_id <= prev:
            return False, prev
        cache[cache_key] = entry_id
        tmp = f"{_WECHAT_CACHE_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, _WECHAT_CACHE_FILE)
        return True, prev

    try:
        updated, prev = await asyncio.to_thread(_write_cache)
        if updated:
            logger.info(
                "QQ wechat delivery ack cache updated chat_id={} key={} prev={} new={}",
                chat_id,
                cache_key,
                prev,
                entry_id,
            )
    except Exception as e:
        logger.warning("QQ wechat delivery ack failed chat_id={} err={}", chat_id, e)
    return True
