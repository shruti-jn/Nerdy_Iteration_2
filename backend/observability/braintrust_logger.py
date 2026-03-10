"""
Braintrust evaluation logging for per-turn Socratic quality scores.
Pipeline stage: Infrastructure (observability)

Provides BraintrustLogger, which wraps the Braintrust SDK to log every
tutoring turn with structured input/output, six Socratic quality scores,
and latency metadata.  Scorer functions are imported from
observability.scorers (built in parallel).

Key exports:
    - BraintrustLogger: main class for per-turn eval logging
"""

from __future__ import annotations

from typing import Any, Dict

from braintrust import init_logger

from observability.scorers import (
    score_ends_with_question,
    score_encouragement,
    score_no_direct_answer,
    score_no_negation,
    score_readability,
    score_response_length,
)


class BraintrustLogger:
    """Logs each tutoring turn to Braintrust with Socratic quality scores.

    On initialisation the logger connects to the ``ai-video-tutor`` project
    (creating it if necessary).  Each call to :meth:`log_turn` evaluates the
    tutor's response against six scoring dimensions and ships the results to
    Braintrust for analysis.

    Attributes:
        logger: The underlying ``braintrust.Logger`` instance.
    """

    def __init__(self) -> None:
        """Initialise the Braintrust logger for the ai-video-tutor project.

        Reads the BRAINTRUST_API_KEY from the environment automatically.
        """
        self.logger = init_logger(project="ai-video-tutor")

    def log_turn(self, turn_data: Dict[str, Any]) -> str:
        """Log a single tutoring turn with scores and metadata.

        Evaluates the tutor response against all six scoring dimensions
        and sends a structured log event to Braintrust.

        Args:
            turn_data: A dict containing at minimum:
                - student_input (str): what the student said / asked.
                - tutor_response (str): the tutor's reply.
                - topic (str): the lesson topic.
                - turn_number (int): ordinal turn index in the session.
                - orchestrator (str): orchestrator type ("custom" | "livekit").
                - latency (dict): per-stage latency measurements with keys
                  stt_ms, llm_ttft_ms, tts_ms, avatar_ms, total_ms.

        Returns:
            The Braintrust event ID for the logged row.

        Side effects:
            Calls each scorer function and sends a log event to Braintrust.
        """
        response: str = turn_data["tutor_response"]

        # -- Compute all six scoring dimensions --
        scores: Dict[str, float | int] = {
            "ends_with_question": score_ends_with_question(response),
            "no_direct_answer": score_no_direct_answer(turn_data),
            "no_negation": score_no_negation(turn_data),
            "readability": score_readability(response),
            "encouragement": score_encouragement(response),
            "response_length": score_response_length(response),
        }

        # -- Assemble metadata --
        metadata: Dict[str, Any] = {
            "topic": turn_data.get("topic", ""),
            "turn_number": turn_data.get("turn_number", 0),
            "orchestrator": turn_data.get("orchestrator", "unknown"),
            "latency": turn_data.get("latency", {}),
        }

        # -- Ship to Braintrust --
        return self.logger.log(
            input=turn_data["student_input"],
            output=response,
            scores=scores,
            metadata=metadata,
        )
