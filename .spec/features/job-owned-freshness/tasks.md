# Tasks — job-owned-freshness

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — an inert capability, proven wired

### [x] T1 · `Freshness` exists, is injected, and always reports `None`

**Files:** `src/functualize/_engine/capabilities/freshness.py`,
`src/functualize/_primitives/capability_names.py`, `src/functualize/job/__init__.py`,
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
rg -c 'Freshness' src/functualize/_primitives/capability_names.py
```
now: `0` · after: `1`

> Corrected 2026-09-10 (jof S2). Both the gate path and the `Files:` line above
> said `_primitives/di.py`, which holds nothing capability-related — the registry
> is `_primitives/capability_names.py:49`
> (`INJECTED_PARAM_TYPE_NAMES`), and `Freshness` is at line 60. The invariant
> itself was always satisfied; what was wrong was the artifact an auditor is told
> to run, so a reader re-running T1 got a red gate on a task ticked `[x]` and no
> way to tell the code was right. `W012-REPORT.md`'s *Scope note* had already
> recorded the discrepancy and run the real gate — the residue was that the
> record was never carried back here, which is the only place anyone re-runs.

**Test:** a job declaring `rc`-injected `Freshness` runs, receives the instance, and gets
`None` from `verdict()`. **The point of this wave is that the wiring is proven before it
carries meaning.**

---

## Wave 1 — the verdict arrives

### [x] T2 · Bind the verdict after the pre-flight, before the body

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

### [x] T3 · `Fingerprint.decides`, and the engine honours it

**Files:** `src/functualize/_types/job_declaration.py`,
`src/functualize/_engine/executor.py`,
`tests/execution/test_fingerprint_decides.py`

Add `decides: bool = False`. In the engine, extend the existing override block that already
handles `force_fresh` and `force` — **`:1022-1025`, not the return at `:1026`** — so all three
overrides of `SKIP_FRESH` read together in one place.

Spec AC-4, AC-5.

**Gate — the field exists**
```bash
rg -c '^\s+decides: bool = ' src/functualize/_types/job_declaration.py
```
now: `0` · after: `1`

> Corrected 2026-09-10 (jof S5). The gate was `rg -c 'decides' <file>`, which
> answers `8` — and **five** of those are code while three are the class
> docstring and a comment *describing* the field. So the smallest edit that
> should turn it red, deleting `decides: bool = False`, leaves three matches and
> the gate stays green. That is hazard #1 on this branch — a gate matching its
> own explanation — in a new place. Anchoring on the declaration line answers
> `1`, and deleting the field answers `0`.

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

### [x] T4 · The worked example, and the guide

**Files:** `examples/standalone/freshness_lab/jobs/self_caching_job.py`, `docs/guides/`,
`contributor/architecture/run-model/11-boundaries.md` (cross-reference)

> Corrected 2026-09-10 (jof S7). Planned as `examples/quickstart/…`; delivered
> under `examples/standalone/freshness_lab/`. **The move is right** —
> `quickstart/` is the README's Quick Start walked step by step, and every
> feature lab lives in `standalone/` — and every index already agrees with
> reality (`examples/README.md`, `examples/standalone/README.md`,
> `docs/examples/index.md`, the guide, and the boundaries cross-reference). Only
> this line and `plan.md`'s deliverable line were stale, which is the shape of
> defect that survives longest: everything a *reader* consults was updated, and
> only the two artifacts a *re-runner* consults were not.

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
rg -c 'GuardState.SKIP_FRESH' src/functualize/_engine/capabilities/freshness.py src/functualize/_engine/explain.py
```
now: `freshness.py: n/a`, `explain.py:2` · after: `freshness.py:1`, `explain.py:2`

> Corrected 2026-09-10 (jof S6). The gate matched the bare name `GuardState`,
> which only asserts that both files *mention the enum* — it would stay green if
> `FreshnessVerdict` spoke an entirely private vocabulary beside an unused
> import. `GuardState.SKIP_FRESH` is the one member the job actually
> distinguishes (`is_fresh` is true for that state and no other), so matching it
> is matching the shared word rather than the shared module.
>
> The gate is still the weaker instrument. What genuinely checks R-c is the
> **test** named below, which compares the two renderings of one run:
> `examples/standalone/freshness_lab/tests/test_self_caching_job.py::TestTheVerdictAndWhyAgree::test_they_describe_the_same_run`
> — `state=skip_fresh` in the job's own output against `SKIP (up to date)` from
> `func builtin why`. A gate is a tripwire; that test is the claim.

**Test:** `func builtin why <job>` and the job's own `verdict().state` describe the same run
identically —
`examples/standalone/freshness_lab/tests/test_self_caching_job.py::TestTheVerdictAndWhyAgree::test_they_describe_the_same_run`.

---

## Wave 4 — checkpoint

### [x] T5 · Feature gate

## AC → test, all eight

| AC | Kept by |
|---|---|
| AC-1 a job can read its own verdict | `tests/execution/test_freshness_capability.py`; `Freshness` is injected and carries the `GuardState`, the key, the recorded value, the declared patterns and the source map |
| AC-2 bound **after** the pre-flight, **before** the body | `CapabilitySpec.preflight_bind=_bind_from_preflight` — DI resolves before the pre-flight runs, so a capability carrying pre-flight data cannot be complete at creation. Same suite |
| AC-3 a job that does not opt in is still skipped when fresh | the `baseline` control job in `examples/standalone/freshness_lab/` runs beside `report` for exactly this |
| AC-4 opting in **enters the body** on `SKIP_FRESH` | `test_a_fresh_run_enters_the_body_and_returns_the_artifact` |
| AC-5 opting in does not bypass a precondition or a gate | `tests/execution/test_fingerprint_decides.py` |
| AC-6 the verdict read is the object the engine decided with | `tests/execution/test_freshness_capability.py::test_the_source_map_is_the_decisions_own_object` — `verdict.source_map is decision.source_map`, asserted against a `PreflightDecision` handed straight to `_bind_from_preflight`. Supported by `test_a_fresh_run_enters_the_body_and_returns_the_artifact` (`recorded_value` is a value only the decision holds) |
| AC-7 sabotage fails on **both** cold and warm paths | run below |
| AC-8 documented with a worked example | `uv run pytest examples/ -q -k self_caching` → **7 passed, 194 deselected** (was `no tests ran`) |

> **AC-1 row corrected 2026-09-10 (jof S3).** It said `Freshness` carries "the
> `GuardState`, key **and reason**". It does not carry a reason:
> `FreshnessVerdict` holds `state`, `key`, `recorded_value`, `declared_sources`,
> `declared_generates`, `source_map` and the `is_fresh` property. The *reason*
> belonging to the same decision is computed one layer up and reaches only
> `func builtin why` and the run record (`executor.py`, `"reason":
> decision.verdict.reason`).
>
> **Corrected rather than implemented, deliberately.** AC-1 never asked for it,
> and §6's concern is that the *vocabulary* agree — which it does, on
> `GuardState`, and which the R-c test checks. Adding `reason` and `checks` to
> the verdict would be cheap (both are already on `decision.verdict`) and is a
> reasonable future request, but nobody made it, and inventing a public field
> while fixing a sentence is how scope grows silently. Recorded here so the
> option is not lost.

> **AC-6 row corrected 2026-09-10 (jof S8).** It named
> `TestTheVerdictAndWhyAgree::test_they_describe_the_same_run`, which compares
> two *renderings* of one run — a by-value check standing in for a criterion
> about **identity**. The identity assertion existed and was not cited.
>
> One precision the AC itself owes: what the job reads is not literally the same
> object. `_bind` builds a `FreshnessVerdict` from five fields of the
> `PreflightDecision`, so "the same object" holds for `source_map` (bound by
> reference, deliberately) and for the `GuardState` member, but not for the
> wrapper. The substance AC-6 is after — *not recomputed* — is what the cited
> test proves.
>
> Also worth recording: `test_the_reading_changes_when_the_decision_changes`
> changes the **input file**, not the decision, so a capability that recomputed
> the map from the file itself would pass it identically. Its docstring claims
> more than it discriminates. The identity test is the one that separates them.

**Orphan scan** — every added symbol has real consumers, in `src` and in tests:
`Freshness` 19/30 · `FreshnessVerdict` 11/8 · `decides` 42/63.

**Both sabotages, run and restored.**

*T2 — disable `_bind_from_preflight`:* 10 failed, and AC-7's actual requirement is
visible in **which** failed — `test_the_declaration_survives_a_warm_boot` (warm) alongside
`test_a_cold_run_builds_and_writes_its_own_artifact` (cold). A binding that broke on only one
path would leave the other silently unbound, which is the shape the AC exists to forbid.

*T3 — force `_decides = False`:* 6 failed, including `test_the_framework_never_reads_the_artifact`
— the boundary this whole feature is *for*. Restored: 14 passed.

**Feature complete: 5/5.** The maintainer's decision it implements — the framework hands the
run its freshness verdict and the job decides whether to skip and return, because storing an
artifact is the job's business — is now a declaration a user can write, a verdict they can
read, and a lab they can run.

- `uv run ruff check src/ tests/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — 6 contracts kept
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- AC-1…AC-8 each named to a test
- orphan scan over `Freshness`, `FreshnessVerdict`, `decides`
- the two sabotages (T2's two-path binding, T3's forced `decides`), **committing before each**

---

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | *(fill from the wave's task headings: T1)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 1 | *(fill from the wave's task headings: T2)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 2 | *(fill from the wave's task headings: T3)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 3 | *(fill from the wave's task headings: T4)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 4 | *(fill from the wave's task headings: T5)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


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
