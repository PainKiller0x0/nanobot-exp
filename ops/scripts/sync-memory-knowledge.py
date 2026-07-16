#!/usr/bin/env python3
"""Index knowledge-inbox metadata in Memory-RS without loading article bodies."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib import error, request


INBOX = Path(os.environ.get("KNOWLEDGE_INBOX_ITEMS", "/root/.nanobot/data/knowledge-inbox/items.json"))
ENDPOINT = os.environ.get("MEMORY_RS_URL", "http://127.0.0.1:8105").rstrip("/") + "/api/knowledge"


def clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def mapped_items(raw: object) -> list[dict[str, object]]:
    values = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    items: list[dict[str, object]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        item_id = clean_text(item.get("id") or item.get("item_id"), 180)
        if not item_id:
            continue
        keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
        items.append(
            {
                "id": item_id,
                "title": clean_text(item.get("title") or item.get("name") or item.get("description"), 300),
                "source": clean_text(item.get("source") or item.get("source_name") or item.get("host"), 160),
                "summary": clean_text(item.get("llm_summary") or item.get("summary") or item.get("extractive_summary") or item.get("description"), 1800),
                "keywords": [clean_text(word, 80) for word in keywords if clean_text(word, 80)][:30],
                "score": numeric_score(item),
                "markdown_path": clean_text(item.get("markdown_path") or item.get("markdown") or "", 500),
                "created_at": clean_text(item.get("captured_at") or item.get("created_at") or item.get("saved_at") or "", 80),
            }
        )
    return items


def numeric_score(item: dict[str, object]) -> float:
    for key in ("manual_score", "decision_score", "auto_decision_score", "score"):
        try:
            return float(item.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def main() -> int:
    if not INBOX.exists():
        return 0
    try:
        raw = json.loads(INBOX.read_text(encoding="utf-8"))
        payload = json.dumps({"scope": "default-nanobot", "items": mapped_items(raw)}, ensure_ascii=False).encode("utf-8")
        req = request.Request(ENDPOINT, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=4) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"memory-rs HTTP {response.status}")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"memory knowledge sync failed: HTTP {exc.code} {detail}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"memory knowledge sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
