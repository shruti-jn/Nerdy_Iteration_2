"""
Typed exception hierarchy for the Live AI Video Tutor pipeline.

Every exception carries structured context so that error handlers and
loggers can emit machine-readable diagnostics without parsing messages.

Hierarchy:
    TutorError                 (base for all pipeline errors)
    +-- AdapterError           (external service adapter failed)
    |   +-- AdapterTimeoutError(adapter exceeded latency budget)
    +-- PipelineError          (orchestration-level failure)
    +-- SessionError           (session / token management failed)
    +-- InterruptError         (interrupt handling incomplete)

Pipeline stage: Infrastructure (shared by all stages)
"""

from __future__ import annotations

from typing import Optional


class TutorError(Exception):
    """Base exception for all pipeline errors.

    Attributes:
        message:  Human-readable description of the failure.
        context:  Optional dict of structured metadata for logging
                  (e.g. session_id, request_id, timestamps).
    """

    message: str
    context: Optional[dict]

    def __init__(self, message: str, *, context: Optional[dict] = None) -> None:
        """Initialise with a message and optional structured context.

        Args:
            message: Human-readable error description.
            context: Arbitrary key-value pairs for structured logging.
        """
        self.message = message
        self.context = context
        super().__init__(message)

    def __repr__(self) -> str:
        """Return a developer-friendly representation including context."""
        if self.context:
            return f"{self.__class__.__name__}({self.message!r}, context={self.context!r})"
        return f"{self.__class__.__name__}({self.message!r})"


class AdapterError(TutorError):
    """An external service adapter (STT, LLM, TTS, Avatar) failed.

    The formatted message follows the pattern:
        [stage/provider] CauseClass: cause message

    Attributes:
        stage:    Pipeline stage that failed ("stt", "llm", "tts", or "avatar").
        provider: Service provider name ("deepgram", "groq", "cartesia", or "simli").
        cause:    The original exception raised by the adapter.
    """

    stage: str
    provider: str
    cause: Exception

    def __init__(
        self,
        *,
        stage: str,
        provider: str,
        cause: Exception,
        context: Optional[dict] = None,
    ) -> None:
        """Initialise from a failed adapter call.

        Args:
            stage:    Pipeline stage identifier.
            provider: External service provider name.
            cause:    The underlying exception from the adapter.
            context:  Optional structured metadata for logging.
        """
        self.stage = stage
        self.provider = provider
        self.cause = cause
        message = f"[{stage}/{provider}] {cause.__class__.__name__}: {cause}"
        super().__init__(message, context=context)

    def __repr__(self) -> str:
        """Return repr including stage, provider, and cause."""
        parts = (
            f"stage={self.stage!r}, "
            f"provider={self.provider!r}, "
            f"cause={self.cause!r}"
        )
        if self.context:
            parts += f", context={self.context!r}"
        return f"{self.__class__.__name__}({parts})"


class AdapterTimeoutError(AdapterError):
    """An adapter exceeded its per-stage latency budget.

    The *cause* attribute is auto-created as a ``TimeoutError`` whose
    message includes both the budget and actual durations so that it is
    self-describing when logged.

    Attributes:
        budget_ms: Maximum allowed latency for the stage (milliseconds).
        actual_ms: Observed latency that triggered the timeout (milliseconds).
    """

    budget_ms: float
    actual_ms: float

    def __init__(
        self,
        *,
        stage: str,
        provider: str,
        budget_ms: float,
        actual_ms: float,
        context: Optional[dict] = None,
    ) -> None:
        """Initialise from a latency budget violation.

        Args:
            stage:     Pipeline stage identifier.
            provider:  External service provider name.
            budget_ms: Maximum allowed latency in milliseconds.
            actual_ms: Actual observed latency in milliseconds.
            context:   Optional structured metadata for logging.
        """
        self.budget_ms = budget_ms
        self.actual_ms = actual_ms
        # Auto-create a TimeoutError as the underlying cause
        cause = TimeoutError(f"Budget {budget_ms}ms, actual {actual_ms}ms")
        super().__init__(
            stage=stage,
            provider=provider,
            cause=cause,
            context=context,
        )

    def __repr__(self) -> str:
        """Return repr including budget and actual latency."""
        parts = (
            f"stage={self.stage!r}, "
            f"provider={self.provider!r}, "
            f"budget_ms={self.budget_ms!r}, "
            f"actual_ms={self.actual_ms!r}"
        )
        if self.context:
            parts += f", context={self.context!r}"
        return f"{self.__class__.__name__}({parts})"


class PipelineError(TutorError):
    """Orchestration-level failure in the pipeline.

    Raised when the orchestrator itself fails — possibly aggregating
    multiple per-stage ``AdapterError`` instances that contributed to
    the overall failure.

    Attributes:
        stage_errors: List of ``AdapterError`` instances from individual
                      stages that failed during this pipeline run.
    """

    stage_errors: list[AdapterError]

    def __init__(
        self,
        message: str,
        *,
        stage_errors: Optional[list[AdapterError]] = None,
        context: Optional[dict] = None,
    ) -> None:
        """Initialise with a message and optional list of stage errors.

        Args:
            message:      Human-readable description of the pipeline failure.
            stage_errors: Adapter-level errors collected during the run.
            context:      Optional structured metadata for logging.
        """
        self.stage_errors = stage_errors if stage_errors is not None else []
        super().__init__(message, context=context)

    def __repr__(self) -> str:
        """Return repr including count and details of stage errors."""
        parts = f"{self.message!r}, stage_errors={self.stage_errors!r}"
        if self.context:
            parts += f", context={self.context!r}"
        return f"{self.__class__.__name__}({parts})"


class SessionError(TutorError):
    """Session management failed.

    Covers failures in token economy tracking, conversation history
    compression, and session lifecycle management.
    """

    # No additional attributes beyond TutorError; context dict carries
    # session-specific metadata (session_id, tokens_used, etc.).


class InterruptError(TutorError):
    """Interrupt handling did not complete cleanly.

    Raised when a student interruption triggers pipeline cancellation
    but some cleanup step (draining audio buffers, aborting in-flight
    requests, resetting avatar state) fails to finish.
    """

    # No additional attributes beyond TutorError; context dict carries
    # interrupt-specific metadata (pending_chunks, aborted_stages, etc.).
