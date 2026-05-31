#!/usr/bin/env python3
"""Install Nanobot ops guard scheduled jobs.

This script keeps the live notify-sidecar config reproducible without committing
private target IDs or tokens. It only adds/updates the ops guard jobs by id.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

CONFIG_PATH = Path('/root/.nanobot/workspace/skills/notify-sidecar-rs/config.json')

JOBS: list[dict[str, Any]] = [
    {
        'id': 'ops-guard-heal',
        'name': 'Nanobot 服务自愈巡检',
        'enabled': True,
        'schedule': '*/5 * * * *',
        'timezone': 'Asia/Shanghai',
        'command': '/root/nanobot-ops/scripts/nanobot-ops-guard.py --mode heal',
        'timeout_secs': 90,
    },
    {
        'id': 'ops-guard-upstream',
        'name': 'Nanobot 上游版本通知',
        'enabled': True,
        'schedule': '30 10 * * 1',
        'timezone': 'Asia/Shanghai',
        'command': '/root/nanobot-ops/scripts/nanobot-ops-guard.py --mode upstream',
        'timeout_secs': 45,
    },
    {
        'id': 'ops-guard-obp-budget',
        'name': 'OBP 月预算告警',
        'enabled': True,
        'schedule': '10 9,21 * * *',
        'timezone': 'Asia/Shanghai',
        'command': 'NANOBOT_OBP_MONTHLY_BUDGET_CNY=${NANOBOT_OBP_MONTHLY_BUDGET_CNY:-10} /root/nanobot-ops/scripts/nanobot-ops-guard.py --mode obp-budget',
        'timeout_secs': 45,
    },
]


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f'missing notify config: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def install_jobs(path: Path, dry_run: bool) -> bool:
    data = load_config(path)
    jobs = data.setdefault('jobs', [])
    by_id = {job.get('id'): idx for idx, job in enumerate(jobs)}
    changed = False
    for job in JOBS:
        idx = by_id.get(job['id'])
        if idx is None:
            jobs.append(job)
            changed = True
            continue
        merged = dict(jobs[idx])
        merged.update(job)
        if merged != jobs[idx]:
            jobs[idx] = merged
            changed = True
    if not changed:
        return False
    if dry_run:
        print(f'would update {path}')
        return True
    backup = path.with_suffix(path.suffix + f'.bak.{time.strftime("%Y%m%d-%H%M%S")}')
    shutil.copy2(path, backup)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(tmp, path.stat().st_mode & 0o777)
    tmp.replace(path)
    print(f'updated notify jobs: {path}')
    print(f'backup: {backup}')
    return True


def run_systemctl(args: list[str], dry_run: bool) -> None:
    cmd = ['systemctl', *args]
    if dry_run:
        print('would run:', ' '.join(cmd))
        return
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Install Nanobot ops guard jobs')
    parser.add_argument('--config', type=Path, default=CONFIG_PATH)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--restart-notify', action='store_true')
    parser.add_argument('--enable-timer', action='store_true')
    args = parser.parse_args()

    changed = install_jobs(args.config, args.dry_run)
    if args.enable_timer:
        run_systemctl(['daemon-reload'], args.dry_run)
        run_systemctl(['enable', '--now', 'nanobot-data-backup.timer'], args.dry_run)
    if args.restart_notify and changed:
        run_systemctl(['restart', 'notify-sidecar-rs.service'], args.dry_run)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())