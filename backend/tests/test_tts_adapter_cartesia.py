"""
Tests for CartesiaTTSAdapter.

Unit tests mock the Cartesia SDK to validate audio streaming, TTFA recording,
error wrapping, empty text handling, and cooperative cancellation.
One integration test makes a real Cartesia API call (requires CARTESIA_API_KEY).

Pipeline stage: TTS (Stage 3)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.tts_adapter import CartesiaTTSAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeSettings:
    cartesia_api_key: str = "test-cartesia-key"
    cartesia_voice_id: str = "test-voice-id"


async def _make_stream(*audio_chunks: bytes):
    """Async generator yielding mock ChunkEvent objects."""
    for audio in audio_chunks:
        event = MagicMock()
        event.type = "chunk"
        event.audio = audio
        yield event
    # Terminal done event (no audio)
    done = MagicMock()
    done.type = "done"
    done.audio = None
    yield done


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------

class TestCartesiaTTSAdapterStream:

    @pytest.mark.asyncio
    async def test_stream_returns_audio_chunks(self):
        """stream() yields all audio bytes from Cartesia SSE response."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        chunk1, chunk2 = b"\x00" * 1600, b"\x01" * 1600
        adapter._client.tts.generate_sse = AsyncMock(
            return_value=_make_stream(chunk1, chunk2)
        )

        chunks = []
        async for chunk in adapter.stream("Hello world.", mc):
            chunks.append(chunk)

        assert chunks == [chunk1, chunk2]

    @pytest.mark.asyncio
    async def test_first_byte_latency_logged(self):
        """stream() records tts_ttf_ms via metrics.mark_first('tts')."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.tts.generate_sse = AsyncMock(
            return_value=_make_stream(b"\x00" * 100)
        )

        async for _ in adapter.stream("Test.", mc):
            pass

        stage = mc.get_stage("tts")
        assert stage is not None
        assert stage.time_to_first_ms is not None

    @pytest.mark.asyncio
    async def test_timeout_raises_adapter_error(self):
        """stream() wraps asyncio.TimeoutError into AdapterError(provider='cartesia')."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.tts.generate_sse = AsyncMock(side_effect=asyncio.TimeoutError())

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream("Test.", mc):
                pass

        assert exc_info.value.stage == "tts"
        assert exc_info.value.provider == "cartesia"

    @pytest.mark.asyncio
    async def test_connection_error_raises_adapter_error(self):
        """stream() wraps connection errors into AdapterError(stage='tts', provider='cartesia')."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        adapter._client.tts.generate_sse = AsyncMock(side_effect=Exception("connection refused"))

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream("Hello.", mc):
                pass

        assert exc_info.value.stage == "tts"
        assert exc_info.value.provider == "cartesia"

    @pytest.mark.asyncio
    async def test_empty_input_no_error(self):
        """stream() returns immediately for empty text without calling the API."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        mock_sse = AsyncMock()
        adapter._client.tts.generate_sse = mock_sse

        chunks = []
        async for chunk in adapter.stream("", mc):
            chunks.append(chunk)

        assert chunks == []
        mock_sse.assert_not_called()
        assert mc.get_stage("tts") is None

    @pytest.mark.asyncio
    async def test_cancel_stops_stream(self):
        """cancel() stops stream() after a few chunks (cooperative cancellation)."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        async def _slow_audio():
            for i in range(20):
                event = MagicMock()
                event.type = "chunk"
                event.audio = bytes([i]) * 100
                yield event
                await asyncio.sleep(0.005)

        adapter._client.tts.generate_sse = AsyncMock(return_value=_slow_audio())

        chunks = []
        async for chunk in adapter.stream("Long text here.", mc):
            chunks.append(chunk)
            if len(chunks) == 2:
                await adapter.cancel()

        assert len(chunks) <= 3

    @pytest.mark.asyncio
    async def test_skips_non_chunk_events(self):
        """stream() skips done/timestamps/error events and only yields audio."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        mc = MetricsCollector()

        async def _mixed_stream():
            # timestamps event (no audio)
            ts = MagicMock()
            ts.type = "timestamps"
            ts.audio = None
            yield ts
            # real chunk
            chunk = MagicMock()
            chunk.type = "chunk"
            chunk.audio = b"\xAA" * 800
            yield chunk
            # done event
            done = MagicMock()
            done.type = "done"
            done.audio = None
            yield done

        adapter._client.tts.generate_sse = AsyncMock(return_value=_mixed_stream())

        chunks = []
        async for chunk in adapter.stream("Test.", mc):
            chunks.append(chunk)

        assert chunks == [b"\xAA" * 800]

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_sdk(self):
        """stream() passes model, voice, output_format to Cartesia generate_sse()."""
        settings = _FakeSettings(cartesia_voice_id="my-voice-id")
        adapter = CartesiaTTSAdapter(settings)
        mc = MetricsCollector()

        mock_sse = AsyncMock(return_value=_make_stream(b"\x00"))
        adapter._client.tts.generate_sse = mock_sse

        async for _ in adapter.stream("Hello.", mc):
            pass

        mock_sse.assert_called_once_with(
            model_id="sonic-3",
            transcript="Hello.",
            voice={"id": "my-voice-id", "mode": "id"},
            output_format={"container": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
        )

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent(self):
        """cancel() can be called multiple times without error."""
        adapter = CartesiaTTSAdapter(_FakeSettings())
        await adapter.cancel()
        await adapter.cancel()  # Must not raise


# ---------------------------------------------------------------------------
# Integration test (requires CARTESIA_API_KEY in env)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_cartesia_tts_real_streaming():
    """Integration: stream real audio from Cartesia Sonic-3 API.

    Requires CARTESIA_API_KEY and CARTESIA_VOICE_ID in the environment.
    Validates that real audio bytes are yielded and TTFA is < 200ms.
    """
    api_key = os.environ.get("CARTESIA_API_KEY", "")
    voice_id = os.environ.get("CARTESIA_VOICE_ID", "")
    if not api_key or api_key.startswith("test-"):
        pytest.skip("CARTESIA_API_KEY not set (or is a test placeholder)")
    if not voice_id or voice_id.startswith("test-"):
        pytest.skip("CARTESIA_VOICE_ID not set (or is a test placeholder)")

    @dataclass
    class _RealSettings:
        cartesia_api_key: str = api_key
        cartesia_voice_id: str = voice_id

    adapter = CartesiaTTSAdapter(_RealSettings())
    mc = MetricsCollector()

    chunks = []
    async for chunk in adapter.stream("Hello, this is a test of Cartesia Sonic-3.", mc):
        chunks.append(chunk)
        if len(chunks) > 10:
            break

    assert len(chunks) > 0
    assert all(isinstance(c, bytes) for c in chunks)
    stage = mc.get_stage("tts")
    assert stage is not None
    assert stage.time_to_first_ms is not None
    assert stage.time_to_first_ms < 200, f"TTFA {stage.time_to_first_ms:.1f}ms exceeds 200ms budget"
