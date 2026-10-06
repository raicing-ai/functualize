"""BASELINE — what every runtime store must do, whatever its profile declares.

The design package's list (`08-delivery-and-tests.md`), one check each:

1. run tree and recent history;
2. workflow transition and replay determinism;
3. state batch and rollback;
4. corrupt-data policy;
5. event sequence monotonicity;
6. close / reopen durability.

Every check talks to the store through the public port only — commands in,
questions out — so a third-party backend runs exactly what the shipped ones
run. Checks are plain functions that raise ``AssertionError``; nothing here
imports pytest. Each gets a fresh directory and builds its own store from it
with ``make_store``; a check that reopens calls ``make_store`` again on the
same directory, which is how a store says what "the same store" means.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    FinishAttempt,
    IllegalTransition,
    RunQuery,
    RuntimeStore,
    StartAttempt,
    StateBatch,
    SuspendAtGate,
    WorkflowQuery,
)

__all__ = ["BASELINE", "MakeStore", "run_baseline"]

#: Builds a store over a directory. Called again on the same directory, it must
#: open the same data — that is what close/reopen durability checks.
MakeStore = Callable[[Path], RuntimeStore]

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = 300.0


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _claim(store: RuntimeStore, scope_id: str, owner: str = "runner-a") -> int:
    with store.transaction() as tx:
        outcome = tx.workflows.claim(ClaimWorkflow(scope_id, owner, T0, LEASE))
    assert isinstance(outcome, Claimed), (
        f"a first claim of {scope_id!r} answered {outcome!r}"
    )
    return outcome.generation


def _run_id(store: RuntimeStore, job: str) -> str:
    [view] = store.runs.recent(RunQuery(job=job))
    return view.run_id


# -- 1 ------------------------------------------------------------------------


def run_tree_and_recent_history(make_store: MakeStore, root: Path) -> None:
    """A run, its child, newest-first history, filters, and a finished outcome."""
    store = make_store(root)
    with store.transaction() as tx:
        tx.runs.start_attempt(StartAttempt("parent", "cli", _at(1)))
    parent = _run_id(store, "parent")
    with store.transaction() as tx:
        tx.runs.start_attempt(
            StartAttempt("child", "cli", _at(2), parent_run_id=parent, invoke_depth=1)
        )
    child = _run_id(store, "child")
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(child, 1, "success", _at(3)))

    tree = store.runs.tree(parent)
    assert tree.run.run_id == parent, "tree() is not rooted at the run asked for"
    assert [c.run.run_id for c in tree.children] == [child], (
        "the child is not under its parent"
    )

    finished = store.runs.run(child)
    assert finished is not None and finished.status == "success", (
        f"child reads {finished!r}"
    )
    assert finished.parent_run_id == parent and finished.invoke_depth == 1

    recent = [v.run_id for v in store.runs.recent(RunQuery())]
    assert recent[:2] == [child, parent], f"recent() is not newest first: {recent}"
    assert [v.run_id for v in store.runs.recent(RunQuery(limit=1))] == [child]
    assert [v.run_id for v in store.runs.recent(RunQuery(parent_run_id=parent))] == [
        child
    ]
    assert store.runs.run("run-that-never-was") is None
    store.close()


# -- 2 ------------------------------------------------------------------------


def workflow_transition_and_replay_determinism(
    make_store: MakeStore, root: Path
) -> None:
    """Claims fence by generation; a walk moves through legal states only; a
    gate opens one request and a re-entering walk keeps it."""
    store = make_store(root)
    gen = _claim(store, "wf")
    with store.transaction() as tx:
        loser = tx.workflows.claim(ClaimWorkflow("wf", "runner-b", T0, LEASE))
    assert loser == Conflict("wf", held_by="runner-a", held_generation=gen), (
        f"got {loser!r}"
    )

    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("wf", gen, "first", _at(1), position="gate")
        )
    with store.transaction() as tx:
        tx.workflows.suspend(SuspendAtGate("wf", gen, "gate", "req-1", "gate", _at(2)))
    # The walk re-enters the gate (back through ``running``) and suspends again
    # with a freshly minted id: the live request must be kept, not reopened.
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("wf", gen, "first", _at(2), position="gate")
        )
    with store.transaction() as tx:
        tx.workflows.suspend(SuspendAtGate("wf", gen, "gate", "req-2", "gate", _at(2)))

    view = store.workflows.workflow("wf")
    assert view is not None and (view.status, view.position) == ("blocked", "gate"), (
        f"{view!r}"
    )
    assert view.generation == gen and view.owner == "runner-a"
    request = store.inputs.open_for("wf")
    assert request is not None and request.request_id == "req-1", (
        f"replay reopened: {request!r}"
    )
    assert [r.request_id for r in store.inputs.awaiting()] == ["req-1"]
    assert store.inputs.request("req-1") == request
    assert [
        w.scope_id for w in store.workflows.resumable(WorkflowQuery(status="blocked"))
    ] == ["wf"]

    with store.transaction() as tx:  # past the gate, the walk runs on to END
        tx.workflows.complete_step(
            CompleteStep("wf", gen, "gate", _at(3), position="last")
        )
        tx.workflows.complete_step(
            CompleteStep(
                "wf", gen, "last", _at(3), position=None, scope_status="completed"
            )
        )
    try:
        with store.transaction() as tx:
            tx.workflows.complete_step(
                CompleteStep("wf", gen, "again", _at(4), scope_status="blocked")
            )
    except IllegalTransition:
        pass
    else:
        raise AssertionError(
            "completed -> blocked was accepted; the scope machine refuses it"
        )
    after = store.workflows.workflow("wf")
    assert after is not None and after.status == "completed", (
        f"a refused move landed: {after!r}"
    )
    store.close()


# -- 3 ------------------------------------------------------------------------


def state_batch_and_rollback(make_store: MakeStore, root: Path) -> None:
    """A unit applies whole or not at all, and a stale generation lands nothing."""
    store = make_store(root)
    gen = _claim(store, "st")
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("st", gen, _at(1), {"a": 1, "b": [1, 2]}))
        tx.workflows.complete_step(
            CompleteStep("st", gen, "one", _at(1), position="p1")
        )

    try:
        with store.transaction() as tx:
            tx.workflows.write_state(
                StateBatch("st", gen, _at(2), {"a": 2}, deletes=("b",))
            )
            tx.workflows.complete_step(
                CompleteStep("st", gen, "two", _at(2), position="p2")
            )
            raise _AbortError
    except _AbortError:
        pass
    view = store.workflows.workflow("st")
    assert view is not None and view.position == "p1", (
        f"a raising unit applied: {view!r}"
    )

    with store.transaction() as tx:
        taken = tx.workflows.claim(
            ClaimWorkflow("st", "runner-b", _at(3), LEASE, force=True)
        )
    assert isinstance(taken, Claimed) and taken.generation > gen
    try:
        with store.transaction() as tx:
            tx.workflows.complete_step(
                CompleteStep("st", gen, "stale", _at(4), position="stale")
            )
    except Exception:  # the refusal's type is the store's own; landing is the defect
        pass
    view = store.workflows.workflow("st")
    assert view is not None and view.position == "p1", (
        f"a stale generation landed: {view!r}"
    )
    assert view.generation == taken.generation and view.owner == "runner-b"
    store.close()


class _AbortError(Exception):
    """Raised inside a unit to prove the unit applies nothing."""


# -- 4 ------------------------------------------------------------------------


def corrupt_data_policy(make_store: MakeStore, root: Path) -> None:
    """A value outside the vocabulary is refused before it is written; a question
    about something that does not exist is answered ``None``, never invented."""
    store = make_store(root)
    gen = _claim(store, "cd")
    for bad in ("finished", "RUNNING-ish", ""):
        try:
            with store.transaction() as tx:
                tx.workflows.complete_step(
                    CompleteStep("cd", gen, "x", _at(1), scope_status=bad)
                )
        except IllegalTransition:
            continue
        raise AssertionError(f"scope status {bad!r} was accepted")
    view = store.workflows.workflow("cd")
    assert view is not None and view.status == "running", (
        f"a refused status landed: {view!r}"
    )

    with store.transaction() as tx:
        tx.runs.start_attempt(StartAttempt("job", "cli", _at(2)))
    run_id = _run_id(store, "job")
    try:
        with store.transaction() as tx:
            tx.runs.finish_attempt(FinishAttempt(run_id, 1, "exploded", _at(3)))
    except IllegalTransition:
        pass
    else:
        raise AssertionError("run status 'exploded' was accepted")
    run = store.runs.run(run_id)
    assert run is not None and run.status == "running", (
        f"a refused run status landed: {run!r}"
    )

    assert store.workflows.workflow("no-such-scope") is None
    assert store.inputs.open_for("no-such-scope") is None
    assert store.inputs.request("no-such-request") is None
    assert list(store.workflows.events_after("no-such-scope", 0)) == []
    store.close()


# -- 5 ------------------------------------------------------------------------


def event_sequence_monotonicity(make_store: MakeStore, root: Path) -> None:
    """``seq`` strictly increases per scope, and "after N" means exactly that."""
    store = make_store(root)
    gen = _claim(store, "ev")
    for n in range(4):
        with store.transaction() as tx:
            tx.workflows.complete_step(
                CompleteStep("ev", gen, f"s{n}", _at(n), position=f"s{n}")
            )
            tx.events.append("conformance.tick", {"n": n})

    ticks = [
        e for e in store.workflows.events_after("ev", 0) if e.type == "conformance.tick"
    ]
    assert [e.payload for e in ticks] == [{"n": n} for n in range(4)], (
        f"events: {ticks!r}"
    )
    seqs = [e.seq for e in ticks]
    assert all(a < b for a, b in zip(seqs, seqs[1:], strict=False)), (
        f"seq not increasing: {seqs}"
    )
    later = store.workflows.events_after("ev", seqs[1])
    assert [e.seq for e in later if e.type == "conformance.tick"] == seqs[2:]
    assert all(e.seq > seqs[1] for e in later)
    store.close()


# -- 6 ------------------------------------------------------------------------


def close_reopen_durability(make_store: MakeStore, root: Path) -> None:
    """What committed before ``close()`` is what a new store over the same place reads."""
    store = make_store(root)
    gen = _claim(store, "du")
    with store.transaction() as tx:
        tx.workflows.suspend(SuspendAtGate("du", gen, "gate", "req-du", "gate", _at(1)))
        tx.runs.start_attempt(StartAttempt("durable", "cli", _at(1), scope_id="du"))
    run_id = _run_id(store, "durable")
    store.close()

    reopened = make_store(root)
    view = reopened.workflows.workflow("du")
    assert view is not None and (view.status, view.generation) == ("blocked", gen), (
        f"{view!r}"
    )
    request = reopened.inputs.open_for("du")
    assert request is not None and request.request_id == "req-du"
    run = reopened.runs.run(run_id)
    assert run is not None and (run.job, run.scope_id) == ("durable", "du"), f"{run!r}"
    reopened.close()


#: The checks, in the design package's order — ``(name, check)``.
BASELINE: tuple[tuple[str, Callable[[MakeStore, Path], None]], ...] = (
    ("run tree and recent history", run_tree_and_recent_history),
    (
        "workflow transition and replay determinism",
        workflow_transition_and_replay_determinism,
    ),
    ("state batch and rollback", state_batch_and_rollback),
    ("corrupt-data policy", corrupt_data_policy),
    ("event sequence monotonicity", event_sequence_monotonicity),
    ("close/reopen durability", close_reopen_durability),
)


def run_baseline(make_store: MakeStore, root: Path | None = None) -> None:
    """Run every BASELINE check; raise ``AssertionError`` naming the first that fails.

    ``root`` is where each check gets its own directory; a temporary one is
    made (and left for inspection) when none is given.
    """
    base = Path(tempfile.mkdtemp(prefix="conformance-")) if root is None else root
    for index, (name, check) in enumerate(BASELINE):
        directory = base / f"{index}-{name.replace(' ', '-').replace('/', '-')}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            check(make_store, directory)
        except AssertionError as failure:
            raise AssertionError(f"BASELINE {name!r}: {failure}") from failure
