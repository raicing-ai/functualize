"""promptfoo provider: a cheap probe for *which* skill a prompt selects.

Triggering is a separate failure mode from task quality. A perfect skill that
never loads scores zero in real use, and our four skills have deliberately
overlapping descriptions, so the question is not "did functualize fire" but
"did the right one of the four win".

The agent gets only read-only tools and is asked for a brief answer, so a run
is a handful of turns instead of thirty. With no Bash and no write tools there
is nothing to contain, so this provider defaults to `sandbox: host` and does
not need the container image built.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import build_workspace, resolve_sandbox_mode, run_claude  # noqa: E402

# Two ways this instruction has already been got wrong, both of which made the
# probe measure nothing:
#
# 1. "Do not run commands, do not read files" suppresses the Skill tool too,
#    so the agent answers from memory and nothing ever fires.
# 2. Asking "how *would* you approach this" invites a hypothetical, and the
#    agent narrates — "I'd load the functualize-app skill" — without loading
#    it. That reads as a routing failure when routing was in fact correct.
#
# So: imperative, present tense, no conditional. Start the work for real; the
# only prohibition is on changing anything. And no nudge toward skills, or the
# near-miss cases lose their ability to fail.
STOP_INSTRUCTION = (
    "\n\n---\nBegin now. Do your normal first step, then stop and say in one "
    "sentence what you did. Do not create or modify any files."
)

# Read-only, so the agent behaves as it would in a real session instead of
# discovering it has no tools and answering from memory. Nothing here can
# change the workspace.
ROUTER_TOOLS = ["Skill", "Read", "Glob", "Grep"]

# Safe on the host: read-only tools only, so there is nothing to contain and no
# image to build. FZ_EVAL_SANDBOX still overrides, so `FZ_EVAL_SANDBOX=docker`
# containerises the whole directory uniformly.
DEFAULT_SANDBOX = "host"


def call_api(prompt: str, options: dict, _context: dict) -> dict:
    config = (options or {}).get("config", {}) or {}
    try:
        mode = resolve_sandbox_mode(config.get("sandbox"), DEFAULT_SANDBOX)
        workspace, sandbox = build_workspace(
            config.get("fixture"), with_skills=True, mode=mode
        )
    except (FileNotFoundError, RuntimeError) as exc:
        return {"error": str(exc)}

    try:
        run = run_claude(
            sandbox,
            prompt + STOP_INSTRUCTION,
            # Env overrides the suite, matching FZ_EVAL_SANDBOX. The reverse
            # makes the knob inert the moment a suite pins a value.
            model=os.environ.get("FZ_EVAL_MODEL") or config.get("model"),
            max_turns=int(config.get("max_turns", 4)),
            allowed_tools=config.get("allowed_tools") or ROUTER_TOOLS,
            timeout_s=int(config.get("timeout_s", 180)),
        )
        ours = [s for s in run.skills_loaded if s.startswith("functualize")]
        return {
            "output": {
                "skills_loaded": run.skills_loaded,
                "selected": ours[0] if ours else None,
                "any_fired": bool(ours),
                "text": run.text,
                "error": run.error,
            },
            "cost": run.cost_usd,
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if sandbox.agent_home:
            shutil.rmtree(sandbox.agent_home, ignore_errors=True)
