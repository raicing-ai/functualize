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

CONSOLE_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "func.job",
        "func.group",
        "func.single-file",
        "app.cli",
    }
)
"""The surfaces whose caller owns the process's stdin.

Four doors, not six. ``func.builtin`` and ``func.bare`` were declared here and in
``RunSurface`` and **produced by nothing** — `func builtin parallel` runs its jobs
through `app.execute_parallel`, which names them `app.parallel`, and bare `func`
opens the inline TUI, which names its runs `tui.inline`. Both were removed
(maintainer's decision, 2026-09-10): a label nothing can produce is decoration,
and this feature exists to remove exactly that. If a later door needs one, it
comes back together with the code that produces it.


``Stdin``-marked parameters are resolved by ``engine.run()`` (run-request/T11),
which every surface reaches — so the engine has to know which callers actually
have a pipe. Only a console invocation does. An HTTP or Lambda request that
omits a ``Stdin`` parameter must get the parameter's default, not a read of the
server process's stdin, which is typically ``/dev/null`` (non-tty, so the
``isatty`` guard does not save it) and would silently substitute an empty
string. The TUI surfaces are excluded for the opposite reason: their stdin is a
live terminal the UI owns, and reading it would steal the user's keystrokes.

Before T11 this was implicit — stdin resolution lived in the click adapters, so
only click did it. Naming the set keeps that true now that the code moved.
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
    so ``func --output none outer`` silently emitted from ``outer``'s child.

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
