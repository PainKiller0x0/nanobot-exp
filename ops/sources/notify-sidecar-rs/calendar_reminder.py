#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SHANGHAI = timezone(timedelta(hours=8))
HOLIDAY_DIR = Path("/root/.nanobot/workspace/skills/weather-expert")


def today_shanghai() -> date:
    override = os.environ.get("NOTIFY_REMINDER_DATE", "").strip()
    if override:
        return date.fromisoformat(override)
    return datetime.now(SHANGHAI).date()


def holiday_paths(year: int) -> list[Path]:
    paths: list[Path] = []
    env_path = os.environ.get("NOTIFY_HOLIDAY_FILE", "").strip()
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            HOLIDAY_DIR / f"holidays_{year}.json",
            HOLIDAY_DIR / f"holidays_{year + 1}.json",
            HOLIDAY_DIR / "holidays_cache.json",
        ]
    )
    return paths


def load_holiday_item(check_date: date) -> dict[str, Any]:
    key = check_date.isoformat()
    short_key = check_date.strftime("%m-%d")
    for path in holiday_paths(check_date.year):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        days = data.get("holiday") or data.get("holidays") or {}
        if not isinstance(days, dict):
            continue
        item = days.get(key) or days.get(short_key)
        if isinstance(item, dict):
            return item
    return {}


def is_adjusted_workday(item: dict[str, Any]) -> bool:
    if item.get("holiday") is not False:
        return False
    name = str(item.get("name") or item.get("reason") or "")
    return (
        item.get("wage") == 1
        or item.get("after") is not None
        or item.get("before") is not None
        or "\u8865\u73ed" in name
    )


def is_cn_workday(check_date: date) -> bool:
    item = load_holiday_item(check_date)
    if item.get("holiday") is True:
        return False
    if is_adjusted_workday(item):
        return True
    return check_date.weekday() < 5


def is_last_workday_before_rest(check_date: date) -> bool:
    return is_cn_workday(check_date) and not is_cn_workday(check_date + timedelta(days=1))


def final_workday_label(check_date: date) -> str:
    tomorrow = check_date + timedelta(days=1)
    if tomorrow.month != check_date.month:
        return "\u672c\u6708\u6700\u540e\u4e00\u4e2a\u5de5\u4f5c\u65e5"
    return "\u672c\u5468\u6700\u540e\u4e00\u4e2a\u5de5\u4f5c\u65e5"


def print_if(text: str, condition: bool) -> int:
    if condition:
        print(text)
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    today = today_shanghai()
    tomorrow = today + timedelta(days=1)
    today_workday = is_cn_workday(today)
    tomorrow_workday = is_cn_workday(tomorrow)
    final_workday = today_workday and not tomorrow_workday
    final_label = final_workday_label(today)

    if mode == "daily-final":
        if not final_workday:
            return 0
        if today.weekday() == 4:
            return print_if("\u5468\u4e94\u5566\uff0c\u8bb0\u5f97\u63d0\u4ea4\u65e5\u62a5\uff01\U0001f4dd", True)
        return print_if(f"{final_label}\uff0c\u8bb0\u5f97\u63d0\u4ea4\u65e5\u62a5\uff01\U0001f4dd", True)

    if mode == "daily-normal":
        return print_if("\u4e0b\u73ed\u524d\u8bb0\u5f97\u5199\u65e5\u62a5\uff01\U0001f4dd", today_workday and tomorrow_workday)

    if mode == "weekly-final":
        if not final_workday:
            return 0
        if today.weekday() == 4:
            return print_if("\u5468\u4e94\u5566\uff0c\u8bb0\u5f97\u5199\u9879\u76ee\u5468\u62a5\uff01\U0001f4dd", True)
        return print_if(f"{final_label}\uff0c\u8bb0\u5f97\u5199\u9879\u76ee\u5468\u62a5\uff01\U0001f4dd", True)

    if mode == "debug":
        info = {
            "today": today.isoformat(),
            "tomorrow": tomorrow.isoformat(),
            "today_workday": today_workday,
            "tomorrow_workday": tomorrow_workday,
            "last_workday_before_rest": final_workday,
            "today_holiday_info": load_holiday_item(today),
            "tomorrow_holiday_info": load_holiday_item(tomorrow),
        }
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    print("usage: calendar_reminder.py daily-final|daily-normal|weekly-final|debug", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
