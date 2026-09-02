"""Grades the 3-way routing decision, not a yes/no trigger.

Our three descriptions all say "functualize", so a binary "did it fire" test
passes trivially and tells us nothing. What matters is which one won, and
whether the near-miss prompts leave all three alone.

Config:
    expect: the skill that should load, or null for "none of ours should"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import as_record, result  # noqa: E402


def get_assert(output, context) -> dict:
    record = as_record(output)

    # From `vars`, NOT from the assertion's `config`: promptfoo renders test
    # vars but passes assertion config through verbatim, so `{{expect}}` in a
    # config block arrives as the literal five-character template and every
    # comparison fails. `config` stays as a fallback for static values.
    variables = (context or {}).get("vars") or {}
    config = (context or {}).get("config") or {}
    expected = variables.get("expect", config.get("expect"))

    if isinstance(expected, str) and (
        expected.strip().lower() in {"", "null", "none"} or "{{" in expected
    ):
        expected = None
    selected = record.get("selected")
    loaded = record.get("skills_loaded") or []

    if expected is None:
        if not record.get("any_fired"):
            return result(
                True, f"Correctly stayed out of it (loaded: {loaded or 'nothing'})"
            )
        return result(
            False, f"False positive — loaded {selected} on a near-miss prompt"
        )

    if selected == expected:
        return result(True, f"Routed to {expected}")

    if selected is None:
        return result(False, f"Expected {expected}, but no functualize skill fired")

    # Partial credit: a functualize skill fired, just not the best one. That is
    # a description-overlap problem, meaningfully better than silence.
    return result(False, f"Expected {expected}, got {selected}", score=0.3)
