"""
Prompts package — assembles the three-layer Socratic system prompt.
Layer 1: Identity and absolute rules (socratic_system.py)
Layer 2: Topic-specific scaffolding (photosynthesis.py, newtons_laws.py)
Layer 3: Adaptive behavior rules (adaptive_rules.py)
"""

from prompts.socratic_system import SOCRATIC_SYSTEM_PROMPT
from prompts.photosynthesis import PHOTOSYNTHESIS_SCAFFOLD
from prompts.newtons_laws import NEWTONS_LAWS_SCAFFOLD
from prompts.adaptive_rules import ADAPTIVE_RULES

# Registry of available topic scaffolds
_TOPIC_SCAFFOLDS = {
    "photosynthesis": PHOTOSYNTHESIS_SCAFFOLD,
    "newtons_laws": NEWTONS_LAWS_SCAFFOLD,
}


def build_prompt(topic: str) -> str:
    """Assembles the full system prompt from all three layers for the given topic.

    Args:
        topic: Topic identifier ("photosynthesis" or "newtons_laws").

    Returns:
        Complete system prompt string combining Layer 1 + Layer 2 + Layer 3.

    Raises:
        ValueError: If the topic is not in the scaffold registry.
    """
    scaffold = _TOPIC_SCAFFOLDS.get(topic)
    if scaffold is None:
        available = ", ".join(_TOPIC_SCAFFOLDS.keys())
        raise ValueError(f"Unknown topic '{topic}'. Available: {available}")

    return f"{SOCRATIC_SYSTEM_PROMPT}\n{scaffold}\n{ADAPTIVE_RULES}"
