"""
Tests for the DeepgramSTTAdapter (live WebSocket streaming).

Unit tests mock the Deepgram live WebSocket connection to validate
partial/final transcript callbacks, metrics recording, error wrapping,
cancellation, and the finish() flow. One integration test makes a real
Deepgram live connection (requires DEEPGRAM_API_KEY).

Pipeline stage: STT (Stage 1)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.stt_adapter import DeepgramSTTAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettings:
    deepgram_api_key: str = "test-deepgram-key"
    stt_endpointing_ms: int = 300
    stt_utterance_end_ms: int = 1000
    stt_interim_results: bool = True


def _make_result(transcript: str, is_final: bool = False, speech_final: bool = False):
    """Build a mock ListenV1Results object."""
    from deepgram.listen.v1.types import (
        ListenV1Results,
        ListenV1ResultsChannel,
        ListenV1ResultsChannelAlternativesItem,
    )
    alt = MagicMock(spec=ListenV1ResultsChannelAlternativesItem)
    alt.transcript = transcript
    alt.confidence = 0.95

    channel = MagicMock(spec=ListenV1ResultsChannel)
    channel.alternatives = [alt]

    result = MagicMock(spec=ListenV1Results)
    result.type = "Results"
    result.channel = channel
    result.is_final = is_final
    result.speech_final = speech_final
    result.from_finalize = False
    return result


def _make_utterance_end(last_word_end: float = 1.5):
    """Build a mock ListenV1UtteranceEnd object."""
    from deepgram.listen.v1.types import ListenV1UtteranceEnd
    msg = MagicMock(spec=ListenV1UtteranceEnd)
    msg.type = "UtteranceEnd"
    msg.channel = [0]
    msg.last_word_end = last_word_end
    return msg


def _make_speech_started(timestamp: float = 0.0):
    """Build a mock ListenV1SpeechStarted object."""
    from deepgram.listen.v1.types import ListenV1SpeechStarted
    msg = MagicMock(spec=ListenV1SpeechStarted)
    msg.type = "SpeechStarted"
    msg.channel = [0]
    msg.timestamp = timestamp
    return msg


class _MockConnection:
    """Simulates a Deepgram AsyncV1SocketClient for testing.

    Feed messages into ``_incoming`` to simulate Deepgram sending
    results.  The ``__aiter__`` yields from that queue.
    """

    def __init__(self):
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._closed = False
        self.send_media = AsyncMock()
        self.send_finalize = AsyncMock()
        self.send_close_stream = AsyncMock()

    async def __aiter__(self):
        """Yield messages from the incoming queue until closed."""
        while not self._closed:
            try:
                msg = await asyncio.wait_for(self._incoming.get(), timeout=0.5)
                yield msg
            except asyncio.TimeoutError:
                if self._closed:
                    break

    def feed(self, msg):
        """Enqueue a message for the adapter's receive loop to consume."""
        self._incoming.put_nowait(msg)

    def close(self):
        self._closed = True


class _MockContextManager:
    """Simulates the async context manager returned by client.listen.v1.connect()."""

    def __init__(self, connection: _MockConnection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, *args):
        self._connection.close()


def _patch_adapter(adapter: DeepgramSTTAdapter, mock_conn: _MockConnection):
    """Patch the adapter's client to return our mock connection."""
    mock_client = MagicMock()
    mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
    adapter._client = mock_client
    # Bypass __init__'s client creation by setting _client before start()
    # We also need to ensure start() creates _client from api_key.
    # Patch at module level instead:
    return mock_client


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestDeepgramSTTAdapterStart:
    """Tests for the start/connect lifecycle."""

    @pytest.mark.asyncio
    async def test_start_opens_connection(self):
        """start() opens a Deepgram live WebSocket connection."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

            mock_client.listen.v1.connect.assert_called_once()
            call_kwargs = mock_client.listen.v1.connect.call_args.kwargs
            assert call_kwargs["model"] == "nova-3"
            assert call_kwargs["encoding"] == "linear16"
            assert call_kwargs["sample_rate"] == "16000"
            assert call_kwargs["interim_results"] == "true"
            assert call_kwargs["smart_format"] == "true"

        # Cleanup
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_start_records_stt_metrics_start(self):
        """start() calls metrics.start('stt')."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        stage = mc.get_stage("stt")
        assert stage is not None
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_start_connection_failure_raises_adapter_error(self):
        """start() wraps connection errors in AdapterError."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            # Make the context manager's __aenter__ raise
            bad_ctx = MagicMock()
            bad_ctx.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
            bad_ctx.__aexit__ = AsyncMock()
            mock_client.listen.v1.connect.return_value = bad_ctx
            mock_cls.return_value = mock_client

            with pytest.raises(AdapterError) as exc_info:
                await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

            assert exc_info.value.stage == "stt"
            assert exc_info.value.provider == "deepgram"


class TestDeepgramSTTAdapterSendAudio:
    """Tests for send_audio()."""

    @pytest.mark.asyncio
    async def test_send_audio_forwards_to_connection(self):
        """send_audio() forwards raw PCM to the Deepgram connection."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        chunk = b"\x00\x01" * 1600
        await adapter.send_audio(chunk)

        mock_conn.send_media.assert_called_once_with(chunk)
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_send_audio_noop_when_cancelled(self):
        """send_audio() is a no-op after cancel()."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        await adapter.cancel()
        await adapter.send_audio(b"\x00" * 100)
        mock_conn.send_media.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_audio_noop_before_start(self):
        """send_audio() is a no-op if start() was never called."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        await adapter.send_audio(b"\x00" * 100)
        # Should not raise


class TestDeepgramSTTAdapterTranscripts:
    """Tests for partial and final transcript handling."""

    @pytest.mark.asyncio
    async def test_partial_transcript_fires_on_partial(self):
        """Interim results call the on_partial callback."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        on_partial = AsyncMock()
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=on_partial, on_final=on_final)

        # Simulate Deepgram sending an interim result
        mock_conn.feed(_make_result("What is", is_final=False))
        await asyncio.sleep(0.1)

        on_partial.assert_called_with("What is")
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_final_transcript_fires_on_final(self):
        """is_final=True results call the on_final callback."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        on_partial = AsyncMock()
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=on_partial, on_final=on_final)

        mock_conn.feed(_make_result("What is photosynthesis?", is_final=True))
        await asyncio.sleep(0.1)

        on_final.assert_called_with("What is photosynthesis?")
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_finals_accumulate_across_segments(self):
        """Multiple is_final=True results are concatenated."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        on_partial = AsyncMock()
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=on_partial, on_final=on_final)

        mock_conn.feed(_make_result("What is", is_final=True))
        await asyncio.sleep(0.05)
        mock_conn.feed(_make_result("photosynthesis?", is_final=True))
        await asyncio.sleep(0.05)

        # Second on_final call should have accumulated text
        assert on_final.call_count == 2
        assert on_final.call_args_list[1].args[0] == "What is photosynthesis?"
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_partial_includes_accumulated_finals(self):
        """Interim results are prefixed with accumulated final segments."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        on_partial = AsyncMock()
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=on_partial, on_final=on_final)

        # Final segment committed
        mock_conn.feed(_make_result("What is", is_final=True))
        await asyncio.sleep(0.05)
        # Then a partial for the next word
        mock_conn.feed(_make_result("photo", is_final=False))
        await asyncio.sleep(0.05)

        on_partial.assert_called_with("What is photo")
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_empty_transcript_is_ignored(self):
        """Empty transcripts don't fire callbacks."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        on_partial = AsyncMock()
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=on_partial, on_final=on_final)

        mock_conn.feed(_make_result("", is_final=False))
        mock_conn.feed(_make_result("", is_final=True))
        await asyncio.sleep(0.1)

        on_partial.assert_not_called()
        on_final.assert_not_called()
        await adapter.cancel()


class TestDeepgramSTTAdapterFinish:
    """Tests for the finish() method."""

    @pytest.mark.asyncio
    async def test_finish_returns_accumulated_transcript(self):
        """finish() returns the full accumulated final transcript."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        # Simulate final transcript + utterance end
        mock_conn.feed(_make_result("What is photosynthesis?", is_final=True))
        mock_conn.feed(_make_utterance_end())
        await asyncio.sleep(0.05)

        result = await adapter.finish()
        assert result == "What is photosynthesis?"

    @pytest.mark.asyncio
    async def test_finish_sends_finalize(self):
        """finish() calls send_finalize() on the connection."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        # Pre-set transcript_done so finish() doesn't block
        adapter._transcript_done.set()

        await adapter.finish()
        mock_conn.send_finalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_finish_timeout_returns_accumulated(self):
        """If UtteranceEnd never fires, finish() returns accumulated finals after timeout."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        # Feed a final result but no UtteranceEnd
        mock_conn.feed(_make_result("Hello world", is_final=True))
        await asyncio.sleep(0.05)

        # Patch timeout to be very short for test speed
        with patch("adapters.stt_adapter._FINISH_TIMEOUT_S", 0.2):
            result = await adapter.finish()

        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_finish_empty_when_no_speech(self):
        """finish() returns '' when no speech was detected."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        # UtteranceEnd with no transcript
        mock_conn.feed(_make_utterance_end())
        await asyncio.sleep(0.05)

        result = await adapter.finish()
        assert result == ""

    @pytest.mark.asyncio
    async def test_finish_noop_when_not_active(self):
        """finish() returns '' if start() was never called."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        result = await adapter.finish()
        assert result == ""


class TestDeepgramSTTAdapterMetrics:
    """Tests for metrics recording."""

    @pytest.mark.asyncio
    async def test_mark_first_on_first_partial(self):
        """metrics.mark_first('stt') is called on the first partial transcript."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        mock_conn.feed(_make_result("Hello", is_final=False))
        await asyncio.sleep(0.1)

        stage = mc.get_stage("stt")
        assert stage is not None
        assert stage.time_to_first_ms is not None
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_metrics_end_on_utterance_end(self):
        """metrics.end('stt') is called when UtteranceEnd is received."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        mock_conn.feed(_make_result("Hello", is_final=True))
        mock_conn.feed(_make_utterance_end())
        await asyncio.sleep(0.1)

        stage = mc.get_stage("stt")
        assert stage is not None
        assert stage.duration_ms is not None
        await adapter.cancel()


class TestDeepgramSTTAdapterCancel:
    """Tests for cancel()."""

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent(self):
        """cancel() can be called multiple times without error."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        await adapter.cancel()
        await adapter.cancel()

    @pytest.mark.asyncio
    async def test_cancel_stops_active_session(self):
        """cancel() closes the Deepgram connection and stops the receive loop."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        assert adapter._active is True

        await adapter.cancel()
        assert adapter._active is False

    @pytest.mark.asyncio
    async def test_cancel_unblocks_finish(self):
        """cancel() sets transcript_done so finish() doesn't hang."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=AsyncMock(), on_final=AsyncMock())

        # cancel in parallel with finish
        async def cancel_soon():
            await asyncio.sleep(0.05)
            await adapter.cancel()

        asyncio.create_task(cancel_soon())
        result = await adapter.finish()
        assert result == ""


class TestDeepgramSTTAdapterErrorHandling:
    """Tests for error wrapping."""

    @pytest.mark.asyncio
    async def test_callback_error_does_not_break_receive_loop(self):
        """If on_partial raises, the receive loop continues."""
        adapter = DeepgramSTTAdapter(_FakeSettings())
        mc = MetricsCollector()
        mock_conn = _MockConnection()
        failing_partial = AsyncMock(side_effect=Exception("callback boom"))
        on_final = AsyncMock()

        with patch("adapters.stt_adapter.AsyncDeepgramClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.listen.v1.connect.return_value = _MockContextManager(mock_conn)
            mock_cls.return_value = mock_client

            await adapter.start(mc, on_partial=failing_partial, on_final=on_final)

        # First message triggers failing callback
        mock_conn.feed(_make_result("Hello", is_final=False))
        await asyncio.sleep(0.05)
        # Second message should still be processed
        mock_conn.feed(_make_result("world", is_final=True))
        await asyncio.sleep(0.05)

        on_final.assert_called_once_with("world")
        await adapter.cancel()


# ---------------------------------------------------------------------------
# Integration test (requires DEEPGRAM_API_KEY in env)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_deepgram_live_real_connection():
    """Integration: open a real Deepgram live WebSocket, send silence, close.

    Requires DEEPGRAM_API_KEY in the environment. Sends 1 second of
    silence and verifies the connection opens and closes cleanly.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        pytest.skip("DEEPGRAM_API_KEY not set")

    @dataclass
    class _RealSettings:
        deepgram_api_key: str = api_key
        stt_endpointing_ms: int = 300
        stt_utterance_end_ms: int = 1000
        stt_interim_results: bool = True

    adapter = DeepgramSTTAdapter(_RealSettings())
    mc = MetricsCollector()

    partials = []
    finals = []

    await adapter.start(
        mc,
        on_partial=lambda t: partials.append(t),
        on_final=lambda t: finals.append(t),
    )

    # Send 1 second of silence (16kHz, 16-bit mono)
    silence = bytes(32000)
    for i in range(0, len(silence), 3200):
        await adapter.send_audio(silence[i:i + 3200])
        await asyncio.sleep(0.05)

    result = await adapter.finish()

    # Silence should produce empty or near-empty transcript
    assert isinstance(result, str)
    stage = mc.get_stage("stt")
    assert stage is not None
