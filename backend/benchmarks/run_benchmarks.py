"""
Benchmark runner — provider validation + end-to-end pipeline latency.

Run via:
    python -m benchmarks.run_benchmarks                     # providers + pipeline (5 runs)
    python -m benchmarks.run_benchmarks --providers-only    # skip pipeline
    python -m benchmarks.run_benchmarks --pipeline-only --runs 3
    python -m benchmarks.run_benchmarks --runs 10

Artifacts written to benchmarks/results/:
    benchmark_report.json    -- machine-readable full report
    benchmark_summary.md     -- human-readable markdown table
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
import time
from datetime import datetime, timezone
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
        ])
        stt = pb.get("stt_finish_ms")
        if stt:
            lines.append(f"| STT | {stt['p50']:.1f} | {stt['p95']:.1f} | {stt['p99']:.1f} |")
        llm = pb.get("llm_ttf_ms")
        if llm:
            lines.append(f"| LLM TTFT | {llm['p50']:.1f} | {llm['p95']:.1f} | {llm['p99']:.1f} |")
        tts = pb.get("tts_ttf_ms")
        if tts:
            lines.append(f"| TTS TTFA | {tts['p50']:.1f} | {tts['p95']:.1f} | {tts['p99']:.1f} |")
        total = pb.get("turn_duration_ms")
        if total:
            lines.append(f"| Total TTFA | {total['p50']:.1f} | {total['p95']:.1f} | {total['p99']:.1f} |")
        lines.append("")
        lines.append(
            "_Note: STT measured via Deepgram prerecorded API (1 s WAV). "
            "Production uses live WebSocket STT that processes audio concurrently as the "
            "student speaks, so real-world end-to-end TTFA is lower. "
            "Pipeline pass gate: LLM TTFT p50 < 500 ms, TTS TTFA p50 < 700 ms._"
        )
        lines.append("")
    summary_path = os.path.join(output_dir, "benchmark_summary.md")
    with open(summary_path, "w") as f:
        f.write("\n".join(lines))
    return summary_path


# ---------------------------------------------------------------------------
# Pipeline benchmark
# ---------------------------------------------------------------------------

_PIPELINE_TEST_TRANSCRIPT = "Plants need sunlight and water to make their own food through photosynthesis."

_PIPELINE_PASS_CRITERIA = {
    "llm_ttf_ms": 500.0,   # Groq 70b TTFT p50 < 500ms
    "tts_ttf_ms": 700.0,   # Cartesia TTFA p50 < 700ms (SSE streaming; benchmark overhead ~400-600ms)
}


def _gen_test_audio_wav(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate near-silent PCM16 audio wrapped in a WAV container.

    Deepgram prerecorded API determines encoding/sample-rate from the WAV header,
    avoiding the need to pass ``encoding`` as a separate query parameter.
    """
    import random
    random.seed(42)
    n = int(sample_rate * duration_s)
    samples = [random.randint(-10, 10) for _ in range(n)]
    pcm_data = struct.pack(f"<{n}h", *samples)

    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)
    file_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", file_size, b"WAVE",
        b"fmt ", 16, 1, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm_data


async def _pipeline_run_once(settings: Any) -> dict[str, Any]:
    """Execute one STT → LLM → TTS pass and return per-stage timing in ms."""
    run: dict[str, Any] = {}

    # --- STT (prerecorded) ---
    t0 = time.perf_counter()
    try:
        from deepgram import DeepgramClient
        dg = DeepgramClient(api_key=settings.deepgram_api_key)
        audio = _gen_test_audio_wav()
        dg.listen.v1.media.transcribe_file(
            request=audio,
            model="nova-3",
            language="en",
        )
        run["stt_finish_ms"] = (time.perf_counter() - t0) * 1000
    except Exception as exc:
        print(f"    [STT] {exc}")

    # --- LLM (Groq 70b streaming TTFT) ---
    t0 = time.perf_counter()
    try:
        from groq import Groq
        groq = Groq(api_key=settings.groq_api_key)
        stream = groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a Socratic tutor."},
                {"role": "user", "content": _PIPELINE_TEST_TRANSCRIPT},
            ],
            stream=True,
            max_tokens=100,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                run["llm_ttf_ms"] = (time.perf_counter() - t0) * 1000
                break
    except Exception as exc:
        print(f"    [LLM] {exc}")

    # --- TTS (Cartesia Sonic-3 TTFA) ---
    t0 = time.perf_counter()
    try:
        from cartesia import AsyncCartesia
        voice_id = getattr(settings, "cartesia_voice_id", "a0e99841-438c-4a64-b679-ae501e7d6091")
        client = AsyncCartesia(api_key=settings.cartesia_api_key)
        stream = await client.tts.generate_sse(
            model_id="sonic-3",
            transcript="What do you think about that?",
            voice={"mode": "id", "id": voice_id},
            output_format={"container": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
        )
        async for event in stream:
            if event.type == "chunk" and event.audio:
                run["tts_ttf_ms"] = (time.perf_counter() - t0) * 1000
                break
        await client.close()
    except Exception as exc:
        print(f"    [TTS] {exc}")

    # Total TTFA = sum of available stages (excludes STT from pass gate since
    # production uses live streaming STT which runs concurrently with speech)
    llm = run.get("llm_ttf_ms", 0.0)
    tts = run.get("tts_ttf_ms", 0.0)
    stt = run.get("stt_finish_ms", 0.0)
    run["turn_duration_ms"] = stt + llm + tts
    return run


async def _run_pipeline_benchmark_async(settings: Any, num_runs: int = 5) -> tuple[list[dict], bool]:
    """Run the end-to-end pipeline benchmark and return (runs, passed)."""
    print(f"\n--- PIPELINE BENCHMARK ({num_runs} runs) ---")
    print(f"  Transcript: '{_PIPELINE_TEST_TRANSCRIPT[:60]}...'")
    runs: list[dict] = []

    for i in range(num_runs):
        print(f"\n  Run {i + 1}/{num_runs}:")
        run = await _pipeline_run_once(settings)
        runs.append(run)
        stt_s = f"{run['stt_finish_ms']:.0f}" if "stt_finish_ms" in run else "N/A"
        llm_s = f"{run['llm_ttf_ms']:.0f}" if "llm_ttf_ms" in run else "N/A"
        tts_s = f"{run['tts_ttf_ms']:.0f}" if "tts_ttf_ms" in run else "N/A"
        tot_s = f"{run.get('turn_duration_ms', 0):.0f}"
        print(f"    STT={stt_s}ms  LLM={llm_s}ms  TTS={tts_s}ms  Total={tot_s}ms")

    # Evaluate pass/fail against targets
    llm_vals = sorted(r["llm_ttf_ms"] for r in runs if "llm_ttf_ms" in r)
    tts_vals = sorted(r["tts_ttf_ms"] for r in runs if "tts_ttf_ms" in r)
    tot_vals = sorted(r["turn_duration_ms"] for r in runs if r.get("turn_duration_ms"))

    llm_p50 = _percentile(llm_vals, 50) if llm_vals else float("inf")
    tts_p50 = _percentile(tts_vals, 50) if tts_vals else float("inf")
    tot_p50 = _percentile(tot_vals, 50) if tot_vals else float("inf")

    passed = (
        llm_p50 < _PIPELINE_PASS_CRITERIA["llm_ttf_ms"]
        and tts_p50 < _PIPELINE_PASS_CRITERIA["tts_ttf_ms"]
    )
    print(f"\n  Pipeline p50 — STT={_percentile(sorted(r.get('stt_finish_ms', 0) for r in runs if r.get('stt_finish_ms')), 50):.0f}ms  LLM={llm_p50:.0f}ms  TTS={tts_p50:.0f}ms  Total={tot_p50:.0f}ms")
    print(f"  Pipeline pass criteria: LLM<{_PIPELINE_PASS_CRITERIA['llm_ttf_ms']:.0f}ms  TTS<{_PIPELINE_PASS_CRITERIA['tts_ttf_ms']:.0f}ms")
    print(f"  Pipeline verdict: {'PASS' if passed else 'FAIL'}")
    return runs, passed


def _run_pipeline_benchmark(settings: Any, num_runs: int = 5) -> tuple[list[dict], bool]:
    """Synchronous entry point: runs the async pipeline benchmark."""
    return asyncio.run(_run_pipeline_benchmark_async(settings, num_runs))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None):
    import argparse
    p = argparse.ArgumentParser(description="Run provider validation and/or pipeline benchmark.")
    p.add_argument("--runs", type=int, default=5, help="Number of pipeline benchmark runs (default: 5)")
    p.add_argument("--providers-only", action="store_true", help="Skip pipeline benchmark")
    p.add_argument("--pipeline-only", action="store_true", help="Skip provider validation")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Orchestrate provider validation + pipeline benchmark and write artifacts."""
    import sys as _sys

    # Ensure the backend package root is on the path when run as a module
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import settings

    args = _parse_args(argv)
    timestamp = datetime.now(timezone.utc).isoformat()
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(output_dir, exist_ok=True)

    provider_results = None
    provider_passed = True

    # --- Provider validation ---
    if not args.pipeline_only:
        from benchmarks.validate_providers import (
            validate_deepgram,
            validate_groq,
            validate_cartesia,
            validate_simli,
            validate_braintrust,
            validate_aiortc,
            ValidationResult,
            print_summary_table,
            save_results,
        )

        results: list[ValidationResult] = []
        asyncio.run(_run_providers(
            results,
            validate_deepgram,
            validate_groq,
            validate_cartesia,
            validate_simli,
            validate_braintrust,
            validate_aiortc,
        ))

        print_summary_table(results)
        prov_path = os.path.join(output_dir, "provider_validation.json")
        save_results(results, prov_path)

        passed_count = sum(1 for r in results if r.status == "PASS")
        total_count = len(results)
        provider_results = {
            "passed": passed_count,
            "total": total_count,
            "results": [
                {
                    "provider": r.provider,
                    "model": r.model,
                    "metric": r.metric,
                    "target": r.target,
                    "measured": r.measured,
                    "status": r.status,
                }
                for r in results
            ],
        }
        provider_passed = passed_count == total_count

    # --- Pipeline benchmark ---
    pipeline_runs: list[dict] = []
    pipeline_passed = False

    if not args.providers_only:
        pipeline_runs, pipeline_passed = _run_pipeline_benchmark(settings, num_runs=args.runs)

    # --- Write artifacts ---
    report = _write_benchmark_report(
        output_dir,
        provider_results=provider_results,
        pipeline_runs=pipeline_runs,
        pipeline_passed=pipeline_passed,
        timestamp=timestamp,
    )
    summary_path = _write_benchmark_summary(output_dir, report, provider_results, pipeline_passed)

    print(f"\nArtifacts written:")
    print(f"  {os.path.join(output_dir, 'benchmark_report.json')}")
    print(f"  {summary_path}")

    overall_ok = (args.pipeline_only or provider_passed) and (args.providers_only or pipeline_passed)
    if not overall_ok:
        sys.exit(1)


async def _run_providers(results, *validators):
    """Run all provider validators sequentially."""
    for validator in validators:
        await validator(results)


if __name__ == "__main__":
    main()
