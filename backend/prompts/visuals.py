"""
Visual step registry — maps (topic, step_id) to deterministic visual data.

Each topic defines an ordered list of VisualStep entries that align with the
CURRICULUM FLOW steps in the topic scaffold prompts. The orchestrator looks up
the current step after parsing the LLM's [STEP:N] tag and sends the visual
payload to the frontend via a lesson_visual_update WebSocket message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "VisualStep",
    "get_visual_for_step",
    "get_recap_visual",
    "get_total_steps",
    "parse_step_tag",
]

# ── Step tag parsing ────────────────────────────────────────────────────────

_STEP_TAG_RE = re.compile(r"^\[STEP:(\d+)\]\s*")


def parse_step_tag(text: str) -> tuple[int | None, str]:
    """Extract ``[STEP:N]`` from the start of LLM output.

    Returns:
        (step_id, cleaned_text) — step_id is None if no tag found.
    """
    m = _STEP_TAG_RE.match(text)
    if m:
        return int(m.group(1)), text[m.end():]
    return None, text


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VisualStep:
    step_id: int
    step_label: str
    caption: str
    emoji_diagram: str
    highlight_keys: list[str] = field(default_factory=list)


# ── Photosynthesis (7 steps: 0-6) ──────────────────────────────────────────

_PHOTOSYNTHESIS_STEPS: list[VisualStep] = [
    VisualStep(
        step_id=0,
        step_label="The Hook",
        caption="A tiny seed becomes a giant tree… where does the mass come from?",
        emoji_diagram="🌱 → ❓ → 🌳",
        highlight_keys=["seed", "tree", "mass"],
    ),
    VisualStep(
        step_id=1,
        step_label="The Ingredients",
        caption="Plants need three ingredients: sunlight, water, and carbon dioxide",
        emoji_diagram="☀️ + 💧 + 🌬️CO₂ → 🌿",
        highlight_keys=["sunlight", "water", "carbon dioxide"],
    ),
    VisualStep(
        step_id=2,
        step_label="The Green Kitchen",
        caption="Chloroplasts are tiny kitchens inside every leaf. Chlorophyll is the green chef!",
        emoji_diagram="🌿 → 🏭 Chloroplast → 👨‍🍳 Chlorophyll",
        highlight_keys=["chloroplast", "chlorophyll", "leaf"],
    ),
    VisualStep(
        step_id=3,
        step_label="The Process",
        caption="Chlorophyll catches sunlight like a solar panel and powers the reaction",
        emoji_diagram="☀️ → ⚡ → 🏭",
        highlight_keys=["chlorophyll", "sunlight", "energy"],
    ),
    VisualStep(
        step_id=4,
        step_label="The Output",
        caption="Plants make their own food (glucose) and release oxygen as a bonus",
        emoji_diagram="☀️ + 💧 + CO₂ → 🍬 Glucose + 💨 O₂",
        highlight_keys=["glucose", "oxygen", "equation"],
    ),
    VisualStep(
        step_id=5,
        step_label="Why It Matters",
        caption="Without photosynthesis: no oxygen, no food chains, no us",
        emoji_diagram="🌍 → 🌿 → 💨O₂ → 🫁 → 🍎",
        highlight_keys=["oxygen", "food chain", "ecosystem"],
    ),
    VisualStep(
        step_id=6,
        step_label="Teach-Back",
        caption="Now YOU are the expert. Explain photosynthesis in your own words!",
        emoji_diagram="🎓 You explain! ☀️+💧+CO₂ → ?",
        highlight_keys=["teach-back"],
    ),
]

_PHOTOSYNTHESIS_RECAP = VisualStep(
    step_id=-1,
    step_label="Complete!",
    caption="You traced the full journey of photosynthesis!",
    emoji_diagram="🌱 ☀️+💧+CO₂ → 🏭 Chloroplast → 🍬 Glucose + 💨 O₂ → 🌍🫁🍎",
    highlight_keys=["photosynthesis"],
)

# ── Newton's Laws (8 steps: 0-7) ───────────────────────────────────────────

_NEWTONS_LAWS_STEPS: list[VisualStep] = [
    VisualStep(
        step_id=0,
        step_label="The Hook",
        caption="Why do you lurch forward when a car stops?",
        emoji_diagram="🚗💨 → 🛑 → 🏃‍♂️💨",
        highlight_keys=["car", "seatbelt", "force"],
    ),
    VisualStep(
        step_id=1,
        step_label="Objects in Motion",
        caption="A puck on ice keeps sliding forever — nothing stops it",
        emoji_diagram="🏒 → → → 🧊",
        highlight_keys=["motion", "puck", "ice"],
    ),
    VisualStep(
        step_id=2,
        step_label="Friction",
        caption="Rough surfaces create friction — the invisible brake",
        emoji_diagram="🏒 → 🟫 → 🛑",
        highlight_keys=["friction", "surface"],
    ),
    VisualStep(
        step_id=3,
        step_label="Objects at Rest",
        caption="No force? No movement. Objects at rest stay at rest",
        emoji_diagram="📖🪑 = 😴",
        highlight_keys=["rest", "net force"],
    ),
    VisualStep(
        step_id=4,
        step_label="Inertia",
        caption="Objects resist changing what they're doing — that's inertia",
        emoji_diagram="🧠 Inertia = resist change",
        highlight_keys=["inertia", "newton first law"],
    ),
    VisualStep(
        step_id=5,
        step_label="Force and Mass",
        caption="Empty cart speeds up fast; full cart? Not so much",
        emoji_diagram="🛒💨 vs 🛒🧱…💨",
        highlight_keys=["mass", "force", "acceleration"],
    ),
    VisualStep(
        step_id=6,
        step_label="F = ma",
        caption="More force = more acceleration. More mass = less acceleration",
        emoji_diagram="F = m × a ⚡",
        highlight_keys=["F=ma", "newton second law"],
    ),
    VisualStep(
        step_id=7,
        step_label="Teach-Back",
        caption="Now YOU are the expert. Explain Newton's Laws!",
        emoji_diagram="🎓 You explain! F = m × a",
        highlight_keys=["teach-back"],
    ),
]

_NEWTONS_LAWS_RECAP = VisualStep(
    step_id=-1,
    step_label="Complete!",
    caption="You mastered Newton's 1st and 2nd Laws!",
    emoji_diagram="🛑 Inertia + ⚡ F = m × a → 🚀",
    highlight_keys=["newton first law", "newton second law"],
)

# ── Registry ────────────────────────────────────────────────────────────────

_TOPIC_STEPS: dict[str, list[VisualStep]] = {
    "photosynthesis": _PHOTOSYNTHESIS_STEPS,
    "newtons_laws": _NEWTONS_LAWS_STEPS,
}

_TOPIC_RECAPS: dict[str, VisualStep] = {
    "photosynthesis": _PHOTOSYNTHESIS_RECAP,
    "newtons_laws": _NEWTONS_LAWS_RECAP,
}


def get_total_steps(topic: str) -> int:
    """Return total number of curriculum steps for a topic."""
    steps = _TOPIC_STEPS.get(topic)
    if steps is None:
        return 0
    return len(steps)


def get_visual_for_step(topic: str, step_id: int) -> VisualStep | None:
    """Look up the visual for a given topic and step.

    Clamps step_id to the valid range ``[0, total_steps - 1]``.
    Returns None if the topic is unknown.
    """
    steps = _TOPIC_STEPS.get(topic)
    if steps is None:
        return None
    clamped = max(0, min(step_id, len(steps) - 1))
    return steps[clamped]


def get_recap_visual(topic: str) -> VisualStep | None:
    """Return the full recap visual for session completion.

    Returns None if the topic is unknown.
    """
    return _TOPIC_RECAPS.get(topic)


def visual_to_message(
    visual: VisualStep,
    topic: str,
    turn_number: int,
    is_recap: bool = False,
) -> dict:
    """Convert a VisualStep to a ``lesson_visual_update`` WebSocket message dict."""
    return {
        "type": "lesson_visual_update",
        "diagram_id": topic,
        "step_id": visual.step_id,
        "step_label": visual.step_label,
        "total_steps": get_total_steps(topic),
        "highlight_keys": list(visual.highlight_keys),
        "caption": visual.caption,
        "emoji_diagram": visual.emoji_diagram,
        "turn_number": turn_number,
        "is_recap": is_recap,
    }
