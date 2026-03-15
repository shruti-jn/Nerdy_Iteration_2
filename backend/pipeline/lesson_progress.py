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
    "roots",
    "carbon_dioxide",
    "leaf",
    "chloroplast",
    "chlorophyll",
    "sugar",
    "fruit",
    "oxygen",
)


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
    allows backward movement and never skips more than one step per turn.
    """
    if total_steps <= 0:
        return LessonProgressState(topic=topic, current_step_id=0, visual_step_id=0)

    current_step = max(0, min(state.current_step_id, total_steps - 1))
    hint_step = current_step if step_hint is None else max(0, min(step_hint, total_steps - 1))
    hint_step = min(max(hint_step, current_step), current_step + 1)
    current_attempts = max(0, state.failed_attempts_on_current_step)
    revealed_elements = _merge_revealed_elements(topic, state.revealed_elements, transcript)

    if _student_mastered_step(topic, current_step, transcript):
        next_step = min(max(current_step + 1, hint_step), total_steps - 1)
        return LessonProgressState(
            topic=topic,
            current_step_id=next_step,
            visual_step_id=next_step,
            failed_attempts_on_current_step=0,
            revealed_elements=revealed_elements,
        )

    failure_increment = _failure_increment(transcript)
    if failure_increment > 0:
        current_attempts += failure_increment

    return LessonProgressState(
        topic=topic,
        current_step_id=current_step,
        visual_step_id=current_step,
        failed_attempts_on_current_step=current_attempts,
        revealed_elements=revealed_elements,
    )


def _student_mastered_step(topic: str, step_id: int, transcript: str) -> bool:
    text = _normalise(transcript)
    if not text.strip():
        return False

    if topic == "photosynthesis":
        return _mastered_photosynthesis_step(step_id, text)
    if topic == "newtons_laws":
        return _mastered_newtons_step(step_id, text)
    return False


def _failure_increment(transcript: str) -> int:
    text = _normalise(transcript)
    if not text:
        return 0
    if _contains_any(text, _GIVE_UP_PHRASES):
        return 2
    if _contains_any(text, _STUCK_PHRASES):
        return 1
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


def _extract_revealed_elements(topic: str, transcript: str) -> list[str]:
    text = _normalise(transcript)
    if not text or topic != "photosynthesis":
        return []

    matches: list[str] = []

    if _contains_any(text, ("sunlight", "sun light", "light", "sun")):
        matches.append("sunlight")
    if _contains_any(text, ("water", "h2o")):
        matches.extend(["water", "roots"])
    if _contains_any(text, ("root", "roots")) and "roots" not in matches:
        matches.append("roots")
    if _contains_any(text, ("carbon dioxide", "co2", "co 2")):
        matches.append("carbon_dioxide")
    if _contains_any(text, ("leaf", "leaves")):
        matches.append("leaf")
    if _contains_any(text, ("chloroplast", "chloroplasts")):
        matches.append("chloroplast")
    if _contains_any(text, ("chlorophyll",)):
        matches.append("chlorophyll")
    if _contains_any(text, ("glucose", "sugar", "plant food", "food")):
        matches.append("sugar")
    if _contains_any(text, ("fruit", "fruits", "apple", "apples")):
        matches.append("fruit")
    if _contains_any(text, ("oxygen", "o2", "o 2")):
        matches.append("oxygen")

    return _dedupe_revealed_elements(topic, matches)


def _mastered_photosynthesis_step(step_id: int, text: str) -> bool:
    if step_id == 0:
        return _contains_any(text, ("carbon dioxide", "co2", "the air", "air", "atmosphere"))
    if step_id == 1:
        groups = (
            ("sunlight", "sun light", "light", "sun"),
            ("water", "h2o"),
            ("carbon dioxide", "co2", "air"),
        )
        return _count_groups(text, groups) >= 3
    if step_id == 2:
        groups = (
            ("chloroplast", "chloroplasts"),
            ("chlorophyll",),
            ("leaf", "leaves"),
        )
        return _count_groups(text, groups) >= 2
    if step_id == 3:
        groups = (
            ("sunlight", "light", "sun"),
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
        )
        return _count_groups(text, groups) >= 2
    if step_id == 4:
        groups = (
            ("glucose", "sugar", "food", "plant food"),
            ("oxygen", "o2"),
        )
        return _count_groups(text, groups) >= 2
    if step_id == 5:
        return _contains_any(
            text,
            (
                "oxygen",
                "breathe",
                "breathing",
                "food chain",
                "food chains",
                "ecosystem",
                "humans survive",
                "we survive",
            ),
        )
    return False


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
