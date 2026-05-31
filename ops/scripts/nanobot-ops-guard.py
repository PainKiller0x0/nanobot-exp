#!/usr/bin/env python3
"""Small operational guard for Nanobot sidecars.

Modes:
- backup: local root-only snapshot for user data.
- heal: restart unhealthy sidecars after consecutive failures.
- upstream: notify when HKUDS/nanobot publishes a new GitHub release.
- obp-budget: notify when paid OBP monthly spend crosses configured levels.

The script is intentionally quiet on success so notify-sidecar only sends actionable alerts.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python 3.9+ on the server has zoneinfo.
    ZoneInfo = None  # type: ignore

ROOT = Path('/root/.nanobot')
STATE_DIR = ROOT / 'data' / 'ops-guard'
STATE_FILE = STATE_DIR / 'state.json'
BACKUP_DIR = ROOT / 'backups' / 'ops-guard'
SIDECAR_API = os.environ.get('NANOBOT_SIDECAR_API', 'http://127.0.0.1:8093/api/sidecars')
OBP_STATS_API = os.environ.get('NANOBOT_OBP_STATS_API', 'http://127.0.0.1:8000/admin/stats')
UPSTREAM_RELEASE_API = os.environ.get(
    'NANOBOT_UPSTREAM_RELEASE_API',
    'https://api.github.com/repos/HKUDS/nanobot/releases/latest',
)
TZ_NAME = os.environ.get('NANOBOT_OPS_TZ', 'Asia/Shanghai')

HEAL_ALLOWED_IDS = {
    'nanobot',
    'rss',
    'qq',
    'lof',
    'notify',
    'trend',
    'reflexio',
    'obp',
}
SKIP_RESTART_IDS = {'podman-public-rule', 'bing-rewards'}

BACKUP_PATHS = [
    ROOT / 'data',
    ROOT / 'workspace' / 'memory',
    ROOT / 'workspace' / 'skills' / 'notify-sidecar-rs' / 'data',
    ROOT / 'workspace' / 'skills' / 'wechat-rss-sidecar' / 'data',
    ROOT / 'workspace' / 'skills' / 'trend-radar' / 'data',
    ROOT / 'workspace' / 'cron' / 'jobs.json',
    ROOT / 'config.json',
    ROOT / 'capabilities.json',
    ROOT / 'evolution.json',
    ROOT / 'sidecars.json',
    ROOT / 'overrides',
]

EXCLUDE_PARTS = {
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    'target',
    'node_modules',
    'backups',
}


def shanghai_now() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(TZ_NAME))
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return shanghai_now().isoformat(timespec='seconds')


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except PermissionError:
        pass


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        broken = STATE_FILE.with_suffix(f'.broken-{int(time.time())}.json')
        STATE_FILE.replace(broken)
        return {}


def save_state(state: dict[str, Any], dry_run: bool = False) -> None:
    if dry_run:
        return
    ensure_private_dir(STATE_DIR)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(STATE_FILE)


def http_json(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={'User-Agent': 'nanobot-ops-guard/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def run_cmd(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def readable_size(num: int) -> str:
    value = float(num)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if value < 1024 or unit == 'GB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{value:.1f} GB'


def should_exclude(path: Path) -> bool:
    return bool(set(path.parts) & EXCLUDE_PARTS)


def archive_name(now: datetime) -> str:
    return f'nanobot-data-{now.strftime("%Y%m%d-%H%M%S")}.tar.gz'


def arcname_for(path: Path) -> str:
    try:
        rel = path.relative_to(ROOT)
        return str(Path('dot-nanobot') / rel)
    except ValueError:
        return str(Path('extra') / path.name)


def add_path(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    if not path.exists() or should_exclude(path):
        return
    if path.is_dir():
        info = tar.gettarinfo(str(path), arcname)
        info.mode = 0o700
        tar.addfile(info)
        for child in sorted(path.iterdir()):
            add_path(tar, child, str(Path(arcname) / child.name))
        return
    info = tar.gettarinfo(str(path), arcname)
    if path.name.endswith('.json') or 'config' in path.name:
        info.mode = 0o600
    with path.open('rb') as fh:
        tar.addfile(info, fh)


def run_backup(args: argparse.Namespace, state: dict[str, Any]) -> list[str]:
    ensure_private_dir(BACKUP_DIR)
    now = shanghai_now()
    final = BACKUP_DIR / archive_name(now)
    if args.dry_run:
        found = [str(p) for p in BACKUP_PATHS if p.exists()]
        return [f'[dry-run] would back up {len(found)} paths to {final}']

    fd, tmp_name = tempfile.mkstemp(prefix='.nanobot-data-', suffix='.tar.gz', dir=str(BACKUP_DIR))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tarfile.open(tmp, 'w:gz') as tar:
            manifest = {
                'created_at': iso_now(),
                'host': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
                'paths': [str(p) for p in BACKUP_PATHS if p.exists()],
                'note': 'Root-only local snapshot. Contains config; keep permissions private.',
            }
            payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
            info = tarfile.TarInfo('MANIFEST.json')
            info.size = len(payload)
            info.mode = 0o600
            info.mtime = time.time()
            tar.addfile(info, io.BytesIO(payload))
            for path in BACKUP_PATHS:
                add_path(tar, path, arcname_for(path))
        os.chmod(tmp, 0o600)
        tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)

    keep = int(os.environ.get('NANOBOT_BACKUP_KEEP', '14'))
    backups = sorted(BACKUP_DIR.glob('nanobot-data-*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)

    remote = os.environ.get('NANOBOT_BACKUP_RCLONE_TARGET', '').strip()
    remote_msg = ''
    if remote:
        proc = run_cmd(['rclone', 'copy', str(final), remote], timeout=600)
        if proc.returncode != 0:
            remote_msg = f'\n远端同步失败：{(proc.stderr or proc.stdout).strip()[:300]}'
        else:
            remote_msg = f'\n已同步到：{remote}'

    state.setdefault('backup', {})['last_success'] = {'at': iso_now(), 'path': str(final), 'bytes': final.stat().st_size}
    save_state(state, args.dry_run)
    if args.force_report:
        return [f'数据备份完成：{final}\n大小：{readable_size(final.stat().st_size)}{remote_msg}']
    if remote_msg.startswith('\n远端同步失败'):
        return [f'数据备份完成，但远端同步失败：{final}{remote_msg}']
    return []


def run_heal(args: argparse.Namespace, state: dict[str, Any]) -> list[str]:
    threshold = int(os.environ.get('NANOBOT_HEAL_FAILURE_THRESHOLD', '3'))
    cooldown = int(os.environ.get('NANOBOT_HEAL_COOLDOWN_SECONDS', '1800'))
    heal_state = state.setdefault('heal', {})
    messages: list[str] = []
    now_ts = int(time.time())

    try:
        data = http_json(SIDECAR_API, timeout=8)
        items = data.get('items', [])
    except Exception as exc:
        entry = heal_state.setdefault('sidecar-api', {'failures': 0, 'last_restart_at': 0})
        entry['failures'] = int(entry.get('failures', 0)) + 1
        entry['last_error'] = str(exc)
        if entry['failures'] >= threshold and now_ts - int(entry.get('last_restart_at', 0)) >= cooldown:
            if args.dry_run:
                messages.append(f'[dry-run] sidecar API failed {entry["failures"]} times; would restart lof-sidecar.service')
            else:
                proc = run_cmd(['systemctl', 'restart', 'lof-sidecar.service'], timeout=60)
                entry['last_restart_at'] = now_ts
                if proc.returncode == 0:
                    messages.append(f'Nanobot 自愈：sidecar 管理接口连续 {entry["failures"]} 次不可用，已重启 lof-sidecar.service。')
                else:
                    messages.append(f'Nanobot 自愈失败：lof-sidecar.service 重启失败：{(proc.stderr or proc.stdout).strip()[:300]}')
        save_state(state, args.dry_run)
        return messages

    seen_ids = set()
    for item in items:
        sid = str(item.get('id') or '')
        seen_ids.add(sid)
        if sid in SKIP_RESTART_IDS:
            continue
        unit = str(item.get('unit') or '').strip()
        if sid not in HEAL_ALLOWED_IDS or not unit:
            continue
        entry = heal_state.setdefault(sid, {'failures': 0, 'last_restart_at': 0})
        if bool(item.get('ok')):
            entry['failures'] = 0
            entry['last_ok_at'] = iso_now()
            continue
        entry['failures'] = int(entry.get('failures', 0)) + 1
        entry['last_bad_at'] = iso_now()
        entry['last_error'] = '; '.join(item.get('recent_errors') or [])[:500]
        failures = int(entry['failures'])
        since_restart = now_ts - int(entry.get('last_restart_at', 0))
        if failures >= threshold and since_restart >= cooldown:
            if args.dry_run:
                messages.append(f'[dry-run] {sid} 连续 {failures} 次异常，将重启 {unit}')
            else:
                proc = run_cmd(['systemctl', 'restart', unit], timeout=90)
                entry['last_restart_at'] = now_ts
                if proc.returncode == 0:
                    messages.append(f'Nanobot 自愈：{sid} 连续 {failures} 次异常，已重启 {unit}。')
                else:
                    messages.append(f'Nanobot 自愈失败：{sid} 连续 {failures} 次异常，但 {unit} 重启失败：{(proc.stderr or proc.stdout).strip()[:300]}')
        elif failures == threshold:
            messages.append(f'Nanobot 巡检：{sid} 连续 {failures} 次异常，但仍在重启冷却期。')

    for sid in list(heal_state.keys()):
        if sid not in seen_ids and sid != 'sidecar-api':
            heal_state.pop(sid, None)

    save_state(state, args.dry_run)
    if args.force_report and not messages:
        summary = data.get('summary') or {}
        messages.append(f'Nanobot 巡检正常：{summary.get("healthy", 0)}/{summary.get("total", 0)} 个服务健康。')
    return messages


def run_upstream(args: argparse.Namespace, state: dict[str, Any]) -> list[str]:
    upstream_state = state.setdefault('upstream', {}).setdefault('HKUDS/nanobot', {})
    try:
        data = http_json(UPSTREAM_RELEASE_API, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    tag = str(data.get('tag_name') or '').strip()
    if not tag:
        return []
    old = str(upstream_state.get('tag') or '').strip()
    upstream_state.update(
        {
            'tag': tag,
            'name': data.get('name') or tag,
            'url': data.get('html_url') or 'https://github.com/HKUDS/nanobot/releases',
            'published_at': data.get('published_at') or '',
            'checked_at': iso_now(),
        }
    )
    save_state(state, args.dry_run)
    if not old:
        if args.force_report:
            return [f'上游版本基线已记录：HKUDS/nanobot {tag}']
        return []
    if old != tag:
        return [
            'Nanobot 上游有新版本：\n'
            f'- 旧版本：{old}\n'
            f'- 新版本：{tag}\n'
            f'- 地址：{upstream_state["url"]}\n'
            '建议先在默认 nanobot 本地回测，通过后再更新广州 nanobot。'
        ]
    if args.force_report:
        return [f'上游版本无变化：HKUDS/nanobot {tag}']
    return []


def paid_month_cost(stats: dict[str, Any], month_key: str) -> float:
    paid = stats.get('paid') or {}
    month = (paid.get('by_month') or {}).get(month_key) or {}
    return float(month.get('cost_cny') or 0.0)


def by_source_summary(stats: dict[str, Any]) -> str:
    paid = stats.get('paid') or {}
    by_source = paid.get('by_source') or {}
    rows = []
    for source, item in sorted(by_source.items(), key=lambda kv: float((kv[1] or {}).get('cost_cny') or 0.0), reverse=True)[:5]:
        rows.append(f'- {source}: ¥{float(item.get("cost_cny") or 0.0):.4f}')
    return '\n'.join(rows) if rows else '- 暂无付费来源记录'


def run_obp_budget(args: argparse.Namespace, state: dict[str, Any]) -> list[str]:
    budget = float(os.environ.get('NANOBOT_OBP_MONTHLY_BUDGET_CNY', '10'))
    if budget <= 0:
        return []
    ratios = []
    for raw in os.environ.get('NANOBOT_OBP_BUDGET_ALERT_RATIOS', '0.5,0.8,1.0').split(','):
        raw = raw.strip()
        if raw:
            ratios.append(float(raw))
    ratios = sorted(set(ratios))
    month_key = shanghai_now().strftime('%Y-%m')
    stats = http_json(OBP_STATS_API, timeout=8)
    cost = paid_month_cost(stats, month_key)
    obp_state = state.setdefault('obp_budget', {}).setdefault(month_key, {'notified': []})
    notified = set(str(x) for x in obp_state.get('notified', []))
    messages = []
    for ratio in ratios:
        level = f'{ratio:.3f}'
        if cost >= budget * ratio and level not in notified:
            pct = ratio * 100
            messages.append(
                'OBP 月预算提醒：\n'
                f'- 本月付费消耗：¥{cost:.4f}\n'
                f'- 预算：¥{budget:.2f}\n'
                f'- 已触达：{pct:.0f}% 阈值\n'
                '按来源：\n'
                f'{by_source_summary(stats)}'
            )
            notified.add(level)
    obp_state['notified'] = sorted(notified)
    obp_state['last_cost_cny'] = cost
    obp_state['last_checked_at'] = iso_now()
    save_state(state, args.dry_run)
    if args.force_report and not messages:
        messages.append(
            'OBP 月预算正常：\n'
            f'- 本月付费消耗：¥{cost:.4f}\n'
            f'- 预算：¥{budget:.2f}\n'
            '按来源：\n'
            f'{by_source_summary(stats)}'
        )
    return messages


def acquire_lock() -> int:
    ensure_private_dir(STATE_DIR)
    lock = STATE_DIR / 'ops-guard.lock'
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('ops guard already running', file=sys.stderr)
        sys.exit(0)
    return fd


def main() -> int:
    parser = argparse.ArgumentParser(description='Nanobot operational guard')
    parser.add_argument('--mode', choices=['all', 'backup', 'heal', 'upstream', 'obp-budget'], default='all')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force-report', action='store_true')
    args = parser.parse_args()

    lock_fd = acquire_lock()
    try:
        state = load_state()
        messages: list[str] = []
        if args.mode in ('all', 'backup'):
            messages.extend(run_backup(args, state))
        if args.mode in ('all', 'heal'):
            messages.extend(run_heal(args, state))
        if args.mode in ('all', 'upstream'):
            messages.extend(run_upstream(args, state))
        if args.mode in ('all', 'obp-budget'):
            messages.extend(run_obp_budget(args, state))
        if messages:
            print('\n\n'.join(m.strip() for m in messages if m.strip()))
        return 0
    finally:
        os.close(lock_fd)


if __name__ == '__main__':
    raise SystemExit(main())