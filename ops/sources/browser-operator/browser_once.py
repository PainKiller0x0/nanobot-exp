#!/usr/bin/env python3
"""On-demand bb-browser wrapper for nanobot.

This wrapper keeps browser automation explicit and short-lived. It never stores
secrets itself; bb-browser may persist login state in its own dedicated Chrome
profile under ~/.bb-browser/browser.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

DEFAULT_TIMEOUT = 90
DEFAULT_OUTPUT_LIMIT = 24000
CDP_HOST = os.environ.get("BB_BROWSER_CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("BB_BROWSER_CDP_PORT", "19825"))
CDP_URL = os.environ.get("BB_BROWSER_CDP_URL", f"http://{CDP_HOST}:{CDP_PORT}")
PROFILE_DIR = Path(os.environ.get("BB_BROWSER_PROFILE", str(Path.home() / ".bb-browser/browser"))).expanduser()
CHROMIUM_LOG = Path(os.environ.get("BB_BROWSER_CHROMIUM_LOG", "/tmp/bb-browser-chromium.log"))
BB_BROWSER_PROFILE_MARKERS = (
    ".bb-browser/browser",
    "--remote-debugging-port=19825",
    "--remote-debugging-port=" + str(CDP_PORT),
    "bb-browser/dist/daemon.js",
    "/node_modules/bb-browser/dist/daemon.js",
    "--cdp-port " + str(CDP_PORT),
)


def which(name: str) -> str | None:
    return shutil.which(name)


def bb_command() -> list[str] | None:
    override = os.environ.get("BB_BROWSER_BIN", "").strip()
    if override:
        return [override]
    direct = which("bb-browser")
    if direct:
        return [direct]
    npx = which("npx")
    if npx:
        return [npx, "-y", "bb-browser"]
    return None


def detect_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = which(name)
        if found:
            return found
    return None


def cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def chromium_binary() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = which(name)
        if found:
            return found
    return None


def ensure_managed_browser() -> dict:
    if cdp_alive():
        return {"ok": True, "cdp_url": CDP_URL, "started": False, "pids": managed_browser_pids()}
    browser = chromium_binary()
    if not browser:
        return {"ok": False, "error": "No Chromium-based browser found", "cdp_url": CDP_URL}
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    CHROMIUM_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        browser,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-background-networking",
        "--remote-debugging-address=" + CDP_HOST,
        "--remote-debugging-port=" + str(CDP_PORT),
        "--user-data-dir=" + str(PROFILE_DIR),
        "about:blank",
    ]
    log = CHROMIUM_LOG.open("ab")
    subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        if cdp_alive():
            return {"ok": True, "cdp_url": CDP_URL, "started": True, "pids": managed_browser_pids()}
        time.sleep(0.25)
    return {
        "ok": False,
        "error": "Chromium did not expose CDP in time",
        "cdp_url": CDP_URL,
        "log": str(CHROMIUM_LOG),
        "pids": managed_browser_pids(),
    }


def managed_browser_pids() -> list[int]:
    pids: list[int] = []
    proc = Path("/proc")
    if not proc.exists():
        return pids
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            raw = (item / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except Exception:
            continue
        if any(marker in raw for marker in BB_BROWSER_PROFILE_MARKERS):
            pids.append(int(item.name))
    return sorted(set(pids))


def kill_managed_browser(grace: float = 2.0) -> list[int]:
    pids = managed_browser_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    if pids:
        time.sleep(grace)
    for pid in managed_browser_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    return pids


def emit(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return 0 if obj.get("ok", False) else int(obj.get("exit_code", 1))


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]", True


def run_bb(args: Iterable[str], timeout: int, output_limit: int = DEFAULT_OUTPUT_LIMIT) -> dict:
    cmd = bb_command()
    if not cmd:
        return {
            "ok": False,
            "exit_code": 127,
            "error": "bb-browser/npx not found. Run setup_bb_browser.sh first.",
            "missing": [name for name in ("node", "npm", "npx", "bb-browser") if not which(name)],
        }
    arg_list = list(args)
    browser_state = None
    if not (arg_list and arg_list[0] in {"--help", "help", "version", "--version"}):
        browser_state = ensure_managed_browser()
        if not browser_state.get("ok"):
            return {"ok": False, "exit_code": 127, "error": browser_state.get("error"), "browser": browser_state}
    full_cmd = cmd + arg_list
    env = os.environ.copy()
    env.setdefault("BB_BROWSER_CDP_URL", CDP_URL)
    try:
        completed = subprocess.run(
            full_cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        stdout, out_truncated = truncate(stdout, output_limit)
        stderr, err_truncated = truncate(stderr, output_limit)
        return {
            "ok": False,
            "exit_code": 124,
            "timeout": timeout,
            "command": full_cmd,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_truncated or err_truncated,
            "error": "bb-browser command timed out",
        }
    stdout, out_truncated = truncate(completed.stdout, output_limit)
    stderr, err_truncated = truncate(completed.stderr, output_limit)
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command": full_cmd,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": out_truncated or err_truncated,
    }


def cmd_check(_: argparse.Namespace) -> int:
    cmd = bb_command()
    return emit({
        "ok": bool(cmd and detect_chrome()),
        "node": which("node"),
        "npm": which("npm"),
        "npx": which("npx"),
        "bb_browser": which("bb-browser"),
        "resolved_command": cmd,
        "chrome": detect_chrome(),
        "cdp_url": CDP_URL,
        "cdp_alive": cdp_alive(),
        "managed_browser_pids": managed_browser_pids(),
        "profile": str(PROFILE_DIR),
        "chromium_log": str(CHROMIUM_LOG),
        "notes": "Dependencies can be installed with setup_bb_browser.sh; browser is started only on demand.",
    })


def cmd_cleanup(args: argparse.Namespace) -> int:
    killed = kill_managed_browser(grace=args.grace)
    return emit({"ok": True, "killed_pids": killed, "remaining_pids": managed_browser_pids()})


def cmd_run(args: argparse.Namespace) -> int:
    if not args.bb_args:
        return emit({"ok": False, "exit_code": 2, "error": "missing bb-browser args after --"})
    result = run_bb(args.bb_args, timeout=args.timeout, output_limit=args.output_limit)
    if args.kill_browser_after:
        result["killed_pids"] = kill_managed_browser()
    return emit(result)


def cmd_quick_text(args: argparse.Namespace) -> int:
    js = f"document.body ? document.body.innerText.substring(0, {int(args.limit)}) : ''"
    opened = run_bb(["open", args.url], timeout=args.timeout)
    waited = run_bb(["wait", str(args.wait_ms)], timeout=min(15, args.timeout)) if opened.get("ok") else None
    result = run_bb(["eval", js], timeout=args.timeout, output_limit=args.output_limit) if opened.get("ok") else opened
    closed = run_bb(["close"], timeout=15)
    killed: list[int] = []
    if not args.keep_browser:
        killed = kill_managed_browser()
    return emit({
        "ok": bool(result.get("ok")),
        "url": args.url,
        "open": opened,
        "wait": waited,
        "result": result,
        "close": closed,
        "killed_pids": killed,
    })


def cmd_screenshot(args: argparse.Namespace) -> int:
    out = str(Path(args.output).expanduser())
    opened = run_bb(["open", args.url], timeout=args.timeout)
    waited = run_bb(["wait", str(args.wait_ms)], timeout=min(15, args.timeout)) if opened.get("ok") else None
    shot = run_bb(["screenshot", out], timeout=args.timeout) if opened.get("ok") else opened
    closed = run_bb(["close"], timeout=15)
    killed: list[int] = []
    if not args.keep_browser:
        killed = kill_managed_browser()
    return emit({
        "ok": bool(shot.get("ok")),
        "url": args.url,
        "output": out,
        "open": opened,
        "wait": waited,
        "screenshot": shot,
        "close": closed,
        "killed_pids": killed,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="On-demand bb-browser wrapper for nanobot")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="check dependencies and managed browser processes")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("cleanup", help="kill bb-browser managed Chrome processes")
    p.add_argument("--grace", type=float, default=2.0)
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser("run", help="run one bb-browser command")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--output-limit", type=int, default=DEFAULT_OUTPUT_LIMIT)
    p.add_argument("--kill-browser-after", action="store_true")
    p.add_argument("bb_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("quick-text", help="open a URL, extract rendered body text, close tab")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=8000)
    p.add_argument("--wait-ms", type=int, default=2000)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--output-limit", type=int, default=DEFAULT_OUTPUT_LIMIT)
    p.add_argument("--keep-browser", action="store_true")
    p.set_defaults(func=cmd_quick_text)

    p = sub.add_parser("screenshot", help="open a URL, save screenshot, close tab")
    p.add_argument("url")
    p.add_argument("output")
    p.add_argument("--wait-ms", type=int, default=2000)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--keep-browser", action="store_true")
    p.set_defaults(func=cmd_screenshot)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
