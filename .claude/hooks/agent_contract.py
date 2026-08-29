#!/usr/bin/env python3
"""PreToolUse on Agent: give the built-in Plan agent the contract it cannot load.

Contract: .spec/features/spec-workflow-enforcement/contracts.md section C3.

The built-in Plan agent does not read CLAUDE.md, AGENTS.md, or .claude/rules/,
so it plans this repository blind to the workflow. Explore, the default agent,
and spec-driven-developer are left alone.

CRITICAL (contracts.md C3-RULE): `updatedInput` replaces the ENTIRE input
object, so it is built by shallow-copying what arrived and mutating only
`prompt`. It must never enumerate known keys. The documented key list is wrong
in this build -- `model` is absent unless explicitly passed, and an undocumented
`run_in_background` is present -- so an enumerating implementation would drop a
real field and inject one that was never set.
"""

import json
import sys

CONTRACT = """\
Context on this repository before planning:

Non-trivial work here is specified before it is built. A feature lives in
`.spec/features/<name>/` as `spec.md` (behavior), `contracts.md` (external
interfaces), `plan.md` (technical approach), and `tasks.md` (atomized tasks
ending in a `## Task Dependency Graph` JSON wave list). Those artifacts are
produced by `/agentic-specify` and `/agentic-plan`.

Modifying `src/functualize/**` or `plugins/*/src/**` requires an existing
`tasks.md` with a wave graph, or a declared exemption in `.spec/EXEMPT`. A plan
that proposes editing shipped code without one describes work that cannot
proceed as written.

Acceptance criteria in this repository are executable gates, run when the task
is authored, with the task's file scope equal to the gate's hit set.

`AGENTS.md` carries the project's commands, architecture, and constraints.
`.spec/CONSTITUTION.md` carries the non-negotiables.
"""


def main():
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    if tool_input.get("subagent_type") != "Plan":
        return  # Explore, spec-driven-developer, default agent: untouched

    updated = dict(tool_input)  # every field, including undocumented ones
    prompt = updated.get("prompt")
    updated["prompt"] = CONTRACT + "\n\n" + (prompt if isinstance(prompt, str) else "")

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": updated,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
