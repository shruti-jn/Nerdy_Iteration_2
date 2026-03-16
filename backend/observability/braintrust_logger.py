"""
Braintrust evaluation logging for per-turn Socratic quality scores.
Pipeline stage: Infrastructure (observability)

Gracefully degrades when BRAINTRUST_API_KEY is not set — log_turn
becomes a no-op so callers never need to check.

Key exports:
    - BraintrustLogger: main class for per-turn eval logging
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    from braintrust import init_logger
except Exception:  # pragma: no cover - fallback for missing optional dependency
    def init_logger(*args, **kwargs):
        raise RuntimeError("braintrust is not installed")
from observability.scorers import (
    score_ends_with_question,
    score_encouragement,
    score_no_direct_answer,
    score_no_negation,
    score_readability,
    score_response_length,
)

logger = logging.getLogger("tutor")


class BraintrustLogger:
    """Logs each tutoring turn to Braintrust with Socratic quality scores.
    Gracefully degrades: if BRAINTRUST_API_KEY is missing or init fails,
    all methods become no-ops."""

    def __init__(self) -> None:
        self._logger = None
        try:
            self._logger = init_logger(project="ai-video-tutor")
            logger.info("Braintrust logger initialized (project=ai-video-tutor)")
        except Exception as exc:
            logger.info("Braintrust not configured — per-turn scoring disabled: %s", exc)

    @property
    def logger(self):
        return self._logger

    @property
    def is_enabled(self) -> bool:
        return self._logger is not None

    def log_turn(self, turn_data: Dict[str, Any]) -> Optional[str]:
        if self._logger is None:
            return None

        response: str = turn_data["tutor_response"]
        response_word_count = score_response_length(response)
        readability_raw = score_readability(response)
        readability_score = (
            readability_raw
            if 0.0 <= float(readability_raw) <= 1.0
            else (1.0 if 4.0 <= float(readability_raw) <= 9.0 else 0.0)
        )

        scores: Dict[str, float | int] = {
            "ends_with_question": score_ends_with_question(response),
            "no_direct_answer": score_no_direct_answer(turn_data),
            "no_negation": score_no_negation(turn_data),
            "readability": readability_score,
            "encouragement": score_encouragement(response),
            # Braintrust expects score values in [0, 1]; keep raw count in metadata.
            "response_length": 1.0 if response_word_count <= 50 else 0.0,
        }
        token_counts: Dict[str, Any] = turn_data.get("token_counts") or {}
        metadata: Dict[str, Any] = {
            "topic": turn_data.get("topic", ""),
            "turn_number": turn_data.get("turn_number", 0),
            "orchestrator": turn_data.get("orchestrator", "unknown"),
            "avatar_mode": turn_data.get("avatar_mode", "unknown"),
            "latency": turn_data.get("latency", {}),
            "response_word_count": response_word_count,
            "readability_raw": readability_raw,
            "prompt_tokens": token_counts.get("prompt_tokens", 0),
            "completion_tokens": token_counts.get("completion_tokens", 0),
            "total_tokens": token_counts.get("total_tokens", 0),
        }
        try:
            return self._logger.log(
                input=turn_data["student_input"], output=response,
                scores=scores, metadata=metadata,
            )
        except Exception as exc:
            logger.warning("braintrust_log_failed turn=%s error=%s",
                           turn_data.get("turn_number", "?"), exc)
            return None
