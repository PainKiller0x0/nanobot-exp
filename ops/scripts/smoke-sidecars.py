#!/usr/bin/env python3
import argparse
import sys

from smoke_common import (
    CheckResult as Result,
    add_result as add,
    get_simple as get,
    post_simple as post,
    run_command as command,
    short,
)

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
        ("memory.health", "http://127.0.0.1:8105/health"),
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

    rc, output, dt = command(["/root/nanobot/ops/scripts/smoke-dashboard-ui.py"], timeout=30)
    add(results, "dashboard.ui_audit", rc == 0, f"rc={rc} {dt:.2f}s {short(output)}")

    print("Nanobot sidecar smoke")
    failed = 0
    optional_failed = 0
    optional = {"qq.health"}
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