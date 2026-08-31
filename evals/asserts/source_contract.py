"""Greps the produced source for contracts the skill says are wrong by default.

These are the cheapest high-signal graders in the suite: `Secret[str]` either
appears in the job signature or it does not. Use `require` for patterns that
must appear and `forbid` for the plausible-looking wrong answer, because a run
that satisfies neither is a different failure from one that picks the wrong
idiom.

Config:
    require: [{pattern, label}]   at least one produced .py must match each
    forbid:  [{pattern, label}]   no produced .py may match any
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import any_source_matches, as_record, python_sources, result  # noqa: E402


def get_assert(output, context) -> dict:
    record = as_record(output)
    config = (context or {}).get("config") or {}

    sources = python_sources(record)
    if not sources:
        return result(False, "Agent produced no Python files")

    misses: list[str] = []
    hits: list[str] = []

    for rule in config.get("require", []):
        found, where = any_source_matches(record, rule["pattern"])
        (hits if found else misses).append(
            f"{rule.get('label', rule['pattern'])}{f' ({where})' if found else ''}"
        )

    for rule in config.get("forbid", []):
        compiled = re.compile(rule["pattern"])
        for path, body in sources.items():
            if compiled.search(body):
                misses.append(
                    f"forbidden: {rule.get('label', rule['pattern'])} in {path}"
                )
                break

    total = len(config.get("require", [])) + len(config.get("forbid", []))
    if not misses:
        return result(True, f"All {total} source contracts held: {', '.join(hits)}")

    return result(
        False,
        f"{len(misses)}/{total} source contracts failed: {'; '.join(misses)}",
        score=max(0.0, 1.0 - len(misses) / total) if total else 0.0,
    )
