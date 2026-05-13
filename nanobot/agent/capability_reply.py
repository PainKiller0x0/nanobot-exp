"""Capability registry based direct replies."""

from __future__ import annotations

from nanobot.agent import capability_formatters
from nanobot.agent.capability_registry import load_capabilities
from nanobot.agent.capability_snapshot import dashboard_json, dashboard_snapshot
from nanobot.agent.direct_reply_common import as_dict as _dict


def format_capability_menu() -> str:
    return capability_formatters.format_capability_menu(load_capabilities())


def format_capability_status() -> str:
    caps = _dict(dashboard_json("/api/capabilities", {}))
    sidecars = _dict(dashboard_json("/api/sidecars", {}))
    return capability_formatters.format_capability_status(caps, sidecars)


def format_evolution_brief() -> str:
    data = _dict(dashboard_json("/api/evolution", {"items": []}))
    return capability_formatters.format_evolution_brief(data)


def format_today_brief() -> str:
    data = dashboard_snapshot(fetcher=dashboard_json)
    return capability_formatters.format_today_brief(data)
