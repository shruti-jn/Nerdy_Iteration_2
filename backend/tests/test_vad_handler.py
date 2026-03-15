"""
Tests for the VAD Handler & Interrupt State Machine.

TDD: These tests were written BEFORE the implementation.

Covers:
  - Valid state transitions (IDLE → LISTENING → PROCESSING → SPEAKING)
  - Invalid state transitions (raises ValueError)
  - Interrupt behaviour (cancel callbacks, timeout, flag management)

Pipeline stage: VAD / Interruption (Task 1G)
"""

from __future__ import annotations

import asyncio

import pytest

from pipeline.errors import InterruptError


# ── Valid Transitions ─────────────────────────────────────────────────────


class TestValidTransitions:
    """State machine must allow only the correct transition paths."""

    def test_initial_state_is_idle(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        assert handler.state == "idle"

    def test_idle_to_listening(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        assert handler.state == "listening"

    def test_listening_to_processing(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        assert handler.state == "processing"

    def test_processing_to_speaking(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        assert handler.state == "speaking"

    @pytest.mark.asyncio
    async def test_speaking_to_listening_via_interrupt(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()
        assert handler.state == "listening"

    def test_speaking_to_idle_via_finish(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        handler.finish_speaking()
        assert handler.state == "idle"


# ── Invalid Transitions ──────────────────────────────────────────────────


class TestInvalidTransitions:
    """Invalid state transitions must raise ValueError."""

    def test_idle_to_speaking_raises(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        with pytest.raises(ValueError, match="idle.*speaking"):
            handler.start_speaking()

    def test_idle_to_processing_raises(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        with pytest.raises(ValueError, match="idle.*processing"):
            handler.start_processing()

    def test_listening_to_speaking_raises(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        with pytest.raises(ValueError, match="listening.*speaking"):
            handler.start_speaking()

    def test_processing_to_listening_raises(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        with pytest.raises(ValueError, match="processing.*listening"):
            handler.start_listening()

    def test_idle_finish_speaking_raises(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        with pytest.raises(ValueError, match="idle.*idle"):
            handler.finish_speaking()

    def test_listening_cancel_returns_to_idle(self):
        """cancel_listening() transitions from LISTENING back to IDLE."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.cancel_listening()
        assert handler.state == "idle"

    def test_cancel_listening_from_idle_raises(self):
        """cancel_listening() from IDLE is invalid."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        with pytest.raises(ValueError, match="idle.*idle"):
            handler.cancel_listening()


# ── Interrupt Behaviour ──────────────────────────────────────────────────


class TestInterruptBehaviour:
    """Interrupt must call cancel callbacks and manage the interrupted flag."""

    @pytest.mark.asyncio
    async def test_interrupt_calls_cancel_callbacks(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        called = {"llm": False, "tts": False, "avatar": False}

        async def cancel_llm():
            called["llm"] = True

        async def cancel_tts():
            called["tts"] = True

        async def cancel_avatar():
            called["avatar"] = True

        handler.register_cancel_callback("llm", cancel_llm)
        handler.register_cancel_callback("tts", cancel_tts)
        handler.register_cancel_callback("avatar", cancel_avatar)

        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()

        assert called["llm"] is True
        assert called["tts"] is True
        assert called["avatar"] is True

    @pytest.mark.asyncio
    async def test_interrupt_timeout_raises(self):
        """Cancel callbacks exceeding 200ms total should raise InterruptError."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()

        async def slow_cancel():
            await asyncio.sleep(0.3)  # 300ms > 200ms budget

        handler.register_cancel_callback("slow", slow_cancel)

        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()

        with pytest.raises(InterruptError):
            await handler.interrupt()

    @pytest.mark.asyncio
    async def test_interrupt_from_non_speaking_is_noop(self):
        """Interrupt from LISTENING should be a no-op (no error, state unchanged)."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        await handler.interrupt()
        assert handler.state == "listening"

    @pytest.mark.asyncio
    async def test_interrupt_from_idle_is_noop(self):
        """Interrupt from IDLE should be a no-op."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        await handler.interrupt()
        assert handler.state == "idle"

    @pytest.mark.asyncio
    async def test_interrupt_from_processing_is_noop(self):
        """Interrupt from PROCESSING should be a no-op."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        await handler.interrupt()
        assert handler.state == "processing"

    @pytest.mark.asyncio
    async def test_interrupt_sets_interrupted_flag(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        assert handler.is_interrupted is False

        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()

        assert handler.is_interrupted is True

    @pytest.mark.asyncio
    async def test_interrupted_flag_resets_on_next_turn(self):
        """The is_interrupted flag should reset when a new processing turn starts."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()
        assert handler.is_interrupted is True

        # New turn cycle
        handler.start_processing()
        assert handler.is_interrupted is False

    @pytest.mark.asyncio
    async def test_interrupt_with_no_callbacks(self):
        """Interrupt with no registered callbacks should still work."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()
        assert handler.state == "listening"

    @pytest.mark.asyncio
    async def test_fast_callbacks_complete_within_budget(self):
        """Fast cancel callbacks should complete without raising InterruptError."""
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()

        async def fast_cancel():
            await asyncio.sleep(0.01)  # 10ms — well within budget

        handler.register_cancel_callback("fast", fast_cancel)

        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()  # Should not raise
        assert handler.state == "listening"


# ── Full Turn Cycle ──────────────────────────────────────────────────────


class TestFullTurnCycle:
    """Test complete turn cycles through the state machine."""

    def test_complete_normal_turn(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        handler.finish_speaking()
        assert handler.state == "idle"

    def test_multiple_turns(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()
        for _ in range(3):
            handler.start_listening()
            handler.start_processing()
            handler.start_speaking()
            handler.finish_speaking()
        assert handler.state == "idle"

    @pytest.mark.asyncio
    async def test_interrupted_then_normal_turn(self):
        from pipeline.vad_handler import VADHandler

        handler = VADHandler()

        # First turn: interrupted
        handler.start_listening()
        handler.start_processing()
        handler.start_speaking()
        await handler.interrupt()
        assert handler.state == "listening"

        # Second turn: normal completion
        handler.start_processing()
        handler.start_speaking()
        handler.finish_speaking()
        assert handler.state == "idle"
