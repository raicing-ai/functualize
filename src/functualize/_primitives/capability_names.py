"""The one list of framework-injected parameter type names.

A capability parameter (``log: Log``, ``sh: Shell``, ``sources: Sources``) is
supplied by the execution engine. It is not a CLI argument, and every layer
that walks a job signature has to know that: the annotation classifier, the two
click-parameter builders, the discovery scan, and the engine's own DI binding
validation.

Each of those kept **its own copy** of the list, and the copies had drifted:

- ``Shell`` was missing from the discovery scan's copy, so a job taking
  ``sh: Shell`` ran fine cold and, on warm boot — every invocation after the
  first — failed with ``Error: Missing argument 'SH'``.
- ``Stdout`` was missing from the same copy and failed that way on *both*
  paths.

The failure is not subtle once seen, but it is invisible from any one layer,
and adding a capability means remembering four places. So the list lives here,
once, and the copies are gone. `_primitives` is the home because every one of
those layers may import it, including `_types`-only consumers.

`_cli` may import public folders only, so it reaches this through the
``functualize.app.utils`` re-export.
"""

from __future__ import annotations

__all__ = ["INJECTED_PARAM_TYPE_NAMES"]

#: Type names the engine injects. Parameters annotated with one of these are
#: stripped from every CLI surface and resolved per-invocation instead.
#:
#: Matched by **name**, not identity, so a layer forbidden from importing the
#: capability's module can still classify it. That is why this is a set of
#: strings rather than of types.
INJECTED_PARAM_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "RunContext",
        "Log",
        "Invoke",
        "Prompt",
        "Perf",
        "Shell",
        "Stdout",
        "State",
        "Sources",
        "JobContext",
        "JobConfigView",
        "TTY",
        "Live",
    }
)
