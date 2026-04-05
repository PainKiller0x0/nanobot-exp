"""SQLite storage layer for session persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


class SessionStore:
    """
    SQLite-backed session store.
    Falls back to JSONL-only mode when DB is unavailable.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT NOT NULL PRIMARY KEY,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata TEXT,
                    last_consolidated INTEGER DEFAULT 0
                )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT,
                    extra TEXT
                )"""
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_key ON messages(key)"
            )
            logger.debug("SessionStore initialized at {}", self.db_path)
        except sqlite3.Error as e:
            logger.warning("SessionStore DB init failed: {}, falling back to JSONL only", e)
            self._conn = None

    @property
    def available(self) -> bool:
        return self._conn is not None

    def load_session(self, key: str) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        """Load session metadata + messages by key. Returns None if not found or DB unavailable."""
        if not self._conn:
            return None
        try:
            cur = self._conn.execute(
                "SELECT created_at, updated_at, metadata, last_consolidated FROM sessions WHERE key = ?",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None

            created_at, updated_at, metadata_json, last_consolidated = row
            full_meta = json.loads(metadata_json) if metadata_json else {}
            messages = []
            msg_cur = self._conn.execute(
                "SELECT role, content, timestamp, extra FROM messages WHERE key = ? ORDER BY id",
                (key,),
            )
            for m_row in msg_cur.fetchall():
                role, content, timestamp, extra = m_row
                msg: dict[str, Any] = {"role": role, "content": content, "timestamp": timestamp}
                if extra:
                    msg.update(json.loads(extra))
                messages.append(msg)

            result_metadata = {
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": full_meta.get("metadata", {}),
                "last_consolidated": last_consolidated,
            }
            return result_metadata, messages
        except sqlite3.Error as e:
            logger.warning("SessionStore load failed for {}: {}", key, e)
            self._conn = None
            return None

    def save_session(
        self,
        key: str,
        metadata: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> bool:
        """Save full session. Returns True on success, False on failure (falls back silently)."""
        if not self._conn:
            return False
        try:
            # Serialize metadata dict to JSON string
            meta_json = json.dumps(metadata, ensure_ascii=False)
            created_at = metadata.get("created_at") or None
            updated_at = metadata.get("updated_at") or None
            last_consolidated = metadata.get("last_consolidated", 0)

            self._conn.execute("BEGIN")
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (key, created_at, updated_at, metadata, last_consolidated) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, created_at, updated_at, meta_json, last_consolidated),
            )
            self._conn.execute("DELETE FROM messages WHERE key = ?", (key,))
            for msg in messages:
                role = str(msg.get("role", ""))
                content = str(msg.get("content", ""))
                timestamp = str(msg.get("timestamp", datetime.now().isoformat()))
                extra_keys = {k: v for k, v in msg.items() if k not in ("role", "content", "timestamp")}
                extra_json = json.dumps(extra_keys, ensure_ascii=False) if extra_keys else None
                self._conn.execute(
                    "INSERT INTO messages (key, role, content, timestamp, extra) VALUES (?, ?, ?, ?, ?)",
                    (key, role, content, timestamp, extra_json),
                )
            self._conn.execute("COMMIT")
            return True
        except sqlite3.Error as e:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("SessionStore save failed for {}: {}", key, e)
            self._conn = None
            return False
        except (TypeError, ValueError) as e:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("SessionStore save serialization failed for {}: {}", key, e)
            self._conn = None
            return False
