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
import re
import shutil
import signal
import subprocess
import time
import urllib.parse
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


def cdp_json(path: str, *, method: str = "GET") -> dict:
    req = urllib.request.Request(f"{CDP_URL}{path}", method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


class CdpSession:
    def __init__(self, ws_url: str):
        import websocket  # type: ignore

        self.ws = websocket.create_connection(ws_url, timeout=1, suppress_origin=True)
        self.next_id = 1
        self.events: list[dict] = []

    def call(self, method: str, params: dict | None = None, *, timeout: float = 5.0) -> dict:
        call_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in message:
                self.events.append(message)
                continue
            if message.get("id") == call_id:
                return message
        raise TimeoutError(f"timeout waiting for CDP method {method}")

    def pump(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in message:
                self.events.append(message)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def feishu_doc_id(url: str) -> str | None:
    match = re.search(r"/docx/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def block_text(block: dict) -> str:
    data = block.get("data") if isinstance(block.get("data"), dict) else {}
    text = data.get("text") if isinstance(data.get("text"), dict) else {}
    initial = text.get("initialAttributedTexts") if isinstance(text.get("initialAttributedTexts"), dict) else {}
    pieces = initial.get("text") if isinstance(initial.get("text"), dict) else {}
    if not pieces:
        return ""

    def sort_key(key: object) -> tuple[int, str]:
        raw = str(key)
        return (int(raw), raw) if raw.isdigit() else (10_000, raw)

    return "".join(str(pieces[key]) for key in sorted(pieces.keys(), key=sort_key)).replace("\u200b", "").strip()


def extract_feishu_text_from_html(html: str, url: str, *, limit: int) -> tuple[str, str, int]:
    marker = re.search(
        r"clientVars:\s*Object\((\{.*?\})\)\s*\}\);\s*window\.docxSSREditable",
        html,
        re.S,
    )
    if not marker:
        raise ValueError("Feishu clientVars block was not found")
    payload = json.loads(marker.group(1))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return extract_feishu_text_from_data(data, url, limit=limit)


def extract_feishu_text_from_data(data: dict, url: str, *, limit: int) -> tuple[str, str, int]:
    block_map = data.get("block_map") if isinstance(data.get("block_map"), dict) else {}
    if not block_map:
        raise ValueError("Feishu block_map is empty")

    doc_id = feishu_doc_id(url) or str(data.get("id") or "")
    root = block_map.get(doc_id)
    if not isinstance(root, dict):
        root = next(
            (
                block
                for block in block_map.values()
                if isinstance(block, dict)
                and isinstance(block.get("data"), dict)
                and block["data"].get("type") == "page"
            ),
            None,
        )
    if not isinstance(root, dict):
        raise ValueError("Feishu root page block was not found")

    title = block_text(root)
    lines: list[str] = []
    seen: set[str] = set()

    def append_line(line: str) -> None:
        line = re.sub(r"[ \t\r\f\v]+", " ", line or "").strip()
        if not line:
            return
        if line == title and not lines:
            lines.append(line)
            return
        if line in seen:
            return
        seen.add(line)
        lines.append(line)

    def walk(ids: list[str]) -> None:
        for block_id in ids:
            block = block_map.get(block_id)
            if not isinstance(block, dict):
                continue
            data = block.get("data") if isinstance(block.get("data"), dict) else {}
            text = block_text(block)
            block_type = str(data.get("type") or "")
            if text:
                if block_type == "heading1":
                    append_line(f"## {text}")
                elif block_type == "heading2":
                    append_line(f"### {text}")
                elif block_type == "heading3":
                    append_line(f"#### {text}")
                elif block_type in {"bullet", "bullet_list"}:
                    append_line(f"- {text}")
                elif block_type in {"ordered", "ordered_list"}:
                    append_line(f"1. {text}")
                else:
                    append_line(text)
            children = data.get("children")
            if isinstance(children, list):
                walk([str(child) for child in children])

    append_line(title)
    root_data = root.get("data") if isinstance(root.get("data"), dict) else {}
    children = root_data.get("children") if isinstance(root_data.get("children"), list) else []
    walk([str(child) for child in children])
    text = "\n".join(lines).strip()
    return title, text[:limit], len(block_map)


def merge_feishu_client_vars(base: dict, page: dict) -> None:
    block_map = page.get("block_map") if isinstance(page.get("block_map"), dict) else {}
    if block_map:
        target = base.setdefault("block_map", {})
        if isinstance(target, dict):
            target.update(block_map)
    sequence = page.get("block_sequence") if isinstance(page.get("block_sequence"), list) else []
    if sequence:
        target_sequence = base.setdefault("block_sequence", [])
        if isinstance(target_sequence, list):
            seen = set(str(item) for item in target_sequence)
            target_sequence.extend(str(item) for item in sequence if str(item) not in seen)


def extract_feishu_data_from_html(html: str) -> dict:
    marker = re.search(
        r"clientVars:\s*Object\((\{.*?\})\)\s*\}\);\s*window\.docxSSREditable",
        html,
        re.S,
    )
    if not marker:
        raise ValueError("Feishu clientVars block was not found")
    payload = json.loads(marker.group(1))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        raise ValueError("Feishu clientVars data is empty")
    return data


def cdp_eval_value(session: CdpSession, expression: str, *, timeout: float = 20.0) -> object:
    result = session.call(
        "Runtime.evaluate",
        {"expression": expression, "awaitPromise": True, "returnByValue": True},
        timeout=timeout,
    )
    return result.get("result", {}).get("result", {}).get("value")


def fetch_feishu_client_vars_page(session: CdpSession, doc_id: str, cursor: str, *, limit: int = 200) -> dict:
    path = (
        "/space/api/docx/pages/client_vars"
        f"?id={urllib.parse.quote(doc_id, safe='')}"
        f"&mode=7&limit={limit}"
        f"&cursor={urllib.parse.quote(cursor, safe='')}"
    )
    expression = f"""
(async () => {{
  const response = await fetch({json.dumps(path)}, {{ credentials: 'include' }});
  return await response.text();
}})()
"""
    raw = cdp_eval_value(session, expression, timeout=30)
    payload = json.loads(str(raw or "{}"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        raise ValueError(f"Feishu client_vars returned no data: {str(raw)[:180]}")
    return data


def root_children_missing(data: dict, url: str) -> list[str]:
    block_map = data.get("block_map") if isinstance(data.get("block_map"), dict) else {}
    doc_id = feishu_doc_id(url) or str(data.get("id") or "")
    root = block_map.get(doc_id)
    if not isinstance(root, dict):
        return []
    root_data = root.get("data") if isinstance(root.get("data"), dict) else {}
    children = root_data.get("children") if isinstance(root_data.get("children"), list) else []
    return [str(child) for child in children if str(child) not in block_map]


def cdp_new_target() -> dict:
    quoted = urllib.parse.quote("about:blank", safe="")
    try:
        return cdp_json(f"/json/new?{quoted}", method="PUT")
    except Exception:
        return cdp_json(f"/json/new?{quoted}")


def close_cdp_target(target_id: str | None) -> None:
    if not target_id:
        return
    try:
        cdp_json(f"/json/close/{target_id}")
    except Exception:
        pass


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


def cmd_deep_text(args: argparse.Namespace) -> int:
    limit = max(1000, int(args.limit))
    scrolls = max(1, int(args.scrolls))
    delay_ms = max(100, int(args.delay_ms))
    js = f"""
(async () => {{
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (text) => (text || '').replace(/\\u200b/g, '').trim();
  const snapshots = [];
  const addSnapshot = () => {{
    const text = normalize(document.body ? document.body.innerText : '');
    if (text && !snapshots.includes(text)) {{
      snapshots.push(text);
    }}
  }};
  const scrollTargets = () => {{
    const nodes = Array.from(document.querySelectorAll('*'))
      .filter((node) => {{
        const style = window.getComputedStyle(node);
        const overflow = `${{style.overflowY}} ${{style.overflow}}`;
        return node.scrollHeight > node.clientHeight + 40 && /(auto|scroll)/.test(overflow);
      }})
      .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))
      .slice(0, 8);
    const root = document.scrollingElement || document.documentElement;
    return [root, ...nodes].filter(Boolean);
  }};
  addSnapshot();
  for (let i = 0; i < {scrolls}; i += 1) {{
    const amount = Math.max(320, Math.floor(window.innerHeight * 0.85));
    window.scrollBy(0, amount);
    for (const target of scrollTargets()) {{
      target.scrollTop = Math.min(target.scrollTop + amount, target.scrollHeight);
      target.dispatchEvent(new Event('scroll', {{ bubbles: true }}));
    }}
    await sleep({delay_ms});
    addSnapshot();
    const height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const rootDone = window.scrollY + window.innerHeight >= height - 8;
    const targetsDone = scrollTargets().every((target) => target.scrollTop + target.clientHeight >= target.scrollHeight - 8);
    if (rootDone && targetsDone) {{
      break;
    }}
  }}
  const merged = [];
  for (const snapshot of snapshots) {{
    for (const rawLine of snapshot.split(/\\n+/)) {{
      const line = normalize(rawLine);
      if (!line) {{
        continue;
      }}
      if (merged[merged.length - 1] !== line && !merged.includes(line)) {{
        merged.push(line);
      }}
    }}
  }}
  return merged.join('\\n').slice(0, {limit});
}})()
"""
    return emit(page_flow(
        args,
        lambda: run_bb(["eval", js], timeout=args.timeout, output_limit=args.output_limit),
        "result",
    ))


def cmd_feishu_text(args: argparse.Namespace) -> int:
    if not feishu_doc_id(args.url):
        return emit({"ok": False, "exit_code": 2, "error": "Only Feishu docx URLs are supported by feishu-text", "url": args.url})

    state = ensure_browser()
    if not state.get("ok"):
        return emit({"ok": False, "exit_code": 127, "error": state.get("error"), "browser": state})

    target = None
    session = None
    try:
        target = cdp_new_target()
        session = CdpSession(target["webSocketDebuggerUrl"])
        session.call("Page.enable")
        session.call("Runtime.enable")
        session.call("Network.enable", {"maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 50_000_000})
        session.call("Page.navigate", {"url": args.url})
        session.pump(max(2.0, args.wait_ms / 1000))

        doc_id = feishu_doc_id(args.url) or ""
        request_id = None
        for event in session.events:
            if event.get("method") != "Network.responseReceived":
                continue
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            response = params.get("response") if isinstance(params.get("response"), dict) else {}
            response_url = str(response.get("url") or "")
            if (
                doc_id in response_url
                and "text/html" in str(response.get("mimeType") or "")
                and int(response.get("status") or 0) < 400
            ):
                request_id = params.get("requestId")
                break
        if not request_id:
            return emit({"ok": False, "exit_code": 1, "error": "Feishu document HTML response was not captured", "url": args.url})

        body_result = session.call("Network.getResponseBody", {"requestId": request_id}, timeout=10)
        body = body_result.get("result", {}).get("body", "")
        data = extract_feishu_data_from_html(str(body))
        doc_id = feishu_doc_id(args.url) or str(data.get("id") or "")
        cursors: list[str] = []
        if data.get("has_more") and data.get("cursor"):
            cursors.append(str(data.get("cursor")))
        next_cursors = data.get("next_cursors")
        if isinstance(next_cursors, list):
            cursors.extend(str(cursor) for cursor in next_cursors if cursor)

        seen_cursors: set[str] = set()
        pages_fetched = 0
        while cursors and pages_fetched < 12 and root_children_missing(data, args.url):
            cursor = cursors.pop(0)
            if not cursor or cursor in seen_cursors:
                continue
            seen_cursors.add(cursor)
            page_data = fetch_feishu_client_vars_page(session, doc_id, cursor)
            pages_fetched += 1
            merge_feishu_client_vars(data, page_data)
            if page_data.get("has_more") and page_data.get("cursor"):
                cursors.append(str(page_data.get("cursor")))
            page_next_cursors = page_data.get("next_cursors")
            if isinstance(page_next_cursors, list):
                cursors.extend(str(item) for item in page_next_cursors if item)

        title, text, blocks = extract_feishu_text_from_data(data, args.url, limit=max(1000, int(args.limit)))
        return emit({
            "ok": True,
            "exit_code": 0,
            "url": args.url,
            "title": title,
            "blocks": blocks,
            "pages_fetched": pages_fetched,
            "missing_blocks": len(root_children_missing(data, args.url)),
            "chars": len(text),
            "result": {"stdout": text, "stderr": ""},
            "truncated": len(text) >= max(1000, int(args.limit)),
        })
    except Exception as exc:
        return emit({"ok": False, "exit_code": 1, "error": str(exc), "url": args.url})
    finally:
        if session is not None:
            session.close()
        close_cdp_target(target.get("id") if isinstance(target, dict) else None)
        if not args.keep_browser:
            kill_managed_browser()


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

    p = sub.add_parser("deep-text", help="open a URL, scroll, extract rendered body text, close tab")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=24000)
    p.add_argument("--scrolls", type=int, default=18)
    p.add_argument("--delay-ms", type=int, default=450)
    p.add_argument("--wait-ms", type=int, default=5000)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--output-limit", type=int, default=DEFAULT_OUTPUT_LIMIT)
    p.add_argument("--keep-browser", action="store_true")
    p.set_defaults(func=cmd_deep_text)

    p = sub.add_parser("feishu-text", help="extract full text from public Feishu docx bootstrap data")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=60000)
    p.add_argument("--wait-ms", type=int, default=8000)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--output-limit", type=int, default=DEFAULT_OUTPUT_LIMIT)
    p.add_argument("--keep-browser", action="store_true")
    p.set_defaults(func=cmd_feishu_text)

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
