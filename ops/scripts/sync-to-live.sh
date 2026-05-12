#!/usr/bin/env bash
set -euo pipefail

SRC=${NANOBOT_OPS_SRC:-/root/nanobot/ops}
DST=${NANOBOT_OPS_LIVE:-/root/nanobot-ops}
APPLY=0

usage() {
  cat <<'USAGE'
Usage: sync-to-live.sh [--apply] [--src PATH] [--dst PATH]

Synchronize the repository ops snapshot into the live ops worktree used by
/usr/local/sbin/deploy-sidecar. Default mode is dry-run.

Safety rules:
- default source must be /root/nanobot/ops
- default destination must be /root/nanobot-ops
- .git is never touched
- build artifacts, runtime data, logs, target/, .env and local refresh Dockerfiles are excluded
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --src) SRC=${2:?missing --src value}; shift ;;
    --dst) DST=${2:?missing --dst value}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

SRC=$(readlink -f "$SRC")
DST=$(readlink -m "$DST")

if [[ "$SRC" != "/root/nanobot/ops" ]]; then
  echo "refusing non-standard source: $SRC" >&2
  exit 1
fi
if [[ "$DST" != "/root/nanobot-ops" ]]; then
  echo "refusing non-standard destination: $DST" >&2
  exit 1
fi
if [[ ! -d "$SRC" ]]; then
  echo "missing source: $SRC" >&2
  exit 1
fi

mkdir -p "$DST"

rsync_args=(
  -a
  --delete
  --exclude '.git/'
  --exclude 'target/'
  --exclude 'data/'
  --exclude 'logs/'
  --exclude '.env'
  --exclude '.env.*'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '*.bak.*'
  --exclude '*.bak*/'
  --exclude 'notify-sidecar-rs/config.json'
  --exclude 'Dockerfile.local-refresh'
  --exclude '*.log'
)
if [[ "$APPLY" -eq 0 ]]; then
  rsync_args+=(--dry-run --itemize-changes)
  echo "dry-run: pass --apply to write changes"
else
  echo "apply: syncing $SRC -> $DST"
fi

for dir in bin sbin config docs scripts sources systemd; do
  [[ -d "$SRC/$dir" ]] || continue
  mkdir -p "$DST/$dir"
  rsync "${rsync_args[@]}" "$SRC/$dir/" "$DST/$dir/"
done

echo "done"
