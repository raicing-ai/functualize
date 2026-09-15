# ADR-022: Storage Is a Substrate, Not a Backend-Agnostic Key-Value Domain

**Status**: accepted
**Date**: 2026-09-12
**Deciders**: maintainer, during `store-substrate`

## Context

The project shipped a `functualize-state` domain: `StateBackend` and
`ExecutionStore`, two protocols a plugin could implement to put a job's state
and its execution history somewhere durable. `functualize-state-sqlite`
implemented both. `WorkflowScope.replace_state_store` let a plugin swap a
key-value store into one scope at `ON_SCOPE_CREATED`.

It is a reasonable-looking design and it is re-proposed easily, so this records
why it is retired rather than deferred.

### It could not express the questions callers actually had

`functualize-mcp`'s `get_job_history` wanted recent executions. The protocol
had no such method, so the tool probed for four:

```python
if hasattr(store, "get_all_executions"):
    executions = store.get_all_executions(limit=limit)
elif hasattr(store, "get_session_executions"):
    if hasattr(store, "get_recent_executions"):
        executions = store.get_recent_executions(limit=limit)
    else:
        try:
            executions = store.get_session_executions("", limit=limit)
        except Exception:
            session_id = getattr(self._app, "session_id", None) or ""
            ...
```

That is not a caller being careless. It is what a backend-agnostic protocol
costs at the point of use: the contract can only promise the **intersection**
of every possible backend, so anything sharper has to be discovered by feeling
around for it at runtime. Which of those four branches a given install took was
not knowable — the tests used a fake that implemented all four.

And the intersection is worth least exactly where having a database is worth
most. A KV protocol over Postgres offers `get`, `set`, `delete`, `keys`.

### It was a second seam, below the real one

The scope-store swap sat one level under the framework's own storage. A plugin
could give a scope SQLite for its **job state** while the **records describing
that scope** — which steps ran, where the walk stopped, what a human approved —
stayed on the filesystem. A resumed run then found its steps and not its
variables.

Nothing prevented that arrangement; it was what the seam was *for*. Two seams
at two levels is how the split brain became reachable.

### It duplicated records the framework already kept

`ExecutionStore` held execution records and phase records.
`durable-run-layer` gave the framework a run log with run records and events,
which the CLI renders. The two were separate answers to "what ran", written by
different code, and only one of them was wired into the engine's own lifecycle.

## Decision

**Storage is a substrate: where documents live, chosen once per app.** The port
is `StoreSubstrate` (`_types/protocols.py`) — `read`, `write` with
compare-and-swap, `lock` over several keys, plus `clear`, `delete` and
`describe` for the operator commands. Stores keep their typed methods and their
own rules about meaning.

- `functualize-state` is **removed**.
- `StateStoreProtocol` and `WorkflowScope.replace_state_store` are **removed**.
- `functualize-state-sqlite` implements `StoreSubstrate`.
- A plugin installs one via `EngineHost.substrate`, at `APP_READY`. Every store
  the engine builds follows, so the choice moves all of them or none.

### Why this is not the same idea renamed

A KV protocol asks every backend to expose the same *queries*. A substrate asks
every backend to store and return *documents*, and the queries stay in the
stores, where they are written once against a mapping rather than once per
backend. Nothing about a scope record's shape reaches the backend, so nothing
about the backend has to be discovered by `hasattr`.

The port is also where the properties a database actually brings become
sayable. `lock` takes several keys, so a substrate may satisfy it with **one**
lock — which removes, by construction, a lock-order inversion an external
review found between the scope lock and the state lock and which no store could
fix, because the caller chooses which batch to open first. `write` takes
`expect`, so a backend with no `flock` has compare-and-swap instead of nothing.

## Consequences

- **A gate blocked on one machine can be resumed on another.** That was the
  point, and a KV store for one scope's state could not deliver it: the scope
  record stayed on the first machine's disk.
- **`func builtin data` works on any backend.** `clear`, `delete` and
  `describe` are in the port precisely so the operator commands are not
  stranded on the filesystem.
- **The MCP history tools read the run log**, and register unconditionally.
  They used to appear only when `functualize-state` was importable, so on an
  ordinary install they were absent and the absence looked like a missing
  feature.
- **`functualize-tasks-local` keeps one document** instead of holding a
  `StateBackend`. Tasks now follow the project's substrate, so a task written
  under SQLite is not invisible to a reader on the filesystem.
- **A plugin can no longer give one scope different storage.** That is the
  intended loss.

## What would reopen this

A backend whose value is in *queries the framework cannot express* — full-text
search over gate payloads, say, or a retention policy enforced by the database.
A substrate cannot offer that, because the stores do the querying.

The answer then is still not a KV protocol. It is a port for that capability,
named for the question it answers, with the substrate underneath — which is the
shape ADR-021 argues for on a different axis: one lookup, two doors, not two
systems that must be kept in agreement.
