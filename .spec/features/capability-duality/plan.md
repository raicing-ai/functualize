# Plan — capability duality

## R-a · The mechanism: `rc._cap(T)`

One private resolver on `RunContext`, consulted by every accessor that has a
capability behind it:

```python
def _cap(self, t: type) -> Any | None:
    """The run's instance of capability `t`, or None."""
    if self._caps is not None and t in self._caps:
        return self._caps[t]
    return None          # never constructs — see R-b
```

`_log_sink` collapses into it; `rc[T]` / `T in rc` consult it before the DI
registry; `rc.state` reads the scope's store through it.

**It never constructs.** That is not an optimisation, it is the correctness
rule: `Sources` and `Freshness` are injected *empty* and completed after the
pre-flight decision, so a resolver that helpfully built one on demand would
hand back an empty map with no error — the defect `sources.py`'s own factory
comment already warns about.

## R-b · Why lazy lookup, not eager capture

A capability factory runs *during* parameter resolution, so for
`def j(inv: Invoke, rc: RunContext)` the RunContext does not exist yet when
`inv` is built. `TTY.ctx` already resolved this by holding `caps` and looking
up at call time; `99dcaf2` applied the same shape to `Invoke` and `Perf`. The
mechanism is that shape, named.

## R-c · `State`

1. `StateStore.keys()` gains `prefix: str = ""` (lifted from the class being
   deleted) — this is what makes the documented `"fetch.count"` convention
   usable.
2. `_engine/capabilities/state.py` is **deleted**. `State` becomes the public
   name of `_engine/capabilities/state_store.StateStore`, so `rc.state` and
   `state: State` name one class.
3. `workflow_orchestrator` passes `parent_scope=runner.scope` alongside the id,
   so a step's `rc.state` resolves to the scope's store.

**Risk.** Step 3 is a behaviour change, not a leak fix: steps that today each
get a private store begin sharing one. That is the intent (AC-1) and the
maintainer decision, but it means `examples/.../pipeline.py` §8 — which exists
to demonstrate the isolation — must be rewritten, not merely updated (AC-8).

## R-d · Blast radius

`rg -l '\bState\b' src/ tests/ plugins/ examples/ -g '*.py'` → **75 files** at
authoring time. Most are annotations that keep working unchanged once `State`
names the surviving class; the ones that break are those constructing `State()`
directly (`testing/builder.py`, `testing/doubles.py`, `tests/test_state_prefix.py`).

## R-e · The tripwire

Parametrized over `CAPABILITY_SPECS`, which already exists and is already the
single registry (ADR-014). A capability added tomorrow is covered the day its
spec is written — the property the prose rule lacked, and the reason a third
prose rule would fail the same way the first two did.
