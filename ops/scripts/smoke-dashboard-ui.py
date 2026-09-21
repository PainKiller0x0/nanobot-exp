#!/usr/bin/env python3
"""Lightweight UI/API audit for the Nanobot gateway.

This is intentionally browser-free and token-free. It catches the regressions we
keep seeing in sidecar pages: missing key cards, mojibake, broken gateway paths,
and API fields that the dashboard depends on.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from smoke_common import CheckResult as Result, add_result as add, get_simple, short

BASE = "http://127.0.0.1:8093"


def fetch_text(path: str, timeout: float = 12.0) -> tuple[int, str, float]:
    started = time.time()
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "nanobot-ui-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, text, time.time() - started
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, text, time.time() - started
    except Exception as exc:
        return 0, str(exc), time.time() - started


def inline_script_errors(name: str, text: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        return []
    errors: list[str] = []
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", text, flags=re.S | re.I)
    for idx, script in enumerate(scripts):
        if not script.strip():
            continue
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=f"-{name}-{idx}.js", delete=False) as fh:
            fh.write(script)
            script_path = fh.name
        proc = subprocess.run([node, "--check", script_path], text=True, capture_output=True, timeout=10)
        Path(script_path).unlink(missing_ok=True)
        if proc.returncode != 0:
            errors.append(f"script{idx}:{short(proc.stderr or proc.stdout, 120)}")
    return errors


def check_page(results: list[Result], name: str, path: str, required: list[str]) -> None:
    status, text, elapsed = fetch_text(path)
    missing = [item for item in required if item not in text]
    mojibake = "????" in text or "锟" in text
    js_errors = inline_script_errors(name, text) if 200 <= status < 300 else []
    ok = 200 <= status < 300 and not missing and not mojibake and not js_errors
    detail = f"http={status} {elapsed:.2f}s"
    if missing:
        detail += " missing=" + ",".join(missing[:4])
    if mojibake:
        detail += " mojibake=true"
    if js_errors:
        detail += " js=" + ";".join(js_errors[:2])
    add(results, name, ok, detail)


def main() -> int:
    results: list[Result] = []

    pages = [
        ("ui.dashboard", "/", ["todayBrief", "lofRadar", "今天真正需要处理的 3 件事", "投资信号", "infoGrid", "opsMiniGrid"]),
        ("ui.today", "/today", ["todaySummary", "sourceCosts", "recent_runs", "今天真正需要处理的 3 件事"]),
        ("ui.tasks", "/tasks", ["taskRows", "近7次运行", "recent_runs", "runTask"]),
        ("ui.model_routes", "/model-routes", ["sourceCosts", "来源消耗（本月）", "modelRows"]),
        ("ui.lof", "/lof", ["boardAutoRefresh", "BOARD_AUTO_REFRESH_MS=30000", "manualBoardRefresh"]),
        ("ui.workbench", "/workbench", ["内容工作台", "RSS", "收件箱"]),
        ("ui.sidecars", "/sidecars", ["abilityGrid", "notifyModal", "openNotifyJobs"]),
    ]
    for name, path, required in pages:
        check_page(results, name, path, required)

    status, data, dt = get_simple(BASE + "/api/today")
    actions = data.get("actions", []) if isinstance(data, dict) else []
    add(results, "api.today.actions", status == 200 and 0 < len(actions) <= 3,
        f"http={status} actions={len(actions) if isinstance(actions, list) else '-'} {dt:.2f}s {short(actions)}")

    status, data, dt = get_simple(BASE + "/api/task-trace")
    jobs = data.get("items", []) if isinstance(data, dict) else []
    has_history_key = any("recent_runs" in job for job in jobs) if isinstance(jobs, list) else False
    add(results, "api.tasks.history", status == 200 and data.get("history_ready") is True and has_history_key,
        f"http={status} jobs={len(jobs) if isinstance(jobs, list) else '-'} history_key={has_history_key} {dt:.2f}s")

    status, data, dt = get_simple(BASE + "/api/model-routes")
    source_costs = data.get("source_costs", []) if isinstance(data, dict) else []
    add(results, "api.model.source_costs", status == 200 and isinstance(source_costs, list),
        f"http={status} sources={len(source_costs) if isinstance(source_costs, list) else '-'} {dt:.2f}s")

    print("Nanobot dashboard UI smoke")
    failed = 0
    for item in results:
        marker = "OK" if item.ok else "FAIL"
        print(f"[{marker}] {item.name}: {item.detail}")
        if not item.ok:
            failed += 1
    if failed:
        print(f"failed={failed}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
