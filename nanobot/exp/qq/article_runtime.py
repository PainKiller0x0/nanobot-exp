"""Runtime adapters for QQ article requests.

This is nanobot-exp glue, not upstream botpy channel logic: prefer the Rust RSS
sidecar, then fall back to the legacy personal skill scripts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import aiohttp

from nanobot.exp.qq import rss_sidecar


async def run_sidecar_json(
    session: aiohttp.ClientSession | None,
    args: Sequence[str],
    *,
    timeout_sec: float = 30.0,
    logger: Any | None = None,
) -> dict[str, Any] | None:
    """Run RSS sidecar client semantics and return JSON."""
    rust_payload = await rss_sidecar.run_client_json(
        session,
        args,
        timeout_sec=timeout_sec,
        logger=logger,
    )
    if rust_payload is not None:
        return rust_payload

    cmd = [
        "python3",
        "/root/.nanobot/workspace/skills/wechat-rss-sidecar/client.py",
        *args,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError:
        if logger is not None:
            logger.warning("qq wechat guard timeout: {}", " ".join(cmd))
        return None
    except Exception as e:
        if logger is not None:
            logger.warning("qq wechat guard exec failed: {} err={}", " ".join(cmd), e)
        return None

    out = (stdout or b"").decode("utf-8", errors="ignore").strip()
    err = (stderr or b"").decode("utf-8", errors="ignore").strip()
    if proc.returncode != 0:
        if logger is not None:
            logger.warning(
                "qq wechat guard non-zero: rc={} cmd={} err={}",
                proc.returncode,
                " ".join(cmd),
                err,
            )
        return None
    if not out:
        if logger is not None:
            logger.warning("qq wechat guard empty output: {}", " ".join(cmd))
        return None
    try:
        return json.loads(out)
    except Exception:
        if logger is not None:
            logger.warning("qq wechat guard invalid json: cmd={} out_head={}", " ".join(cmd), out[:200])
        return None


async def run_yage_signed(
    session: aiohttp.ClientSession | None,
    *,
    timeout_sec: float = 45.0,
    nth: int | None = None,
    target_date: str | None = None,
    force_latest: bool = False,
    logger: Any | None = None,
) -> str | None:
    """Return a signed Yage article payload, falling back to the legacy skill."""
    rust_payload = await rss_sidecar.yage_signed(
        session,
        timeout_sec=timeout_sec,
        nth=nth,
        target_date=target_date,
        force_latest=force_latest,
        logger=logger,
    )
    if rust_payload is not None:
        return rust_payload

    args: list[str] = []
    if force_latest:
        args.append("--latest")
    if nth and nth > 1:
        args.extend(["--nth", str(nth)])
    if target_date:
        args.extend(["--date", target_date])
    arg_str = " ".join(args).strip()
    cmd = "cd /root/.nanobot/workspace/skills/news-curator && python3 yage_check.py"
    if arg_str:
        cmd = f"{cmd} {arg_str}"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        if proc.returncode != 0:
            if logger is not None:
                logger.warning(
                    "yage latest script failed rc={} err={}",
                    proc.returncode,
                    (stderr or b"").decode("utf-8", "ignore")[:500],
                )
            return None
        return (stdout or b"").decode("utf-8", "ignore")
    except Exception as e:
        if logger is not None:
            logger.warning("yage latest script execution failed: {}", e)
        return None


async def run_wechat_signed(
    session: aiohttp.ClientSession | None,
    subscription_id: int,
    *,
    timeout_sec: float = 45.0,
    force: bool = True,
    logger: Any | None = None,
) -> str | None:
    """Return a signed WeChat article payload, falling back to the legacy skill."""
    if subscription_id <= 0:
        return None
    rust_payload = await rss_sidecar.wechat_signed(
        session,
        subscription_id,
        timeout_sec=timeout_sec,
        force=force,
        logger=logger,
    )
    if rust_payload is not None:
        return rust_payload

    cmd = (
        "cd /root/.nanobot/workspace/skills/wechat-rss-sidecar "
        "&& WECHAT_RSS_BASE_URL=http://wechat-rss-sidecar:8091 "
        f"python3 wechat_push.py --subscription-id {subscription_id}"
    )
    if force:
        cmd += " --force"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        if proc.returncode != 0:
            if logger is not None:
                logger.warning(
                    "wechat signed script failed rc={} sub={} err={}",
                    proc.returncode,
                    subscription_id,
                    (stderr or b"").decode("utf-8", "ignore")[:500],
                )
            return None
        return (stdout or b"").decode("utf-8", "ignore")
    except Exception as e:
        if logger is not None:
            logger.warning("wechat signed script execution failed sub={} err={}", subscription_id, e)
        return None


__all__ = ["run_sidecar_json", "run_wechat_signed", "run_yage_signed"]
