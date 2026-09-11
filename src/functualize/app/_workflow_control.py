"""Workflow verbs that *do* something — the side-effecting half.

``_workflow_view`` reads and ``_workflow_answer`` records. This module is the
only one of the three that runs jobs, and everything in it goes through one
function.

**Why the funnel matters.** The MCP adapter enforces its gate-tool policy at
``_execute_job``, described in its own comment as *"the one place a
job-executing call cannot get past, so there is no version of the check a
caller can forget to make"*. Making ``builtin workflow resume`` **advance** a
walk turns the CLI into a second job-executing door. A door that called
``app.execute`` directly would leave the gate policy as theatre — exactly the
failure ``_gate_refusal`` was written to prevent, where an agent refused
``deploy`` as a tool just calls ``run_job("deploy")`` instead.

So every path that can run a job while a gate waits — CLI ``workflow resume``,
MCP ``resume_workflow``, ``call_gate_tool`` — is routed through the module's
one job-executing chokepoint, and :class:`GateToolPolicy` lives here rather
than in the plugin. A check that a caller can skip by not calling it is not a
permission. ``--wf-resume`` is not one of those paths: the click wrappers
resolve it with ``apply_workflow_flags`` and run the engine directly. The walk
it continues is the workflow's own — the continuation no policy governs
(``resume_scope`` passes ``policy=None`` for the same reason) — so routing it
through the chokepoint would add nothing.

**``resume`` advances; ``answer`` records.** One meaning each, on every surface.
This is the verb the whole feature exists for: before it, nothing anywhere
advanced a blocked walk except re-invoking the job process, which an agent over
MCP cannot do.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._types.errors import ScopeCancelledError
from functualize.app._workflow_answer import answer_gate
from functualize.app._workflow_resume import pending_gates
from functualize.app._workflow_view import (
    LIVE_STATUSES,
    TERMINAL_STATES,
    derived_state,
    describe_scope,
    tool_entries,
)

__all__ = [
    "GateToolPolicy",
    "advanceable_scopes",
    "call_gate_tool",
    "cancel_scope",
    "guarded_execute",
    "purge_scopes",
    "resume_scope",
]


if TYPE_CHECKING:
    from functualize._types.run_request import RunSurface


logger = logging.getLogger(__name__)


def _canonical(name: str) -> str:
    """A job name in the canonical form jobs are registered under."""
    from functualize._types.naming import normalize_name

    return normalize_name(name) or name


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": code, "message": message, **extra}


class GateToolPolicy:
    """Decides whether a job may run while a gate is waiting.

    ``Gate(name, awaits, tools)`` declares what may be used while resolving that
    gate, and ``tools`` is a *permission*: a job call arriving while the gate
    waits is refused unless the job is named.

    Lifted out of the MCP plugin so the CLI's new advance verbs take the same
    lock. It governed one surface while only one surface could run a job; that
    stopped being true the moment ``resume`` advanced.

    **The workflow's own continuation is never governed.** ``resume_scope`` runs
    the workflow job itself, and the policy's allow-list is built from the
    *gate's* ``tools`` — so a gate declaring ``tools=["build"]`` would refuse the
    very walk that is the way out of the block. That is the same rule the
    original policy stated for the read tools and for the same reason: an actor
    that could not inspect, answer, or continue the gate blocking it would have
    no way out at all. What this governs is an actor running *other* jobs while
    a gate waits.

    **Which gate governs.** A call carries no scope id, so when several scopes
    wait at once the policy takes the **union** of their lists — an intersection
    would let two unrelated workflows deadlock each other. A gate that declares
    no tools asks for no restriction, so a single such gate lifts the
    restriction entirely rather than being read as "permit nothing".
    """

    def __init__(self, app: Any, *, store: Any = None) -> None:
        self._app = app
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from functualize._primitives.fresh_store import FreshStore

            self._store = FreshStore.for_project(Path.cwd())
        return self._store

    def permitted(self, tool_name: str) -> bool:
        """True when ``tool_name`` may run right now.

        The name is canonicalized first: tools are jobs, jobs are addressed
        canonically, and a caller asking for ``order_history`` means the
        ``order-history`` on the allow-list. Comparing raw strings refused a
        permitted call and reported a missing permission, which is a maximally
        misleading way to fail.
        """
        allowed = self.allowed_tools()
        return allowed is None or _canonical(tool_name) in allowed

    def allowed_tools(self) -> set[str] | None:
        """The permitted jobs, or None when nothing is restricted."""
        declared: list[list[str]] = []
        for scope_id in self.store.scope_ids():
            scope = self.store.get_scope(scope_id)
            if scope is None or scope.get("status") not in LIVE_STATUSES:
                continue
            for _name, record in pending_gates(scope):
                entries = tool_entries(record)
                if not entries:
                    return None  # a gate asking for no restriction wins
                declared.append([e["tool"] for e in entries])

        if not declared:
            return None
        return {tool for tools in declared for tool in tools}

    def refusal(self, tool_name: str) -> dict[str, Any]:
        """The error envelope for a refused call."""
        allowed = self.allowed_tools() or set()
        return {
            "error": "tool_not_permitted",
            "message": (
                f"'{tool_name}' is not permitted while a workflow gate is "
                "awaiting input. Answer the gate, or use one of the tools it "
                "allows."
            ),
            "tool": tool_name,
            "allowed_tools": sorted(allowed),
        }


def guarded_execute(
    app: Any,
    store: Any,
    job_name: str,
    *,
    scope_id: str | None = None,
    policy: GateToolPolicy | None = None,
    surface: RunSurface = "app.execute",
    **kwargs: Any,
) -> Any:
    """Run a job, subject to the waiting gate's tool policy.

    The chokepoint. Every surface that can start a job while a gate waits calls
    this rather than ``app.execute``, so there is no version of the check a
    caller can forget to make.

    Raises:
        PermissionError: carrying the refusal envelope as its argument, so a
            caller that forgot to handle it fails loudly instead of running the
            job anyway.
    """
    if policy is not None and not policy.permitted(job_name):
        raise PermissionError(policy.refusal(job_name))
    from functualize.types import RunRequest

    # A request, not a name plus keywords. `scope_id` is a **control input** and
    # says so by landing on `workflow_scope_id`; `**kwargs` are the job's own
    # arguments and stay in `kwargs`. Before run-request/T15 the facade took
    # both through one `**kwargs`, so a caller who splatted a payload could
    # choose the scope the run joined (spec 1.6a). This door is the chokepoint
    # for starting a job while a gate waits, which makes it exactly the one that
    # must not be able to confuse the two.
    return app.execute(
        RunRequest(
            job_name=_canonical(job_name),
            # The door that asked, not a constant. This was hardcoded
            # `app.execute`, so `func builtin workflow resume`, an MCP workflow
            # tool and a programmatic call were indistinguishable in the one
            # field whose whole purpose is telling them apart (rre F9). The
            # default stays `app.execute` because a caller with nothing to say
            # about its door genuinely *is* a programmatic one.
            surface=surface,
            kwargs=kwargs,
            workflow_scope_id=scope_id,
        )
    )


def advanceable_scopes(store: Any, workflow_name: str | None = None) -> list[str]:
    """Scope ids a ``resume`` could advance, in store order.

    ``running`` and ``blocked`` both qualify: a resumed walk reports ``blocked``
    for its whole duration (``FrontierWalk.start`` sets ``RUNNING`` only on
    first entry), so excluding one would hide live runs rather than stale ones.

    Terminal scopes never qualify — a cancelled one is refused by the engine,
    and a completed one has nothing to advance.
    """
    return [
        sid
        for sid in store.scope_ids()
        if (scope := store.get_scope(sid)) is not None
        and scope.get("status") in LIVE_STATUSES
        and (workflow_name is None or scope.get("workflow") == workflow_name)
    ]


def resolve_advanceable(
    store: Any, scope_id: str | None, workflow_name: str | None = None
) -> str | dict[str, Any]:
    """The scope to advance, or an error naming what to do instead.

    **Ambiguity never guesses.** Zero candidates is an error naming the survey
    verb; exactly one is used; several are listed. Never "newest wins" —
    ``blocked_at`` resets on every re-block, so recency is not computable even
    if it were wanted.
    """
    if scope_id is not None:
        scope = store.get_scope(scope_id)
        if scope is None:
            # The defect this replaces: `--scope-id <typo>` silently started a
            # *new* run under the typo'd id, because the runner does
            # `scope_id or new_scope_id()` and the walk calls `ensure_scope`.
            # Advancing an id that does not exist is a mistake, not an intent.
            return _error(
                "workflow_not_found",
                f"No workflow scope '{scope_id}'. It was not created — "
                "use --wf-run-id to start a run under a chosen id.",
            )
        return scope_id

    candidates = advanceable_scopes(store, workflow_name)
    if not candidates:
        which = f" of '{workflow_name}'" if workflow_name else ""
        return _error(
            "no_advanceable_scope",
            f"No workflow scope{which} is waiting. "
            "Run `func builtin workflow list` to see what is.",
        )
    if len(candidates) > 1:
        return _error(
            "ambiguous_scope",
            f"{len(candidates)} scopes could be advanced. Name one.",
            candidates=candidates,
        )
    return candidates[0]


def resume_scope(
    app: Any,
    store: Any,
    scope_id: str,
    *,
    input: dict[str, Any] | None = None,
    gate: str | None = None,
    retry_epilogue: bool = False,
    surface: RunSurface = "app.execute",
) -> dict[str, Any]:
    """Advance a workflow scope to its next durable boundary.

    Optionally answers a gate first, so *answer and continue* is one command
    rather than two — the fusion that makes ``--wf-resume --wf-input`` useful.
    The answer still goes through the same :func:`answer_gate`, so a fused
    answer and a standalone one cannot validate differently.

    Args:
        input: Gate input to record before walking.
        gate: Which gate ``input`` answers, when several are pending.
        retry_epilogue: Clear a recorded epilogue so the body re-runs. For the
            sticky-body case: a walk that reached ``END`` and whose body then
            failed is ``completed`` with a failed epilogue, and without this it
            can never run again.

    Returns a flat result dict carrying ``status`` (the walk's outcome),
    ``workflow_id``, and the scope projection under ``scope``.
    """
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
    if scope.get("status") == "cancelled":
        return _error(
            "scope_cancelled",
            f"Workflow scope '{scope_id}' was cancelled and cannot be resumed.",
        )

    if input is not None:
        pending = [name for name, _ in pending_gates(scope)]
        if gate is None:
            if not pending:
                return _error(
                    "gate_not_found",
                    f"Workflow '{scope_id}' has no gate awaiting input.",
                )
            if len(pending) > 1:
                return _error(
                    "ambiguous_gate",
                    f"Workflow '{scope_id}' has {len(pending)} pending gates. "
                    "Name the one this input answers.",
                    pending_gates=pending,
                )
            gate = pending[0]
        answered = answer_gate(app, store, scope_id, gate, input)
        if "error" in answered:
            return answered
        if answered.get("status") != "answered":
            # An incomplete draft is not a failure, but it is also not a reason
            # to walk: the gate still blocks, so advancing would return the
            # caller to exactly where they started with no explanation.
            answered["message"] = (
                f"{answered['message']} The walk was not advanced — the gate "
                "is still waiting."
            )
            return answered

    if retry_epilogue:
        _clear_epilogue(store, scope_id)

    workflow_name = scope.get("workflow")
    if not isinstance(workflow_name, str):
        return _error(
            "workflow_not_found",
            f"Scope '{scope_id}' does not name a workflow to advance.",
        )

    try:
        # Through the funnel, with **no policy** — deliberately.
        #
        # The gate-tool allow-list is built from the gate's own `tools`, so a
        # gate declaring `tools=["build"]` would refuse `release` and the walk
        # that is the only way out of the block could never run. The policy
        # governs an actor running *other* jobs while a gate waits, not the
        # workflow's own continuation; `GateToolPolicy` states the same rule for
        # the read tools, and for the same reason.
        #
        # Still routed through `guarded_execute` rather than calling
        # `app.execute` directly, so there is exactly one place a workflow verb
        # starts a job and a future verb cannot quietly grow a second.
        result = guarded_execute(
            app,
            store,
            workflow_name,
            scope_id=scope_id,
            policy=None,
            surface=surface,
        )
    except ScopeCancelledError as exc:
        return _error("scope_cancelled", str(exc))

    status = getattr(result.status, "value", str(result.status)).lower()
    return {
        "status": status,
        "workflow_id": scope_id,
        "return_value": result.return_value,
        "metadata": dict(getattr(result, "metadata", None) or {}),
        "scope": describe_scope(app, store, scope_id),
    }


def _clear_epilogue(store: Any, scope_id: str) -> None:
    """Drop the epilogue record so the body may run again.

    The one recorded thing that is *sticky on failure*: the walk reached
    ``END``, so replaying it changes nothing, and the body will not re-run while
    its record stands. Failed **steps** need no equivalent — they already re-run
    on resume, which is why ``--wf-retry-failed`` is not part of this feature.
    """
    store.record_epilogue(scope_id, None)


def cancel_scope(store: Any, scope_id: str) -> dict[str, Any]:
    """Mark a scope cancelled. Terminal — the engine refuses to resume it."""
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
    status = scope.get("status")
    if status not in LIVE_STATUSES:
        return _error(
            "workflow_not_active", f"Workflow '{scope_id}' is already {status}."
        )
    # **Take the lease first** (`durable-run-layer`/T7, AC-10). Setting the
    # status alone does not cancel a walk that is already running: that walk
    # holds the current generation, so its own COMPLETED stamp is a legal write
    # and overwrites this one. Forcing a claim supersedes it — its next write is
    # refused, it stops where it is, and this cancellation is what the record
    # says.
    #
    # `force` because cancelling is exactly the case where a live holder must
    # lose. It is the second of the two verbs allowed to use it; the other is
    # an explicit `reclaim`, where a human has decided the holder is gone.
    _gen_of = getattr(store, "scope_generation", None)
    previous = _gen_of(scope_id) if callable(_gen_of) else None
    try:
        from functualize._primitives.run_store import runner_identity

        taken = store.claim_scope(
            scope_id, owner=f"cancel/{runner_identity()}", force=True
        )
        # Hold what was just taken. Without this the cancel fences **itself**
        # out: claiming moved the generation, and the status write below still
        # carries whatever this store held before — which is now stale. Found
        # by the test for AC-10, where the CLI store and the walker's store are
        # deliberately the same object.
        store.hold_scope_generation(scope_id, taken.generation)
    except Exception:  # noqa: BLE001 - a store without leases still cancels
        logger.debug("could not take the lease before cancelling", exc_info=True)

    try:
        store.set_scope_status(scope_id, "cancelled")
    finally:
        # Restore whatever this store was holding. Cancel borrows the lease to
        # make its own write land; it does not leave the caller's store fenced
        # to a generation the caller never claimed.
        if hasattr(store, "hold_scope_generation"):
            store.hold_scope_generation(scope_id, previous)
    return {
        "status": "cancelled",
        "workflow_id": scope_id,
        "message": f"Workflow '{scope_id}' has been cancelled.",
    }


def reclaim_scope(store: Any, scope_id: str) -> dict[str, Any]:
    """Take an abandoned scope, so someone else can resume it.

    **Explicit, and it has to be** (`durable-run-layer`/T8). A lease that
    expired means *nothing has heard from that runner*, not *that runner is
    dead* — a long step on a machine with a slow clock looks identical. So
    nothing reclaims on a schedule and nothing reclaims on read; a person
    decides, having looked.

    It is also **not destructive**: reclaiming moves the generation and leaves
    every step record, gate payload and position exactly where they were. That
    is the difference between this and `purge`, which remains the only verb
    that removes anything.

    Refuses a scope whose lease is **live**, because that is not an abandoned
    scope — it is one someone is using. Cancel is the verb for taking a scope
    away from a runner that is working.
    """
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")

    from datetime import UTC, datetime

    from functualize._primitives.lease import is_expired, read_lease
    from functualize._primitives.run_store import runner_identity

    lease = read_lease(scope)
    if lease is not None and not is_expired(lease, datetime.now(UTC)):
        return _error(
            "workflow_held",
            f"Workflow '{scope_id}' is held by {lease.owner} until "
            f"{lease.expires_at}. Cancel it if the holder should stop.",
        )

    # Claim, then **release**. Reclaiming is not "take this scope", it is
    # "invalidate whoever had it and let someone start". Holding the lease here
    # would leave the scope unavailable for the whole lease period to the very
    # runner that is meant to pick it up — which is what happened: the resuming
    # process could not claim and the workflow never advanced.
    #
    # Found by the crash-and-resume test, because it is the only one that goes
    # on to *use* the scope. Every unit test for `reclaim` passed: they checked
    # what the record said and stopped there.
    #
    # Releasing expires the lease in place and keeps the generation, so the dead
    # holder's writes stay refused while the scope is immediately claimable.
    previous_owner = lease.owner if lease is not None else None
    taken = store.claim_scope(scope_id, owner=runner_identity(), force=True)
    store.release_scope(scope_id, generation=taken.generation)
    return {
        "status": "reclaimed",
        "workflow_id": scope_id,
        "generation": taken.generation,
        "previous_owner": previous_owner,
        # **Says what was not done** (AC-12). A lapsed lease means that runner
        # stopped *renewing*; nothing stopped the runner. Python cannot preempt
        # a running function — `_engine/exec_policy` researched and rejected
        # every mechanism that pretends otherwise — so a reclaim that reported
        # "the old work was cancelled" would be the same lie in a new place: a
        # caller who believes the work stopped may release a lock or delete a
        # file the still-live runner is using.
        "work_not_stopped": previous_owner is not None,
        "message": (
            f"Reclaimed '{scope_id}' at generation {taken.generation}. "
            f"Writes from {previous_owner or 'any previous holder'} are now "
            f"refused, but that runner was **not** stopped — it may still be "
            f"executing. It cannot corrupt this scope; it can still touch "
            f"anything outside it."
            if previous_owner
            else f"Reclaimed '{scope_id}' at generation {taken.generation}."
        ),
    }


def purge_scopes(
    store: Any, *, state: str | None = None, older_than_days: float | None = None
) -> dict[str, Any]:
    """Delete finished scopes. Refuses to touch a live one.

    **A hard delete with no backup**, unlike ``state clear --scopes``, which
    moves the whole file aside. That asymmetry is why only terminal states are
    purgeable and why ``--state`` cannot name a live one: a mistyped filter must
    not be able to destroy a run somebody is waiting on.

    ``older_than_days`` measures the **newest** ``completed_at`` across the
    scope's step and epilogue records — the only timestamps that exist.
    ``blocked_at`` is not usable: it resets on every re-block, so it measures
    the last resume attempt rather than the wait.

    A scope with no timestamps at all is **never** matched by an age filter. It
    cannot be aged, and treating it as infinitely old would purge exactly the
    records whose history is least known.
    """
    if state is not None and state not in TERMINAL_STATES:
        return _error(
            "invalid_state",
            f"'{state}' is not a finished state. Purgeable: "
            f"{', '.join(sorted(TERMINAL_STATES))}.",
        )

    cutoff = _cutoff(older_than_days)
    removed: list[str] = []
    for sid in list(store.scope_ids()):
        scope = store.get_scope(sid)
        if scope is None:
            continue
        current = derived_state(scope)
        if current not in TERMINAL_STATES:
            continue
        if state is not None and current != state:
            continue
        if cutoff is not None:
            newest = _newest_timestamp(scope)
            if newest is None or newest > cutoff:
                continue
        if store.delete_scope(sid):
            removed.append(sid)
            # **Record first, then state.** T3 moved a run's job state out of
            # the record and into its own file, so purging the record alone
            # leaves a file nothing references and nothing will ever collect —
            # `purge_scopes` walks records, so an orphaned state file is
            # invisible to the only thing that could remove it.
            #
            # This order is the safe one and the reverse is not: a record
            # pointing at state that is already gone reads as corruption, while
            # a state file with no record reads as nothing at all. If the
            # process dies between these two lines the result is the
            # recoverable half.
            discard = getattr(store, "discard_state", None)
            if discard is not None:
                discard(sid)

    return {
        "status": "purged",
        "removed": removed,
        "count": len(removed),
        "message": (
            f"Purged {len(removed)} finished scope{'' if len(removed) == 1 else 's'}."
        ),
    }


def _cutoff(older_than_days: float | None) -> datetime | None:
    if older_than_days is None:
        return None
    from datetime import timedelta

    return datetime.now(UTC) - timedelta(days=older_than_days)


def _newest_timestamp(scope: dict[str, Any]) -> datetime | None:
    """The most recent ``completed_at`` in the scope, or None if it has none."""
    stamps: list[datetime] = []
    records: list[Any] = list((scope.get("steps") or {}).values())
    epilogue = scope.get("epilogue")
    if isinstance(epilogue, dict):
        records.append(epilogue)
    for record in records:
        if not isinstance(record, dict):
            continue
        raw = record.get("completed_at")
        if not isinstance(raw, str):
            continue
        try:
            stamps.append(datetime.fromisoformat(raw))
        except ValueError:
            continue
    return max(stamps) if stamps else None


def call_gate_tool(
    app: Any,
    store: Any,
    scope_id: str,
    tool: str,
    args: dict[str, Any] | None = None,
    *,
    policy: GateToolPolicy | None = None,
    surface: RunSurface = "app.execute",
) -> dict[str, Any]:
    """Run a tool a waiting gate offers, inside that gate's scope.

    Lifted out of the MCP plugin, which is where it had been for no reason
    beyond where it was first needed — there was no CLI spelling for running a
    gate's tool at all.

    A bound argument is **refused**, never silently overridden: a caller that
    believes it set a value and did not is worse off than one told no, and that
    difference is what separates a permission from a preference.
    """
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")

    entry = None
    for _gate_name, record in pending_gates(scope):
        for candidate in tool_entries(record):
            if _canonical(candidate["tool"]) == _canonical(tool):
                entry = candidate
    if entry is None:
        return _error(
            "tool_not_permitted",
            f"'{tool}' is not offered by any gate awaiting input in workflow "
            f"'{scope_id}'.",
            tool=tool,
            allowed_tools=sorted(
                e["tool"] for _n, r in pending_gates(scope) for e in tool_entries(r)
            ),
        )

    supplied = dict(args or {})
    overreach = sorted(set(entry["bound"]) & set(supplied))
    if overreach:
        return _error(
            "argument_not_permitted",
            f"{', '.join(overreach)} is fixed by gate policy for '{tool}' and "
            "cannot be supplied.",
            tool=tool,
            bound=entry["bound"],
        )

    bound_values, failure = _bound_values(app, scope, tool)
    if failure is not None:
        return failure

    # From here the canonical name is the one of record: it is the job that
    # actually ran, and an audit trail spelled however the caller happened to
    # type it cannot be grouped or compared.
    tool = _canonical(tool)

    try:
        result = guarded_execute(
            app,
            store,
            tool,
            scope_id=scope_id,
            policy=policy,
            surface=surface,
            **{**bound_values, **supplied},
        )
    except PermissionError as exc:
        return exc.args[0] if exc.args else _error("tool_not_permitted", str(exc))
    except Exception as exc:
        return _error("tool_failed", f"'{tool}' raised {type(exc).__name__}: {exc}")

    status = getattr(result.status, "value", str(result.status))
    store.record_tool_call(
        scope_id,
        {
            "tool": tool,
            "args": supplied,
            "status": status,
            "return_value": result.return_value,
            "called_at": _now(),
        },
    )
    return {
        "tool": tool,
        "status": status,
        "return_value": result.return_value,
        "workflow_id": scope_id,
    }


def _resolve_bound(scope: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    """Replace each ``FromStep`` marker with this scope's recorded result.

    Without this the marker object itself was handed to the job as the argument
    value — so ``Tool(read_file, allowed=FromStep("setup-vfs"))`` passed a
    ``FromStep`` where a file list was expected, and the narrowing the gate
    exists to enforce silently did not happen.

    A step with no record resolves to None rather than raising: the walk may
    legitimately not have reached it, and the job's own signature is the right
    place for that to be an error.
    """
    from functualize._primitives.fingerprint import reusable_return_value
    from functualize._types.from_job import FromStep

    if not any(isinstance(v, FromStep) for v in bound.values()):
        return dict(bound)

    steps = scope.get("steps") or {}
    resolved: dict[str, Any] = {}
    for arg, value in bound.items():
        if not isinstance(value, FromStep):
            resolved[arg] = value
            continue
        record = next(
            (
                r
                for key, r in steps.items()
                if key.split("::", 1)[0] == value.name and isinstance(r, dict)
            ),
            None,
        )
        resolved[arg] = reusable_return_value(record, job_name=value.name)
    return resolved


def _bound_values(
    app: Any, scope: dict[str, Any], tool: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The gate's pinned argument *values*, from the live declaration.

    Only the parameter *names* are persisted — a bound value is arbitrary and
    need not be JSON-safe. Reading the values here costs nothing extra, because
    running the job requires materializing its module anyway.
    """
    workflow_name = scope.get("workflow")
    try:
        entry = app.execution_engine.materialize_job(workflow_name)
        declaration = entry.function.__functualize_workflow__
        for node in declaration.gates():
            for spec in node.tool_specs():
                # `spec.name` is canonical; `tool` is whatever the caller typed.
                # Comparing them raw silently found no spec and ran the job with
                # *no* bound values — the cap the gate exists to enforce would
                # simply not apply.
                if spec.name == _canonical(tool):
                    return _resolve_bound(scope, spec.bound), None
    except Exception as exc:
        return {}, _error(
            "tool_unresolvable",
            f"Cannot load gate policy for '{tool}' from workflow "
            f"'{workflow_name}': {type(exc).__name__}: {exc}",
        )
    return {}, None
