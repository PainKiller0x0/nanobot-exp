#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


def http(method: str, url: str, body: Any = None, timeout: float = 12.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            parsed = parse_json(text)
            return resp.status, parsed, time.time() - started
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, parse_json(text), time.time() - started
    except Exception as exc:
        return 0, {"error": str(exc)}, time.time() - started


def parse_json(text: str):
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:500]}


def short(value: Any, limit: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text[:limit] + ("..." if len(text) > limit else "")


def add(results: list[Result], name: str, ok: bool, detail: str):
    results.append(Result(name, ok, detail))


def get(url: str, timeout: float = 12.0):
    return http("GET", url, timeout=timeout)


def post(url: str, body: Any, timeout: float = 45.0):
    return http("POST", url, body=body, timeout=timeout)


def command(args: list[str], timeout: float = 20.0):
    started = time.time()
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip(), time.time() - started
    except Exception as exc:
        return 99, str(exc), time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test nanobot-exp local sidecars without spending LLM tokens.")
    parser.add_argument("--refresh-lof", action="store_true", help="Trigger one LOF refresh before status check.")
    parser.add_argument("--strict", action="store_true", help="Fail when optional services are degraded.")
    args = parser.parse_args()

    results: list[Result] = []

    checks = [
        ("nanobot.health", "http://127.0.0.1:8080/health"),
        ("lof.health", "http://127.0.0.1:8093/health"),
        ("rss.root", "http://127.0.0.1:8091/"),
        ("rss.cleaner", "http://127.0.0.1:8091/rss/cleaner"),
        ("notify.health", "http://127.0.0.1:8094/health"),
        ("trend.health", "http://127.0.0.1:8095/health"),
        ("reflexio.health", "http://127.0.0.1:8081/health"),
        ("obp.root", "http://127.0.0.1:8000/"),
        ("qq.health", "http://172.17.0.1:8092/health"),
    ]
    for name, url in checks:
        status, data, dt = get(url)
        add(results, name, 200 <= status < 300, f"http={status} {dt:.2f}s {short(data)}")

    status, data, dt = get("http://127.0.0.1:8093/api/sidecars")
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    add(results, "manager.sidecars", status == 200 and summary.get("unhealthy", 1) == 0,
        f"http={status} healthy={summary.get('healthy')}/{summary.get('total')} unhealthy={summary.get('unhealthy')} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8093/api/capabilities")
    caps = data.get("items", []) if isinstance(data, dict) else []
    add(results, "manager.capabilities", status == 200 and len(caps) > 0,
        f"http={status} count={len(caps)} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8093/api/system")
    mem = data.get("memory", {}) if isinstance(data, dict) else {}
    add(results, "dashboard.system", status == 200 and bool(mem),
        f"http={status} mem={mem.get('used_mb')}MB/{mem.get('total_mb')}MB {dt:.2f}s")

    if args.refresh_lof:
        status, data, dt = post("http://127.0.0.1:8093/api/run", {"tag": "smoke"}, timeout=80)
        add(results, "lof.refresh", status == 200 and isinstance(data, dict), f"http={status} {dt:.2f}s {short(data)}")
    status, data, dt = get("http://127.0.0.1:8093/api/status")
    add(results, "lof.status", status == 200 and isinstance(data, dict) and bool(data.get("last_run") or data.get("items") or data.get("funds")),
        f"http={status} keys={list(data.keys())[:8] if isinstance(data, dict) else '-'} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8091/api/subscriptions")
    subs = data.get("items", []) if isinstance(data, dict) else []
    add(results, "rss.subscriptions", status == 200 and len(subs) > 0, f"http={status} count={len(subs)} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8091/api/entries?days=7&limit=5")
    entries = data.get("items", []) if isinstance(data, dict) else []
    add(results, "rss.entries", status == 200 and len(entries) > 0, f"http={status} count={len(entries)} {dt:.2f}s")
    if entries:
        article_id = entries[0].get("id")
        status, data, dt = get(f"http://127.0.0.1:8091/api/articles/{article_id}")
        item = data.get("item", {}) if isinstance(data, dict) else {}
        md = item.get("article_markdown") or item.get("content_markdown") or ""
        add(results, "rss.article_markdown", status == 200 and len(md) > 20,
            f"http={status} article={article_id} chars={len(md)} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8091/api/auto-refresh-status")
    add(results, "rss.auto_refresh", status == 200 and isinstance(data, dict), f"http={status} {short(data)}")

    status, data, dt = get("http://127.0.0.1:8094/api/status")
    jobs = data.get("job_details") or data.get("configured_jobs") or [] if isinstance(data, dict) else []
    enabled = sum(1 for job in jobs if job.get("enabled")) if isinstance(jobs, list) else 0
    errors = sum(1 for job in jobs if (job.get("status") or {}).get("last_status") == "error") if isinstance(jobs, list) else 0
    add(results, "notify.jobs", status == 200 and enabled > 0 and errors == 0,
        f"http={status} jobs={len(jobs) if isinstance(jobs, list) else 0} enabled={enabled} errors={errors} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8095/api/trends/status")
    count = data.get("items_count") or data.get("cached_items") or 0 if isinstance(data, dict) else 0
    add(results, "trend.status", status == 200 and count > 0, f"http={status} items={count} {dt:.2f}s")

    status, data, dt = get("http://127.0.0.1:8095/api/mcp/tools")
    tools = data.get("tools", []) if isinstance(data, dict) else []
    add(results, "trend.mcp_tools", status == 200 and len(tools) > 0, f"http={status} tools={len(tools)} {dt:.2f}s")

    rc, output, dt = command(["/root/nanobot/ops/scripts/check-architecture.sh"], timeout=30)
    add(results, "architecture.check", rc == 0, f"rc={rc} {dt:.2f}s {short(output)}")

    print("Nanobot sidecar smoke")
    failed = 0
    optional_failed = 0
    optional = {"reflexio.health", "qq.health"}
    for item in results:
        marker = "OK" if item.ok else "FAIL"
        print(f"[{marker}] {item.name}: {item.detail}")
        if not item.ok:
            if item.name in optional and not args.strict:
                optional_failed += 1
            else:
                failed += 1
    if optional_failed:
        print(f"optional_failed={optional_failed}")
    if failed:
        print(f"failed={failed}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())