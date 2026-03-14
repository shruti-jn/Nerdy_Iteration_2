"""
Deepgram Nova-3 STT adapter using the live WebSocket streaming API.

Implements the BaseSTTAdapter ABC using Deepgram's ``/v1/listen`` live
endpoint.  Audio frames are forwarded as they arrive (no buffering),
and partial transcripts are emitted in real time via callbacks while
the student is still speaking.  The final transcript is returned from
``finish()`` after Deepgram flushes its internal buffer.

Pipeline stage: STT (Stage 1 of STT → LLM → TTS → Avatar)

Exports:
    DeepgramSTTAdapter -- Concrete STT adapter backed by Deepgram Nova-3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1.types import (
    ListenV1Results,
    ListenV1UtteranceEnd,
    ListenV1SpeechStarted,
)

from adapters.base import BaseSTTAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector

logger = logging.getLogger("tutor.stt")

# Safety timeout for waiting on Deepgram's final result after finalize.
# Reduced from 3.0 — speech_final now unblocks finish() immediately, so
# this timeout only fires if Deepgram sends neither speech_final nor
# UtteranceEnd (e.g. empty audio, connection hiccup).
_FINISH_TIMEOUT_S = 1.0


class DeepgramSTTAdapter(BaseSTTAdapter):
    """Deepgram-backed STT adapter using Nova-3 live WebSocket streaming.

    Opens a persistent WebSocket connection to Deepgram per utterance.
    Audio frames are forwarded immediately (no local buffering), and
    partial/final transcripts are delivered via callbacks.

    Args:
        settings: Application settings with ``deepgram_api_key`` and
                  optional ``stt_endpointing_ms``, ``stt_utterance_end_ms``,
                  ``stt_interim_results``.
    """

    def __init__(self, settings) -> None:
        self._api_key = settings.deepgram_api_key
        self._model = "nova-3"
        self._endpointing_ms: int = getattr(settings, "stt_endpointing_ms", 300)
        self._utterance_end_ms: int = getattr(settings, "stt_utterance_end_ms", 1000)
        self._interim_results: bool = getattr(settings, "stt_interim_results", True)

        # Per-utterance state (initialised in start(), cleared in _cleanup())
        self._client: AsyncDeepgramClient | None = None
        self._connection = None  # AsyncV1SocketClient via context manager
        self._ctx_manager = None  # the async context manager itself
        self._listen_task: asyncio.Task | None = None
        self._cancel_event = asyncio.Event()
        self._transcript_done = asyncio.Event()
        self._accumulated_finals: str = ""
        self._metrics: MetricsCollector | None = None
        self._on_partial: Callable[[str], Awaitable[None]] | None = None
        self._on_final: Callable[[str], Awaitable[None]] | None = None
        self._marked_first: bool = False
        self._active: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(
        self,
        metrics: MetricsCollector,
        on_partial: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
    ) -> None:
        """Open a Deepgram live WebSocket and begin accepting audio."""
        self._cancel_event.clear()
        self._transcript_done.clear()
        self._accumulated_finals = ""
        self._metrics = metrics
        self._on_partial = on_partial
        self._on_final = on_final
        self._marked_first = False
        self._active = True

        metrics.start("stt")

        try:
            self._client = AsyncDeepgramClient(api_key=self._api_key)
            self._ctx_manager = self._client.listen.v1.connect(
                model=self._model,
                language="en",
                smart_format="true",
                encoding="linear16",
                sample_rate="16000",
                channels="1",
                interim_results="true" if self._interim_results else "false",
                utterance_end_ms=str(self._utterance_end_ms),
                endpointing=str(self._endpointing_ms),
                vad_events="true",
            )
            self._connection = await self._ctx_manager.__aenter__()

            # Background task to consume incoming messages from Deepgram
            self._listen_task = asyncio.create_task(self._receive_loop())

        except Exception as exc:
            self._active = False
            metrics.end("stt")
            raise AdapterError(
                stage="stt",
                provider="deepgram",
                cause=exc,
            ) from exc

    async def send_audio(self, chunk: bytes) -> None:
        """Forward a raw PCM chunk to the Deepgram live connection."""
        if not self._active or self._cancel_event.is_set():
            return
        if self._connection is None:
            return
        try:
            await self._connection.send_media(chunk)
        except Exception as exc:
            logger.warning("stt send_audio error: %s", exc)

    async def finish(self) -> str:
        """Signal end of audio and return the accumulated transcript."""
        if not self._active:
            return ""

        try:
            # Tell Deepgram to flush any remaining audio
            if self._connection is not None:
                await self._connection.send_finalize()

            # Wait for Deepgram to deliver the final result + UtteranceEnd
            try:
                await asyncio.wait_for(
                    self._transcript_done.wait(),
                    timeout=_FINISH_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "stt finish timeout after %.1fs — using accumulated finals",
                    _FINISH_TIMEOUT_S,
                )
                if self._metrics:
                    self._metrics.end("stt")
        except Exception as exc:
            logger.error("stt finish error: %s", exc)
        finally:
            await self._cleanup()

        return self._accumulated_finals.strip()

    async def cancel(self) -> None:
        """Cancel in-progress recognition and close the connection."""
        if not self._active:
            return
        self._cancel_event.set()
        self._transcript_done.set()  # unblock any waiting finish()
        await self._cleanup()

    # ------------------------------------------------------------------
    # Internal: message receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Iterate over incoming Deepgram messages and dispatch."""
        if self._connection is None:
            return

        try:
            async for msg in self._connection:
                if self._cancel_event.is_set():
                    break
                await self._dispatch(msg)
        except Exception as exc:
            if not self._cancel_event.is_set():
                logger.error("stt receive_loop error: %s", exc)
            # Unblock finish() so the pipeline can proceed
            self._transcript_done.set()
            if self._metrics and not self._transcript_done.is_set():
                self._metrics.end("stt")

    async def _dispatch(self, msg) -> None:
        """Route a single Deepgram message to the appropriate handler."""
        if isinstance(msg, ListenV1Results):
            await self._handle_result(msg)
        elif isinstance(msg, ListenV1UtteranceEnd):
            self._handle_utterance_end(msg)
        elif isinstance(msg, ListenV1SpeechStarted):
            logger.debug("stt speech_started channel=%s ts=%.3f",
                         msg.channel, msg.timestamp)

    async def _handle_result(self, result: ListenV1Results) -> None:
        """Process a transcription result (interim or final)."""
        transcript = ""
        if result.channel and result.channel.alternatives:
            transcript = result.channel.alternatives[0].transcript or ""

        if not transcript:
            return

        # Mark time-to-first on the first transcript (partial or final)
        if not self._marked_first and self._metrics:
            self._metrics.mark_first("stt")
            self._marked_first = True

        if result.is_final:
            # Final segment — append to accumulated transcript
            if self._accumulated_finals:
                self._accumulated_finals += " " + transcript
            else:
                self._accumulated_finals = transcript

            if self._on_final:
                try:
                    await self._on_final(self._accumulated_finals)
                except Exception:
                    pass  # callback errors must not break the receive loop

            # If speech_final is set, Deepgram thinks the speaker is done.
            # Unblock finish() immediately — don't wait for UtteranceEnd,
            # which Deepgram often skips after send_finalize().
            if result.speech_final:
                logger.debug("stt speech_final transcript=%s", transcript[:60])
                if self._metrics and not self._transcript_done.is_set():
                    self._metrics.end("stt")
                self._transcript_done.set()
        else:
            # Interim result — show accumulated finals + current partial
            display_text = self._accumulated_finals
            if display_text:
                display_text += " " + transcript
            else:
                display_text = transcript

            if self._on_partial:
                try:
                    await self._on_partial(display_text)
                except Exception:
                    pass

    def _handle_utterance_end(self, msg: ListenV1UtteranceEnd) -> None:
        """Handle UtteranceEnd — Deepgram confirms the utterance is complete.

        Guarded: if speech_final already fired, metrics are already ended
        and _transcript_done is already set. Avoid double-ending.
        """
        logger.debug("stt utterance_end last_word_end=%.3f", msg.last_word_end)
        if self._metrics and not self._transcript_done.is_set():
            self._metrics.end("stt")
        self._transcript_done.set()

    # ------------------------------------------------------------------
    # Internal: cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Close the Deepgram connection and cancel the listen task."""
        if not self._active:
            return
        self._active = False

        # Cancel the background receive loop
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listen_task = None

        # Exit the async context manager (closes the WebSocket)
        if self._ctx_manager is not None:
            try:
                await self._ctx_manager.__aexit__(None, None, None)
            except Exception:
                pass
            self._ctx_manager = None
            self._connection = None

        self._client = None
