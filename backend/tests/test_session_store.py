"""
Tests for the SessionStore (in-memory + JSON backup with TTL).

Covers:
  - Save/load roundtrip (memory and disk)
  - TTL expiry
  - Cleanup of expired sessions
  - Disk persistence and recovery
  - Delete behavior

Pipeline stage: Session Persistence
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

from pipeline.session_store import SessionStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _sample_state(turn_count: int = 2) -> dict:
    """Create a minimal session state dict (like SessionManager.to_dict())."""
    return {
        "history": [
            {"role": "user", "content": f"Q{i}"}
            if i % 2 == 0
            else {"role": "assistant", "content": f"A{i}?"}
            for i in range(turn_count * 2)
        ],
        "summary": "",
        "turn_count": turn_count,
        "turns_since_compression": turn_count,
    }


# ── Tests ────────────────────────────────────────────────────────────────


class TestSaveAndLoad:
    """Basic save/load roundtrip."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        state = _sample_state()
        await store.save("sess-1", state, "photosynthesis")

        loaded = await store.load("sess-1")
        assert loaded is not None
        assert loaded["topic"] == "photosynthesis"
        assert loaded["turn_count"] == 2
        assert len(loaded["history"]) == 4

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        assert await store.load("no-such-session") is None

    @pytest.mark.asyncio
    async def test_save_overwrites_previous(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(1), "photosynthesis")
        await store.save("sess-1", _sample_state(3), "photosynthesis")

        loaded = await store.load("sess-1")
        assert loaded is not None
        assert loaded["turn_count"] == 3


class TestDiskPersistence:
    """Verify JSON files are written and can be read back."""

    @pytest.mark.asyncio
    async def test_json_file_created(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(), "photosynthesis")

        file_path = tmp_path / "sess-1.json"
        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert data["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_load_from_disk_after_memory_clear(self, tmp_path):
        """Simulate server restart: clear memory, load from disk."""
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(), "photosynthesis")

        # Clear in-memory cache to simulate restart
        store._sessions.clear()

        loaded = await store.load("sess-1")
        assert loaded is not None
        assert loaded["topic"] == "photosynthesis"
        assert loaded["turn_count"] == 2


class TestTTLExpiry:
    """Verify sessions expire after TTL."""

    @pytest.mark.asyncio
    async def test_expired_session_returns_none(self, tmp_path):
        store = SessionStore(ttl=1, data_dir=str(tmp_path))  # 1 second TTL
        await store.save("sess-1", _sample_state(), "photosynthesis")

        # Manually set updated_at to the past
        store._sessions["sess-1"]["updated_at"] = time.time() - 2

        loaded = await store.load("sess-1")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_fresh_session_not_expired(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(), "photosynthesis")

        loaded = await store.load("sess-1")
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_expired_disk_file_returns_none(self, tmp_path):
        store = SessionStore(ttl=1, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(), "photosynthesis")

        # Clear memory, backdate the disk file
        store._sessions.clear()
        file_path = tmp_path / "sess-1.json"
        with open(file_path) as f:
            data = json.load(f)
        data["updated_at"] = time.time() - 2
        with open(file_path, "w") as f:
            json.dump(data, f)

        loaded = await store.load("sess-1")
        assert loaded is None


class TestDelete:
    """Verify deletion from memory and disk."""

    @pytest.mark.asyncio
    async def test_delete_removes_from_memory_and_disk(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        await store.save("sess-1", _sample_state(), "photosynthesis")

        await store.delete("sess-1")

        assert await store.load("sess-1") is None
        assert not (tmp_path / "sess-1.json").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_safe(self, tmp_path):
        store = SessionStore(ttl=3600, data_dir=str(tmp_path))
        # Should not raise
        await store.delete("no-such-session")


class TestCleanup:
    """Verify expired sessions are cleaned up on save."""

    @pytest.mark.asyncio
    async def test_cleanup_prunes_expired_on_save(self, tmp_path):
        store = SessionStore(ttl=1, data_dir=str(tmp_path))
        await store.save("old-1", _sample_state(), "photosynthesis")
        await store.save("old-2", _sample_state(), "newtons_laws")

        # Backdate both sessions
        for sid in ["old-1", "old-2"]:
            store._sessions[sid]["updated_at"] = time.time() - 2

        # Save a new session — triggers cleanup
        await store.save("fresh", _sample_state(), "photosynthesis")

        assert await store.load("old-1") is None
        assert await store.load("old-2") is None
        assert await store.load("fresh") is not None
