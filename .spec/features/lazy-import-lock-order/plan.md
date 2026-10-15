# Plan

## Alignment

The issue's live `Shape state` remains `not-required`. This is an internal concurrency correction with no new user-facing surface.

## Architecture

BEFORE:

```text
_engine/executor.py (peer) -> _discovery/LazyJobFunction.materialize (peer)
                              -> proxy lock -> _IMPORT_LOCK -> sys.path/importlib
module import code -----------------------> another proxy lock (cycle)
```

AFTER:

```text
_engine/executor.py (peer) -> _discovery/LazyJobFunction.materialize (peer)
                              -> _IMPORT_LOCK -> sys.path/importlib
module import code -----------------------> _IMPORT_LOCK (same-thread reentry)
```

`_app/boot.py` (composition layer) still creates one proxy per descriptor. `_engine` calls the proxy interface and adds no `_discovery` import. The only synchronization needed for first materialization is the same re-entrant mutex that already owns the process-wide import region. It also protects publication of the proxy's callable and config class. Already-materialized calls retain the fast path.

The BEFORE has **Inappropriate Intimacy** between two independently owned mutexes: arbitrary module code can acquire another proxy lock while the import mutex is held, allowing opposite lock order on another thread. The AFTER removes the redundant proxy mutex. It introduces no new shared mutable data or layer dependency. Consulted `python-design-patterns` (one responsibility, KISS) and `design-patterns-refactoring` (remove redundant synchronization rather than add a lock hierarchy).

## Surviving smells

The interpreter's `sys.path` is **Global Data**; it is an existing Python import resource. The mutex stores no domain state and remains the narrow serialization primitive around that resource. First-time materializations of unrelated jobs serialize; this is the accepted throughput cost of protecting the shared import path.

## Scope and verification

Change `src/functualize/_discovery/lazy_wrapper.py`, `tests/execution/test_lazy_materialization.py`, `.spec/STATUS.md`, and `CHANGELOG.md`. Reproduce the old deadlock in a timed child process, run the targeted and selected test tiers, and run Ruff, mypy, and import-linter. Correct the previous PR description's false lock-order claim separately through GitHub.
