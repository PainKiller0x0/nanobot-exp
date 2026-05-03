"""Shared helpers for deterministic direct replies."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DASHBOARD_TIMEOUT = 0.8
DASHBOARD_BASES = ("http://172.17.0.1:8093", "http://127.0.0.1:8093")


def get_json(path: str, default: Any, *, timeout: float = DASHBOARD_TIMEOUT) -> Any:
    return request_json("GET", path, None, default, timeout=timeout)


def post_json(
    path: str, payload: dict[str, Any], default: Any, *, timeout: float = DASHBOARD_TIMEOUT
) -> Any:
    return request_json("POST", path, payload, default, timeout=timeout)


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    default: Any,
    *,
    timeout: float = DASHBOARD_TIMEOUT,
) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for base in dashboard_bases():
        req = Request(base + path, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
    return default


def dashboard_bases() -> list[str]:
    values = [os.environ.get("NANOBOT_DASHBOARD_URL", "").strip(), *DASHBOARD_BASES]
    bases: list[str] = []
    for value in values:
        value = value.rstrip("/")
        if value and value not in bases:
            bases.append(value)
    return bases


def compact_text(text: str) -> str:
    return re.sub(r"[\s，。！？!?,.、:：;；]+", "", text.lower())


def short_text(value: Any, limit: int = 48) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "..."


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def items_from(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in as_list(data.get("items")) if isinstance(item, dict)]
