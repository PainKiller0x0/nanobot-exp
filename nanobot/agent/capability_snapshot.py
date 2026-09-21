"""Dashboard snapshot helpers for capability direct replies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nanobot.agent.capability_registry import enabled_capabilities, load_capabilities
from nanobot.agent.direct_reply_common import DASHBOARD_TIMEOUT, as_dict, get_json

DASHBOARD_ENDPOINTS: dict[str, tuple[str, Any]] = {
    "system": ("/api/system", {}),
    "sidecars": ("/api/sidecars", {}),
    "caps": ("/api/capabilities", {}),
    "notify": ("/api/notify-jobs", {}),
    "articles": ("/rss/api/entries?days=1&limit=5", {"items": []}),
    "lof": ("/api/status", {}),
    "evolution": ("/api/evolution", {"items": []}),
}
DashboardFetcher = Callable[[str, Any], Any]


def dashboard_json(path: str, default: Any) -> Any:
    return get_json(path, default, timeout=DASHBOARD_TIMEOUT)


def dashboard_snapshot(*, fetcher: DashboardFetcher = dashboard_json) -> dict[str, dict[str, Any]]:
    return {
        name: as_dict(fetcher(path, default))
        for name, (path, default) in DASHBOARD_ENDPOINTS.items()
    }


def capability_summary(caps: dict[str, Any]) -> dict[str, Any]:
    if summary := as_dict(caps.get("summary")):
        return summary
    items = load_capabilities()
    return {
        "total": len(items),
        "enabled": len(enabled_capabilities(items)),
        "healthy": "-",
    }


__all__ = [
    "DASHBOARD_ENDPOINTS",
    "DashboardFetcher",
    "capability_summary",
    "dashboard_json",
    "dashboard_snapshot",
]
