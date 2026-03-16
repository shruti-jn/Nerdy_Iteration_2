"""
Tests for the observability layer: Logfire tracing and Braintrust eval logging.
Pipeline stage: Infrastructure (observability)

Tests are written TDD-style — all external services (Logfire, Braintrust) are
mocked so no real API calls are made.
"""

from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Logfire setup tests
# ---------------------------------------------------------------------------


class TestLogfireSetup:
    """Tests for observability.logfire_setup module."""

    @patch("observability.logfire_setup.logfire")
    def test_setup_logfire_does_not_crash(self, mock_logfire):
        """setup_logfire should call logfire.configure() and
        logfire.instrument_fastapi(app) without raising."""
        from observability.logfire_setup import setup_logfire

        mock_app = MagicMock()
        # Should not raise
        setup_logfire(mock_app)

        mock_logfire.configure.assert_called_once()
        mock_logfire.instrument_fastapi.assert_called_once_with(mock_app)

    @patch("observability.logfire_setup.logfire")
    def test_create_span_returns_context_manager(self, mock_logfire):
        """create_span should return a context manager wrapping logfire.span()
        and forward standard attributes."""
        from observability.logfire_setup import create_span

        mock_span = MagicMock()
        mock_logfire.span.return_value = mock_span

        attributes = {"stage": "stt", "provider": "deepgram", "run_id": "abc-123"}
        result = create_span("stt_transcribe", attributes)

        # Should delegate to logfire.span with the name and attributes
        mock_logfire.span.assert_called_once_with(
            "stt_transcribe",
            stage="stt",
            provider="deepgram",
            run_id="abc-123",
        )
        assert result is mock_span

    @patch("observability.logfire_setup.logfire")
    def test_create_span_with_empty_attributes(self, mock_logfire):
        """create_span should work when no extra attributes are given."""
        from observability.logfire_setup import create_span

        mock_span = MagicMock()
        mock_logfire.span.return_value = mock_span

        result = create_span("idle_check", {})
        mock_logfire.span.assert_called_once_with("idle_check")
        assert result is mock_span


# ---------------------------------------------------------------------------
# Braintrust logger tests
# ---------------------------------------------------------------------------


class TestBraintrustLoggerInit:
    """Tests for BraintrustLogger initialization."""

    @patch("observability.braintrust_logger.init_logger")
    def test_braintrust_logger_initializes(self, mock_init_logger):
        """BraintrustLogger.__init__ should call init_logger with the correct
        project name and store the returned logger."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger()

        mock_init_logger.assert_called_once_with(project="ai-video-tutor")
        assert bt.logger is mock_logger

    @patch("observability.braintrust_logger.init_logger")
    def test_braintrust_logger_passes_api_key_when_provided(self, mock_init_logger):
        """BraintrustLogger should forward an explicit API key to init_logger."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger(api_key="bt-test-key")

        mock_init_logger.assert_called_once_with(
            project="ai-video-tutor",
            api_key="bt-test-key",
        )
        assert bt.logger is mock_logger


class TestBraintrustLogTurn:
    """Tests for BraintrustLogger.log_turn."""

    @patch("observability.braintrust_logger.score_response_length", return_value=42)
    @patch("observability.braintrust_logger.score_encouragement", return_value=0.8)
    @patch("observability.braintrust_logger.score_readability", return_value=0.75)
    @patch("observability.braintrust_logger.score_no_negation", return_value=1.0)
    @patch("observability.braintrust_logger.score_no_direct_answer", return_value=0.9)
    @patch("observability.braintrust_logger.score_ends_with_question", return_value=1.0)
    @patch("observability.braintrust_logger.init_logger")
    def test_log_turn_calls_logger_log_with_correct_structure(
        self,
        mock_init_logger,
        mock_ewq,
        mock_nda,
        mock_nn,
        mock_read,
        mock_enc,
        mock_rlen,
    ):
        """log_turn should call logger.log() with input, output, scores, and
        metadata extracted from turn_data."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger()

        turn_data = {
            "student_input": "Why does ice float?",
            "tutor_response": "What do you know about density?",
            "topic": "states of matter",
            "turn_number": 3,
            "orchestrator": "custom",
            "avatar_mode": "simli_sdk",
            "token_counts": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
            "latency": {
                "stt_ms": 120,
                "llm_ttft_ms": 180,
                "tts_ms": 140,
                "avatar_ms": 90,
                "total_ms": 530,
            },
        }

        bt.log_turn(turn_data)

        mock_logger.log.assert_called_once()
        call_kwargs = mock_logger.log.call_args[1]

        # Verify input/output
        assert call_kwargs["input"] == "Why does ice float?"
        assert call_kwargs["output"] == "What do you know about density?"

        # Verify scores dict has all 6 scoring dimensions
        scores = call_kwargs["scores"]
        assert scores["ends_with_question"] == 1.0
        assert scores["no_direct_answer"] == 0.9
        assert scores["no_negation"] == 1.0
        assert scores["readability"] == 0.75
        assert scores["encouragement"] == 0.8
        assert scores["response_length"] == 1.0

        # Verify metadata
        metadata = call_kwargs["metadata"]
        assert metadata["topic"] == "states of matter"
        assert metadata["turn_number"] == 3
        assert metadata["orchestrator"] == "custom"
        assert metadata["avatar_mode"] == "simli_sdk"
        assert metadata["latency"]["stt_ms"] == 120
        assert metadata["latency"]["total_ms"] == 530
        assert metadata["response_word_count"] == 42
        assert metadata["prompt_tokens"] == 120
        assert metadata["completion_tokens"] == 45
        assert metadata["total_tokens"] == 165

    @patch("observability.braintrust_logger.score_response_length", return_value=10)
    @patch("observability.braintrust_logger.score_encouragement", return_value=0.5)
    @patch("observability.braintrust_logger.score_readability", return_value=0.6)
    @patch("observability.braintrust_logger.score_no_negation", return_value=1.0)
    @patch("observability.braintrust_logger.score_no_direct_answer", return_value=1.0)
    @patch("observability.braintrust_logger.score_ends_with_question", return_value=1.0)
    @patch("observability.braintrust_logger.init_logger")
    def test_braintrust_scores_computed_all_six(
        self,
        mock_init_logger,
        mock_ewq,
        mock_nda,
        mock_nn,
        mock_read,
        mock_enc,
        mock_rlen,
    ):
        """All 6 scoring dimensions must be present in the logged scores."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger()

        turn_data = {
            "student_input": "What is gravity?",
            "tutor_response": "Can you think of an example where gravity pulls things down?",
            "topic": "physics",
            "turn_number": 1,
            "orchestrator": "custom",
            "latency": {
                "stt_ms": 100,
                "llm_ttft_ms": 150,
                "tts_ms": 130,
                "avatar_ms": 80,
                "total_ms": 460,
            },
        }

        bt.log_turn(turn_data)

        call_kwargs = mock_logger.log.call_args[1]
        scores = call_kwargs["scores"]

        expected_keys = {
            "ends_with_question",
            "no_direct_answer",
            "no_negation",
            "readability",
            "encouragement",
            "response_length",
        }
        assert set(scores.keys()) == expected_keys

    @patch("observability.braintrust_logger.score_response_length", return_value=10)
    @patch("observability.braintrust_logger.score_encouragement", return_value=0.5)
    @patch("observability.braintrust_logger.score_readability", return_value=0.6)
    @patch("observability.braintrust_logger.score_no_negation", return_value=1.0)
    @patch("observability.braintrust_logger.score_no_direct_answer", return_value=1.0)
    @patch("observability.braintrust_logger.score_ends_with_question", return_value=1.0)
    @patch("observability.braintrust_logger.init_logger")
    def test_log_turn_defaults_avatar_mode_and_token_counts_when_absent(
        self,
        mock_init_logger,
        mock_ewq,
        mock_nda,
        mock_nn,
        mock_read,
        mock_enc,
        mock_rlen,
    ):
        """log_turn must use 'unknown' for avatar_mode and 0 for token counts
        when those keys are absent from turn_data (backwards compatibility)."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger()

        turn_data = {
            "student_input": "Hello?",
            "tutor_response": "What do you think?",
            "topic": "chemistry",
            "turn_number": 1,
            "orchestrator": "custom",
            # intentionally omit avatar_mode and token_counts
            "latency": {"total_ms": 400},
        }

        bt.log_turn(turn_data)

        call_kwargs = mock_logger.log.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["avatar_mode"] == "unknown"
        assert metadata["prompt_tokens"] == 0
        assert metadata["completion_tokens"] == 0
        assert metadata["total_tokens"] == 0

    @patch("observability.braintrust_logger.score_response_length", return_value=15)
    @patch("observability.braintrust_logger.score_encouragement", return_value=0.7)
    @patch("observability.braintrust_logger.score_readability", return_value=0.8)
    @patch("observability.braintrust_logger.score_no_negation", return_value=0.5)
    @patch("observability.braintrust_logger.score_no_direct_answer", return_value=0.6)
    @patch("observability.braintrust_logger.score_ends_with_question", return_value=0.0)
    @patch("observability.braintrust_logger.init_logger")
    def test_log_turn_passes_turn_dict_to_turn_scorers(
        self,
        mock_init_logger,
        mock_ewq,
        mock_nda,
        mock_nn,
        mock_read,
        mock_enc,
        mock_rlen,
    ):
        """Scorers that take a turn dict (no_direct_answer, no_negation) should
        receive the full turn_data dict; scorers that take a string should
        receive tutor_response."""
        mock_logger = MagicMock()
        mock_init_logger.return_value = mock_logger

        from observability.braintrust_logger import BraintrustLogger

        bt = BraintrustLogger()

        turn_data = {
            "student_input": "Is 2+2=5?",
            "tutor_response": "Let us count together. What is 2+2?",
            "topic": "arithmetic",
            "turn_number": 2,
            "orchestrator": "custom",
            "latency": {"stt_ms": 100, "llm_ttft_ms": 150, "tts_ms": 130, "avatar_ms": 80, "total_ms": 460},
        }

        bt.log_turn(turn_data)

        # String-based scorers receive the tutor_response text
        mock_ewq.assert_called_once_with("Let us count together. What is 2+2?")
        mock_read.assert_called_once_with("Let us count together. What is 2+2?")
        mock_enc.assert_called_once_with("Let us count together. What is 2+2?")
        mock_rlen.assert_called_once_with("Let us count together. What is 2+2?")

        # Turn-dict-based scorers receive the full turn_data dict
        mock_nda.assert_called_once_with(turn_data)
        mock_nn.assert_called_once_with(turn_data)
