"""Helpers shared by the assertion modules.

promptfoo hands `output` back as whatever the provider returned. It survives a
JSON round trip, so it may arrive as a dict or as its string encoding; every
assertion normalises through `as_record` first.
"""

from __future__ import annotations

import json
import re


def as_record(output) -> dict:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {"text": output}
        return parsed if isinstance(parsed, dict) else {"text": output}
    return {"text": str(output)}


def result(passed: bool, reason: str, score: float | None = None) -> dict:
    return {
        "pass": passed,
        "score": (1.0 if passed else 0.0) if score is None else score,
        "reason": reason,
    }


def python_sources(record: dict) -> dict[str, str]:
    """Only the .py files the agent produced."""
    return {
        path: body
        for path, body in (record.get("files") or {}).items()
        if path.endswith(".py")
    }


def any_source_matches(record: dict, pattern: str) -> tuple[bool, str]:
    """True if any produced Python file matches `pattern`."""
    compiled = re.compile(pattern)
    for path, body in python_sources(record).items():
        if compiled.search(body):
            return True, path
    return False, ""
