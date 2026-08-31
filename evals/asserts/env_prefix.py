"""Grades section 0 of the functualize skill: the invocation ladder.

The skill claims a repo with `uv.lock` takes `uv run func`, and that guessing
wrong "ends in `command not found` followed by a pip install into the wrong
interpreter". That is a falsifiable claim about agent behaviour, and it is
graded here from the tool-call trace rather than from the final prose.

Config:
    required_prefix:  the prefix the first `func` call must carry
    forbid:           regexes that must appear in no Bash command at all
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import as_record, result  # noqa: E402

DEFAULT_FORBIDDEN = [r"\bpip install\b", r"pip3 install\b"]


def get_assert(output, context) -> dict:
    record = as_record(output)
    config = (context or {}).get("config") or {}
    required = config.get("required_prefix", "uv run")
    forbidden = config.get("forbid", DEFAULT_FORBIDDEN)

    commands = record.get("bash_commands") or []
    func_calls = [c for c in commands if re.search(r"(^|[;&|]\s*|\s)func\b", c)]

    if not func_calls:
        return result(False, "Agent never invoked `func` at all")

    first = func_calls[0]
    if required not in first:
        return result(
            False,
            f"First `func` call did not use `{required}`: {first[:200]}",
        )

    for pattern in forbidden:
        for command in commands:
            if re.search(pattern, command):
                return result(
                    False,
                    f"Ran a forbidden command matching /{pattern}/: {command[:200]}",
                )

    not_found = [
        c
        for c in record.get("checks") or []
        if "command not found" in (c.get("stderr") or "")
    ]
    if not_found:
        return result(False, "A verification command hit `command not found`")

    return result(True, f"Resolved the prefix first try: {first[:120]}")
