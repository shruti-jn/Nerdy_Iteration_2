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

logger = logging.getLogger("tutor")


class BraintrustLogger:
    """Logs each tutoring turn to Braintrust with Socratic quality scores.
    Gracefully degrades: if BRAINTRUST_API_KEY is missing or init fails,
    all methods become no-ops."""

    def __init__(self) -> None:
        self._logger = None
        try:
            from braintrust import init_logger
            self._logger = init_logger(project="ai-video-tutor")
            logger.info("Braintrust logger initialized (project=ai-video-tutor)")
        except Exception as exc:
            logger.info("Braintrust not configured — per-turn scoring disabled: %s", exc)

    @property
    def is_enabled(self) -> bool:
        return self._logger is not None

    def log_turn(self, turn_data: Dict[str, Any]) -> Optional[str]:
        if self._logger is None:
            return None

        from observability.scorers import (
            score_ends_with_question, score_encouragement,
            score_no_direct_answer, score_no_negation,
            score_readability, score_response_length,
        )

        response: str = turn_data["tutor_response"]
        scores: Dict[str, float | int] = {
            "ends_with_question": score_ends_with_question(response),
            "no_direct_answer": score_no_direct_answer(turn_data),
            "no_negation": score_no_negation(turn_data),
            "readability": score_readability(response),
            "encouragement": score_encouragement(response),
            "response_length": score_response_length(response),
        }
        metadata: Dict[str, Any] = {
            "topic": turn_data.get("topic", ""),
            "turn_number": turn_data.get("turn_number", 0),
            "orchestrator": turn_data.get("orchestrator", "unknown"),
            "latency": turn_data.get("latency", {}),
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
