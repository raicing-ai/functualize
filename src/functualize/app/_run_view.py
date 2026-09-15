"""What happened in this project — the run-log projection.

`durable-run-layer`/T3. One projection, thin callers: the shape
`app/_workflow_view.py` established for scopes and this applies to runs. The
CLI renders these rows and the MCP tools return them; neither reads the store
directly, so `func builtin run list` and `list_runs` cannot answer differently.

**Runs and scopes answer different questions**, which is why this is a second
projection rather than a filter on the first:

* a **scope** is *a workflow's position* — which steps are done, which gate is
  waiting, where the walk stopped. It exists to be resumed.
* a **run** is *one execution* — what was asked for, through which door, by
  which process, and how it ended. It exists to be read afterwards.

A workflow that blocked and resumed three times is **one scope and four runs**.
Asking "what is waiting on me" is a scope question; asking "why did last
night's build fail" is a run question, and until this module there was nowhere
to ask it — `runs.json` was written by `engine.run` and read by nothing.

## Derived, never stored

`state`, `duration_ms` and `children` are computed here. Nothing is added to
the record, so no format version moves (decision K4, inherited C2), and a
reader that wants the raw entry can still have it.

The important one is **`state`**. A record carries `status`, which is what the
run *reported*; `state` is what is true now. They differ in exactly one case
and it is the case that matters: a record still open when the process that
owned it is gone reads `running` for ever, because nothing reaps it. That is
named `abandoned` here — the same word `_workflow_view.derived_state` will gain
for scopes in T8, chosen so one vocabulary covers both.

Today `abandoned` is reported only when a run has no end and its runner is not
this process. That is a weaker test than the lease T5 will provide, and it is
deliberately conservative: a long-running job on another machine must not be
called dead. The docstring on `_derive_state` says exactly what it can and
cannot know, because a projection that guesses is worse than one that abstains.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from functualize._types.enums import RunStatus
from functualize._types.run_request import SURFACE_POLICY

__all__ = [
    "RUN_STATES",
    "describe_run",
    "job_history",
    "list_runs",
    "run_events",
    "run_tree",
]

#: Every value `state` can take: every `RunStatus` a run can close with, plus
#: the one value this module derives.
#:
#: **Derived from `RunStatus`, not written out.** The first version of this
#: line was a hand-written tuple and it was wrong — it guessed six values where
#: there are ten, omitting `cancelled`, `skipped`, `timeout` and `unknown`. A
#: surface enumerating it would have rejected four legal filters. That is
#: exactly the sixth-copy failure `contributor/reference/pitfalls.md` §6
#: describes, committed while writing a comment citing §6.
RUN_STATES: tuple[str, ...] = (
    *sorted(status.value.lower() for status in RunStatus),
    #: Not a `RunStatus`: no run ever *reports* being abandoned, because a run
    #: that could report it would not be abandoned. See `_derive_state`.
    "abandoned",
)


def _parse(stamp: Any) -> datetime | None:
    """An ISO timestamp from the store, or None if it is missing or malformed.

    Never raises. A run record whose clock string cannot be read is still a run
    worth listing; losing the whole row over a duration is the wrong trade.
    """
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _duration_ms(record: dict[str, Any]) -> float | None:
    """Wall-clock milliseconds, or None while the run is still open."""
    started, ended = _parse(record.get("started_at")), _parse(record.get("ended_at"))
    if started is None or ended is None:
        return None
    return (ended - started).total_seconds() * 1000.0


def _derive_state(record: dict[str, Any], *, this_runner: str | None) -> str:
    """What is true about this run *now*, which is not always what it reported.

    `status` is what the run said on its way out. It is absent while the run is
    in flight — and stays absent for ever if the process died before closing
    the record, because nothing reaps it. A reader cannot tell those two apart
    from the record alone, and calling both `running` is how a crashed run
    stays invisible.

    **What this can know, and what it cannot.** A record with no end whose
    `runner` is *this* process is genuinely running — we are the process, and
    we are alive. A record with no end whose runner is some *other* identity is
    the ambiguous one: it may be a job running right now on another machine, or
    the wreckage of one that died. It is reported `abandoned`.

    That is a real over-report and it is the conservative direction only
    because of what each error costs: calling a live run abandoned is a
    misleading row a human can re-check, while calling a dead run `running`
    hides it for ever. The honest fix is a lease with a renewal — `T5` — after
    which this function reads liveness instead of inferring it. Until then the
    weakness is stated rather than hidden.
    """
    status = record.get("status")
    if isinstance(status, str) and status:
        return status
    runner = record.get("runner")
    if this_runner is not None and runner == this_runner:
        return "running"
    return "abandoned"


def _describe(
    run_id: str, record: dict[str, Any], store: Any, *, this_runner: str | None
) -> dict[str, Any]:
    """One row. The full projection — there is no reduced survey shape.

    `_workflow_view.list_scopes` explains why at length and the reasoning is
    identical: one key meaning two things across two shapes is the drift these
    modules exist to end. A caller wanting one line renders one; it does not get
    a different projection to render it from.
    """
    return {
        "run_id": run_id,
        "job": record.get("job"),
        "surface": record.get("surface"),
        "state": _derive_state(record, this_runner=this_runner),
        "status": record.get("status"),
        "started_at": record.get("started_at"),
        "ended_at": record.get("ended_at"),
        "duration_ms": _duration_ms(record),
        "scope_id": record.get("scope_id"),
        "parent_run_id": record.get("parent_run_id"),
        "invoke_depth": record.get("invoke_depth", 0),
        "runner": record.get("runner"),
        "args_hash": record.get("args_hash"),
        "force": bool(record.get("force")),
        "group_option_values": record.get("group_option_values") or {},
        "children": [child.get("run_id") for child in store.children_of(run_id)],
        "event_count": len(store.events_for(run_id)),
    }


def _this_runner() -> str | None:
    """This process's runner identity, or None if it cannot be determined."""
    try:
        from functualize._primitives.run_store import runner_identity

        return runner_identity()
    except Exception:  # noqa: BLE001 - a projection never fails over identity
        return None


def describe_run(store: Any, run_id: str) -> dict[str, Any] | None:
    """Everything known about one run, or None if there is no such run.

    None rather than raising, so a caller renders its own not-found message
    with its own exit code — the same contract `describe_scope` has.
    """
    record = store.get_run(run_id)
    if record is None:
        return None
    return _describe(run_id, record, store, this_runner=_this_runner())


def list_runs(
    store: Any,
    *,
    job: str | None = None,
    surface: str | None = None,
    state: str | None = None,
    scope_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Runs matching the filters, **newest first**.

    Newest first is the opposite of `list_scopes`, and deliberately so: a scope
    list answers "what is waiting on me", where order is incidental, while a run
    list answers "what just happened", where it is the entire question.

    Args:
        job: Only runs of this job.
        surface: Only runs started through this door — `cli`, `http`, `invoke`,
            `app.execute`. The field exists so a run's origin is *carried* by
            the request rather than reconstructed from what else is in the
            record; this is what makes it answerable.
        state: Only runs whose **derived** state matches (see `RUN_STATES`).
            Derived rather than stored, for the reason `_derive_state` gives —
            filtering on `status` cannot express "which runs never finished",
            which is the query a person actually has.
        scope_id: Only runs that executed in this scope. The join between the
            two projections: a workflow that blocked and resumed three times is
            one scope and four runs, and this is how the four are found.
        limit: How many rows at most. Applied **after** filtering, so a narrow
            filter is not starved by a flood of unrelated recent runs.
    """
    this_runner = _this_runner()
    rows: list[dict[str, Any]] = []
    for run_id in sorted(store.run_ids(), reverse=True):
        record = store.get_run(run_id)
        if record is None:
            continue
        if job is not None and record.get("job") != job:
            continue
        if surface is not None and record.get("surface") != surface:
            continue
        if scope_id is not None and record.get("scope_id") != scope_id:
            continue
        if (
            state is not None
            and _derive_state(record, this_runner=this_runner) != state
        ):
            continue
        rows.append(_describe(run_id, record, store, this_runner=this_runner))
        if len(rows) >= max(0, limit):
            break
    return rows


def run_events(store: Any, run_id: str) -> list[dict[str, Any]] | None:
    """A run's events in sequence order, or None if there is no such run.

    **Ordered by `seq`, never by timestamp.** The sequence is assigned by the
    store and is monotonic per run, so a replay is correct across two processes
    on two clocks — which timestamps cannot promise.

    An empty list and None are different answers: `[]` is a run that emitted
    nothing (or whose events were trimmed by `EVENTS_PER_RUN_LIMIT`), None is a
    run that does not exist.
    """
    if store.get_run(run_id) is None:
        return None
    return sorted(store.events_for(run_id), key=lambda e: e.get("seq", 0))


def run_tree(store: Any, run_id: str) -> dict[str, Any] | None:
    """One run and its descendants, nested by `parent_run_id`.

    The question the flat list cannot answer: *what did this run set off?* A
    workflow step, a dependency and an `rc.invoke` child are all runs, and their
    relationship is the thing the history ring dropped and the run log keeps.

    Cycles are impossible — a child's id is minted after its parent's — but the
    walk still carries a `seen` set, because a hand-edited or partially trimmed
    log should produce a short tree rather than a hang.
    """
    root = describe_run(store, run_id)
    if root is None:
        return None

    def _expand(node: dict[str, Any], seen: set[str]) -> dict[str, Any]:
        children = []
        for child_id in node.get("children", []):
            if not child_id or child_id in seen:
                continue
            seen.add(child_id)
            child = describe_run(store, child_id)
            if child is not None:
                children.append(_expand(child, seen))
        return {**node, "children": children}

    return _expand(root, {run_id})


def _is_a_launch(record: dict[str, Any]) -> bool:
    """Did the *user* ask for this run, as opposed to something it set off?

    The rule `executor._records_history` used to apply at **write** time, moved
    here and applied at read time. It is reproducible because both of its
    inputs — `surface` and `invoke_depth` — are in the run record, which is the
    whole reason history can be derived rather than stored.

    `invoke_depth == 0` is the ordinary answer. The exception is an item of a
    **top-level parallel batch**: `func builtin parallel a b` reaches
    `Invoke.parallel`, which runs each item at depth 1, so the plain depth rule
    showed neither `a` nor `b` for a command the user had just run.

    **The distinction is the door, not the depth** — a top-level job's context
    and the standalone `WiredInvoke` that `app.execute_parallel` builds both sit
    at depth 0, so both put their items at depth 1. `app.execute_parallel`
    stamps its items `app.parallel` and is included; `rc.invoke_parallel` stamps
    `invoke.parallel` and is not, because its parent is already listed.
    """
    if record.get("invoke_depth", 0) == 0:
        return True
    surface = record.get("surface")
    policy = SURFACE_POLICY.get(surface) if surface else None
    return bool(policy and policy.records_batch_items)


def job_history(store: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """What the user launched, newest first — derived, not stored.

    Until `durable-run-layer`/T3b this was a second record: a 200-entry ring in
    the freshness ledger, written by the engine beside the run log. The log already
    held every one of those runs *and* the nested ones *and* who invoked them,
    so the ring was a poorer copy of a subset — the drift these projections
    exist to end, in the one place it had survived.

    Shaped exactly as the ring's job entries were (`namespace`, `job`,
    `args_hash`, `status`, `duration_ms`, `at`), so `func builtin history` and
    its renderer are unchanged by the move. The one thing the ring was strict
    about is preserved: **argument values are never included**, only their
    hash, so a record identifies a run without persisting its inputs.
    """
    out: list[dict[str, Any]] = []
    for run_id in sorted(store.run_ids(), reverse=True):
        record = store.get_run(run_id)
        if record is None or not _is_a_launch(record):
            continue
        duration = _duration_ms(record)
        out.append(
            {
                "namespace": "job",
                "job": record.get("job"),
                "args_hash": record.get("args_hash"),
                "status": record.get("status"),
                "duration_ms": None if duration is None else round(duration, 3),
                "at": record.get("started_at"),
            }
        )
        if limit is not None and len(out) >= limit:
            break
    return out
