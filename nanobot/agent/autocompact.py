"""Auto compact: proactive compression of idle sessions to reduce token cost and latency."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Collection
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class AutoCompact:
    _RECENT_SUFFIX_MESSAGES = 8
    _DEFER_META_KEY = "_auto_compact_defer"
    _MIN_MESSAGES_PER_PERIOD = 5
    _MIN_MESSAGE_CAP = 60
    _MAX_DEFER_HOURS = 12
    _EVENT_PREVIEW_CHARS = 4_000
    _INTERNAL_SESSION_PREFIXES = ("dream:",)

    def __init__(self, sessions: SessionManager, consolidator: Consolidator,
                 session_ttl_minutes: int = 0):
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, tuple[str, datetime]] = {}
        try:
            workspace = self.sessions.workspace
        except AttributeError:
            workspace = Path(tempfile.gettempdir()) / "nanobot"
        self._event_file = Path(workspace) / "auto_compact_events.jsonl"

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _is_expired(self, ts: datetime | str | None,
                    now: datetime | None = None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return ((now or datetime.now()) - ts).total_seconds() >= self._ttl * 60

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        return f"Previous conversation summary (last active {last_active.isoformat()}):\n{text}"

    @classmethod
    def _message_preview(cls, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        preview: list[dict[str, str]] = []
        for message in messages[:6]:
            content = str(message.get("content", "")).replace("\n", " ").strip()
            if len(content) > 280:
                content = content[:280] + "..."
            preview.append({
                "role": str(message.get("role", "")),
                "content": content,
            })
        return preview

    def _write_event(self, action: str, key: str, **fields: Any) -> None:
        event = {
            "ts": datetime.now().isoformat(),
            "action": action,
            "key": key,
            **fields,
        }
        try:
            self._event_file.parent.mkdir(parents=True, exist_ok=True)
            with self._event_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            logger.debug("Auto-compact: failed to write event log", exc_info=True)



    def _split_unconsolidated(
        self, session: Session,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split live session tail into archiveable prefix and retained recent suffix."""
        tail = list(session.messages[session.last_consolidated:])
        if not tail:
            return [], []

        probe = Session(
            key=session.key,
            messages=tail.copy(),
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata={},
            last_consolidated=0,
        )
        probe.retain_recent_legal_suffix(self._RECENT_SUFFIX_MESSAGES)
        kept = probe.messages
        cut = len(tail) - len(kept)
        return tail[:cut], kept

    def _defer_decision(
        self,
        session: Session,
        pending_count: int,
        now: datetime,
    ) -> tuple[bool, dict[str, Any]]:
        meta = session.metadata.get(self._DEFER_META_KEY)
        defer_meta = meta if isinstance(meta, dict) else {}
        started_at = self._parse_dt(defer_meta.get("started_at")) or session.updated_at
        elapsed_seconds = max(0.0, (now - started_at).total_seconds())
        period_seconds = max(60, self._ttl * 60)
        periods = max(1, int(elapsed_seconds // period_seconds))
        threshold = min(self._MIN_MESSAGE_CAP, periods * self._MIN_MESSAGES_PER_PERIOD)
        forced = elapsed_seconds >= self._MAX_DEFER_HOURS * 3600
        should_defer = pending_count < threshold and not forced
        return should_defer, {
            "started_at": started_at.isoformat(),
            "elapsed_minutes": int(elapsed_seconds // 60),
            "periods": periods,
            "threshold_messages": threshold,
            "forced": forced,
        }

    @classmethod
    def _is_internal_session(cls, key: str) -> bool:
        return key.startswith(cls._INTERNAL_SESSION_PREFIXES)

    def check_expired(self, schedule_background: Callable[[Coroutine], None],
                      active_session_keys: Collection[str] = ()) -> None:
        """Schedule archival for idle sessions, skipping those with in-flight agent tasks."""
        now = datetime.now()
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if not key or self._is_internal_session(key) or key in self._archiving:
                continue
            if key in active_session_keys:
                continue
            if self._is_expired(info.get("updated_at"), now):
                self._archiving.add(key)
                schedule_background(self._archive(key))


    async def _archive(self, key: str) -> None:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            return
        try:
            session = self.sessions.get_or_create(key)
            defer_meta: dict[str, Any] = {}
            if isinstance(session, Session):
                pending_count = max(0, len(session.messages) - session.last_consolidated)
                if pending_count > 0:
                    should_defer, defer_meta = self._defer_decision(
                        session,
                        pending_count,
                        datetime.now(),
                    )
                    defer_meta["pending_messages"] = pending_count
                    if should_defer:
                        session.metadata[self._DEFER_META_KEY] = defer_meta
                        self.sessions.save(session)
                        self._write_event("deferred", key, **defer_meta)
                        return

            summary = await self.consolidator.compact_idle_session(
                key, self._RECENT_SUFFIX_MESSAGES,
            )
            session = self.sessions.get_or_create(key)
            session.metadata.pop(self._DEFER_META_KEY, None)
            meta = session.metadata.get("_last_summary")
            if summary and summary != "(nothing)" and isinstance(meta, dict):
                self._summaries[key] = (
                    meta["text"],
                    datetime.fromisoformat(meta["last_active"]),
                )
            self.sessions.save(session)
            self._write_event("archived", key, summary=summary, **defer_meta)
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        if self._is_internal_session(key):
            self._archiving.discard(key)
            self._summaries.pop(key, None)
            return session, None
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        # Hot path: summary from in-memory dict (process hasn't restarted).
        entry = self._summaries.pop(key, None)
        if entry:
            return session, self._format_summary(entry[0], entry[1])
        # Cold path: summary persisted in session metadata (process restarted).
        meta = session.metadata.get("_last_summary")
        if isinstance(meta, dict):
            return session, self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))
        return session, None
