"""
Tests for the SentenceBuffer.

Validates sentence boundary detection including period/question/exclamation
splits, abbreviation handling, decimal numbers, ellipsis, empty streams,
and remainder flushing.

Pipeline stage: Orchestration (between LLM and TTS)
"""

import pytest

from pipeline.sentence_buffer import SentenceBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _tokens(*parts: str):
    """Yield string parts as an async iterator (simulates LLM token stream)."""
    for p in parts:
        yield p


async def _collect(buf: SentenceBuffer, token_stream) -> list[str]:
    """Collect all sentences from the buffer into a list."""
    result = []
    async for sentence in buf.process(token_stream):
        result.append(sentence)
    return result


# ---------------------------------------------------------------------------
# Basic sentence splitting
# ---------------------------------------------------------------------------

class TestBasicSplitting:
    """Tests for basic sentence boundary detection."""

    @pytest.mark.asyncio
    async def test_period_split(self):
        """Splits on period followed by space."""
        buf = SentenceBuffer()
        tokens = _tokens("Hello world. ", "How are you?")
        result = await _collect(buf, tokens)
        assert result == ["Hello world.", "How are you?"]

    @pytest.mark.asyncio
    async def test_question_mark_split(self):
        """Splits on question mark followed by space."""
        buf = SentenceBuffer()
        tokens = _tokens("What is this? ", "Tell me more.")
        result = await _collect(buf, tokens)
        assert result == ["What is this?", "Tell me more."]

    @pytest.mark.asyncio
    async def test_exclamation_split(self):
        """Splits on exclamation mark followed by space."""
        buf = SentenceBuffer()
        tokens = _tokens("Great job! ", "Keep going.")
        result = await _collect(buf, tokens)
        assert result == ["Great job!", "Keep going."]

    @pytest.mark.asyncio
    async def test_multiple_sentences(self):
        """Handles three sentences in one stream."""
        buf = SentenceBuffer()
        tokens = _tokens("One. ", "Two. ", "Three.")
        result = await _collect(buf, tokens)
        assert result == ["One.", "Two.", "Three."]

    @pytest.mark.asyncio
    async def test_token_by_token(self):
        """Works when tokens arrive character by character."""
        buf = SentenceBuffer()
        tokens = _tokens("H", "i", ".", " ", "B", "y", "e", ".")
        result = await _collect(buf, tokens)
        assert result == ["Hi.", "Bye."]


# ---------------------------------------------------------------------------
# Remainder flushing
# ---------------------------------------------------------------------------

class TestFlushRemainder:
    """Tests for flushing incomplete content at end of stream."""

    @pytest.mark.asyncio
    async def test_flush_remainder(self):
        """Flushes remaining text when stream ends without terminal punctuation."""
        buf = SentenceBuffer()
        tokens = _tokens("Hello world. ", "This is incomplete")
        result = await _collect(buf, tokens)
        assert result == ["Hello world.", "This is incomplete"]

    @pytest.mark.asyncio
    async def test_single_sentence_no_punctuation(self):
        """A single sentence without ending punctuation is flushed."""
        buf = SentenceBuffer()
        tokens = _tokens("Just some text")
        result = await _collect(buf, tokens)
        assert result == ["Just some text"]


# ---------------------------------------------------------------------------
# Empty and edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        """Empty token stream yields no sentences."""
        buf = SentenceBuffer()
        tokens = _tokens()
        result = await _collect(buf, tokens)
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        """Whitespace-only tokens yield no sentences."""
        buf = SentenceBuffer()
        tokens = _tokens("  ", "  ", "  ")
        result = await _collect(buf, tokens)
        assert result == []

    @pytest.mark.asyncio
    async def test_reset_clears_buffer(self):
        """reset() clears internal state."""
        buf = SentenceBuffer()
        buf._buffer = "partial content"
        buf.reset()
        assert buf._buffer == ""


# ---------------------------------------------------------------------------
# Abbreviation handling
# ---------------------------------------------------------------------------

class TestAbbreviations:
    """Tests for abbreviation handling — should NOT split."""

    @pytest.mark.asyncio
    async def test_dr_abbreviation(self):
        """'Dr.' does not trigger a sentence split."""
        buf = SentenceBuffer()
        tokens = _tokens("Dr. Smith is here. ", "Welcome.")
        result = await _collect(buf, tokens)
        assert result[0] == "Dr. Smith is here."

    @pytest.mark.asyncio
    async def test_us_abbreviation(self):
        """'U.S.' does not trigger a sentence split."""
        buf = SentenceBuffer()
        tokens = _tokens("The U.S. is large. ", "Indeed.")
        result = await _collect(buf, tokens)
        assert result[0] == "The U.S. is large."

    @pytest.mark.asyncio
    async def test_eg_abbreviation(self):
        """'e.g.' does not trigger a sentence split."""
        buf = SentenceBuffer()
        tokens = _tokens("Use colors e.g. red or blue. ", "Got it?")
        result = await _collect(buf, tokens)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Decimal handling
# ---------------------------------------------------------------------------

class TestDecimals:
    """Tests for decimal number handling — should NOT split on the dot."""

    @pytest.mark.asyncio
    async def test_decimal_number(self):
        """'3.14' does not trigger a sentence split."""
        buf = SentenceBuffer()
        tokens = _tokens("Pi is 3.14 approximately. ", "Cool?")
        result = await _collect(buf, tokens)
        assert "3.14" in result[0]
        assert len(result) == 2
