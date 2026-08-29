#!/usr/bin/env python3
"""PostToolUse on ExitPlanMode: deliver the execution contract at plan approval.

Contract: .spec/features/spec-workflow-enforcement/contracts.md section C2.

Never blocks. Never emits `decision`. Exits 0 unconditionally: a failure to add
context must not break the session.

The text is written as factual statements about the repository, not as
imperative instructions. Imperative, out-of-band framing trips prompt-injection
defenses, which surfaces the text to the user instead of treating it as context.
"""

import json
import sys

CONTEXT = """\
Execution discipline in this repository, for the plan that was just approved:

Wave ordering is binding. `tasks.md` ends with a `## Task Dependency Graph`
holding a JSON wave list. The current wave is the lowest-numbered one with
unchecked tasks; every task in an earlier wave is already `[x]`. Tasks within a
wave touch disjoint files and may run in any order.

Acceptance criteria are gates, and gates are run against the code as it actually
stands -- not inferred from the task's description of its own final state. A
task whose gate can only pass after a later step is partial: it stays `[ ]`, and
the remainder is recorded rather than absorbed silently.

Reachability precedes marking a task `[x]`. Closing a task includes naming the
production call path that reaches the code it added, verified by breaking that
call and watching a test fail. "A test calls it" is not a call path. This rule
exists because three capabilities shipped built, unit-tested and unreachable
while every gate stayed green.

Sabotage happens after a commit, never before. Restoring with
`git checkout -- <file>` reverts everything uncommitted in that file, so
sabotaging uncommitted work discards it.

`.spec/STATE.md` is updated after each task, and records wave transitions.

Modifying `src/functualize/**` or `plugins/*/src/**` requires an atomized task
list on disk. Writes to `.spec/`, `tests/`, `docs/`, and `contributor/` are not
gated, so the Specify and Plan phases operate normally.
"""


def main():
    payload = json.load(sys.stdin)
    plan = payload.get("tool_response", {}).get("plan")
    if not isinstance(plan, str) or not plan.strip():
        return  # nothing was approved; nothing to contextualize
    text = CONTEXT
    if len(text) > 9500:  # stay well under the 10000-char file-spill threshold
        text = text[:9500]
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": text,
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
