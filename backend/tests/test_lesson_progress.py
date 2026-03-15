from pipeline.lesson_progress import (
    LessonProgressState,
    describe_prompt_state,
    evaluate_lesson_progress,
)


def test_wrong_answer_does_not_advance_photosynthesis_hook():
    state = LessonProgressState(topic="photosynthesis", current_step_id=0, visual_step_id=0)

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Came from food",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 0
    assert updated.visual_step_id == 0


def test_correct_hook_answer_advances_only_one_step():
    state = LessonProgressState(topic="photosynthesis", current_step_id=0, visual_step_id=0)

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="It comes from the air, especially carbon dioxide.",
        step_hint=5,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 1
    assert updated.visual_step_id == 1


def test_model_regression_cannot_move_newtons_map_backward():
    state = LessonProgressState(topic="newtons_laws", current_step_id=3, visual_step_id=3)

    updated = evaluate_lesson_progress(
        "newtons_laws",
        transcript="I am not sure",
        step_hint=0,
        state=state,
        total_steps=8,
    )

    assert updated.current_step_id == 3
    assert updated.visual_step_id == 3


def test_partial_ingredients_answer_does_not_advance():
    state = LessonProgressState(topic="photosynthesis", current_step_id=1, visual_step_id=1)

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Plants need sunlight and water.",
        step_hint=2,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 1
    assert updated.visual_step_id == 1
    assert updated.failed_attempts_on_current_step == 0


def test_partial_photosynthesis_answer_reveals_found_scene_elements():
    state = LessonProgressState(topic="photosynthesis", current_step_id=0, visual_step_id=0)

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Plants need sunlight and water.",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 0
    assert updated.visual_step_id == 0
    assert updated.revealed_elements == ["sunlight", "water"]


def test_rich_answer_can_bridge_one_adjacent_step():
    state = LessonProgressState(topic="photosynthesis", current_step_id=0, visual_step_id=0)

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Plants need sunlight, water, and carbon dioxide from the air.",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 2
    assert updated.visual_step_id == 2
    assert updated.revealed_elements == ["sunlight", "water", "carbon_dioxide"]


def test_revealed_scene_elements_accumulate_across_turns():
    state = LessonProgressState(
        topic="photosynthesis",
        current_step_id=0,
        visual_step_id=0,
        revealed_elements=["sunlight", "water"],
    )

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Also carbon dioxide from the air.",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.revealed_elements == ["sunlight", "water", "carbon_dioxide"]


def test_final_missing_ingredient_advances_from_accumulated_progress():
    state = LessonProgressState(
        topic="photosynthesis",
        current_step_id=1,
        visual_step_id=1,
        revealed_elements=["sunlight", "carbon_dioxide"],
    )

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Water.",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 2
    assert updated.visual_step_id == 2
    assert updated.failed_attempts_on_current_step == 0


def test_partial_correct_answer_does_not_escalate_failed_attempts():
    state = LessonProgressState(
        topic="photosynthesis",
        current_step_id=1,
        visual_step_id=1,
        failed_attempts_on_current_step=2,
        revealed_elements=["carbon_dioxide"],
    )

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Sunlight.",
        step_hint=1,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 1
    assert updated.visual_step_id == 1
    assert updated.failed_attempts_on_current_step == 0


def test_prompt_state_remembers_partial_ingredients_from_prior_turns():
    progress = LessonProgressState(
        topic="photosynthesis",
        current_step_id=1,
        visual_step_id=1,
        revealed_elements=["sunlight", "carbon_dioxide"],
    )

    prompt_state = describe_prompt_state(
        "photosynthesis",
        progress,
        transcript="Water.",
        total_steps=7,
    )

    assert prompt_state["accepted_so_far"] == "carbon dioxide, sunlight"
    assert prompt_state["accepted_this_turn"] == "water"
    assert prompt_state["missing_current"] == "none yet"
    assert prompt_state["do_not_reask"] == "carbon dioxide, sunlight, water"
    assert "completes this checkpoint" in prompt_state["bridge_guidance"]


def test_failed_attempts_increment_for_stuck_response():
    state = LessonProgressState(
        topic="photosynthesis",
        current_step_id=2,
        visual_step_id=2,
        failed_attempts_on_current_step=1,
    )

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="I don't know",
        step_hint=2,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 2
    assert updated.visual_step_id == 2
    assert updated.failed_attempts_on_current_step == 2
    assert updated.current_scaffold_level == 2


def test_give_up_counts_as_extra_failed_attempt():
    state = LessonProgressState(
        topic="newtons_laws",
        current_step_id=4,
        visual_step_id=4,
        failed_attempts_on_current_step=1,
    )

    updated = evaluate_lesson_progress(
        "newtons_laws",
        transcript="Just tell me the answer",
        step_hint=4,
        state=state,
        total_steps=8,
    )

    assert updated.failed_attempts_on_current_step == 3
    assert updated.current_scaffold_level == 3


def test_step_advance_resets_failed_attempts():
    state = LessonProgressState(
        topic="photosynthesis",
        current_step_id=4,
        visual_step_id=4,
        failed_attempts_on_current_step=3,
    )

    updated = evaluate_lesson_progress(
        "photosynthesis",
        transcript="Plants make glucose and oxygen.",
        step_hint=5,
        state=state,
        total_steps=7,
    )

    assert updated.current_step_id == 5
    assert updated.visual_step_id == 5
    assert updated.failed_attempts_on_current_step == 0
