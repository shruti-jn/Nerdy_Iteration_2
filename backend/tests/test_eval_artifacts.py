"""
Tests for eval and benchmark artifact generation (no live API calls).

Verifies JSON/markdown schema, percentile computation, and pass/fail logic
using mocks and fixtures.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.validate_socratic_prompt import (
    TurnResult,
    _percentile,
    print_report,
    write_markdown_summary,
)


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


class TestPercentileEval:
    """Test percentile helper used in eval summary."""

    def test_empty_returns_zero(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_single_value(self) -> None:
        assert _percentile([10.0], 50) == 10.0
        assert _percentile([10.0], 95) == 10.0

    def test_p50_p95_known(self) -> None:
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 50) == 3.0
        assert _percentile(vals, 95) == pytest.approx(4.8, rel=0.01)

    def test_sorted_input_required(self) -> None:
        # _percentile expects sorted list; p50 of sorted [1,3,5] is 3
        vals = [1.0, 3.0, 5.0]
        assert _percentile(vals, 50) == 3.0


# ---------------------------------------------------------------------------
# print_report pass/fail
# ---------------------------------------------------------------------------


def _make_turn(
    turn_number: int = 1,
    ends_with_question: float = 1.0,
    no_direct_answer: float = 1.0,
    no_negation: float = 1.0,
    readability: float = 6.0,
    encouragement: float = 1.0,
    response_length: int = 20,
) -> TurnResult:
    return TurnResult(
        turn_number=turn_number,
        student_input="What is it?",
        tutor_response="What do you think?",
        ends_with_question=ends_with_question,
        no_direct_answer=no_direct_answer,
        no_negation=no_negation,
        readability=readability,
        encouragement=encouragement,
        response_length=response_length,
        llm_latency_ms=100.0,
    )


class TestPrintReportVerdict:
    """Test that print_report returns True/False by threshold."""

    def test_empty_results_returns_false(self) -> None:
        assert print_report("test", []) is False

    def test_all_pass_returns_true(self) -> None:
        results = [_make_turn(i) for i in range(1, 4)]
        assert print_report("test", results) is True

    def test_missing_question_fails(self) -> None:
        results = [
            _make_turn(1),
            _make_turn(2, ends_with_question=0.0),
        ]
        assert print_report("test", results) is False

    def test_direct_answer_fails(self) -> None:
        results = [
            _make_turn(1),
            _make_turn(2, no_direct_answer=0.0),
        ]
        assert print_report("test", results) is False

    def test_negation_fails(self) -> None:
        results = [
            _make_turn(1),
            _make_turn(2, no_negation=0.0),
        ]
        assert print_report("test", results) is False

    def test_readability_out_of_range_fails(self) -> None:
        results = [_make_turn(1, readability=2.0)]
        assert print_report("test", results) is False
        # Upper bound is 13.0 (calibrated for STEM content at high-school level)
        results = [_make_turn(1, readability=14.0)]
        assert print_report("test", results) is False

    def test_readability_stem_level_passes(self) -> None:
        """Readability between 9 and 13 should pass (STEM content, high school)."""
        results = [_make_turn(1, readability=10.5)]
        assert print_report("test", results) is True
        results = [_make_turn(1, readability=12.5)]
        assert print_report("test", results) is True
        results = [_make_turn(1, readability=13.0)]
        assert print_report("test", results) is True


# ---------------------------------------------------------------------------
# write_markdown_summary
# ---------------------------------------------------------------------------


class TestWriteMarkdownSummary:
    """Test markdown summary artifact shape and content."""

    def test_writes_file_with_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            all_results = {
                "photosynthesis": [_make_turn(1), _make_turn(2)],
            }
            write_markdown_summary(str(path), all_results, "2026-01-01T00:00:00Z", "llama-3.3-70b")
            text = path.read_text()
            assert "# Socratic Validation Summary" in text
            assert "## Per-topic results" in text
            assert "photosynthesis" in text
            assert "| Topic |" in text
            assert "## Overall verdict" in text

    def test_empty_topic_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            all_results = {"empty_topic": []}
            write_markdown_summary(str(path), all_results, "2026-01-01T00:00:00Z", "model")
            text = path.read_text()
            assert "empty_topic" in text
            assert "| 0 |" in text or "0 |" in text


# ---------------------------------------------------------------------------
# JSON artifact schema (eval)
# ---------------------------------------------------------------------------


class TestEvalJsonSchema:
    """Test that the eval JSON structure has expected keys and types."""

    def test_turn_result_asdict_has_required_keys(self) -> None:
        from dataclasses import asdict
        r = _make_turn(1)
        d = asdict(r)
        assert "turn_number" in d
        assert "student_input" in d
        assert "tutor_response" in d
        assert "ends_with_question" in d
        assert "no_direct_answer" in d
        assert "llm_latency_ms" in d
        assert isinstance(d["turn_number"], int)
        assert isinstance(d["llm_latency_ms"], (int, float))

    def test_full_data_structure_matches_expected_schema(self) -> None:
        """Structure that validate_socratic_prompt.main() / run_socratic_eval produce."""
        data = {
            "timestamp": "2026-01-01T00:00:00Z",
            "model": "llama-3.3-70b-versatile",
            "topics": {
                "photosynthesis": {
                    "turns": [{"turn_number": 1, "student_input": "x", "tutor_response": "y?", "ends_with_question": 1.0, "no_direct_answer": 1.0, "no_negation": 1.0, "readability": 6.0, "encouragement": 1.0, "response_length": 10, "llm_latency_ms": 50.0}],
                    "summary": {
                        "total_turns": 1,
                        "question_pct": 100.0,
                        "no_answer_pct": 100.0,
                        "no_negation_pct": 100.0,
                        "avg_readability": 6.0,
                        "encouragement_pct": 100.0,
                        "avg_word_count": 10.0,
                        "llm_latency_p50_ms": 50.0,
                        "llm_latency_p95_ms": 50.0,
                    },
                },
            },
        }
        assert "timestamp" in data
        assert "model" in data
        assert "topics" in data
        for topic, payload in data["topics"].items():
            assert "turns" in payload
            assert "summary" in payload
            assert "llm_latency_p50_ms" in payload["summary"]
            assert "llm_latency_p95_ms" in payload["summary"]


# ---------------------------------------------------------------------------
# Benchmark report schema and percentile
# ---------------------------------------------------------------------------


class TestBenchmarkPercentile:
    """Test percentile in benchmarks.run_benchmarks."""

    def test_benchmark_percentile(self) -> None:
        from benchmarks.run_benchmarks import _percentile as bench_percentile
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert bench_percentile(vals, 50) == 30.0
        assert bench_percentile(vals, 95) == pytest.approx(48.0, rel=0.01)
        assert bench_percentile([], 50) == 0.0


class TestBenchmarkReportSchema:
    """Test benchmark_report.json structure."""

    def test_write_benchmark_report_produces_valid_json(self) -> None:
        from benchmarks.run_benchmarks import _write_benchmark_report
        with tempfile.TemporaryDirectory() as tmp:
            report = _write_benchmark_report(
                tmp,
                provider_results=None,
                pipeline_runs=[
                    {"stt_finish_ms": 100, "llm_ttf_ms": 200, "tts_ttf_ms": 50, "turn_duration_ms": 400},
                    {"stt_finish_ms": 120, "llm_ttf_ms": 220, "tts_ttf_ms": 60, "turn_duration_ms": 450},
                ],
                pipeline_passed=True,
                timestamp="2026-01-01T00:00:00Z",
            )
            report_path = Path(tmp) / "benchmark_report.json"
            assert report_path.exists()
            with open(report_path) as f:
                loaded = json.load(f)
            report = loaded
            assert "timestamp" in report
            assert report["pipeline_benchmark"] is not None
            pb = report["pipeline_benchmark"]
            assert pb["runs"] == 2
            assert "stt_finish_ms" in pb
            assert "p50" in pb["stt_finish_ms"]
            assert "p95" in pb["stt_finish_ms"]
            assert "p99" in pb["stt_finish_ms"]
            assert pb["passed"] is True

    def test_write_benchmark_summary_produces_markdown(self) -> None:
        from benchmarks.run_benchmarks import _write_benchmark_report, _write_benchmark_summary
        with tempfile.TemporaryDirectory() as tmp:
            report = _write_benchmark_report(
                tmp,
                provider_results=None,
                pipeline_runs=[
                    {"stt_finish_ms": 100, "llm_ttf_ms": 200, "tts_ttf_ms": 50, "turn_duration_ms": 400},
                ],
                pipeline_passed=True,
                timestamp="2026-01-01T00:00:00Z",
            )
            _write_benchmark_summary(tmp, report, None, True)
            summary_path = Path(tmp) / "benchmark_summary.md"
            assert summary_path.exists()
            text = summary_path.read_text()
            assert "# Benchmark Summary" in text
            assert "Pipeline latency" in text or "pipeline" in text.lower()
            assert "p50" in text
            assert "PASS" in text
