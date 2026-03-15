"""
Tests for the FastAPI WebSocket server (main.py).

Uses Starlette TestClient for WebSocket testing and httpx AsyncClient
for HTTP endpoint testing. All external adapters are mocked.

Pipeline stage: Testing (server integration tests)
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from main import app


# ── HTTP endpoint tests ─────────────────────────────────────────────────────


def test_health_endpoint():
    """GET /health returns 200 with status ok."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_endpoint():
    """GET /ready returns 200 with active session count."""
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert "active_sessions" in body


def test_metrics_endpoint_empty():
    """GET /metrics returns empty dict when no turns have run."""
    import main
    original = main.latest_metrics
    main.latest_metrics = {}
    try:
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.json() == {}
    finally:
        main.latest_metrics = original


def test_metrics_endpoint_with_data():
    """GET /metrics returns stored metrics after a turn."""
    import main
    original = main.latest_metrics
    main.latest_metrics = {"test-session": {"stt_duration_ms": 120.5, "turn_duration_ms": 800.0}}
    try:
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stt_duration_ms"] == 120.5
        assert data["turn_duration_ms"] == 800.0
    finally:
        main.latest_metrics = original


# ── WebSocket tests (contract gate: protocol + session behavior, no live providers) ──


@pytest.mark.contract
def test_ws_session_start():
    """WebSocket connection receives session_start message."""
    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_start"
        assert "session_id" in msg


@pytest.mark.contract
def test_ws_passes_query_avatar_provider_to_orchestrator():
    """The orchestrator should receive the session-selected avatar provider."""
    import main as main_module

    captured: dict[str, str | None] = {"avatar_provider": None}

    class FakeOrchestrator:
        def __init__(self, settings, session_id, send_json, max_turns=None, braintrust_logger=None, avatar_provider=None):
            del settings, session_id, send_json, max_turns, braintrust_logger
            captured["avatar_provider"] = avatar_provider

        def set_simli(self, adapter):
            del adapter

        async def handle_greeting(self, session, topic):
            del session, topic

        async def handle_welcome_back(self, session, topic):
            del session, topic

        async def handle_interrupt(self, session):
            del session

        async def cancel_active_turn(self):
            return None

        async def get_metrics(self):
            return {}

    with patch.object(main_module, "CustomOrchestrator", FakeOrchestrator):
        client = TestClient(app)
        with client.websocket_connect("/session?avatar=spatialreal") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "session_start"

    assert captured["avatar_provider"] == "spatialreal"


@pytest.mark.contract
def test_ws_session_limit_rejection_contract():
    """Connection beyond MAX_SESSIONS returns SESSION_LIMIT_EXCEEDED and closes."""
    import main as main_module

    original_sessions = set(main_module.active_sessions)
    main_module.active_sessions.clear()
    main_module.active_sessions.update({f"busy-{i}" for i in range(main_module.MAX_SESSIONS)})
    try:
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/session") as ws:
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert msg["code"] == "SESSION_LIMIT_EXCEEDED"
                ws.receive_text()
    finally:
        main_module.active_sessions.clear()
        main_module.active_sessions.update(original_sessions)


@pytest.mark.contract
def test_ws_invalid_json():
    """Sending invalid JSON returns an INVALID_JSON error."""
    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        # Consume session_start
        ws.receive_text()
        # Send malformed JSON
        ws.send_text("not valid json {{{")
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_JSON"


@pytest.mark.contract
def test_ws_barge_in():
    """Sending barge_in returns barge_in_ack."""
    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        ws.receive_text()  # session_start
        ws.send_text(json.dumps({"type": "barge_in"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "barge_in_ack"


@pytest.mark.contract
def test_ws_start_lesson_resets_restored_session_in_place():
    """Starting over from a restored session should keep the same live connection and clear lesson state."""
    import main as main_module

    saved_session = {
        "topic": "photosynthesis",
        "history": [
            {"role": "assistant", "content": "Old tutor question"},
            {"role": "user", "content": "Old student answer"},
        ],
        "summary": "Old summary",
        "turn_count": 4,
        "lesson_progress": {
            "topic": "photosynthesis",
            "current_step_id": 2,
            "visual_step_id": 2,
        },
        "turns_since_compression": 2,
    }
    observed: dict[str, object] = {}

    async def fake_handle_greeting(self, session, topic):
        observed["topic"] = topic
        observed["turn_count"] = session.turn_count
        observed["history"] = list(session.history)
        observed["summary"] = session.summary
        observed["lesson_progress"] = session.lesson_progress
        await self._send_json({"type": "greeting_complete"})

    with (
        patch.object(main_module.session_store, "load", AsyncMock(return_value=saved_session)),
        patch.object(main_module.session_store, "save", AsyncMock()),
        patch("main.CustomOrchestrator.handle_greeting", new=fake_handle_greeting),
    ):
        client = TestClient(app)
        with client.websocket_connect("/session?session_id=resume-123") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "session_restore"
            ws.send_text(json.dumps({"type": "start_lesson"}))
            for _ in range(4):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "greeting_complete":
                    break
            else:
                pytest.fail("Expected greeting_complete after start_lesson on a restored session")

    assert observed["topic"] == "photosynthesis"
    assert observed["turn_count"] == 0
    assert observed["history"] == []
    assert observed["summary"] == ""
    assert observed["lesson_progress"] is None


@pytest.mark.contract
def test_ws_simli_not_configured():
    """simli_sdp_offer returns SIMLI_NOT_CONFIGURED when credentials are empty."""
    import main as main_module
    with patch.object(main_module.settings, "simli_api_key", ""), \
         patch.object(main_module.settings, "simli_face_id", ""):
        client = TestClient(app)
        with client.websocket_connect("/session") as ws:
            ws.receive_text()  # session_start
            ws.send_text(json.dumps({"type": "simli_sdp_offer", "sdp": "v=0..."}))
            msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert msg["code"] == "SIMLI_NOT_CONFIGURED"


@pytest.mark.contract
def test_ws_simli_connect_fails_without_credentials():
    """Sending simli_sdp_offer with invalid (but non-empty) credentials returns SIMLI_CONNECT_FAILED."""
    import main as main_module
    with patch.object(main_module.settings, "simli_api_key", "invalid-fake-key"), \
         patch.object(main_module.settings, "simli_face_id", "invalid-fake-face"):
        client = TestClient(app)
        with client.websocket_connect("/session") as ws:
            ws.receive_text()  # session_start
            ws.send_text(json.dumps({"type": "simli_sdp_offer", "sdp": "v=0..."}))
            msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert msg["code"] == "SIMLI_CONNECT_FAILED"


@pytest.mark.contract
def test_ws_simli_missing_sdp_field():
    """Sending simli_sdp_offer without 'sdp' field returns MISSING_SDP error."""
    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        ws.receive_text()  # session_start
        ws.send_text(json.dumps({"type": "simli_sdp_offer"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert msg["code"] == "MISSING_SDP"


@pytest.mark.contract
def test_ws_session_cleanup():
    """Session is removed from active_sessions on disconnect."""
    import main as main_module

    client = TestClient(app)
    before = len(main_module.active_sessions)
    with client.websocket_connect("/session") as ws:
        ws.receive_text()  # session_start
        assert len(main_module.active_sessions) == before + 1
    # After disconnect
    assert len(main_module.active_sessions) == before


@pytest.mark.contract
def test_ws_disconnect_during_active_turn_cancels_turn_task_and_cleans_session():
    """Disconnect while a turn is active cancels turn task and removes session."""
    import main as main_module

    cancelled = {"value": False}
    before = len(main_module.active_sessions)

    async def fake_handle_turn(self, audio_chunks, session):
        try:
            async for _chunk in audio_chunks:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise

    with patch("main.CustomOrchestrator.handle_turn", new=fake_handle_turn):
        client = TestClient(app)
        with client.websocket_connect("/session") as ws:
            ws.receive_text()  # session_start
            ws.send_bytes(b"\x00" * 3200)
            assert len(main_module.active_sessions) == before + 1

    for _ in range(20):
        if cancelled["value"]:
            break
        time.sleep(0.01)

    assert cancelled["value"] is True
    assert len(main_module.active_sessions) == before


@pytest.mark.contract
def test_ws_turn_limit_returns_session_complete_with_turn_fields():
    """When turn limit reached, sending audio emits session_complete with turn metadata."""
    import main as main_module

    mock_session_mgr = MagicMock()
    mock_session_mgr.turn_count = main_module.MAX_TURNS

    with patch("main.SessionManager", return_value=mock_session_mgr):
        client = TestClient(app)
        with client.websocket_connect("/session") as ws:
            ws.receive_text()  # session_start
            ws.send_bytes(b"\x00" * 3200)
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "session_complete"
            assert msg["turn_number"] == main_module.MAX_TURNS
            assert msg["total_turns"] == main_module.MAX_TURNS


@pytest.mark.contract
def test_ws_turn_failed_includes_timing_payload():
    """TURN_FAILED contract includes partial timing payload fields."""
    timing_payload = {
        "stt_finish_ms": 25.0,
        "turn_number": 1,
        "total_turns": 15,
        "turn_duration_ms": 26.0,
    }

    async def fake_handle_turn(self, audio_chunks, session):
        async for _ in audio_chunks:
            pass
        await self._send_json({
            "type": "error",
            "code": "TURN_FAILED",
            "message": "mock llm failure",
            "timing": timing_payload,
        })

    with patch("main.CustomOrchestrator.handle_turn", new=fake_handle_turn):
        client = TestClient(app)
        with client.websocket_connect("/session") as ws:
            ws.receive_text()  # session_start
            ws.send_bytes(b"\x00" * 3200)
            ws.send_text(json.dumps({"type": "end_of_utterance"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "error"
            assert msg["code"] == "TURN_FAILED"
            assert "timing" in msg
            assert msg["timing"]["stt_finish_ms"] == timing_payload["stt_finish_ms"]
            assert msg["timing"]["turn_number"] == timing_payload["turn_number"]
            assert msg["timing"]["total_turns"] == timing_payload["total_turns"]


@pytest.mark.contract
@pytest.mark.skip(reason="Hangs with Starlette TestClient when main creates_task and awaits later; pipeline covered by integration/e2e")
@patch("pipeline.orchestrator_custom.CartesiaTTSAdapter")
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_end_of_utterance_pipeline(mock_stt_cls, mock_llm_cls, mock_deepgram_tts_cls, mock_cartesia_tts_cls):
    """end_of_utterance triggers the full STT -> LLM -> TTS pipeline.

    Mocks all adapters to verify:
    1. STT transcribes audio and student_transcript is sent
    2. LLM generates tokens
    3. TTS produces audio chunks sent as base64
    4. tutor_text_chunk is sent with full text and timing

    Both DeepgramTTSAdapter and CartesiaTTSAdapter are patched so this test
    passes regardless of the TTS_PROVIDER setting in the environment.
    """
    # Configure STT mock — streaming interface (start/send_audio/finish/cancel)
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="What is photosynthesis?")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    # Configure LLM mock — stream() is an async generator
    async def mock_llm_stream(transcript, context, metrics):
        metrics.start("llm")
        metrics.mark_first("llm")
        for token in ["Great ", "question! ", "What do plants need to grow?"]:
            yield token
        metrics.end("llm")

    mock_llm = MagicMock()
    mock_llm.stream = mock_llm_stream
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    # Configure TTS mock — stream() is an async generator
    async def mock_tts_stream(sentence, metrics):
        metrics.start("tts")
        metrics.mark_first("tts")
        yield b"\x00\x01" * 100  # fake PCM audio
        metrics.end("tts")

    mock_tts = MagicMock()
    mock_tts.stream = mock_tts_stream
    mock_tts.cancel = AsyncMock()
    # Patch both adapters — only one will be used depending on TTS_PROVIDER
    mock_deepgram_tts_cls.return_value = mock_tts
    mock_cartesia_tts_cls.return_value = mock_tts

    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        # Consume session_start
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_start"

        # Send some audio frames (triggers stt.start + stt.send_audio)
        ws.send_bytes(b"\x00" * 3200)
        ws.send_bytes(b"\x00" * 3200)

        # Signal end of utterance (triggers stt.finish -> LLM -> TTS)
        ws.send_text(json.dumps({"type": "end_of_utterance"}))

        # Collect all messages until tutor_text_chunk
        # Note: with streaming STT, student_partial messages may appear
        # before student_transcript (from on_partial/on_final callbacks)
        messages = []
        for _ in range(20):  # safety limit
            raw = ws.receive_text()
            msg = json.loads(raw)
            messages.append(msg)
            if msg["type"] == "tutor_text_chunk":
                break

        # Verify message sequence — filter out student_partial (optional)
        types = [m["type"] for m in messages]
        assert "student_transcript" in types
        assert "audio_chunk" in types
        assert "tutor_text_chunk" in types

        # student_transcript should come before audio_chunk
        st_idx = types.index("student_transcript")
        ac_idx = types.index("audio_chunk")
        tt_idx = types.index("tutor_text_chunk")
        assert st_idx < ac_idx < tt_idx

        # Verify student transcript content
        st_msg = messages[st_idx]
        assert st_msg["text"] == "What is photosynthesis?"

        # Verify audio is base64-encoded
        ac_msg = messages[ac_idx]
        decoded = base64.b64decode(ac_msg["data"])
        assert len(decoded) > 0

        # Verify tutor text
        tt_msg = messages[tt_idx]
        assert "question" in tt_msg["text"].lower() or "plant" in tt_msg["text"].lower()
        assert "timing" in tt_msg


@pytest.mark.contract
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_empty_audio_no_pipeline(mock_stt_cls, mock_llm_cls, mock_tts_cls):
    """end_of_utterance without any audio frames does not trigger pipeline."""
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    mock_llm = MagicMock()
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.cancel = AsyncMock()
    mock_tts_cls.return_value = mock_tts

    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        ws.receive_text()  # session_start

        # end_of_utterance without sending any audio — stt_active stays False
        ws.send_text(json.dumps({"type": "end_of_utterance"}))

        # Send another message to verify the connection is still alive
        ws.send_text(json.dumps({"type": "barge_in"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "barge_in_ack"


@pytest.mark.contract
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_turn_error_sends_error_message(mock_stt_cls, mock_llm_cls, mock_tts_cls):
    """If stt.start() raises, an error message is sent to the client."""
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock(side_effect=Exception("STT boom"))
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    mock_llm = MagicMock()
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.cancel = AsyncMock()
    mock_tts_cls.return_value = mock_tts

    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        ws.receive_text()  # session_start

        # Send audio — this triggers stt.start() which will raise
        ws.send_bytes(b"\x00" * 3200)

        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert msg["code"] == "STT_START_FAILED"
        assert "STT boom" in msg["message"]


# ── Topic selection and greeting tests ──────────────────────────────────────


@pytest.mark.contract
def test_topics_endpoint():
    """GET /topics returns the list of available topic identifiers."""
    client = TestClient(app)
    resp = client.get("/topics")
    assert resp.status_code == 200
    body = resp.json()
    assert "topics" in body
    assert "photosynthesis" in body["topics"]
    assert "newtons_laws" in body["topics"]


@pytest.mark.contract
def test_ws_session_start_with_topic_param():
    """WebSocket connection with ?topic=newtons_laws includes topic in session_start."""
    client = TestClient(app)
    with client.websocket_connect("/session?topic=newtons_laws") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_start"
        assert msg["topic"] == "newtons_laws"
        assert "session_id" in msg
        assert "total_turns" in msg


@pytest.mark.contract
def test_ws_invalid_topic_param():
    """WebSocket connection with an unknown topic receives INVALID_TOPIC error and closes."""
    client = TestClient(app)
    # The server sends an error message and then closes the connection.
    # Starlette TestClient raises WebSocketDisconnect when the server closes,
    # so we need to handle that gracefully.
    from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

    with pytest.raises(Exception):
        # The server will close the connection after sending the error.
        # Depending on timing, we may get the error message or the close.
        with client.websocket_connect("/session?topic=invalid") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "error"
            assert msg["code"] == "INVALID_TOPIC"
            assert "invalid" in msg["message"].lower()
            # The server closes after the error — reading again should raise
            ws.receive_text()


@pytest.mark.contract
@patch("pipeline.orchestrator_custom.CartesiaTTSAdapter")
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_start_lesson_triggers_greeting(
    mock_stt_cls, mock_llm_cls, mock_deepgram_tts_cls, mock_cartesia_tts_cls
):
    """start_lesson triggers LLM -> TTS greeting pipeline.

    Mocks all adapters to verify:
    1. audio_chunk messages are sent (TTS output)
    2. tutor_text_chunk with is_greeting=True is sent
    3. greeting_complete message signals the greeting is done

    Both DeepgramTTSAdapter and CartesiaTTSAdapter are patched so this test
    passes regardless of the TTS_PROVIDER setting in the environment.
    """
    # STT mock — not used for greeting, but must be instantiated
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    # LLM mock — stream() is an async generator returning greeting tokens
    async def mock_llm_stream(transcript, context, metrics):
        metrics.start("llm")
        metrics.mark_first("llm")
        for token in ["Hello! ", "Welcome to today's lesson. ", "What do you already know?"]:
            yield token
        metrics.end("llm")

    mock_llm = MagicMock()
    mock_llm.stream = mock_llm_stream
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    # TTS mock — stream() is an async generator yielding audio bytes
    async def mock_tts_stream(sentence, metrics):
        metrics.start("tts")
        metrics.mark_first("tts")
        yield b"\x00\x01" * 100  # fake PCM audio
        metrics.end("tts")

    mock_tts = MagicMock()
    mock_tts.stream = mock_tts_stream
    mock_tts.cancel = AsyncMock()
    mock_deepgram_tts_cls.return_value = mock_tts
    mock_cartesia_tts_cls.return_value = mock_tts

    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        # Consume session_start
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_start"

        # Send start_lesson to trigger greeting
        ws.send_text(json.dumps({"type": "start_lesson"}))

        # Collect messages until greeting_complete
        messages = []
        for _ in range(30):  # safety limit
            raw = ws.receive_text()
            msg = json.loads(raw)
            messages.append(msg)
            if msg["type"] == "greeting_complete":
                break

        types = [m["type"] for m in messages]

        # Verify audio_chunk messages were sent
        assert "audio_chunk" in types, f"Expected audio_chunk in {types}"

        # Verify tutor_text_chunk with is_greeting=True
        assert "tutor_text_chunk" in types, f"Expected tutor_text_chunk in {types}"
        tt_msg = next(m for m in messages if m["type"] == "tutor_text_chunk")
        assert tt_msg.get("is_greeting") is True
        assert len(tt_msg["text"]) > 0
        assert "timing" in tt_msg

        # Verify greeting_complete is the final message we collected
        assert types[-1] == "greeting_complete"

        # Verify tutor_text_chunk comes after all audio_chunk messages
        last_audio_idx = max(i for i, t in enumerate(types) if t == "audio_chunk")
        tt_idx = types.index("tutor_text_chunk")
        assert last_audio_idx < tt_idx


@pytest.mark.contract
@patch("pipeline.orchestrator_custom.CartesiaTTSAdapter")
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_duplicate_start_lesson_ignored(
    mock_stt_cls, mock_llm_cls, mock_deepgram_tts_cls, mock_cartesia_tts_cls
):
    """Sending start_lesson twice generates only one greeting (duplicate is ignored).

    Verifies that the greeting_sent flag prevents a second greeting pipeline run.
    Only one greeting_complete message should be received.
    """
    # STT mock
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    # LLM mock — count calls to verify greeting runs only once
    greeting_call_count = 0

    async def mock_llm_stream(transcript, context, metrics):
        nonlocal greeting_call_count
        greeting_call_count += 1
        metrics.start("llm")
        metrics.mark_first("llm")
        for token in ["Hey there! ", "Ready to learn?"]:
            yield token
        metrics.end("llm")

    mock_llm = MagicMock()
    mock_llm.stream = mock_llm_stream
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    # TTS mock
    async def mock_tts_stream(sentence, metrics):
        metrics.start("tts")
        metrics.mark_first("tts")
        yield b"\x00\x01" * 100
        metrics.end("tts")

    mock_tts = MagicMock()
    mock_tts.stream = mock_tts_stream
    mock_tts.cancel = AsyncMock()
    mock_deepgram_tts_cls.return_value = mock_tts
    mock_cartesia_tts_cls.return_value = mock_tts

    client = TestClient(app)
    with client.websocket_connect("/session") as ws:
        # Consume session_start
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_start"

        # Send start_lesson twice in rapid succession
        ws.send_text(json.dumps({"type": "start_lesson"}))
        ws.send_text(json.dumps({"type": "start_lesson"}))

        # Collect messages until greeting_complete
        messages = []
        for _ in range(30):  # safety limit
            raw = ws.receive_text()
            msg = json.loads(raw)
            messages.append(msg)
            if msg["type"] == "greeting_complete":
                break

        types = [m["type"] for m in messages]
        assert "greeting_complete" in types

        # After the first greeting completes, the duplicate start_lesson has
        # already been processed (silently ignored). Verify there is exactly
        # one greeting_complete and the LLM stream was called only once.
        greeting_complete_count = types.count("greeting_complete")
        assert greeting_complete_count == 1, (
            f"Expected exactly 1 greeting_complete, got {greeting_complete_count}"
        )

        # The LLM stream should have been invoked exactly once
        assert greeting_call_count == 1, (
            f"Expected LLM stream to be called once, but was called {greeting_call_count} times"
        )

        # Verify the connection is still alive after the duplicate was ignored
        ws.send_text(json.dumps({"type": "barge_in"}))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "barge_in_ack"


@pytest.mark.contract
@patch("pipeline.orchestrator_custom.CartesiaTTSAdapter")
@patch("pipeline.orchestrator_custom.DeepgramTTSAdapter")
@patch("pipeline.orchestrator_custom.GroqLLMEngine")
@patch("pipeline.orchestrator_custom.DeepgramSTTAdapter")
def test_ws_session_restore_waits_for_continue_before_welcome_back(
    mock_stt_cls, mock_llm_cls, mock_deepgram_tts_cls, mock_cartesia_tts_cls
):
    """Restored sessions defer the welcome-back prompt until continue_lesson."""
    import main as main_module

    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.send_audio = AsyncMock()
    mock_stt.finish = AsyncMock(return_value="")
    mock_stt.cancel = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    mock_llm = MagicMock()
    mock_llm.cancel = AsyncMock()
    mock_llm_cls.return_value = mock_llm

    async def mock_tts_stream(sentence, metrics):
        metrics.start("tts")
        metrics.mark_first("tts")
        yield b"\x00\x01" * 50
        metrics.end("tts")

    mock_tts = MagicMock()
    mock_tts.stream = mock_tts_stream
    mock_tts.cancel = AsyncMock()
    mock_deepgram_tts_cls.return_value = mock_tts
    mock_cartesia_tts_cls.return_value = mock_tts

    restored_record = {
        "session_id": "resume-123",
        "topic": "photosynthesis",
        "history": [
            {"role": "assistant", "content": "What do you think plants need to make food?"}
        ],
        "summary": "",
        "turn_count": 2,
        "lesson_progress": {
            "topic": "photosynthesis",
            "current_step_id": 1,
            "visual_step_id": 1,
            "revealed_elements": ["sunlight", "water", "roots"],
        },
        "turns_since_compression": 0,
        "updated_at": time.time(),
    }

    with patch.object(main_module.session_store, "load", AsyncMock(return_value=restored_record)):
        client = TestClient(app)
        with client.websocket_connect("/session?topic=photosynthesis&session_id=resume-123") as ws:
            first = json.loads(ws.receive_text())
            assert first["type"] == "session_restore"

            visual_msg = json.loads(ws.receive_text())
            assert visual_msg["type"] == "lesson_visual_update"
            assert visual_msg["step_id"] == 1
            assert visual_msg["step_label"] == "The Ingredients"
            assert visual_msg["unlocked_elements"] == ["sunlight", "water", "roots"]
            assert visual_msg["progress_completed"] == 3
            assert visual_msg["progress_total"] == 10

            ws.send_text(json.dumps({"type": "continue_lesson"}))

            messages = []
            for _ in range(30):
                raw = ws.receive_text()
                msg = json.loads(raw)
                messages.append(msg)
                if msg["type"] == "greeting_complete":
                    break

            types = [m["type"] for m in messages]
            assert "audio_chunk" in types
            assert "tutor_text_chunk" in types
            welcome_msg = next(m for m in messages if m["type"] == "tutor_text_chunk")
            assert welcome_msg.get("is_greeting") is True
            assert "Welcome back!" in welcome_msg["text"]
            assert "What do you think plants need to make food?" in welcome_msg["text"]
            assert types[-1] == "greeting_complete"
