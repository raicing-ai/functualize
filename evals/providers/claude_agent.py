"""promptfoo provider: a full agentic Claude Code run in a sandboxed workspace.

Returns a structured record rather than prose, because the interesting
questions about a skill are not "what did it say" but "which tools did it
reach for" and "does the code it wrote actually run".

Provider config (from the suite YAML):
    with_skills:   mount ../skills into the workspace (the ablation switch)
    arm:           'load-everything' | 'native' | 'router' — the skill-router
                   suite's three treatments; setting it replaces `with_skills`
    sandbox:       'docker' (default) or 'host' — see evals/README.md
    max_turns / timeout_s / allowed_tools / model: budget knobs

Per-case data comes from test `vars`, so each case owns its own fixture and
verification commands:
    fixture:  directory under evals/fixtures/ to seed the workspace with
    checks:   shell commands run in the workspace afterwards
    setup:    shell commands run *before* the agent (e.g. `uv sync`)
    case:     the selection id, read only by the `router` arm
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (  # noqa: E402
    SKILLS,
    build_workspace,
    collect_files,
    log_progress,
    resolve_sandbox_mode,
    run_check,
    run_claude,
    skill_bodies,
)

# What to leave on disk for poking at afterwards. Extracted files (see
# `npm run inspect -- --extract`) exclude the built .venv, so keeping the real
# workspace is the way to re-run a failing check by hand.
KEEP_WORKSPACES = os.environ.get("FZ_EVAL_KEEP", "failed").lower()

# Containment is the default for an agent that gets a shell; opting out has to
# be deliberate. See the safety note in evals/README.md before setting
# FZ_EVAL_SANDBOX=host.
DEFAULT_SANDBOX = "docker"

# The router suite's three treatments. A selection is only meaningful against
# something, and the two baselines answer different questions: `native` is
# today's product, `load-everything` is what a router has to beat.
ARMS = ("load-everything", "native", "router")

# The router arm's whole input: the file the `select` command (C-7) writes.
SELECTIONS_ENV = "FZ_SKILL_ROUTER_SELECTIONS"


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


def _override_refusal(arm: str, config: dict) -> str | None:
    """Refuse an env knob that would make the arms incomparable.

    `FZ_EVAL_MODEL` and `FZ_EVAL_SANDBOX` exist to override a suite that pins
    nothing, and they still do elsewhere. Under an arm the config *is* the
    treatment: one arm running a different model or sandbox turns the delta
    between arms — the entire result — into noise, and it does so silently.
    Checked before any workspace exists, so a bad override costs nothing.
    """
    model = _clean(config.get("model"))
    sandbox = config.get("sandbox")
    sandbox = sandbox.strip().lower() if isinstance(sandbox, str) else DEFAULT_SANDBOX

    env_model = (os.environ.get("FZ_EVAL_MODEL") or "").strip()
    if env_model and env_model != model:
        return (
            f"override refused: FZ_EVAL_MODEL={env_model!r} but arm {arm!r} is "
            f"configured for {model or 'no model'}. An arm runs on the model "
            "its config names, or the arms are not comparable."
        )

    env_sandbox = (os.environ.get("FZ_EVAL_SANDBOX") or "").strip()
    if env_sandbox and env_sandbox.lower() != sandbox:
        return (
            f"override refused: FZ_EVAL_SANDBOX={env_sandbox!r} but arm {arm!r} "
            f"is configured for {sandbox!r}. An arm runs on the sandbox its "
            "config names, or the arms are not comparable."
        )
    return None


def _router_outcome(case: str | None) -> tuple[str | None, str | None]:
    """The `select` command's verdict for one case, or why it is unavailable.

    Read from `SELECTIONS_ENV`, the file C-7 writes. A missing
    variable, an unreadable file or an unselected case is reported rather than
    papered over with the native toolset — a router arm that silently fell back
    would be indistinguishable from the native arm while claiming to route.
    """
    path = os.environ.get(SELECTIONS_ENV)
    if not path:
        return None, (f"the router arm needs {SELECTIONS_ENV}=<run>/selections.json")
    if not case:
        return None, "the router arm needs a `case` var on every test"
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return None, f"cannot read selections from {path}: {exc}"

    entry = (payload.get("cases") or {}).get(case)
    if not isinstance(entry, dict) or not entry.get("outcome"):
        return None, f"no selection for case {case!r} in {path}"
    return str(entry["outcome"]), None


def call_api(prompt: str, options: dict, context: dict) -> dict:
    config = (options or {}).get("config", {}) or {}
    variables = (context or {}).get("vars", {}) or {}

    fixture = _clean(variables.get("fixture")) or _clean(config.get("fixture"))
    checks = _as_commands(variables.get("checks") or config.get("checks"))
    setup = _as_commands(variables.get("setup") or config.get("setup"))

    arm = _clean(config.get("arm"))
    if arm is not None and arm not in ARMS:
        return {"error": f"unknown arm {arm!r}; expected one of {', '.join(ARMS)}"}

    if arm is not None:
        refusal = _override_refusal(arm, config)
        if refusal:
            return {"error": refusal}
        # An arm is its own treatment; `with_skills` cannot halve it.
        with_skills = True
    else:
        with_skills = bool(config.get("with_skills", True))

    router_outcome: str | None = None
    skills: list[str] | None = None
    append_system_prompt: str | None = None
    if arm == "load-everything":
        skills = list(SKILLS)
        append_system_prompt = skill_bodies(SKILLS)
    elif arm == "router":
        router_outcome, selection_error = _router_outcome(_clean(variables.get("case")))
        if selection_error:
            return {"error": selection_error}
        if router_outcome == "escalated":
            # No confident selection: the agent gets the native toolset rather
            # than a wrong skill, which is the failure the router must not add.
            skills = None
        elif router_outcome == "none":
            skills = []
        else:
            skills = [router_outcome]
            append_system_prompt = skill_bodies(skills)

    try:
        mode = resolve_sandbox_mode(config.get("sandbox"), DEFAULT_SANDBOX)
        workspace, sandbox = build_workspace(
            fixture, with_skills, mode=mode, skills=skills
        )
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
            # makes the knob inert the moment a suite pins a value. Under an
            # arm, `_override_refusal` has already refused a divergent value.
            model=os.environ.get("FZ_EVAL_MODEL") or config.get("model"),
            max_turns=int(config.get("max_turns", 30)),
            allowed_tools=config.get("allowed_tools"),
            timeout_s=int(config.get("timeout_s", 900)),
            append_system_prompt=append_system_prompt,
        )

        check_results = [run_check(sandbox, cmd) for cmd in checks]
        failed = run.error is not None or any(
            c["exit_code"] != 0 for c in check_results
        )
        keep = KEEP_WORKSPACES == "all" or (KEEP_WORKSPACES == "failed" and failed)
        if keep:
            log_progress(f"  kept workspace {workspace}")

        output = {
            # The arm's own name when the suite names one; otherwise the
            # ablation switch speaks, exactly as before.
            "arm": arm or ("with-skills" if with_skills else "baseline"),
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
        }
        if arm is not None:
            # The numbers the comparison is made of, and nothing for the
            # ablation arms, whose output stays as their reports already read.
            output["first_turn_input_tokens"] = run.first_turn_input_tokens
            output["duration_s"] = run.duration_s
            output["model"] = run.model
        if arm == "router":
            output["router_outcome"] = router_outcome

        return {"output": output, "cost": run.cost_usd}
    finally:
        if not keep:
            shutil.rmtree(workspace, ignore_errors=True)
        if sandbox.agent_home:
            shutil.rmtree(sandbox.agent_home, ignore_errors=True)
