"""Pure logic helpers for the PPC (rock/paper/scissors) command.

Kept Discord-free so it can be tested without a bot token or discord.py installed.
"""

from __future__ import annotations

from dataclasses import dataclass


CHOICES = ("rock", "paper", "scissors")


@dataclass(frozen=True)
class PpcRound:
    a: str
    b: str


def normalize_choice(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in CHOICES:
        raise ValueError(f"Invalid choice: {value!r}")
    return v


def result(a: str, b: str) -> int:
    """Return 0=tie, 1=a wins, -1=b wins."""

    a_n = normalize_choice(a)
    b_n = normalize_choice(b)

    if a_n == b_n:
        return 0

    wins = {
        ("rock", "scissors"),
        ("scissors", "paper"),
        ("paper", "rock"),
    }
    return 1 if (a_n, b_n) in wins else -1
