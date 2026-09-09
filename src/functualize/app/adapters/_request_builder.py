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

# The surface both click constructors report. They are the app's own CLI door
# (contracts.md §5): the eager path builds from a live signature, the lazy
# path from a cached descriptor, but the user typed the same command in both
# cases. One surface, not two.
_SURFACE: RunSurface = "app.cli"


def build_request(
    job_name: str,
    *,
    kwargs: Mapping[str, Any],
    group_option_values: Mapping[str, Any] | None = None,
    workflow_scope_id: str | None = None,
    force: bool = False,
) -> RunRequest:
    """Build the :class:`RunRequest` a click callback hands to the facade.

    Both the eager and lazy callbacks call this with the values they resolved
    (scope id, force, group flags, the split kwargs) so that the request — not
    the loose arguments — is what travels to the facade. The surface is fixed
    at ``app.cli``: these are the app's own click commands, and a door names
    itself.
    """
    return RunRequest(
        job_name=job_name,
        surface=_SURFACE,
        kwargs=kwargs,
        group_option_values=group_option_values,
        workflow_scope_id=workflow_scope_id,
        force=force,
    )
