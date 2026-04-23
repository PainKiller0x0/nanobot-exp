#!/usr/bin/env bash
set -euo pipefail

REPO=${1:-/root/nanobot}
CHANNEL_DIR="$REPO/nanobot/channels"
TS=$(date +%Y%m%d_%H%M%S)
ARCHIVE_DIR="/root/.nanobot/workspace/sessions/nanobot_cleanup_${TS}"

mkdir -p "$ARCHIVE_DIR"
shopt -s nullglob
for f in "$CHANNEL_DIR"/*.bak* "$CHANNEL_DIR"/*~ "$CHANNEL_DIR"/*.tmp; do
  mv "$f" "$ARCHIVE_DIR/"
done
shopt -u nullglob

echo "archive=$ARCHIVE_DIR"
ls -la "$ARCHIVE_DIR" | sed -n '1,80p'
