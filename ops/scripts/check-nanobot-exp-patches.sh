#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-/root/nanobot}"
fail=0

check() {
  local file="$1" pattern="$2" label="$3"
  if grep -qF "$pattern" "$REPO/$file" 2>/dev/null; then
    printf 'ok   %s\n' "$label"
  else
    printf 'MISS %s (%s)\n' "$label" "$file" >&2
    fail=1
  fi
}

check 'nanobot/config/schema.py' 'delivery_channel: str | None = None' 'heartbeat delivery_channel schema'
check 'nanobot/config/schema.py' 'delivery_chat_id: str | None = None' 'heartbeat delivery_chat_id schema'
check 'nanobot/cli/commands.py' 'hb_cfg.delivery_channel' 'heartbeat fixed target routing'
check 'ops/sources/hermes-check/hermes_check.py' 'SIDECAR_STATUS_API' 'HERMES sidecar manager health check'
check 'ops/sources/qdii-monitor/send_qq.py' 'run_fresh_report' 'LOF refresh-before-send wrapper'

exit "$fail"
