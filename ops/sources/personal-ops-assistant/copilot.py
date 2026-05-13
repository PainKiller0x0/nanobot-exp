#!/usr/bin/env python3
"""Personal copilot commands layered on top of ops_summary.py."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ops_summary import (  # noqa: E402
    JsonHttpClient,
    fetch_json,
    fmt_time,
    job_name,
    load_bundle,
    lof_rows,
    now_shanghai,
    num,
    pct,
    post_json,
    render_articles,
    render_decision,
    render_lof,
    render_system,
    render_tasks,
    service_name,
    short,
    source_name,
    status_text,
    top_lof_rows,
)

DATA_DIR = Path(os.environ.get("PERSONAL_OPS_DATA_DIR", "/root/.nanobot/data/personal-ops-assistant"))
DECISIONS = DATA_DIR / "decisions.jsonl"
OBP_HTTP = JsonHttpClient(
    [
        os.environ.get("OBP_ADMIN_URL", "").strip(),
        "http://127.0.0.1:8000",
        "http://172.17.0.1:8000",
    ],
    timeout=5,
)


def safe_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "entries", "data", "rows"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def parse_dt(value: Any):
    from ops_summary import parse_dt as _parse_dt

    return _parse_dt(value)


def metric_count(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    for key in ("requests", "request_count", "count", "total", "calls"):
        try:
            return int(float(value.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


def metric_cost(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    for key in ("cost_cny", "cost", "total_cost_cny", "total_cost"):
        try:
            return float(value.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def money(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{n:.4f} 元" if n < 0.01 else f"{n:.2f} 元"


def article_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "未命名文章")


def article_time(item: dict[str, Any]) -> Any:
    return item.get("published_at") or item.get("created_at") or item.get("updated_at")


def article_priority(item: dict[str, Any]) -> tuple[str, str]:
    title = article_title(item)
    src = source_name(item)
    text = f"{src} {title}".lower()
    if any(word in text for word in ("广告", "八段锦", "推广", "付费文章", "购买")):
        return "可跳过", "疑似广告/导流"
    if any(word in text for word in ("记忆承载", "记忆承载3", "鸭哥", "ai", "deepseek", "美国", "市场", "财富")):
        return "优先读", "与你近期关注相关"
    if any(word in text for word in ("周报", "每日", "趋势", "新闻")):
        return "稍后看", "适合扫读"
    return "稍后看", "常规更新"


def configured_jobs(notify: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = notify.get("job_details") or notify.get("configured_jobs") or []
    return [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []


def job_stamp(job: dict[str, Any]) -> Any:
    status = job.get("status") or {}
    return status.get("last_finished_at") or status.get("last_started_at")


def recent_jobs(notify: dict[str, Any], days: int = 1) -> list[dict[str, Any]]:
    cutoff = now_shanghai() - timedelta(days=days)
    rows = [job for job in configured_jobs(notify) if (parse_dt(job_stamp(job)) or cutoff) >= cutoff]
    return sorted(rows, key=lambda job: parse_dt(job_stamp(job)) or cutoff, reverse=True)


def job_errors(notify: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        job
        for job in configured_jobs(notify)
        if (job.get("status") or {}).get("last_status") in {"error", "timeout"}
    ]


def today_jobs(notify: dict[str, Any]) -> list[dict[str, Any]]:
    today = now_shanghai().date()
    return [job for job in configured_jobs(notify) if (parse_dt(job_stamp(job)) or now_shanghai()).date() == today]


def unhealthy_services(sidecars: dict[str, Any]) -> list[str]:
    return [service_name(item) for item in safe_items(sidecars) if not item.get("ok")]


def obp_recent_bad(row: dict[str, Any]) -> bool:
    status = row.get("status")
    if isinstance(status, int):
        return status >= 400
    if isinstance(status, str):
        lowered = status.lower()
        if lowered in {"", "ok", "success", "200"}:
            return False
        try:
            return int(lowered) >= 400
        except ValueError:
            return True
    return bool(row.get("error"))


def load_obp_stats() -> dict[str, Any]:
    direct = OBP_HTTP.get_json("/admin/stats", {})
    if isinstance(direct, dict) and direct:
        return direct
    direct = fetch_json("/obp/admin/stats", {})
    if isinstance(direct, dict) and direct:
        return direct
    return fetch_json("/obp/api/stats", {})


def month_stats(stats: dict[str, Any]) -> tuple[dict[str, Any], str]:
    month = now_shanghai().strftime("%Y-%m")
    by_month = stats.get("by_month") if isinstance(stats, dict) else {}
    row = by_month.get(month, {}) if isinstance(by_month, dict) else {}
    if not row and isinstance(stats.get("total"), dict):
        row = stats["total"]
    return row if isinstance(row, dict) else {}, month


def decisions(limit: int = 8, days: int | None = None) -> list[dict[str, Any]]:
    if not DECISIONS.exists():
        return []
    cutoff = now_shanghai() - timedelta(days=days or 3650)
    rows: list[dict[str, Any]] = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if parse_dt(item.get("created_at")) and parse_dt(item.get("created_at")) >= cutoff:
            rows.append(item)
    return rows[-limit:][::-1]


def record_decision(text: str, category: str) -> str:
    text = text.strip()
    if not text:
        return "没有拿到要记录的决策内容。用法：copilot.py remember-decision --text '...'"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    item = {"created_at": now_shanghai().isoformat(), "category": category or "general", "text": text}
    with DECISIONS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return f"已记录决策：{short(text, 72)}"


def render_menu() -> str:
    return "\n".join(
        [
            "🧭 Nanobot 个人副驾驶",
            "1. 今日情报官：问“今天有什么要看 / 今日简报”",
            "2. 阅读消化器：问“今天文章怎么读 / 哪篇值得看”",
            "3. 异常雷达：问“有没有异常 / 服务哪里不对”",
            "4. 成本守门员：问“OBP 花了多少钱 / 模型成本”",
            "5. 决策日志：说“记一条决策：...”或问“最近决策”",
            "6. 睡前收束：问“睡前总结 / 今天收束一下”",
            "7. 观点对撞：问“帮我反驳这篇 / 观点对撞 + 主题”",
            "8. 运维 Copilot：问“内存怎么样 / cron 怎么样 / LOF 怎么样”",
            "9. 自省周报：问“本周总结 / nanobot 进化了什么”",
            "10. 刷新动作：明确说“刷新 RSS”或“触发 LOF 刷新”才会执行",
            "",
            "默认只读，不会主动改配置、不重启服务、不补发消息。",
        ]
    )


def render_reading(data: dict[str, Any]) -> str:
    items = safe_items(data.get("articles") or {})
    groups: dict[str, list[str]] = {"优先读": [], "稍后看": [], "可跳过": []}
    for item in items:
        tag, reason = article_priority(item)
        groups.setdefault(tag, []).append(
            f"- [{source_name(item)}] {short(article_title(item), 40)}：{reason}"
        )
    lines = ["📚 阅读消化器", f"今日候选：{len(items)} 篇"]
    for tag in ("优先读", "稍后看", "可跳过"):
        lines.append(f"{tag}：")
        lines.extend(groups.get(tag, [])[:4] or ["暂无"])
    return "\n".join(lines)


def render_anomalies(data: dict[str, Any]) -> str:
    system = data.get("system") or {}
    sidecars = data.get("sidecars") or {}
    notify = data.get("notify") or {}
    stats = load_obp_stats()
    mem = system.get("memory") or {}
    findings: list[str] = []
    bad_services = unhealthy_services(sidecars)
    if bad_services:
        findings.append("服务异常：" + "、".join(bad_services[:6]))
    for job in job_errors(notify)[:6]:
        st = job.get("status") or {}
        findings.append(f"任务异常：{job_name(job)} {status_text(st.get('last_status'))} {short(st.get('last_error'), 34)}")
    if (num(mem.get("used_pct")) or 0) >= 75:
        findings.append(f"内存偏高：{mem.get('used_mb', '-')} MB（{mem.get('used_pct', '-')}%）")
    recent = stats.get("recent") if isinstance(stats, dict) else []
    if isinstance(recent, list):
        bad = [row for row in recent[:30] if isinstance(row, dict) and obp_recent_bad(row)]
        if bad:
            findings.append(f"OBP 最近 {len(bad)} 条可能异常，建议看网关日志。")
    if not findings:
        findings.append("暂无硬异常。服务、任务、模型网关看起来都平稳。")
    return "\n".join(["🚨 个人异常雷达", f"扫描时间：{now_shanghai().strftime('%Y-%m-%d %H:%M')}", *[f"- {row}" for row in findings[:10]]])


def fmt_tokens(bucket: Any) -> str:
    if not isinstance(bucket, dict):
        return "0 tokens"
    return f"{int(bucket.get('total_tokens') or 0):,} tokens"


def render_cost() -> str:
    stats = load_obp_stats()
    if not isinstance(stats, dict) or not stats:
        return "💰 成本守门员\nOBP 统计暂不可读。建议检查 /obp 管理页或 admin stats 接口。"
    paid_stats = stats.get("paid") if isinstance(stats.get("paid"), dict) else {}
    free_stats = stats.get("free") if isinstance(stats.get("free"), dict) else {}
    paid_month, month = month_stats(paid_stats or stats)
    free_month, _ = month_stats(free_stats)
    total_month, _ = month_stats(stats)
    day = now_shanghai().strftime("%Y-%m-%d")
    paid_day_map = paid_stats.get("by_day") if isinstance(paid_stats, dict) else {}
    paid_day = paid_day_map.get(day, {}) if isinstance(paid_day_map, dict) else {}
    total_day_map = stats.get("by_day") if isinstance(stats, dict) else {}
    total_day = total_day_map.get(day, {}) if isinstance(total_day_map, dict) else {}
    day_label = "付费今天"
    if metric_count(paid_day) == 0 and metric_cost(total_day) > 0:
        paid_day = total_day
        day_label = "今天付费估算"
    lines = [
        "💰 成本守门员（默认付费账）",
        f"付费本月（{month}）：{metric_count(paid_month)} 次，{fmt_tokens(paid_month)}，约 {money(metric_cost(paid_month))}",
        f"{day_label}：{metric_count(paid_day)} 次，约 {money(metric_cost(paid_day))}",
        f"免费本月：{metric_count(free_month)} 次，{fmt_tokens(free_month)}，约 {money(metric_cost(free_month))}",
        f"总账本月：{metric_count(total_month)} 次，{fmt_tokens(total_month)}，约 {money(metric_cost(total_month))}",
    ]
    source_month = paid_stats.get("by_source_month") if isinstance(paid_stats, dict) else {}
    source_rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(source_month, dict):
        for source, periods in source_month.items():
            row = periods.get(month, {}) if isinstance(periods, dict) else {}
            if isinstance(row, dict) and metric_count(row):
                source_rows.append((str(source), row))
    source_rows.sort(key=lambda item: metric_cost(item[1]), reverse=True)
    if source_rows:
        lines.append("付费来源（本月）：")
        for source, row in source_rows[:6]:
            lines.append(f"- {source}：{metric_count(row)} 次，{fmt_tokens(row)}，{money(metric_cost(row))}")
    by_model = paid_stats.get("by_model") if isinstance(paid_stats, dict) else {}
    model_rows = sorted(by_model.items(), key=lambda item: metric_cost(item[1]) if isinstance(item[1], dict) else 0, reverse=True) if isinstance(by_model, dict) else []
    if model_rows:
        lines.append("付费模型 TOP：")
        for model, row in model_rows[:5]:
            lines.append(f"- {model}：{metric_count(row)} 次，{fmt_tokens(row)}，{money(metric_cost(row))}")
    free_models = free_stats.get("by_model") if isinstance(free_stats, dict) else {}
    if isinstance(free_models, dict) and free_models:
        rows = [
            f"{name} {fmt_tokens(row)}"
            for name, row in list(free_models.items())[:4]
            if isinstance(row, dict)
        ]
        if rows:
            lines.append("免费模型：" + "、".join(rows))
    return "\n".join(lines)


def render_today(data: dict[str, Any]) -> str:
    system = data.get("system") or {}
    sidecars = data.get("sidecars") or {}
    notify = data.get("notify") or {}
    articles = safe_items(data.get("articles") or {})
    rows = lof_rows(data.get("lof") or {})
    high = [row for row in rows if (num(row.get("rt_premium_pct")) or 0) >= 5]
    mem = system.get("memory") or {}
    attention: list[str] = []
    for name in unhealthy_services(sidecars)[:3]:
        attention.append(f"服务异常：{name}")
    for job in job_errors(notify)[:3]:
        attention.append(f"定时任务异常：{job_name(job)}")
    for row in top_lof_rows(high, 3):
        attention.append(f"LOF 高溢价：{row.get('code')} {short(row.get('name'), 12)} {pct(row.get('rt_premium_pct'))}")
    for item in articles[:3]:
        tag, reason = article_priority(item)
        if tag != "可跳过":
            attention.append(f"{tag}文章：[{source_name(item)}] {short(article_title(item), 34)}（{reason}）")
    if not attention:
        attention.append("暂无硬异常，今天可以慢慢看。")
    return "\n".join(
        [
            "🧭 今日情报官",
            f"时间：{now_shanghai().strftime('%Y-%m-%d %H:%M')}（东八区）",
            f"系统：内存 {mem.get('used_mb', '-')} / {mem.get('total_mb', '-')} MB",
            f"任务：今日触发 {len(today_jobs(notify))} 个，异常 {len(job_errors(notify))} 个",
            f"文章：今日 {len(articles)} 篇；LOF 高溢价 {len(high)} 只",
            "今天先看：",
            *[f"- {item}" for item in attention[:8]],
        ]
    )


def render_night(data: dict[str, Any]) -> str:
    notify = data.get("notify") or {}
    articles = safe_items(data.get("articles") or {})
    jobs = today_jobs(notify)
    errors = job_errors(notify)
    stats = load_obp_stats()
    day = now_shanghai().strftime("%Y-%m-%d")
    day_row = (stats.get("by_day") or {}).get(day, {}) if isinstance(stats, dict) else {}
    lines = [
        "🌙 睡前收束",
        f"今天任务：触发 {len(jobs)} 个，异常 {len(errors)} 个",
        f"今天文章：{len(articles)} 篇；模型成本约 {money(metric_cost(day_row))}",
        "睡前建议：",
    ]
    lines.append("- 明早先看异常任务：" + "、".join(job_name(job) for job in errors[:3]) if errors else "- 硬异常暂无，今晚不用惦记服务器。")
    important = [f"[{source_name(item)}] {short(article_title(item), 32)}" for item in articles if article_priority(item)[0] == "优先读"]
    if important:
        lines.append("- 明天可补读：" + "；".join(important[:3]))
    rows = decisions(limit=3, days=7)
    if rows:
        lines.append("最近决策：")
        lines.extend(f"- {fmt_time(row.get('created_at'))} {short(row.get('text'), 52)}" for row in rows)
    return "\n".join(lines)


def render_weekly(data: dict[str, Any]) -> str:
    notify = data.get("notify") or {}
    stats = load_obp_stats()
    recent = recent_jobs(notify, days=7)
    errors = [job for job in recent if (job.get("status") or {}).get("last_status") in {"error", "timeout"}]
    month_row, month = month_stats(stats if isinstance(stats, dict) else {})
    rows = decisions(limit=6, days=7)
    lines = [
        "🪞 Nanobot 自省周报",
        f"本周任务触发：{len(recent)} 次，异常：{len(errors)} 次",
        f"本月模型调用：{metric_count(month_row)} 次，约 {money(metric_cost(month_row))}（{month}）",
        f"本周记录的决策：{len(rows)} 条",
    ]
    lines.append("需要复盘：" + ("、".join(job_name(job) for job in errors[:5]) if errors else "暂无硬异常"))
    if rows:
        lines.append("决策片段：")
        lines.extend(f"- {short(row.get('text'), 64)}" for row in rows[:5])
    lines.append("建议：继续优先做按需技能，少加常驻服务；重构只围绕上游可同步性展开。")
    return "\n".join(lines)


def render_decision_log() -> str:
    rows = decisions(limit=10)
    if not rows:
        return "📝 决策日志\n暂无记录。可以说：记一条决策：以后 sidecar 默认按需运行。"
    return "\n".join(["📝 决策日志", *[f"- {fmt_time(row.get('created_at'))} [{row.get('category', 'general')}] {short(row.get('text'), 80)}" for row in rows]])


def render_debate(data: dict[str, Any], topic: str) -> str:
    items = safe_items(data.get("articles") or {})
    if not topic and items:
        topic = f"[{source_name(items[0])}] {article_title(items[0])}"
    topic = topic or "最近看到的观点"
    return "\n".join(
        [
            "⚔️ 观点对撞",
            f"主题：{short(topic, 80)}",
            "正方可能在说：这个观点能解释一部分现实，适合先保留。",
            "反方要追问：它有没有忽略样本偏差、成本、时间窗口，或者把相关性当因果？",
            "你可以继续问：按投资/职业/生活三个角度拆一下。",
        ]
    )


def refresh_lof(yes: bool) -> str:
    if not yes:
        return "这是会触发 LOF 后台刷新的动作。请明确要求刷新时运行：copilot.py refresh-lof --yes"
    result = post_json("/api/run", {"tag": "manual"})
    if not result.get("ok") and not result.get("queued"):
        result = post_json("/api/trigger", {"tag": "手动刷新"})
    return "LOF 刷新已触发。" if result.get("ok", True) or result.get("queued") else f"LOF 刷新返回异常：{short(result, 120)}"


def arg_text(args: argparse.Namespace) -> str:
    parts = []
    if args.text:
        parts.append(args.text)
    if args.extra:
        parts.append(" ".join(args.extra))
    if not parts and not sys.stdin.isatty():
        parts.append(sys.stdin.read())
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Nanobot personal copilot")
    parser.add_argument(
        "command",
        choices=[
            "menu",
            "today",
            "morning",
            "brief",
            "reading",
            "anomalies",
            "cost",
            "night",
            "weekly",
            "decision-log",
            "remember-decision",
            "debate",
            "system",
            "lof",
            "articles",
            "tasks",
            "decision",
            "refresh-lof",
        ],
    )
    parser.add_argument("extra", nargs="*")
    parser.add_argument("--text", default="")
    parser.add_argument("--category", default="general")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.command == "menu":
        print(render_menu())
        return 0
    if args.command == "remember-decision":
        print(record_decision(arg_text(args), args.category))
        return 0
    if args.command == "decision-log":
        print(render_decision_log())
        return 0
    if args.command == "cost":
        print(render_cost())
        return 0
    if args.command == "refresh-lof":
        print(refresh_lof(args.yes))
        return 0

    data = load_bundle()
    if args.command in {"today", "morning", "brief"}:
        print(render_today(data))
    elif args.command == "reading":
        print(render_reading(data))
    elif args.command == "anomalies":
        print(render_anomalies(data))
    elif args.command == "night":
        print(render_night(data))
    elif args.command == "weekly":
        print(render_weekly(data))
    elif args.command == "debate":
        print(render_debate(data, arg_text(args)))
    elif args.command == "system":
        print(render_system(data))
    elif args.command == "lof":
        print(render_lof(data))
    elif args.command == "articles":
        print(render_articles(data))
    elif args.command == "tasks":
        print(render_tasks(data))
    elif args.command == "decision":
        print(render_decision(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
