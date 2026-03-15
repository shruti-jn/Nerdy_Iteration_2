from pipeline.lesson_progress import LessonProgressState, evaluate_lesson_progress


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
    assert updated.failed_attempts_on_current_step == 1


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
