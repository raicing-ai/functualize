"""Grades what the agent *did*, from the tool-call trace.

The functualize skill's central instruction is "Never guess — the app
describes itself at runtime." That is only observable in the trace: an agent
that ran `func builtin` before answering behaved correctly even if its prose
was identical to one that guessed.

Config:
    require_bash:  [{pattern, label}]  at least one Bash command must match
    forbid_bash:   [{pattern, label}]  no Bash command may match
    require_tools: ["Skill", ...]      tools that must have been used
    forbid_tools:  ["WebFetch", ...]   tools that must not have been used
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import as_record, result  # noqa: E402


def get_assert(output, context) -> dict:
    record = as_record(output)
    config = (context or {}).get("config") or {}

    commands = record.get("bash_commands") or []
    tools = set(record.get("tools_used") or [])
    problems: list[str] = []
    total = 0

    for rule in config.get("require_bash", []):
        total += 1
        compiled = re.compile(rule["pattern"])
        if not any(compiled.search(c) for c in commands):
            problems.append(f"never ran: {rule.get('label', rule['pattern'])}")

    for rule in config.get("forbid_bash", []):
        total += 1
        compiled = re.compile(rule["pattern"])
        offender = next((c for c in commands if compiled.search(c)), None)
        if offender:
            problems.append(
                f"ran forbidden {rule.get('label', rule['pattern'])}: {offender[:120]}"
            )

    for name in config.get("require_tools", []):
        total += 1
        if name not in tools:
            problems.append(f"never used tool {name}")

    for name in config.get("forbid_tools", []):
        total += 1
        if name in tools:
            problems.append(f"used forbidden tool {name}")

    if not problems:
        return result(
            True, f"All {total} trace contracts held ({len(commands)} bash calls)"
        )

    return result(
        False,
        f"{len(problems)}/{total} trace contracts failed: {'; '.join(problems)}",
        score=max(0.0, 1.0 - len(problems) / total) if total else 0.0,
    )
