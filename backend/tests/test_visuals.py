"""
Tests for the visual step registry.

Validates step-tag parsing, per-topic visual lookups (including clamping),
recap visuals, total-step counts, and the WebSocket message serialiser.

Pipeline stage: Orchestration (visual payload generation)
"""

import pytest

from prompts.visuals import (
    VisualStep,
    get_recap_visual,
    get_total_steps,
    get_visual_for_step,
    parse_step_tag,
    visual_to_message,
)


# ---------------------------------------------------------------------------
# parse_step_tag
# ---------------------------------------------------------------------------


class TestParseStepTag:
    """Tests for [STEP:N] tag extraction from raw LLM output."""

    def test_parses_valid_tag(self):
        """Extracts step number and strips tag from text."""
        step_id, text = parse_step_tag("[STEP:3] Great question!")
        assert step_id == 3
        assert text == "Great question!"

    def test_no_tag_returns_none(self):
        """Returns (None, original_text) when no tag is present."""
        step_id, text = parse_step_tag("No tag here")
        assert step_id is None
        assert text == "No tag here"

    def test_step_zero(self):
        """Handles step 0 and strips leading whitespace after tag."""
        step_id, text = parse_step_tag("[STEP:0]  Leading spaces")
        assert step_id == 0
        assert text == "Leading spaces"

    def test_tag_with_newline(self):
        r"""Newline after tag is consumed as whitespace by \s*."""
        step_id, text = parse_step_tag("[STEP:2]\nSome text")
        assert step_id == 2
        assert text == "Some text"

    def test_tag_not_at_start(self):
        """Tag must appear at position 0; mid-string tags are ignored."""
        step_id, text = parse_step_tag("Hello [STEP:1] world")
        assert step_id is None
        assert text == "Hello [STEP:1] world"

    def test_large_step_number(self):
        """Handles multi-digit step numbers."""
        step_id, text = parse_step_tag("[STEP:99] text")
        assert step_id == 99
        assert text == "text"


# ---------------------------------------------------------------------------
# get_visual_for_step
# ---------------------------------------------------------------------------


class TestGetVisualForStep:
    """Tests for per-topic, per-step visual lookups."""

    def test_photosynthesis_step_0(self):
        """Step 0 for photosynthesis is 'The Hook'."""
        vs = get_visual_for_step("photosynthesis", 0)
        assert vs is not None
        assert vs.step_id == 0
        assert vs.step_label == "The Hook"

    def test_photosynthesis_step_6(self):
        """Step 6 for photosynthesis is 'Teach-Back'."""
        vs = get_visual_for_step("photosynthesis", 6)
        assert vs is not None
        assert vs.step_id == 6
        assert vs.step_label == "Teach-Back"

    def test_photosynthesis_clamps_high(self):
        """Out-of-range step_id is clamped to last valid step."""
        vs = get_visual_for_step("photosynthesis", 99)
        assert vs is not None
        assert vs.step_id == 6
        assert vs.step_label == "Teach-Back"

    def test_photosynthesis_clamps_negative(self):
        """Negative step_id is clamped to 0."""
        vs = get_visual_for_step("photosynthesis", -1)
        assert vs is not None
        assert vs.step_id == 0
        assert vs.step_label == "The Hook"

    def test_newtons_laws_step_0(self):
        """Step 0 for newtons_laws is 'The Hook'."""
        vs = get_visual_for_step("newtons_laws", 0)
        assert vs is not None
        assert vs.step_id == 0
        assert vs.step_label == "The Hook"

    def test_newtons_laws_step_7(self):
        """Step 7 for newtons_laws is 'Teach-Back'."""
        vs = get_visual_for_step("newtons_laws", 7)
        assert vs is not None
        assert vs.step_id == 7
        assert vs.step_label == "Teach-Back"

    def test_unknown_topic_returns_none(self):
        """An unrecognised topic returns None."""
        assert get_visual_for_step("unknown", 0) is None

    def test_all_steps_have_nonempty_emoji(self):
        """Every registered step across all topics has a non-empty emoji_diagram."""
        for topic in ("photosynthesis", "newtons_laws"):
            total = get_total_steps(topic)
            for step_id in range(total):
                vs = get_visual_for_step(topic, step_id)
                assert vs is not None, f"{topic} step {step_id} returned None"
                assert vs.emoji_diagram, (
                    f"{topic} step {step_id} has empty emoji_diagram"
                )


# ---------------------------------------------------------------------------
# get_recap_visual
# ---------------------------------------------------------------------------


class TestGetRecapVisual:
    """Tests for end-of-session recap visuals."""

    def test_photosynthesis_recap(self):
        """Photosynthesis recap has step_id=-1 and non-empty emoji_diagram."""
        recap = get_recap_visual("photosynthesis")
        assert recap is not None
        assert recap.step_id == -1
        assert recap.emoji_diagram  # non-empty

    def test_newtons_laws_recap(self):
        """Newton's Laws recap has step_id=-1 and non-empty emoji_diagram."""
        recap = get_recap_visual("newtons_laws")
        assert recap is not None
        assert recap.step_id == -1
        assert recap.emoji_diagram  # non-empty

    def test_unknown_topic_recap(self):
        """An unrecognised topic returns None."""
        assert get_recap_visual("unknown") is None


# ---------------------------------------------------------------------------
# get_total_steps
# ---------------------------------------------------------------------------


class TestGetTotalSteps:
    """Tests for total curriculum step counts."""

    def test_photosynthesis(self):
        """Photosynthesis has 7 curriculum steps (0-6)."""
        assert get_total_steps("photosynthesis") == 7

    def test_newtons_laws(self):
        """Newton's Laws has 8 curriculum steps (0-7)."""
        assert get_total_steps("newtons_laws") == 8

    def test_unknown(self):
        """An unrecognised topic returns 0."""
        assert get_total_steps("unknown") == 0


# ---------------------------------------------------------------------------
# visual_to_message
# ---------------------------------------------------------------------------


class TestVisualToMessage:
    """Tests for WebSocket message serialisation."""

    def test_normal_step(self):
        """Normal step produces a dict with is_recap=False and correct values."""
        vs = get_visual_for_step("photosynthesis", 2)
        assert vs is not None
        msg = visual_to_message(
            vs,
            topic="photosynthesis",
            turn_number=5,
            lesson_progress={"revealed_elements": ["sunlight", "water", "roots"]},
        )
        assert msg["type"] == "lesson_visual_update"
        assert msg["diagram_id"] == "photosynthesis"
        assert msg["step_id"] == 2
        assert msg["step_label"] == "The Green Kitchen"
        assert msg["total_steps"] == 7
        assert msg["turn_number"] == 5
        assert msg["is_recap"] is False
        assert "sunlight, water, and roots" in msg["caption"]
        assert msg["emoji_diagram"] == vs.emoji_diagram
        assert msg["highlight_keys"] == list(vs.highlight_keys)
        assert msg["unlocked_elements"] == ["sunlight", "water", "roots"]
        assert msg["progress_completed"] == 3
        assert msg["progress_total"] == 10
        assert msg["progress_label"] == "Scene Pieces Unlocked: 3/10"

    def test_recap_step(self):
        """Recap message has is_recap=True."""
        recap = get_recap_visual("newtons_laws")
        assert recap is not None
        msg = visual_to_message(
            recap, topic="newtons_laws", turn_number=10, is_recap=True,
        )
        assert msg["is_recap"] is True
        assert msg["step_id"] == -1
        assert msg["type"] == "lesson_visual_update"

    def test_message_has_all_required_keys(self):
        """Photosynthesis message includes base visual fields plus progress metadata."""
        vs = get_visual_for_step("photosynthesis", 0)
        assert vs is not None
        msg = visual_to_message(vs, topic="photosynthesis", turn_number=1)
        expected_keys = {
            "type",
            "diagram_id",
            "step_id",
            "step_label",
            "total_steps",
            "highlight_keys",
            "caption",
            "emoji_diagram",
            "turn_number",
            "is_recap",
            "unlocked_elements",
            "progress_completed",
            "progress_total",
            "progress_label",
        }
        assert set(msg.keys()) == expected_keys

    def test_photosynthesis_recap_unlocks_every_scene_element(self):
        recap = get_recap_visual("photosynthesis")
        assert recap is not None

        msg = visual_to_message(
            recap,
            topic="photosynthesis",
            turn_number=9,
            is_recap=True,
        )

        assert msg["progress_completed"] == 10
        assert msg["progress_total"] == 10
        assert msg["unlocked_elements"] == [
            "sunlight",
            "water",
            "roots",
            "carbon_dioxide",
            "leaf",
            "chloroplast",
            "chlorophyll",
            "sugar",
            "fruit",
            "oxygen",
        ]
