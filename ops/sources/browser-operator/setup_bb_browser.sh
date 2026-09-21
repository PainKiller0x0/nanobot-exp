#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Please run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends nodejs npm ca-certificates
fi

if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1 && ! command -v google-chrome >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends chromium fonts-noto-cjk fonts-noto-color-emoji
fi

npm config set registry "${NPM_REGISTRY:-https://registry.npmmirror.com}"
npm install -g bb-browser@latest

systemctl disable --now avahi-daemon.service avahi-daemon.socket 2>/dev/null || true
systemctl disable --now upower.service 2>/dev/null || systemctl stop upower.service 2>/dev/null || true
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py check
