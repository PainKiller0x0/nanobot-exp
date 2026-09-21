"""Capability registry loading for deterministic direct replies."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CAPABILITY_FILE = Path("/root/.nanobot/capabilities.json")


def load_capabilities(path: Path | None = None, *, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Load enabled capability metadata from the local registry file."""
    source = path or configured_registry_path(env=env)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def configured_registry_path(*, env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    configured = values.get("CAPABILITY_REGISTRY_CONFIG", "").strip()
    return Path(configured) if configured else CAPABILITY_FILE


def enabled_capabilities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("enabled", True)]


def group_by_category(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        categories.setdefault(str(item.get("category") or "其他"), []).append(item)
    return categories


__all__ = [
    "CAPABILITY_FILE",
    "configured_registry_path",
    "enabled_capabilities",
    "group_by_category",
    "load_capabilities",
]
