"""Direct-run StdoutSurface gate, shared by both CLI command paths.

A direct ``func <job>`` run registers a ``StdoutSurface`` (rich scrollback +
live zone) only when something will actually render into it:

- the job declares ``live: Live`` (its own constructs need a zone),
- a plugin registered an ambient construct eligible for the job, or
- an *explicit* STDOUT preference — the job's ``@surface_hint("stdout")`` or
  the ``tui.default_surface`` setting (incl. its
  ``FUNCTUALIZE_TUI_DEFAULT_SURFACE`` env override) — asks for the rich
  stdout branch.

With none of those, the gate is closed and plain ``func <job>`` output is
byte-identical to the pre-surface behavior. A PANEL preference is ignored
here: there is no TUI on a direct run, and we do not auto-launch one. The
``requires_tty`` capability floor is enforced by the callers *before* this
gate — an EXCLUSIVE job owns the terminal and gets no StdoutSurface.

Lives in the adapter layer so ``create_job_command`` (materialized path) and
``make_lazy_command`` (warm/lazy path) cannot drift apart.
"""

from __future__ import annotations

from typing import Any

__all__ = ["wants_ambient", "wants_stdout_surface"]


def wants_ambient(app: Any, descriptor: Any) -> bool:
    """Whether a plugin's ambient construct would render for this job.

    Kept tolerant: ambient rendering is an enhancement, so a failure to decide
    falls back to "no" rather than breaking the run.
    """
    try:
        from functualize.app.utils import has_eligible_ambient

        return has_eligible_ambient(app, descriptor)
    except Exception:
        return False


def wants_stdout_surface(app: Any, descriptor: Any, *, uses_live: bool) -> bool:
    """Decide whether a direct run should register a ``StdoutSurface``.

    Args:
        app: The FunctualizeApp (consulted for ambient-construct registry).
        descriptor: The JobDescriptor, or None when unavailable (legacy
            standalone-adapter paths) — hint/ambient checks then skip.
        uses_live: The job's ``live: Live`` marker (callers already have it
            from the signature or the cached descriptor).

    Returns:
        True when a surface should wrap the execution.
    """
    if uses_live or wants_ambient(app, descriptor):
        return True
    # The ladder's HARD rung outranks preferences: a `tty: TTY` job resolves
    # EXCLUSIVE, so a stdout hint/setting must not wrap it in a surface that
    # would fight the job for the terminal.
    if getattr(descriptor, "requires_tty", False):
        return False
    return _explicit_stdout_preference(descriptor)


def _explicit_stdout_preference(descriptor: Any) -> bool:
    """True when hint or setting explicitly resolves to STDOUT.

    Best-effort: a settings-read failure must never break a run, so any
    exception collapses to "no preference".
    """
    try:
        from functualize._cli.data.func_settings import FuncSettingsStore
        from functualize._cli.orchestrator import RenderSurface, explicit_surface

        hint = getattr(descriptor, "surface_hint", None)
        setting: str | None = None
        try:
            setting = (
                FuncSettingsStore.discover()
                .effective_values()
                .get("tui.default_surface")
            )
        except Exception:
            setting = None
        return explicit_surface(hint, setting) is RenderSurface.STDOUT
    except Exception:
        return False


def refuse_without_terminal(job_name: str) -> None:
    """Refuse a `tty: TTY` job when there is no terminal — one route, one code.

    Capability floor (`surface-architecture.md` §5): a job that owns the
    terminal cannot run where there is none, and refusing pre-flight with an
    actionable message beats corrupt output or a signal-handler traceback
    mid-run.

    **This existed twice**, once in each dispatch path, with the *same message*
    and **different exit codes** — `click_params.py` raised
    `SystemExit(ExitCode.REFUSED)` and `lazy_command.py` called `sys.exit(1)`.
    So the identical refusal of the identical job reported differently depending
    on whether the discovery cache happened to be warm. That is
    `contributor/reference/pitfalls.md` §23 exactly ("Cold boot exited 1, warm
    boot exited 0, for the same job and the same failure"), and it is why
    surface-request-parity/T4 asks for one route rather than merely one import.

    `REFUSED` is the correct code: nothing ran, and this is a pre-flight
    decision, not a job failure (T39 exit table).
    """
    import sys

    from functualize.app.utils import terminal_available
    from functualize.types import ExitCode

    if terminal_available():
        return
    print(
        f"Error: '{job_name}' needs an interactive terminal "
        f"(it declares `tty: TTY`). Run it from `func` at a real "
        f"TTY — it cannot run over a pipe, in CI, or under MCP.",
        file=sys.stderr,
    )
    raise SystemExit(ExitCode.REFUSED)
