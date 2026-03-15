"""
Unit tests for CustomOrchestrator avatar-path behavior.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, call

import pytest

from pipeline.lesson_progress import LessonProgressState
from pipeline.metrics import MetricsCollector
from pipeline.orchestrator_custom import CustomOrchestrator, _build_turn_hint


class _FakeTTS:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def stream(self, text: str, metrics: MetricsCollector):
        del text, metrics
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_stream_text_audio_forwards_chunks_to_frontend_and_simli_adapter(test_config):
    """Custom Simli mode should drive both browser playback and backend lip-sync."""
    sent_messages: list[dict] = []

    async def send_json(payload: dict) -> None:
        sent_messages.append(payload)

    orchestrator = CustomOrchestrator(
        test_config,
        "test-session",
        send_json,
        avatar_provider="simli",
    )
    orchestrator._tts = _FakeTTS([b"\x01\x02", b"\x03\x04"])
    orchestrator._simli = AsyncMock()

    await orchestrator._stream_text_audio("hello", MetricsCollector(), label="test")

    assert sent_messages == [
        {"type": "audio_chunk", "data": base64.b64encode(b"\x01\x02").decode("ascii")},
        {"type": "audio_chunk", "data": base64.b64encode(b"\x03\x04").decode("ascii")},
    ]
    orchestrator._simli.send_audio.assert_has_awaits(
        [call(b"\x01\x02"), call(b"\x03\x04")]
    )


@pytest.mark.asyncio
async def test_stream_text_audio_only_uses_frontend_audio_when_simli_is_absent(test_config):
    """SDK mode should keep using the frontend-only audio path."""
    sent_messages: list[dict] = []

    async def send_json(payload: dict) -> None:
        sent_messages.append(payload)

    orchestrator = CustomOrchestrator(
        test_config,
        "test-session",
        send_json,
        avatar_provider="simli",
    )
    orchestrator._tts = _FakeTTS([b"\x05\x06"])

    await orchestrator._stream_text_audio("hello", MetricsCollector(), label="test")

    assert sent_messages == [
        {"type": "audio_chunk", "data": base64.b64encode(b"\x05\x06").decode("ascii")},
    ]


def test_constructor_uses_explicit_avatar_provider(test_config):
    """Per-session avatar provider must override the global default."""
    test_config.avatar_provider = "simli"

    orchestrator = CustomOrchestrator(
        test_config,
        "test-session",
        AsyncMock(),
        avatar_provider="spatialreal",
    )

    assert orchestrator._avatar_provider == "spatialreal"


def test_build_turn_hint_uses_scaffold_level_and_blocks_teach_back_until_ready():
    progress = LessonProgressState(
        topic="photosynthesis",
        current_step_id=1,
        visual_step_id=1,
        failed_attempts_on_current_step=3,
        revealed_elements=["carbon_dioxide", "sunlight"],
    )

    hint = _build_turn_hint(
        turn_number=13,
        max_turns=15,
        progress=progress,
        total_steps=7,
        transcript="Water.",
    )

    assert "SCAFFOLD LEVEL 3" in hint
    assert "A, B, and C" in hint
    assert "do not force a recap or teach-back" in hint
    assert "ACCEPTED SO FAR=carbon dioxide, sunlight" in hint
    assert "ACCEPTED THIS TURN=water" in hint
    assert "MISSING NOW=none yet" in hint
    assert "DO NOT RE-ASK=carbon dioxide, sunlight, water" in hint
    assert "Treat ACCEPTED SO FAR as ideas the student had already earned before this reply." in hint
    assert "[TEACH-BACK PHASE]" not in hint


def test_build_turn_hint_unlocks_teach_back_when_final_step_reached():
    progress = LessonProgressState(
        topic="photosynthesis",
        current_step_id=6,
        visual_step_id=6,
        failed_attempts_on_current_step=0,
    )

    hint = _build_turn_hint(turn_number=13, max_turns=15, progress=progress, total_steps=7)

    assert "[TEACH-BACK PHASE]" in hint
