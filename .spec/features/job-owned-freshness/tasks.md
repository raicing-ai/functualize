# Tasks — job-owned-freshness

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — an inert capability, proven wired

### [ ] T1 · `Freshness` exists, is injected, and always reports `None`

**Files:** `src/functualize/_engine/capabilities/freshness.py`,
`src/functualize/_primitives/di.py`, `src/functualize/job/__init__.py`,
`tests/execution/test_freshness_capability.py`

`FreshnessVerdict` and `Freshness` per `contracts.md` §1, with a `CapabilitySpec` whose
factory is **deliberately empty** — DI resolves before the pre-flight, so there is nothing to
report at injection time. `verdict()` returns `None` for now.

Register the name in `INJECTED_PARAM_TYPE_NAMES` — ADR-014's import-time invariant makes a
forgotten name a startup crash, which is the whole reason to do it in this wave rather than
later.

**Gate**
```bash
test -f src/functualize/_engine/capabilities/freshness.py && \
  rg -c 'CapabilitySpec\(' src/functualize/_engine/capabilities/freshness.py
```
now: `file absent` · after: `1`

**Gate — the ADR-014 invariant is satisfied**
```bash
rg -c 'Freshness' src/functualize/_primitives/di.py
```
now: `0` · after: `≥1`

**Test:** a job declaring `rc`-injected `Freshness` runs, receives the instance, and gets
`None` from `verdict()`. **The point of this wave is that the wiring is proven before it
carries meaning.**

---

## Wave 1 — the verdict arrives

### [ ] T2 · Bind the verdict after the pre-flight, before the body

**Files:** `src/functualize/_engine/capabilities/freshness.py`,
`src/functualize/_engine/executor.py`,
`tests/execution/test_freshness_capability.py`

`Sources`-shaped: populated by a `preflight_bind` once `PreflightDecision` is in hand. Read
`verdict`, `key`, `recorded_value`, `declared_sources`, `declared_generates` and `source_map`
off the decision — **do not recompute any of them** (spec AC-6).

Spec AC-1, AC-2.

**Gate**
```bash
rg -c 'preflight_bind' src/functualize/_engine/capabilities/freshness.py
```
now: `0` · after: `1`

**Gate — nothing is recomputed**
```bash
rg -c 'compute_args_hash|glob|stat\(' src/functualize/_engine/capabilities/freshness.py
```
now: `n/a` · after: `0`

**Test:** a job with a `Fingerprint` reads a populated verdict on a **cold** run and on a
**warm** run, and the state matches what the engine decided.

**Sabotage — two paths, and this is the acceptance criterion, not a nicety (AC-7):** break the
binding; a test must fail on **both** the cold and the warm path. A single-path sabotage is
what let a capability "resolve and do nothing" ship before
(`contributor/guides/wiring-discipline.md`). **Commit before sabotaging.**

---

## Wave 2 — the one behaviour change

### [ ] T3 · `Fingerprint.decides`, and the engine honours it

**Files:** `src/functualize/_types/job_declaration.py`,
`src/functualize/_engine/executor.py`,
`tests/execution/test_fingerprint_decides.py`

Add `decides: bool = False`. In the engine, extend the existing override block that already
handles `force_fresh` and `force` — **`:1022-1025`, not the return at `:1026`** — so all three
overrides of `SKIP_FRESH` read together in one place.

Spec AC-4, AC-5.

**Gate — the field exists**
```bash
rg -c 'decides' src/functualize/_types/job_declaration.py
```
now: `0` · after: `≥1`

**Gate — the override lives beside its siblings**
```bash
rg -n 'force_fresh and _state is GuardState.SKIP_FRESH' src/functualize/_engine/executor.py
```
now: `1022` · after: still present, with `decides` handled in the same block

**Gate — the early return is untouched**
```bash
rg -n 'not preflight_decision.should_run' src/functualize/_engine/executor.py
```
now: `1026` · after: `1026` *(unchanged — the decision is made above it, not at it)*

**Tests:**
1. **Default unchanged (AC-3).** A job *without* `decides` that is fresh is skipped: same
   result, same exit code, same history entry as today. **Write this test before the engine
   change**, so it is a regression gate rather than a description (risk R-b).
2. **Opted in (AC-4).** A job with `decides=True` that is fresh has its **body entered**, and
   reads `verdict().is_fresh is True`.
3. **Scope of the override (AC-5).** `decides=True` does **not** bypass a failing
   `Precondition` (still exit 3) or a blocking gate (still exit 5).
4. **Honest history (§3.3).** An opted-in job that runs is recorded as having run, not as
   `SKIPPED`.

**Sabotage:** make `decides` always `True`; test 1 must fail.

---

## Wave 3 — say what it is for

### [ ] T4 · The worked example, and the guide

**Files:** `examples/quickstart/…/self_caching_job.py`, `docs/guides/`,
`contributor/architecture/run-model/11-boundaries.md` (cross-reference)

Spec AC-8. The example is a job that caches its own artifact **into a path it chose, which the
framework never reads** — that is the boundary this whole feature exists to make usable
(`11-boundaries.md` **N1**), and an example that used a framework-provided store would
undercut it.

The guide must also say what `Freshness` is **not**: it is not a cache, and reading a fresh
verdict does not oblige a job to skip.

**Gate**
```bash
uv run pytest examples/ -q -k self_caching
```
now: `no tests ran` · after: passing

**Gate — the vocabulary agrees with `why` (risk R-c)**
```bash
rg -c 'GuardState' src/functualize/_engine/capabilities/freshness.py src/functualize/_engine/explain.py
```
now: `freshness.py: n/a`, `explain.py:≥1` · after: both `≥1`

**Test:** `func builtin why <job>` and the job's own `verdict().state` describe the same run
identically.

---

## Wave 4 — checkpoint

### [ ] T5 · Feature gate

- `uv run ruff check src/ tests/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — 6 contracts kept
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- AC-1…AC-8 each named to a test
- orphan scan over `Freshness`, `FreshnessVerdict`, `decides`
- the two sabotages (T2's two-path binding, T3's forced `decides`), **committing before each**

---

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3"]},
    {"id": 3, "tasks": ["T4"]},
    {"id": 4, "tasks": ["T5"]}
  ]
}
```

**Why these boundaries**

Every wave holds one task, and that is deliberate rather than lazy. This feature is four
strictly sequential steps over three files, and each step is a producer for the next:

- **W0 → W1** — the capability must be injected before it can be bound. Landing it inert first
  means a green suite proves the wiring, so when W1's sabotage fails a test we know it failed
  for the binding and not for the injection.
- **W1 → W2** — the verdict must be readable before the body is allowed to read it. Reversing
  these would enter a body that cannot see why it was entered.
- **W2 → W3** — the example demonstrates behaviour that must already exist.
- **W4 is a checkpoint** and checkpoints always get their own wave.

`_engine/executor.py` is touched by T2 and T3, in waves 1 and 2 — separated, as the
file-disjointness rule requires. `freshness.py` is touched by T1 and T2, also separated.
