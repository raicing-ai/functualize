"""How a finished run reads, and who is allowed to decide.

Nine sites used to translate a :class:`RunStatus` into something a caller could
act on — an exit code, a rendered panel, a tool status string, an HTTP status —
and each carried its own copy of the rules. Two of them disagreed. MCP's
``wire_status`` says so in its own docstring: *"Three doors disagreed."*

This module is the single authority. A delivery surface declares **which family
it belongs to** and asks; it does not decide.

The four families are not styles of presentation. They are four different
answers to *"is this outcome a failure?"*, and the difference is real:

* ``PROCESS`` — a shell reads an exit code. A gate pause is unfinished work, so
  it is a failure here (exit 5): a script resuming in a loop must be able to
  tell "paused" from "done".
* ``PANEL`` — a live surface renders the outcome in place and the run is still
  addressable. A gate pause is **not** a failure here; it is the normal way a
  gated workflow behaves, and painting it red is how the TUI came to report
  BLOCKED as success (D-7).
* ``TOOL`` — a tool response carries a status string. The caller branches on the
  string, so a pause is reported, not raised.
* ``WIRE`` — an HTTP client reads a status code. A pause is 202 Accepted:
  neither success nor error, which is exactly what happened.

Stdlib-only, at the bottom of the layer graph, so every surface can import it
without importing the framework.
"""

from __future__ import annotations

from enum import StrEnum

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.http_status import http_status_for_status


class Family(StrEnum):
    """The kind of boundary a run's outcome is crossing.

    A :class:`~enum.StrEnum` so a family can be logged, serialised and compared
    against a plain string without the caller unwrapping it. ``contracts.md``
    spells it ``(str, Enum)``; on this interpreter that is the same type with a
    ruff warning attached (UP042), so the modern spelling is used.
    """

    PROCESS = "process"
    """An exit code a shell sees."""

    PANEL = "panel"
    """A rendered outcome inside a live surface, where the run stays addressable."""

    TOOL = "tool"
    """A status string in a tool response."""

    WIRE = "wire"
    """An HTTP status."""


# The one place the families disagree, written down instead of commented.
#
# Every family treats SUCCESS and SKIPPED as not-a-failure and FAILURE,
# TIMEOUT, CANCELLED and UNKNOWN as failures. BLOCKED and REFUSED are where
# they part, and the reason is in the module docstring.
_NOT_A_FAILURE: dict[Family, frozenset[RunStatus]] = {
    Family.PROCESS: frozenset({RunStatus.SUCCESS, RunStatus.SKIPPED}),
    # A pause is how a gated workflow behaves; the panel keeps it addressable.
    Family.PANEL: frozenset({RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED}),
    # A tool reports the pause in its status string rather than raising.
    Family.TOOL: frozenset({RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED}),
    # 202 Accepted is not an error class.
    Family.WIRE: frozenset({RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED}),
}


def is_failure(status: RunStatus, *, family: Family) -> bool:
    """Is this outcome a failure at ``family``'s boundary?

    The rule that was spelled three times, with the family as an argument
    instead of as a comment. ``is_failure(BLOCKED, family=PROCESS)`` is ``True``;
    ``is_failure(BLOCKED, family=PANEL)`` is ``False``.

    ``RUNNING`` is transient and never observed at a boundary; asking about it
    is a caller bug, and it answers ``True`` rather than inventing a fifth
    outcome, matching how the exit-code table treats anything unmapped.
    """
    return status not in _NOT_A_FAILURE[family]


def report_line(status: RunStatus) -> str | None:
    """The one line a status owes the caller before its code is delivered.

    Two statuses have something to say first, and saying nothing is worse than
    saying it twice:

    * ``BLOCKED`` — without the message a paused run looks like a plain success
      to anything reading only stdout;
    * ``REFUSED`` — a stage that declined because its declared inputs were
      absent must reach the boundary, or silence plus exit 0 reads as
      "verified, nothing wrong". That is precisely the false clean.

    Returns ``None`` for every status that owes nothing, so a caller can write
    ``if (line := report_line(status)):`` without a second table.

    The *detail* — which gate, which scope, the resume incantation — stays with
    the surface that has the result object. This is the sentence, not the report.
    """
    if status is RunStatus.BLOCKED:
        return "Blocked: the run paused at a declared gate and is resumable."
    if status is RunStatus.REFUSED:
        return "Refused: a declared precondition for running this job was not met."
    return None


def wire_value(status: RunStatus) -> str:
    """The status string a tool response carries.

    Lowercase, stable, and the inverse of :func:`status_from_wire`. Callers
    branch on these strings, so they are an interface, not a rendering.
    """
    return status.value.lower()


def status_from_wire(value: str) -> RunStatus | None:
    """Read a status string back, or ``None`` if it names no status.

    This replaces the hand-rolled reverse lookup in ``_cli/builtins.py``, whose
    fallback — ``0 if status in {"answered", "drafted"} else 1`` — invented two
    outcomes the ``RunStatus`` vocabulary does not have and mapped everything
    else to a bare failure. Returning ``None`` hands the decision back to the
    caller with the fact that the string was unrecognised, which is the thing
    the fallback threw away.
    """
    wanted = value.strip().lower()
    for member in RunStatus:
        if member.value.lower() == wanted:
            return member
    return None


__all__ = [
    "ExitCode",
    "Family",
    "exit_code_for_status",
    "http_status_for_status",
    "is_failure",
    "report_line",
    "status_from_wire",
    "wire_value",
]
