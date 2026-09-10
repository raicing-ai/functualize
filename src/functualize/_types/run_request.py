"""The request a run is made from.

One object, built at the door, frozen before it travels. Every entry surface
constructs one; :meth:`functualize._engine.executor.JobExecutionEngine.run`
consumes one. Nothing else is a legal way to ask for a job to be executed.

Stdlib-only by contract: this module sits at the bottom of the layer graph
(``_types``) and must remain importable before any part of the framework has
booted. The import-linter contracts in ``pyproject.toml`` enforce it; the test
in ``tests/types/test_run_request.py`` enforces it a second way, by reading the
source, so a violation fails even when the linter is not run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, get_args

RunSurface = Literal[
    "func.job",
    "func.group",
    "func.single-file",
    "app.cli",
    "app.execute",
    "func.builtin",
    "tui.inline",
    "tui.shell",
    "mcp.tool",
    "mcp.run-job",
    "mcp.async",
    "http",
    "lambda",
    "invoke",
    "invoke.parallel",
    "app.parallel",
    "event.job-submit",
    "engine.step",
    "engine.dependency",
]

RUN_SURFACES: Final[frozenset[str]] = frozenset(get_args(RunSurface))

"""Every legal value of :attr:`RunRequest.surface`.

Derived from the ``Literal`` rather than repeated, so the two cannot drift.
"""


@dataclass(frozen=True, slots=True)
class SurfacePolicy:
    """What the engine needs to know about a door, other than its name.

    Two questions, one per field, and both were **string comparisons scattered
    in the kernel**: ``request.surface not in CONSOLE_SURFACES`` and
    ``request.surface == "app.parallel"``. Conditional-on-type-code, two files
    apart, and the first of them answered *silently* — a door added to
    `RunSurface` and forgotten here simply stopped resolving stdin, with the
    parameter's default winning and nothing said.

    A policy object keyed by every surface makes the omission loud instead:
    :data:`SURFACE_POLICY` is total, the lookup is a plain subscript, and a door
    nobody classified raises `KeyError` at its first run rather than quietly
    behaving like the majority.
    """

    owns_stdin: bool
    """Whether this door's caller owns the process's stdin.

    ``Stdin``-marked parameters are resolved by ``engine.run()``
    (run-request/T11), which every surface reaches — so the engine has to know
    which callers actually have a pipe. Only a console invocation does. An HTTP
    or Lambda request that omits a ``Stdin`` parameter must get the parameter's
    default, not a read of the server process's stdin, which is typically
    ``/dev/null`` (non-tty, so the ``isatty`` guard does not save it) and would
    silently substitute an empty string. The TUI surfaces are excluded for the
    opposite reason: their stdin is a live terminal the UI owns, and reading it
    would steal the user's keystrokes.

    Before T11 this was implicit — stdin resolution lived in the click adapters,
    so only click did it. Declaring it per door keeps that true now the code has
    moved into the kernel.
    """

    records_batch_items: bool
    """Whether a run at depth > 0 through this door still reaches history.

    ``func builtin parallel a b`` is the user launching `a` and `b`, and neither
    appeared in ``func builtin history`` because ``Invoke.parallel`` runs each
    item one level down — mechanically nested, but not nested *work* (spec
    AC-18, STATUS #5). Depth alone cannot tell that apart from
    ``rc.invoke_parallel`` inside a job, which must stay out of the ring: both
    parents sit at depth 0, so both put their items at depth 1.

    So the door says which it is. ``app.execute_parallel`` — the seam for
    callers that are not jobs — stamps its items ``app.parallel`` and they are
    recorded; ``rc.invoke_parallel`` stamps ``invoke.parallel`` and they are
    not.
    """


SURFACE_POLICY: Final[Mapping[RunSurface, SurfacePolicy]] = MappingProxyType(
    {
        # The four console doors: a person at a terminal, with a pipe.
        "func.job": SurfacePolicy(owns_stdin=True, records_batch_items=False),
        "func.group": SurfacePolicy(owns_stdin=True, records_batch_items=False),
        "func.single-file": SurfacePolicy(owns_stdin=True, records_batch_items=False),
        "app.cli": SurfacePolicy(owns_stdin=True, records_batch_items=False),
        # Programmatic and embedded entry: no pipe of its own.
        "app.execute": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        # `func builtin ...` — a control verb rather than a job invocation.
        #
        # Deleted on 2026-09-10 as "a label nothing can produce", with the
        # condition for its return stated at the time: *"if a later door needs
        # one, it comes back together with the code that produces it."* This is
        # that. `func builtin workflow resume` reaches `guarded_execute` and was
        # labelled `app.execute`, which made a CLI-driven resume, an MCP-driven
        # one and a plain `request_for` call indistinguishable in the one field
        # whose purpose is telling them apart (rre F9).
        #
        # It does **not** own stdin, unlike the three `func.*` job doors: the
        # user is naming a control verb, not piping data into a job body, and
        # resolving `Stdin` markers here would read the terminal on a resume.
        "func.builtin": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        # The TUIs own a live terminal; reading it steals keystrokes.
        "tui.inline": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "tui.shell": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        # Out-of-process callers. Their stdin is the server's, usually /dev/null.
        "mcp.tool": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "mcp.run-job": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "mcp.async": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "http": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "lambda": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        # Nested work, deliberately out of the history ring.
        "invoke": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "invoke.parallel": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        # The one door whose *items* are what the user launched.
        "app.parallel": SurfacePolicy(owns_stdin=False, records_batch_items=True),
        "event.job-submit": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "engine.step": SurfacePolicy(owns_stdin=False, records_batch_items=False),
        "engine.dependency": SurfacePolicy(owns_stdin=False, records_batch_items=False),
    }
)
"""Every door's policy, one entry per :data:`RunSurface` member.

Total by construction and by test (`tests/types/test_run_request.py`). Look a
surface up with a plain subscript — a `KeyError` on an unclassified door is the
whole point, and is what the `frozenset` membership test it replaces could not
do.

``func.builtin`` and ``func.bare`` were declared here and in ``RunSurface`` and
**produced by nothing** — `func builtin parallel` runs its jobs through
`app.execute_parallel`, which names them `app.parallel`, and bare `func` opens
the inline TUI, which names its runs `tui.inline`. Both were removed
(maintainer's decision, 2026-09-10): a label nothing can produce is decoration,
and this feature exists to remove exactly that. If a later door needs one, it
comes back together with the code that produces it.
"""

CONSOLE_SURFACES: Final[frozenset[str]] = frozenset(
    surface for surface, policy in SURFACE_POLICY.items() if policy.owns_stdin
)
"""The surfaces whose caller owns the process's stdin.

**Derived, not written out.** It was a second hand-maintained taxonomy beside
the 18-value ``Literal``, and a third copy was re-typed in
`tests/engine/test_run_request_stdin.py`. Kept as a name because it reads well
at a call site and because tests assert against it; it is no longer a place to
forget a door.
"""

_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Everything one run needs, frozen at the door that built it.

    The job is *named*, never resolved: :meth:`JobExecutionEngine.run` performs
    the lookup, as it already does for workflow steps and dependencies. Nothing
    outside ``_engine/`` holds a job function in order to execute it.

    ``surface`` has no default. A door must name itself — the coverage audit had
    to reconstruct which door a run came from by reading code, and the run record
    (F5) cannot record what the request never carried.
    """

    job_name: str
    surface: RunSurface
    kwargs: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)

    # Delivery inputs — these were deposits on the app object (spec §1.2).
    prompt_gates: bool = False
    output_format: str = "auto"
    force: bool = False

    # Execution inputs.
    group_option_values: Mapping[str, Any] | None = None
    parent_scope: Any | None = None
    workflow_scope_id: str | None = None
    invoke_depth: int = 0
    run_dependencies: bool = True
    force_fresh: bool = False
    cwd: Path | None = None
    job_directory: Path | None = None

    def __post_init__(self) -> None:
        if self.surface not in RUN_SURFACES:
            # Name the offender and the closed set; a door that mistypes itself
            # would otherwise travel all the way to the run record.
            raise ValueError(
                f"unknown surface {self.surface!r}; "
                f"expected one of {', '.join(sorted(RUN_SURFACES))}"
            )

    def __hash__(self) -> int:
        """Hash the scalar identity, not the payload.

        ``kwargs`` and ``group_option_values`` are ``Mapping``s, and no mapping
        the callers actually pass is hashable — a request carrying a plain dict
        would make the whole object unhashable, which is the wrong trade for a
        value object that wants to key a cache or join a set. Equality still
        compares every field, so equal requests still hash equal; unequal
        requests may collide, which is all a hash promises.
        """
        return hash(
            (
                self.job_name,
                self.surface,
                self.prompt_gates,
                self.output_format,
                self.force,
                self.workflow_scope_id,
                self.invoke_depth,
                self.run_dependencies,
                self.force_fresh,
                self.cwd,
                self.job_directory,
            )
        )

    def replace(self, **changes: Any) -> RunRequest:
        """Return a copy with ``changes`` applied.

        The engine re-points a request at a dependency or a workflow step this
        way, so the surface and delivery inputs travel with it instead of being
        re-derived at the second hop.
        """
        return _dc_replace(self, **changes)


def request_from_envelope(
    payload: Mapping[str, Any],
    *,
    job_name: str,
    surface: RunSurface,
) -> RunRequest:
    """Parse a wire payload into a request — the one copy of that contract.

    The shape is an **envelope**: the job's own parameters live in a nested
    ``arguments`` object and the control inputs sit beside it, never inside::

        {"arguments": {"target": "prod"},
         "group_option_values": {"env": "staging"},
         "scope_id": "run-42",
         "force": true}

    The nesting is the fix, not decoration. A flat body meant a caller's key
    could bind to a control parameter — send ``{"scope_id": "x"}`` and you were
    choosing the workflow scope the run joined rather than passing an argument
    (**spec AC-17a**). Nested, a job parameter literally named ``scope_id``
    arrives as an argument and the scope stays a separate, deliberate choice.

    ``scope_id`` is also what makes a gated workflow **resumable over the wire**:
    start it, read the scope id back from the result metadata, answer the gate,
    send the same id again. The audit recorded that as impossible (D-6) because
    there was no field to put it in.

    **Breaking, deliberately.** Job parameters used to be the whole body; they
    are now under ``arguments``.

    **Why it lives here.** It was written twice — HTTP and Lambda held
    byte-identical copies differing only in the ``surface`` literal — and
    restated in prose twice more at MCP's two doors. One wire contract
    maintained in four places, with the breaking change documented four times
    and *three of the four citations wrong* (two said "risk R-a, spec AC-9",
    one said "spec AC-4, AC-9"; the criterion is AC-17a). A reader auditing
    AC-17a through its keeper would conclude the wire doors were uncovered.
    This module is stdlib-only and every one of those doors already imports
    ``RunRequest`` from it, so there is no layering reason for the copies to
    exist (rre F12).

    Args:
        payload: The decoded wire body.
        job_name: The job the door resolved.
        surface: The calling door — the only thing that differed between the
            two copies, and now a parameter rather than a reason to fork.

    Raises:
        ValueError: A field is present with the wrong JSON type. Each is
            reported by name, because "invalid payload" sends the caller
            hunting through a body they thought was correct.
    """
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("'arguments' must be a JSON object")
    group_options = payload.get("group_option_values") or None
    if group_options is not None and not isinstance(group_options, dict):
        raise ValueError("'group_option_values' must be a JSON object")
    scope_id = payload.get("scope_id")
    if scope_id is not None and not isinstance(scope_id, str):
        raise ValueError("'scope_id' must be a string")
    return RunRequest(
        job_name=job_name,
        surface=surface,
        kwargs=arguments,
        group_option_values=group_options,
        workflow_scope_id=scope_id,
        force=bool(payload.get("force", False)),
    )


def nested_request(parent: RunRequest | None, **changes: Any) -> RunRequest:
    """A request for a run made *by* another run.

    The **delivery inputs travel down** — ``prompt_gates``, ``output_format``,
    ``force``. They describe how this invocation of the program behaves, not how
    one job behaves, so a workflow step, a dependency and an ``rc.invoke`` child
    all answer them the way the run the user started does.

    Everything else resets: a child's arguments, scope and dependency policy are
    its own. A caller that states one of those overrides the reset.

    Before run-request-entry these lived on the app as process-globals, so
    nesting inherited them by accident of storage. Making them per-request made
    the inheritance something the code has to *say* — and for a while it did not,
    so ``func --emit-format none outer`` silently emitted from ``outer``'s child.

    It lives here rather than on the engine because it is a fact about what a
    request *is*, and because the engine is not the only thing that builds a
    nested one: `_engine/capabilities/invoke.py` does too, and reaching into a
    private engine method to ask this question coupled a capability to the
    kernel's internals (and broke every test with a mocked engine).
    """
    if parent is None:
        return RunRequest(**changes)
    fields: dict[str, Any] = {
        "kwargs": _EMPTY,
        "group_option_values": None,
        "parent_scope": None,
        "workflow_scope_id": None,
        "run_dependencies": True,
        "force_fresh": False,
    }
    fields.update(changes)
    return parent.replace(**fields)


__all__ = [
    "CONSOLE_SURFACES",
    "RUN_SURFACES",
    "RunRequest",
    "RunSurface",
    "nested_request",
]
