"""Gateway restart greeting helpers for the QQ channel."""

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


def consume_restart_flag(flag_path: Path = DEFAULT_RESTART_FLAG_PATH) -> bool:
    """Return True once for a restart flag, deleting the flag best-effort."""
    if not flag_path.exists():
        return False
    try:
        flag_path.unlink()
    except OSError:
        pass
    return True


def build_restart_greeting(
    *,
    now: datetime | None = None,
    flag_path: Path = DEFAULT_RESTART_FLAG_PATH,
) -> str | None:
    """Build the restart greeting if the one-shot flag is present."""
    if not consume_restart_flag(flag_path):
        return None
    now = now or datetime.now()
    return f"gateway 已上线 · {greeting_for_hour(now.hour)}"


__all__ = [
    "DEFAULT_RESTART_FLAG_PATH",
    "build_restart_greeting",
    "consume_restart_flag",
    "greeting_for_hour",
]
