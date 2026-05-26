"""Lightweight per-turn trace context for outbound model calls."""

from __future__ import annotations

import string
import uuid
from contextvars import ContextVar, Token

_TRACE_ID: ContextVar[str | None] = ContextVar("nanobot_trace_id", default=None)
_ALLOWED_TRACE_CHARS = set(string.ascii_letters + string.digits + "-_.:")


def new_trace_id() -> str:
    """Return a compact trace id that is safe for HTTP headers and logs."""
    return f"nb-{uuid.uuid4().hex}"


def normalize_trace_id(value: object | None) -> str:
    """Normalize caller-provided trace ids without leaking arbitrary text into headers."""
    raw = str(value or "").strip()
    if not raw:
        return new_trace_id()
    safe = "".join(ch for ch in raw if ch in _ALLOWED_TRACE_CHARS)
    return safe[:96] or new_trace_id()


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


def set_trace_id(trace_id: str) -> Token[str | None]:
    return _TRACE_ID.set(trace_id)


def reset_trace_id(token: Token[str | None]) -> None:
    _TRACE_ID.reset(token)
