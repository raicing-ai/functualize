# Contracts — durable-run-layer

External interfaces only. Internal shapes are in `schema.md`.

---

## 1. `functualize.app.utils` / `functualize.app` — reading runs

```python
def describe_run(app, store, run_id: str) -> dict | None: ...
def list_runs(app, store, *, job=None, surface=None, state=None,
              since=None, limit=100) -> list[dict]: ...
def run_events(app, store, run_id: str, *, after=None, limit=500) -> list[dict]: ...
```

One projection, thin callers — the shape 0.3.0 established for scopes
(`app/_workflow_view.py`) and the reason that lift was worth doing.

`surface=` is the filter that only exists because `RunRequest` carries provenance
(spec AC-2).

## 2. `functualize.app.utils` — the lease

```python
@dataclass(frozen=True)
class Lease:
    scope_id: str
    owner: str          # runner identity
    generation: int     # the fencing token — monotonic per scope
    expires_at: str     # ISO-8601 UTC

def claim(store, scope_id: str, *, owner: str, ttl_s: float) -> Lease: ...
def renew(store, lease: Lease, *, ttl_s: float) -> Lease: ...
def release(store, lease: Lease) -> None: ...
```

Raises `LeaseHeldError(scope_id, holder, expires_at)` when another live lease exists, and
`StaleGenerationError(scope_id, expected, actual)` when a write presents a stale token.

> **Every scope write carries a generation, and a stale one is refused.** The expiry is only
> how a dead runner's claim eventually clears; the generation is the mechanism. A lease without
> a fencing token is a suggestion.

## 3. `functualize.workflow` — one declaration

```python
@dataclass(frozen=True)
class Step:
    ...
    effecting: bool = False     # NEW
```

`effecting=True` means: **this step's completion is committed with its record, so a crash
cannot replay it.** The default is today's behaviour — a step with no record re-runs on resume
— now *declared* rather than assumed.

Named `effecting` rather than `once` or `idempotent=False` because it says what the step
**does to the world**, which is the property the author knows.

## 4. `functualize.types` — errors

```python
class LeaseHeldError(FunctualizeError): ...
class StaleGenerationError(FunctualizeError): ...
class WorkflowDepthExceededError(FunctualizeError): ...   # C9
class SourceIdentityChangedError(FunctualizeError): ...   # AC-16
```

Each maps to an exit code through F2's outcome module — **this feature adds no exit code and no
second vocabulary.**

> Refusal messages report a **count, never content**. Scope records hold gate payloads, and a
> holder's identity is not a reason to print what they are working on.

## 5. Derived state gains one value

`derived_state` (`app/_workflow_view.py`) gains **`abandoned`**: a scope whose lease expired
with no renewal.

Derived, not stored — no new field in the scope record, no version bump (decision **K4**,
inherited **C2**). It joins `waiting · ready · running · completed · stalled · failed ·
cancelled`.

## 6. CLI and MCP

```
func builtin run list [--job X] [--surface Y] [--state Z]
func builtin run show <run-id> [--events]
func builtin workflow reclaim <scope-id>      # an abandoned scope, explicitly
```

MCP gains `list_runs`, `get_run`, `get_run_events`, `reclaim_workflow` — **verb for verb**, per
decision **A3** and pinned by the parity test **A7** established in 0.3.0.

`reclaim` is explicit. **Nothing reclaims automatically, and nothing deletes** — `purge`
remains the only destructive verb (spec §3.6).

## 7. Unchanged

- `state.json`'s `_SECTIONS`, `STATE_VERSION`, and its discard-on-mismatch.
- `scopes.json`'s `SCOPES_VERSION` and its **refuse**-on-mismatch.
- The history ring: shape, 200 cap, `invoke_depth == 0` gate, no argument values.
- `EventBus`: in-memory, fire-and-forget, name grammar, zero file I/O.
- `atomic_write_json`, `ScopeStore.batch()`, `StateStore.scope_batch()`.
- `sh(..., timeout=N)` — the one timeout that stops work, because the OS enforces it.
