"""
Deterministic lesson-progress evaluation for concept-map state.

The model may suggest a curriculum step via ``[STEP:N]``, but the backend owns
the authoritative lesson progression shown in the concept map. Progress only
advances when the student's transcript demonstrates the current concept well
enough to move on.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, int | str]:
        return {
            "topic": self.topic,
            "current_step_id": self.current_step_id,
            "visual_step_id": self.visual_step_id,
            "failed_attempts_on_current_step": self.failed_attempts_on_current_step,
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
        return cls(
            topic=topic,
            current_step_id=max(0, current_step_id),
            visual_step_id=max(0, visual_step_id),
            failed_attempts_on_current_step=max(0, failed_attempts_on_current_step),
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

    if _student_mastered_step(topic, current_step, transcript):
        next_step = min(max(current_step + 1, hint_step), total_steps - 1)
        return LessonProgressState(
            topic=topic,
            current_step_id=next_step,
            visual_step_id=next_step,
            failed_attempts_on_current_step=0,
        )

    failure_increment = _failure_increment(transcript)
    if failure_increment > 0:
        current_attempts += failure_increment

    return LessonProgressState(
        topic=topic,
        current_step_id=current_step,
        visual_step_id=current_step,
        failed_attempts_on_current_step=current_attempts,
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
