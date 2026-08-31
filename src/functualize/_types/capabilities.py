"""The canonical set of engine-injected capability type names.

A capability is *supplied by the engine*, never by a caller. Every surface that
publishes a job's inputs — the CLI's flags, the MCP tool's ``inputSchema``, a
TUI's argument form — has to subtract them, or it asks an agent to fill in a
dependency-injected internal.

This list exists because that subtraction was being done twice from two
different sources of truth. ``_discovery`` kept a hand-written frozenset;
``_engine`` dispatches on type identity. They disagreed: the engine imports
``Shell`` and ``Stdout`` from ``_types`` while every other capability comes
from ``_engine.capabilities``, and the hand-written set was assembled from the
latter — so ``out: Stdout`` and ``sh: Shell`` were published as required string
arguments on the MCP surface while the CLI, which tests the live annotation on
a different path, filtered them correctly. A leak visible only on the surface
nobody was looking at.

Names rather than types, deliberately: ``_types`` imports nothing internal, and
the extraction path must also handle string (PEP 563 / forward-ref)
annotations, where a name is all there is.

``tests/discovery/test_capability_parity.py`` asserts this set equals the
engine's actual injection dispatch, so adding a capability without updating
this list fails rather than silently leaking it.
"""

from __future__ import annotations

__all__ = ["INJECTED_CAPABILITY_TYPE_NAMES"]

#: Every type the execution engine constructs and injects by parameter type.
#:
#: ``Stdin`` is deliberately absent: it is an ``Annotated[...]`` marker on a
#: real user-supplied parameter, not an injected capability, and excluding it
#: would delete a flag the caller is supposed to pass.
INJECTED_CAPABILITY_TYPE_NAMES = frozenset(
    {
        "RunContext",
        "Log",
        "Stdout",
        "Shell",
        "Invoke",
        "Prompt",
        "Perf",
        "State",
        "TTY",
        "Live",
        "JobContext",
        "JobConfigView",
    }
)
