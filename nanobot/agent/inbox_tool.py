"""Knowledge inbox skill runner for deterministic direct replies."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

DEFAULT_TOOL = Path("/root/.nanobot/workspace/skills/knowledge-inbox/inbox.py")
FALLBACK_TOOL = Path("/app/ops/sources/knowledge-inbox/inbox.py")
TIMEOUT_SECS = 24
MAX_REPLY_CHARS = 1800


def run_tool(
    args: list[str],
    *,
    user_id: str | None = None,
    env: Mapping[str, str] | None = None,
    python_executable: str | None = None,
    timeout: int = TIMEOUT_SECS,
) -> str:
    """Run the knowledge-inbox skill without crashing the reply path."""
    run_env = dict(os.environ if env is None else env)
    tool = resolve_tool(env=run_env)
    if not tool.exists():
        return f"知识收件箱失败：找不到脚本 {tool}"

    if user_id:
        run_env["NANOBOT_INBOX_USER"] = user_id
    try:
        completed = subprocess.run(
            [python_executable or sys.executable, str(tool), *args],
            capture_output=True,
            env=run_env,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "知识收件箱失败：抓取超时，先不打扰主回复链路。"
    except Exception as exc:  # noqa: BLE001 - direct reply must stay non-crashing.
        return f"知识收件箱失败：{exc}"

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        return f"知识收件箱失败：{clip_text(detail, 600)}"
    return completed.stdout


def resolve_tool(
    *,
    env: Mapping[str, str] | None = None,
    default_tool: Path = DEFAULT_TOOL,
    fallback_tool: Path = FALLBACK_TOOL,
) -> Path:
    values = os.environ if env is None else env
    configured = values.get("NANOBOT_KNOWLEDGE_INBOX_TOOL", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([default_tool, fallback_tool])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else default_tool


def clip_text(text: str, limit: int = MAX_REPLY_CHARS) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 20)].rstrip() + "\n...（已截断）"


__all__ = [
    "DEFAULT_TOOL",
    "FALLBACK_TOOL",
    "MAX_REPLY_CHARS",
    "TIMEOUT_SECS",
    "clip_text",
    "resolve_tool",
    "run_tool",
]
