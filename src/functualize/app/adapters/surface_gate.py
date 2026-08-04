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
        from functualize._engine.ambient import has_eligible_ambient

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
