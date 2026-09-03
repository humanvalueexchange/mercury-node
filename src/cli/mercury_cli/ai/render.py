"""Operator-facing rendering for local AI answers."""

from __future__ import annotations

import sys


def print_answer(question: str, answer: str) -> None:
    print("\n🤖 Mercury AI  (Local)")
    print("─" * 55)
    print(f"  Q: {question}\n")
    print(f"  A: {answer}\n")


def debug_timings(timings: dict[str, int]) -> None:
    if timings:
        print("Mercury AI timings: " + ", ".join(f"{key}={value}ms" for key, value in timings.items()), file=sys.stderr)
