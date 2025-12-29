"""Quick self-check for RPS logic.

Run:
  python scripts/ppc_selfcheck.py

This doesn't require discord.py.
"""

from __future__ import annotations

import os
import sys

# Allow running from repo root without installing as a package.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
  sys.path.insert(0, REPO_ROOT)

from src.ppc_logic import result


def main() -> int:
    assert result("rock", "rock") == 0
    assert result("paper", "paper") == 0
    assert result("scissors", "scissors") == 0

    assert result("rock", "scissors") == 1
    assert result("scissors", "paper") == 1
    assert result("paper", "rock") == 1

    assert result("scissors", "rock") == -1
    assert result("paper", "scissors") == -1
    assert result("rock", "paper") == -1

    print("PPC self-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
