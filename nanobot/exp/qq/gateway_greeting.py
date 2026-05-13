"""Gateway restart greeting helpers for the QQ downstream adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

DEFAULT_RESTART_FLAG_PATH = Path("/root/.nanobot/workspace/lof_monitor/.gateway_restart_flag")


def greeting_for_hour(hour: int) -> str:
    """Return the Chinese greeting used after the gateway reconnects."""
    if 5 <= hour < 12:
        return "早安 ☀️"
    if 12 <= hour < 18:
        return "下午好 🌤️"
    if 18 <= hour < 23:
        return "晚上好 🌙"
    return "夜深了，早点休息 🌛"


def build_restart_greeting(
    *,
    now: datetime | None = None,
    flag_path: Path = DEFAULT_RESTART_FLAG_PATH,
) -> str | None:
    """Build the one-shot restart greeting and consume the flag when present."""
    if not flag_path.exists():
        return None
    try:
        flag_path.unlink()
    except OSError:
        pass
    now = now or datetime.now()
    return f"gateway 已上线 · {greeting_for_hour(now.hour)}"


__all__ = ["DEFAULT_RESTART_FLAG_PATH", "build_restart_greeting", "greeting_for_hour"]
