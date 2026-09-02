"""Checks that a produced SKILL.md stays on the portable frontmatter fields.

`functualize-skill` §2 says the Agent Skills spec defines exactly six fields
and that inventing a seventh is a portability bug. That is mechanically
checkable, so it should never be an LLM's judgment call.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import as_record, result  # noqa: E402

PORTABLE_FIELDS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:", re.MULTILINE)


def get_assert(output, context) -> dict:
    record = as_record(output)
    skill_files = {
        path: body
        for path, body in (record.get("files") or {}).items()
        if path.endswith("SKILL.md")
    }

    if not skill_files:
        return result(False, "No SKILL.md was produced")

    problems: list[str] = []
    for path, body in skill_files.items():
        match = FRONTMATTER.match(body)
        if not match:
            problems.append(f"{path}: no YAML frontmatter block")
            continue

        block = match.group(1)
        # The pattern is anchored at column 0, so nested keys under `metadata:`
        # are already excluded.
        keys = set(TOP_LEVEL_KEY.findall(block))

        for required in ("name", "description"):
            if required not in keys:
                problems.append(f"{path}: missing required `{required}`")

        for extra in sorted(keys - PORTABLE_FIELDS):
            problems.append(f"{path}: non-portable field `{extra}`")

        # The spec requires `name` to match the containing directory.
        declared = re.search(r"^name:\s*(\S+)", block, re.MULTILINE)
        directory = Path(path).parent.name
        if declared and directory and declared.group(1).strip("'\"") != directory:
            problems.append(
                f"{path}: name `{declared.group(1)}` does not match directory `{directory}`"
            )

    if problems:
        return result(False, "; ".join(problems))
    return result(True, f"{len(skill_files)} SKILL.md file(s) use only portable fields")
