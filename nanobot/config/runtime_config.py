"""Runtime configuration manager with hot-reload support.

Loads a separate YAML config (~/.nanobot/runtime_config.yaml) that overrides
schema defaults for runtime-tunable parameters (compression, context, etc.).

Usage:
    from nanobot.config.runtime_config import runtime_config

    # Get a value (returns default if key not in yaml)
    threshold = runtime_config.get("compaction.threshold", 0.75)

    # Access all overrides (returns full dict)
    overrides = runtime_config.overrides

    # Check if hot-reload is running
    runtime_config.is_running()
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

# Default values (mirror of schema defaults)
_DEFAULTS: dict[str, Any] = {
    # CompactionConfig
    "compaction.threshold": 0.75,
    "compaction.target": 0.35,
    "compaction.preserve_recent": 4,
    "compaction.safety_buffer": 1024,
    # AgentDefaults
    "agent.context_window_tokens": 204_800,
    "agent.max_tool_iterations": 40,
    "agent.temperature": 0.1,
    # HeartbeatConfig
    "heartbeat.interval_s": 1800,
    "heartbeat.keep_recent_messages": 8,
    # ConsolidationMeta
    "consolidation.threshold_hours": 1.0,
    # Logging
    "log.level": None,
    # Memory consolidation tool
    "consolidation.compress_threshold_lines": 100,
}

# Config file path
_CONFIG_PATH = Path.home() / ".nanobot" / "runtime_config.yaml"


class RuntimeConfigManager:
    """Singleton runtime config manager with hot-reload via mtime polling."""

    _instance: "RuntimeConfigManager | None" = None
    _lock = threading.Lock()

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or _CONFIG_PATH
        self._overrides: dict[str, Any] = {}
        self._last_mtime: float = 0
        self._poll_interval = 2.0  # seconds
        self._running = False
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._listeners: list[callable] = []
        self._listeners_lock = threading.Lock()
        self._load()

    @classmethod
    def get_instance(cls, config_path: Path | None = None) -> "RuntimeConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config_path)
        return cls._instance

    def _load(self) -> None:
        """Load (or reload) the YAML config file."""
        if not self.config_path.exists():
            self._overrides = {}
            self._last_mtime = 0
            return

        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._overrides = self._flatten(data)
            self._last_mtime = self.config_path.stat().st_mtime
            logger.debug("RuntimeConfig loaded: {} overrides", len(self._overrides))
        except Exception as e:
            logger.warning("Failed to load runtime_config.yaml: {}", e)
            self._overrides = {}

    def _flatten(self, data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten nested dict into dot-notation keys."""
        result = {}
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(self._flatten(value, full_key))
            else:
                result[full_key] = value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value. Returns override if present, else default from _DEFAULTS, else provided default."""
        if key in self._overrides:
            return self._overrides[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

    @property
    def overrides(self) -> dict[str, Any]:
        """Return all loaded overrides (for debugging/inspection)."""
        return dict(self._overrides)

    def reload(self) -> None:
        """Force reload from disk."""
        self._load()
        self._notify()

    def _notify(self) -> None:
        with self._listeners_lock:
            for cb in self._listeners:
                try:
                    cb(self._overrides)
                except Exception as e:
                    logger.warning("RuntimeConfig listener error: {}", e)

    def add_listener(self, cb: callable) -> None:
        """Register a callback called whenever config reloads."""
        with self._listeners_lock:
            self._listeners.append(cb)

    def start_polling(self) -> None:
        """Start background polling thread for hot-reload."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="RuntimeConfigPoll")
        self._poll_thread.start()
        logger.info("RuntimeConfig hot-reload polling started (path={})", self.config_path)

    def _poll_loop(self) -> None:
        """Polling loop runs in background thread."""
        while not self._stop_event.is_set():
            try:
                if self.config_path.exists():
                    mtime = self.config_path.stat().st_mtime
                    if mtime != self._last_mtime:
                        logger.info("RuntimeConfig file changed, reloading...")
                        self._load()
                        self._notify()
            except Exception as e:
                logger.debug("RuntimeConfig poll error: {}", e)
            self._stop_event.wait(self._poll_interval)

    def stop_polling(self) -> None:
        """Stop background polling."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        logger.info("RuntimeConfig hot-reload polling stopped")

    def is_running(self) -> bool:
        return self._running


# -------------------------------------------------------------------
# Global singleton accessor
# -------------------------------------------------------------------

def _get_runtime_config() -> RuntimeConfigManager:
    manager = RuntimeConfigManager.get_instance()
    manager.start_polling()  # start hot-reload polling on first access
    return manager


# Expose singleton instance
runtime_config = _get_runtime_config()
