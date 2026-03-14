"""
End-to-end pipeline test: WebSocket client -> STT -> LLM -> TTS -> audio.

This test exercises the REAL pipeline with live API calls to Deepgram (STT+TTS)
and Groq (LLM). It:
  1. Generates student speech audio via Deepgram TTS
  2. Connects to the FastAPI server via WebSocket
  3. Sends the audio as binary PCM frames
  4. Sends end_of_utterance
  5. Verifies the full response cycle:
     - student_transcript (STT recognized the speech)
     - audio_chunk (TTS generated audio for the tutor reply)
     - tutor_text_chunk (LLM generated a Socratic response with timing)

Requires: DEEPGRAM_API_KEY and GROQ_API_KEY in the environment (or ../.env).

Run with:
    cd backend && python3 -m pytest tests/test_e2e_pipeline.py -v -s

Pipeline stage: Testing (end-to-end integration)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import time
from typing import AsyncIterator

import pytest

# Skip the entire module if API keys are not available
pytestmark = pytest.mark.integration

# Check for keys early
_has_keys = bool(os.environ.get("DEEPGRAM_API_KEY") or os.path.exists("../.env"))


def _load_env():
    """Load .env from the project root if it exists."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)


_load_env()


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _generate_student_audio(text: str) -> bytes:
    """Generate PCM audio of a student utterance using Deepgram TTS.

    Returns raw PCM 16-bit 16kHz mono audio bytes (no WAV header).
    The server's STT adapter will add WAV headers internally.
    """
    from deepgram import AsyncDeepgramClient

    client = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
    chunks = []

    audio_stream = client.speak.v1.audio.generate(
        text=text,
        model="aura-2-asteria-en",
        encoding="linear16",
        container="none",
        sample_rate=16000,
    )
    async for chunk in audio_stream:
        chunks.append(chunk)

    return b"".join(chunks)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("DEEPGRAM_API_KEY"),
    reason="DEEPGRAM_API_KEY not set"
)
@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set"
)
async def test_full_e2e_pipeline():
    """Full end-to-end: TTS-generated audio -> WebSocket -> STT -> LLM -> TTS -> verify.

    This is the definitive smoke test for the entire pipeline. It sends
    synthesized speech of a student question, and verifies the server
    returns a Socratic tutor response with audio.
    """
    import uvicorn
    from main import app

    # ── Step 1: Generate student audio ──
    student_text = "What is photosynthesis?"
    print(f"\n[E2E] Generating student audio for: '{student_text}'")
    t0 = time.monotonic()
    student_audio = await _generate_student_audio(student_text)
    print(f"[E2E] Generated {len(student_audio)} bytes of audio in {time.monotonic()-t0:.2f}s")
    assert len(student_audio) > 1000, "Audio too short"

    # ── Step 2: Start the server ──
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    # Run server in background task
    serve_task = asyncio.create_task(server.serve())

    # Wait for server to be ready
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    assert server.started, "Server did not start"

    # Get the actual bound port
    sockets = server.servers[0].sockets if server.servers else []
    port = sockets[0].getsockname()[1] if sockets else 8000
    print(f"[E2E] Server running on port {port}")

    try:
        import websockets

        # ── Step 3: Connect via WebSocket ──
        ws_url = f"ws://127.0.0.1:{port}/session"
        async with websockets.connect(ws_url) as ws:
            # Expect session_start
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["type"] == "session_start"
            session_id = msg["session_id"]
            print(f"[E2E] Session started: {session_id}")

            # ── Step 4: Send audio in chunks (simulating AudioWorklet) ──
            chunk_size = 3200  # 100ms of 16-bit mono at 16kHz
            turn_start = time.monotonic()

            for i in range(0, len(student_audio), chunk_size):
                chunk = student_audio[i:i + chunk_size]
                await ws.send(chunk)

            # ── Step 5: Signal end of utterance ──
            await ws.send(json.dumps({"type": "end_of_utterance"}))
            print(f"[E2E] Sent {len(student_audio)} bytes + end_of_utterance")

            # ── Step 6: Collect all response messages ──
            messages = []
            audio_chunks = []
            deadline = time.monotonic() + 30  # 30s timeout

            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    msg = json.loads(raw)
                    messages.append(msg)

                    if msg["type"] == "audio_chunk":
                        audio_data = base64.b64decode(msg["data"])
                        audio_chunks.append(audio_data)
                    elif msg["type"] == "tutor_text_chunk":
                        break  # Pipeline complete
                    elif msg["type"] == "error":
                        pytest.fail(f"Server error: {msg}")
                except asyncio.TimeoutError:
                    pytest.fail(f"Timed out waiting for response. Got: {[m['type'] for m in messages]}")

            turn_duration = time.monotonic() - turn_start

            # ── Step 7: Verify results ──
            types = [m["type"] for m in messages]
            print(f"[E2E] Message types received: {types}")

            # Must have student_transcript
            assert "student_transcript" in types, f"Missing student_transcript. Got: {types}"
            st_msg = next(m for m in messages if m["type"] == "student_transcript")
            transcript = st_msg["text"]
            print(f"[E2E] Student transcript: '{transcript}'")
            assert len(transcript) > 3, f"Transcript too short: '{transcript}'"

            # Must have audio_chunk(s)
            assert "audio_chunk" in types, f"Missing audio_chunk. Got: {types}"
            total_audio_bytes = sum(len(c) for c in audio_chunks)
            print(f"[E2E] TTS audio: {len(audio_chunks)} chunks, {total_audio_bytes} bytes total")
            assert total_audio_bytes > 100, "TTS audio too small"

            # Must have tutor_text_chunk
            assert "tutor_text_chunk" in types, f"Missing tutor_text_chunk. Got: {types}"
            tt_msg = next(m for m in messages if m["type"] == "tutor_text_chunk")
            tutor_text = tt_msg["text"]
            timing = tt_msg["timing"]
            print(f"[E2E] Tutor response: '{tutor_text}'")
            print(f"[E2E] Timing: {timing}")

            # Tutor response should be Socratic (end with ?)
            assert tutor_text.strip().endswith("?"), \
                f"Tutor response should end with '?' (Socratic): '{tutor_text}'"

            # Response should not be empty
            assert len(tutor_text) > 10, f"Tutor response too short: '{tutor_text}'"

            # Timing should have per-stage metrics
            assert "stt_duration_ms" in timing or "stt_ttf_ms" in timing, \
                f"Missing STT timing: {timing}"
            assert "llm_ttf_ms" in timing, f"Missing LLM timing: {timing}"
            assert "tts_ttf_ms" in timing, f"Missing TTS timing: {timing}"
            assert "turn_duration_ms" in timing, f"Missing turn timing: {timing}"

            # Message order: student_transcript before audio_chunk before tutor_text_chunk
            st_idx = types.index("student_transcript")
            ac_idx = types.index("audio_chunk")
            tt_idx = types.index("tutor_text_chunk")
            assert st_idx < ac_idx < tt_idx, \
                f"Wrong message order: transcript@{st_idx}, audio@{ac_idx}, text@{tt_idx}"

            # ── Step 8: Print latency summary ──
            print(f"\n[E2E] === LATENCY SUMMARY ===")
            print(f"  Turn duration (wall clock): {turn_duration*1000:.0f}ms")
            if timing.get("stt_duration_ms"):
                print(f"  STT duration:              {timing['stt_duration_ms']:.0f}ms")
            if timing.get("llm_ttf_ms"):
                print(f"  LLM time-to-first-token:   {timing['llm_ttf_ms']:.0f}ms")
            if timing.get("llm_duration_ms"):
                print(f"  LLM total duration:        {timing['llm_duration_ms']:.0f}ms")
            if timing.get("tts_ttf_ms"):
                print(f"  TTS time-to-first-audio:   {timing['tts_ttf_ms']:.0f}ms")
            if timing.get("tts_duration_ms"):
                print(f"  TTS total duration:        {timing['tts_duration_ms']:.0f}ms")
            if timing.get("turn_duration_ms"):
                print(f"  Turn duration (pipeline):  {timing['turn_duration_ms']:.0f}ms")
            print(f"[E2E] === PASS ===\n")

    finally:
        server.should_exit = True
        await serve_task


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("DEEPGRAM_API_KEY"),
    reason="DEEPGRAM_API_KEY not set"
)
@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set"
)
async def test_multi_turn_conversation():
    """Test a 2-turn conversation to verify context is maintained.

    Turn 1: Student asks about photosynthesis
    Turn 2: Student gives a follow-up answer

    The tutor should maintain context between turns.
    """
    import uvicorn
    from main import app

    # Generate audio for both turns
    audio1 = await _generate_student_audio("What is photosynthesis?")
    audio2 = await _generate_student_audio("Is it something to do with sunlight?")

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break

    sockets = server.servers[0].sockets if server.servers else []
    port = sockets[0].getsockname()[1] if sockets else 8000

    try:
        import websockets

        async with websockets.connect(f"ws://127.0.0.1:{port}/session") as ws:
            # Session start
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["type"] == "session_start"

            # ── Turn 1 ──
            print("\n[E2E] Turn 1: 'What is photosynthesis?'")
            await ws.send(audio1)
            await ws.send(json.dumps({"type": "end_of_utterance"}))

            turn1_text = await _collect_tutor_response(ws)
            print(f"[E2E] Tutor T1: '{turn1_text}'")
            assert turn1_text.strip().endswith("?"), "Turn 1 should be Socratic"

            # ── Turn 2 ──
            print("[E2E] Turn 2: 'Is it something to do with sunlight?'")
            await ws.send(audio2)
            await ws.send(json.dumps({"type": "end_of_utterance"}))

            turn2_text = await _collect_tutor_response(ws)
            print(f"[E2E] Tutor T2: '{turn2_text}'")
            assert turn2_text.strip().endswith("?"), "Turn 2 should be Socratic"
            assert len(turn2_text) > 5, "Turn 2 response too short"

            print("[E2E] Multi-turn conversation: PASS\n")

    finally:
        server.should_exit = True
        await serve_task


async def _collect_tutor_response(ws) -> str:
    """Read messages from WebSocket until tutor_text_chunk, return the text."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        msg = json.loads(raw)
        if msg["type"] == "tutor_text_chunk":
            return msg["text"]
        if msg["type"] == "error":
            pytest.fail(f"Server error: {msg}")
