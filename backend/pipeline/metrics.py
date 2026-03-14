"""
Metrics collector for per-stage and end-to-end latency tracking.

Provides nanosecond-precision timing for each pipeline stage (STT, LLM,
TTS, Avatar) and the overall turn. Uses ``time.monotonic_ns()`` for
monotonic, high-resolution measurements unaffected by wall-clock drift.

Pipeline stage: Infrastructure (shared by all stages)

Exports:
    StageMetrics     -- Per-stage timing dataclass
    MetricsCollector -- Turn-level metrics aggregator
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StageMetrics:
    """Timing data for a single pipeline stage.

    For stages invoked multiple times per turn (e.g. TTS called per
    sentence), ``first_start_ns`` / ``first_token_ns`` capture the *first*
    invocation while ``start_ns`` / ``end_ns`` track the *latest* so
    ``duration_ms`` reflects the overall span.

    Attributes:
        stage:          Stage name (e.g. "stt", "llm", "tts", "avatar").
        first_start_ns: Monotonic timestamp of the very first start() call.
        start_ns:       Monotonic timestamp of the most recent start() call.
        first_token_ns: Monotonic timestamp of the first output token/byte
                        (write-once — never overwritten by later invocations).
        end_ns:         Monotonic timestamp when the stage last completed.
        invocations:    How many times start() was called (e.g. sentence count).
    """

    stage: str
    first_start_ns: Optional[int] = None
    start_ns: Optional[int] = None
    first_token_ns: Optional[int] = None
    end_ns: Optional[int] = None
    invocations: int = 0

    @property
    def duration_ms(self) -> Optional[float]:
        """Total stage duration (first start → last end) in ms, or None."""
        if self.first_start_ns is not None and self.end_ns is not None:
            return (self.end_ns - self.first_start_ns) / 1_000_000
        return None

    @property
    def time_to_first_ms(self) -> Optional[float]:
        """Time from first start to first token/byte in ms, or None."""
        if self.first_start_ns is not None and self.first_token_ns is not None:
            return (self.first_token_ns - self.first_start_ns) / 1_000_000
        return None

    @property
    def last_invocation_ms(self) -> Optional[float]:
        """Duration of the most recent invocation (latest start → end)."""
        if self.start_ns is not None and self.end_ns is not None:
            return (self.end_ns - self.start_ns) / 1_000_000
        return None


class MetricsCollector:
    """Collects per-stage and turn-level latency metrics.

    One instance per pipeline turn. Not thread-safe — each turn creates
    its own collector.

    Usage::

        mc = MetricsCollector()
        mc.start_turn()
        mc.start("llm")
        mc.mark_first("llm")
        mc.end("llm")
        mc.end_turn()
        print(mc.to_dict())
    """

    def __init__(self) -> None:
        self._stages: dict[str, StageMetrics] = {}
        self._turn_start_ns: Optional[int] = None
        self._turn_end_ns: Optional[int] = None

    # -- Turn-level timing ---------------------------------------------------

    def start_turn(self) -> None:
        """Record the start of a pipeline turn."""
        self._turn_start_ns = time.monotonic_ns()

    def end_turn(self) -> None:
        """Record the end of a pipeline turn."""
        self._turn_end_ns = time.monotonic_ns()

    @property
    def turn_duration_ms(self) -> Optional[float]:
        """Total turn duration in milliseconds, or None if incomplete."""
        if self._turn_start_ns is not None and self._turn_end_ns is not None:
            return (self._turn_end_ns - self._turn_start_ns) / 1_000_000
        return None

    # -- Stage-level timing --------------------------------------------------

    def _ensure_stage(self, stage: str) -> StageMetrics:
        """Get or create a StageMetrics entry for the named stage."""
        if stage not in self._stages:
            self._stages[stage] = StageMetrics(stage=stage)
        return self._stages[stage]

    def start(self, stage: str) -> None:
        """Record that a pipeline stage has begun processing.

        Safe to call multiple times (e.g. TTS per sentence). The first
        call is preserved in ``first_start_ns``; subsequent calls only
        update ``start_ns`` so ``last_invocation_ms`` stays accurate.

        Args:
            stage: Stage identifier (e.g. "stt", "llm", "tts", "avatar").
        """
        sm = self._ensure_stage(stage)
        now = time.monotonic_ns()
        if sm.first_start_ns is None:
            sm.first_start_ns = now
        sm.start_ns = now
        sm.invocations += 1

    def mark_first(self, stage: str) -> None:
        """Record the arrival of the first output token/byte for a stage.

        Write-once: only the *first* call takes effect. Subsequent calls
        (e.g. TTS for sentence 2+) are no-ops so the metric reflects the
        true time-to-first for the user.

        Args:
            stage: Stage identifier.
        """
        sm = self._ensure_stage(stage)
        if sm.first_token_ns is None:
            sm.first_token_ns = time.monotonic_ns()

    def end(self, stage: str) -> None:
        """Record that a pipeline stage has completed.

        Args:
            stage: Stage identifier.
        """
        sm = self._ensure_stage(stage)
        sm.end_ns = time.monotonic_ns()

    def get_stage(self, stage: str) -> Optional[StageMetrics]:
        """Return the StageMetrics for a stage, or None if not tracked.

        Args:
            stage: Stage identifier.

        Returns:
            The StageMetrics instance, or None.
        """
        return self._stages.get(stage)

    def to_dict(self) -> dict:
        """Export all metrics as a flat dictionary for structured logging.

        Keys follow the convention:
            ``{stage}_ttf_ms``       — time-to-first for the stage
            ``{stage}_duration_ms``  — total duration (first start → last end)
            ``{stage}_invocations``  — how many times the stage was invoked
            ``turn_duration_ms``     — total turn duration

        Returns:
            dict with string keys and float/None values.
        """
        result: dict = {}
        for name, sm in self._stages.items():
            result[f"{name}_ttf_ms"] = sm.time_to_first_ms
            result[f"{name}_duration_ms"] = sm.duration_ms
            result[f"{name}_invocations"] = sm.invocations
        result["turn_duration_ms"] = self.turn_duration_ms
        return result
