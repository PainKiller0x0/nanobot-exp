"""Reflexio client helpers for deterministic memory direct replies."""

from __future__ import annotations

from typing import Any

from nanobot.agent.direct_reply_common import (
    get_json as _common_get_json,
)
from nanobot.agent.direct_reply_common import (
    post_json as _common_post_json,
)

REFLEXIO_TIMEOUT = 0.8
MEMORY_SOURCE = "nanobot-direct-reply"


def save_memory(content: str, *, user_id: str | None, category: str) -> dict[str, Any]:
    return as_dict(
        post_json(
            "/reflexio/api/memories",
            {
                "user_id": user_id or "default_user",
                "category": category,
                "content": content,
                "source": MEMORY_SOURCE,
            },
            {},
        )
    )


def memory_status() -> tuple[dict[str, Any], list[Any]]:
    stats = as_dict(get_json("/reflexio/api/stats", {}))
    recent = get_json("/reflexio/api/memories?limit=5", [])
    return stats, recent if isinstance(recent, list) else []


def search_memories(query: str, *, limit: int = 8) -> list[Any]:
    data = post_json("/reflexio/api/memory/search", {"query": query, "limit": limit}, {"results": []})
    results = data.get("results") if isinstance(data, dict) else []
    return results if isinstance(results, list) else []


def get_json(path: str, default: Any) -> Any:
    return _common_get_json(path, default, timeout=REFLEXIO_TIMEOUT)


def post_json(path: str, payload: dict[str, Any], default: Any) -> Any:
    return _common_post_json(path, payload, default, timeout=REFLEXIO_TIMEOUT)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "MEMORY_SOURCE",
    "REFLEXIO_TIMEOUT",
    "as_dict",
    "get_json",
    "memory_status",
    "post_json",
    "save_memory",
    "search_memories",
]
