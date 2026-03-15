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

# Public list of topic keys that have full scaffolds
AVAILABLE_TOPICS: list[str] = list(_TOPIC_SCAFFOLDS.keys())

# Template for the greeting turn (Turn 0) — injected as the user message
# so the LLM generates a warm opening within the Socratic persona.
_GREETING_TEMPLATE = (
    "[Greeting — no student has spoken yet] "
    "Introduce yourself as Socrates VI. Welcome the student to today's lesson on {topic}. "
    "Start with a mystery or surprising question that hooks their curiosity "
    "(use the STEP 0 — THE HOOK from the topic scaffold). "
    "Be warm and a little funny. Keep it under 40 words total."
)


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


def build_greeting_prompt(topic: str) -> str:
    """Build the synthetic user message that triggers the tutor's greeting.

    Args:
        topic: Topic identifier (e.g. "photosynthesis").

    Returns:
        A user-message string instructing the LLM to greet the student.
    """
    display = topic.replace("_", " ").title()
    return _GREETING_TEMPLATE.format(topic=display)
