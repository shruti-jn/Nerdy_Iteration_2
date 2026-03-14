"""
Persistent session store with in-memory cache and JSON file backup.

Enables session recovery after page refresh: sessions are kept in memory
for fast access and written to disk as JSON after each turn for crash
recovery. Sessions expire after a configurable TTL (default 1 hour).

Pipeline stage: Session Persistence (supports reconnection in main.py)

Exports:
    SessionStore -- In-memory + disk session store with TTL expiry
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("tutor")

# Default time-to-live for persisted sessions (seconds)
_DEFAULT_TTL = 3600  # 1 hour

# Directory for session JSON files (relative to backend/)
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sessions")


class SessionStore:
    """In-memory session store with JSON file backup and TTL expiry.

    Sessions are keyed by ``session_id``. Each save writes the session
    dict to both the in-memory cache and a JSON file on disk. Expired
    sessions are pruned lazily on ``save()`` and ``load()``.

    Args:
        ttl:      Time-to-live in seconds (default 3600 = 1 hour).
        data_dir: Directory for JSON backup files. Created if missing.

    Thread safety:
        All mutations are protected by an asyncio.Lock.
    """

    def __init__(
        self,
        ttl: int = _DEFAULT_TTL,
        data_dir: str = _DATA_DIR,
    ) -> None:
        self._ttl = ttl
        self._data_dir = data_dir
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        os.makedirs(self._data_dir, exist_ok=True)

    def _file_path(self, session_id: str) -> str:
        """Return the JSON file path for a given session ID."""
        # Sanitize session_id to prevent path traversal
        safe_id = session_id.replace("/", "_").replace("..", "_")
        return os.path.join(self._data_dir, f"{safe_id}.json")

    def _is_expired(self, session_data: dict) -> bool:
        """Check whether a session has exceeded its TTL."""
        updated_at = session_data.get("updated_at", 0)
        return (time.time() - updated_at) > self._ttl

    async def save(
        self,
        session_id: str,
        session_state: dict,
        topic: str,
    ) -> None:
        """Persist a session to memory and disk.

        Args:
            session_id:    Unique session identifier.
            session_state: Dict from ``SessionManager.to_dict()``.
            topic:         Topic identifier (e.g. "photosynthesis").
        """
        async with self._lock:
            now = time.time()
            record = {
                "session_id": session_id,
                "topic": topic,
                "created_at": self._sessions.get(session_id, {}).get("created_at", now),
                "updated_at": now,
                **session_state,
            }
            self._sessions[session_id] = record

            # Write to disk
            try:
                file_path = self._file_path(session_id)
                with open(file_path, "w") as f:
                    json.dump(record, f, indent=2)
            except OSError as exc:
                logger.warning(
                    "session_store_write_failed session_id=%s error=%s",
                    session_id,
                    exc,
                )

            # Lazy cleanup: prune expired sessions
            await self._cleanup_unlocked()

    async def load(self, session_id: str) -> dict | None:
        """Load a session from memory or disk.

        Returns the session dict if found and not expired, else None.

        Args:
            session_id: Unique session identifier.

        Returns:
            Session dict or None if not found / expired.
        """
        async with self._lock:
            # Check memory first
            record = self._sessions.get(session_id)
            if record is not None:
                if self._is_expired(record):
                    await self._delete_unlocked(session_id)
                    return None
                return dict(record)

            # Fall back to disk
            file_path = self._file_path(session_id)
            if not os.path.exists(file_path):
                return None

            try:
                with open(file_path) as f:
                    record = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "session_store_read_failed session_id=%s error=%s",
                    session_id,
                    exc,
                )
                return None

            if self._is_expired(record):
                await self._delete_unlocked(session_id)
                return None

            # Cache in memory
            self._sessions[session_id] = record
            return dict(record)

    async def delete(self, session_id: str) -> None:
        """Remove a session from memory and disk.

        Args:
            session_id: Unique session identifier.
        """
        async with self._lock:
            await self._delete_unlocked(session_id)

    async def _delete_unlocked(self, session_id: str) -> None:
        """Internal delete — caller must hold the lock."""
        self._sessions.pop(session_id, None)
        file_path = self._file_path(session_id)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as exc:
            logger.warning(
                "session_store_delete_failed session_id=%s error=%s",
                session_id,
                exc,
            )

    async def _cleanup_unlocked(self) -> None:
        """Prune expired sessions — caller must hold the lock."""
        expired = [
            sid
            for sid, data in self._sessions.items()
            if self._is_expired(data)
        ]
        for sid in expired:
            await self._delete_unlocked(sid)
        if expired:
            logger.info("session_store_cleanup pruned=%d", len(expired))
