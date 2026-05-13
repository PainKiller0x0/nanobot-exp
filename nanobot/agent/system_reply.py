"""Local system status direct replies."""

from __future__ import annotations

import time
from pathlib import Path


def format_memory_report(model: str, start_time: float, last_usage: dict[str, int]) -> str:
    mem = read_meminfo()
    cgroup = read_cgroup_memory()
    rss = read_process_rss()
    uptime = format_duration(max(0, int(time.time() - start_time)))

    lines = ["内存直查（未调用 LLM）"]
    if mem:
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = max(0, total - available)
        pct = (used / total * 100) if total else 0
        lines.append(
            f"宿主机：{fmt_kib(used)} / {fmt_kib(total)}，"
            f"可用 {fmt_kib(available)}（{pct:.0f}%）"
        )
    if cgroup:
        current, limit = cgroup
        if limit:
            pct = current / limit * 100 if limit else 0
            lines.append(f"容器：{fmt_bytes(current)} / {fmt_bytes(limit)}（{pct:.0f}%）")
        else:
            lines.append(f"容器：{fmt_bytes(current)}")
    if rss:
        lines.append(f"nanobot 进程 RSS：{fmt_kib(rss)}")
    lines.append(f"运行时长：{uptime}")
    lines.append(f"模型：{model}")
    if last_usage:
        prompt = last_usage.get("prompt_tokens", 0)
        cached = last_usage.get("cached_tokens", 0)
        completion = last_usage.get("completion_tokens", 0)
        lines.append(f"上次 LLM：prompt {prompt}，cached {cached}，completion {completion}")
    return "\n".join(lines)


def read_meminfo() -> dict[str, int]:
    data: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, rest = line.split(":", 1)
            value = rest.strip().split()[0]
            data[name] = int(value)
    except Exception:
        return {}
    return data


def read_process_rss() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except Exception:
        return 0
    return 0


def read_cgroup_memory() -> tuple[int, int | None] | None:
    current = read_int("/sys/fs/cgroup/memory.current")
    if current is None:
        return None
    raw_limit = read_text("/sys/fs/cgroup/memory.max")
    if not raw_limit or raw_limit == "max":
        return current, None
    try:
        return current, int(raw_limit)
    except ValueError:
        return current, None


def read_int(path: str) -> int | None:
    text = read_text(path)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def fmt_kib(kib: int) -> str:
    return fmt_bytes(kib * 1024)


def fmt_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def format_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes or not parts:
        parts.append(f"{minutes}分钟")
    return "".join(parts)


__all__ = [
    "fmt_bytes",
    "fmt_kib",
    "format_duration",
    "format_memory_report",
    "read_cgroup_memory",
    "read_meminfo",
    "read_process_rss",
]
