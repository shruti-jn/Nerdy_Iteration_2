"""
Langfuse LLM observability integration.

Provides a singleton Langfuse client for tracing LLM calls (generations),
turn-level spans, session metadata, and per-turn Socratic quality scores.
Gracefully degrades when Langfuse credentials are not configured — all
callers should check ``get_langfuse()`` for None before creating observations.

Pipeline stage: Infrastructure (observability)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from langfuse import Langfuse

logger = logging.getLogger("tutor")

_client: Optional[Langfuse] = None
_current_trace_id: Optional[str] = None


def init_langfuse(settings) -> None:
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
    return _client


def shutdown_langfuse() -> None:
    global _client
    if _client is not None:
        _client.flush()
        _client.shutdown()
        _client = None
        logger.info("Langfuse shut down")


def _noop(**kwargs: Any) -> None:
    """No-op finisher used when Langfuse is disabled."""


def trace_span(
    name: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable[..., None]:
    """Start a Langfuse span. Returns a finish callable.
    Call finish(metadata={...}) to attach final metadata before closing."""
    global _current_trace_id
    lf = _client
    if lf is None:
        return _noop

    cm = lf.start_as_current_observation(name=name, metadata=metadata)
    cm.__enter__()
    trace_id = getattr(cm, "trace_id", None)
    _current_trace_id = trace_id

    def finish(**kwargs: Any) -> None:
        global _current_trace_id
        if kwargs.get("metadata"):
            try:
                lf.update_current_observation(metadata=kwargs["metadata"])
            except Exception:
                pass
        cm.__exit__(None, None, None)
        _current_trace_id = None

    return finish


def get_current_trace_id() -> Optional[str]:
    return _current_trace_id


def trace_generation(
    name: str,
    *,
    model: str,
    input: Any = None,
    model_parameters: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable[..., None]:
    """Start a Langfuse generation observation. Returns a finish callable."""
    lf = _client
    if lf is None:
        return _noop
    cm = lf.start_as_current_observation(
        name=name, as_type="generation", model=model,
        input=input, model_parameters=model_parameters, metadata=metadata,
    )
    cm.__enter__()

    def finish(**kwargs: Any) -> None:
        if kwargs:
            lf.update_current_generation(**kwargs)
        cm.__exit__(None, None, None)

    return finish


def score_turn(scores: Dict[str, float | int]) -> None:
    """Attach Socratic quality scores to the current Langfuse trace.
    No-op if Langfuse is not configured or no trace is active."""
    lf = _client
    trace_id = _current_trace_id
    if lf is None or trace_id is None:
        return
    for name, value in scores.items():
        try:
            lf.score(trace_id=trace_id, name=name, value=float(value))
        except Exception as exc:
            logger.warning("langfuse_score_failed name=%s error=%s", name, exc)
