"""
Logfire configuration and span helpers for pipeline tracing.
Pipeline stage: Infrastructure (observability)

Provides setup_logfire() to configure Pydantic Logfire with auto-instrumentation
for FastAPI, and create_span() to wrap logfire.span() with standard pipeline
attributes (stage, provider, run_id).

Key exports:
    - setup_logfire(app): one-call init for Logfire + FastAPI instrumentation
    - create_span(name, attributes): context-manager factory with standard attrs
"""

from __future__ import annotations

from typing import Any, Dict

import logfire
from logfire import LogfireSpan


def setup_logfire(app: Any) -> None:
    """Configure Logfire and instrument a FastAPI application.

    Reads the LOGFIRE_TOKEN from the environment (via logfire.configure()
    defaults) and attaches OpenTelemetry auto-instrumentation to the given
    FastAPI app so that every request is traced automatically.

    Args:
        app: A FastAPI application instance to instrument.

    Side effects:
        - Calls logfire.configure() which reads LOGFIRE_TOKEN from env.
        - Calls logfire.instrument_fastapi(app) for automatic span creation
          on every HTTP request.
    """
    logfire.configure()
    logfire.instrument_fastapi(app)


def create_span(name: str, attributes: Dict[str, Any]) -> LogfireSpan:
    """Create a Logfire span with standard pipeline attributes.

    Wraps logfire.span() and unpacks the provided attributes dict as keyword
    arguments.  Typical attributes include:
        - stage: pipeline stage name (e.g. "stt", "llm", "tts", "avatar")
        - provider: service provider (e.g. "deepgram", "groq", "cartesia")
        - run_id: unique identifier for the current pipeline run

    Args:
        name: Human-readable span name (e.g. "stt_transcribe").
        attributes: Dict of key-value pairs to attach to the span.  Keys must
            not start with an underscore (Logfire restriction).

    Returns:
        A LogfireSpan context manager.  Use with a ``with`` statement::

            with create_span("stt_transcribe", {"stage": "stt", "provider": "deepgram", "run_id": rid}):
                # ... do work inside the span
    """
    return logfire.span(name, **attributes)
