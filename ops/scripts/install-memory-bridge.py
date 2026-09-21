#!/usr/bin/env python3
"""Install or verify the intentionally tiny Nanobot memory-rs hook seam.

The script uses exact anchors. If upstream changes the gateway composition it
fails before a restart rather than guessing and silently corrupting the patch.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path('/root/nanobot')
BRIDGE_SOURCE = ROOT / 'ops' / 'sources' / 'memory-rs' / 'memory_bridge.py'
BRIDGE_DEST = ROOT / 'nanobot' / 'exp' / 'agent' / 'memory_bridge.py'
COMMANDS = ROOT / 'nanobot' / 'cli' / 'commands.py'
IMPORT = '    from nanobot.exp.agent.memory_bridge import build_memory_hook\n'
MALFORMED_IMPORT = 'from nanobot.exp.agent.memory_bridge import build_memory_hook\n'
ANCHOR = '    from nanobot.webui.token_usage import TokenUsageHook\n'
HOOK = 'hooks=[TokenUsageHook(timezone_name=config.agents.defaults.timezone)],'
HOOK_REPLACEMENT = 'hooks=[TokenUsageHook(timezone_name=config.agents.defaults.timezone), build_memory_hook()],'


def fail(message: str) -> None:
    raise SystemExit(f'memory-rs bridge: {message}')


def patch_commands(write: bool) -> bool:
    text = COMMANDS.read_text(encoding='utf-8')
    changed = False
    if f"\n{MALFORMED_IMPORT}" in f"\n{text}":
        text = text.replace(f"\n{MALFORMED_IMPORT}", f"\n{IMPORT}", 1)
        changed = True
    if IMPORT not in text:
        if ANCHOR not in text:
            fail('upstream TokenUsageHook import anchor changed; refusing to patch')
        text = text.replace(ANCHOR, ANCHOR + IMPORT, 1)
        changed = True
    if HOOK_REPLACEMENT not in text:
        if HOOK not in text:
            fail('upstream hook composition anchor changed; refusing to patch')
        text = text.replace(HOOK, HOOK_REPLACEMENT, 1)
        changed = True
    if write and changed:
        backup = COMMANDS.with_suffix('.py.memory-rs.bak')
        if not backup.exists():
            shutil.copy2(COMMANDS, backup)
        COMMANDS.write_text(text, encoding='utf-8')
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not BRIDGE_SOURCE.exists():
        fail(f'missing bridge source: {BRIDGE_SOURCE}')
    if args.check:
        if patch_commands(False):
            fail('bridge anchor is present but installation is incomplete; run installer before restart')
        if not BRIDGE_DEST.exists():
            fail(f'missing installed bridge: {BRIDGE_DEST}')
        print('memory-rs bridge check OK')
        return
    BRIDGE_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BRIDGE_SOURCE, BRIDGE_DEST)
    patch_commands(True)
    print('memory-rs bridge installed')


if __name__ == '__main__':
    main()
