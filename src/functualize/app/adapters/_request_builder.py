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


def build_request(
    job_name: str,
    *,
    kwargs: Mapping[str, Any],
    group_option_values: Mapping[str, Any] | None = None,
    workflow_scope_id: str | None = None,
    force: bool = False,
    surface: RunSurface = _DEFAULT_SURFACE,
) -> RunRequest:
    """Build the :class:`RunRequest` a click callback hands to the engine.

    Both the eager and lazy callbacks call this with the values they resolved
    (scope id, force, group flags, kwargs) so that the request — not the loose
    arguments — is what travels. ``surface`` defaults to ``app.cli`` and is
    overridden by whichever ``func`` handler built the command.
    """
    return RunRequest(
        job_name=job_name,
        surface=surface,
        kwargs=kwargs,
        group_option_values=group_option_values,
        workflow_scope_id=workflow_scope_id,
        force=force,
    )
