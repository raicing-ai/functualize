"""promptfoo provider: a full agentic Claude Code run in a sandboxed workspace.

Returns a structured record rather than prose, because the interesting
questions about a skill are not "what did it say" but "which tools did it
reach for" and "does the code it wrote actually run".

Provider config (from the suite YAML):
    with_skills:   mount ../skills into the workspace (the ablation switch)
    sandbox:       'docker' (default) or 'host' — see evals/README.md
    max_turns / timeout_s / allowed_tools / model: budget knobs

Per-case data comes from test `vars`, so each case owns its own fixture and
verification commands:
    fixture:  directory under evals/fixtures/ to seed the workspace with
    checks:   shell commands run in the workspace afterwards
    setup:    shell commands run *before* the agent (e.g. `uv sync`)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (  # noqa: E402
    build_workspace,
    collect_files,
    log_progress,
    resolve_sandbox_mode,
    run_check,
    run_claude,
)

# What to leave on disk for poking at afterwards. Extracted files (see
# `npm run inspect -- --extract`) exclude the built .venv, so keeping the real
# workspace is the way to re-run a failing check by hand.
KEEP_WORKSPACES = os.environ.get("FZ_EVAL_KEEP", "failed").lower()

# Containment is the default for an agent that gets a shell; opting out has to
# be deliberate. See the safety note in evals/README.md before setting
# FZ_EVAL_SANDBOX=host.
DEFAULT_SANDBOX = "docker"


def _clean(value) -> str | None:
    """YAML `null` reaches us as a rendered template string, not as None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if stripped.lower() in {"", "null", "none"} else stripped


def _as_commands(value) -> list[str]:
    """Normalise a `setup`/`checks` var into a list of shell commands.

    A list-valued promptfoo var is a *var-expansion axis*, not a list value, so
    without `options.disableVarExpansion` the suite's `checks: [...]` arrives
    here as a bare string. `for cmd in "uv sync"` then iterates CHARACTERS and
    launches one container per letter — every case burning ~36 container starts
    on `u`, `v`, `s`, `y`, … while the real `uv sync` never runs and the agent
    starts in a workspace with no `.venv`.

    The suites set `disableVarExpansion`, but the failure is silent and looks
    like a broken skill rather than a broken harness, so refuse to iterate a
    string here regardless of what the suite did.
    """
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(item) for item in value]


def call_api(prompt: str, options: dict, context: dict) -> dict:
    config = (options or {}).get("config", {}) or {}
    variables = (context or {}).get("vars", {}) or {}

    fixture = _clean(variables.get("fixture")) or _clean(config.get("fixture"))
    checks = _as_commands(variables.get("checks") or config.get("checks"))
    setup = _as_commands(variables.get("setup") or config.get("setup"))
    with_skills = bool(config.get("with_skills", True))

    try:
        mode = resolve_sandbox_mode(config.get("sandbox"), DEFAULT_SANDBOX)
        workspace, sandbox = build_workspace(fixture, with_skills, mode=mode)
    except (FileNotFoundError, RuntimeError) as exc:
        return {"error": str(exc)}

    keep = False
    try:
        for command in setup:
            run_check(sandbox, command, timeout_s=600)

        run = run_claude(
            sandbox,
            prompt,
            # Env overrides the suite, matching FZ_EVAL_SANDBOX. The reverse
            # makes the knob inert the moment a suite pins a value.
            model=os.environ.get("FZ_EVAL_MODEL") or config.get("model"),
            max_turns=int(config.get("max_turns", 30)),
            allowed_tools=config.get("allowed_tools"),
            timeout_s=int(config.get("timeout_s", 900)),
        )

        check_results = [run_check(sandbox, cmd) for cmd in checks]
        failed = run.error is not None or any(
            c["exit_code"] != 0 for c in check_results
        )
        keep = KEEP_WORKSPACES == "all" or (KEEP_WORKSPACES == "failed" and failed)
        if keep:
            log_progress(f"  kept workspace {workspace}")

        return {
            "output": {
                "arm": "with-skills" if with_skills else "baseline",
                "sandbox": mode,
                "text": run.text,
                "error": run.error,
                "skills_loaded": run.skills_loaded,
                "tools_used": sorted({c["name"] for c in run.tool_calls}),
                "bash_commands": run.bash_commands(),
                "tool_calls": run.tool_calls,
                "checks": check_results,
                "files": collect_files(workspace),
                "num_turns": run.num_turns,
                "workspace": str(workspace) if keep else None,
            },
            "cost": run.cost_usd,
        }
    finally:
        if not keep:
            shutil.rmtree(workspace, ignore_errors=True)
        if sandbox.agent_home:
            shutil.rmtree(sandbox.agent_home, ignore_errors=True)
