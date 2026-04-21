#!/usr/bin/env bash
set -euo pipefail

# One-shot wrapper: apply reflexio glue + slim profile.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=false

usage() {
  cat <<'USAGE'
Usage:
  scripts/apply_runtime_profiles.sh [--apply]

Options:
  --apply     Apply immediately with docker compose up -d
  -h, --help  Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

cd "$REPO_DIR"

if $APPLY; then
  scripts/apply_reflexio_glue.sh --apply
  scripts/apply_slim_profile.sh --apply
else
  scripts/apply_reflexio_glue.sh
  scripts/apply_slim_profile.sh
fi

echo "[runtime] done"