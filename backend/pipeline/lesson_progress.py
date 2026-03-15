"""
Deterministic lesson-progress evaluation for concept-map state.

The model may suggest a curriculum step via ``[STEP:N]``, but the backend owns
the authoritative lesson progression shown in the concept map. Progress only
advances when the student's transcript demonstrates the current concept well
enough to move on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

_STUCK_PHRASES = (
    "i don t know",
    "i dont know",
    "idk",
    "not sure",
    "no idea",
    "i don t get it",
    "i cant",
    "i can t",
    "this is hard",
    "confused",
)

_GIVE_UP_PHRASES = (
    "just tell me",
    "tell me the answer",
    "i give up",
    "give up",
)

_PHOTOSYNTHESIS_REVEAL_ORDER = (
    "sunlight",
    "water",
    "carbon_dioxide",
    "leaf",
    "chloroplast",
    "chlorophyll",
    "sugar",
    "oxygen",
)

_PHOTOSYNTHESIS_REVEALED_PROMPT_TERMS = {
    "sunlight": "sunlight",
    "water": "water",
    "carbon_dioxide": "carbon dioxide air",
    "leaf": "leaf leaves",
    "chloroplast": "chloroplast chloroplasts",
    "chlorophyll": "chlorophyll",
    "sugar": "glucose sugar plant food",
    "oxygen": "oxygen o2 breathing breathe air for us",
}

_PHOTOSYNTHESIS_STEP_LABELS = {
    0: "The Hook",
    1: "The Ingredients",
    2: "The Green Kitchen",
    3: "The Process",
    4: "The Output",
    5: "Why It Matters",
    6: "Teach-Back",
}

_PHOTOSYNTHESIS_STEP_GOALS = {
    0: "connect the tree's extra mass to carbon dioxide from the air",
    1: "finish the ingredient list: sunlight, water, and carbon dioxide",
    2: "identify the leaf factory: leaf, chloroplast, and chlorophyll",
    3: "explain that chlorophyll captures sunlight energy",
    4: "name both outputs: glucose and oxygen",
    5: "connect photosynthesis to oxygen and food chains",
    6: "let the student explain the whole process in their own words",
}

_PHOTOSYNTHESIS_STEP_TARGETS: dict[int, tuple[tuple[str, tuple[str, ...]], ...]] = {
    0: (
        ("carbon dioxide", ("carbon dioxide", "co2", "co 2", "the air", "air", "atmosphere")),
    ),
    1: (
        ("sunlight", ("sunlight", "sun light", "light", "sun")),
        ("water", ("water", "h2o")),
        ("carbon dioxide", ("carbon dioxide", "co2", "co 2", "air")),
    ),
    2: (
        ("leaf", ("leaf", "leaves")),
        ("chloroplast", ("chloroplast", "chloroplasts")),
        ("chlorophyll", ("chlorophyll",)),
    ),
    3: (
        ("sunlight", ("sunlight", "sun light", "light", "sun")),
        (
            "capturing light energy",
            (
                "energy",
                "light energy",
                "sunlight energy",
                "capture",
                "captures",
                "capturing",
                "absorb",
                "absorbs",
                "absorbing",
                "power",
                "powers",
            ),
        ),
    ),
    4: (
        ("glucose", ("glucose", "sugar", "plant food", "food for itself", "its own food")),
        ("oxygen", ("oxygen", "o2", "o 2")),
    ),
    5: (
        ("oxygen for breathing", ("breathe", "breathing", "humans survive", "we survive", "air for us")),
        ("food chains depend on plants", ("food chain", "food chains", "ecosystem")),
    ),
}


def _normalise(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9+\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _count_groups(text: str, groups: tuple[tuple[str, ...], ...]) -> int:
    return sum(1 for group in groups if _contains_any(text, group))


@dataclass
class LessonProgressState:
    topic: str
    current_step_id: int
    visual_step_id: int
    failed_attempts_on_current_step: int = 0
    revealed_elements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, int | str | list[str]]:
        return {
            "topic": self.topic,
            "current_step_id": self.current_step_id,
            "visual_step_id": self.visual_step_id,
            "failed_attempts_on_current_step": self.failed_attempts_on_current_step,
            "revealed_elements": list(self.revealed_elements),
        }

    @property
    def current_scaffold_level(self) -> int:
        if self.failed_attempts_on_current_step <= 0:
            return 0
        if self.failed_attempts_on_current_step == 1:
            return 1
        if self.failed_attempts_on_current_step == 2:
            return 2
        if self.failed_attempts_on_current_step == 3:
            return 3
        return 4

    @classmethod
    def from_dict(cls, data: dict | None, topic: str) -> "LessonProgressState":
        if not data or data.get("topic") != topic:
            return cls(topic=topic, current_step_id=0, visual_step_id=0)
        current_step_id = int(data.get("current_step_id", 0))
        visual_step_id = int(data.get("visual_step_id", current_step_id))
        failed_attempts_on_current_step = int(data.get("failed_attempts_on_current_step", 0))
        raw_revealed = data.get("revealed_elements", [])
        revealed_elements = (
            [str(item) for item in raw_revealed if isinstance(item, str)]
            if isinstance(raw_revealed, list)
            else []
        )
        return cls(
            topic=topic,
            current_step_id=max(0, current_step_id),
            visual_step_id=max(0, visual_step_id),
            failed_attempts_on_current_step=max(0, failed_attempts_on_current_step),
            revealed_elements=_dedupe_revealed_elements(topic, revealed_elements),
        )


def evaluate_lesson_progress(
    topic: str,
    transcript: str,
    step_hint: int | None,
    state: LessonProgressState,
    total_steps: int,
) -> LessonProgressState:
    """Advance lesson progress deterministically.

    ``step_hint`` from the LLM is treated as a hint only. The evaluator never
    allows backward movement and may bridge at most one additional adjacent
    checkpoint when a single student reply clearly covers both.
    """
    if total_steps <= 0:
        return LessonProgressState(topic=topic, current_step_id=0, visual_step_id=0)

    current_step = max(0, min(state.current_step_id, total_steps - 1))
    hint_step = current_step if step_hint is None else max(0, min(step_hint, total_steps - 1))
    hint_step = min(max(hint_step, current_step), current_step + 1)
    current_attempts = max(0, state.failed_attempts_on_current_step)
    revealed_elements = _merge_revealed_elements(topic, state.revealed_elements, transcript)

    if _student_mastered_step(topic, current_step, transcript, state.revealed_elements):
        advance_steps = _preview_mastered_step_advance(
            topic,
            current_step,
            transcript,
            total_steps,
            revealed_elements=state.revealed_elements,
        )
        next_step = min(
            max(current_step + max(1, advance_steps), hint_step),
            total_steps - 1,
        )
        return LessonProgressState(
            topic=topic,
            current_step_id=next_step,
            visual_step_id=next_step,
            failed_attempts_on_current_step=0,
            revealed_elements=revealed_elements,
        )

    if _made_progress_on_current_step(topic, current_step, transcript, state.revealed_elements):
        current_attempts = 0

    failure_increment = _failure_increment(
        topic,
        current_step,
        transcript,
    )
    if failure_increment > 0:
        current_attempts += failure_increment

    return LessonProgressState(
        topic=topic,
        current_step_id=current_step,
        visual_step_id=current_step,
        failed_attempts_on_current_step=current_attempts,
        revealed_elements=revealed_elements,
    )


def _student_mastered_step(
    topic: str,
    step_id: int,
    transcript: str,
    revealed_elements: list[str] | None = None,
) -> bool:
    text = _concept_text_for_matching(topic, transcript, revealed_elements)
    if not text.strip():
        return False

    if topic == "photosynthesis":
        return _mastered_photosynthesis_step(step_id, text)
    if topic == "newtons_laws":
        return _mastered_newtons_step(step_id, text)
    return False


def _failure_increment(topic: str, current_step: int, transcript: str) -> int:
    text = _normalise(transcript)
    if not text:
        return 0
    if _contains_any(text, _GIVE_UP_PHRASES):
        return 2
    if _contains_any(text, _STUCK_PHRASES):
        return 1
    if _matched_targets_for_step(topic, current_step, transcript):
        return 0
    return 1


def _dedupe_revealed_elements(topic: str, elements: list[str]) -> list[str]:
    if topic != "photosynthesis":
        return []

    deduped: list[str] = []
    for element in _PHOTOSYNTHESIS_REVEAL_ORDER:
        if element in elements and element not in deduped:
            deduped.append(element)
    return deduped


def _merge_revealed_elements(topic: str, existing: list[str], transcript: str) -> list[str]:
    if topic != "photosynthesis":
        return []

    merged = _dedupe_revealed_elements(topic, existing)
    matches = _extract_revealed_elements(topic, transcript)
    for element in matches:
        if element not in merged:
            merged.append(element)
    return _dedupe_revealed_elements(topic, merged)


def get_step_label(topic: str, step_id: int) -> str:
    if topic == "photosynthesis":
        return _PHOTOSYNTHESIS_STEP_LABELS.get(step_id, f"Step {step_id}")
    return f"Step {step_id}"


def get_step_goal(topic: str, step_id: int) -> str:
    if topic == "photosynthesis":
        return _PHOTOSYNTHESIS_STEP_GOALS.get(step_id, "continue the lesson")
    return "continue the lesson"


def describe_prompt_state(
    topic: str,
    progress: LessonProgressState,
    transcript: str,
    total_steps: int,
) -> dict[str, str]:
    """Build a concise runtime state block for the tutoring prompt."""
    current_step = max(0, min(progress.current_step_id, max(total_steps - 1, 0)))
    current_label = get_step_label(topic, current_step)
    accepted_so_far = _accepted_concepts_before_turn(topic, progress, current_step)
    accepted_this_turn = _accepted_concepts_for_prompt(
        topic,
        current_step,
        transcript,
        total_steps,
        already_accepted=accepted_so_far,
        revealed_elements=progress.revealed_elements,
    )
    missing_current = _missing_concepts_for_prompt(
        topic,
        current_step,
        transcript,
        revealed_elements=progress.revealed_elements,
    )
    bridge_steps = _preview_mastered_step_advance(
        topic,
        current_step,
        transcript,
        total_steps,
        revealed_elements=progress.revealed_elements,
    )
    target_step = min(current_step + bridge_steps, max(total_steps - 1, 0))
    next_goal = get_step_goal(topic, target_step)
    do_not_reask = _dedupe_labels((*accepted_so_far, *accepted_this_turn))

    if bridge_steps >= 2:
        bridge_guidance = (
            "The student's current reply covers the current idea and the next checkpoint. "
            "Acknowledge both, then move straight to the following concept."
        )
    elif bridge_steps == 1:
        bridge_guidance = (
            "The student's current reply completes this checkpoint. "
            "Acknowledge it clearly, then move to the next concept in the same response."
        )
    else:
        bridge_guidance = (
            "Stay on this checkpoint. Acknowledge any correct partial idea, then ask only for one missing piece."
        )

    return {
        "current_step_label": current_label,
        "accepted_so_far": _format_prompt_list(accepted_so_far),
        "accepted_this_turn": _format_prompt_list(accepted_this_turn),
        "missing_current": _format_prompt_list(missing_current),
        "do_not_reask": _format_prompt_list(do_not_reask),
        "next_goal": next_goal,
        "bridge_guidance": bridge_guidance,
    }


def _concept_text_for_matching(
    topic: str,
    transcript: str,
    revealed_elements: list[str] | None = None,
) -> str:
    text = _normalise(transcript)
    if topic != "photosynthesis" or not revealed_elements:
        return text

    revealed_terms = " ".join(
        _PHOTOSYNTHESIS_REVEALED_PROMPT_TERMS.get(element, "")
        for element in _dedupe_revealed_elements(topic, list(revealed_elements))
    )
    if not revealed_terms:
        return text
    return _normalise(f"{revealed_terms} {transcript}")


def _extract_revealed_elements(topic: str, transcript: str) -> list[str]:
    text = _normalise(transcript)
    if not text or topic != "photosynthesis":
        return []

    matches: list[str] = []

    if _contains_any(text, ("sunlight", "sun light", "light", "sun")):
        matches.append("sunlight")
    if _contains_any(text, ("water", "h2o")):
        matches.append("water")
    if _contains_any(text, ("carbon dioxide", "co2", "co 2")):
        matches.append("carbon_dioxide")
    if _contains_any(text, ("leaf", "leaves")):
        matches.append("leaf")
    if _contains_any(text, ("chloroplast", "chloroplasts")):
        matches.append("chloroplast")
    if _contains_any(text, ("chlorophyll",)):
        matches.append("chlorophyll")
    if _contains_any(text, ("glucose", "sugar", "plant food", "food for itself", "its own food")):
        matches.append("sugar")
    if _contains_any(text, ("oxygen", "o2", "o 2")):
        matches.append("oxygen")

    return _dedupe_revealed_elements(topic, matches)


def _mastered_photosynthesis_step(step_id: int, text: str) -> bool:
    if step_id == 0:
        return _count_groups(text, _target_groups_for_step(step_id)) >= 1
    if step_id == 1:
        return _count_groups(text, _target_groups_for_step(step_id)) >= 3
    if step_id == 2:
        return _count_groups(text, _target_groups_for_step(step_id)) >= 2
    if step_id == 3:
        return _count_groups(text, _target_groups_for_step(step_id)) >= 2
    if step_id == 4:
        output_groups = (
            ("glucose", "sugar", "food", "plant food", "food for itself", "its own food"),
            ("oxygen", "o2"),
        )
        return _count_groups(text, output_groups) >= 2
    if step_id == 5:
        return _count_groups(text, _target_groups_for_step(step_id)) >= 1
    return False


def _target_groups_for_step(step_id: int) -> tuple[tuple[str, ...], ...]:
    return tuple(group for _, group in _PHOTOSYNTHESIS_STEP_TARGETS.get(step_id, ()))


def _matched_targets_for_step(
    topic: str,
    step_id: int,
    transcript: str,
    revealed_elements: list[str] | None = None,
) -> list[str]:
    text = _concept_text_for_matching(topic, transcript, revealed_elements)
    if topic != "photosynthesis" or not text:
        return []
    return [
        label
        for label, phrases in _PHOTOSYNTHESIS_STEP_TARGETS.get(step_id, ())
        if _contains_any(text, phrases)
    ]


def _missing_targets_for_step(
    topic: str,
    step_id: int,
    transcript: str,
    revealed_elements: list[str] | None = None,
) -> list[str]:
    if topic != "photosynthesis":
        return []

    matched = set(_matched_targets_for_step(topic, step_id, transcript, revealed_elements))
    targets = [label for label, _ in _PHOTOSYNTHESIS_STEP_TARGETS.get(step_id, ())]

    if step_id == 0 and targets and not matched:
        return ["carbon dioxide from the air"]

    return [label for label in targets if label not in matched]


def _preview_mastered_step_advance(
    topic: str,
    current_step: int,
    transcript: str,
    total_steps: int,
    *,
    max_extra_steps: int = 2,
    revealed_elements: list[str] | None = None,
) -> int:
    """Return how many adjacent checkpoints this transcript completes."""
    if total_steps <= 0:
        return 0

    text = _concept_text_for_matching(topic, transcript, revealed_elements)
    if not text:
        return 0

    advance = 0
    step_to_check = current_step
    final_step = total_steps - 1

    while (
        step_to_check < final_step
        and advance < max_extra_steps
        and _student_mastered_step(topic, step_to_check, text)
    ):
        advance += 1
        step_to_check += 1

    return advance


def _mastered_concepts_before_step(topic: str, step_id: int) -> list[str]:
    if topic != "photosynthesis":
        return []

    concepts: list[str] = []
    for prior_step in range(step_id):
        concepts.extend(label for label, _ in _PHOTOSYNTHESIS_STEP_TARGETS.get(prior_step, ()))
    return _dedupe_labels(tuple(concepts))


def _accepted_concepts_before_turn(
    topic: str,
    progress: LessonProgressState,
    current_step: int,
) -> list[str]:
    if topic != "photosynthesis":
        return _mastered_concepts_before_step(topic, current_step)

    accepted: list[str] = []
    for step in range(current_step + 1):
        accepted.extend(
            _matched_targets_for_step(topic, step, "", progress.revealed_elements)
        )
    return _dedupe_labels(tuple(accepted))


def _accepted_concepts_for_prompt(
    topic: str,
    current_step: int,
    transcript: str,
    total_steps: int,
    *,
    already_accepted: list[str] | None = None,
    revealed_elements: list[str] | None = None,
) -> list[str]:
    prior = set(already_accepted or [])
    accepted = [
        label
        for label in _matched_targets_for_step(topic, current_step, transcript)
        if label not in prior
    ]
    bridge_steps = _preview_mastered_step_advance(
        topic,
        current_step,
        transcript,
        total_steps,
        revealed_elements=revealed_elements,
    )
    if bridge_steps >= 2:
        accepted.extend(
            label
            for label in _matched_targets_for_step(topic, current_step + 1, transcript)
            if label not in prior and label not in accepted
        )
    return _dedupe_labels(tuple(accepted))


def _missing_concepts_for_prompt(
    topic: str,
    current_step: int,
    transcript: str,
    *,
    revealed_elements: list[str] | None = None,
) -> list[str]:
    missing = _missing_targets_for_step(topic, current_step, transcript, revealed_elements)
    if missing:
        return missing
    return []


def _made_progress_on_current_step(
    topic: str,
    current_step: int,
    transcript: str,
    revealed_elements: list[str],
) -> bool:
    current_matches = _matched_targets_for_step(topic, current_step, transcript)
    if not current_matches:
        return False
    prior_matches = set(_matched_targets_for_step(topic, current_step, "", revealed_elements))
    return any(label not in prior_matches for label in current_matches)


def _dedupe_labels(labels: tuple[str, ...] | list[str]) -> list[str]:
    deduped: list[str] = []
    for label in labels:
        if label and label not in deduped:
            deduped.append(label)
    return deduped


def _format_prompt_list(labels: list[str]) -> str:
    return ", ".join(labels) if labels else "none yet"


def _mastered_newtons_step(step_id: int, text: str) -> bool:
    if step_id == 0:
        groups = (
            ("car stops", "stops suddenly", "brakes", "brake"),
            ("seatbelt", "inertia", "lurch", "forward"),
        )
        return _count_groups(text, groups) >= 2
    if step_id == 1:
        return _contains_any(
            text,
            ("keep moving", "keeps moving", "keep sliding", "keeps sliding", "forever"),
        )
    if step_id == 2:
        return _contains_any(text, ("friction", "rough", "concrete", "slows", "slows down"))
    if step_id == 3:
        groups = (
            ("at rest", "stay still", "stays still", "still"),
            ("no force", "net force", "no outside force"),
        )
        return _count_groups(text, groups) >= 2 or _contains_any(
            text,
            ("no net force",),
        )
    if step_id == 4:
        return _contains_any(text, ("inertia", "resist change", "keeps moving"))
    if step_id == 5:
        groups = (
            ("empty cart", "empty shopping cart", "lighter", "less mass"),
            ("full cart", "heavy", "heavier", "more mass"),
        )
        return _count_groups(text, groups) >= 1 and _contains_any(
            text,
            ("faster", "speeds up", "accelerates", "easier"),
        )
    if step_id == 6:
        groups = (
            ("force", "push"),
            ("mass",),
            ("acceleration", "accelerate", "faster"),
        )
        equation = _contains_any(text, ("f = m a", "f ma", "f = ma"))
        return _count_groups(text, groups) >= 3 or (
            equation and _count_groups(text, groups) >= 1
        )
    return False
