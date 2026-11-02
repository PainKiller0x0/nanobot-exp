#!/usr/bin/env python3
"""Install and verify the restricted Shenzhen Home Assistant climate bridge."""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/nanobot")
SOURCE_DIR = ROOT / "ops" / "sources" / "homeassistant-climate"
BRIDGE_SOURCE = SOURCE_DIR / "homeassistant_climate.py"
SKILL_SOURCE = SOURCE_DIR / "SKILL.md"
BRIDGE_DEST = ROOT / "nanobot" / "exp" / "agent" / "homeassistant_climate.py"
SKILL_DEST = Path("/root/.nanobot/workspace/skills/home-assistant/SKILL.md")
GATEWAY = ROOT / "nanobot" / "cli" / "gateway_runtime.py"
TOKEN_FILE = Path("/root/.nanobot/secrets/homeassistant-token")

REGISTRATION_ANCHOR = "        recovery_admission=recovery,\n    )\n"
REGISTRATION_TEXT = (
    "    if \"home_assistant\" in config.tools.mcp_servers:\n"
    "        from nanobot.exp.agent.homeassistant_climate import (\n"
    "            HomeAssistantClimateControlTool,\n"
    "            token_file_is_private,\n"
    "        )\n"
    "        if token_file_is_private():\n"
    "            tools.register(HomeAssistantClimateControlTool())\n"
    "            logger.info(\"Registered restricted Shenzhen Home Assistant climate tool\")\n"
)
OLD_IMPORT_TEXT = (
    "from nanobot.exp.agent.homeassistant_climate import (\n"
    "    HomeAssistantClimateControlTool,\n"
    "    token_file_is_private,\n"
    ")\n"
)
OLD_REGISTRATION_TEXT = (
    "    if \"home_assistant\" in config.tools.mcp_servers and token_file_is_private():\n"
    "        tools.register(HomeAssistantClimateControlTool())\n"
    "        logger.info(\"Registered restricted Shenzhen Home Assistant climate tool\")\n"
)


def fail(message: str) -> None:
    raise SystemExit(f"HA climate bridge: {message}")


def patched_gateway(text: str) -> tuple[str, bool]:
    if REGISTRATION_TEXT in text:
        return text, False
    has_old_import = OLD_IMPORT_TEXT in text
    has_old_registration = OLD_REGISTRATION_TEXT in text
    if has_old_import or has_old_registration:
        if not (has_old_import and has_old_registration):
            fail("gateway climate bridge seam is incomplete; refusing to patch")
        text = text.replace(OLD_IMPORT_TEXT, "", 1)
        text = text.replace(OLD_REGISTRATION_TEXT, REGISTRATION_TEXT, 1)
        return text, True
    if "HomeAssistantClimateControlTool" in text or "token_file_is_private" in text:
        fail("unknown gateway climate bridge edits found; refusing to patch")
    if text.count(REGISTRATION_ANCHOR) != 1:
        fail("gateway agent construction anchor changed; refusing to patch")
    return text.replace(REGISTRATION_ANCHOR, REGISTRATION_ANCHOR + REGISTRATION_TEXT, 1), True


def backup_targets(paths: list[Path]) -> Path:
    root = ROOT / "ops" / "backups"
    stamp = datetime.now().strftime("ha-climate-install-%Y%m%dT%H%M%S")
    directory = root / stamp
    suffix = 1
    while directory.exists():
        directory = root / f"{stamp}-{suffix}"
        suffix += 1
    directory.mkdir(parents=True)
    for path in paths:
        if path.is_file():
            shutil.copy2(path, directory / path.name)
    return directory


def check_install() -> None:
    for path in (BRIDGE_SOURCE, SKILL_SOURCE, BRIDGE_DEST, SKILL_DEST, GATEWAY):
        if not path.is_file():
            fail(f"missing file: {path}")
    if BRIDGE_DEST.read_bytes() != BRIDGE_SOURCE.read_bytes():
        fail("installed bridge differs from canonical source")
    if SKILL_DEST.read_bytes() != SKILL_SOURCE.read_bytes():
        fail("installed skill differs from canonical source")
    gateway = GATEWAY.read_text(encoding="utf-8")
    patched, changed = patched_gateway(gateway)
    if changed or patched != gateway:
        fail("gateway bridge seam is not installed")
    try:
        mode = TOKEN_FILE.stat().st_mode & 0o777
    except OSError:
        fail("root-only HA token file is unavailable")
    if mode & 0o077:
        fail("HA token file permissions are not owner-only")
    print("HA climate bridge check OK")


def install() -> None:
    for path in (BRIDGE_SOURCE, SKILL_SOURCE, GATEWAY):
        if not path.is_file():
            fail(f"missing source or gateway file: {path}")
    gateway_text, gateway_changed = patched_gateway(GATEWAY.read_text(encoding="utf-8"))
    changed = (
        gateway_changed
        or not BRIDGE_DEST.is_file()
        or BRIDGE_DEST.read_bytes() != BRIDGE_SOURCE.read_bytes()
        or not SKILL_DEST.is_file()
        or SKILL_DEST.read_bytes() != SKILL_SOURCE.read_bytes()
    )
    if not changed:
        check_install()
        return

    backup_dir = backup_targets([GATEWAY, BRIDGE_DEST, SKILL_DEST])
    BRIDGE_DEST.parent.mkdir(parents=True, exist_ok=True)
    SKILL_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BRIDGE_SOURCE, BRIDGE_DEST)
    shutil.copy2(SKILL_SOURCE, SKILL_DEST)
    if gateway_changed:
        GATEWAY.write_text(gateway_text, encoding="utf-8")
    print(f"HA climate bridge installed; backup: {backup_dir}")
    check_install()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_install()
    else:
        install()


if __name__ == "__main__":
    main()
