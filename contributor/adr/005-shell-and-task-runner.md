# ADR-005: Shell Integration & Task Runner — `@job`, `Shell`, Dependencies, State, Workflows

**Status**: accepted
**Date**: 2026-07-24
**Deciders**: Core team

## Context

Functualize had convention-only discovery (every public function is a job), no shell capability,
no dependency system, no up-to-date checking, and a declaration-only `@workflow` with no walker.
Jobs were identified by function name alone; there was no way to declare dependencies, guard
execution, cache results, or run shell commands with proper lifecycle management.

The design covered a comprehensive task-runner kernel: `@job` decorator with grouped
value objects, `Shell` capability at PyInvoke parity,
runtime state store, guard pipeline, dependency execution, workflow walker, `FromJob`/`FromStep`
return-value reuse, pipeline mode, and graph unification.

## Decision

The work was split across stages S0–S9. Stages S0–S5, SG (graph unification), S8, and S9 are fully
shipped. S6 is ~90% done. S7 (watch/matrix/dry-run) was split out and is not started.

### Stages Shipped (S0–S5, SG, S8, S9)

1. **`@job` decorator with grouped value objects** — `Deps`, `Fingerprint`, `Guards`, `Exec`, `Retry`
   are identity-preserving, cache-serializable typed objects. `@job` subsumes `@job_metadata`.
   The `__functualize_job__` dunder integrates with discovery. Strict mode (`[discovery]
   require_job_decorators = ["job"]`) enforces opt-in.

2. **`Shell` capability** — list/template/raw forms, tee, pty, watchers/responders, `cd()`/`prefix()`,
   sudo, defer (LIFO, signal-aware), secret masking via shared `Secret[str]` + `_types/redaction.py`.
   `FakeShell` for testing with pattern→result table and loud-on-unexpected semantics.
   Protocol in `_types/shell.py`, impl in `_engine/capabilities/shell.py`, public in `functualize.job`.

3. **Runtime state store** (`_primitives/state_format.py`) — separate from the discovery cache.
   Fingerprints with config-hash keys (`<job>::<args_hash>::<method>`), per-scope records,
   history ring buffer (bound 200). Atomic write + advisory lock.

4. **Guard pipeline** — precedence order: platforms → preconditions → status → fingerprint.
   Three outcome states + `BLOCKED(awaiting=Model)`. Session precondition cache.
   Truthy guard ANDs with staleness (R10a).

5. **Dependency execution** — topological scheduling via `graphlib.TopologicalSorter`.
   Sequential default, `--parallel` bounded pool, `Deps.policy` (fail-fast vs keep-going), `--from`.
   `DepScheduler` runs through the engine.

6. **Workflow walker** — `Step(job)` + `Gate(name, awaits, tools)` + `Edge`/`ConditionalEdge` + `END`.
   Epilogue body on `END` with `FromStep` injection. Block→resume via state store.
   Workflows chain and nest as ordinary jobs. `FrontierWalk` per-step execution through the engine.

7. **`FromJob[T]` / `FromStep[T]`** — return-value reuse across the dependency graph.
   Disqualification warnings. Pydantic classifier.

8. **Pipeline mode** — `Stdout` capability (`out.emit`/`out.write`), `--output` flag, NDJSON streaming,
   SIGPIPE handling, exit-code table.

9. **Builtins** — `func builtin parallel`, `func builtin history`, `func builtin env`,
   `func builtin shell-init`, `func builtin why`, `func builtin state clear`.

10. **Graph unification** — one `JobGraph` on `graphlib.TopologicalSorter`.
    Name resolution delegated to `_discovery/naming.py`.

### Stages Not Yet Shipped

| Stage | Description | Status |
|-------|-------------|--------|
| S6 | Shell output channel + `stream=True` default sink + `silent` | ~90% done (T-S6b-3 remains) |
| S6b | Shell output channel gate (TUI audit + observe-tui) | Blocked on T-S6b-3 |
| S7 | Watch/matrix/dry-run | Split out; not started |

## Consequences

### Positive

- Jobs gain build-tool semantics: declare dependencies, guard execution, cache results
- Shell commands are first-class citizens with DI/config/perf/events
- State store enables incremental builds (fingerprints, up-to-date checks)
- Workflows execute end-to-end with gate-based AI integration
- `DepScheduler` + guards + fingerprints are **wired** (verified: production call paths exist —
  `executor.py` constructs `DepScheduler`; `func builtin why` prints dependency trees)
- Pipeline mode enables Unix-style composition (`func job | jq ...`)

### Negative

- State store is a new concern with its own invariants (separate from discovery cache;
  `func builtin state clear` does NOT touch discovery cache; `func cache clear` does NOT touch state)
- `@job` decorator adds a new concept users must learn (opt-in in non-strict mode)
- `FromJob`/`FromStep` type-checking adds complexity to the DI system

### Neutral

- Graphlib replaced a hand-rolled walker that needed a deferral-counter heuristic for diamond joins
- `networkx` was never imported (499ms import vs graphlib's 0.23ms)
- The convention-only path (no `@job` decorator) still works in non-strict mode

## Status

Partially shipped. Stages S0–S5, SG, S8, and S9 are done. S6 (shell output channel)
is ~90% complete — the remaining piece is the output-channel gate. S7
(watch/matrix/dry-run) was split out and is not started.
