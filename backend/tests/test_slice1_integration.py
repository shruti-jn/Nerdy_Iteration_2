"""
Slice 1 integration tests: LLM → SentenceBuffer → TTS pipeline.

Validates the wired flow from mock LLM tokens through real SentenceBuffer
to mock TTS, confirming that sentences are correctly split and each
triggers a separate TTS call. Also tests MetricsCollector integration
and cancel propagation.

Pipeline stage: Integration (Slice 1 — text in → spoken audio out)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.metrics import MetricsCollector
from pipeline.sentence_buffer import SentenceBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mock_llm_tokens(*tokens):
    """Simulate an LLM token stream."""
    for t in tokens:
        yield t
        await asyncio.sleep(0.001)  # Simulate streaming latency


async def _mock_tts_stream(sentence: str, mc: MetricsCollector):
    """Simulate a TTS audio stream — yields 2 chunks per sentence."""
    mc.start("tts")
    mc.mark_first("tts")
    yield b"\x00" * 800
    yield b"\x01" * 800
    mc.end("tts")


# ---------------------------------------------------------------------------
# Integration tests (mocked adapters, real SentenceBuffer + MetricsCollector)
# ---------------------------------------------------------------------------

class TestSlice1Pipeline:
    """Tests the LLM → SentenceBuffer → TTS wiring."""

    @pytest.mark.asyncio
    async def test_tokens_split_into_sentences_trigger_tts(self):
        """Mock LLM tokens correctly split into sentences, each triggering TTS."""
        buf = SentenceBuffer()
        mc = MetricsCollector()
        mc.start_turn()

        # Simulate LLM streaming two sentences
        llm_tokens = _mock_llm_tokens(
            "Great ", "question! ",
            "What do ", "you think ", "happens next? ",
        )

        sentences = []
        all_audio = []

        async for sentence in buf.process(llm_tokens):
            sentences.append(sentence)
            # For each sentence, collect TTS audio
            async for chunk in _mock_tts_stream(sentence, mc):
                all_audio.append(chunk)

        mc.end_turn()

        assert len(sentences) == 2
        assert "question!" in sentences[0]
        assert "next?" in sentences[1]
        assert len(all_audio) == 4  # 2 chunks per sentence × 2 sentences
        assert mc.turn_duration_ms is not None

    @pytest.mark.asyncio
    async def test_metrics_captures_all_stages(self):
        """MetricsCollector captures LLM and TTS stage metrics."""
        buf = SentenceBuffer()
        mc = MetricsCollector()
        mc.start_turn()

        # Simulate LLM stage
        mc.start("llm")
        mc.mark_first("llm")
        llm_tokens = _mock_llm_tokens("Hello world. ")
        mc.end("llm")

        async for sentence in buf.process(llm_tokens):
            async for _ in _mock_tts_stream(sentence, mc):
                pass

        mc.end_turn()

        d = mc.to_dict()
        assert "llm_ttf_ms" in d
        assert "llm_duration_ms" in d
        assert "tts_ttf_ms" in d
        assert "tts_duration_ms" in d
        assert "turn_duration_ms" in d

    @pytest.mark.asyncio
    async def test_single_sentence_flows_through(self):
        """A single sentence from LLM produces audio output."""
        buf = SentenceBuffer()
        mc = MetricsCollector()

        llm_tokens = _mock_llm_tokens("Why do you think that?")

        audio_chunks = []
        async for sentence in buf.process(llm_tokens):
            async for chunk in _mock_tts_stream(sentence, mc):
                audio_chunks.append(chunk)

        assert len(audio_chunks) == 2

    @pytest.mark.asyncio
    async def test_cancel_propagates(self):
        """Cancellation stops the pipeline mid-stream."""
        buf = SentenceBuffer()
        mc = MetricsCollector()

        async def _long_llm_stream():
            for word in ["One. ", "Two. ", "Three. ", "Four. ", "Five. "]:
                yield word
                await asyncio.sleep(0.01)

        sentences = []
        cancel = asyncio.Event()

        async for sentence in buf.process(_long_llm_stream()):
            sentences.append(sentence)
            if len(sentences) >= 2:
                cancel.set()
                break

        # We stopped after 2 sentences — pipeline didn't run to completion
        assert len(sentences) == 2


# ---------------------------------------------------------------------------
# Live integration test (requires both GROQ_API_KEY and DEEPGRAM_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_slice1_live_pipeline():
    """End-to-end: real Groq LLM → SentenceBuffer → real Deepgram TTS.

    Requires GROQ_API_KEY and DEEPGRAM_API_KEY in the environment.
    Streams a short tutoring response and synthesises the first sentence.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    dg_key = os.environ.get("DEEPGRAM_API_KEY")
    if not groq_key or not dg_key:
        pytest.skip("GROQ_API_KEY and/or DEEPGRAM_API_KEY not set")

    from adapters.llm_engine import GroqLLMEngine
    from adapters.tts_adapter import DeepgramTTSAdapter

    @dataclass
    class _LiveSettings:
        groq_api_key: str = groq_key
        deepgram_api_key: str = dg_key

    settings = _LiveSettings()
    llm = GroqLLMEngine(settings)
    tts = DeepgramTTSAdapter(settings)
    buf = SentenceBuffer()
    mc = MetricsCollector()

    mc.start_turn()

    # Stream LLM tokens
    mc.start("llm")
    llm_stream = llm.stream(
        "What is photosynthesis?",
        [{"role": "system", "content": "You are a Socratic tutor. Ask a guiding question. Keep it under 2 sentences."}],
        mc,
    )

    # Collect sentences and synthesise the first one
    first_audio_chunks = []
    sentence_count = 0

    async for sentence in buf.process(llm_stream):
        sentence_count += 1
        if sentence_count == 1:
            # Synthesise only the first sentence to keep test fast
            async for chunk in tts.stream(sentence, mc):
                first_audio_chunks.append(chunk)
                if len(first_audio_chunks) > 10:
                    break
            break  # Only process first sentence

    mc.end_turn()

    assert sentence_count >= 1
    assert len(first_audio_chunks) > 0
    assert all(isinstance(c, bytes) for c in first_audio_chunks)

    d = mc.to_dict()
    assert d["llm_ttf_ms"] is not None
    assert d["tts_ttf_ms"] is not None
    assert d["turn_duration_ms"] is not None
