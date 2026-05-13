"""Inbound QQ message helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.exp.qq import media_io


def resolve_chat_context(
    data: Any,
    *,
    is_group: bool,
    chat_type_cache: dict[str, str],
    logger: Any | None = None,
) -> tuple[str, str] | None:
    """Resolve (chat_id, user_id) and update the chat-type cache."""
    author = getattr(data, "author", None)
    if is_group:
        chat_id = getattr(data, "group_openid", "")
        user_id = getattr(author, "member_openid", "unknown")
        if not chat_id:
            if logger is not None:
                logger.warning(
                    "QQ group message missing group_openid message_id={}",
                    getattr(data, "id", "unknown"),
                )
            return None
        chat_type_cache[chat_id] = "group"
        return chat_id, user_id

    chat_id = str(getattr(author, "id", None) or getattr(author, "user_openid", "unknown"))
    chat_type_cache[chat_id] = "c2c"
    return chat_id, chat_id


def compose_attachment_content(
    content: str,
    *,
    media_paths: list[str],
    recv_lines: list[str],
) -> str:
    """Append actionable saved-file paths to inbound content."""
    if not recv_lines:
        return content
    tag = "[Image]" if any(media_io.is_image_name(Path(p).name) for p in media_paths) else "[File]"
    file_block = "Received files:\n" + "\n".join(recv_lines)
    return f"{content}\n\n{file_block}".strip() if content else f"{tag}\n{file_block}"


__all__ = [
    "compose_attachment_content",
    "resolve_chat_context",
]
