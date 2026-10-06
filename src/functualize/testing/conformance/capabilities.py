"""Capability tiers — run only for what a store's profile declares.

Each tier is keyed by the ``StoreProfile`` field and value that switches it on,
and :func:`run_capability_tiers` reads the profile of the store ``make_store``
builds: a store that declares nothing runs nothing, and one that declares a
capability is held to it. There is no list of stores here — the profile is
the only input to the choice, which is what makes a declaration a promise.

- ``cross_aggregate_atomicity=True`` — a fault raised after every command of a
  transition that spans two scopes and a run leaves nothing of it; the whole
  transition lands together (E-3, at the port). At the port a fault can only
  land between *commands*: a fault between the *statements* of one commit
  needs a hook into the store's write path, which is open with the two below;
- ``fencing="cross-process"`` — a second OS process takes the scope over; the
  first process's write under its old generation lands nothing, and the
  taker's value survives (E-2);
- ``durable_outbox=True`` and ``versioned_migrations=True`` — registered, and
  they **refuse** rather than pass: the port has no outbox reader and no way
  to lay down a historical schema, so a store-agnostic suite cannot observe
  either. Their harness hooks are an open decision on this module's public
  signature; until it lands, a store declaring either fails here loudly.
"""

from __future__ import annotations

import multiprocessing
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    IllegalTransition,
    RunQuery,
    StartAttempt,
    StoreProfile,
)

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore, RuntimeTransaction
    from functualize.testing.conformance.baseline import MakeStore

__all__ = ["CAPABILITY_TIERS", "CapabilityTier", "run_capability_tiers", "tiers_for"]

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = 300.0


@dataclass(frozen=True)
class CapabilityTier:
    """One tier, and the profile field value that switches it on."""

    field: str
    value: object
    check: Callable[[MakeStore, Path], None]

    @property
    def name(self) -> str:
        return f"{self.field}={self.value!r}"

    def applies_to(self, profile: StoreProfile) -> bool:
        return bool(getattr(profile, self.field) == self.value)


def _claim(store: RuntimeStore, scope_id: str, owner: str) -> int:
    with store.transaction() as tx:
        outcome = tx.workflows.claim(ClaimWorkflow(scope_id, owner, T0, LEASE))
    assert isinstance(outcome, Claimed), f"claim of {scope_id!r} answered {outcome!r}"
    return outcome.generation


# -- cross_aggregate_atomicity --------------------------------------------------


class _FaultError(Exception):
    """The injected fault: raised between two commands of one transition."""


def cross_aggregate_atomicity(make_store: MakeStore, root: Path) -> None:
    """A unit over two scopes and a run lands whole, or — faulted after any of
    its commands, or refused part-way — not at all."""
    store = make_store(root)
    a, b = _claim(store, "agg-a", "runner"), _claim(store, "agg-b", "runner")
    commands: list[Callable[[RuntimeTransaction], None]] = [
        lambda tx: tx.workflows.complete_step(
            CompleteStep("agg-a", a, "s", T0, position="a1")
        ),
        lambda tx: tx.runs.start_attempt(
            StartAttempt("atomic-run", "cli", T0, scope_id="agg-a")
        ),
        lambda tx: tx.workflows.complete_step(
            CompleteStep("agg-b", b, "s", T0, position="b1")
        ),
    ]

    def landed() -> tuple[object, object, int]:
        va, vb = store.workflows.workflow("agg-a"), store.workflows.workflow("agg-b")
        runs = store.runs.recent(RunQuery(job="atomic-run"))
        return (va.position if va else None, vb.position if vb else None, len(runs))

    nothing = landed()
    for faulted_after in range(len(commands) + 1):
        try:
            with store.transaction() as tx:
                for command in commands[:faulted_after]:
                    command(tx)
                raise _FaultError
        except _FaultError:
            pass
        assert landed() == nothing, (
            f"a fault after {faulted_after} command(s) left {landed()!r}, expected {nothing!r}"
        )

    try:
        with store.transaction() as tx:
            commands[0](tx)
            commands[1](tx)
            tx.workflows.complete_step(
                CompleteStep("agg-b", b, "s", T0, scope_status="nonsense")
            )
    except IllegalTransition:
        pass
    assert landed() == nothing, f"a refusal part-way left {landed()!r}"

    with store.transaction() as tx:
        for command in commands:
            command(tx)
    assert landed() == ("a1", "b1", 1), (
        f"the whole unit did not land together: {landed()!r}"
    )
    store.close()


# -- fencing == "cross-process" ---------------------------------------------------


def _take_over(make_store: MakeStore, root: str) -> None:
    """The second process: force-claim the scope and write under the new generation."""
    store = make_store(Path(root))
    with store.transaction() as tx:
        taken = tx.workflows.claim(
            ClaimWorkflow("fenced", "process-b", T0, LEASE, force=True)
        )
    if not isinstance(taken, Claimed):
        os._exit(3)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("fenced", taken.generation, "s", T0, position="live")
        )
    store.close()
    os._exit(0)


def cross_process_fencing(make_store: MakeStore, root: Path) -> None:
    """Two OS processes on one store: the stale writer lands nothing."""
    store = make_store(root)
    held = _claim(store, "fenced", "process-a")
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("fenced", held, "s", T0, position="first")
        )

    context: Any = multiprocessing.get_context(
        "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    )
    child = context.Process(target=_take_over, args=(make_store, str(root)))
    child.start()
    child.join(timeout=120)
    assert child.exitcode == 0, (
        f"the second process failed to take the scope over: exit {child.exitcode}"
    )

    try:
        with store.transaction() as tx:
            tx.workflows.complete_step(
                CompleteStep(
                    "fenced", held, "s", T0 + timedelta(seconds=1), position="stale"
                )
            )
    except Exception:  # the refusal's type is the store's own; landing is the defect
        pass
    view = store.workflows.workflow("fenced")
    assert view is not None and view.position == "live", (
        f"the stale process's write landed: {view!r}"
    )
    assert view.owner == "process-b" and (view.generation or 0) > held, f"{view!r}"
    store.close()


# -- declared, not yet observable --------------------------------------------------


def _needs_a_hook(capability: str, why: str) -> Callable[[MakeStore, Path], None]:
    def check(make_store: MakeStore, root: Path) -> None:
        raise AssertionError(
            f"the store declares {capability}, and this suite cannot yet hold it to that: "
            f"{why} A harness hook for it is pending; until then the declaration is unproven."
        )

    check.__name__ = capability
    return check


#: Every tier, keyed by the profile value that switches it on.
CAPABILITY_TIERS: tuple[CapabilityTier, ...] = (
    CapabilityTier("cross_aggregate_atomicity", True, cross_aggregate_atomicity),
    CapabilityTier("fencing", "cross-process", cross_process_fencing),
    CapabilityTier(
        "durable_outbox",
        True,
        _needs_a_hook(
            "durable_outbox=True", "the port records intents but has no outbox reader."
        ),
    ),
    CapabilityTier(
        "versioned_migrations",
        True,
        _needs_a_hook(
            "versioned_migrations=True",
            "a historical schema and a failed revision are backend-specific to lay down.",
        ),
    ),
)


def tiers_for(profile: StoreProfile) -> tuple[CapabilityTier, ...]:
    """The tiers ``profile`` switches on — read from the profile, nothing else."""
    return tuple(tier for tier in CAPABILITY_TIERS if tier.applies_to(profile))


def run_capability_tiers(
    make_store: MakeStore, root: Path | None = None
) -> tuple[str, ...]:
    """Run every tier the store's profile declares; return the names that ran.

    Raises ``AssertionError`` naming the first tier that fails.
    """
    base = Path(tempfile.mkdtemp(prefix="capabilities-")) if root is None else root
    probe_dir = base / "profile"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = make_store(probe_dir)
    profile = probe.profile
    probe.close()
    ran = []
    for index, tier in enumerate(tiers_for(profile)):
        directory = base / f"{index}-{tier.field}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            tier.check(make_store, directory)
        except AssertionError as failure:
            raise AssertionError(f"capability tier {tier.name}: {failure}") from failure
        ran.append(tier.name)
    return tuple(ran)
