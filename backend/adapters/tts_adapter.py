"""
Deepgram Aura TTS adapter for low-latency speech synthesis.

Implements the BaseTTSAdapter ABC with streaming audio generation via the
Deepgram Python SDK's speak API. Outputs raw PCM 16-bit 16 kHz mono audio
for Simli avatar compatibility. Records time-to-first-audio (TTFA) through
the MetricsCollector and wraps all SDK exceptions into AdapterError.

Supports cooperative cancellation via asyncio.Event for interrupt handling.

Pipeline stage: TTS (Stage 3 of STT → LLM → TTS → Avatar)

Exports:
    DeepgramTTSAdapter -- Concrete TTS adapter backed by Deepgram Aura
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import AsyncIterator

logger = logging.getLogger("tutor.tts")

from cartesia import AsyncCartesia
from deepgram import AsyncDeepgramClient

from adapters.base import BaseTTSAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


class DeepgramTTSAdapter(BaseTTSAdapter):
    """Deepgram Aura-backed TTS adapter for streaming audio synthesis.

    Uses ``aura-2-asteria-en`` model by default and outputs raw PCM
    16-bit 16 kHz mono (container=none, encoding=linear16) for direct
    compatibility with Simli's ``sendAudioData()`` method.

    Args:
        settings: Application settings with ``deepgram_api_key``.
    """

    def __init__(self, settings) -> None:
        self._client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
        self._model = "aura-2-asteria-en"
        self._cancel_event = asyncio.Event()

    async def stream(
        self,
        sentence: str,
        metrics: MetricsCollector,
    ) -> AsyncIterator[bytes]:
        """Stream synthesised audio for a single sentence.

        Sends text to Deepgram Aura and yields PCM audio chunks as they
        arrive. Records TTFA via ``metrics.mark_first("tts")`` on the
        first chunk.

        Args:
            sentence: The text to synthesise.
            metrics:  MetricsCollector for recording TTFA and duration.

        Yields:
            Raw PCM 16-bit 16 kHz mono audio chunks.

        Raises:
            AdapterError: Wraps any Deepgram SDK exception.
        """
        if not sentence or not sentence.strip():
            return

        self._cancel_event.clear()

        try:
            metrics.start("tts")
            # generate() returns an async generator (not a coroutine)
            audio_stream = self._client.speak.v1.audio.generate(
                text=sentence,
                model=self._model,
                encoding="linear16",
                container="none",
                sample_rate=16000,
            )

            first_chunk = True
            async for chunk in audio_stream:
                if self._cancel_event.is_set():
                    break

                if first_chunk:
                    metrics.mark_first("tts")
                    first_chunk = False

                yield chunk

            metrics.end("tts")

        except Exception as exc:
            metrics.end("tts")
            raise AdapterError(
                stage="tts",
                provider="deepgram",
                cause=exc,
            ) from exc

    async def cancel(self) -> None:
        """Signal the streaming loop to stop on the next iteration."""
        self._cancel_event.set()


class CartesiaTTSAdapter(BaseTTSAdapter):
    """Cartesia Sonic-3 backed TTS adapter for streaming audio synthesis.

    Uses ``sonic-3`` model and outputs raw PCM 16-bit 16 kHz mono
    (container=raw, encoding=pcm_s16le, sample_rate=16000) for direct
    compatibility with Simli's ``sendAudioData()`` method.

    Targets ~40ms time-to-first-audio vs. Deepgram Aura-2's ~150-200ms.

    Args:
        settings: Application settings with ``cartesia_api_key`` and
                  ``cartesia_voice_id``.
    """

    def __init__(self, settings) -> None:
        self._client = AsyncCartesia(api_key=settings.cartesia_api_key)
        self._voice_id = settings.cartesia_voice_id
        self._cancel_event = asyncio.Event()

    async def stream(
        self,
        sentence: str,
        metrics: MetricsCollector,
    ) -> AsyncIterator[bytes]:
        """Stream synthesised audio for a single sentence via Cartesia Sonic-3.

        Sends text to Cartesia and yields PCM audio chunks as they arrive.
        Skips non-chunk SSE events (timestamps, done, error). Records TTFA
        via ``metrics.mark_first("tts")`` on the first audio chunk.

        Args:
            sentence: The text to synthesise.
            metrics:  MetricsCollector for recording TTFA and duration.

        Yields:
            Raw PCM 16-bit 16 kHz mono audio chunks.

        Raises:
            AdapterError: Wraps any Cartesia SDK exception.
        """
        if not sentence or not sentence.strip():
            return

        # Skip punctuation-only fragments — Cartesia rejects them with 400
        if re.fullmatch(r'[\s.!?,;:\-—…""\'()]+', sentence):
            logger.debug("tts cartesia skipping punctuation-only: %r", sentence)
            return

        self._cancel_event.clear()

        try:
            metrics.start("tts")
            t0 = time.monotonic_ns()
            stream = await self._client.tts.generate_sse(
                model_id="sonic-3",
                transcript=sentence,
                voice={"id": self._voice_id, "mode": "id"},
                output_format={
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000,
                },
            )
            api_call_ms = (time.monotonic_ns() - t0) / 1_000_000
            logger.debug("tts cartesia api_call_ms=%.1f sentence=%s", api_call_ms, sentence[:60])

            first_chunk = True
            chunk_count = 0
            async for event in stream:
                if self._cancel_event.is_set():
                    break

                # Only yield audio from chunk events; skip timestamps/done/error
                if event.type != "chunk" or not event.audio:
                    continue

                chunk_count += 1
                if first_chunk:
                    ttfa_ms = (time.monotonic_ns() - t0) / 1_000_000
                    logger.debug("tts cartesia ttfa_ms=%.1f sentence=%s", ttfa_ms, sentence[:60])
                    metrics.mark_first("tts")
                    first_chunk = False

                yield event.audio

            total_ms = (time.monotonic_ns() - t0) / 1_000_000
            logger.debug("tts cartesia total_ms=%.1f chunks=%d sentence=%s", total_ms, chunk_count, sentence[:60])
            metrics.end("tts")

        except Exception as exc:
            metrics.end("tts")
            raise AdapterError(
                stage="tts",
                provider="cartesia",
                cause=exc,
            ) from exc

    async def cancel(self) -> None:
        """Signal the streaming loop to stop on the next iteration."""
        self._cancel_event.set()
