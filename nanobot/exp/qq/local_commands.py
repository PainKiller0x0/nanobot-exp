"""Local skill command runners used by the QQ downstream adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Sequence

PERSONAL_OPS_SCRIPT = Path("/root/.nanobot/workspace/skills/personal-ops-assistant/ops_summary.py")
KNOWLEDGE_INBOX_SCRIPT = Path("/root/.nanobot/workspace/skills/knowledge-inbox/inbox.py")


async def _run_python_script(
    script: Path,
    args: Sequence[str],
    *,
    timeout_sec: float,
    missing_message: str,
    timeout_message: str,
    failure_prefix: str,
    empty_message: str,
) -> str:
    if not script.exists():
        return missing_message

    proc = await asyncio.create_subprocess_exec(
        "python3",
        str(script),
        *[str(arg) for arg in args],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return timeout_message

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        detail = err or out or f"exit {proc.returncode}"
        return f"{failure_prefix}{detail[:500]}"
    return out or empty_message


async def run_personal_ops_command(
    command: str,
    *,
    script: Path = PERSONAL_OPS_SCRIPT,
    timeout_sec: float = 20,
) -> str:
    """Run the personal ops script without involving the LLM."""
    return await _run_python_script(
        script,
        [command],
        timeout_sec=timeout_sec,
        missing_message="运维助手脚本不存在，暂时无法查询。",
        timeout_message="运维查询超时了，稍后再试一下。",
        failure_prefix="运维查询失败：",
        empty_message="运维查询完成，但没有输出。",
    )


async def run_knowledge_inbox_command(
    args: Sequence[str],
    *,
    script: Path = KNOWLEDGE_INBOX_SCRIPT,
    timeout_sec: float = 35,
) -> str:
    """Run the knowledge inbox script without involving the LLM."""
    return await _run_python_script(
        script,
        args,
        timeout_sec=timeout_sec,
        missing_message="知识收件箱脚本不存在，暂时无法处理链接。",
        timeout_message="知识收件箱抓取超时了，可能是目标网页太慢或禁止访问。",
        failure_prefix="知识收件箱失败：",
        empty_message="知识收件箱处理完成，但没有输出。",
    )


__all__ = ["run_knowledge_inbox_command", "run_personal_ops_command"]
