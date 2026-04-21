#!/usr/bin/env bash
set -euo pipefail

# Quick memory report focused on nanobot stack.

echo "=== host ==="
free -h

echo
echo "=== top rss processes ==="
ps -eo pid,cmd,rss,%mem --sort=-rss | head -n 20

echo
echo "=== docker services ==="
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' || true

echo
echo "=== nanobot/reflexio/sidecars ==="
ps -eo pid,cmd,rss,%mem | grep -E 'nanobot|reflexio|qq-sidecar|wechat-rss|python3 app.py' | grep -v grep || true