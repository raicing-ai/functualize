"""The workflow recorder — walk moments as scope commands.

FUN-17/T10. A ``FrontierWalk`` owns four moments that persistence must
survive — taking the scope, finishing a step, stopping at a gate, resuming —
and this module is where each becomes its command value. Thin by contract,
exactly as ``run_recorder`` is: the facts a moment observed go in, the
command comes out, and nothing else happens — no clock reads, no
conditionals, no state between calls.

Which moments carry a generation and which take one is the command layer's
own split (``_types/persistence.py``, contracts.md §1.2): ``claimed`` and
``resumed`` are acquisitions, so they carry owner and lease instead of a
held generation; ``step_completed`` and ``suspended`` mutate a scope the
walk holds, so they carry the generation the walk holds — passed through,
never tracked here. The walk keeps its generation (``frontier.py``); a
recorder that remembered one would be a second source for what the fence
reads.

``step_completed``'s ``scope_status`` is the walk's decision passed through
— reaching END makes a scope ``completed`` and a terminal failure makes it
``failed``, and which of those a step was is transition meaning (ADR-025).
Deriving it here from the position would put a ``resume``-adjacent
conditional in a module whose whole point is to hold none.

The recorder holds no transaction, for the same lifetime reason as
``run_recorder``: transactions are per-transition, recorders are not. The
walker issues what these methods return inside
``store.transaction()`` — wiring that arrives with T11, not here.

Mapping sources: ``contracts.md`` §1.2 fixes the command shapes and
``tasks.md`` T10 names the four moments. Nothing constructs these values
anywhere in the tree yet, so the mapping is derived from the contract, not
copied from a call site.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from functualize._types.persistence import (
    ClaimWorkflow,
    CompleteStep,
    ResumeWorkflow,
    SuspendAtGate,
)

__all__ = ["WorkflowRecorder"]


class WorkflowRecorder:
    """Four walk moments, as the scope commands that record them."""

    def claimed(
        self,
        *,
        scope_id: str,
        owner: str,
        now: datetime,
        lease_seconds: float,
        force: bool = False,
    ) -> ClaimWorkflow:
        """The walk is taking the scope, fencing every later write it makes.

        Acquisition-shaped: no held generation, because this is the moment
        that takes one. ``force`` only for an explicit reclaim, where a
        human has decided the holder is gone.
        """
        return ClaimWorkflow(
            scope_id=scope_id,
            owner=owner,
            now=now,
            lease_seconds=lease_seconds,
            force=force,
        )

    def step_completed(
        self,
        *,
        scope_id: str,
        generation: int,
        step_key: str,
        now: datetime,
        iteration: int = 0,
        status: str = "success",
        result: Any = None,
        decision_key: str | None = None,
        chosen_target: str | None = None,
        position: str | None = None,
        scope_status: str = "running",
    ) -> CompleteStep:
        """A step finished, and the scope advanced past it.

        A loop revisits a step key, so ``iteration`` distinguishes the
        visits; a branch choice rides along when the step made one (both
        fields together or neither — the walk that observed the choice is
        the one that knows it made it).
        """
        return CompleteStep(
            scope_id=scope_id,
            generation=generation,
            step_key=step_key,
            now=now,
            iteration=iteration,
            status=status,
            result=result,
            decision_key=decision_key,
            chosen_target=chosen_target,
            position=position,
            scope_status=scope_status,
        )

    def suspended(
        self,
        *,
        scope_id: str,
        generation: int,
        gate_name: str,
        position: str,
        now: datetime,
        schema: Any = None,
        prompt: Any = None,
    ) -> SuspendAtGate:
        """The walk stopped at a gate and opened the input request that
        pauses it — collecting the answer happens outside any transaction."""
        return SuspendAtGate(
            scope_id=scope_id,
            generation=generation,
            gate_name=gate_name,
            position=position,
            now=now,
            schema=schema,
            prompt=prompt,
        )

    def resumed(
        self,
        *,
        scope_id: str,
        owner: str,
        gate_name: str,
        now: datetime,
        lease_seconds: float,
        force: bool = False,
    ) -> ResumeWorkflow:
        """An accepted answer is being consumed and the scope reclaimed.

        One transition, which is the point: today the deposit and the claim
        are two locked writes in different call frames. Acquisition-shaped
        like ``claimed`` — resume takes a **new** generation rather than
        holding one.
        """
        return ResumeWorkflow(
            scope_id=scope_id,
            owner=owner,
            gate_name=gate_name,
            now=now,
            lease_seconds=lease_seconds,
            force=force,
        )
