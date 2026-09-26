# Runtime schema — Contracts

## What changes at a boundary

All additions are **internal** (`_types`, `_primitives`). No public `__all__` changes.

```python
# _types/lifecycle.py — data only
class ScopeStatus(StrEnum): RUNNING, BLOCKED, COMPLETED, FAILED, CANCELLED
class AttemptStatus(StrEnum): RUNNING, SUCCEEDED, FAILED, SKIPPED, CANCELLED
class InputRequestStatus(StrEnum): OPEN, ACCEPTED, CONSUMED, CANCELLED, EXPIRED

@dataclass(frozen=True)
class Machine:
    name: str                                   # "scope" | "run" | "attempt" | "input_request"
    states: frozenset[str]
    transitions: frozenset[tuple[str | None, str]]   # None = absent (creation)
    absorbing: frozenset[str]                   # nothing leaves: SCOPE {cancelled}; RUN = RunStatus.terminal
    evictable: frozenset[str]                   # a cap may drop: SCOPE {completed, failed, cancelled}

SCOPE: Final[Machine]; RUN: Final[Machine]; ATTEMPT: Final[Machine]; INPUT_REQUEST: Final[Machine]

# _types/errors.py
class IllegalTransition(Exception):  # noqa: N818 — names a refused move, like TerminalUnavailable
    machine: str; current: str | None; target: str
    # message names all three: "scope: 'cancelled' -> 'running' is not a legal transition"

# _types/retention.py
@dataclass(frozen=True)
class RetentionPolicy:
    max_records: int = 500
    evictable_only: bool = True
    max_age: timedelta | None = None
DEFAULT_RETENTION: Final[RetentionPolicy]

# _primitives/transitions.py
def require_transition(machine: Machine, current: str | None, target: str) -> str:
    """Return ``target`` if (current, target) is in the table; else raise IllegalTransition.
    An unknown ``target`` (not in ``machine.states``) is also illegal."""
```

The migration surface (`Migration`, `MigrationTarget`, `MigrationRefused`, `migrate`) moved to
`sqlite-runtime-provider` with the runner (D3 = B); its contract is `schema.md` §4.

```python
# _engine/frontier.py — FrontierWalk.start, resumed branch (task T3, D2 = 1)
if position is not None:
    self._store.set_scope_status(self._scope_id, WalkState.RUNNING)   # new: every entry says running
    return [position]
```

## Behaviour that changes for existing callers

| Caller | Before | After |
|---|---|---|
| `ScopeStore.set_scope_status(sid, s)` | writes any `str` | writes `s` if legal from the stored status; else raises `IllegalTransition`, envelope unchanged |
| `RunStore.close_run(rid, s)` | overwrites any status | refuses when the stored status is terminal (`RunStatus.terminal`) |
| `FrontierWalk.start` on a resumed scope | status left as `blocked` / `failed` for the whole walk | status is `running` from entry; `list_scopes` shows `running` (or `abandoned` once the lease lapses) instead of `waiting`/`ready`; `advanceable_scopes` now also lists a scope resumed from `failed`/`completed` while it walks (it reads `running`, which `LIVE_STATUSES` holds); a resumed-from-`blocked` scope was listed before and still is; the silent-step detector (`frontier.py:245`) now covers resumed walks |
| tests that write an illegal move directly | pass | fail by design; each one is listed and rewritten in task T6 |

`IllegalTransition` propagates. `executor._close_scope` wraps its status write in a broad
`except Exception` (`executor.py:1068`) and keeps swallowing it at debug level, as it does any store
error today — a disclosed limit, not a new one. Task T6 checks the run-record closers
(`executor.py:1082-1110`) for the same wrapper and records what it finds.

## Public API surface

`tests/test_public_api_surface.py` must pass unchanged. `IllegalTransition` is not exported from
`functualize.plugin` in this wave: no plugin writes a status.

## Import-linter contracts

`uv run lint-imports` must stay **7 kept, 0 broken**. `_types/lifecycle.py` and
`_types/retention.py` import stdlib and `_types.enums` only; an import-line test reads them, per
ADR-026 (`exclude_type_checking_imports` hides deferred imports).

## Backward compatibility

Persisted formats are unchanged (`SCOPES_VERSION`, run-log version). A stored status outside the
state set is not rewritten; it refuses on its next write. Falsify with:
`rg -n 'format_version|SCOPES_VERSION|RUNS_VERSION' src/functualize/_primitives/{scope,run}_format.py`
before and after — no diff.
