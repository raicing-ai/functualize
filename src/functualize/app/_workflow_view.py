"""The scope projection — one implementation, every surface.

Two projections of the same store existed, in the same process, and the poorer
one faced humans. The MCP plugin's ``_describe`` computed the full graph,
position, branch choices, per-step return values and resolved inputs, and gate
schemas with bound arguments stripped. The CLI's ``_scope_summary`` emitted
**five fields** over the same records — even under ``--format json``.

Observability was inverted: the agent surface had everything, the human surface
had five fields, and the two had already drifted on every field but ``status``.
That is ``contributor/reference/pitfalls.md`` §6 — *a list hardcoded in five
places has already drifted* — and its remedy is the one applied here: **one
implementation, plus a test asserting the callers agree** (a registry nothing
verifies is just another copy). The test is
``tests/workflow/test_workflow_surface_parity.py``.

**Read-only.** Nothing here runs a job, writes a record, or takes a lock.
Side-effecting workflow verbs live in ``_workflow_control``; answering a gate
lives in ``_workflow_answer``. Keeping the read half separate is what lets
``func builtin workflow list`` stay a store read with no app boot.

**``state`` is derived, never stored.** Adding a stored field would mean a
format bump for something recomputable from what is already there — the exact
inversion ``scope_format`` exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize.app._workflow_resume import pending_gates

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "WORKFLOW_STATES",
    "describe_scope",
    "derived_state",
    "list_scopes",
    "tool_summaries",
    "walk_is_live",
    "watch_scope",
]

#: Scope statuses that can still accept input or make progress.
LIVE_STATUSES = frozenset({"running", "blocked"})

#: Derived states a `purge` may remove. Everything else is somebody's live run.
TERMINAL_STATES = frozenset({"completed", "stalled", "failed", "cancelled"})

#: Every derived state, in the order a reader meets them: waiting for someone,
#: waiting for nobody, moving, then the four ways of being over.
#:
#: One tuple, because a surface that spelled its own `--state` choices would be
#: a second copy of a vocabulary that must match `derived_state` exactly, and it
#: would go stale the first time a state is added
#: (`contributor/reference/pitfalls.md` §6).
WORKFLOW_STATES: tuple[str, ...] = (
    "waiting",
    "ready",
    "running",
    "completed",
    "stalled",
    "failed",
    "cancelled",
)

#: Discovery records parameter types as strings; JSON Schema wants its own.
_JSON_TYPES = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "str": "string",
}


def _lease_has_lapsed(scope: dict[str, Any]) -> bool:
    """Has this scope's runner stopped renewing?

    `True` only when a lease exists and has expired. A scope with **no** lease
    is not abandoned: it was written by a runner that predates leases, or by a
    plain job that never claimed, and calling those dead would make `abandoned`
    the answer for most of the file.

    The judgement is deliberately conservative in the same direction as
    `_run_view._derive_state`: over-reporting a live runner as abandoned is a
    misleading row a human re-checks, while under-reporting is a dead scope
    nobody ever notices. Here the conservative choice runs the other way —
    absence of evidence is not evidence — because an absent lease is the
    ordinary case rather than the suspicious one.
    """
    from datetime import UTC, datetime

    from functualize._primitives.lease import is_expired, read_lease

    lease = read_lease(scope)
    if lease is None:
        return False
    return is_expired(lease, datetime.now(UTC))


def walk_is_live(scope: dict[str, Any] | None) -> bool:
    """Is a runner holding this scope **right now**?

    The live-versus-parked fact `derived_state`'s own docstring says it cannot
    supply: *"a resumed walk reports `blocked` for its whole duration…
    live-versus-parked needs a lease."* Spec AC-12 is that sentence answered.

    Stricter than `not _lease_has_lapsed`, and the difference is the point. That
    helper treats an **absent** lease as "not abandoned", which is right for it:
    a scope written by a plain job that never claimed must not be called dead.
    Here the question is the other one — *is someone walking this?* — and the
    answer for a scope nobody holds is no, whether the lease expired or was
    never taken. A watcher that waited on an absent lease would wait for ever.
    """
    from datetime import UTC, datetime

    from functualize._primitives.lease import is_expired, read_lease

    if not scope:
        return False
    lease = read_lease(scope)
    return lease is not None and not is_expired(lease, datetime.now(UTC))


def watch_scope(
    store: Any,
    scope_id: str,
    *,
    after: int = 0,
    poll_seconds: float = 0.25,
    timeout: float | None = None,
    sleep: Any = None,
    clock: Any = None,
) -> Iterator[dict[str, Any]]:
    """Yield a scope's walk events as the walk emits them, then stop.

    **What a watcher renders comes from here and nowhere else** (spec AC-11).
    Every record yielded is one the walker emitted; nothing in this function
    compares two readings of the scope and infers a transition between them.
    That distinction is the whole of R-e, and it is what the sabotage tests:
    with the walker's emit calls removed this yields nothing at all, rather than
    quietly falling back to describing the record.

    It does *ask* the store for "everything after `seq`", repeatedly, and that
    is a poll — there is no blocking read over a document substrate, and there
    must not be one over a substrate that is a table or an object store. The
    property that matters survives it: the transport asks by sequence number,
    so it never has to work out what is new, and the renderer is fed events
    rather than differences.

    Stops, in this order:

    - the log is drained **and** nobody holds the lease — `walk_is_live` is
      false, so nothing more will arrive and waiting is waiting for ever;
    - the scope has gone (purged under the watcher);
    - ``timeout`` seconds have passed since the last event.

    Args:
        after: The last sequence number the caller has already seen. Resuming a
            watch is passing this back, which is what `seq` is for.
        poll_seconds: How long to wait before asking again, when the log is
            drained and the walk is still live.
        timeout: Give up after this long without a new event. None waits as
            long as the lease is held.
        sleep: Injected for tests, which must not spend real seconds proving
            that a loop terminates. Defaults to `time.sleep`.
        clock: Monotonic seconds, injected for the same reason.
    """
    import time

    sleep = sleep or time.sleep
    clock = clock or time.monotonic

    seen = after
    quiet_since = clock()
    while True:
        events = store.events_for(scope_id, after=seen)
        if events:
            for event in events:
                seen = max(seen, int(event.get("seq", seen)))
                yield event
            quiet_since = clock()
            continue
        scope = store.get_scope(scope_id)
        if not walk_is_live(scope):
            return
        if timeout is not None and clock() - quiet_since >= timeout:
            return
        sleep(poll_seconds)


def derived_state(scope: dict[str, Any]) -> str:
    """The scope's *state*, derived from what the store already knows.

    ``status`` records what the walk last did. It cannot distinguish a run
    waiting for a human from one that has been answered and merely needs
    somebody to advance it — both read ``blocked`` — so an answered scope looked
    stuck, and there was no name for the difference.

    ``ready`` is exactly the set ``resume`` can advance without input, and
    exactly what a scheduler polls for. That is why the derivation pays for
    itself immediately rather than being cosmetic.

    Ordering is load-bearing: ``completed`` with a failed epilogue must reach
    ``stalled`` before the plain ``completed`` branch, or the sticky-body case
    is invisible on every surface.

    Not derived here: whether a *resumed* walk is running right now.
    ``FrontierWalk.start`` sets ``RUNNING`` only on first entry, so a resumed
    walk reports ``blocked`` for its whole duration. This function reports what
    the store knows rather than guessing; live-versus-parked needs a lease.
    """
    status = scope.get("status")
    if status == "cancelled":
        return "cancelled"
    if status == "failed":
        return "failed"
    if status == "completed":
        epilogue = scope.get("epilogue") or {}
        return "stalled" if epilogue.get("status") == "failed" else "completed"
    if status == "running":
        # **Before the plain `running` branch, and that ordering is the whole
        # point** (`durable-run-layer`/T8, schema §6). A scope whose runner died
        # keeps `status: "running"` for ever, because nothing reaps it — and a
        # reader cannot tell that from a run that is genuinely in progress. The
        # lease is what distinguishes them: a live runner renews, a dead one
        # stops. Testing `running` first would report every dead scope as live,
        # which is the bug this exists to name.
        #
        # Derived, never stored (decision K4): no new field, no version bump,
        # and no schedule. Nothing reclaims automatically — `reclaim` is a verb
        # a person runs.
        if _lease_has_lapsed(scope):
            return "abandoned"
        return "running"
    if status == "blocked":
        return "waiting" if any(pending_gates(scope)) else "ready"
    return str(status or "unknown")


def describe_scope(app: Any, store: Any, scope_id: str) -> dict[str, Any] | None:
    """Full state for one scope — topology from the cache, progress from the store.

    Returns None when no such scope exists, so a caller renders its own
    not-found message with its own exit code.
    """
    scope = store.get_scope(scope_id)
    if scope is None:
        return None
    return _describe(app, store, scope_id, scope)


def list_scopes(
    app: Any,
    store: Any,
    *,
    workflow_name: str | None = None,
    state: str | None = None,
    blocked_on: str | None = None,
) -> list[dict[str, Any]]:
    """Scopes matching the filters, in store order.

    **Rows are the full projection — there is no reduced survey shape.** An
    earlier cut of this had one, and it collided immediately: ``pending_gates``
    meant *a list of names* in the survey and *a list of gate summaries* in the
    detail, so the two surfaces could not return "the same rows" no matter how
    carefully each was written. One key, two shapes, is the drift this module
    exists to end — cheaper to have no second shape than to keep two in step.

    A caller wanting a one-line summary renders one; it does not get a
    different projection to render it from.

    Args:
        workflow_name: Only scopes of this workflow.
        state: Only scopes whose **derived** state matches. Filtering on the
            derived value rather than the stored one is the point — "which runs
            are ``ready``" is the question a scheduler actually asks, and it is
            not answerable from ``status``.
        blocked_on: Only scopes with this gate pending.

    With no filters this returns **live scopes only** — running or blocked —
    matching what both surfaces already did. Naming any filter widens the search
    to every scope, because asking for ``state="completed"`` and receiving
    nothing would be a silently empty answer to a well-formed question.
    """
    explicit = state is not None
    rows: list[dict[str, Any]] = []
    for sid, scope in _scopes(store):
        # A scope record with no workflow is not a workflow.
        #
        # Every run gets a scope, because that is where `rc.state` lives, and
        # the record is written lazily the first time something stores a value.
        # So a plain `func myjob` that calls `rc.state.set(...)` leaves a
        # record — correctly, that is its state — but it never walked a graph,
        # has no steps, and nothing will ever mark it finished. Listing it here
        # showed a phantom "running workflow" that could not be resumed and
        # could not be purged, because `workflow purge` refuses running scopes.
        #
        # `workflow` is set by the walk and by nothing else, so its absence is
        # the honest discriminator. Filtered here rather than at write time:
        # the record has to exist, it just is not a workflow.
        if scope.get("workflow") is None:
            continue
        if not explicit and scope.get("status") not in LIVE_STATUSES:
            continue
        if workflow_name is not None and scope.get("workflow") != workflow_name:
            continue
        if state is not None and derived_state(scope) != state:
            continue
        if blocked_on is not None and not any(
            name == blocked_on for name, _ in pending_gates(scope)
        ):
            continue
        rows.append(_describe(app, store, sid, scope))
    return rows


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _scopes(store: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every known scope, as ``(scope_id, record)``."""
    for scope_id in store.scope_ids():
        scope = store.get_scope(scope_id)
        if scope is not None:
            yield scope_id, scope


def _describe(
    app: Any, store: Any, scope_id: str, scope: dict[str, Any]
) -> dict[str, Any]:
    """The full projection. See the module docstring for why there is one."""
    topology = _topology(app, scope.get("workflow"))
    steps = scope.get("steps", {})

    return {
        "workflow_id": scope_id,
        "workflow": scope.get("workflow"),
        "status": scope.get("status"),
        "state": derived_state(scope),
        "steps": topology["steps"],
        "edges": topology["edges"],
        "current_position": scope.get("position"),
        # Nodes, not steps: an answered gate is recorded here too, and calling
        # that a "completed step" would contradict `steps`, where gates are a
        # distinct kind.
        #
        # Full records, not just names. The store has held each step's return
        # value and resolved inputs all along; publishing only the names meant a
        # caller could see *that* a step ran and never what it produced — so it
        # had to be told the run's own results out of band, which is the
        # workflow asking its caller to be its plumbing.
        "results": {
            _job_of(key): {
                "status": record.get("status"),
                "return_value": record.get("return_value"),
                "inputs": record.get("inputs", {}),
                "completed_at": record.get("completed_at"),
            }
            for key, record in steps.items()
            if isinstance(record, dict)
        },
        "branches": dict(scope.get("branches", {})),
        # The epilogue is what separates `completed` from `stalled`, so a
        # projection that omitted it could not explain its own `state` field.
        "epilogue": scope.get("epilogue"),
        "pending_gates": [
            _gate_summary(app, scope_id, scope, name, record)
            for name, record in pending_gates(scope)
        ],
    }


def _topology(app: Any, workflow_name: Any) -> dict[str, Any]:
    """The declared graph — cached shape first, live declaration as fallback.

    The cached ``descriptor.workflow`` is written only by directory discovery,
    so a workflow declared inside a **plugin** (or via ``register_dynamic_job``)
    has ``.workflow is None`` and used to report an empty graph — a caller could
    advance a workflow it could not see. When the cached shape is absent, fall
    back to the live declaration on ``descriptor.function``; it is
    origin-agnostic and already in hand.

    Still empty when the job is gone entirely — a scope outlives the declaration
    that made it, and a stale scope should report its progress rather than
    raise. The fallback also returns empty (never raises) for a job that has no
    workflow at all.
    """
    empty: dict[str, Any] = {"steps": [], "edges": []}
    if not isinstance(workflow_name, str):
        return empty
    descriptor = app.get_job(workflow_name)
    if descriptor is None:
        return empty
    shape = getattr(descriptor, "workflow", None)
    if shape is None:
        shape = _live_workflow_shape(descriptor)
    return shape.to_dict() if shape is not None else empty


def _live_workflow_shape(descriptor: Any) -> Any:
    """Project the workflow graph from the descriptor's live function.

    Covers the provider-built case the discovery cache cannot: reads
    ``function.__functualize_workflow__`` through the same projection discovery
    uses, ``workflow_shape_of``, rather than the cached field.
    """
    from functualize._types.workflow import workflow_shape_of

    func = getattr(descriptor, "function", None)
    if func is None:
        return None
    try:
        return workflow_shape_of(func)
    except Exception:  # pragma: no cover - defensive; the projection is pure
        return None


def _gate_summary(
    app: Any,
    scope_id: str,
    scope: dict[str, Any],
    name: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """What a caller needs to answer one gate."""
    schema = record.get("input_schema") or {}
    draft = record.get("draft") or None
    return {
        "gate": name,
        "model": record.get("model"),
        "input_schema": schema,
        "unresolved_fields": list(schema.get("required", [])),
        # A partially-answered gate is still pending, and a caller that cannot
        # see the accumulated draft would overwrite a second actor's work
        # without ever knowing it existed.
        "draft": (draft or {}).get("values") if draft else None,
        "tools": tool_summaries(app, record),
        "blocked_at": record.get("blocked_at"),
        "workflow_context": {
            "workflow_id": scope_id,
            "workflow": scope.get("workflow"),
            "position": scope.get("position"),
        },
    }


def tool_summaries(app: Any, record: dict[str, Any]) -> list[dict[str, Any]]:
    """What a caller needs to *call* each gate-offered tool, not just name it.

    Publishing the name alone costs a schema lookup per tool. Publishing the
    schema **minus the gate's bound parameters** is also what makes narrowing
    real: a pinned argument is not in the caller's vocabulary, so the forbidden
    call cannot be *expressed* rather than merely being refused.

    Schemas come from the discovery cache, so this stays import-free.
    """
    summaries: list[dict[str, Any]] = []
    for entry in tool_entries(record):
        name = entry["tool"]
        bound = entry["bound"]
        descriptor = app.get_job(name)
        summary: dict[str, Any] = {
            "tool": name,
            "description": (getattr(descriptor, "docstring", None) or "").strip(),
            "bound": bound,
        }
        schema = _job_input_schema(descriptor)
        if schema is not None:
            summary["input_schema"] = _without(schema, bound)
        if descriptor is None:
            # Listed but not discoverable: say so rather than publishing a tool
            # the caller will only fail to call.
            summary["unavailable"] = f"No registered job named '{name}'."
        summaries.append(summary)
    return summaries


def tool_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a gate record's persisted ``tools`` to entry dicts.

    Tolerates the pre-``Tool`` shape (a bare list of names) so a scope blocked
    by an older run still reports and enforces sensibly rather than crashing or
    silently granting everything.
    """
    entries: list[dict[str, Any]] = []
    for raw in record.get("tools") or []:
        if isinstance(raw, str):
            entries.append({"tool": raw, "bound": []})
        elif isinstance(raw, dict) and isinstance(raw.get("tool"), str):
            bound = raw.get("bound") or []
            entries.append(
                {"tool": raw["tool"], "bound": [b for b in bound if isinstance(b, str)]}
            )
    return entries


def _job_input_schema(descriptor: Any) -> dict[str, Any] | None:
    """A JSON-schema view of a job's arguments, from the discovery cache.

    Reads ``config_fields`` and ``parameters`` both: discovery files a job's
    arguments under whichever fits how they were declared (a Pydantic config
    class versus plain annotated parameters), and a schema that silently
    published nothing for one of those shapes would be worse than no schema —
    the caller would believe the tool takes no arguments.
    """
    if descriptor is None:
        return None
    properties: dict[str, Any] = {}
    required: list[str] = []
    fields = list(getattr(descriptor, "config_fields", None) or [])
    fields += list(getattr(descriptor, "parameters", None) or [])
    for param in fields:
        name = getattr(param, "name", None)
        if not isinstance(name, str) or name in properties:
            continue
        entry: dict[str, Any] = {
            "type": _JSON_TYPES.get(
                str(getattr(param, "type_annotation", "")), "string"
            )
        }
        description = getattr(param, "description", "") or ""
        if description:
            entry["description"] = description
        default = getattr(param, "default", None)
        if default is not None:
            entry["default"] = default
        choices = getattr(param, "choices", None)
        if choices:
            entry["enum"] = list(choices)
        properties[name] = entry
        if getattr(param, "required", False):
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _without(schema: dict[str, Any], bound: list[str]) -> dict[str, Any]:
    """The schema with ``bound`` parameters removed, root and required."""
    if not bound:
        return schema
    hidden = set(bound)
    properties = {
        key: value
        for key, value in (schema.get("properties") or {}).items()
        if key not in hidden
    }
    required = [key for key in (schema.get("required") or []) if key not in hidden]
    return {**schema, "properties": properties, "required": required}


def _job_of(step_key: str) -> str:
    """Job name out of a ``<job_name>::<args_hash>`` step key."""
    return step_key.split("::", 1)[0]
