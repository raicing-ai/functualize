"""The `State` capability — a run's shared, **durable** key-value store.

One object serves both doors: `state: State` as a job parameter and `rc.state`
on the RunContext are the same instance (ADR-021). They were two different
classes with two different lifetimes, behind names that read identically at the
call site, and a write to one was invisible to the other.

**There is no in-memory tier.** There used to be: a dict-backed store that
served when no state plugin was installed. It was a fallback in name only.
`WorkflowScope` held it and `app._scope_registry` held the scopes, and that
registry is reset to `{}` at boot — so a workflow that blocked at a gate and
resumed *in a new process* came back with its step records intact (those live in
``scopes.json``) and its state silently empty. The case you most need a store in
was the one case it could not serve, which is the least defensible split
available.

So state lives in ``scopes.json``, beside ``steps``, ``branches``, ``gates`` and
``epilogue``. That is the right file by the rule it already states: it holds
**records** — not recomputable, refuse rather than discard on a bad read —
whereas ``state.json`` holds derived data it may legitimately throw away. What a
job stored is a record by that test.

Three properties follow from the file rather than from code here: it survives a
resume (same scope id, same record), it is concurrency-safe (``update_scopes``
re-reads inside the lock, so two writers merge instead of clobbering), and two
runs of one workflow share nothing (different scope ids).

**The plugin seam is unchanged.** `StateStoreProtocol` is still the contract and
`WorkflowScope.replace_state_store` still swaps in an implementation —
``functualize-state-sqlite`` among them. What changed is the default it
replaces.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from functualize._engine.capabilities.spec import CapabilitySpec

if TYPE_CHECKING:
    # Annotation-only: every annotation here is a string under
    # `from __future__ import annotations`, and nothing in this module does an
    # isinstance against the protocol.
    from functualize._engine.capabilities.protocols import StateStoreProtocol
    from functualize._primitives.scope_store import ScopeStore

__all__ = ["ScopeBackedStateStore", "State", "StateUnavailableError"]


class StateUnavailableError(RuntimeError):
    """Raised when a `State` has no scope to read or write.

    Deliberately an error rather than a silent no-op or an in-memory
    stand-in. A store that quietly accepts writes nothing will ever read is the
    failure this capability was rebuilt to remove; failing loudly at the first
    call is the only honest alternative.
    """


class ScopeBackedStateStore:
    """The default `StateStoreProtocol` — one scope's slice of ``scopes.json``.

    Satisfies the same protocol `functualize-state-sqlite` implements, so
    `WorkflowScope.replace_state_store` swaps this out unchanged. It is what
    the in-memory store used to be, minus the part where it lost everything on
    resume.

    **Job namespaces are a key convention, not a mechanism.** The run shares one
    flat key space; `set("fetch.rows", …)` is all a namespace is. T12 removed
    the `get_job_state` / `list_job_namespaces` pair that spelled the same
    convention as an API — a framework namespace is a second concept for
    something a string prefix already does (ADR-021 §B).
    """

    #: ``_tmp`` lets a caller that created a throwaway directory for this
    #: store keep it alive exactly as long as the store — `functualize.testing`
    #: does, so a test gets the real implementation rather than a double.
    __slots__ = ("_scopes", "_scope_id", "_tmp", "_closed")

    def __init__(self, scopes: ScopeStore, scope_id: str) -> None:
        self._scopes = scopes
        self._scope_id = scope_id
        self._closed = False

    def _close(self) -> None:
        """Seal the store against further writes.

        `WorkflowScope.close()` calls this. The guarantee is older than the
        durable backing and survives it: once a scope is finished, a late
        write from a straggling thread must fail loudly rather than mutate a
        record something already read as final.
        """
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            from functualize._engine.capabilities.runcontext import (
                InvalidStateTransitionError,
            )

            raise InvalidStateTransitionError(
                f"Workflow scope '{self._scope_id}' is closed; its state "
                "cannot be modified."
            )

    def get(self, key: str, default: Any = None) -> Any:
        return self._scopes.get_state(self._scope_id, key, default)

    def set(self, key: str, value: Any) -> None:
        """Store ``value``, refusing anything that cannot reach the file.

        Validated **here**, in the thing that writes JSON, rather than in
        `State` — one check rather than two that agree today. It runs before
        the write so the traceback names the offending call while it is still
        on the stack, not a later flush.
        """
        self._check_open()
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"state value for {key!r} is not JSON-serializable: {exc}"
            ) from exc
        self._scopes.set_state(self._scope_id, key, value)

    def delete(self, key: str) -> None:
        self._check_open()
        self._scopes.delete_state(self._scope_id, key)

    def keys(self) -> list[str]:
        return list(self._scopes.state_snapshot(self._scope_id).keys())

    def to_dict(self) -> dict[str, Any]:
        return self._scopes.state_snapshot(self._scope_id)

    def clear(self) -> None:
        self._check_open()
        self._scopes.clear_state(self._scope_id)

    def batch(self) -> Any:
        """Hold the file lock across many writes."""
        return self._scopes.batch()


class State:
    """A run's key-value store, shared by every job in the run.

    Reached as `rc.state`, or by declaring `state: State`. Both are the same
    object (ADR-021).

    Keys are flat and the whole run shares one namespace, so two jobs can pick
    the same name. The answer is a naming convention rather than a framework
    namespace — write ``state.set("fetch.rows", n)`` and read the namespace back
    with ``state.keys("fetch.*")``. One concept (a string) instead of two.

    Values must be JSON-serializable; that is checked at write time, where the
    offending call is still on the stack, rather than at the write of the file.

    **Every write is one lock-read-write cycle** against ``scopes.json``. A job
    writing a handful of keys will not notice; one writing hundreds in a loop
    should hold :meth:`batch`.
    """

    __slots__ = ("_backend",)

    def __init__(self, backend: StateStoreProtocol | None) -> None:
        self._backend = backend

    def _bound(self) -> StateStoreProtocol:
        if self._backend is None:
            raise StateUnavailableError(
                "State has no backing store. Every run the engine starts has a "
                "scope, so this object was built outside a run — a RunContext "
                "constructed directly, rather than one the engine created."
            )
        return self._backend

    def get(self, key: str, default: Any = None) -> Any:
        """The value stored under ``key``, or ``default``."""
        return self._bound().get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``.

        Raises:
            TypeError: ``value`` is not JSON-serializable. Raised by the
                backing store, which is the thing that has to write it.
        """
        self._bound().set(key, value)

    def delete(self, key: str) -> None:
        """Remove ``key``. A no-op when it is not there."""
        self._bound().delete(key)

    def keys(self, pattern: str = "") -> list[str]:
        """Stored key names, optionally filtered by a glob ``pattern``.

        ``*`` stops at a ``.`` and ``**`` crosses it::

            state.keys("fetch.*")    # one level under `fetch`
            state.keys("fetch.**")   # every depth under `fetch`
            state.keys("*.rows")     # the same leaf in any namespace
            state.keys()             # everything

        So ``"fetch.*"`` cannot match ``"fetchmeta.x"``: the literal dot has to
        match a real dot. A bare prefix is a ``startswith`` and does reach the
        neighbouring namespace, which is why the pattern form is documented. A
        pattern containing no ``*`` keeps the prefix meaning.

        The matcher is the one the rest of the codebase uses —
        ``rc.events.on_event("job.*")`` and perf-phase filtering call the same
        function. A second glob implementation that agreed with this one today
        is the divergence ADR-021 exists to prevent.

        Raises:
            TypeError: ``pattern`` is not a string.
        """
        if not isinstance(pattern, str):
            raise TypeError(f"pattern must be a str, got {type(pattern).__name__}")
        names = list(self._bound().keys())
        if not pattern:
            return names
        from functualize._events._pattern_matcher import matches_pattern

        return [name for name in names if matches_pattern(name, pattern)]

    def to_dict(self) -> dict[str, Any]:
        """Every key this run holds, as a plain dict."""
        return self._bound().to_dict()

    def clear(self) -> None:
        """Drop every key this run holds."""
        self._bound().clear()

    def batch(self) -> Any:
        """Hold the file lock across many writes, writing once at the end.

        Every :meth:`set` is otherwise its own lock-read-write cycle against
        ``scopes.json``::

            with state.batch():
                for name, n in counts.items():
                    state.set(f"fetch.{name}", n)

        An exception inside the block discards the block's writes rather than
        persisting some of them. A backend that cannot batch yields a plain
        null context, so this is always safe to write.
        """
        backend = self._bound()
        batch = getattr(backend, "batch", None)
        if batch is None:
            from contextlib import nullcontext

            return nullcontext()
        return batch()


CAPABILITY = CapabilitySpec(
    name="State",
    rc_accessor="state",
    type=State,
    # Built from the execution context, lazily: this factory runs *during*
    # parameter resolution, so for `def j(state: State, rc: RunContext)` the
    # RunContext does not exist yet. See ADR-021 for why every capability that
    # needs the run resolves at call time rather than capture time.
    factory=lambda ctx: _make_state(ctx),
)


def _make_state(ctx: Any) -> State:
    """Bind `State` to the run's scope.

    The scope owns the store, so a step, its epilogue, and anything they invoke
    all reach one object — which is what makes state travel across a workflow
    instead of evaporating per job.
    """
    scope = getattr(ctx.context, "parent_scope", None)
    if scope is None:
        return State(None)
    return State(scope.state_store)
