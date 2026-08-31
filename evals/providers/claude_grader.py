"""promptfoo grading provider that authenticates the way the rest of the suite does.

`llm-rubric` defaults to calling **gpt-5 over the OpenAI API** — a completely
separate credential from the one the agent runs on. With no `OPENAI_API_KEY`
every rubric fails at the grader, which reads as a failing skill:

    ✖ contributor question — fires, but redirects
      got=['functualize']                        ← the skill was right
      → API call error: Invalid resource field value in the request.

A subscription OAuth token cannot rescue that either: it authenticates Claude
Code, not the raw Anthropic API. So the grader goes back through `claude -p`,
exactly like the agent, and one credential covers the whole suite.

Wire it up per suite:

    defaultTest:
      options:
        provider: file://../providers/claude_grader.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import build_workspace, log_progress, run_claude  # noqa: E402

# Graders are judges, not agents: no skills mounted (they would bias the
# verdict), no tools, and a small turn budget.
FORMAT_INSTRUCTION = (
    "\n\nRespond with a single JSON object and nothing else, in the form "
    '{"pass": true or false, "score": 0.0 to 1.0, "reason": "one sentence"}.'
)

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _verdict(text: str) -> dict:
    """Pull the grader's JSON out of whatever it wrapped it in."""
    match = JSON_BLOCK.search(text or "")
    if not match:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"grader returned no JSON: {(text or '')[:200]}",
        }
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"grader JSON did not parse: {match.group(0)[:200]}",
        }
    passed = bool(parsed.get("pass"))
    return {
        "pass": passed,
        "score": float(parsed.get("score", 1.0 if passed else 0.0)),
        "reason": str(parsed.get("reason", "")),
    }


def call_api(prompt: str, options: dict, _context: dict) -> dict:
    config = (options or {}).get("config", {}) or {}
    workspace, sandbox = build_workspace(None, with_skills=False, mode="host")
    try:
        run = run_claude(
            sandbox,
            prompt + FORMAT_INSTRUCTION,
            model=os.environ.get("FZ_EVAL_GRADER_MODEL")
            or config.get("model")
            or "claude-sonnet-5",
            max_turns=2,
            allowed_tools=[],
            timeout_s=int(config.get("timeout_s", 180)),
        )
        if run.error:
            log_progress(f"✖ grader {run.error[:80]}")
            return {"error": f"grader failed: {run.error}"}

        verdict = _verdict(run.text)
        log_progress(
            f"⚖ grade {'pass' if verdict['pass'] else 'FAIL'} · {verdict['reason'][:60]}"
        )
        # promptfoo parses the grader's JSON out of `output`.
        return {"output": json.dumps(verdict), "cost": run.cost_usd}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if sandbox.agent_home:
            shutil.rmtree(sandbox.agent_home, ignore_errors=True)
