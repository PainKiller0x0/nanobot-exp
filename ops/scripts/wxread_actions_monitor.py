#!/usr/bin/env python3
"""Notify only when the daily wxread GitHub Actions run is missing or unhealthy."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPO = "PainKiller0x0/wxread"
WORKFLOW = "deploy.yml"
ACTIONS_URL = f"https://github.com/{REPO}/actions/workflows/{WORKFLOW}"
API_URL = (
    f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"
    "?per_page=100"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


def fetch_runs() -> list[dict[str, object]]:
    request = Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "nanobot-wxread-actions-monitor",
        },
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("GitHub response has no workflow_runs list")
    return runs


def run_day(run: dict[str, object]) -> date:
    created_at = run.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("GitHub run has no created_at timestamp")
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return created.astimezone(SHANGHAI).date()


def assess_day(
    runs: list[dict[str, object]], day: date, now: datetime, *, required: bool
) -> str | None:
    day_runs = [run for run in runs if run_day(run) == day]
    if not day_runs:
        if required:
            return f"{day}: 当天没有启动记录（截至北京时间 09:15）。"
        return None

    latest = max(day_runs, key=lambda run: str(run.get("created_at", "")))
    status = latest.get("status")
    if status in ACTIVE_STATUSES:
        created_at = latest.get("created_at")
        if not required and isinstance(created_at, str):
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if now.astimezone(ZoneInfo("UTC")) - created > timedelta(hours=4):
                return f"{day}: 执行已持续超过 4 小时，仍未完成。 {latest.get('html_url', '')}"
        return None

    if status == "completed" and latest.get("conclusion") == "success":
        return None

    conclusion = latest.get("conclusion") or status or "unknown"
    return f"{day}: 最近一次执行状态为 {conclusion}。 {latest.get('html_url', '')}"


def check_runs(runs: list[dict[str, object]], now: datetime) -> list[str]:
    today = now.astimezone(SHANGHAI).date()
    yesterday = today - timedelta(days=1)
    alerts = [
        alert
        for alert in (
            assess_day(runs, yesterday, now, required=False),
            assess_day(runs, today, now, required=True),
        )
        if alert
    ]
    return alerts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        alerts = check_runs(fetch_runs(), datetime.now(SHANGHAI))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        alerts = [f"无法读取 GitHub Actions 状态：{str(exc)[:180]}"]

    if args.dry_run:
        print("检查正常，无需通知。" if not alerts else "\n".join(alerts))
    elif alerts:
        print("【微信读书每日任务异常】\n" + "\n".join(alerts) + f"\n查看：{ACTIONS_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
