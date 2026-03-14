"""
Tests for the GroqLLMEngine.

Unit tests mock the Groq SDK to validate token streaming, TTFT recording,
None-content skipping, error wrapping, and cooperative cancellation.
One integration test makes a real Groq API call (requires GROQ_API_KEY).

Pipeline stage: LLM (Stage 2)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.llm_engine import GroqLLMEngine
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Helpers — mock Groq SDK response objects
# ---------------------------------------------------------------------------

@dataclass
class _MockDelta:
    content: str | None = None

@dataclass
class _MockChoice:
    delta: _MockDelta = None

    def __post_init__(self):
        if self.delta is None:
            self.delta = _MockDelta()

@dataclass
class _MockChunk:
    choices: list = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = [_MockChoice()]


async def _mock_stream(*contents):
    """Create an async iterable of mock chunks with given content values."""
    for content in contents:
        chunk = _MockChunk()
        chunk.choices[0].delta.content = content
        yield chunk


@dataclass
class _FakeSettings:
    groq_api_key: str = "test-groq-key"


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------

class TestGroqLLMEngineStream:
    """Tests for the streaming LLM generation."""

    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        """stream() yields all non-None content tokens."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        mock_create = AsyncMock(return_value=_mock_stream("Hello", " world", "!"))
        engine._client.chat.completions.create = mock_create

        tokens = []
        async for token in engine.stream("hi", [], mc):
            tokens.append(token)

        assert tokens == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_records_ttft(self):
        """stream() records TTFT via metrics.mark_first('llm')."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        mock_create = AsyncMock(return_value=_mock_stream("Hello"))
        engine._client.chat.completions.create = mock_create

        async for _ in engine.stream("hi", [], mc):
            pass

        stage = mc.get_stage("llm")
        assert stage is not None
        assert stage.time_to_first_ms is not None

    @pytest.mark.asyncio
    async def test_records_duration(self):
        """stream() records total duration via metrics.end('llm')."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        mock_create = AsyncMock(return_value=_mock_stream("A", "B"))
        engine._client.chat.completions.create = mock_create

        async for _ in engine.stream("hi", [], mc):
            pass

        stage = mc.get_stage("llm")
        assert stage is not None
        assert stage.duration_ms is not None

    @pytest.mark.asyncio
    async def test_skips_none_content(self):
        """stream() skips chunks where content is None."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        mock_create = AsyncMock(return_value=_mock_stream(None, "Hello", None, "!"))
        engine._client.chat.completions.create = mock_create

        tokens = []
        async for token in engine.stream("hi", [], mc):
            tokens.append(token)

        assert tokens == ["Hello", "!"]

    @pytest.mark.asyncio
    async def test_wraps_connection_error(self):
        """stream() wraps SDK connection errors into AdapterError."""
        from groq import APIConnectionError

        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        engine._client.chat.completions.create = AsyncMock(
            side_effect=APIConnectionError(request=MagicMock())
        )

        with pytest.raises(AdapterError) as exc_info:
            async for _ in engine.stream("hi", [], mc):
                pass

        assert exc_info.value.stage == "llm"
        assert exc_info.value.provider == "groq"

    @pytest.mark.asyncio
    async def test_wraps_rate_limit_error(self):
        """stream() wraps SDK rate-limit errors into AdapterError."""
        from groq import RateLimitError

        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        engine._client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="rate limited",
                response=mock_response,
                body=None,
            )
        )

        with pytest.raises(AdapterError) as exc_info:
            async for _ in engine.stream("hi", [], mc):
                pass

        assert exc_info.value.stage == "llm"

    @pytest.mark.asyncio
    async def test_cancel_stops_iteration(self):
        """cancel() causes stream() to stop yielding."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()

        async def _slow_stream():
            for content in ["A", "B", "C", "D", "E"]:
                chunk = _MockChunk()
                chunk.choices[0].delta.content = content
                yield chunk
                await asyncio.sleep(0.01)

        engine._client.chat.completions.create = AsyncMock(return_value=_slow_stream())

        tokens = []
        async for token in engine.stream("hi", [], mc):
            tokens.append(token)
            if len(tokens) == 2:
                await engine.cancel()

        # Should have stopped early (got at most 2-3 tokens)
        assert len(tokens) <= 3

    @pytest.mark.asyncio
    async def test_context_passed_to_messages(self):
        """stream() prepends context to the messages list."""
        engine = GroqLLMEngine(_FakeSettings())
        mc = MetricsCollector()
        context = [{"role": "system", "content": "You are a tutor."}]

        mock_create = AsyncMock(return_value=_mock_stream("Hi"))
        engine._client.chat.completions.create = mock_create

        async for _ in engine.stream("hello", context, mc):
            pass

        call_args = mock_create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "You are a tutor."}
        assert messages[1] == {"role": "user", "content": "hello"}


class TestGroqLLMEngineQuickCall:
    """Tests for the non-streaming quick_call method."""

    @pytest.mark.asyncio
    async def test_returns_response_content(self):
        """quick_call() returns the model's response content."""
        engine = GroqLLMEngine(_FakeSettings())

        mock_msg = MagicMock()
        mock_msg.content = "Classification: biology"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        engine._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await engine.quick_call("classify this", "llama-3.1-8b-instant")
        assert result == "Classification: biology"

    @pytest.mark.asyncio
    async def test_wraps_error(self):
        """quick_call() wraps SDK errors into AdapterError."""
        engine = GroqLLMEngine(_FakeSettings())
        engine._client.chat.completions.create = AsyncMock(
            side_effect=Exception("network error")
        )

        with pytest.raises(AdapterError):
            await engine.quick_call("test", "llama-3.1-8b-instant")


# ---------------------------------------------------------------------------
# Integration test (requires GROQ_API_KEY in env)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_groq_real_streaming():
    """Integration: stream a real response from Groq API.

    Requires GROQ_API_KEY in the environment. Validates that real tokens
    are yielded and TTFT is recorded.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY not set")

    @dataclass
    class _RealSettings:
        groq_api_key: str = api_key

    engine = GroqLLMEngine(_RealSettings())
    mc = MetricsCollector()

    tokens = []
    async for token in engine.stream(
        "Say exactly: hello world",
        [{"role": "system", "content": "You are a helpful assistant. Be brief."}],
        mc,
    ):
        tokens.append(token)
        if len(tokens) > 20:
            break  # Don't consume too much

    assert len(tokens) > 0
    stage = mc.get_stage("llm")
    assert stage is not None
    assert stage.time_to_first_ms is not None
