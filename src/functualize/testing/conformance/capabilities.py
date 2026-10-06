"""Capability tiers — run only for what a store's profile declares.

Each tier is keyed by the ``StoreProfile`` field and value that switches it on,
and :func:`capability_report` reads the profile of the store ``make_store``
builds: a store that declares nothing runs nothing, and one that declares a
capability is held to it. There is no list of stores here — the profile is
the only input to the choice, which is what makes a declaration a promise.

Some capabilities cannot be observed through the port, so the backend's test
code hands the suite instruments (:mod:`.hooks`). Which tier needs which:

- ``cross_aggregate_atomicity=True`` — ``statement_faults``: a fault after
  every *command* of a two-scope transition leaves nothing (E-3, at the
  port), and a fault before every *statement* of the one commit leaves
  nothing too — the part only a hook into the write path can see;
- ``fencing="cross-process"`` — no hook: a second OS process takes the scope
  over, and the first process's write under its old generation lands
  nothing (E-2);
- ``durable_outbox=True`` — ``outbox``: an intent committed with its step
  survives a crash immediately after commit, and a crash inside the
  transaction leaves neither (recording only — dispatching is another
  feature's);
- ``versioned_migrations=True`` — ``migrations``: every historical schema
  opens to the latest version, and each kind of damage refuses (I-9);
- ``offline_capable=True`` — no hook: BASELINE's first check runs with every
  socket refusing (AC-1 names the field; until this tier nothing gated it).

A tier whose hook is missing **refuses** — ``AssertionError`` naming the
field and the absent attribute — it never silently skips (H-2).
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    IllegalTransition,
    RunQuery,
    StartAttempt,
    StoreProfile,
)
from functualize.testing.conformance.baseline import run_tree_and_recent_history
from functualize.testing.conformance.hooks import (
    CapabilityReport,
    HarnessHooks,
    StatementFault,
    TierRun,
)

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore, RuntimeTransaction
    from functualize.testing.conformance.baseline import MakeStore

__all__ = [
    "CAPABILITY_TIERS",
    "CapabilityTier",
    "capability_report",
    "run_capability_tiers",
    "tiers_for",
]

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = 300.0

#: The harness attribute each tier needs, or ``None`` when the port suffices
#: (H-2's mapping — a tier keyed on is refused, never skipped, without it).
NEEDS_HOOK: dict[str, str] = {
    "cross_aggregate_atomicity": "statement_faults",
    "durable_outbox": "outbox",
    "versioned_migrations": "migrations",
}


@dataclass(frozen=True)
class CapabilityTier:
    """One tier, and the profile field value that switches it on."""

    field: str
    value: object
    check: Callable[[MakeStore, Path, HarnessHooks], str]

    @property
    def name(self) -> str:
        return f"{self.field}={self.value!r}"

    def applies_to(self, profile: StoreProfile) -> bool:
        return bool(getattr(profile, self.field) == self.value)


def _claim(
    store: RuntimeStore, scope_id: str, owner: str, *, force: bool = False
) -> int:
    with store.transaction() as tx:
        outcome = tx.workflows.claim(
            ClaimWorkflow(scope_id, owner, T0, LEASE, force=force)
        )
    assert isinstance(outcome, Claimed), f"claim of {scope_id!r} answered {outcome!r}"
    return outcome.generation


# -- cross_aggregate_atomicity (H-3) --------------------------------------------


class _FaultError(Exception):
    """The injected fault: raised between two commands of one transition."""


def cross_aggregate_atomicity(
    make_store: MakeStore, root: Path, hooks: HarnessHooks
) -> str:
    """A unit over two scopes and a run lands whole, or — faulted after any of
    its commands, refused part-way, or faulted before any of its *statements*
    — not at all."""
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
            f"a fault after {faulted_after} command(s) left {landed()!r}"
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

    # The part only the hook can see: a fault immediately before each
    # *statement* of the one commit. k climbs until a commit completes —
    # a unit with ≤ k statements commits normally, which is how the tier
    # learns the unit's length — and every faulted k must have left nothing.
    assert hooks.statement_faults is not None  # H-2 checked before the tier ran
    statement_faults = 0
    fault_at = 0
    while True:
        faulted_store = hooks.statement_faults.make_store(root, fault_at)
        try:
            with faulted_store.transaction() as tx:
                for command in commands:
                    command(tx)
        except StatementFault:
            faulted_store.close()
            statement_faults += 1
            assert landed() == nothing, (
                f"a fault before statement {fault_at} left {landed()!r}"
            )
            fault_at += 1
            continue
        faulted_store.close()
        break  # the commit completed: the unit has ≤ fault_at statements
    assert statement_faults >= 1, "no statement fault ever fired"
    assert landed() == ("a1", "b1", 1), (
        f"the completing commit did not land the whole unit: {landed()!r}"
    )
    store.close()
    return (
        f"statement faults at {statement_faults} positions "
        f"+ command faults at {len(commands) + 1}"
    )


# -- fencing == "cross-process" (H-7) -------------------------------------------


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


def cross_process_fencing(
    make_store: MakeStore, root: Path, hooks: HarnessHooks
) -> str:
    """Two OS processes on one store: the stale writer lands nothing.

    What this observes is the *outcome* — the stale write did not land and
    the taker's did. Which of the store's guards held it (the generation
    predicate, the owner check, the lease expiry) is not observable here,
    and the strength below says so rather than claiming more.
    """
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
    return "stale write from a second OS process landed nothing"


# -- durable_outbox (H-4) --------------------------------------------------------


def _crashing_unit(
    make_store: MakeStore, root: str, *, exit_before_commit: bool
) -> None:
    """A child process: claim, then a step and its intent — and a hard exit
    either inside the transaction (before commit) or right after its block
    exits (after commit)."""
    store = make_store(Path(root))
    scope = "ox" if exit_before_commit else "ox-2"
    held = _claim(store, scope, f"child-{'before' if exit_before_commit else 'after'}")
    step = "s-before" if exit_before_commit else "s-after"
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep(scope, held, step, T0, position="p-" + step)
        )
        tx.effects.append("conformance", "topic.a", {"n": 1}, "idem-a")
        if exit_before_commit:
            os._exit(7)  # inside the with: the unit never commits
    os._exit(0)  # the block exited: the unit is committed, then we die


def durable_outbox(make_store: MakeStore, root: Path, hooks: HarnessHooks) -> str:
    """An intent committed with its transition survives a crash after commit;
    a crash inside the transaction leaves neither the intent nor the step.

    Three observations, two of them in child processes that die by
    ``os._exit`` so no cleanup can run: what survived is read back through
    the probe's fresh handle, the way a dispatcher restarting after a crash
    would read it.
    """
    assert hooks.outbox is not None  # H-2 checked before the tier ran
    probe = hooks.outbox
    context: Any = multiprocessing.get_context(
        "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    )

    before = context.Process(
        target=_crashing_unit,
        args=(make_store, str(root)),
        kwargs={"exit_before_commit": True},
    )
    before.start()
    before.join(timeout=120)
    assert before.exitcode == 7, (
        f"the crash-before-commit child exited {before.exitcode}"
    )
    store = make_store(root)
    assert list(probe.pending(root)) == [], (
        f"a crash inside the transaction left intents: {probe.pending(root)!r}"
    )
    view = store.workflows.workflow("ox")
    assert view is None or view.position is None, (
        f"a crash inside the transaction left the step: {view!r}"
    )

    after = context.Process(
        target=_crashing_unit,
        args=(make_store, str(root)),
        kwargs={"exit_before_commit": False},
    )
    after.start()
    after.join(timeout=120)
    assert after.exitcode == 0, f"the crash-after-commit child exited {after.exitcode}"
    pending = list(probe.pending(root))
    assert [p.topic for p in pending] == ["topic.a"] and pending[
        0
    ].idempotency_key == "idem-a", (
        f"the committed intent did not survive exactly once: {pending!r}"
    )
    assert pending[0].payload == {"n": 1}, (
        f"the committed intent's payload did not survive intact: {pending!r}"
    )
    view = store.workflows.workflow("ox-2")
    assert view is not None and view.position == "p-s-after", (
        f"the step the intent rode did not survive: {view!r}"
    )

    try:
        with store.transaction() as tx:
            held = _claim(store, "ox-3", "raiser")
            tx.workflows.complete_step(
                CompleteStep("ox-3", held, "s", T0, position="raised")
            )
            tx.effects.append("conformance", "topic.b", None, None)
            raise RuntimeError("mid-unit")
    except RuntimeError:
        pass
    assert [p.topic for p in probe.pending(root)] == ["topic.a"], (
        f"a raised unit left an intent: {probe.pending(root)!r}"
    )
    store.close()
    return "crash before commit, crash after commit, raised unit"


# -- versioned_migrations (H-5) ---------------------------------------------------


def versioned_migrations(make_store: MakeStore, root: Path, hooks: HarnessHooks) -> str:
    """Every historical schema opens to the latest version and answers; every
    kind of damage refuses the next open with a named error."""
    harness = hooks.migrations
    assert harness is not None  # H-2 checked before the tier ran
    historical, refusals = tuple(harness.historical), tuple(harness.refusals)
    assert historical, "the migration harness declares no historical schema"
    assert {"checksum", "ahead"} <= set(refusals), (
        f"the declared refusals must at least cover checksum and ahead: {refusals!r}"
    )
    if harness.latest_version >= 2:
        assert "gap" in refusals, "a multi-revision harness must damage a gap"

    for index, schema in enumerate(historical):
        directory = root / f"hist-{index}"
        directory.mkdir(parents=True, exist_ok=True)
        harness.lay_down(directory, schema)
        store = make_store(directory)
        assert harness.version(directory) == harness.latest_version, (
            f"{schema!r} opened at version {harness.version(directory)}, "
            f"expected {harness.latest_version}"
        )
        held = _claim(store, f"mig-{index}", "runner")
        view = store.workflows.workflow(f"mig-{index}")
        assert view is not None and view.generation == held, f"{view!r}"
        store.close()
        reopened = make_store(directory)  # a reopen changes nothing
        assert harness.version(directory) == harness.latest_version
        assert reopened.workflows.workflow(f"mig-{index}") is not None
        reopened.close()

    for index, refusal in enumerate(refusals):
        directory = root / f"refused-{index}"
        directory.mkdir(parents=True, exist_ok=True)
        make_store(directory).close()
        harness.damage(directory, refusal)
        try:
            make_store(directory)
        except AssertionError:
            raise
        except Exception as refusal_error:
            assert str(refusal_error).strip(), (
                f"{refusal!r} damage refused with an empty message"
            )
        else:
            raise AssertionError(f"damaged store ({refusal}) opened without refusing")

    return f"{len(historical)} historical, {len(refusals)} refusals"


# -- offline_capable (H-6) ---------------------------------------------------------


def _refuse_network(reached: list[str]) -> None:
    """Patch the three socket entry points to refuse, recording each reach.

    The same technique the substrate probe used, re-written here because a
    shipped library cannot import from ``tests/``.
    """

    def _refuse(entry: str) -> Callable[..., None]:
        def _fail(*_args: object, **_kwargs: object) -> None:
            reached.append(entry)
            raise OSError(f"the network was taken away: {entry} refused")

        return _fail

    mock.patch.object(socket, "socket", _refuse("socket.socket")).start()
    mock.patch.object(socket, "create_connection", _refuse("create_connection")).start()
    mock.patch.object(socket, "getaddrinfo", _refuse("getaddrinfo")).start()


def offline_capable(make_store: MakeStore, root: Path, hooks: HarnessHooks) -> str:
    """BASELINE's first check — the run tree — answers with every socket
    refusing. An offline store that reaches for a network here is declaring a
    capability it does not keep."""
    reached: list[str] = []
    _refuse_network(reached)
    try:
        run_tree_and_recent_history(make_store, root)
    finally:
        mock.patch.stopall()
    assert not reached, (
        f"the store reached for the network during a baseline round trip: {reached!r}"
    )
    return "baseline round trip, network refused"


#: Every tier, keyed by the profile value that switches it on.
CAPABILITY_TIERS: tuple[CapabilityTier, ...] = (
    CapabilityTier("cross_aggregate_atomicity", True, cross_aggregate_atomicity),
    CapabilityTier("fencing", "cross-process", cross_process_fencing),
    CapabilityTier("durable_outbox", True, durable_outbox),
    CapabilityTier("versioned_migrations", True, versioned_migrations),
    CapabilityTier("offline_capable", True, offline_capable),
)


def tiers_for(profile: StoreProfile) -> tuple[CapabilityTier, ...]:
    """The tiers ``profile`` switches on — read from the profile, nothing else."""
    return tuple(tier for tier in CAPABILITY_TIERS if tier.applies_to(profile))


def capability_report(
    make_store: MakeStore,
    root: Path | None = None,
    *,
    hooks: HarnessHooks | None = None,
) -> CapabilityReport:
    """Run every tier the store's profile declares; report each with its strength.

    A tier that needs a harness hook the caller did not hand over raises
    ``AssertionError`` naming the field and the missing attribute — it never
    silently skips. Raises the same way for the first tier that fails.
    """
    base = Path(tempfile.mkdtemp(prefix="capabilities-")) if root is None else root
    hooks = HarnessHooks() if hooks is None else hooks
    probe_dir = base / "profile"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = make_store(probe_dir)
    profile = probe.profile
    probe.close()
    runs = []
    for index, tier in enumerate(tiers_for(profile)):
        needed = NEEDS_HOOK.get(tier.field)
        if needed is not None and getattr(hooks, needed) is None:
            raise AssertionError(
                f"capability tier {tier.name}: the profile switches this tier on "
                f"and HarnessHooks.{needed} is None — hand the suite the "
                f"{needed} instrument, or the declaration is unproven"
            )
        directory = base / f"{index}-{tier.field}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            strength = tier.check(make_store, directory, hooks)
        except AssertionError as failure:
            raise AssertionError(f"capability tier {tier.name}: {failure}") from failure
        runs.append(TierRun(name=tier.name, strength=strength))
    return CapabilityReport(runs=tuple(runs))


def run_capability_tiers(
    make_store: MakeStore,
    root: Path | None = None,
    *,
    hooks: HarnessHooks | None = None,
) -> tuple[str, ...]:
    """Run every tier the store's profile declares; return the names that ran.

    Raises ``AssertionError`` naming the first tier that fails.
    """
    return capability_report(make_store, root, hooks=hooks).names
