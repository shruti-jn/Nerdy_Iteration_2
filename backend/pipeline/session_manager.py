"""
Session manager with token economy for the Socratic AI tutor.

Keeps LLM input tokens stable at ~1,500 regardless of session length by
compressing older conversation history into summaries. Uses the LLM engine's
``quick_call()`` method with a lightweight model for summary generation.

Pipeline stage: Session Management (Task 1H)

Exports:
    SessionManager -- Turn history manager with automatic compression
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.errors import SessionError

if TYPE_CHECKING:
    from adapters.base import BaseLLMEngine

logger = logging.getLogger(__name__)

# Summary generation prompt sent to the lightweight LLM
_SUMMARY_PROMPT_TEMPLATE = (
    "Summarize this tutoring conversation in 2-3 sentences. "
    "Focus on: what concept is being taught, what the student understands "
    "so far, what misconceptions remain, where the questioning left off, "
    "how many failed attempts on the current question, "
    "and whether Teacher Mode (direct explanation) was used.\n\n"
    "{conversation}"
)

# Model used for cheap/fast summary generation
_SUMMARY_MODEL = "llama-3.1-8b-instant"

# Number of messages (not turns) to keep in full detail after compression.
# 6 messages = 3 user+assistant pairs.
_KEEP_RECENT = 6

# Compression triggers when history exceeds this many messages
_COMPRESS_THRESHOLD = 12  # 6 turns = 12 messages


class SessionManager:
    """Manages conversation history with automatic compression.

    Keeps the most recent messages in full detail and compresses older
    messages into a summary string to bound LLM input size.

    Args:
        system_prompt: The Socratic system prompt (Layer 1 + 2 + 3).
        llm_engine:    An LLM engine implementing ``quick_call()`` for
                       summary generation.

    Attributes:
        history:    List of message dicts with 'role' and 'content' keys.
        summary:    Compressed summary of older conversation turns.
        turn_count: Total number of completed turns in the session.
    """

    COMPRESS_EVERY: int = 6  # Compress after every N turns

    def __init__(self, system_prompt: str, llm_engine: "BaseLLMEngine") -> None:
        self._system_prompt = system_prompt
        self._llm_engine = llm_engine
        self.history: list[dict] = []
        self.summary: str = ""
        self.turn_count: int = 0
        self.lesson_progress: dict | None = None
        self._turns_since_compression: int = 0

    def append_turn(
        self,
        student_input: str,
        tutor_response: str,
        interrupted: bool = False,
    ) -> None:
        """Add a completed turn to the conversation history.

        Args:
            student_input:  The student's transcribed utterance.
            tutor_response: The tutor's response text.
            interrupted:    Whether this turn was interrupted by the student.
                            If True, the response is marked with [interrupted].
        """
        self.history.append({"role": "user", "content": student_input})

        content = tutor_response
        if interrupted:
            content = f"{tutor_response} [interrupted]"

        self.history.append({"role": "assistant", "content": content})
        self.turn_count += 1
        self._turns_since_compression += 1

    def get_context(self) -> list[dict]:
        """Build the LLM context: system prompt + summary + recent messages.

        Returns a list of message dicts ready to pass to the LLM engine.
        The system prompt always comes first. If a summary exists from
        prior compression, it is included as part of the system message.
        The last ``_KEEP_RECENT`` messages from history are included in
        full detail.

        Returns:
            List of message dicts with 'role' and 'content' keys.
        """
        system_content = self._system_prompt
        if self.summary:
            system_content += f"\n\n[Conversation so far]: {self.summary}"

        messages: list[dict] = [{"role": "system", "content": system_content}]

        # Include the most recent messages in full
        recent = self.history[-_KEEP_RECENT:] if len(self.history) > _KEEP_RECENT else self.history
        messages.extend(recent)

        return messages

    def to_dict(self) -> dict:
        """Serialize session state for persistence.

        Returns:
            A dict with history, summary, turn_count, and internal counters.
        """
        return {
            "history": list(self.history),
            "summary": self.summary,
            "turn_count": self.turn_count,
            "lesson_progress": dict(self.lesson_progress) if self.lesson_progress is not None else None,
            "turns_since_compression": self._turns_since_compression,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        system_prompt: str,
        llm_engine: "BaseLLMEngine",
    ) -> "SessionManager":
        """Restore a SessionManager from serialized state.

        Args:
            data:          Dict produced by ``to_dict()``.
            system_prompt: The Socratic system prompt (Layer 1 + 2 + 3).
            llm_engine:    An LLM engine implementing ``quick_call()``.

        Returns:
            A SessionManager with restored conversation history.
        """
        instance = cls(system_prompt, llm_engine)
        instance.history = list(data.get("history", []))
        instance.summary = data.get("summary", "")
        instance.turn_count = data.get("turn_count", 0)
        lesson_progress = data.get("lesson_progress")
        instance.lesson_progress = dict(lesson_progress) if isinstance(lesson_progress, dict) else None
        instance._turns_since_compression = data.get("turns_since_compression", 0)
        return instance

    async def maybe_compress_history(self) -> None:
        """Compress older history if the threshold is met.

        Triggers compression when the total message count exceeds
        ``_COMPRESS_THRESHOLD``. Older messages beyond the most recent
        ``_KEEP_RECENT`` are summarised via the LLM and replaced with
        the summary string.

        On compression failure (LLM error), the session continues with
        the full uncompressed history — no exception is raised to the
        caller.
        """
        if len(self.history) < _COMPRESS_THRESHOLD:
            return

        if self._turns_since_compression < self.COMPRESS_EVERY:
            return

        # Messages to compress: everything except the most recent _KEEP_RECENT
        to_compress = self.history[:-_KEEP_RECENT]
        if not to_compress:
            return

        # Format the old messages for the summary prompt
        conversation_text = "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}" for msg in to_compress
        )

        # Include existing summary for cumulative compression
        if self.summary:
            conversation_text = f"Previous summary: {self.summary}\n\n{conversation_text}"

        prompt = _SUMMARY_PROMPT_TEMPLATE.format(conversation=conversation_text)

        try:
            new_summary = await self._llm_engine.quick_call(prompt, model=_SUMMARY_MODEL)
            self.summary = new_summary
            # Prune old messages, keep only the recent ones
            self.history = self.history[-_KEEP_RECENT:]
            self._turns_since_compression = 0
            logger.info(
                "Session history compressed: %d messages → summary + %d recent",
                len(to_compress) + _KEEP_RECENT,
                _KEEP_RECENT,
            )
        except Exception as exc:
            # Degrade gracefully: keep uncompressed history, log the error
            logger.warning(
                "Session compression failed, continuing with full history: %s",
                exc,
            )
