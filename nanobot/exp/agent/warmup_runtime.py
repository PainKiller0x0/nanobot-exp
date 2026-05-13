"""AgentLoop warmup scheduling helpers for nanobot-exp.

The upstream loop should stay focused on message orchestration.  These helpers
own the local startup optimisations: tokenizer preloading and optional external
LLM warmup in a child process.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Coroutine, Mapping
from typing import Any, Callable

ScheduleBackground = Callable[[Coroutine[Any, Any, Any]], None]
_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: str = "0", *, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(name, default).strip().lower() in _TRUE_VALUES


def schedule_external_llm_warmup(
    *,
    already_started: bool,
    schedule_background: ScheduleBackground,
    logger: Any,
    env: Mapping[str, str] | None = None,
    executable: str | None = None,
) -> bool:
    """Schedule child-process LLM warmup once when enabled by environment."""
    source = os.environ if env is None else env
    if already_started or not env_flag("NANOBOT_LLM_WARMUP", env=source):
        return already_started
    schedule_background(_run_external_llm_warmup(env=source, executable=executable, logger=logger))
    return True


def schedule_tokenizer_warmup(
    *,
    already_started: bool,
    schedule_background: ScheduleBackground,
    logger: Any,
) -> bool:
    """Schedule tokenizer warmup once without blocking channel heartbeats."""
    if already_started:
        return True
    schedule_background(_run_tokenizer_warmup(logger=logger))
    return True


async def _run_external_llm_warmup(
    *,
    env: Mapping[str, str],
    executable: str | None,
    logger: Any,
) -> None:
    try:
        delay = float(env.get("NANOBOT_LLM_WARMUP_DELAY_S", "10") or "0")
    except ValueError:
        delay = 10.0
    if delay > 0:
        await asyncio.sleep(delay)

    limit = env.get("NANOBOT_LLM_WARMUP_SESSIONS", "1")
    timeout_raw = env.get("NANOBOT_LLM_WARMUP_TIMEOUT_S", "120")
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 120.0
    logger.info("Starting external LLM warmup (sessions={}, timeout={}s)", limit, timeout_s)
    try:
        proc = await asyncio.create_subprocess_exec(
            executable or sys.executable,
            "-m",
            "nanobot.agent.warmup",
            "--limit",
            str(limit),
            "--timeout",
            str(timeout_s),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=max(timeout_s + 30, 60),
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("External LLM warmup timed out")
            return
        out = (stdout or b"").decode("utf-8", "replace").strip()
        err = (stderr or b"").decode("utf-8", "replace").strip()
        if proc.returncode == 0:
            logger.info("External LLM warmup completed: {}", out[-500:] if out else "ok")
        else:
            logger.warning(
                "External LLM warmup failed rc={}: {} {}",
                proc.returncode,
                out[-500:],
                err[-500:],
            )
    except Exception as exc:  # noqa: BLE001 - startup warmup must never crash the loop.
        logger.warning("External LLM warmup launch failed: {}", exc)


async def _run_tokenizer_warmup(*, logger: Any) -> None:
    def _load() -> None:
        import tiktoken

        tiktoken.get_encoding("cl100k_base").encode("nanobot warmup")

    try:
        started = time.perf_counter()
        await asyncio.to_thread(_load)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("Tokenizer warmup completed in {}ms", elapsed_ms)
    except Exception:
        logger.debug("Tokenizer warmup failed", exc_info=True)


__all__ = ["env_flag", "schedule_external_llm_warmup", "schedule_tokenizer_warmup"]
