"""
Tests for the Session Manager & Token Economy.

TDD: These tests were written BEFORE the implementation.

Covers:
  - Basic operations (append turn, get context)
  - Token economy (compression triggers, summary, pruning, bounded tokens)
  - Interrupted turns
  - Error handling (compression failure degrades gracefully)

Pipeline stage: Session Management (Task 1H)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.errors import SessionError


# ── Helpers ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = "You are Nova, a Socratic tutor."


def _make_mock_llm(summary_text: str = "Student is learning about photosynthesis."):
    """Create a mock LLM engine with a working quick_call."""
    mock = AsyncMock()
    mock.quick_call = AsyncMock(return_value=summary_text)
    return mock


# ── Basic Operations ─────────────────────────────────────────────────────


class TestBasicOperations:
    """Core session history management."""

    def test_append_turn(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("Is it the chloroplast?", "Nice thinking! What happens inside?")

        assert sm.turn_count == 1
        assert len(sm.history) == 2  # user + assistant

    def test_history_has_correct_roles(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("Hello", "Hi there! What would you like to learn?")

        assert sm.history[0]["role"] == "user"
        assert sm.history[0]["content"] == "Hello"
        assert sm.history[1]["role"] == "assistant"
        assert sm.history[1]["content"] == "Hi there! What would you like to learn?"

    def test_get_context_includes_system_prompt(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        context = sm.get_context()

        assert context[0]["role"] == "system"
        assert SYSTEM_PROMPT in context[0]["content"]

    def test_get_context_includes_recent_history(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        # Add 3 turns (6 messages)
        for i in range(3):
            sm.append_turn(f"Student says {i}", f"Tutor replies {i}?")

        context = sm.get_context()
        # Should have system + 6 messages
        assert len(context) == 7
        assert context[-1]["content"] == "Tutor replies 2?"

    def test_multiple_turns_build_history(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(5):
            sm.append_turn(f"Q{i}", f"A{i}?")

        assert sm.turn_count == 5
        assert len(sm.history) == 10  # 5 * 2 messages


# ── Token Economy ────────────────────────────────────────────────────────


class TestTokenEconomy:
    """History compression keeps context size bounded."""

    @pytest.mark.asyncio
    async def test_compression_triggers_at_12_messages(self):
        """Compression should trigger after 12 messages (6 user+assistant pairs)."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm("Summary of first 6 turns.")
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        # Add 6 turns = 12 messages → triggers compression
        for i in range(6):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        await sm.maybe_compress_history()
        assert llm.quick_call.called

    @pytest.mark.asyncio
    async def test_compression_produces_summary(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm("Student explored photosynthesis basics.")
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(6):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        await sm.maybe_compress_history()
        assert sm.summary == "Student explored photosynthesis basics."

    @pytest.mark.asyncio
    async def test_old_messages_pruned(self):
        """After compression, only last 6 messages remain in detail."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm("Summary.")
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(8):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        await sm.maybe_compress_history()
        # After compression, only last 6 messages kept
        assert len(sm.history) <= 6

    @pytest.mark.asyncio
    async def test_context_tokens_bounded(self):
        """After 30 turns, total context should stay under 2000 tokens (approx)."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm("Brief summary of conversation so far.")
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(30):
            sm.append_turn(
                f"What about concept {i}?",
                f"Great question! What do you think about aspect {i}?",
            )
            # Trigger compression periodically
            await sm.maybe_compress_history()

        context = sm.get_context()
        # Rough token proxy: ~4 chars per token
        total_chars = sum(len(msg["content"]) for msg in context)
        total_tokens_approx = total_chars / 4
        assert total_tokens_approx < 2000

    @pytest.mark.asyncio
    async def test_summary_included_in_context(self):
        """After compression, context should include the summary."""
        from pipeline.session_manager import SessionManager

        summary_text = "The student is learning about plant cells."
        llm = _make_mock_llm(summary_text)
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(6):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        await sm.maybe_compress_history()
        context = sm.get_context()

        # Summary should appear in the system message or as a separate message
        all_content = " ".join(msg["content"] for msg in context)
        assert summary_text in all_content

    @pytest.mark.asyncio
    async def test_no_compression_below_threshold(self):
        """Compression should NOT trigger with fewer than COMPRESS_EVERY turns."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        # Only 3 turns = 6 messages, below threshold of 12
        for i in range(3):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        await sm.maybe_compress_history()
        assert not llm.quick_call.called


# ── Serialization (to_dict / from_dict) ──────────────────────────────────


class TestSerialization:
    """Verify session state can be serialized and restored for persistence."""

    def test_to_dict_roundtrip(self):
        """to_dict → from_dict should produce an identical session."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("Hello", "Hi! What topic?")
        sm.append_turn("Photosynthesis", "Great! What do plants need?")
        sm.lesson_progress = {
            "topic": "photosynthesis",
            "current_step_id": 2,
            "visual_step_id": 2,
            "failed_attempts_on_current_step": 1,
            "revealed_elements": ["sunlight", "water"],
        }

        data = sm.to_dict()
        restored = SessionManager.from_dict(data, SYSTEM_PROMPT, llm)

        assert restored.turn_count == sm.turn_count
        assert restored.summary == sm.summary
        assert len(restored.history) == len(sm.history)
        assert restored.history == sm.history
        assert restored.lesson_progress == sm.lesson_progress

    def test_from_dict_produces_correct_context(self):
        """Restored session should produce the same LLM context as the original."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        for i in range(3):
            sm.append_turn(f"Q{i}", f"A{i}?")

        original_context = sm.get_context()
        restored = SessionManager.from_dict(sm.to_dict(), SYSTEM_PROMPT, llm)
        restored_context = restored.get_context()

        assert len(restored_context) == len(original_context)
        for orig, rest in zip(original_context, restored_context):
            assert orig["role"] == rest["role"]
            assert orig["content"] == rest["content"]

    def test_to_dict_includes_all_fields(self):
        """to_dict should include history, summary, turn_count, turns_since_compression."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("Q1", "A1?")
        sm.summary = "Prior summary."
        sm.lesson_progress = {
            "topic": "photosynthesis",
            "current_step_id": 1,
            "visual_step_id": 1,
            "failed_attempts_on_current_step": 2,
            "revealed_elements": ["sunlight", "water", "roots"],
        }

        data = sm.to_dict()
        assert "history" in data
        assert "summary" in data
        assert "turn_count" in data
        assert "lesson_progress" in data
        assert "turns_since_compression" in data
        assert data["summary"] == "Prior summary."
        assert data["turn_count"] == 1
        assert data["lesson_progress"]["failed_attempts_on_current_step"] == 2
        assert data["lesson_progress"]["revealed_elements"] == ["sunlight", "water", "roots"]

    def test_from_dict_with_empty_data(self):
        """from_dict with empty dict should produce a fresh session."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        restored = SessionManager.from_dict({}, SYSTEM_PROMPT, llm)

        assert restored.turn_count == 0
        assert restored.history == []
        assert restored.summary == ""


# ── Interrupted Turns ────────────────────────────────────────────────────


class TestInterruptedTurns:
    """Interrupted turns should be marked and partial responses saved."""

    def test_interrupted_turn_marked(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("What is photosynthesis?", "Well, let me ask you—", interrupted=True)

        # The assistant message should have an interruption marker
        assistant_msg = sm.history[-1]
        assert "[interrupted]" in assistant_msg["content"]

    def test_partial_response_saved(self):
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)
        sm.append_turn("Question?", "Partial response so far", interrupted=True)

        # The partial response text should be preserved
        assistant_msg = sm.history[-1]
        assert "Partial response so far" in assistant_msg["content"]


# ── Error Handling ───────────────────────────────────────────────────────


class TestErrorHandling:
    """Compression failure must degrade gracefully."""

    @pytest.mark.asyncio
    async def test_compression_failure_degrades_gracefully(self):
        """If LLM quick_call fails, session should continue with uncompressed history."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        llm.quick_call = AsyncMock(side_effect=Exception("LLM down"))
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(8):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        # Should not raise
        await sm.maybe_compress_history()

        # History should still be usable
        context = sm.get_context()
        assert len(context) > 0

    @pytest.mark.asyncio
    async def test_compression_failure_preserves_history(self):
        """On compression failure, all history messages should still be present."""
        from pipeline.session_manager import SessionManager

        llm = _make_mock_llm()
        llm.quick_call = AsyncMock(side_effect=Exception("LLM down"))
        sm = SessionManager(system_prompt=SYSTEM_PROMPT, llm_engine=llm)

        for i in range(8):
            sm.append_turn(f"Student {i}", f"Tutor {i}?")

        original_len = len(sm.history)
        await sm.maybe_compress_history()

        # History should not be truncated since compression failed
        assert len(sm.history) == original_len
