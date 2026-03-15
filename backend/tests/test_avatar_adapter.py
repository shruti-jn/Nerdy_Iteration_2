"""
Tests for the Simli Avatar Adapter (server-side signaling proxy).

TDD: These tests were written BEFORE the implementation.

Covers:
  - Happy path: session init, audio streaming, render latency
  - Error paths: timeout, connection error, stop behaviour
  - Session lifecycle: init → stream → stop

Pipeline stage: Avatar (Task 1D)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.errors import AdapterError, AdapterTimeoutError
from pipeline.metrics import MetricsCollector


# ── Helpers ──────────────────────────────────────────────────────────────


async def _audio_chunks(count: int = 5, size: int = 6000):
    """Yield fake PCM16 audio chunks."""
    for _ in range(count):
        yield b"\x00" * size


def _mock_config():
    """Create a minimal config-like object."""
    cfg = MagicMock()
    cfg.simli_api_key = "test-simli-key"
    cfg.simli_face_id = "test-face-id"
    cfg.avatar_max_ms = 200
    return cfg


# ── Happy Path ───────────────────────────────────────────────────────────


class TestHappyPath:
    """Verify core adapter functionality with mocked Simli API."""

    def test_keepalive_frame_matches_simli_client_chunk_size(self):
        """Keepalive silence should be large enough to mimic normal Simli PCM payloads."""
        from adapters import avatar_adapter as avatar_module

        assert avatar_module._KEEPALIVE_SAMPLES == 3000
        assert len(avatar_module._SILENT_FRAME) == 6000

    @pytest.mark.asyncio
    async def test_initialize_session_gets_token(self):
        """initialize_session should call the Simli token endpoint."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"session_token": "test-token-123"}
        mock_response.raise_for_status = MagicMock()

        mock_ice_response = MagicMock()
        mock_ice_response.status_code = 200
        mock_ice_response.json.return_value = [
            {"urls": "stun:stun.example.com:3478"}
        ]
        mock_ice_response.raise_for_status = MagicMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=mock_response)
            client_instance.get = AsyncMock(return_value=mock_ice_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            result = await adapter.initialize_session()

        assert result["session_token"] == "test-token-123"
        assert "ice_servers" in result

    @pytest.mark.asyncio
    async def test_stream_audio_sends_chunks(self):
        """stream_audio should forward audio chunks to the WebSocket."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        # Pre-set session state as if initialized
        adapter._session_token = "test-token"
        sent_chunks = []

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda data: sent_chunks.append(data))
        mock_ws.recv = AsyncMock(return_value="START")
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        adapter._ws = mock_ws
        adapter._ready = True

        metrics = MetricsCollector()

        await adapter.stream_audio(_audio_chunks(3, 6000), metrics)

        # Should have sent 3 binary audio chunks
        binary_sends = [c for c in sent_chunks if isinstance(c, bytes)]
        assert len(binary_sends) == 3

    @pytest.mark.asyncio
    async def test_render_latency_logged(self):
        """Metrics should record avatar stage timing."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        adapter._session_token = "test-token"
        adapter._ws = AsyncMock()
        adapter._ws.send = AsyncMock()
        adapter._ready = True

        metrics = MetricsCollector()
        await adapter.stream_audio(_audio_chunks(2), metrics)

        stage = metrics.get_stage("avatar")
        assert stage is not None
        assert stage.start_ns is not None
        assert stage.end_ns is not None


# ── Error Paths ──────────────────────────────────────────────────────────


class TestErrorPaths:
    """Error conditions must produce correctly typed exceptions."""

    @pytest.mark.asyncio
    async def test_connection_error_raises_adapter_error(self):
        """Connection failure should raise AdapterError with stage=avatar."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            with pytest.raises(AdapterError) as exc_info:
                await adapter.initialize_session()

            assert exc_info.value.stage == "avatar"
            assert exc_info.value.provider == "simli"

    @pytest.mark.asyncio
    async def test_stream_without_init_raises(self):
        """Streaming before initialization should raise AdapterError."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        metrics = MetricsCollector()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.stream_audio(_audio_chunks(1), metrics)

        assert exc_info.value.stage == "avatar"

    @pytest.mark.asyncio
    async def test_stop_returns_cleanly(self):
        """stop() should complete within 200ms with mock connections."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        adapter._session_token = "test-token"
        adapter._ws = AsyncMock()
        adapter._ws.send = AsyncMock()
        adapter._ws.close = AsyncMock()
        adapter._ready = True

        import time

        start = time.monotonic()
        await adapter.stop()
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200

    @pytest.mark.asyncio
    async def test_stop_idempotent_when_not_initialized(self):
        """stop() on an uninitialised adapter should be a no-op."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        await adapter.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_sends_skip_command(self):
        """stop() should send SKIP to clear buffered audio."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        adapter._session_token = "test-token"
        mock_ws = AsyncMock()
        sent_messages = []
        mock_ws.send = AsyncMock(side_effect=lambda data: sent_messages.append(data))
        mock_ws.close = AsyncMock()
        adapter._ws = mock_ws
        adapter._ready = True

        await adapter.stop()

        # Should have sent "SKIP" text command
        assert "SKIP" in sent_messages


# ── Session Lifecycle ────────────────────────────────────────────────────


class TestSessionLifecycle:
    """Full lifecycle: init → stream → stop."""

    @pytest.mark.asyncio
    async def test_webrtc_details_returned(self):
        """initialize_session should return session_token and ice_servers."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"session_token": "tok-abc"}
        mock_response.raise_for_status = MagicMock()

        mock_ice_response = MagicMock()
        mock_ice_response.status_code = 200
        mock_ice_response.json.return_value = [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "turn:turn.example.com:3478", "username": "u", "credential": "c"},
        ]
        mock_ice_response.raise_for_status = MagicMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=mock_response)
            client_instance.get = AsyncMock(return_value=mock_ice_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            result = await adapter.initialize_session()

        assert result["session_token"] == "tok-abc"
        assert len(result["ice_servers"]) == 2

    @pytest.mark.asyncio
    async def test_multiple_stream_calls(self):
        """Multiple stream_audio calls should all send chunks."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        adapter._session_token = "test-token"
        sent_count = 0

        async def count_sends(data):
            nonlocal sent_count
            if isinstance(data, bytes):
                sent_count += 1

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=count_sends)
        adapter._ws = mock_ws
        adapter._ready = True

        metrics1 = MetricsCollector()
        metrics2 = MetricsCollector()

        await adapter.stream_audio(_audio_chunks(3), metrics1)
        await adapter.stream_audio(_audio_chunks(2), metrics2)

        assert sent_count == 5


# ── WebRTC Handshake (connect) ────────────────────────────────────────────


def _mock_http_session(token: str, ice: list):
    """Return a fake httpx.AsyncClient context manager with mocked responses."""
    token_resp = MagicMock()
    token_resp.json.return_value = {"session_token": token}
    token_resp.raise_for_status = MagicMock()

    ice_resp = MagicMock()
    ice_resp.json.return_value = ice
    ice_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=token_resp)
    client.get = AsyncMock(return_value=ice_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestConnect:
    """Verify the full WebRTC handshake via connect()."""

    @pytest.mark.asyncio
    async def test_connect_returns_sdp_answer(self):
        """connect() exchanges SDP and returns answer + ICE servers."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        ice = [{"urls": "stun:stun.l.google.com:19302"}]

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=["START", '{"type": "answer", "sdp": "v=0 answer..."}']
        )
        mock_ws.send = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok-xyz", ice)
            with patch("adapters.avatar_adapter.websockets.connect", new=AsyncMock(return_value=mock_ws)):
                result = await adapter.connect("v=0 offer...")

        assert result["sdp"] == "v=0 answer..."
        assert result["ice_servers"] == ice
        assert adapter._ready is True

    @pytest.mark.asyncio
    async def test_connect_sends_offer_with_correct_format(self):
        """connect() sends the SDP offer as JSON {"type": "offer", "sdp": "…"}."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        sent_messages = []

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=["START", '{"type": "answer", "sdp": "v=0..."}']
        )
        mock_ws.send = AsyncMock(side_effect=lambda m: sent_messages.append(m))

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok", [])
            with patch("adapters.avatar_adapter.websockets.connect", new=AsyncMock(return_value=mock_ws)):
                await adapter.connect("v=0 my-offer")

        assert len(sent_messages) == 1
        sent = json.loads(sent_messages[0])
        assert sent == {"type": "offer", "sdp": "v=0 my-offer"}

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_adapter_error(self):
        """connect() retries transient timeouts, then raises AdapterError if they persist."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok", [])
            connect_mock = AsyncMock(side_effect=asyncio.TimeoutError())
            with patch(
                "adapters.avatar_adapter.websockets.connect",
                new=connect_mock,
            ):
                with pytest.raises(AdapterError) as exc_info:
                    await adapter.connect("v=0 offer")

        assert exc_info.value.stage == "avatar"
        assert exc_info.value.provider == "simli"
        assert connect_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_connect_retries_timeout_waiting_for_answer_and_succeeds(self):
        """connect() should recover when a first SDP-answer wait times out."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        ice = [{"urls": "stun:stun.l.google.com:19302"}]

        first_ws = AsyncMock()
        first_ws.recv = AsyncMock(side_effect=["START", asyncio.TimeoutError()])
        first_ws.send = AsyncMock()
        first_ws.close = AsyncMock()

        second_ws = AsyncMock()
        second_ws.recv = AsyncMock(
            side_effect=["START", '{"type": "answer", "sdp": "v=0 recovered-answer"}']
        )
        second_ws.send = AsyncMock()
        second_ws.close = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok-xyz", ice)
            connect_mock = AsyncMock(side_effect=[first_ws, second_ws])
            with patch("adapters.avatar_adapter.websockets.connect", new=connect_mock):
                result = await adapter.connect("v=0 offer...")

        assert result["sdp"] == "v=0 recovered-answer"
        assert result["ice_servers"] == ice
        assert adapter._ready is True
        assert connect_mock.await_count == 2
        first_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_retries_malformed_answer_and_succeeds(self):
        """connect() should retry when Simli returns a non-JSON SDP answer."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        ice = [{"urls": "stun:stun.l.google.com:19302"}]

        first_ws = AsyncMock()
        first_ws.recv = AsyncMock(side_effect=["START", "not-json-answer-payload"])
        first_ws.send = AsyncMock()
        first_ws.close = AsyncMock()

        second_ws = AsyncMock()
        second_ws.recv = AsyncMock(
            side_effect=["START", '{"type": "answer", "sdp": "v=0 recovered-answer"}']
        )
        second_ws.send = AsyncMock()
        second_ws.close = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok-xyz", ice)
            connect_mock = AsyncMock(side_effect=[first_ws, second_ws])
            with patch("adapters.avatar_adapter.websockets.connect", new=connect_mock):
                result = await adapter.connect("v=0 offer...")

        assert result["sdp"] == "v=0 recovered-answer"
        assert result["ice_servers"] == ice
        assert adapter._ready is True
        assert connect_mock.await_count == 2
        first_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_malformed_answer_raises_after_retries(self):
        """connect() should still fail cleanly if Simli keeps sending malformed answers."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        first_ws = AsyncMock()
        first_ws.recv = AsyncMock(side_effect=["START", "not-json-answer-payload"])
        first_ws.send = AsyncMock()
        first_ws.close = AsyncMock()

        second_ws = AsyncMock()
        second_ws.recv = AsyncMock(side_effect=["START", "still-not-json"])
        second_ws.send = AsyncMock()
        second_ws.close = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok", [])
            connect_mock = AsyncMock(side_effect=[first_ws, second_ws])
            with patch("adapters.avatar_adapter.websockets.connect", new=connect_mock):
                with pytest.raises(AdapterError) as exc_info:
                    await adapter.connect("v=0 offer")

        assert exc_info.value.stage == "avatar"
        assert exc_info.value.provider == "simli"
        assert connect_mock.await_count == 2
        first_ws.close.assert_awaited_once()
        second_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_unexpected_first_message_raises_adapter_error(self):
        """connect() raises AdapterError when Simli doesn't send 'START'."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value="UNEXPECTED")
        mock_ws.send = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok", [])
            with patch("adapters.avatar_adapter.websockets.connect", new=AsyncMock(return_value=mock_ws)):
                with pytest.raises(AdapterError) as exc_info:
                    await adapter.connect("v=0 offer")

        assert exc_info.value.stage == "avatar"

    @pytest.mark.asyncio
    async def test_connect_accepts_new_simli_json_protocol(self):
        """connect() accepts the new Simli JSON ready signal (destination+session_id)."""
        import base64
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        ice = [{"urls": "stun:stun.l.google.com:19302"}]

        dest_b64 = base64.b64encode(b"192.168.1.1:6070").decode()
        ready_msg = json.dumps({"destination": dest_b64, "session_id": "abc-123"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=[ready_msg, '{"type": "answer", "sdp": "v=0 answer..."}']
        )
        mock_ws.send = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok-xyz", ice)
            with patch("adapters.avatar_adapter.websockets.connect", new=AsyncMock(return_value=mock_ws)):
                result = await adapter.connect("v=0 offer...")

        assert result["sdp"] == "v=0 answer..."
        assert adapter._ready is True

    @pytest.mark.asyncio
    async def test_connect_json_without_destination_raises_adapter_error(self):
        """connect() raises AdapterError when JSON from Simli has no 'destination' field."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        bad_msg = json.dumps({"session_id": "abc-123"})  # missing 'destination'

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=bad_msg)
        mock_ws.send = AsyncMock()

        with patch("adapters.avatar_adapter.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _mock_http_session("tok", [])
            with patch("adapters.avatar_adapter.websockets.connect", new=AsyncMock(return_value=mock_ws)):
                with pytest.raises(AdapterError) as exc_info:
                    await adapter.connect("v=0 offer")

        assert exc_info.value.stage == "avatar"

    @pytest.mark.asyncio
    async def test_send_audio_forwards_when_ready(self):
        """send_audio() sends a binary chunk when the session is ready."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())
        adapter._ready = True
        sent = []

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda d: sent.append(d))
        # Simulate websockets OPEN state (state == 1)
        mock_ws.state = 1
        # Mock transport with is_closing() returning False (connection alive)
        mock_transport = MagicMock()
        mock_transport.is_closing.return_value = False
        mock_ws.transport = mock_transport
        adapter._ws = mock_ws

        await adapter.send_audio(b"\x00" * 3200)

        assert sent == [b"\x00" * 3200]

    @pytest.mark.asyncio
    async def test_send_audio_noop_when_not_ready(self):
        """send_audio() does nothing when the session is not initialized."""
        from adapters.avatar_adapter import SimliAvatarAdapter

        adapter = SimliAvatarAdapter(_mock_config())  # _ready=False, _ws=None

        # Should not raise
        await adapter.send_audio(b"\x00" * 3200)
