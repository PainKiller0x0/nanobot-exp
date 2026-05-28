"""QQ streaming policy helpers for nanobot-exp.

The upstream QQ channel should only need to ask small policy questions here:
"can this reply stream?", "when should a delta flush?", and "how should markdown be chunked?".
"""

from __future__ import annotations

from typing import Any


def supports_streaming(config: Any) -> bool:
    """Return whether QQ markdown streaming is enabled for this config."""
    return bool(
        getattr(config, "stream_enabled", False)
        and getattr(config, "msg_format", "plain") == "markdown"
    )


def should_stream_text(
    config: Any,
    *,
    msg_id: str | None,
    is_signed_payload: bool,
    content: str,
) -> bool:
    """Decide if a normal outbound text reply should use QQ stream frames."""
    if not supports_streaming(config):
        return False
    if is_signed_payload:
        return False
    if getattr(config, "stream_requires_msg_id", True) and not msg_id:
        return False
    text_len = len((content or "").strip())
    min_chars = max(1, int(getattr(config, "stream_min_chars", 120) or 120))
    max_chars = max(min_chars, int(getattr(config, "stream_max_chars", 5000) or 5000))
    return min_chars <= text_len <= max_chars


def delta_flush_policy(config: Any, *, first_frame_sent: bool) -> tuple[int, float]:
    """Return `(chars_threshold, seconds_threshold)` for delta streaming flushes."""
    threshold_key = "stream_delta_flush_chars" if first_frame_sent else "stream_first_flush_chars"
    # QQ stream creation is unreliable with one-character first frames, but
    # waiting for a full sentence defeats the point of streaming. Two visible
    # CJK chars are enough to create a real, non-placeholder first frame.
    threshold_floor = 20 if first_frame_sent else 2
    threshold_default = 120 if first_frame_sent else 2
    threshold = max(
        threshold_floor,
        int(getattr(config, threshold_key, threshold_default) or threshold_default),
    )
    interval = float(getattr(config, "stream_delta_flush_interval_sec", 0.35) or 0.0)
    return threshold, max(0.0, interval)


def split_stream_chunks(config: Any, text: str) -> list[str]:
    """Split markdown for QQ append frames while preserving line endings."""
    max_chars = max(20, int(getattr(config, "stream_chunk_chars", 180) or 180))
    chunks: list[str] = []
    current = ""
    for line in (text or "").splitlines(keepends=True):
        if len(line) > max_chars:
            if current:
                chunks.append(current if current.endswith("\n") else f"{current}\n")
                current = ""
            for i in range(0, len(line), max_chars):
                piece = line[i : i + max_chars]
                chunks.append(piece if piece.endswith("\n") else f"{piece}\n")
            continue
        if len(current) + len(line) <= max_chars:
            current += line
        else:
            if current:
                chunks.append(current if current.endswith("\n") else f"{current}\n")
            current = line
    if current:
        chunks.append(current if current.endswith("\n") else f"{current}\n")
    return chunks or [text if text.endswith("\n") else f"{text}\n"]


def split_stream_frame_chunks(config: Any, text: str) -> list[str]:
    """Split a QQ stream frame without changing the text.

    ``split_stream_chunks`` intentionally adds newlines for standalone stream
    sends. Delta streaming needs exact-prefix accounting so fallback messages
    do not duplicate already-visible text.
    """
    max_chars = max(20, int(getattr(config, "stream_chunk_chars", 180) or 180))
    if not text:
        return [""]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:max_chars])
            line = line[max_chars:]
        if len(current) + len(line) <= max_chars:
            current += line
        else:
            if current:
                chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return chunks or [text]
