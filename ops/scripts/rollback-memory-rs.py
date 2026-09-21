#!/usr/bin/env python3
"""Rollback the Memory-RS glue from the backup created during installation.

Default mode only restores the Nanobot Python glue.  ``--restore-legacy`` also
restores the saved dashboard/service wiring and starts the retained Reflexio
service.  It intentionally does not delete Memory-RS data.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


ROOT = Path("/root/nanobot")
BACKUP = Path("/root/.nanobot/backups/memory-rs")
COMMANDS = ROOT / "nanobot/cli/commands.py"
IMPORT = "    from nanobot.exp.agent.memory_bridge import build_memory_hook\n"
HOOK = "hooks=[TokenUsageHook(timezone_name=config.agents.defaults.timezone)],"
HOOK_REPLACEMENT = "hooks=[TokenUsageHook(timezone_name=config.agents.defaults.timezone), build_memory_hook()],"


def restore_file(relative: str, destination: Path) -> None:
    source = BACKUP / relative
    if not source.exists():
        raise SystemExit(f"memory-rs rollback: missing backup {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def restore_glue() -> None:
    for relative, destination in {
        "commands.py": COMMANDS,
        "memory_client.py": ROOT / "nanobot/agent/memory_client.py",
        "memory_formatters.py": ROOT / "nanobot/agent/memory_formatters.py",
    }.items():
        restore_file(relative, destination)


def restore_legacy_runtime() -> None:
    restore_file("sidecars.json", ROOT / "ops/config/sidecars.json")
    restore_file("capabilities.json", ROOT / "ops/config/capabilities.json")
    restore_file("podman-nanobot-cage.service", ROOT / "ops/systemd/podman-nanobot-cage.service")
    restore_file("nanobot-stack.target", ROOT / "ops/systemd/nanobot-stack.target")
    shutil.copy2(BACKUP / "sidecars.json", Path("/root/.nanobot/sidecars.json"))
    shutil.copy2(BACKUP / "capabilities.json", Path("/root/.nanobot/capabilities.json"))
    shutil.copy2(BACKUP / "podman-nanobot-cage.service", Path("/etc/systemd/system/podman-nanobot-cage.service"))
    shutil.copy2(BACKUP / "nanobot-stack.target", Path("/etc/systemd/system/nanobot-stack.target"))
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "nanobot-reflexio-rs.service"], check=True)
    subprocess.run(["systemctl", "restart", "lof-sidecar.service"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-legacy", action="store_true", help="Restore old dashboard/service wiring and start Reflexio")
    args = parser.parse_args()
    restore_glue()
    if args.restore_legacy:
        restore_legacy_runtime()
    print("memory-rs rollback prepared; restart podman-nanobot-cage.service to apply Python glue restoration")


if __name__ == "__main__":
    main()
