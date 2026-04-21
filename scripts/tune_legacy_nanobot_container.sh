#!/usr/bin/env bash
set -euo pipefail

# Recreate legacy nanobot-cage container with safer memory settings.
# Keeps image/cmd/mounts/ports while adding allocator env + resource limits.

NAME="nanobot-cage"
BACKUP_NAME="nanobot-cage-backup"
MEMORY_LIMIT="600m"
CPU_LIMIT="1.0"
APPLY=false

usage() {
  cat <<'USAGE'
Usage:
  scripts/tune_legacy_nanobot_container.sh [options]

Options:
  --name <value>          Container name. Default: nanobot-cage
  --backup-name <value>   Backup container name. Default: nanobot-cage-backup
  --memory <value>        Docker memory limit. Default: 600m
  --cpus <value>          Docker cpu limit. Default: 1.0
  --apply                 Apply recreation now
  -h, --help              Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --backup-name) BACKUP_NAME="${2:-}"; shift 2 ;;
    --memory) MEMORY_LIMIT="${2:-}"; shift 2 ;;
    --cpus) CPU_LIMIT="${2:-}"; shift 2 ;;
    --apply) APPLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "Error: container not found: $NAME" >&2
  exit 1
fi

IMAGE="$(docker inspect -f '{{.Config.Image}}' "$NAME")"

echo "[legacy-tune] target=$NAME image=$IMAGE mem=$MEMORY_LIMIT cpus=$CPU_LIMIT"

# Known-good runtime contract for current legacy container.
RUN_ARGS=(
  -d
  --name "$NAME"
  --restart always
  --memory "$MEMORY_LIMIT"
  --cpus "$CPU_LIMIT"
  -p 8080:8080
  -v /etc/localtime:/etc/localtime:ro
  -v /var/run/docker.sock:/var/run/docker.sock:rw
  -v /root/.nanobot:/root/.nanobot:rw
  -v /root/nanobot:/app:rw
  --security-opt label=disable
  -e NANOBOT_CONFIG=/root/.nanobot/config.json
  -e TZ=Asia/Shanghai
  -e NANOBOT_REFLEXIO_ENABLED=true
  -e REFLEXIO_URL=http://172.17.0.1:8081
  -e NANOBOT_FAILOVER_SETTINGS_URL=http://150.158.121.88:8000/admin/failover
  -e PYTHONPATH=/app
  -e PYTHONUNBUFFERED=1
  -e ARK_SLOT_WORKSPACE=/root/.nanobot/workspace
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTHONMALLOC=malloc
  -e MALLOC_ARENA_MAX=2
  -e MALLOC_TRIM_THRESHOLD_=131072
)

CMD=(sh -lc "python /root/.nanobot/overrides/apply_overrides.py && python -m nanobot.cli.commands gateway")

if ! $APPLY; then
  echo "[legacy-tune] dry-run only."
  echo "[legacy-tune] docker run ${RUN_ARGS[*]} $IMAGE ${CMD[*]}"
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$BACKUP_NAME"; then
  docker rm -f "$BACKUP_NAME" >/dev/null 2>&1 || true
fi

echo "[legacy-tune] creating backup: $BACKUP_NAME"
docker stop "$NAME" >/dev/null 2>&1 || true
docker rename "$NAME" "$BACKUP_NAME"

echo "[legacy-tune] starting optimized container"
docker run "${RUN_ARGS[@]}" "$IMAGE" "${CMD[@]}" >/dev/null

sleep 3
if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "[legacy-tune] new container failed, rolling back" >&2
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$BACKUP_NAME" "$NAME"
  docker start "$NAME" >/dev/null 2>&1 || true
  exit 1
fi

echo "[legacy-tune] success"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | sed -n '1,3p'