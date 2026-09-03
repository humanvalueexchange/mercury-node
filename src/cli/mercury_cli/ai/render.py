"""Operator-facing rendering for local AI answers."""

from __future__ import annotations

import sys


def print_answer(question: str, answer: str) -> None:
    print("\n🤖 Mercury AI  (Local)")
    print("─" * 55)
    print(f"  Q: {question}\n")
    print(f"  A: {answer}\n")


def debug_timings(timings: dict[str, int | str]) -> None:
    if timings:
        values = []
        for key, value in timings.items():
            suffix = "" if isinstance(value, str) else "ms"
            values.append(f"{key}={value}{suffix}")
        print("Mercury AI timings: " + ", ".join(values), file=sys.stderr)
