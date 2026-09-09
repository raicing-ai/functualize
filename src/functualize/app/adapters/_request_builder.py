"""One builder for the ``RunRequest`` both click constructors emit.

``click_params.build_job_engine_callback`` (eager, from a live signature) and
``lazy_command.make_lazy_command`` (lazy, from a cached descriptor) are two
dispatch paths that produce the same kind of thing — a click command whose
callback runs a job. ``pitfalls.md`` §23 is the scar from the last time they
disagreed: the eager path inspected its ``JobResult`` and the lazy path did
not, so cold boot and warm boot exited differently for the same failure.

This module is the same discipline applied one layer earlier: the request both
callbacks build is built here, once, so the eager and lazy paths cannot drift
on *what they ask for* any more than they can on *what they do with the answer*.
A test that runs one argv through both paths and compares the requests is the
second run ``pitfalls.md`` §23 demands ("run every end-to-end assertion twice —
the second run is a different code path").
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from functualize._types.run_request import RunRequest, RunSurface

# The default surface: the app's own CLI door (contracts.md §5). The eager
# path builds from a live signature and the lazy path from a cached
# descriptor, but the user typed the same command in both cases — one surface,
# not two.
#
# `func`'s own handlers build click commands too, and they are *not* this
# door: `func <job>`, `func <group> <job>` and `func <file.py>::<fn>` boot
# their own app first and each answer differently when something goes wrong.
# They pass their surface at build time (run-request/T11). It is a parameter
# rather than an attribute on the app because the door that knows the answer
# is the one constructing the command, and an attribute would be the eleventh
# deposit — which is what this feature exists to remove.
_DEFAULT_SURFACE: RunSurface = "app.cli"


def _click_obj() -> Mapping[str, Any]:
    """The nearest ``ctx.obj`` dict on the live click context stack.

    The one legitimate ambient channel for a delivery input, and only because
    of the shape of the app's own CLI: its **root callback** parses ``--force``
    (and, after T13, ``--prompt-gates`` and ``--output``) *after* the
    subcommands were already built, so it cannot hand them to the builder the
    way ``func``'s handlers do.

    This is not the deposit protocol coming back. A deposit lived on the
    **app** — a process-lifetime object — so two concurrent runs shared one
    answer and the kernel read an attribute the app was not obliged to have.
    A click context is created per invocation, torn down with it, and already
    carries this dict (``adapters/cli.py`` fills it in). Ambient in scope but
    not in lifetime.

    Silent and defensive: outside click there is no context, and a caller that
    put something other than a dict in ``obj`` is not an error here.
    """
    try:
        import click

        ctx = click.get_current_context(silent=True)
    except Exception:  # pragma: no cover - click absent or no active context
        return {}
    while ctx is not None:
        if isinstance(ctx.obj, dict):
            return ctx.obj
        ctx = ctx.parent
    return {}


def build_request(
    job_name: str,
    *,
    kwargs: Mapping[str, Any],
    group_option_values: Mapping[str, Any] | None = None,
    workflow_scope_id: str | None = None,
    prompt_gates: bool | None = None,
    output_format: str | None = None,
    force: bool | None = None,
    surface: RunSurface = _DEFAULT_SURFACE,
) -> RunRequest:
    """Build the :class:`RunRequest` a click callback hands to the engine.

    Both the eager and lazy callbacks call this with the values they resolved
    (scope id, group flags, kwargs) so that the request — not the loose
    arguments — is what travels. ``surface`` defaults to ``app.cli`` and is
    overridden by whichever ``func`` handler built the command.

    The three **delivery inputs** — ``prompt_gates``, ``output_format``,
    ``force`` — accept ``None`` meaning *not stated here*, in which case they
    come from :func:`_click_obj`. ``func``'s handlers state them, because they
    parsed the flags before building the command; the app's own root callback
    cannot, and puts them in ``ctx.obj`` instead. Until T12 both routes were
    one thing: an attribute written onto the app.
    """
    ambient = (
        _click_obj()
        if prompt_gates is None or output_format is None or force is None
        else {}
    )
    return RunRequest(
        job_name=job_name,
        surface=surface,
        kwargs=kwargs,
        group_option_values=group_option_values,
        workflow_scope_id=workflow_scope_id,
        prompt_gates=(
            bool(ambient.get("prompt_gates", False))
            if prompt_gates is None
            else prompt_gates
        ),
        output_format=(
            str(ambient.get("output_format", "auto") or "auto")
            if output_format is None
            else output_format
        ),
        force=bool(ambient.get("force", False)) if force is None else force,
    )
