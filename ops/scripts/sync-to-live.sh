#!/usr/bin/env bash
set -euo pipefail

SRC=${NANOBOT_OPS_SRC:-/root/nanobot/ops}
DST=${NANOBOT_OPS_LIVE:-/root/nanobot-ops}
MODE=dry-run

usage() {
  cat <<'USAGE'
Usage: sync-to-live.sh [--check|--apply] [--src PATH] [--dst PATH]

Synchronize the repository ops snapshot into the live ops worktree used by
/usr/local/sbin/deploy-sidecar. Default mode is dry-run.

Modes:
  default     Show itemized changes without writing.
  --check     Exit 0 only when live ops is already in sync.
  --apply     Write changes, then verify live ops is in sync.

Safety rules:
- default source must be /root/nanobot/ops
- default destination must be /root/nanobot-ops
- .git is never touched
- build artifacts, runtime data, logs, target/, .env and local refresh Dockerfiles are excluded
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) MODE=apply ;;
    --check) MODE=check ;;
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
if ! command -v rsync >/dev/null 2>&1; then
  echo "missing dependency: rsync" >&2
  exit 1
fi

mkdir -p "$DST"

base_rsync_args=(
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

dirs=(bin sbin config docs scripts sources systemd)

run_rsync() {
  local dry_flag=${1:-0}
  local -a args=("${base_rsync_args[@]}")
  if [[ "$dry_flag" -eq 1 ]]; then
    args+=(--dry-run --itemize-changes)
  fi
  for dir in "${dirs[@]}"; do
    [[ -d "$SRC/$dir" ]] || continue
    mkdir -p "$DST/$dir"
    rsync "${args[@]}" "$SRC/$dir/" "$DST/$dir/"
  done
}

collect_drift() {
  run_rsync 1 | sed '/^$/d'
}

case "$MODE" in
  dry-run)
    echo "dry-run: $SRC -> $DST"
    echo "pass --apply to write changes, or --check to use this as a guard"
    drift=$(collect_drift)
    if [[ -n "$drift" ]]; then
      printf '%s\n' "$drift"
      echo "drift: detected"
    else
      echo "drift: none"
    fi
    ;;
  check)
    drift=$(collect_drift)
    if [[ -n "$drift" ]]; then
      echo "live ops drift detected: $SRC -> $DST" >&2
      printf '%s\n' "$drift" | sed -n '1,120p' >&2
      echo "run: /root/nanobot/ops/scripts/sync-to-live.sh --apply" >&2
      exit 1
    fi
    echo "live ops in sync: $DST"
    ;;
  apply)
    echo "apply: syncing $SRC -> $DST"
    run_rsync 0
    drift=$(collect_drift)
    if [[ -n "$drift" ]]; then
      echo "sync verification failed; live ops still differs" >&2
      printf '%s\n' "$drift" | sed -n '1,120p' >&2
      exit 1
    fi
    echo "live ops in sync: $DST"
    ;;
  *)
    echo "internal error: unknown mode $MODE" >&2
    exit 2
    ;;
esac
