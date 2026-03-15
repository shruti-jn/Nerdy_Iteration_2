"""
Shared pytest fixtures for all test files.

Pipeline stage: Testing infrastructure (shared across all pipeline stages).

Provides reusable fixtures for:
  - Application configuration with fake/test API keys
  - Sample Socratic tutoring turns (correct, wrong, lecture)
  - Mock audio frame async iterators for STT adapter testing
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import AsyncIterator

import pytest


# ---------------------------------------------------------------------------
# test_config — fake Settings-like object for unit tests
# ---------------------------------------------------------------------------


@dataclass
class TestConfig:
    """Minimal config object with fake API keys for unit testing.

    Mirrors the shape of ``config.Settings`` without requiring a real
    ``.env`` file or live credentials.
    """

    deepgram_api_key: str = "test-deepgram-key-00000"
    groq_api_key: str = "test-groq-key-00000"
    cartesia_api_key: str = "test-cartesia-key-00000"
    cartesia_voice_id: str = "test-cartesia-voice-id-00000"
    elevenlabs_api_key: str = "test-elevenlabs-key-00000"
    elevenlabs_voice_id: str = "test-voice-id-00000"
    tts_provider: str = "cartesia"
    simli_api_key: str = "test-simli-key-00000"
    avatar_provider: str = "simli"
    spatialreal_api_key: str = "test-spatialreal-key-00000"
    spatialreal_app_id: str = "test-app-id-00000"
    spatialreal_avatar_id: str = "test-avatar-id-00000"
    spatialreal_region: str = "us-west"
    logfire_token: str = "test-logfire-token-00000"
    braintrust_api_key: str = "test-braintrust-key-00000"
    stt_target_ms: int = 150
    stt_max_ms: int = 300
    llm_ttft_target_ms: int = 200
    llm_ttft_max_ms: int = 400
    tts_target_ms: int = 150
    tts_max_ms: int = 300
    avatar_target_ms: int = 100
    avatar_max_ms: int = 200
    total_target_ms: int = 500
    total_max_ms: int = 1000


@pytest.fixture
def test_config() -> TestConfig:
    """Return a config object populated with fake / test API keys."""
    return TestConfig()


# ---------------------------------------------------------------------------
# Sample tutoring turns
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_turn_correct() -> dict:
    """A turn where the student answered correctly.

    The tutor should affirm and probe deeper with a follow-up question.
    """
    return {
        "student_input": "Is it the chloroplast?",
        "tutor_response": (
            "Nice thinking! What happens inside the chloroplast "
            "that converts sunlight to energy?"
        ),
        "topic": "photosynthesis",
    }


@pytest.fixture
def sample_turn_wrong() -> dict:
    """A turn where the student answered incorrectly.

    The tutor should redirect without blunt negation, using a guiding
    question to lead the student toward the right organelle.
    """
    return {
        "student_input": "Photosynthesis happens in the mitochondria",
        "tutor_response": (
            "Interesting idea! Mitochondria do play a big role in cells. "
            "But which organelle is green and captures sunlight?"
        ),
        "topic": "photosynthesis",
    }


@pytest.fixture
def sample_turn_lecture() -> dict:
    """A turn where the tutor accidentally lectures (negative test case).

    This response gives a direct factual explanation instead of asking a
    guiding question, which violates the Socratic method.
    """
    return {
        "student_input": "How do plants make food?",
        "tutor_response": (
            "Photosynthesis is the process by which plants convert "
            "sunlight, water, and CO2 into glucose and oxygen."
        ),
        "topic": "photosynthesis",
    }


# ---------------------------------------------------------------------------
# Mock audio frames for STT adapter testing
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_audio_frames():
    """Return an async iterator that yields 5 chunks of random bytes.

    Simulates a stream of raw audio frames for STT adapter tests.
    Each chunk is 1600 bytes (100ms of 16-bit mono audio at 16 kHz).
    """

    async def _audio_stream() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield os.urandom(1600)

    return _audio_stream


# ---------------------------------------------------------------------------
# MetricsCollector fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def metrics_collector():
    """Return a fresh MetricsCollector instance for per-test latency tracking."""
    from pipeline.metrics import MetricsCollector

    return MetricsCollector()
