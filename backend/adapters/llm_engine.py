"""
Groq LLM engine using Llama 3.3 70B Versatile for Socratic tutoring.

Implements the BaseLLMEngine ABC with streaming token generation via the
Groq Python SDK. Records time-to-first-token (TTFT) through the
MetricsCollector and wraps all Groq SDK exceptions into AdapterError.

Supports cooperative cancellation via asyncio.Event for interrupt handling.

Pipeline stage: LLM (Stage 2 of STT → LLM → TTS → Avatar)

Exports:
    GroqLLMEngine -- Concrete LLM engine backed by Groq
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from groq import AsyncGroq

from adapters.base import BaseLLMEngine
from observability.langfuse_setup import get_langfuse
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector


class GroqLLMEngine(BaseLLMEngine):
    """Groq-backed LLM engine for streaming Socratic tutor responses.

    Uses ``llama-3.3-70b-versatile`` by default for tutoring, with the
    Groq Python SDK's async streaming API.

    Args:
        settings: Application settings object with ``groq_api_key``.
    """

    def __init__(self, settings) -> None:
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._cancel_event = asyncio.Event()
        self._default_model = getattr(settings, "llm_model", "llama-3.3-70b-versatile")
        self._max_tokens = getattr(settings, "llm_max_tokens", 150)
        self._last_usage: dict | None = None

    @property
    def last_usage(self) -> dict | None:
        """Token usage from the most recent stream() call.
        Keys: prompt_tokens, completion_tokens, total_tokens.
        None if usage was not returned (e.g. cancelled before completion)."""
        return self._last_usage

    async def stream(
        self,
        transcript: str,
        context: list[dict],
        metrics: MetricsCollector,
    ) -> AsyncIterator[str]:
        """Stream LLM response tokens for a student utterance.

        Builds a message list from conversation context plus the new
        student transcript, then streams tokens from Groq. Records TTFT
        via ``metrics.mark_first("llm")`` on the first non-None content
        chunk.

        Args:
            transcript: The student's transcribed utterance.
            context:    Conversation history as message dicts.
            metrics:    MetricsCollector for recording TTFT and duration.

        Yields:
            Individual response tokens as strings.

        Raises:
            AdapterError: Wraps any Groq SDK exception.
        """
        self._cancel_event.clear()
        self._last_usage = None
        messages = list(context) + [{"role": "user", "content": transcript}]

        try:
            metrics.start("llm")
            stream = await self._client.chat.completions.create(
                model=self._default_model,
                messages=messages,
                stream=True,
                max_tokens=self._max_tokens,
                temperature=0.7,
            )

            first_token = True
            async for chunk in stream:
                if self._cancel_event.is_set():
                    break

                # Capture usage if the SDK populates it on a final chunk
                if getattr(chunk, "usage", None) is not None:
                    self._last_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                content = chunk.choices[0].delta.content if chunk.choices else None
                if content is None:
                    continue

                if first_token:
                    metrics.mark_first("llm")
                    first_token = False

                yield content

            metrics.end("llm")

        except Exception as exc:
            metrics.end("llm")
            raise AdapterError(
                stage="llm",
                provider="groq",
                cause=exc,
            ) from exc

    async def quick_call(self, prompt: str, model: str) -> str:
        """Make a non-streaming single-turn LLM call.

        Args:
            prompt: The complete prompt.
            model:  Model identifier (e.g. "llama-3.1-8b-instant").

        Returns:
            The full model response as a string.

        Raises:
            AdapterError: Wraps any Groq SDK exception.
        """
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            result = response.choices[0].message.content or ""

            # Trace the generation in Langfuse (inherits parent span if active)
            lf = get_langfuse()
            if lf:
                usage = getattr(response, "usage", None)
                with lf.start_as_current_observation(
                    name="llm_quick_call",
                    as_type="generation",
                    model=model,
                    input=[{"role": "user", "content": prompt}],
                    output=result,
                    usage_details={
                        "input": getattr(usage, "prompt_tokens", 0),
                        "output": getattr(usage, "completion_tokens", 0),
                    } if usage else None,
                ):
                    pass  # observation auto-ends on exit

            return result
        except Exception as exc:
            raise AdapterError(
                stage="llm",
                provider="groq",
                cause=exc,
            ) from exc

    async def cancel(self) -> None:
        """Signal the streaming loop to stop on the next iteration."""
        self._cancel_event.set()
