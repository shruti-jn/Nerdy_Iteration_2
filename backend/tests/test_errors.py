"""
Tests for the pipeline error hierarchy.

Validates that all custom exception classes carry the right attributes,
format messages correctly, produce useful __repr__ output, and maintain
proper inheritance relationships. Written TDD-first before the
implementation in pipeline/errors.py.

Pipeline stage: Infrastructure (shared by all stages)
"""

import pytest

from pipeline.errors import (
    TutorError,
    AdapterError,
    AdapterTimeoutError,
    PipelineError,
    SessionError,
    InterruptError,
)


# ---------------------------------------------------------------------------
# TutorError (base)
# ---------------------------------------------------------------------------

class TestTutorError:
    """Tests for the base TutorError exception."""

    def test_instantiation_with_message_only(self):
        err = TutorError("something broke")
        assert str(err) == "something broke"
        assert err.message == "something broke"
        assert err.context is None

    def test_instantiation_with_context(self):
        ctx = {"session_id": "abc-123", "attempt": 2}
        err = TutorError("boom", context=ctx)
        assert err.message == "boom"
        assert err.context == ctx
        assert err.context["session_id"] == "abc-123"

    def test_is_exception(self):
        assert issubclass(TutorError, Exception)

    def test_repr_contains_message(self):
        err = TutorError("test msg")
        r = repr(err)
        assert "TutorError" in r
        assert "test msg" in r

    def test_repr_contains_context_when_present(self):
        err = TutorError("test", context={"key": "val"})
        r = repr(err)
        assert "key" in r
        assert "val" in r

    def test_repr_with_none_context(self):
        err = TutorError("no ctx")
        r = repr(err)
        assert "TutorError" in r
        # Should still be valid repr even without context
        assert "no ctx" in r


# ---------------------------------------------------------------------------
# AdapterError
# ---------------------------------------------------------------------------

class TestAdapterError:
    """Tests for AdapterError — external service failures."""

    def test_instantiation(self):
        cause = ConnectionError("connection refused")
        err = AdapterError(
            stage="stt",
            provider="deepgram",
            cause=cause,
        )
        assert err.stage == "stt"
        assert err.provider == "deepgram"
        assert err.cause is cause

    def test_message_format(self):
        cause = ValueError("bad audio format")
        err = AdapterError(stage="tts", provider="cartesia", cause=cause)
        expected = "[tts/cartesia] ValueError: bad audio format"
        assert err.message == expected
        assert str(err) == expected

    def test_subclass_of_tutor_error(self):
        assert issubclass(AdapterError, TutorError)

    def test_context_preserved(self):
        cause = RuntimeError("fail")
        ctx = {"request_id": "r-42"}
        err = AdapterError(
            stage="llm", provider="groq", cause=cause, context=ctx
        )
        assert err.context == ctx

    def test_repr_includes_stage_and_provider(self):
        cause = OSError("dns fail")
        err = AdapterError(stage="avatar", provider="simli", cause=cause)
        r = repr(err)
        assert "avatar" in r
        assert "simli" in r
        assert "AdapterError" in r

    def test_all_valid_stages(self):
        """All four pipeline stages should be accepted."""
        cause = RuntimeError("x")
        for stage in ("stt", "llm", "tts", "avatar"):
            err = AdapterError(stage=stage, provider="deepgram", cause=cause)
            assert err.stage == stage

    def test_all_valid_providers(self):
        """All four providers should be accepted."""
        cause = RuntimeError("x")
        for provider in ("deepgram", "groq", "cartesia", "simli"):
            err = AdapterError(stage="stt", provider=provider, cause=cause)
            assert err.provider == provider

    def test_cause_accessible_via_dunder_cause(self):
        """The original exception should be retrievable."""
        cause = IOError("stream closed")
        err = AdapterError(stage="stt", provider="deepgram", cause=cause)
        assert err.cause is cause


# ---------------------------------------------------------------------------
# AdapterTimeoutError
# ---------------------------------------------------------------------------

class TestAdapterTimeoutError:
    """Tests for AdapterTimeoutError — latency budget exceeded."""

    def test_instantiation(self):
        err = AdapterTimeoutError(
            stage="stt",
            provider="deepgram",
            budget_ms=300.0,
            actual_ms=452.1,
        )
        assert err.stage == "stt"
        assert err.provider == "deepgram"
        assert err.budget_ms == 300.0
        assert err.actual_ms == 452.1

    def test_cause_is_timeout_error(self):
        err = AdapterTimeoutError(
            stage="llm", provider="groq",
            budget_ms=400.0, actual_ms=612.0,
        )
        assert isinstance(err.cause, TimeoutError)

    def test_cause_message_contains_budget_and_actual(self):
        err = AdapterTimeoutError(
            stage="tts", provider="cartesia",
            budget_ms=300.0, actual_ms=500.0,
        )
        cause_msg = str(err.cause)
        assert "300" in cause_msg
        assert "500" in cause_msg

    def test_subclass_of_adapter_error(self):
        assert issubclass(AdapterTimeoutError, AdapterError)

    def test_subclass_of_tutor_error(self):
        assert issubclass(AdapterTimeoutError, TutorError)

    def test_message_includes_timeout_info(self):
        err = AdapterTimeoutError(
            stage="avatar", provider="simli",
            budget_ms=200.0, actual_ms=350.0,
        )
        msg = str(err)
        assert "avatar" in msg
        assert "simli" in msg
        assert "TimeoutError" in msg

    def test_repr_includes_budget_and_actual(self):
        err = AdapterTimeoutError(
            stage="stt", provider="deepgram",
            budget_ms=150.0, actual_ms=280.0,
        )
        r = repr(err)
        assert "150" in r
        assert "280" in r

    def test_context_preserved(self):
        ctx = {"session_id": "s-1"}
        err = AdapterTimeoutError(
            stage="stt", provider="deepgram",
            budget_ms=300.0, actual_ms=400.0,
            context=ctx,
        )
        assert err.context == ctx


# ---------------------------------------------------------------------------
# PipelineError
# ---------------------------------------------------------------------------

class TestPipelineError:
    """Tests for PipelineError — orchestration-level failure."""

    def test_instantiation(self):
        err = PipelineError("pipeline failed")
        assert err.message == "pipeline failed"
        assert err.stage_errors == []

    def test_stores_adapter_errors(self):
        cause1 = RuntimeError("fail1")
        cause2 = RuntimeError("fail2")
        ae1 = AdapterError(stage="stt", provider="deepgram", cause=cause1)
        ae2 = AdapterError(stage="tts", provider="cartesia", cause=cause2)
        err = PipelineError("multi-failure", stage_errors=[ae1, ae2])
        assert len(err.stage_errors) == 2
        assert err.stage_errors[0] is ae1
        assert err.stage_errors[1] is ae2

    def test_subclass_of_tutor_error(self):
        assert issubclass(PipelineError, TutorError)

    def test_repr_includes_stage_errors_count(self):
        ae = AdapterError(
            stage="llm", provider="groq", cause=RuntimeError("x")
        )
        err = PipelineError("orchestration fail", stage_errors=[ae])
        r = repr(err)
        assert "PipelineError" in r
        assert "orchestration fail" in r

    def test_context_preserved(self):
        ctx = {"pipeline_run": "run-7"}
        err = PipelineError("fail", context=ctx)
        assert err.context == ctx


# ---------------------------------------------------------------------------
# SessionError
# ---------------------------------------------------------------------------

class TestSessionError:
    """Tests for SessionError — session management failures."""

    def test_instantiation(self):
        err = SessionError("token limit exceeded")
        assert err.message == "token limit exceeded"

    def test_subclass_of_tutor_error(self):
        assert issubclass(SessionError, TutorError)

    def test_context_preserved(self):
        ctx = {"session_id": "s-99", "tokens_used": 4096}
        err = SessionError("token limit", context=ctx)
        assert err.context["tokens_used"] == 4096

    def test_repr_contains_class_and_message(self):
        err = SessionError("compression failed")
        r = repr(err)
        assert "SessionError" in r
        assert "compression failed" in r


# ---------------------------------------------------------------------------
# InterruptError
# ---------------------------------------------------------------------------

class TestInterruptError:
    """Tests for InterruptError — incomplete interrupt handling."""

    def test_instantiation(self):
        err = InterruptError("interrupt cleanup failed")
        assert err.message == "interrupt cleanup failed"

    def test_subclass_of_tutor_error(self):
        assert issubclass(InterruptError, TutorError)

    def test_context_preserved(self):
        ctx = {"pending_chunks": 3}
        err = InterruptError("stale chunks", context=ctx)
        assert err.context["pending_chunks"] == 3

    def test_repr_contains_class_and_message(self):
        err = InterruptError("cancel incomplete")
        r = repr(err)
        assert "InterruptError" in r
        assert "cancel incomplete" in r


# ---------------------------------------------------------------------------
# Cross-cutting: inheritance chain
# ---------------------------------------------------------------------------

class TestInheritanceChain:
    """Verify the full inheritance hierarchy is correct."""

    def test_all_errors_are_tutor_errors(self):
        classes = [
            AdapterError, AdapterTimeoutError,
            PipelineError, SessionError, InterruptError,
        ]
        for cls in classes:
            assert issubclass(cls, TutorError), f"{cls.__name__} not subclass of TutorError"

    def test_all_errors_are_exceptions(self):
        classes = [
            TutorError, AdapterError, AdapterTimeoutError,
            PipelineError, SessionError, InterruptError,
        ]
        for cls in classes:
            assert issubclass(cls, Exception), f"{cls.__name__} not subclass of Exception"

    def test_adapter_timeout_is_adapter_error(self):
        assert issubclass(AdapterTimeoutError, AdapterError)

    def test_catching_tutor_error_catches_all(self):
        """A bare except TutorError should catch every custom error."""
        cause = RuntimeError("inner")
        errors = [
            TutorError("base"),
            AdapterError(stage="stt", provider="deepgram", cause=cause),
            AdapterTimeoutError(
                stage="stt", provider="deepgram",
                budget_ms=100, actual_ms=200,
            ),
            PipelineError("orchestration"),
            SessionError("session"),
            InterruptError("interrupt"),
        ]
        for err in errors:
            with pytest.raises(TutorError):
                raise err
