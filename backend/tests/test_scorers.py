"""
TDD tests for Socratic tutoring scoring functions.

Pipeline stage: Testing (validates observability/scorers.py).

These tests are written *first* (TDD style) and exercise every scorer
against representative tutoring turns provided by conftest.py fixtures.
"""

from __future__ import annotations

import pytest

from observability.scorers import (
    score_encouragement,
    score_ends_with_question,
    score_no_direct_answer,
    score_no_negation,
    score_readability,
    score_response_length,
)


# ---------------------------------------------------------------------------
# 1. score_ends_with_question
# ---------------------------------------------------------------------------


class TestEndsWithQuestion:
    """Verify that the scorer detects trailing question marks correctly."""

    def test_ends_with_question_positive(self) -> None:
        """A response ending with '?' should score 1.0."""
        assert score_ends_with_question("What do you think?") == 1.0

    def test_ends_with_question_negative(self) -> None:
        """A declarative response should score 0.0."""
        assert score_ends_with_question("That's correct.") == 0.0

    def test_ends_with_question_trailing_whitespace(self) -> None:
        """Trailing whitespace after '?' should not affect the result."""
        assert score_ends_with_question("What do you think?  ") == 1.0

    def test_ends_with_question_hint_after_question(self) -> None:
        """Model appends 'Hint: look up!' after the question — should still score 1.0."""
        assert score_ends_with_question(
            "Where does sunlight come from to make food? Hint: look up!"
        ) == 1.0

    def test_ends_with_question_no_question_at_all(self) -> None:
        """No '?' anywhere near the end should score 0.0."""
        assert score_ends_with_question(
            "Plants use sunlight, water, and carbon dioxide. That is photosynthesis."
        ) == 0.0

    def test_ends_with_question_question_far_from_end(self) -> None:
        """A '?' only at the very start, with a long declarative tail, scores 0.0."""
        assert score_ends_with_question(
            "?" + "x" * 80 + " That is the answer and it ends here."
        ) == 0.0


# ---------------------------------------------------------------------------
# 2. score_no_direct_answer
# ---------------------------------------------------------------------------


class TestNoDirectAnswer:
    """Verify that lecturing / giving away answers is penalised."""

    def test_no_direct_answer_clean(self, sample_turn_correct: dict) -> None:
        """A proper Socratic response should score 1.0."""
        assert score_no_direct_answer(sample_turn_correct) == 1.0

    def test_no_direct_answer_lecture(self, sample_turn_lecture: dict) -> None:
        """A lecture that states 'photosynthesis is the process' should score 0.0."""
        assert score_no_direct_answer(sample_turn_lecture) == 0.0

    def test_no_direct_answer_explicit_answer(self) -> None:
        """An explicit 'the answer is' phrasing should score 0.0."""
        turn = {
            "student_input": "What is 2+2?",
            "tutor_response": "The answer is 4.",
            "topic": "math",
        }
        assert score_no_direct_answer(turn) == 0.0


class TestNoDirectAnswerTeacherMode:
    """Verify Teacher Mode tolerance in the no-direct-answer scorer."""

    def test_teacher_mode_allows_direct_answer(self) -> None:
        """When teacher_mode=True, direct explanations should score 1.0."""
        turn = {
            "student_input": "I don't know",
            "tutor_response": "Photosynthesis is the process where plants use sunlight to make food. What ingredient comes from the sky?",
            "topic": "photosynthesis",
            "teacher_mode": True,
        }
        assert score_no_direct_answer(turn) == 1.0

    def test_teacher_mode_false_still_penalizes(self) -> None:
        """When teacher_mode=False, direct explanations should score 0.0."""
        turn = {
            "student_input": "I don't know",
            "tutor_response": "Photosynthesis is the process by which plants make food.",
            "topic": "photosynthesis",
            "teacher_mode": False,
        }
        assert score_no_direct_answer(turn) == 0.0

    def test_teacher_mode_absent_defaults_to_penalty(self) -> None:
        """When teacher_mode key is absent, direct answers are penalized (backward compat)."""
        turn = {
            "student_input": "How do plants eat?",
            "tutor_response": "The answer is that they photosynthesize.",
            "topic": "photosynthesis",
        }
        assert score_no_direct_answer(turn) == 0.0


# ---------------------------------------------------------------------------
# 3. score_no_negation
# ---------------------------------------------------------------------------


class TestNoNegation:
    """Verify that blunt negation is caught without false positives."""

    def test_no_negation_clean(self, sample_turn_wrong: dict) -> None:
        """A redirect without saying 'no' should score 1.0."""
        assert score_no_negation(sample_turn_wrong) == 1.0

    def test_no_negation_caught(self) -> None:
        """A blunt 'No, that's wrong' should score 0.0."""
        turn = {
            "student_input": "Is it the mitochondria?",
            "tutor_response": "No, that's wrong. Think again.",
            "topic": "photosynthesis",
        }
        assert score_no_negation(turn) == 0.0

    def test_no_negation_no_false_positive(self) -> None:
        """The word 'know' contains 'no' but must NOT trigger a false positive."""
        turn = {
            "student_input": "I'm not sure.",
            "tutor_response": "Do you know what happens next?",
            "topic": "photosynthesis",
        }
        assert score_no_negation(turn) == 1.0

    def test_no_negation_incorrect_caught(self) -> None:
        """The word 'incorrect' as a standalone word should score 0.0."""
        turn = {
            "student_input": "Is it 5?",
            "tutor_response": "That's incorrect, try again.",
            "topic": "math",
        }
        assert score_no_negation(turn) == 0.0

    def test_no_negation_now_not_false_positive(self) -> None:
        """The word 'now' contains 'no' but must NOT trigger a false positive."""
        turn = {
            "student_input": "What next?",
            "tutor_response": "Now, what do you think happens?",
            "topic": "photosynthesis",
        }
        assert score_no_negation(turn) == 1.0


# ---------------------------------------------------------------------------
# 4. score_readability
# ---------------------------------------------------------------------------


class TestReadability:
    """Verify that readability scoring returns grade-appropriate levels."""

    def test_readability_range(self) -> None:
        """A typical Socratic response should be between grade 4.0 and 9.0."""
        response = (
            "That's a great observation! What do you think happens when "
            "sunlight hits the green pigment inside the leaf?"
        )
        grade = score_readability(response)
        assert 4.0 <= grade <= 9.0, (
            f"Expected grade level between 4.0 and 9.0, got {grade}"
        )

    def test_readability_returns_float(self) -> None:
        """The return type must be float."""
        result = score_readability("What do you think about that?")
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# 5. score_encouragement
# ---------------------------------------------------------------------------


class TestEncouragement:
    """Verify detection of encouraging / affirming language."""

    def test_encouragement_present(self, sample_turn_correct: dict) -> None:
        """The sample correct turn contains 'Nice thinking' and should score 1.0."""
        assert score_encouragement(sample_turn_correct["tutor_response"]) == 1.0

    def test_encouragement_absent(self) -> None:
        """A clinical response with no warmth should score 0.0."""
        response = "Consider the relationship between the two variables."
        assert score_encouragement(response) == 0.0

    def test_encouragement_case_insensitive(self) -> None:
        """Encouragement detection should be case-insensitive."""
        assert score_encouragement("GREAT question!") == 1.0


# ---------------------------------------------------------------------------
# 6. score_response_length
# ---------------------------------------------------------------------------


class TestResponseLength:
    """Verify word count calculation."""

    def test_response_length(self) -> None:
        """'What do you think about that?' has 6 words."""
        assert score_response_length("What do you think about that?") == 6

    def test_response_length_empty(self) -> None:
        """An empty string should return 0 words."""
        assert score_response_length("") == 0

    def test_response_length_single_word(self) -> None:
        """A single word should return 1."""
        assert score_response_length("Hello") == 1
