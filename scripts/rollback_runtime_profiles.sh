#!/usr/bin/env bash
set -euo pipefail

# Roll back runtime overlay profiles by using base compose only.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLEAN_FILES=false

usage() {
  cat <<'USAGE'
Usage:
  scripts/rollback_runtime_profiles.sh [options]

Options:
  --clean-files  Remove generated overlay files under repo root
  -h, --help     Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean-files) CLEAN_FILES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

cd "$REPO_DIR"

# Prefer upstream compose service names; fallback for legacy single-service setup.
if docker compose config --services | grep -qx "nanobot-gateway"; then
  services="nanobot-gateway"
  if docker compose config --services | grep -qx "nanobot-api"; then
    services="$services nanobot-api"
  fi
  docker compose -f docker-compose.yml up -d $services
elif docker compose config --services | grep -qx "nanobot"; then
  docker compose -f docker-compose.yml up -d nanobot
else
  echo "[runtime] no known service names found in compose" >&2
fi

if $CLEAN_FILES; then
  rm -f docker-compose.slim.yml docker-compose.reflexio.yml docker-compose.runtime.yml
fi

echo "[runtime] rollback done"