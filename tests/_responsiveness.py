"""Measure event-loop responsiveness against the machine, not a constant.

Three test modules assert that blocking work moved to a thread worker leaves
the Textual event loop responsive. Each did so with a hand-picked constant —
``RESPONSIVE_THRESHOLD = 3`` ticks over ``BLOCK_SECONDS = 0.4`` — which makes
the assertion a statement about how fast the machine is, not about whether the
code under test schedules its work correctly.

That is the same failure mode as Hypothesis's ``deadline`` and the stale
``test_config_resolution_budget`` ceiling: on a loaded CI runner (~2.5x slower
than a workstation here) the loop can be genuinely responsive and still miss
an absolute count, and the test reports a defect that does not exist. Lowering
the constant only trades one arbitrary number for another and erodes the
signal in the other direction.

The fix is to measure the *same loop, doing nothing*, and require the blocked
case to reach a fraction of that. Both numbers move together when the machine
is slow, so the ratio keeps meaning what the test says it means.

Only lower-bound (``>=``) assertions need this. An upper bound — "a frozen
loop fits almost no ticks" — is already safe under load, because load pushes
the observed count down, i.e. further into passing.
"""

from __future__ import annotations

import asyncio
import time

__all__ = ["count_polls", "responsive_floor"]


async def count_polls(duration: float, interval: float) -> int:
    """Count how often an ``await``-sleep loop is scheduled within ``duration``.

    With the event loop otherwise idle this yields the machine's ceiling for
    the poll pattern the responsiveness tests use, which is what
    `responsive_floor` turns into a threshold.
    """
    polls = 0
    end = time.monotonic() + duration
    while time.monotonic() < end:
        await asyncio.sleep(interval)
        polls += 1
    return polls


def responsive_floor(baseline: int) -> int:
    """The tick count below which a loop is not meaningfully responsive.

    A third of the idle ceiling. Generous on purpose: the point of these tests
    is to separate "the loop keeps running" from "the loop is frozen", and
    those differ by roughly the whole ceiling, not by a few percent. A tighter
    fraction would start measuring scheduler jitter again.

    Floored at 2 so the check cannot degenerate into ``>= 0`` on a machine so
    loaded that even the idle baseline collapses — at that point the run is
    not measuring anything and should fail rather than pass vacuously.
    """
    return max(2, baseline // 3)
