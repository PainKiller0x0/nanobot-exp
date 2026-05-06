#!/usr/bin/env python3
"""On-demand bb-browser wrapper for nanobot.

The wrapper keeps browser automation explicit and short-lived. It starts a
managed Chromium only when a command needs CDP, and cleanup removes both the
Chromium tree and bb-browser's Node daemon.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_TIMEOUT = 90
DEFAULT_OUTPUT_LIMIT = 24000
CHROME_BINS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
CDP_HOST = os.environ.get("BB_BROWSER_CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("BB_BROWSER_CDP_PORT", "19825"))
CDP_URL = os.environ.get("BB_BROWSER_CDP_URL", f"http://{CDP_HOST}:{CDP_PORT}")
PROFILE_DIR = Path(os.environ.get("BB_BROWSER_PROFILE", str(Path.home() / ".bb-browser/browser"))).expanduser()
CHROMIUM_LOG = Path(os.environ.get("BB_BROWSER_CHROMIUM_LOG", "/tmp/bb-browser-chromium.log"))
PROC_MARKERS = (
    ".bb-browser/browser",
    f"--remote-debugging-port={CDP_PORT}",
    "bb-browser/dist/daemon.js",
    "/node_modules/bb-browser/dist/daemon.js",
    f"--cdp-port {CDP_PORT}",
)
NO_BROWSER_COMMANDS = {"--help", "help", "version", "--version", "close"}


def which(name: str) -> str | None:
    return shutil.which(name)


def first_bin(names: Iterable[str]) -> str | None:
    return next((found for name in names if (found := which(name))), None)


def bb_command() -> list[str] | None:
    if override := os.environ.get("BB_BROWSER_BIN", "").strip():
        return [override]
    if direct := which("bb-browser"):
        return [direct]
    if npx := which("npx"):
        return [npx, "-y", "bb-browser"]
    return None


def chrome_binary() -> str | None:
    return first_bin(CHROME_BINS)


def cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def managed_pids() -> list[int]:
    proc = Path("/proc")
    if not proc.exists():
        return []
    pids: set[int] = set()
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            cmdline = (item / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except Exception:
            continue
        if any(marker in cmdline for marker in PROC_MARKERS):
            pids.add(int(item.name))
    return sorted(pids)


def kill_managed_browser(grace: float = 2.0) -> list[int]:
    killed: set[int] = set(managed_pids())
    for sig, delay in ((signal.SIGTERM, grace), (signal.SIGKILL, 0.0)):
        for pid in managed_pids():
            killed.add(pid)
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if delay and killed:
            time.sleep(delay)
    return sorted(killed)


def emit(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return 0 if obj.get("ok") else int(obj.get("exit_code", 1))


def limited(text: str | bytes | None, limit: int) -> tuple[str, bool]:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = text or ""
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]", True


def ensure_browser() -> dict:
    if cdp_alive():
        return {"ok": True, "cdp_url": CDP_URL, "started": False, "pids": managed_pids()}
    browser = chrome_binary()
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
        f"--remote-debugging-address={CDP_HOST}",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "about:blank",
    ]
    with CHROMIUM_LOG.open("ab") as log:
        subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)

    for _ in range(40):
        if cdp_alive():
            return {"ok": True, "cdp_url": CDP_URL, "started": True, "pids": managed_pids()}
        time.sleep(0.25)
    return {
        "ok": False,
        "error": "Chromium did not expose CDP in time",
        "cdp_url": CDP_URL,
        "log": str(CHROMIUM_LOG),
        "pids": managed_pids(),
    }


def needs_browser(args: list[str]) -> bool:
    return bool(args) and args[0] not in NO_BROWSER_COMMANDS


def normalize_args(args: Iterable[str]) -> list[str]:
    arg_list = list(args)
    if arg_list[:1] == ["--"]:
        return arg_list[1:]
    return arg_list


def run_bb(
    args: Iterable[str],
    *,
    timeout: int,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    ensure: bool | None = None,
) -> dict:
    cmd = bb_command()
    if not cmd:
        return {
            "ok": False,
            "exit_code": 127,
            "error": "bb-browser/npx not found. Run setup_bb_browser.sh first.",
            "missing": [name for name in ("node", "npm", "npx", "bb-browser") if not which(name)],
        }

    arg_list = normalize_args(args)
    if arg_list[:1] == ["close"] and not cdp_alive():
        return {"ok": True, "exit_code": 0, "command": cmd + arg_list, "stdout": "No managed browser is alive.\n", "stderr": "", "truncated": False}
    if ensure if ensure is not None else needs_browser(arg_list):
        state = ensure_browser()
        if not state.get("ok"):
            return {"ok": False, "exit_code": 127, "error": state.get("error"), "browser": state}

    env = os.environ.copy()
    env.setdefault("BB_BROWSER_CDP_URL", CDP_URL)
    full_cmd = cmd + arg_list
    try:
        completed = subprocess.run(full_cmd, text=True, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        stdout, out_cut = limited(exc.stdout, output_limit)
        stderr, err_cut = limited(exc.stderr, output_limit)
        return {
            "ok": False,
            "exit_code": 124,
            "timeout": timeout,
            "command": full_cmd,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_cut or err_cut,
            "error": "bb-browser command timed out",
        }

    stdout, out_cut = limited(completed.stdout, output_limit)
    stderr, err_cut = limited(completed.stderr, output_limit)
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command": full_cmd,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": out_cut or err_cut,
    }


def page_flow(args: argparse.Namespace, action: Callable[[], dict], result_key: str, extra: dict | None = None) -> dict:
    opened = run_bb(["open", args.url], timeout=args.timeout)
    waited = run_bb(["wait", str(args.wait_ms)], timeout=min(15, args.timeout)) if opened.get("ok") else None
    result = action() if opened.get("ok") else opened
    closed = run_bb(["close"], timeout=15, ensure=False) if opened.get("ok") else None
    killed = [] if args.keep_browser else kill_managed_browser()
    payload = {"ok": bool(result.get("ok")), "url": args.url, "open": opened, "wait": waited, result_key: result, "close": closed, "killed_pids": killed}
    if extra:
        payload.update(extra)
    return payload


def cmd_check(_: argparse.Namespace) -> int:
    cmd = bb_command()
    return emit({
        "ok": bool(cmd and chrome_binary()),
        "node": which("node"),
        "npm": which("npm"),
        "npx": which("npx"),
        "bb_browser": which("bb-browser"),
        "resolved_command": cmd,
        "chrome": chrome_binary(),
        "cdp_url": CDP_URL,
        "cdp_alive": cdp_alive(),
        "managed_browser_pids": managed_pids(),
        "profile": str(PROFILE_DIR),
        "chromium_log": str(CHROMIUM_LOG),
        "notes": "Dependencies can be installed with setup_bb_browser.sh; browser is started only on demand.",
    })


def cmd_cleanup(args: argparse.Namespace) -> int:
    return emit({"ok": True, "killed_pids": kill_managed_browser(grace=args.grace), "remaining_pids": managed_pids()})


def cmd_run(args: argparse.Namespace) -> int:
    if not args.bb_args:
        return emit({"ok": False, "exit_code": 2, "error": "missing bb-browser args after --"})
    result = run_bb(args.bb_args, timeout=args.timeout, output_limit=args.output_limit)
    if args.kill_browser_after:
        result["killed_pids"] = kill_managed_browser()
    return emit(result)


def cmd_quick_text(args: argparse.Namespace) -> int:
    js = f"document.body ? document.body.innerText.substring(0, {int(args.limit)}) : ''"
    return emit(page_flow(
        args,
        lambda: run_bb(["eval", js], timeout=args.timeout, output_limit=args.output_limit),
        "result",
    ))


def cmd_screenshot(args: argparse.Namespace) -> int:
    output = str(Path(args.output).expanduser())
    return emit(page_flow(
        args,
        lambda: run_bb(["screenshot", output], timeout=args.timeout),
        "screenshot",
        {"output": output},
    ))


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
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
