# Handoff — capability-duality

**GREEN as of 2026-09-11**, across all three suites — and the first version of
this line was wrong, which is worth keeping:

| suite | how it must be run | result |
|---|---|---|
| `tests/` | `HYPOTHESIS_PROFILE=ci pytest --run-slow -n auto` | 11,726 passed, 155 skipped |
| `examples/` | separately — a conftest clash means it cannot be collected with `tests/` | 201 passed |
| `plugins/*/tests` | one package at a time, same reason | 28 + 59 + 80 + 25 passed |

Plus ruff, `mypy` (348 files), `lint-imports` (7 contracts).

**`examples/` was red with 8 failures when this file first said GREEN.** It does
not run with `tests/`, so "the full suite is green" was a claim about one of
three suites. The failures were mine (the unified scope id) and had been there
for hours. **Run all three before saying green** — the same shape of mistake as
the `--run-slow` one below, one level out: the first was a flag I forgot, this
was a suite I forgot. The section
below is kept as the record of what was wrong and how it was found.

---

## The red, and how it was cleared (historical)

**The branch was red: 36 failures.** Every one is attributable to T2 (durable
state) and none were caught before commit, because the suites run during
execution — `tests/context`, `tests/integration`, `tests/workflow`,
`tests/core` — did not include these files. The lesson is the one already
recorded on this branch and repeated here: *a refactor's blast radius is not
the directory it edits.* Run the full suite before commit, not the neighbourhood.

**Root cause of the whole episode, worth keeping:** every one of the 36 was a
`--run-slow` test. The suites run during execution used the default profile,
which *skips* them; only the full suite passes the flag. So "I ran the
neighbouring suites" was never the check it appeared to be. The rule that
replaces it: **run the full suite with `--run-slow` before committing a
refactor**, not the directory you edited.

## What is done

| task | state |
|---|---|
| T1 · `keys()` matches by glob | done — `5642b32` |
| T2 · `State` is durable, no in-memory tier | **code done, tests not migrated** — `fb7b409` |
| T3 · a workflow step's `rc.state` is the run's store | done — `2d72925` |
| T5 · ADR-021 | done — `5009eca` |
| T4 · `rc._cap` is the one resolver | done — `d7a01c4` |
| T6 · the registry-driven tripwire | done — `43f5809` |
| T7 · the example stops teaching the trap | done — `81d4db2` |
| T8, T9, T10 | not started |

Plus `a7fb91d`: a scope with no workflow is no longer listed as one.

## The 36, grouped — with the judgement each needs

Most are mechanical. **Two are not**, and they are listed first because they
are decisions, not chores.

### 1. `tests/context/test_parallel_and_log_properties.py` (1) — a deliberate semantic change

`test_parallel_state_mutations_isolated_across_keys` asserts that parallel
items have **isolated** state. T2 deliberately reversed that: `invoke_parallel`
now passes the scope *object* (state) while `nested_request` still withholds
the *id* (records). The reasoning is in `invoke.py` at the call site and in
`research.md` §2.

**This test is not wrong — it pins the old contract.** Rewrite it to assert the
new one (items share the run's store; two *runs* share nothing), or overturn
the change. Do not silently delete it.

### 2. `tests/workflow/test_wf_flags_dispatch_matrix.py` (7) — resume, unexamined

`test_wf_resume_advances_on_every_mode`. Not yet diagnosed. Most likely the
scope-id shape (one generator now, `<job>-<hex8>`) or the fact that
`engine.run` mints a scope where the dispatch matrix expected none. **Diagnose
before assuming it is cosmetic** — this is the resume path, which is the whole
point of durable state.

### 3. Tests of API deleted with the in-memory class (12) — mechanical

- `tests/test_state_prefix.py` (6) — `State.keys(prefix)` with the old
  prefix/TypeError semantics. `keys()` is a glob now.
- `tests/context/test_state_store_props.py::TestStateStoreTypedGet` (5) —
  typed `get(key, type)`. Removed: no caller in `src/`, `examples/` or `docs/`.
- `tests/context/test_state_store_props.py` clear/keys (1).

Port to `State` over a real store via `tests/context/conftest.py::new_state_store`,
or delete where they test API that no longer exists — and say which, per the
Pre-Release Stance.

### 4. Scope construction now requires a store (12) — mechanical

`WorkflowScope(...)` no longer defaults to an in-memory store; the store is
injected so a scope that cannot persist is visible at construction.

- `tests/context/test_state_store_scope_props.py` (5)
- `tests/context/test_scope_metadata_properties.py` (4)
- `tests/context/test_workflow_scope_props.py` (3)

Same fix as `tests/core/test_scope_state_metadata.py`, already ported:
`WorkflowScope(id, state_store=new_state_store(id))`.

### 5. Two small ones

- `tests/test_scope_store.py::test_blank_scope_has_every_section` (1) — the
  blank record gained a `state` section. Update the expected set.
- `tests/test_testing_properties.py` (3) — `TestRunContext` defaults now build
  a real temp-backed store (`builder._temp_state`), not `State()`.

## Two things worth not losing

**The in-memory double is gone on purpose.** `MemoryStateStore` was deleted
from `functualize.testing.doubles` after measuring the real store: 0.557 ms per
unbatched `set`, 0.091 ms per `get`, 1.1 ms for 100 batched, 0.012 ms to
construct. There is no performance argument for a double, and a double standing
in for the production collaborator at the seam under test is how `Perf` shipped
unwired for its entire life. Do not reintroduce one to make these 36 easier.

**T10 is real and unfixed.** Tests without a `chdir` write into the
*repository's* `.functualize/`. Measured mid-feature: `scopes.json` 359 KB,
`runs.json` 261 KB, `state.json` 51 KB of residue. Gitignored, so nothing was
committed, but it makes tests order-dependent and it produced a real failure
(`invocation=4` on a first invocation). Some of the 36 may be order-dependent
for this reason — **fix T10 before concluding any of them is flaky.**

## Follows from this feature

`store-substrate` — written 2026-09-11, **not started**. Two things this
feature surfaced that it owns:

- **The split-brain.** `capability-duality` put `rc.state` inside the scope
  record, so swapping the KV store to SQLite today puts the value in SQLite and
  the record that gives it meaning in `scopes.json` — two locks, no transaction
  across them. `functualize-state-sqlite` produces this now.
- **`StateStore` is 36 methods of which 25 forward to `ScopeStore`.** They
  become peers over one substrate and the 25 are deleted.

Sequenced after `durable-run-layer` T3b (history leaves `state.json`) and
T5–T8 (the lease, which is the compare-and-swap primitive a remote substrate
needs).

## Held elsewhere, deliberately

`durable-run-layer`/**T3b** — deriving `history` from the run log, then renaming
`state.json` to `fresh.json`. Written up in full there. It is only correct after
the history question is decided, and that is decided in T3.
