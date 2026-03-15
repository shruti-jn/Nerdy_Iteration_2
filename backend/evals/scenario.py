"""Shared types for eval scenario banks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EvalScenario:
    """A single evaluation scenario: name, description, and student turn list."""
    name: str
    description: str
    student_turns: list[str]
    teacher_mode_from_turn: Optional[int] = None  # If set, score no_direct_answer with teacher_mode from this turn onward
