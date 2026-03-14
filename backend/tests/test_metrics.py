"""
Tests for the MetricsCollector and StageMetrics.

Validates timing recording, TTFT tracking, turn duration, and
the flat dict export for structured logging.

Pipeline stage: Infrastructure (shared by all stages)
"""

import time

import pytest

from pipeline.metrics import MetricsCollector, StageMetrics


# ---------------------------------------------------------------------------
# StageMetrics
# ---------------------------------------------------------------------------

class TestStageMetrics:
    """Tests for the StageMetrics dataclass."""

    def test_duration_ms_when_complete(self):
        """duration_ms returns correct value when first_start and end are set."""
        sm = StageMetrics(stage="llm", first_start_ns=1_000_000, start_ns=1_000_000, end_ns=11_000_000)
        assert sm.duration_ms == 10.0

    def test_duration_ms_when_incomplete(self):
        """duration_ms returns None when end_ns is not set."""
        sm = StageMetrics(stage="llm", start_ns=1_000_000)
        assert sm.duration_ms is None

    def test_time_to_first_ms_when_complete(self):
        """time_to_first_ms returns correct value when first_start and first_token are set."""
        sm = StageMetrics(stage="llm", first_start_ns=1_000_000, start_ns=1_000_000, first_token_ns=6_000_000)
        assert sm.time_to_first_ms == 5.0

    def test_time_to_first_ms_when_incomplete(self):
        """time_to_first_ms returns None when first_token_ns is not set."""
        sm = StageMetrics(stage="llm", start_ns=1_000_000)
        assert sm.time_to_first_ms is None

    def test_all_none_by_default(self):
        """All timing fields are None by default."""
        sm = StageMetrics(stage="tts")
        assert sm.first_start_ns is None
        assert sm.start_ns is None
        assert sm.first_token_ns is None
        assert sm.end_ns is None
        assert sm.invocations == 0
        assert sm.duration_ms is None
        assert sm.time_to_first_ms is None


# ---------------------------------------------------------------------------
# MetricsCollector — turn-level
# ---------------------------------------------------------------------------

class TestMetricsCollectorTurn:
    """Tests for turn-level timing."""

    def test_turn_duration_records_correctly(self):
        """start_turn/end_turn records a measurable duration."""
        mc = MetricsCollector()
        mc.start_turn()
        # Small sleep to ensure non-zero duration
        time.sleep(0.001)
        mc.end_turn()
        assert mc.turn_duration_ms is not None
        assert mc.turn_duration_ms > 0

    def test_turn_duration_none_before_end(self):
        """turn_duration_ms is None if end_turn hasn't been called."""
        mc = MetricsCollector()
        mc.start_turn()
        assert mc.turn_duration_ms is None

    def test_turn_duration_none_before_start(self):
        """turn_duration_ms is None if start_turn hasn't been called."""
        mc = MetricsCollector()
        assert mc.turn_duration_ms is None


# ---------------------------------------------------------------------------
# MetricsCollector — stage-level
# ---------------------------------------------------------------------------

class TestMetricsCollectorStage:
    """Tests for per-stage timing."""

    def test_start_and_end_records_duration(self):
        """start/end for a stage records measurable duration."""
        mc = MetricsCollector()
        mc.start("llm")
        time.sleep(0.001)
        mc.end("llm")
        stage = mc.get_stage("llm")
        assert stage is not None
        assert stage.duration_ms is not None
        assert stage.duration_ms > 0

    def test_mark_first_records_ttf(self):
        """mark_first records time-to-first for a stage."""
        mc = MetricsCollector()
        mc.start("tts")
        time.sleep(0.001)
        mc.mark_first("tts")
        stage = mc.get_stage("tts")
        assert stage is not None
        assert stage.time_to_first_ms is not None
        assert stage.time_to_first_ms > 0

    def test_get_stage_returns_none_for_unknown(self):
        """get_stage returns None for a stage that was never tracked."""
        mc = MetricsCollector()
        assert mc.get_stage("nonexistent") is None

    def test_multiple_stages_independent(self):
        """Multiple stages are tracked independently."""
        mc = MetricsCollector()
        mc.start("stt")
        mc.start("llm")
        mc.end("stt")
        mc.end("llm")
        stt = mc.get_stage("stt")
        llm = mc.get_stage("llm")
        assert stt is not None
        assert llm is not None
        assert stt.duration_ms is not None
        assert llm.duration_ms is not None


# ---------------------------------------------------------------------------
# MetricsCollector — to_dict
# ---------------------------------------------------------------------------

class TestMetricsCollectorToDict:
    """Tests for the flat dict export."""

    def test_to_dict_keys_convention(self):
        """to_dict follows {stage}_ttf_ms / {stage}_duration_ms convention."""
        mc = MetricsCollector()
        mc.start_turn()
        mc.start("llm")
        mc.mark_first("llm")
        mc.end("llm")
        mc.end_turn()
        d = mc.to_dict()
        assert "llm_ttf_ms" in d
        assert "llm_duration_ms" in d
        assert "turn_duration_ms" in d

    def test_to_dict_values_are_numbers(self):
        """to_dict values are floats (not None) when stages are complete."""
        mc = MetricsCollector()
        mc.start_turn()
        mc.start("tts")
        mc.mark_first("tts")
        time.sleep(0.001)
        mc.end("tts")
        mc.end_turn()
        d = mc.to_dict()
        assert isinstance(d["tts_ttf_ms"], float)
        assert isinstance(d["tts_duration_ms"], float)
        assert isinstance(d["turn_duration_ms"], float)

    def test_to_dict_empty_collector(self):
        """to_dict returns only turn_duration_ms when no stages tracked."""
        mc = MetricsCollector()
        d = mc.to_dict()
        assert d == {"turn_duration_ms": None}

    def test_to_dict_multiple_stages(self):
        """to_dict includes all tracked stages."""
        mc = MetricsCollector()
        mc.start("stt")
        mc.end("stt")
        mc.start("llm")
        mc.end("llm")
        d = mc.to_dict()
        assert "stt_ttf_ms" in d
        assert "stt_duration_ms" in d
        assert "llm_ttf_ms" in d
        assert "llm_duration_ms" in d
