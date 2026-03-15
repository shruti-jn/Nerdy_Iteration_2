"""
Langfuse LLM observability integration.

Provides a singleton Langfuse client for tracing LLM calls (generations),
turn-level spans, and session metadata. Gracefully degrades when Langfuse
credentials are not configured — all callers should check ``get_langfuse()``
for None before creating observations.

Pipeline stage: Infrastructure (observability)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from langfuse import Langfuse

logger = logging.getLogger("tutor")

_client: Optional[Langfuse] = None


def init_langfuse(settings) -> None:
    """Initialize the Langfuse client from application settings.

    No-op if ``LANGFUSE_PUBLIC_KEY`` or ``LANGFUSE_SECRET_KEY`` are empty.
    Safe to call multiple times — subsequent calls are ignored.
    """
    global _client
    if _client is not None:
        return

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.info("Langfuse credentials not configured — LLM tracing disabled")
        return

    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    logger.info("Langfuse initialized (host=%s)", settings.langfuse_host)


def get_langfuse() -> Optional[Langfuse]:
    """Return the singleton Langfuse client, or None if not configured."""
    return _client


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    global _client
    if _client is not None:
        _client.flush()
        _client.shutdown()
        _client = None
        logger.info("Langfuse shut down")


# ── Helpers for non-context-manager tracing ──────────────────────────────


def _noop(**kwargs: Any) -> None:
    """No-op finisher used when Langfuse is disabled."""


def trace_span(
    name: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable[..., None]:
    """Start a Langfuse span observation. Returns a ``finish`` callable.

    Call ``finish()`` when the span is complete. If Langfuse is not
    configured, returns a no-op callable so callers don't need to
    check for None.

    Example::

        finish = trace_span("turn-3", metadata={"session_id": "abc"})
        # ... do work ...
        finish()
    """
    lf = _client
    if lf is None:
        return _noop

    cm = lf.start_as_current_observation(name=name, metadata=metadata)
    cm.__enter__()

    def finish(**kwargs: Any) -> None:
        cm.__exit__(None, None, None)

    return finish


def trace_generation(
    name: str,
    *,
    model: str,
    input: Any = None,
    model_parameters: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable[..., None]:
    """Start a Langfuse generation observation. Returns a ``finish`` callable.

    Call ``finish(output=..., usage_details=...)`` when the generation
    is complete. Passes kwargs through to ``update_current_generation()``.

    Example::

        finish = trace_generation("llm_stream", model="llama-3.3-70b")
        # ... stream tokens ...
        finish(output="Hello! What do you know about photosynthesis?")
    """
    lf = _client
    if lf is None:
        return _noop

    cm = lf.start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        input=input,
        model_parameters=model_parameters,
        metadata=metadata,
    )
    cm.__enter__()

    def finish(**kwargs: Any) -> None:
        if kwargs:
            lf.update_current_generation(**kwargs)
        cm.__exit__(None, None, None)

    return finish
