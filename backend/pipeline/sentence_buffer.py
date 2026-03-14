"""
Sentence boundary detection for LLM token streams.

Accumulates streamed LLM tokens and yields complete sentences at
sentence-ending punctuation boundaries (.?!). Handles common
abbreviations, decimal numbers, and ellipsis to avoid false splits.

Pipeline stage: Orchestration (between LLM and TTS)

Exports:
    SentenceBuffer -- Async token-to-sentence transformer
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import AsyncIterator

# Common abbreviations that end with a period but are NOT sentence endings.
# Kept lowercase for case-insensitive matching.
_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "st.", "ave.", "blvd.", "dept.", "est.", "govt.",
    "inc.", "ltd.", "corp.", "vs.", "etc.", "approx.",
    "i.e.", "e.g.", "u.s.", "u.k.", "a.m.", "p.m.",
    "fig.", "vol.", "no.",
})

# Regex: sentence-ending punctuation followed by whitespace or end-of-string.
# Captures the punctuation so we can include it in the yielded sentence.
_SENTENCE_END_RE = re.compile(r'([.!?])(?:\s|$)')

# Time-based flush: if this many seconds pass without a sentence boundary and
# the buffer has at least _FLUSH_MIN_CHARS characters, flush to TTS anyway.
# Prevents starvation when LLM generates long phrases without punctuation.
_FLUSH_TIMEOUT_S = 0.4
_FLUSH_MIN_CHARS = 15


class SentenceBuffer:
    """Accumulates LLM tokens and yields complete sentences.

    Designed for the hot path between LLM streaming and TTS synthesis.
    Each yielded sentence is stripped of leading/trailing whitespace.

    Usage::

        buf = SentenceBuffer()
        async for sentence in buf.process(token_stream):
            await tts.stream(sentence, metrics)
    """

    def __init__(self) -> None:
        self._buffer: str = ""

    async def process(self, token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """Consume a token stream and yield complete sentences.

        Tokens are accumulated in an internal buffer. When a sentence-ending
        punctuation mark (.?!) is detected followed by whitespace (or the
        stream ends), the accumulated sentence is yielded.

        Time-based flush: if ``_FLUSH_TIMEOUT_S`` passes with at least
        ``_FLUSH_MIN_CHARS`` buffered and no sentence boundary, the buffer
        is flushed to TTS. This prevents starvation when the LLM generates
        long phrases without terminal punctuation (e.g. "Let me think —").

        Abbreviations like "Dr.", "U.S.", "e.g." are recognized and do NOT
        trigger a sentence split. Decimal numbers (3.14) and ellipsis (...)
        are also handled correctly.

        Args:
            token_stream: Async iterator of string tokens from the LLM.

        Yields:
            Complete sentences as strings.
        """
        # Track when the current buffer accumulation started (reset after
        # each yield/flush). This avoids the stale-time bug where the
        # generator is suspended during TTS processing and `last_yield_time`
        # becomes artificially old, causing premature mid-word flushes.
        buffer_start_time: float | None = None

        async for token in token_stream:
            self._buffer += token
            if buffer_start_time is None:
                buffer_start_time = time.monotonic()

            # Try to extract complete sentences from the buffer
            yielded = False
            while True:
                sentence = self._try_extract()
                if sentence is None:
                    break
                yielded = True
                buffer_start_time = time.monotonic() if self._buffer.strip() else None
                yield sentence

            # Time-based flush: if the buffer has been accumulating for
            # _FLUSH_TIMEOUT_S with enough content but no sentence boundary,
            # flush to TTS to prevent starvation.
            if (
                not yielded
                and buffer_start_time is not None
                and len(self._buffer.strip()) >= _FLUSH_MIN_CHARS
                and (time.monotonic() - buffer_start_time) >= _FLUSH_TIMEOUT_S
            ):
                flushed = self._buffer.strip()
                self._buffer = ""
                buffer_start_time = None
                yield flushed

        # Flush any remaining content at end of stream
        remainder = self._buffer.strip()
        if remainder:
            self._buffer = ""
            yield remainder

    def _try_extract(self) -> str | None:
        """Try to extract one complete sentence from the buffer.

        Returns:
            A complete sentence string, or None if no complete sentence
            is available yet.
        """
        match = _SENTENCE_END_RE.search(self._buffer)
        if match is None:
            return None

        end_pos = match.end()
        candidate = self._buffer[:end_pos].strip()

        # Check for false positives: abbreviations
        if self._is_abbreviation(candidate):
            # Look for the NEXT sentence boundary after this one
            next_match = _SENTENCE_END_RE.search(self._buffer, pos=match.end())
            if next_match is None:
                return None
            end_pos = next_match.end()
            candidate = self._buffer[:end_pos].strip()
            if self._is_abbreviation(candidate):
                return None

        # Check for decimal numbers: digit.digit pattern at the match position
        dot_pos = match.start()
        if (
            match.group(1) == "."
            and dot_pos > 0
            and self._buffer[dot_pos - 1].isdigit()
            and dot_pos + 1 < len(self._buffer)
            and self._buffer[dot_pos + 1].isdigit()
        ):
            return None

        # Check for ellipsis: ... should not split mid-ellipsis
        if match.group(1) == "." and self._buffer[max(0, dot_pos - 2):dot_pos + 1] == "...":
            # Only split if followed by whitespace AND the ellipsis is complete
            # Check if there's more text after the ellipsis + space
            after = self._buffer[end_pos:]
            if not after.strip():
                return None

        self._buffer = self._buffer[end_pos:]
        return candidate

    def _is_abbreviation(self, text: str) -> bool:
        """Check if text ends with a known abbreviation.

        Args:
            text: The candidate sentence text.

        Returns:
            True if the last word is a known abbreviation.
        """
        # Extract the last "word" (sequence ending with a period)
        words = text.split()
        if not words:
            return False
        last_word = words[-1].lower()
        return last_word in _ABBREVIATIONS

    def reset(self) -> None:
        """Clear the internal buffer. Used during interrupt handling."""
        self._buffer = ""
