"""Explainability renderer for `func why` and `--explain` (§D.6).

With guards, fingerprints, deps, and run modes there are roughly six reasons a
job did or didn't run, and Make/Taskfile are notoriously opaque about which one
applied. All the data exists at decision time; surfacing it is cheap and is
exceptional DX for humans and for the AI agents this project targets.

`func why` and `--explain` share this renderer so the two can never drift into
describing the same decision differently::

    deploy → WOULD RUN
      platforms  linux ✓
      preconditions  docker --version ✓ (cached this session)
      status  test -f dist/app.whl ✗
      fingerprint  1 changed (src/a.py) since last run
      deps  lint ✓ fresh · test → will run first

Pure formatting over :class:`~functualize._engine.guards.GuardVerdict` — no I/O,
so both the CLI and the TUI render identical text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._engine.guards import GuardState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from functualize._engine.guards import GuardVerdict

__all__ = ["HEADLINES", "render_dep_line", "render_verdict"]

# Headline per outcome. The wording distinguishes the three skip states
# because CI needs to tell them apart (§D.2).
HEADLINES: Mapping[GuardState, str] = {
    GuardState.RUN: "WOULD RUN",
    GuardState.SKIP_NEUTRAL: "SKIP (not applicable)",
    GuardState.SKIP_SATISFIED: "SKIP (already done)",
    GuardState.SKIP_FRESH: "SKIP (up to date)",
    GuardState.BLOCKED: "BLOCKED (awaiting input)",
    GuardState.ERROR: "ERROR (precondition failed)",
    # Deliberately not worded as a SKIP: a skip means "nothing to do", and a
    # refusal means "I was asked to verify inputs that are not there".
    GuardState.REFUSED: "REFUSED (declared inputs not present)",
}


def render_verdict(
    job_name: str,
    verdict: GuardVerdict,
    *,
    deps: Sequence[str] = (),
    indent: str = "  ",
) -> str:
    """Render one job's decision as the §D.6 block.

    Args:
        job_name: The job the verdict is about.
        verdict: The guard-pipeline outcome, including its per-check trace.
        deps: Pre-rendered dependency lines (see :func:`render_dep_line`).
        indent: Prefix for the detail lines.

    Returns:
        The full multi-line block, without a trailing newline.
    """
    headline = HEADLINES.get(verdict.state, verdict.state.value.upper())
    lines = [f"{job_name} → {headline}"]

    lines.extend(f"{indent}{check}" for check in verdict.checks)

    if verdict.state is GuardState.BLOCKED and verdict.awaiting is not None:
        lines.append(f"{indent}awaiting  {_name_of(verdict.awaiting)}")

    # The reason is the headline's justification; suppress it when a check line
    # already said the same thing, so the block does not repeat itself.
    if verdict.reason and not any(verdict.reason in check for check in verdict.checks):
        lines.append(f"{indent}reason  {verdict.reason}")

    if deps:
        lines.append(f"{indent}deps  {' · '.join(deps)}")

    return "\n".join(lines)


def render_dep_line(name: str, verdict: GuardVerdict) -> str:
    """Render one dependency's contribution to the `deps` summary line."""
    if verdict.state is GuardState.SKIP_FRESH:
        return f"{name} ✓ fresh"
    if verdict.state.is_skip:
        return f"{name} ✓ skipped"
    if verdict.state is GuardState.ERROR:
        return f"{name} ✗ error"
    if verdict.state is GuardState.BLOCKED:
        return f"{name} ⏸ blocked"
    return f"{name} → will run first"


def _name_of(model: object) -> str:
    """Best-effort display name for an awaited gate model."""
    return getattr(model, "__name__", None) or str(model)


def explain_exit_code(verdict: GuardVerdict) -> int:
    """The process exit code `func builtin why` should terminate with.

    `ExitCode.STALE` (4) is pinned in `_types/exit_codes.py`, documented there
    as "stale-check failure", and had **no producer anywhere in the codebase** —
    an inert surface of the same class as the `@job(matrix=…)` kwarg this branch
    removed. Taskfile's `task --status` is the feature that number was reserved
    for; `why` was 90% of it and answered exit 0 for every outcome, so no script
    could branch on it.

    Deliberately reuses the *run* table's numbers for the outcomes it shares
    with a run: a refusal is 3 whether you ask about it or trigger it, and a
    blocked gate is 5. Inventing a second vocabulary for "what would happen"
    versus "what happened" is how two tables drift.
    """
    from functualize._types.exit_codes import ExitCode

    if verdict.state.is_skip:
        return int(ExitCode.OK)
    if verdict.state in (GuardState.ERROR, GuardState.REFUSED):
        return int(ExitCode.REFUSED)
    if verdict.state is GuardState.BLOCKED:
        return int(ExitCode.BLOCKED)
    return int(ExitCode.STALE)


def model_name(model: object) -> str | None:
    """The awaited model's name, for the JSON payload."""
    if model is None:
        return None
    return _name_of(model)
