"""QQ media and attachment IO helpers for nanobot-exp."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp

from nanobot.security.network import validate_url_target

QQ_FILE_TYPE_IMAGE = 1
QQ_FILE_TYPE_FILE = 4

_IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".ico",
    ".svg",
}

_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]（）【】\u4e00-\u9fff]+", re.UNICODE)

AttachmentDownloader = Callable[..., Awaitable[str | None]]


def sanitize_filename(name: str) -> str:
    """Sanitize filename to avoid traversal and problematic chars."""
    name = (name or "").strip()
    name = Path(name).name
    name = _SAFE_NAME_RE.sub("_", name).strip("._ ")
    return name


def is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in _IMAGE_EXTS


def parse_qq_timestamp(ts: str | None) -> datetime | None:
    """Parse QQ API timestamp string to UTC datetime."""
    if not ts:
        return None
    try:
        value = int(ts)
        if value > 10**10:
            value //= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def guess_send_file_type(filename: str) -> int:
    """Conservative send type: images -> 1, else -> 4."""
    ext = Path(filename).suffix.lower()
    mime, _ = mimetypes.guess_type(filename)
    if ext in _IMAGE_EXTS or (mime and mime.startswith("image/")):
        return QQ_FILE_TYPE_IMAGE
    return QQ_FILE_TYPE_FILE


def is_remote_media_ref(media_ref: str) -> bool:
    media_ref = (media_ref or "").strip()
    return media_ref.startswith("http://") or media_ref.startswith("https://")


def build_download_target(
    media_root: Path,
    url: str,
    filename_hint: str = "",
    *,
    now_ms: int | None = None,
) -> Path:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    safe = sanitize_filename(filename_hint)
    ext = Path(urlparse(url).path).suffix
    if not ext:
        ext = Path(filename_hint).suffix
    if not ext:
        ext = ".bin"

    if safe:
        if not Path(safe).suffix:
            safe = safe + ext
        filename = safe
    else:
        filename = f"qq_file_{now_ms}{ext}"

    target = media_root / filename
    if target.exists():
        target = media_root / f"{target.stem}_{now_ms}{target.suffix}"
    return target


async def read_media_bytes(
    session: aiohttp.ClientSession | None,
    media_ref: str,
    *,
    logger: Any | None = None,
) -> tuple[bytes | None, str | None]:
    """Read bytes from http(s) or local file path; return (data, filename)."""
    media_ref = (media_ref or "").strip()
    if not media_ref:
        return None, None

    if not is_remote_media_ref(media_ref):
        try:
            if media_ref.startswith("file://"):
                parsed = urlparse(media_ref)
                raw = parsed.path or parsed.netloc
                local_path = Path(unquote(raw))
            else:
                local_path = Path(os.path.expanduser(media_ref))

            if not local_path.is_file():
                if logger is not None:
                    logger.warning("QQ outbound media file not found: {}", str(local_path))
                return None, None

            data = await asyncio.to_thread(local_path.read_bytes)
            return data, local_path.name
        except Exception as e:
            if logger is not None:
                logger.warning("QQ outbound media read error ref={} err={}", media_ref, e)
            return None, None

    ok, err = validate_url_target(media_ref)
    if not ok:
        if logger is not None:
            logger.warning("QQ outbound media URL validation failed url={} err={}", media_ref, err)
        return None, None
    if session is None:
        if logger is not None:
            logger.warning("QQ outbound media HTTP session is unavailable url={}", media_ref)
        return None, None

    try:
        async with session.get(media_ref, allow_redirects=True) as resp:
            if resp.status >= 400:
                if logger is not None:
                    logger.warning(
                        "QQ outbound media download failed status={} url={}",
                        resp.status,
                        media_ref,
                    )
                return None, None
            data = await resp.read()
            if not data:
                return None, None
            filename = os.path.basename(urlparse(media_ref).path) or "file.bin"
            return data, filename
    except Exception as e:
        if logger is not None:
            logger.warning("QQ outbound media download error url={} err={}", media_ref, e)
        return None, None


async def handle_attachments(
    attachments: list[Any],
    download_func: AttachmentDownloader,
    *,
    logger: Any | None = None,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Extract, download, and format inbound attachments for agent consumption."""
    media_paths: list[str] = []
    recv_lines: list[str] = []
    att_meta: list[dict[str, Any]] = []

    if not attachments:
        return media_paths, recv_lines, att_meta

    for att in attachments:
        url = getattr(att, "url", "")
        filename = getattr(att, "filename", "")
        ctype = getattr(att, "content_type", "")

        if logger is not None:
            logger.info("Downloading file from QQ: {}", filename or url)
        local_path = await download_func(url, filename_hint=filename)

        att_meta.append(
            {
                "url": url,
                "filename": filename,
                "content_type": ctype,
                "saved_path": local_path,
            }
        )

        if local_path:
            media_paths.append(local_path)
            shown_name = filename or os.path.basename(local_path)
            recv_lines.append(f"- {shown_name}\n  saved: {local_path}")
        else:
            shown_name = filename or url
            recv_lines.append(f"- {shown_name}\n  saved: [download failed]")

    return media_paths, recv_lines, att_meta


async def download_to_media_dir_chunked(
    session: aiohttp.ClientSession,
    media_root: Path,
    url: str,
    *,
    filename_hint: str = "",
    max_bytes: int,
    logger: Any | None = None,
) -> str | None:
    """Download an inbound attachment through QQ-Sidecar-RS."""
    target = build_download_target(media_root, url, filename_hint)
    try:
        async with session.post(
            "http://172.17.0.1:8092/download",
            json={
                "url": url,
                "target_path": str(target),
                "max_bytes": max_bytes,
            },
        ) as resp:
            data = await resp.json()
            if data.get("success"):
                if logger is not None:
                    logger.info("QQ file saved via sidecar: {}", str(target))
                return str(target)
            if logger is not None:
                logger.error("QQ sidecar download error: {}", data.get("error"))
            return None
    except Exception as e:
        if logger is not None:
            logger.error("QQ sidecar download request error: {}", e)
        return None


__all__ = [
    "QQ_FILE_TYPE_FILE",
    "QQ_FILE_TYPE_IMAGE",
    "build_download_target",
    "download_to_media_dir_chunked",
    "guess_send_file_type",
    "handle_attachments",
    "is_image_name",
    "is_remote_media_ref",
    "parse_qq_timestamp",
    "read_media_bytes",
    "sanitize_filename",
]
