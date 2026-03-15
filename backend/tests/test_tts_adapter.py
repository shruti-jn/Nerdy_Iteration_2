"""
Tests for the DeepgramTTSAdapter.

Unit tests mock the Deepgram SDK to validate audio streaming, TTFA
recording, error wrapping, empty text handling, and cooperative cancellation.
One integration test makes a real Deepgram API call (requires DEEPGRAM_API_KEY).

Pipeline stage: TTS (Stage 3)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.tts_adapter import DeepgramTTSAdapter, _normalize_tts_text
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mock_audio_stream(*chunks):
    """Create an async iterable of audio byte chunks."""
    for chunk in chunks:
        yield chunk


@dataclass
class _FakeSettings:
    deepgram_api_key: str = "test-deepgram-key"


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------

class TestDeepgramTTSAdapterStream:
    """Tests for the streaming TTS synthesis."""

    @pytest.mark.asyncio
    async def test_yields_audio_bytes(self):
        """stream() yields all audio chunks from the SDK."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        chunk1, chunk2 = b"\x00" * 1600, b"\x01" * 1600
        adapter._client.speak.v1.audio.generate = MagicMock(
            return_value=_mock_audio_stream(chunk1, chunk2)
        )

        chunks = []
        async for chunk in adapter.stream("Hello world.", mc):
            chunks.append(chunk)

        assert chunks == [chunk1, chunk2]

    @pytest.mark.asyncio
    async def test_records_ttfa(self):
        """stream() records TTFA via metrics.mark_first('tts')."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.speak.v1.audio.generate = MagicMock(
            return_value=_mock_audio_stream(b"\x00" * 100)
        )

        async for _ in adapter.stream("Test.", mc):
            pass

        stage = mc.get_stage("tts")
        assert stage is not None
        assert stage.time_to_first_ms is not None

    @pytest.mark.asyncio
    async def test_records_duration(self):
        """stream() records total duration via metrics.end('tts')."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.speak.v1.audio.generate = MagicMock(
            return_value=_mock_audio_stream(b"\x00" * 100, b"\x01" * 100)
        )

        async for _ in adapter.stream("Test.", mc):
            pass

        stage = mc.get_stage("tts")
        assert stage is not None
        assert stage.duration_ms is not None

    @pytest.mark.asyncio
    async def test_empty_text_returns_immediately(self):
        """stream() yields nothing for empty text."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        chunks = []
        async for chunk in adapter.stream("", mc):
            chunks.append(chunk)

        assert chunks == []
        assert mc.get_stage("tts") is None

    @pytest.mark.asyncio
    async def test_whitespace_text_returns_immediately(self):
        """stream() yields nothing for whitespace-only text."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        chunks = []
        async for chunk in adapter.stream("   ", mc):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_wraps_sdk_error(self):
        """stream() wraps SDK exceptions into AdapterError."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.speak.v1.audio.generate = MagicMock(
            side_effect=Exception("connection failed")
        )

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream("Hello.", mc):
                pass

        assert exc_info.value.stage == "tts"
        assert exc_info.value.provider == "deepgram"

    @pytest.mark.asyncio
    async def test_cancel_stops_iteration(self):
        """cancel() causes stream() to stop yielding audio."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        async def _slow_audio():
            for i in range(10):
                yield bytes([i]) * 100
                await asyncio.sleep(0.01)

        adapter._client.speak.v1.audio.generate = MagicMock(return_value=_slow_audio())

        chunks = []
        async for chunk in adapter.stream("Hello world.", mc):
            chunks.append(chunk)
            if len(chunks) == 2:
                await adapter.cancel()

        assert len(chunks) <= 3

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_sdk(self):
        """stream() passes model, encoding, container, sample_rate to the SDK."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        mock_generate = MagicMock(return_value=_mock_audio_stream(b"\x00"))
        adapter._client.speak.v1.audio.generate = mock_generate

        async for _ in adapter.stream("Test.", mc):
            pass

        mock_generate.assert_called_once_with(
            text="Test.",
            model="aura-2-asteria-en",
            encoding="linear16",
            container="none",
            sample_rate=16000,
        )

    @pytest.mark.asyncio
    async def test_normalizes_brand_name_for_tts_only(self):
        """stream() aliases the tutor brand for speech synthesis."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        mock_generate = MagicMock(return_value=_mock_audio_stream(b"\x00"))
        adapter._client.speak.v1.audio.generate = mock_generate

        async for _ in adapter.stream("Hi, I am Socrates VI.", mc):
            pass

        mock_generate.assert_called_once_with(
            text="Hi, I am Socrates Six.",
            model="aura-2-asteria-en",
            encoding="linear16",
            container="none",
            sample_rate=16000,
        )

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent(self):
        """cancel() can be called multiple times without error."""
        adapter = DeepgramTTSAdapter(_FakeSettings())
        await adapter.cancel()
        await adapter.cancel()  # Should not raise


def test_normalize_tts_text_only_aliases_tutor_brand():
    """Normalization rewrites the spoken tutor name without touching other numerals."""
    assert _normalize_tts_text("Socrates VI") == "Socrates Six"
    assert _normalize_tts_text("Chapter VI starts now.") == "Chapter VI starts now."


# ---------------------------------------------------------------------------
# Integration test (requires DEEPGRAM_API_KEY in env)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_deepgram_tts_real_streaming():
    """Integration: stream real audio from Deepgram Aura API.

    Requires DEEPGRAM_API_KEY in the environment. Validates that real
    audio bytes are yielded and TTFA is recorded.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        pytest.skip("DEEPGRAM_API_KEY not set")

    @dataclass
    class _RealSettings:
        deepgram_api_key: str = api_key

    adapter = DeepgramTTSAdapter(_RealSettings())
    mc = MetricsCollector()

    chunks = []
    async for chunk in adapter.stream("Hello, this is a test.", mc):
        chunks.append(chunk)
        if len(chunks) > 50:
            break

    assert len(chunks) > 0
    assert all(isinstance(c, bytes) for c in chunks)
    stage = mc.get_stage("tts")
    assert stage is not None
    assert stage.time_to_first_ms is not None
