#!/usr/bin/env bash
set -euo pipefail

UNIT=/etc/systemd/system/nanobot-gateway.service
cat > "$UNIT" <<'EOF'
[Unit]
Description=nanobot Gateway Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/.nanobot/workspace
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -m nanobot.cli.commands gateway
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now nanobot-gateway.service

# Stop legacy containerized gateway if present.
if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -qx 'nanobot-cage'; then
    docker stop nanobot-cage >/dev/null 2>&1 || true
    docker update --restart=no nanobot-cage >/dev/null 2>&1 || true
  fi
fi

# Best-effort cleanup of legacy nohup process
pkill -f 'sh -lc python /root/.nanobot/overrides/apply_overrides.py && python -m nanobot.cli.commands gateway' >/dev/null 2>&1 || true

systemctl --no-pager -l status nanobot-gateway.service | sed -n '1,40p'
