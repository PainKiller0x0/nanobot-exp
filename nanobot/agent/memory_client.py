"""memory-rs client helpers for deterministic Nanobot memory replies."""

from __future__ import annotations

import os
from typing import Any, cast

from nanobot.utils.http import request_json

MEMORY_TIMEOUT = 0.35
MEMORY_SOURCE = "nanobot-direct-reply"
MEMORY_RS_URL = os.environ.get("MEMORY_RS_URL", "").rstrip("/")
MEMORY_RS_ENABLED = bool(MEMORY_RS_URL)
MEMORY_SCOPE = os.environ.get("MEMORY_RS_SCOPE", "default-nanobot").strip() or "default-nanobot"
LEGACY_MEMORY_FALLBACK = os.environ.get("MEMORY_RS_LEGACY_FALLBACK", "1") != "0"
def save_memory(content: str, *, user_id: str | None, category: str) -> dict[str, Any]:
    if not MEMORY_RS_ENABLED:
        return _save_legacy_memory(content, user_id=user_id, category=category)
    try:
        data = as_dict(
            post_json(
                "/api/memories",
                {
                    "scope": MEMORY_SCOPE,
                    "kind": category,
                    "content": content,
                    "status": "confirmed",
                    "source": MEMORY_SOURCE,
                    "channel": user_id or "direct",
                    "pinned": True,
                },
                {},
            )
        )
    except AssertionError:
        data = {}
    if data.get("id") or not LEGACY_MEMORY_FALLBACK:
        return data
    return _save_legacy_memory(content, user_id=user_id, category=category)


def memory_status() -> tuple[dict[str, Any], list[Any]]:
    if not MEMORY_RS_ENABLED:
        return _legacy_memory_status()
    try:
        stats = as_dict(get_json("/api/stats", {}))
        recent = get_json(f"/api/memories?scope={MEMORY_SCOPE}&status=confirmed&limit=5", [])
    except AssertionError:
        stats, recent = {}, []
    if (stats or recent) or not LEGACY_MEMORY_FALLBACK:
        return stats, as_list(recent)
    return _legacy_memory_status()


def search_memories(query: str, *, limit: int = 8) -> list[Any]:
    if not MEMORY_RS_ENABLED:
        return _legacy_search_memories(query, limit=limit)
    try:
        data = as_dict(
            post_json("/api/recall", {"scope": MEMORY_SCOPE, "query": query, "limit": limit}, {})
        )
    except AssertionError:
        data = {}
    if not data and LEGACY_MEMORY_FALLBACK:
        legacy = post_json(
            "/reflexio/api/memory/search",
            {"query": query, "limit": limit},
            {},
        )
        if isinstance(legacy, list):
            return as_list(legacy)[:limit]
        data = as_dict(legacy)
    rows = [*as_list(data.get("hot")), *as_list(data.get("results"))]
    seen: set[tuple[str, int]] = set()
    result: list[Any] = []
    for value in rows:
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        key = (str(row.get("kind") or ""), int(row.get("id") or 0))
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "id": row.get("id"),
                "category": row.get("kind", "note"),
                "content": row.get("content", ""),
                "source": row.get("source", "memory-rs"),
                "created_at": row.get("created_at", ""),
            }
        )
    return result[:limit]


def _save_legacy_memory(
    content: str, *, user_id: str | None, category: str
) -> dict[str, Any]:
    return as_dict(
        post_json(
            "/reflexio/api/memories",
            {
                "user_id": user_id,
                "category": category,
                "content": content,
                "source": MEMORY_SOURCE,
            },
            {},
        )
    )


def _legacy_memory_status() -> tuple[dict[str, Any], list[Any]]:
    stats = as_dict(get_json("/reflexio/api/stats", {}))
    recent = get_json("/reflexio/api/memories?limit=5", [])
    return stats, as_list(recent)


def _legacy_search_memories(query: str, *, limit: int) -> list[Any]:
    legacy = post_json(
        "/reflexio/api/memory/search",
        {"query": query, "limit": limit},
        {},
    )
    if isinstance(legacy, list):
        return as_list(legacy)[:limit]
    data = as_dict(legacy)
    results = data.get("results")
    return as_list(results)[:limit]


def get_json(path: str, default: Any) -> Any:
    urls = [f"{MEMORY_RS_URL}{path}"] if MEMORY_RS_URL else []
    return request_json(urls, "GET", None, default, timeout=MEMORY_TIMEOUT)


def post_json(path: str, payload: dict[str, Any], default: Any) -> Any:
    urls = [f"{MEMORY_RS_URL}{path}"] if MEMORY_RS_URL else []
    return request_json(urls, "POST", payload, default, timeout=MEMORY_TIMEOUT)


def as_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []
