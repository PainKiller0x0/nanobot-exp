#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parents[1] / "_shared"
if _SHARED_DIR.exists():
    sys.path.insert(0, str(_SHARED_DIR))

from ops_common import format_article_push_body, load_json_dict, sign_nbraw_sha256  # noqa: E402

BASE_DIR = "/root/.nanobot/workspace/skills/wechat-rss-sidecar"
CLIENT_PATH = f"{BASE_DIR}/client.py"
CACHE_FILE = f"{BASE_DIR}/wechat_push_cache.json"


def _run_latest(
    days: int,
    limit: int,
    subscription_id: int,
    refresh: bool,
    sample_fetches: int,
    sample_interval: float,
) -> dict | None:
    cmd: list[str] = [
        "python3",
        CLIENT_PATH,
        "latest",
        "--days",
        str(days),
        "--limit",
        str(limit),
        "--sample-fetches",
        str(sample_fetches),
        "--sample-interval",
        str(sample_interval),
    ]
    if subscription_id > 0:
        cmd.extend(["--subscription-id", str(subscription_id)])
    if refresh:
        cmd.append("--refresh")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads((proc.stdout or "").strip())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_ack_marker(subscription_id: int, entry_id: int) -> str:
    # Machine-only marker, stripped by QQ channel before user-visible delivery.
    return f"<!-- NBACK_WECHAT sub:{subscription_id} entry:{entry_id} -->"


def _positive_int(value: int | None, default: int, minimum: int = 1) -> int:
    return max(minimum, int(value or default))


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--subscription-id", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sample-fetches", type=int, default=3)
    parser.add_argument("--sample-interval", type=float, default=0.6)
    parser.add_argument("--force", action="store_true")
    args, _ = parser.parse_known_args(sys.argv[1:])

    subscription_id = _positive_int(args.subscription_id, 0, minimum=0)
    latest = _run_latest(
        days=_positive_int(args.days, 7),
        limit=_positive_int(args.limit, 50),
        subscription_id=subscription_id,
        refresh=bool(args.refresh),
        sample_fetches=_positive_int(args.sample_fetches, 3),
        sample_interval=float(args.sample_interval or 0.6),
    )
    if not latest or str(latest.get("status") or "") != "ok":
        return

    entry_id = int(latest.get("entry_id") or 0)
    if entry_id <= 0:
        return

    cache_key = f"sub:{subscription_id}"
    if (not args.force) and int(load_json_dict(CACHE_FILE).get(cache_key, 0) or 0) == entry_id:
        return

    body = format_article_push_body(latest)
    if not body:
        return

    # Cache is acknowledged only after QQ send succeeds (handled in qq.py),
    # preventing "cache advanced but message not delivered".
    body = f"{body}\n\n{_build_ack_marker(subscription_id, entry_id)}".strip()
    sys.stdout.write(sign_nbraw_sha256(body))


if __name__ == "__main__":
    main()
