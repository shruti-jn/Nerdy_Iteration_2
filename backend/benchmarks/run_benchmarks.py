"""Benchmark runner helpers for latency benchmark artifacts."""

from __future__ import annotations

import json
import math
import os
from typing import Any


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Return a linear-interpolated percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    rank = (len(sorted_values) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[lower])

    lower_value = float(sorted_values[lower])
    upper_value = float(sorted_values[upper])
    weight = rank - lower
    return lower_value + (upper_value - lower_value) * weight


def _stage_summary(pipeline_runs: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = sorted(float(run[key]) for run in pipeline_runs if run.get(key) is not None)
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
    }


def _write_benchmark_report(
    output_dir: str,
    provider_results: Any,
    pipeline_runs: list[dict[str, Any]],
    pipeline_passed: bool,
    timestamp: str,
) -> dict[str, Any]:
    """Write the JSON benchmark artifact expected by tests."""
    os.makedirs(output_dir, exist_ok=True)
    report = {
        "timestamp": timestamp,
        "provider_results": provider_results,
        "pipeline_benchmark": {
            "runs": len(pipeline_runs),
            "passed": pipeline_passed,
            "stt_finish_ms": _stage_summary(pipeline_runs, "stt_finish_ms"),
            "llm_ttf_ms": _stage_summary(pipeline_runs, "llm_ttf_ms"),
            "tts_ttf_ms": _stage_summary(pipeline_runs, "tts_ttf_ms"),
            "turn_duration_ms": _stage_summary(pipeline_runs, "turn_duration_ms"),
        } if pipeline_runs else None,
    }
    report_path = os.path.join(output_dir, "benchmark_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    return report


def _write_benchmark_summary(
    output_dir: str,
    report: dict[str, Any],
    provider_results: Any,
    pipeline_passed: bool,
) -> str:
    """Write a simple markdown summary next to the JSON report."""
    os.makedirs(output_dir, exist_ok=True)
    pb = report.get("pipeline_benchmark")
    lines = [
        "# Benchmark Summary",
        "",
        f"Pipeline latency verdict: {'PASS' if pipeline_passed else 'FAIL'}",
        "",
    ]
    if pb is not None:
        lines.extend([
            "| Stage | p50 | p95 | p99 |",
            "| --- | ---: | ---: | ---: |",
            f"| STT | {pb['stt_finish_ms']['p50']:.1f} | {pb['stt_finish_ms']['p95']:.1f} | {pb['stt_finish_ms']['p99']:.1f} |",
            f"| LLM | {pb['llm_ttf_ms']['p50']:.1f} | {pb['llm_ttf_ms']['p95']:.1f} | {pb['llm_ttf_ms']['p99']:.1f} |",
            f"| TTS | {pb['tts_ttf_ms']['p50']:.1f} | {pb['tts_ttf_ms']['p95']:.1f} | {pb['tts_ttf_ms']['p99']:.1f} |",
            f"| Total | {pb['turn_duration_ms']['p50']:.1f} | {pb['turn_duration_ms']['p95']:.1f} | {pb['turn_duration_ms']['p99']:.1f} |",
            "",
        ])
    summary_path = os.path.join(output_dir, "benchmark_summary.md")
    with open(summary_path, "w") as f:
        f.write("\n".join(lines))
    return summary_path
