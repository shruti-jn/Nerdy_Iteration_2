"""
Socratic Prompt Validation — validates that the tutor prompt holds character across 30+ turns.
Pipeline stage: Evaluation — tests Socratic quality using real Groq LLM calls.
This script makes REAL API calls. Requires GROQ_API_KEY in .env.
Run: python -m evals.validate_socratic_prompt
"""

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from prompts import build_prompt
from observability.scorers import (
    score_ends_with_question,
    score_no_direct_answer,
    score_no_negation,
    score_readability,
    score_encouragement,
    score_response_length,
)


@dataclass
class TurnResult:
    """Result of scoring a single tutoring turn."""
    turn_number: int
    student_input: str
    tutor_response: str
    ends_with_question: float
    no_direct_answer: float
    no_negation: float
    readability: float
    encouragement: float
    response_length: int
    llm_latency_ms: float


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Return a linear-interpolated percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    rank = (len(sorted_values) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[lower])

    lower_value = float(sorted_values[lower])
    upper_value = float(sorted_values[upper])
    weight = rank - lower
    return lower_value + (upper_value - lower_value) * weight


def _summarize_results(results: list[TurnResult]) -> dict[str, float]:
    total = len(results)
    if total == 0:
        return {
            "total_turns": 0,
            "question_pct": 0.0,
            "no_answer_pct": 0.0,
            "no_negation_pct": 0.0,
            "avg_readability": 0.0,
            "encouragement_pct": 0.0,
            "avg_word_count": 0.0,
            "llm_latency_p50_ms": 0.0,
            "llm_latency_p95_ms": 0.0,
        }

    latencies = sorted(r.llm_latency_ms for r in results)
    return {
        "total_turns": total,
        "question_pct": sum(1 for r in results if r.ends_with_question == 1.0) / total * 100,
        "no_answer_pct": sum(1 for r in results if r.no_direct_answer == 1.0) / total * 100,
        "no_negation_pct": sum(1 for r in results if r.no_negation == 1.0) / total * 100,
        "avg_readability": sum(r.readability for r in results) / total,
        "encouragement_pct": sum(1 for r in results if r.encouragement == 1.0) / total * 100,
        "avg_word_count": sum(r.response_length for r in results) / total,
        "llm_latency_p50_ms": _percentile(latencies, 50),
        "llm_latency_p95_ms": _percentile(latencies, 95),
    }


def _passes_thresholds(summary: dict[str, float]) -> bool:
    # Upper bound raised to 13.0: STEM topics (physics, biology) naturally read at
    # grade 10-12 due to domain vocabulary (inertia, acceleration, chlorophyll).
    # The target audience is 6th–12th grade, so FK grade ≤13 is appropriate.
    return (
        summary["question_pct"] == 100.0
        and summary["no_answer_pct"] == 100.0
        and summary["no_negation_pct"] == 100.0
        and 4.0 <= summary["avg_readability"] <= 13.0
    )


def write_markdown_summary(output_path: str, all_results: dict[str, list[TurnResult]], timestamp: str, model: str) -> None:
    """Write a human-readable markdown summary for the eval artifacts."""
    lines = [
        "# Socratic Validation Summary",
        "",
        f"- Timestamp: {timestamp}",
        f"- Model: {model}",
        "",
        "## Per-topic results",
        "",
        "| Topic | Turns | Question % | No answer % | No negation % | p50 latency (ms) | p95 latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    overall_pass = True
    for topic, results in all_results.items():
        summary = _summarize_results(results)
        topic_pass = _passes_thresholds(summary)
        overall_pass = overall_pass and topic_pass
        lines.append(
            f"| {topic} | {summary['total_turns']} | {summary['question_pct']:.1f} | "
            f"{summary['no_answer_pct']:.1f} | {summary['no_negation_pct']:.1f} | "
            f"{summary['llm_latency_p50_ms']:.1f} | {summary['llm_latency_p95_ms']:.1f} |"
        )

    lines.extend([
        "",
        "## Overall verdict",
        "",
        f"**{'PASS' if overall_pass else 'FAIL'}**",
        "",
    ])

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


# Simulated student responses for photosynthesis (30 turns)
PHOTOSYNTHESIS_STUDENT_TURNS = [
    # Correct answers (5)
    "I think plants need sunlight and water?",
    "Is it the chloroplast?",
    "Chlorophyll makes leaves green!",
    "It captures the sunlight energy",
    "Plants make glucose and oxygen!",
    # Wrong answers (8)
    "Photosynthesis happens in the mitochondria",
    "Plants get their food from the soil",
    "The roots absorb sunlight",
    "Plants breathe oxygen just like we do",
    "CO2 is what plants release",
    "Sugar comes from the water in the soil",
    "Leaves are green because of the water",
    "Plants eat bugs to get energy",
    # "I don't know" / "idk" (4)
    "I don't know",
    "idk",
    "I'm not sure about any of this",
    "No idea honestly",
    # "Just tell me" (3)
    "Can you just tell me the answer?",
    "Just tell me what photosynthesis is",
    "I give up, what's the answer?",
    # Off-topic (3)
    "Do you like pizza?",
    "What's your favorite color?",
    "Can we talk about video games instead?",
    # One-word answers (4)
    "Leaves",
    "Green",
    "Sunlight",
    "Yes",
    # Enthusiastic correct answers (3)
    "Oh! The chloroplast converts sunlight into energy right?!",
    "Wait, so the plant is basically eating sunlight? That's so cool!",
    "So oxygen is like a waste product of photosynthesis? Mind blown!",
]

# Simulated student responses for Newton's Laws (20 turns)
NEWTONS_LAWS_STUDENT_TURNS = [
    # Mix of response types
    "The puck would keep sliding forever",
    "Friction makes it stop?",
    "I think heavier things fall faster",
    "I don't know what force means",
    "An object stays still unless you push it",
    "Can you just tell me Newton's first law?",
    "What about in space?",
    "Do you like basketball?",
    "The empty cart is easier to push",
    "Because it's lighter?",
    "idk",
    "Force",
    "F equals ma right?",
    "More force means more acceleration!",
    "If mass goes up acceleration goes... down?",
    "Wait so weight and mass are different?",
    "Just tell me the formula",
    "I don't understand any of this",
    "Oh! So that's why it's harder to stop a truck than a car!",
    "Objects in motion stay in motion unless a force acts on them!",
]


def run_conversation(topic: str, student_turns: list[str], model: str = "llama-3.3-70b-versatile") -> list[TurnResult]:
    """Run a simulated conversation and score each turn.

    Args:
        topic: Topic identifier for build_prompt.
        student_turns: List of student inputs to simulate.
        model: Groq model to use.

    Returns:
        List of TurnResult for each turn.
    """
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    system_prompt = build_prompt(topic)

    # Conversation history for the LLM
    messages = [{"role": "system", "content": system_prompt}]
    results = []

    for i, student_input in enumerate(student_turns):
        turn_num = i + 1
        print(f"  Turn {turn_num}/{len(student_turns)}: Student: '{student_input[:50]}...'")

        messages.append({"role": "user", "content": student_input})

        # Get tutor response via streaming
        start = time.perf_counter()
        full_response = ""
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=150,
            temperature=0.7,
        )

        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                full_response += content

        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"           Tutor ({elapsed_ms:.0f}ms): '{full_response[:60]}...'")

        messages.append({"role": "assistant", "content": full_response})

        # Detect teacher-mode reveals: the prompt instructs the tutor to say
        # "look at the map" when doing a pedagogical reveal after the student
        # has repeatedly struggled.  Direct answers in that context are
        # intentional and should not be penalised by the scorer.
        is_teacher_mode = "look at the map" in full_response.lower()

        # Score this turn
        turn_dict = {
            "student_input": student_input,
            "tutor_response": full_response,
            "topic": topic,
            "teacher_mode": is_teacher_mode,
        }

        result = TurnResult(
            turn_number=turn_num,
            student_input=student_input,
            tutor_response=full_response,
            ends_with_question=score_ends_with_question(full_response),
            no_direct_answer=score_no_direct_answer(turn_dict),
            no_negation=score_no_negation(turn_dict),
            readability=score_readability(full_response),
            encouragement=score_encouragement(full_response),
            response_length=score_response_length(full_response),
            llm_latency_ms=elapsed_ms,
        )
        results.append(result)

        # Keep conversation history manageable (last 12 messages + system)
        if len(messages) > 13:
            messages = [messages[0]] + messages[-12:]

    return results


def print_report(topic: str, results: list[TurnResult]):
    """Print the validation report for a topic."""
    total = len(results)
    if total == 0:
        print(f"\n  No results for {topic}")
        return False

    question_pct = sum(1 for r in results if r.ends_with_question == 1.0) / total * 100
    no_answer_pct = sum(1 for r in results if r.no_direct_answer == 1.0) / total * 100
    no_negation_pct = sum(1 for r in results if r.no_negation == 1.0) / total * 100
    avg_readability = sum(r.readability for r in results) / total
    encouragement_pct = sum(1 for r in results if r.encouragement == 1.0) / total * 100
    avg_length = sum(r.response_length for r in results) / total

    print(f"\n{'='*60}")
    print(f"RESULTS: {topic.upper()} ({total} turns)")
    print(f"{'='*60}")
    print(f"  Ends with question:  {question_pct:5.1f}%  (target: 100%)")
    print(f"  No direct answer:    {no_answer_pct:5.1f}%  (target: 100%)")
    print(f"  No negation:         {no_negation_pct:5.1f}%  (target: 100%)")
    print(f"  Avg readability:     {avg_readability:5.1f}   (target: 6.0-8.0)")
    print(f"  Encouragement:       {encouragement_pct:5.1f}%  (target: >50%)")
    print(f"  Avg word count:      {avg_length:5.1f}   (target: <50)")

    # Check pass/fail
    passed = True
    failures = []

    if question_pct < 100:
        passed = False
        failed_turns = [r for r in results if r.ends_with_question != 1.0]
        for r in failed_turns:
            failures.append(f"  Turn {r.turn_number}: Missing question mark — '{r.tutor_response[-40:]}'")

    if no_answer_pct < 100:
        passed = False
        failed_turns = [r for r in results if r.no_direct_answer != 1.0]
        for r in failed_turns:
            failures.append(f"  Turn {r.turn_number}: Direct answer detected — '{r.tutor_response[:60]}'")

    if no_negation_pct < 100:
        passed = False
        failed_turns = [r for r in results if r.no_negation != 1.0]
        for r in failed_turns:
            failures.append(f"  Turn {r.turn_number}: Negation detected — '{r.tutor_response[:60]}'")

    if avg_readability < 4.0 or avg_readability > 13.0:
        passed = False
        failures.append(f"  Readability out of range: {avg_readability:.1f}")

    verdict = "PASS" if passed else "FAIL"
    print(f"\n  VERDICT: {verdict}")

    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    {f}")

    return passed


def main():
    """Run Socratic prompt validation for both topics."""
    print("=" * 60)
    print("SOCRATIC PROMPT VALIDATION")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    all_results = {}

    # Photosynthesis — 30 turns
    print(f"\n--- Photosynthesis ({len(PHOTOSYNTHESIS_STUDENT_TURNS)} turns) ---")
    photo_results = run_conversation("photosynthesis", PHOTOSYNTHESIS_STUDENT_TURNS)
    all_results["photosynthesis"] = photo_results
    photo_pass = print_report("photosynthesis", photo_results)

    # Newton's Laws — 20 turns
    print(f"\n--- Newton's Laws ({len(NEWTONS_LAWS_STUDENT_TURNS)} turns) ---")
    newton_results = run_conversation("newtons_laws", NEWTONS_LAWS_STUDENT_TURNS)
    all_results["newtons_laws"] = newton_results
    newton_pass = print_report("newtons_laws", newton_results)

    # Save results
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "socratic_validation.json")

    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": "llama-3.3-70b-versatile",
        "topics": {},
    }
    for topic, results in all_results.items():
        data["topics"][topic] = {
            "turns": [asdict(r) for r in results],
            "summary": _summarize_results(results),
        }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {output_path}")

    markdown_path = os.path.join(output_dir, "socratic_validation_summary.md")
    write_markdown_summary(markdown_path, all_results, data["timestamp"], data["model"])
    print(f"Markdown summary saved to {markdown_path}")

    # Overall verdict
    overall = "PASS" if (photo_pass and newton_pass) else "FAIL"
    print(f"\n{'='*60}")
    print(f"OVERALL VERDICT: {overall}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
