"""
Voice Activity Detection handler and interrupt state machine.

Manages the conversation state through the turn lifecycle:
    IDLE → LISTENING → PROCESSING → SPEAKING → IDLE

Supports cooperative interrupt handling: when the student starts speaking
while the tutor is speaking, the state machine transitions back to
LISTENING and calls all registered cancel callbacks (LLM, TTS, Avatar)
to abort the current pipeline run.

Pipeline stage: VAD / Interruption (Task 1G)

Exports:
    VADHandler -- State machine for turn management and interrupts
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Literal

from pipeline.errors import InterruptError

# Valid state transitions: current_state -> set of allowed next states
_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"listening"},
    "listening": {"processing"},
    "processing": {"speaking"},
    "speaking": {"listening", "idle"},
}

# Maximum time allowed for all cancel callbacks to complete (seconds)
_INTERRUPT_TIMEOUT_S = 0.2  # 200ms


class VADHandler:
    """State machine for conversation turn management and interrupt handling.

    Tracks the current state of the tutoring session and provides methods
    for each valid transition. Invalid transitions raise ``ValueError``
    with a clear message. Interrupt handling calls registered cancel
    callbacks (e.g. to abort LLM streaming, TTS synthesis, avatar
    rendering) and transitions from SPEAKING back to LISTENING.

    Attributes:
        state:          Current state of the state machine.
        is_interrupted: Whether the last completed turn was interrupted.
    """

    def __init__(self) -> None:
        self._state: Literal["idle", "listening", "processing", "speaking"] = "idle"
        self._is_interrupted: bool = False
        self._cancel_callbacks: dict[str, Callable[[], Awaitable[None]]] = {}

    # -- Properties ------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current state of the state machine."""
        return self._state

    @property
    def is_interrupted(self) -> bool:
        """Whether the last turn was interrupted by the student."""
        return self._is_interrupted

    # -- State Transitions -----------------------------------------------------

    def _transition(self, target: str) -> None:
        """Transition to a new state, raising ValueError if invalid.

        Args:
            target: The desired next state.

        Raises:
            ValueError: If the transition from current state to target
                        is not allowed.
        """
        allowed = _TRANSITIONS.get(self._state, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {self._state!r} → {target!r}. "
                f"Allowed from {self._state!r}: {sorted(allowed)}"
            )
        self._state = target

    def start_listening(self) -> None:
        """Transition from IDLE to LISTENING.

        Called when the microphone is activated and the system is ready
        to receive student audio.
        """
        self._transition("listening")

    def start_processing(self) -> None:
        """Transition from LISTENING to PROCESSING.

        Called when end-of-utterance is detected and the pipeline begins
        STT → LLM → TTS processing. Resets the interrupted flag from
        any previous turn.
        """
        self._transition("processing")
        self._is_interrupted = False

    def start_speaking(self) -> None:
        """Transition from PROCESSING to SPEAKING.

        Called when the TTS begins producing audio and the avatar starts
        lip-syncing the tutor response.
        """
        self._transition("speaking")

    def finish_speaking(self) -> None:
        """Transition from SPEAKING to IDLE.

        Called when the tutor response is fully delivered and the avatar
        returns to its listening pose.
        """
        self._transition("idle")

    # -- Cancel Callback Registration ------------------------------------------

    def register_cancel_callback(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Register an async callback to be invoked on interrupt.

        Multiple callbacks can be registered (e.g. one for LLM, one for
        TTS, one for Avatar). All are called concurrently during
        ``interrupt()``.

        Args:
            name:     A descriptive name for logging (e.g. "llm", "tts").
            callback: An async callable that cancels the named stage.
        """
        self._cancel_callbacks[name] = callback

    # -- Interrupt Handling ----------------------------------------------------

    async def interrupt(self) -> None:
        """Handle a student interrupt while the tutor is speaking.

        If the current state is SPEAKING:
          1. Calls all registered cancel callbacks concurrently.
          2. Transitions to LISTENING.
          3. Sets the ``is_interrupted`` flag.

        If the current state is anything other than SPEAKING, this
        method is a no-op (no error, state unchanged).

        Raises:
            InterruptError: If the combined cancel callbacks exceed the
                            200ms timeout budget.
        """
        if self._state != "speaking":
            return

        # Run all cancel callbacks concurrently with a timeout
        if self._cancel_callbacks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(cb() for cb in self._cancel_callbacks.values()),
                        return_exceptions=True,
                    ),
                    timeout=_INTERRUPT_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                raise InterruptError(
                    f"Cancel callbacks exceeded {_INTERRUPT_TIMEOUT_S * 1000:.0f}ms budget",
                    context={
                        "callbacks": list(self._cancel_callbacks.keys()),
                        "timeout_ms": _INTERRUPT_TIMEOUT_S * 1000,
                    },
                )

        self._state = "listening"
        self._is_interrupted = True
