"""Capability registry based direct replies."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CAPABILITY_FILE = Path("/root/.nanobot/capabilities.json")
DASHBOARD_TIMEOUT = 0.8
DASHBOARD_BASES = ("http://172.17.0.1:8093", "http://127.0.0.1:8093")
DASHBOARD_ENDPOINTS = {
    "system": ("/api/system", {}),
    "sidecars": ("/api/sidecars", {}),
    "caps": ("/api/capabilities", {}),
    "notify": ("/api/notify-jobs", {}),
    "articles": ("/rss/api/entries?days=1&limit=5", {"items": []}),
    "lof": ("/api/status", {}),
}


def format_capability_menu() -> str:
    items = load_capabilities()
    enabled = [item for item in items if item.get("enabled", True)]
    categories: dict[str, list[dict[str, Any]]] = {}
    for item in enabled:
        categories.setdefault(str(item.get("category") or "\u5176\u4ed6"), []).append(item)

    lines = [
        "\U0001f9ed Nanobot \u80fd\u529b\u83dc\u5355\uff08\u672a\u8c03\u7528 LLM\uff09",
        f"\u5df2\u767b\u8bb0\uff1a{len(items)} \u4e2a\uff1b\u5df2\u542f\u7528\uff1a{len(enabled)} \u4e2a",
    ]
    for category, group in sorted(categories.items()):
        lines.extend(["", f"\u3010{category}\u3011"])
        for item in group[:6]:
            trigger = _first(_list(item.get("trigger_phrases")))
            suffix = f"\uff08\u95ee\uff1a{trigger}\uff09" if trigger else ""
            lines.append(f"- {_name(item)}\uff1a{_short(item.get('description'), 42)}{suffix}")
    lines.extend([
        "",
        "\u5e38\u7528\u95ee\u6cd5\uff1a",
        "- \u5185\u5b58\u600e\u4e48\u6837 / \u670d\u52a1\u72b6\u6001 / \u4eca\u5929\u5148\u770b\u4ec0\u4e48",
        "- LOF \u6709\u673a\u4f1a\u5417 / \u4eca\u5929\u6587\u7ae0\u6709\u54ea\u4e9b / \u4eca\u5929\u70ed\u70b9",
        "\u603b\u63a7\u53f0\uff1ahttp://150.158.121.88:8093/sidecars",
    ])
    return "\n".join(lines)


def format_capability_status() -> str:
    caps = _dict(dashboard_json("/api/capabilities", {}))
    sidecars = _dict(dashboard_json("/api/sidecars", {}))
    cap_summary = _cap_summary(caps)
    side_summary = _dict(sidecars.get("summary"))
    bad_caps = _bad_names(_items(caps))
    bad_sidecars = _bad_names(_items(sidecars))

    return "\n".join([
        "\U0001f9ed \u80fd\u529b\u72b6\u6001\uff08\u672a\u8c03\u7528 LLM\uff09",
        f"\u80fd\u529b\uff1a{cap_summary.get('healthy', '-')} / {cap_summary.get('total', '-')} \u53ef\u7528\uff0c"
        f"\u542f\u7528 {cap_summary.get('enabled', '-')}",
        f"\u670d\u52a1\uff1a{side_summary.get('healthy', '-')} / {side_summary.get('total', '-')} \u6b63\u5e38",
        "\u5f02\u5e38\u80fd\u529b\uff1a" + ("\u3001".join(bad_caps[:5]) if bad_caps else "\u6682\u65e0"),
        "\u5f02\u5e38\u670d\u52a1\uff1a" + ("\u3001".join(bad_sidecars[:5]) if bad_sidecars else "\u6682\u65e0"),
        "\u8be6\u60c5\uff1ahttp://150.158.121.88:8093/sidecars",
    ])


def format_today_brief() -> str:
    data = _dashboard_snapshot()
    mem = _dict(data["system"].get("memory"))
    side_summary = _dict(data["sidecars"].get("summary"))
    cap_summary = _dict(data["caps"].get("summary"))
    jobs = _list(data["notify"].get("job_details") or data["notify"].get("configured_jobs"))
    article_items = _items(data["articles"])
    rows = _list(_dict(data["lof"].get("last_board")).get("rows"))
    errors = [job for job in jobs if isinstance(job, dict) and _dict(job.get("status")).get("last_status") in {"error", "timeout"}]
    high_lof = [row for row in rows if (_float(_dict(row).get("rt_premium_pct")) or 0) >= 5]

    lines = [
        "\U0001f9ed \u4eca\u65e5\u6458\u8981\uff08\u672a\u8c03\u7528 LLM\uff09",
        f"\u7cfb\u7edf\uff1a\u5185\u5b58 {mem.get('used_mb', '-')} / {mem.get('total_mb', '-')} MB\uff1b"
        f"\u670d\u52a1 {side_summary.get('healthy', '-')} / {side_summary.get('total', '-')} \u6b63\u5e38",
        f"\u80fd\u529b\uff1a{cap_summary.get('healthy', '-')} / {cap_summary.get('total', '-')} \u53ef\u7528",
        f"\u4efb\u52a1\uff1a{len(jobs)} \u4e2a\uff0c\u5f02\u5e38 {len(errors)} \u4e2a",
        f"\u6587\u7ae0\uff1a{len(article_items)} \u7bc7\uff1bLOF \u9ad8\u6ea2\u4ef7\uff1a{len(high_lof)} \u53ea",
        "",
        "\u5148\u770b\u8fd9\u4e9b\uff1a",
    ]
    lines.extend(f"- {item}" for item in _attention_items(data["sidecars"], errors, high_lof, article_items)[:8])
    return "\n".join(lines)


def dashboard_json(path: str, default: Any) -> Any:
    for base in _dashboard_bases():
        req = Request(base + path, headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=DASHBOARD_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
    return default


def load_capabilities() -> list[dict[str, Any]]:
    path = Path(os.environ.get("CAPABILITY_REGISTRY_CONFIG", "") or CAPABILITY_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = []
    return [item for item in data if isinstance(item, dict)]


def _dashboard_snapshot() -> dict[str, dict[str, Any]]:
    return {name: _dict(dashboard_json(path, default)) for name, (path, default) in DASHBOARD_ENDPOINTS.items()}


def _dashboard_bases() -> list[str]:
    values = [os.environ.get("NANOBOT_DASHBOARD_URL", "").strip(), *DASHBOARD_BASES]
    bases: list[str] = []
    for value in values:
        value = value.rstrip("/")
        if value and value not in bases:
            bases.append(value)
    return bases


def _cap_summary(caps: dict[str, Any]) -> dict[str, Any]:
    if summary := _dict(caps.get("summary")):
        return summary
    items = load_capabilities()
    return {"total": len(items), "enabled": sum(1 for item in items if item.get("enabled", True)), "healthy": "-"}


def _attention_items(sidecars: dict[str, Any], errors: list[Any], high_lof: list[Any], article_items: list[Any]) -> list[str]:
    attention = [f"\u670d\u52a1\u5f02\u5e38\uff1a{_name(item)}" for item in _items(sidecars) if not item.get("ok")]
    attention.extend(f"\u4efb\u52a1\u5f02\u5e38\uff1a{_name(_dict(job))}" for job in errors[:3])
    for row in sorted((_dict(row) for row in high_lof), key=lambda r: _float(r.get("rt_premium_pct")) or -999, reverse=True)[:3]:
        attention.append(f"LOF\uff1a{row.get('code', '-')} {_short(row.get('name'), 14)} {_pct(row.get('rt_premium_pct'))}")
    attention.extend(
        f"\u6587\u7ae0\uff1a{_short(_dict(article).get('title') or _dict(article).get('name'), 36)}"
        for article in article_items[:3]
    )
    return attention or ["\u6ca1\u6709\u786c\u5f02\u5e38\uff0c\u4eca\u5929\u53ef\u4ee5\u5148\u6162\u6162\u770b\u6587\u7ae0\u548c LOF\u3002"]


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list(data.get("items")) if isinstance(item, dict)]


def _bad_names(items: list[dict[str, Any]]) -> list[str]:
    return [_name(item) for item in items if not item.get("ok")]


def _first(values: list[Any]) -> str:
    return str(values[0]) if values else ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("id") or "-")


def _short(value: Any, limit: int = 48) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "..."


def _float(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    number = _float(value)
    return "-" if number is None else f"{number:+.2f}%"
