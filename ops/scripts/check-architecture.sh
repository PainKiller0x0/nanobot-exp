#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OPS="$ROOT/ops"

python3 - "$ROOT" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
ops = root / "ops"
errors: list[str] = []
warnings: list[str] = []


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel(path)}: invalid JSON: {exc}")
        return None


def require_file(path: Path, note: str):
    if not path.exists():
        errors.append(f"missing {note}: {rel(path)}")

sidecars_path = ops / "config" / "sidecars.json"
capabilities_path = ops / "config" / "capabilities.json"
evolution_path = ops / "config" / "evolution.json"
sidecars = load_json(sidecars_path) or []
capabilities = load_json(capabilities_path) or []
if evolution_path.exists():
    load_json(evolution_path)

if not isinstance(sidecars, list):
    errors.append("ops/config/sidecars.json must be a list")
    sidecars = []
if not isinstance(capabilities, list):
    errors.append("ops/config/capabilities.json must be a list")
    capabilities = []

ids = [item.get("id") for item in sidecars if isinstance(item, dict)]
for sid in sorted({x for x in ids if ids.count(x) > 1}):
    errors.append(f"duplicate sidecar id: {sid}")

ports: dict[int, list[str]] = {}
units: dict[str, list[str]] = {}
for item in sidecars:
    if not isinstance(item, dict):
        errors.append("sidecars.json contains non-object item")
        continue
    sid = str(item.get("id") or "")
    if not sid:
        errors.append("sidecar item missing id")
        continue
    port = item.get("port")
    if port is not None:
        if not isinstance(port, int):
            errors.append(f"sidecar {sid}: port must be integer/null")
        else:
            ports.setdefault(port, []).append(sid)
    unit = item.get("unit")
    if unit:
        units.setdefault(unit, []).append(sid)
        require_file(ops / "systemd" / unit, f"systemd unit for sidecar {sid}")
    kind = item.get("check_kind") or "http"
    if kind not in {"http", "tcp", "unit"}:
        errors.append(f"sidecar {sid}: unsupported check_kind {kind!r}")
    check_url = str(item.get("check_url") or "")
    if check_url and not re.match(r"^http://(127\.0\.0\.1|172\.17\.0\.1|localhost)(:\d+)?/", check_url):
        errors.append(f"sidecar {sid}: check_url should stay local/bridge only: {check_url}")
    homepage = item.get("homepage_url")
    if homepage is not None and (not isinstance(homepage, str) or not homepage.startswith("/")):
        errors.append(f"sidecar {sid}: homepage_url must be null or absolute path")
    for key in ["logs_command", "restart_command"]:
        if not str(item.get(key) or "").strip():
            errors.append(f"sidecar {sid}: missing {key}")

for port, owners in sorted(ports.items()):
    if len(owners) > 1:
        errors.append(f"duplicate sidecar port {port}: {', '.join(owners)}")

public = [item for item in sidecars if isinstance(item, dict) and item.get("public") is True]
public_ids = [item.get("id") for item in public]
if public_ids != ["lof"]:
    errors.append(f"public sidecar should be exactly ['lof']; got {public_ids}")
lof = next((item for item in sidecars if isinstance(item, dict) and item.get("id") == "lof"), None)
if not lof:
    errors.append("missing lof sidecar")
elif lof.get("port") != 8093:
    errors.append(f"lof sidecar must own public port 8093; got {lof.get('port')}")

sidecar_ids = set(ids)
cap_ids = [item.get("id") for item in capabilities if isinstance(item, dict)]
for cid in sorted({x for x in cap_ids if cap_ids.count(x) > 1}):
    errors.append(f"duplicate capability id: {cid}")
for item in capabilities:
    if not isinstance(item, dict):
        errors.append("capabilities.json contains non-object item")
        continue
    cid = str(item.get("id") or "")
    service_id = item.get("service_id")
    if service_id and service_id not in sidecar_ids:
        errors.append(f"capability {cid}: unknown service_id {service_id}")
    entry = item.get("entry_url")
    if entry is not None and (not isinstance(entry, str) or not entry.startswith("/")):
        errors.append(f"capability {cid}: entry_url must be null or absolute path")
    commands = item.get("commands") or []
    if not isinstance(commands, list):
        errors.append(f"capability {cid}: commands must be a list")

required_sources = {
    "lof-sidecar-rs": "Cargo.toml",
    "notify-sidecar-rs": "Cargo.toml",
    "qq-sidecar-rs": "Cargo.toml",
    "nanobot-reflexio-rs": "Cargo.toml",
    "obp-rs": "Cargo.toml",
    "trend-sidecar-rs": "Cargo.toml",
    "wechat-rss-rs": "Cargo.toml",
}
for name, marker in required_sources.items():
    require_file(ops / "sources" / name / marker, f"source {name}/{marker}")

for path in [
    ops / "sources" / "wechat-rss-rs" / "src" / "paid_cleaner.rs",
    ops / "sources" / "wechat-rss-rs" / "src" / "markdown.rs",
    ops / "sources" / "wechat-rss-rs" / "src" / "pages.rs",
    ops / "sources" / "wechat-rss-rs" / "src" / "settings.rs",
    ops / "sources" / "wechat-rss-rs" / "src" / "yage.rs",
    ops / "sources" / "lof-sidecar-rs" / "src" / "pages.rs",
    ops / "sources" / "lof-sidecar-rs" / "src" / "lof_domain.rs",
    ops / "sources" / "lof-sidecar-rs" / "src" / "reverse_proxy.rs",
    ops / "sources" / "lof-sidecar-rs" / "src" / "sidecar_manager.rs",
    ops / "sources" / "lof-sidecar-rs" / "src" / "system_metrics.rs",
    ops / "sources" / "obp-rs" / "src" / "protocol.rs",
]:
    require_file(path, "architecture module seam")


sync_script = ops / "scripts" / "sync-to-live.sh"
deploy_script = ops / "scripts" / "deploy-sidecar.sh"
smoke_common = ops / "scripts" / "smoke_common.py"
smoke_scripts = [ops / "scripts" / "smoke-sidecars.py", ops / "scripts" / "smoke-model-switch.py"]
require_file(sync_script, "live ops sync script")
require_file(deploy_script, "sidecar deploy script")
require_file(smoke_common, "shared smoke helper")
for script in smoke_scripts:
    require_file(script, "smoke script")
if sync_script.exists():
    sync_text = sync_script.read_text(encoding="utf-8", errors="replace")
    for token in ["--check", "--apply", "rsync", "/root/nanobot-ops"]:
        if token not in sync_text:
            errors.append(f"ops/scripts/sync-to-live.sh missing {token}")
if deploy_script.exists():
    deploy_text = deploy_script.read_text(encoding="utf-8", errors="replace")
    if "sync-to-live.sh" not in deploy_text or "--skip-sync-check" not in deploy_text:
        errors.append("ops/scripts/deploy-sidecar.sh must guard /root/nanobot-ops drift")
if smoke_common.exists():
    common_text = smoke_common.read_text(encoding="utf-8", errors="replace")
    for token in ["http_json", "CheckResult", "run_command"]:
        if token not in common_text:
            errors.append(f"ops/scripts/smoke_common.py missing {token}")
for script in smoke_scripts:
    if script.exists() and "smoke_common" not in script.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"{rel(script)} must use ops/scripts/smoke_common.py")

for unit in units:
    path = ops / "systemd" / unit
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if "[Service]" in text and "Restart=" not in text and unit != "podman-port-forward-allow.service":
        warnings.append(f"{unit}: no Restart= configured")

print("Architecture check")
print(f"repo: {root}")
print(f"sidecars: {len(sidecars)} capabilities: {len(capabilities)}")
if warnings:
    print("warnings:")
    for item in warnings:
        print(f"  - {item}")
if errors:
    print("errors:")
    for item in errors:
        print(f"  - {item}")
    sys.exit(1)
print("ok")
PY
