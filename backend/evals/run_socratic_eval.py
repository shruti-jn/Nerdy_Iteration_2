"""
Socratic Eval runner — automated quality evaluation across topics.

Run via:
    python -m evals.run_socratic_eval                 # all topics, 30/20 turns
    python -m evals.run_socratic_eval --topic photosynthesis
    python -m evals.run_socratic_eval --turns 10      # smoke test (10 turns per topic)
    python -m evals.run_socratic_eval --topic newtons_laws --turns 5

Artifacts written to evals/results/:
    socratic_validation.json         -- machine-readable per-turn scores
    socratic_validation_summary.md   -- human-readable markdown table

Exit code:
    0  — all topics PASS
    1  — at least one topic FAILs (for CI)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone

# Ensure backend package root is importable when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.validate_socratic_prompt import (
    PHOTOSYNTHESIS_STUDENT_TURNS,
    NEWTONS_LAWS_STUDENT_TURNS,
    TurnResult,
    _summarize_results,
    _passes_thresholds,
    print_report,
    run_conversation,
    write_markdown_summary,
)


_TOPICS: dict[str, list[str]] = {
    "photosynthesis": PHOTOSYNTHESIS_STUDENT_TURNS,
    "newtons_laws": NEWTONS_LAWS_STUDENT_TURNS,
}

_DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Socratic quality eval.")
    p.add_argument(
        "--topic",
        choices=list(_TOPICS.keys()),
        default=None,
        help="Single topic to evaluate (default: all topics)",
    )
    p.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Limit turns per topic (default: full scenario bank)",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Groq model (default: {_DEFAULT_MODEL})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    topics_to_run = {args.topic: _TOPICS[args.topic]} if args.topic else _TOPICS

    print("=" * 60)
    print("SOCRATIC PROMPT VALIDATION")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"Timestamp: {timestamp}")
    print(f"Model:     {args.model}")
    print("=" * 60)

    all_results: dict[str, list[TurnResult]] = {}
    all_passed = True

    for topic, student_turns in topics_to_run.items():
        turns = student_turns[: args.turns] if args.turns else student_turns
        print(f"\n--- {topic} ({len(turns)} turns) ---")
        results = run_conversation(topic, turns, model=args.model)
        all_results[topic] = results
        topic_passed = print_report(topic, results)
        all_passed = all_passed and topic_passed

    # --- Write JSON artifact ---
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(output_dir, exist_ok=True)

    data = {
        "timestamp": timestamp,
        "model": args.model,
        "topics": {
            topic: {
                "turns": [asdict(r) for r in results],
                "summary": _summarize_results(results),
            }
            for topic, results in all_results.items()
        },
    }
    json_path = os.path.join(output_dir, "socratic_validation.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {json_path}")

    # --- Write markdown summary ---
    md_path = os.path.join(output_dir, "socratic_validation_summary.md")
    write_markdown_summary(md_path, all_results, timestamp, args.model)
    print(f"Markdown summary saved to {md_path}")

    # --- Final verdict ---
    verdict = "PASS" if all_passed else "FAIL"
    print(f"\n{'=' * 60}")
    print(f"OVERALL VERDICT: {verdict}")
    print(f"{'=' * 60}")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
