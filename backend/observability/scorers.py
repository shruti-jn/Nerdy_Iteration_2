"""
Scoring functions for Socratic tutoring quality.

Pipeline stage: Observability (shared by Braintrust eval logging and pytest TDD).

These scorers quantify how well the AI tutor follows Socratic teaching
principles: asking guiding questions, avoiding direct answers, using
encouraging language, and maintaining grade-appropriate readability.

Consumed by:
  - observability/braintrust_logger.py  (production per-turn scoring)
  - tests/test_scorers.py              (TDD quality assertions)
"""

from __future__ import annotations

import re

import textstat


# ---------------------------------------------------------------------------
# Forbidden-phrase lists (lowercased for case-insensitive matching)
# ---------------------------------------------------------------------------

_DIRECT_ANSWER_PHRASES: list[str] = [
    "the answer is",
    "actually, it's",
    "the correct answer",
    "photosynthesis is when",
    "photosynthesis is the process",
    "newton's law states",
    "newton's first law is",
    "the formula is",
    "the equation is",
]

_NEGATION_PHRASES: list[str] = [
    "no,",
    "no.",
    "wrong",
    "incorrect",
    "that's not right",
    "not quite",
    "that is not",
]

_ENCOURAGEMENT_PHRASES: list[str] = [
    "nice",
    "great",
    "good thinking",
    "interesting",
    "you're getting",
    "close",
    "exactly",
    "awesome",
    "love that",
    "ooh",
    "yes!",
    "right!",
]


# ---------------------------------------------------------------------------
# 1. score_ends_with_question
# ---------------------------------------------------------------------------


def score_ends_with_question(response: str) -> float:
    """Check whether the tutor response ends with a question mark.

    Almost every Socratic response should end with a guiding question.

    Args:
        response: The tutor's response text.

    Returns:
        1.0 if the stripped response ends with '?', else 0.0.
    """
    return 1.0 if response.strip().endswith("?") else 0.0


# ---------------------------------------------------------------------------
# 2. score_no_direct_answer
# ---------------------------------------------------------------------------


def score_no_direct_answer(turn: dict) -> float:
    """Penalise responses that lecture or give away the answer directly.

    Args:
        turn: A dict with keys ``student_input``, ``tutor_response``, and
              ``topic``.

    Returns:
        0.0 if the response contains any forbidden direct-answer phrase,
        1.0 otherwise.
    """
    text = turn["tutor_response"].lower()
    for phrase in _DIRECT_ANSWER_PHRASES:
        if phrase in text:
            return 0.0
    return 1.0


# ---------------------------------------------------------------------------
# 3. score_no_negation
# ---------------------------------------------------------------------------


def score_no_negation(turn: dict) -> float:
    """Penalise blunt negation — the tutor should redirect, not reject.

    Word-boundary checks prevent false positives on words like *know*,
    *now*, *innovation*, etc.

    Args:
        turn: A dict with keys ``student_input``, ``tutor_response``, and
              ``topic``.

    Returns:
        0.0 if the response contains a negation phrase, 1.0 otherwise.
    """
    text = turn["tutor_response"].lower()

    for phrase in _NEGATION_PHRASES:
        # Build a regex that respects word boundaries.
        # Phrases ending with punctuation (e.g. "no," or "no.") already have
        # a natural boundary on the right, so we only enforce \b on the left.
        # For all-alpha phrases we enforce \b on both sides.
        if phrase[-1].isalpha():
            pattern = r"\b" + re.escape(phrase) + r"\b"
        else:
            pattern = r"\b" + re.escape(phrase)

        if re.search(pattern, text):
            return 0.0

    return 1.0


# ---------------------------------------------------------------------------
# 4. score_readability
# ---------------------------------------------------------------------------


def score_readability(response: str) -> float:
    """Return the Flesch-Kincaid grade level of the response.

    A grade level between ~4 and ~9 is appropriate for 6th-12th graders
    when using a conversational Socratic style.

    Args:
        response: The tutor's response text.

    Returns:
        The Flesch-Kincaid grade level as a float.
    """
    return float(textstat.flesch_kincaid_grade(response))


# ---------------------------------------------------------------------------
# 5. score_encouragement
# ---------------------------------------------------------------------------


def score_encouragement(response: str) -> float:
    """Detect whether the tutor uses encouraging / affirming language.

    Args:
        response: The tutor's response text.

    Returns:
        1.0 if any encouragement phrase is present (case-insensitive),
        0.0 otherwise.
    """
    text = response.lower()
    for phrase in _ENCOURAGEMENT_PHRASES:
        if phrase in text:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# 6. score_response_length
# ---------------------------------------------------------------------------


def score_response_length(response: str) -> int:
    """Return the word count of the response.

    Useful for monitoring verbosity — overly long responses hurt latency
    and can drift into lecturing.

    Args:
        response: The tutor's response text.

    Returns:
        The number of whitespace-delimited words.
    """
    return len(response.split())
