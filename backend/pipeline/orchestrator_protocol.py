"""
Orchestrator Protocol -- structural interface for pipeline orchestrators.

Uses typing.Protocol (not ABC) so that both the custom orchestrator and
any future LiveKit-based orchestrator can satisfy the contract through
structural subtyping (duck typing) without inheriting a shared base class.

Pipeline stage: Infrastructure (orchestration layer)

Exports:
    Orchestrator -- Protocol that every orchestrator implementation must
                    structurally satisfy.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class Orchestrator(Protocol):
    """Protocol defining the contract for pipeline orchestrators.

    An orchestrator coordinates the full STT -> LLM -> TTS -> Avatar
    pipeline for a single conversational turn, and handles student
    interrupts that require cancelling in-progress stages.

    Any class that implements the three methods below satisfies this
    protocol through structural subtyping -- no inheritance required.
    This makes it straightforward to swap between a custom orchestrator
    and a LiveKit Agents-based orchestrator without changing call sites.
    """

    async def handle_turn(
        self,
        audio_chunks: AsyncIterator[bytes],
        session: "SessionManager",
    ) -> None:
        """Execute a full conversational turn through the pipeline.

        Orchestrates audio through STT -> LLM -> TTS -> Avatar,
        streaming between stages wherever possible to minimize
        end-to-end latency.

        Args:
            audio_chunks: Async iterator of raw audio frames from the
                          student's microphone.
            session:      SessionManager holding conversation history,
                          topic state, and token budget.

        Raises:
            PipelineError:  If the orchestration itself fails.
            AdapterError:   If an individual stage adapter fails and
                            the error is not recoverable at the
                            orchestration level.
        """
        ...

    async def handle_interrupt(
        self,
        session: "SessionManager",
    ) -> None:
        """Handle a student interrupt (barge-in).

        Cancels all in-progress pipeline stages, flushes audio
        buffers, and returns the avatar to its listening pose so
        the pipeline is ready for the next student utterance.

        Args:
            session: SessionManager for updating conversation state
                     (e.g. marking the interrupted response as
                     incomplete).

        Raises:
            InterruptError: If one or more cleanup steps fail to
                            complete within the allowed window.
        """
        ...

    async def get_metrics(self) -> dict:
        """Return collected latency and throughput metrics.

        Returns a dict containing per-stage timing data and
        aggregate statistics useful for dashboards, logging, and
        latency regression tests.

        Returns:
            dict with keys such as "stt_ms", "llm_ttft_ms",
            "tts_first_byte_ms", "avatar_render_ms", "total_ms",
            and any provider-specific metadata.
        """
        ...
