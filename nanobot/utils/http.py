"""Small urllib-based JSON HTTP helpers for local Nanobot services."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(
    urls: str | Iterable[str],
    method: str,
    payload: dict[str, Any] | None,
    default: Any,
    *,
    timeout: float,
) -> Any:
    """Request JSON from one or more URLs, failing over in order."""
    candidates = [urls] if isinstance(urls, str) else [url for url in urls if url]
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"

    for url in candidates:
        try:
            request = Request(url, data=body, method=method, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else default
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
    return default
