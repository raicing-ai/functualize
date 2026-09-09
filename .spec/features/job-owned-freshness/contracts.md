# Contracts — job-owned-freshness

External interfaces only. Two: one capability a job reads, one field a job declares.

---

## 1. The capability — `Freshness`

New `src/functualize/_engine/capabilities/freshness.py`, exposed to job bodies the way
`Sources` is.

```python
@dataclass(frozen=True)
class FreshnessVerdict:
    state: GuardState            # SKIP_FRESH, SKIP_SATISFIED, RUN, ...
    key: str                     # the args-hash key the decision was computed under
    recorded_value: Any | None   # what the previous run recorded, if anything
    declared_sources: tuple[str, ...]
    declared_generates: tuple[str, ...]
    source_map: Mapping[str, Mapping[str, Any]]   # {path: {mtime, size, sha256}}

    @property
    def is_fresh(self) -> bool: ...   # state is SKIP_FRESH


class Freshness:
    """The verdict this job's own Fingerprint produced, for the job to act on."""

    def verdict(self) -> FreshnessVerdict | None: ...
```

`verdict()` returns `None` when the job declares no `Fingerprint` — there was no decision to
report, and a fabricated one would be a lie.

Injected by declaration, like every other capability:

```python
CAPABILITY = CapabilitySpec(
    name="Freshness",
    type=Freshness,
    # Deliberately empty, exactly as Sources is: DI resolves before the
    # pre-flight, so the verdict does not exist at injection time.
    factory=lambda ctx: Freshness(),
    preflight_bind=...,   # populated once the decision is in hand
)
```

`source_map` is the same map `Sources` exposes. It is repeated here rather than cross-linked
because a job asking *"why am I fresh?"* should not have to inject two capabilities to get one
answer — and it is the identical object, not a copy.

## 2. The declaration — `Fingerprint.decides`

```python
@dataclass(frozen=True)
class Fingerprint:
    sources: Sequence[str] = ()
    generates: Sequence[str] = ()
    method: str = "mtime"
    decides: bool = False        # NEW
```

`decides=True` means: *when this job is fresh, run the body anyway and let it decide.*

Named `decides` rather than `skip=False` or `manual` because it says what the job **does**,
not what the framework stops doing — and because the reader of a declaration should be able to
tell what happens without knowing the default.

### What it does not do

- It does not affect `SKIP_SATISFIED` (a satisfied `status` guard), a failing `Precondition`,
  or a gate. Only `SKIP_FRESH`, exactly the set `force_fresh` overrides today
  (`executor.py:1022-1025`).
- It does not let a job report `RunStatus.SKIPPED`. *"The framework skipped me"* and *"I ran
  and did nothing"* stay distinguishable in history.

## 3. `functualize.job` — public re-exports

```python
from functualize.job import Freshness, FreshnessVerdict
```

Added to `functualize/job/__init__.py`'s `__all__`, alongside `Sources`.

## 4. Unchanged

- `Sources` and ADR-012's binding.
- `Fingerprint`'s `sources`, `generates`, `method`, and ADR-013's path rules.
- `--force` / `force_fresh` behaviour and precedence.
- The `RunStatus` vocabulary and every exit code.
- `PreflightDecision`'s shape — this feature **reads** it; it adds no field.
