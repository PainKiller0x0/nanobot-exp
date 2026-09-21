#!/usr/bin/env bash
set -euo pipefail
repo=${1:-/root/nanobot-ops}
install -m 0755 "$repo/bin/sidecarctl" /usr/local/bin/sidecarctl
install -m 0755 "$repo/sbin/rust-sidecar-maintain" /usr/local/sbin/rust-sidecar-maintain
if [ -f "$repo/scripts/deploy-sidecar.sh" ]; then install -m 0755 "$repo/scripts/deploy-sidecar.sh" /usr/local/sbin/deploy-sidecar; fi
if [ -f "$repo/sbin/podman-port-forward-allow.sh" ]; then install -m 0755 "$repo/sbin/podman-port-forward-allow.sh" /usr/local/sbin/podman-port-forward-allow.sh; fi
install -m 0644 "$repo/config/sidecars.json" /root/.nanobot/sidecars.json
if [ -f "$repo/config/capabilities.json" ]; then
  install -m 0644 "$repo/config/capabilities.json" /root/.nanobot/capabilities.json
fi
if [ -f "$repo/config/evolution.json" ]; then
  install -m 0644 "$repo/config/evolution.json" /root/.nanobot/evolution.json
fi
install_skill_source() {
  local rel="$1"
  local mode="$2"
  local dst="/root/.nanobot/workspace/skills/$rel"
  if [ -f "$repo/sources/$rel" ]; then
    mkdir -p "$(dirname "$dst")"
    install -m "$mode" "$repo/sources/$rel" "$dst"
  fi
}
install_skill_source "_shared/ops_common.py" 0644
install_skill_source "qdii-monitor/send_qq.py" 0755
for f in "$repo"/systemd/*.service "$repo"/systemd/*.target "$repo"/systemd/*.timer; do
  [ -e "$f" ] || continue
  install -m 0644 "$f" "/etc/systemd/system/$(basename "$f")"
done
if [ -d "$repo/systemd/drop-ins" ]; then
  find "$repo/systemd/drop-ins" -type f -name '*.conf' | while read -r f; do
    rel=${f#"$repo/systemd/drop-ins/"}
    dst="/etc/systemd/system/$rel"
    mkdir -p "$(dirname "$dst")"
    install -m 0644 "$f" "$dst"
  done
fi
systemctl daemon-reload
