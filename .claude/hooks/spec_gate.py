#!/usr/bin/env python3
"""PreToolUse gate: no shipped-code edit without an atomized task list.

Contract: .spec/features/spec-workflow-enforcement/contracts.md section C1.

Invariants this file must never lose:
  * It ALWAYS exits 0, including on internal error. Exit code 2 routes as
    `deny` with stderr as the reason, so a crash here would block every write
    in the repository. A validator that cannot decide must not decide.
  * It resolves paths from the hook input's `cwd`, never ${CLAUDE_PROJECT_DIR},
    which stays pinned to the session's origin root across worktrees.
  * It never emits permissionDecision "allow" -- a pass is silence, so normal
    permission handling still applies.
  * Standard library only. It runs outside the project venv, in clean clones.
"""

import json
import os
import re
import sys

# Paths whose modification requires a task list. Shipped code only: tests,
# per-plugin tests, conftest, packaging metadata and docs are deliberately free.
GATED_DIR = "src/functualize"
GATED_GLOB_PARTS = ("plugins", "src")  # plugins/<pkg>/src/**

REASON_NO_FEATURES = (
    "This repository requires an atomized task list before shipped code is "
    "modified, and no `.spec/features/` directory exists yet.\n\n"
    "Produce one with `/agentic-specify` then `/agentic-plan`. The plan phase "
    "writes `.spec/features/<name>/tasks.md` ending in a `## Task Dependency "
    "Graph` section.\n\n"
    "Writes to `.spec/`, `tests/`, `docs/`, and `contributor/` are not gated, "
    "so the spec and plan phases work normally."
)
REASON_NO_TASKS = (
    "A `.spec/features/` directory exists but contains no `tasks.md`.\n\n"
    "The Specify phase has run; the Plan phase has not. Run `/agentic-plan` to "
    "produce `.spec/features/<name>/tasks.md`."
)
REASON_NO_GRAPH = (
    "A `tasks.md` exists but carries no parseable `## Task Dependency Graph`.\n\n"
    "The section must end the file and contain a fenced ```json block shaped "
    'like {"waves": [{"id": 0, "tasks": ["1.1"]}]}. Wave ordering is what the '
    "Execute phase reads to decide which task is next, so a task list without "
    "it cannot be executed as designed. Add the graph."
)


def deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


def is_gated(file_path, cwd):
    """True when file_path is shipped code inside cwd.

    Uses resolved real paths and commonpath, never a string prefix: a prefix
    test would let `src/functualize_extra/` through and would follow a symlink
    planted inside the gated tree.
    """
    target = os.path.realpath(os.path.join(cwd, file_path))
    root = os.path.realpath(cwd)

    def contained(base):
        try:
            return os.path.commonpath([target, base]) == base
        except ValueError:  # different drives / unrelated roots
            return False

    if contained(os.path.realpath(os.path.join(root, GATED_DIR))):
        return True

    plugins_root = os.path.realpath(os.path.join(root, "plugins"))
    if not contained(plugins_root):
        return False
    rel = os.path.relpath(target, plugins_root).split(os.sep)
    # plugins/<pkg>/src/... -> gated. plugins/<pkg>/tests/..., conftest -> free.
    return len(rel) >= 3 and rel[1] == "src"


def has_wave_graph(text):
    head, sep, tail = text.rpartition("## Task Dependency Graph")
    if not sep:
        return False
    m = re.search(r"```json\s*\n(.*?)\n\s*```", tail, re.S)
    if not m:
        return False
    try:
        waves = json.loads(m.group(1)).get("waves")
    except Exception:
        return False
    return (
        isinstance(waves, list)
        and len(waves) > 0
        and all(isinstance(w, dict) and "id" in w and "tasks" in w for w in waves)
    )


def survey_features(cwd):
    """Return (any_feature_dir, any_tasks_md, any_valid_graph)."""
    root = os.path.join(cwd, ".spec", "features")
    if not os.path.isdir(root):
        return False, False, False
    any_dir = any_tasks = any_graph = False
    with os.scandir(root) as entries:
        for e in entries:
            if not e.is_dir():
                continue
            any_dir = True
            tasks = os.path.join(e.path, "tasks.md")
            if not os.path.isfile(tasks):
                continue
            any_tasks = True
            try:
                with open(tasks, encoding="utf-8") as fh:
                    if has_wave_graph(fh.read()):
                        any_graph = True
                        return any_dir, any_tasks, any_graph
            except OSError:
                continue
    return any_dir, any_tasks, any_graph


def main():
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd")
    file_path = payload.get("tool_input", {}).get("file_path")
    if not isinstance(cwd, str) or not isinstance(file_path, str):
        return
    if not is_gated(file_path, cwd):
        return

    _, _, any_graph = survey_features(cwd)
    if any_graph:
        return

    any_dir, any_tasks, _ = survey_features(cwd)
    if not any_dir:
        deny(REASON_NO_FEATURES)
    elif not any_tasks:
        deny(REASON_NO_TASKS)
    else:
        deny(REASON_NO_GRAPH)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: a validator that cannot decide must not decide
    sys.exit(0)
