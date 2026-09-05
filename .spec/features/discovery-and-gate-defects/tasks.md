# Tasks — Discovery and gate defects

Gates were run at authoring time against `a2f453d`; each task records the hit
count its command returned, so drift between authoring and execution is
visible. `[F]` equals the gate's hit set.

---

## 1. Decision gate

- [ ] **1.1 — Resolve B1: wire or delete `job_providers`**
  Ask the maintainer, one question, with the snippet from `plan.md` §3.
  Record the answer in this file under the task, then do it.
  - `[F]` `src/functualize/app/config.py`
  - Acceptance: `grep -rn "job_providers" src/` returns **0** hits (delete), or
    ≥1 hit outside `app/config.py` (wire). Authoring-time count: **2**, both
    in `app/config.py:48` (docstring) and `:56` (field).
  - If wired: the `(provider, [transforms])` tuple form the docstring promises
    works on **both** boot paths, with a test for each.
  - If deleted: the commit body names `app.add_job_provider()` as the
    supported path.

---

## 2. Silent-drop defects

- [ ] **2.1 — B2: `JobSources.functions` on `boot_standard`**
  Lift the `functions` → `StaticProvider` step out of `boot_static` into a
  helper both paths call.
  - `[F]` `src/functualize/_app/boot.py`, `tests/app/test_job_sources.py`
  - Acceptance: a test asserts
    `FunctualizeApp("a", job_sources=JobSources(functions=[alpha])).get_jobs()`
    yields `alpha`. Authoring-time behaviour: `[]`.
  - Also assert ordering against a directory provider in the same test, so a
    regression in `StaticProvider`'s bare-name keying is visible.
  - Reachability: the call path is `FunctualizeApp.__init__` → `boot_standard`
    → the new helper. Verify by removing the helper call and watching the new
    test fail.

- [ ] **2.2 — B3: `register_dynamic_job` extracts parameters**
  Replace `parameters=[]` with `extract_parameters_from_signature(function)`,
  imported beside the existing `extract_capability_markers` /
  `extract_ext_metadata` imports.
  - `[F]` `src/functualize/_app/impl.py`, `tests/app/test_dynamic_registration.py`
  - Acceptance: `grep -n "parameters=\[\]" src/functualize/_app/impl.py` returns
    **0** hits. Authoring-time count: **1**, at `:732`.
  - Second acceptance: a test asserts the dynamic and directory-discovered
    descriptors for one function have **equal** `parameters`. Authoring-time:
    `[]` vs `['x']`.
  - Layer check: `_app` → `_discovery` is permitted (composition root).
    `uv run lint-imports` must stay green.

---

## 3. Gate robustness

- [ ] **3.1 — B4a: an unregistered strategy is a failed strategy, not a raise**
  In `GateRegistry.resolve_gate`, when the strategy list has more than one
  entry, an unregistered name records its failure and continues instead of
  raising. A single explicitly-named strategy still raises, and the
  preset branch keeps its distinct message.
  - `[F]` `src/functualize/_gate/_registry.py`, `tests/gate/test_registry.py`
  - Acceptance: a test asserts `resolve_gate(M, gate_strategy=["nope", "resolve"])`
    resolves via `resolve`, and `resolve_gate(M, gate_strategy="nope")` raises.
  - `GateResolutionError.last_error` names the unregistered strategies.

- [ ] **3.2 — B4b: the strategy→plugin table**
  Add the fixed table from `contracts.md` §2 to `_gate/_strategy.py`, beside
  the enum. Core names the plugins; it must not import them.
  - `[F]` `src/functualize/_gate/_strategy.py`
  - Acceptance: `grep -rn "import functualize_ai\|import functualize_mcp" src/`
    returns **0** hits. Authoring-time count: **0** — this gate exists to keep
    it at zero.

- [ ] **3.3 — B4c: the walk blocks, with a reason**
  The walker's gate branch produces `BLOCKED` for this cause and sets the
  additive `blocked_reason` from the `GateResolutionError`.
  - `[F]` `src/functualize/_engine/workflow_walker.py`, `tests/engine/test_workflow_gates.py`
  - Acceptance: a test asserts `Gate(strategy="ai_inbound")` with no resolver
    registered gives `RunStatus.BLOCKED` and a `blocked_reason` naming
    `functualize-ai`. Authoring-time behaviour: raises `ValueError`.
  - Second acceptance: the three already-correct cases stay correct —
    `strategy=None`, `"ai_outbound"`, and a registered-but-raising resolver all
    still return `BLOCKED`. Regression guard, parameterized.
  - `[verify-e2e:TARGETED]`

---

## 4. Diagnosis

- [ ] **4.1 — B5: retain import failures**
  The directory scan appends `{module, path, error_type, message}` per failed
  import instead of only logging.
  - `[F]` `src/functualize/_discovery/providers.py`, `tests/discovery/test_import_failures.py`
  - Acceptance: a test with a module raising `ModuleNotFoundError` asserts one
    retained record with the module path and the exception type.
  - The list is per-scan. A cached/lazy boot that imported nothing reports no
    failures — assert that too, so a stale report cannot appear.

- [ ] **4.2 — B5: surface them**
  `builtin info` carries `import_failures` (empty list when none, never
  absent), per `contracts.md` §3.
  - `[F]` `src/functualize/_cli/info.py`, `tests/cli/test_info.py`
  - Acceptance: `func builtin info --output json` on a tree with one broken
    module contains the record; on a clean tree the key is present and `[]`.
  - Reachability: name the call path from the CLI command to the provider's
    list. Verify by breaking it and watching the test fail.

---

## 5. Documentation

- [ ] **5.1 — B6: state the gate-strategy constraints**
  In `docs/guides/ai.md`, the "Gate Strategies" section says that a `Gate`
  accepts only the four bare names, that `Gate(strategy="ai")` raises, and
  that presets resolve only via `rc.invoke(..., gate_strategy=...)` and
  `app.resolve_gate`. Note the two-axis use of *inbound*/*outbound*
  (`contracts.md` §4).
  - `[F]` `docs/guides/ai.md`
  - Acceptance: every snippet in the section executes. `mkdocs build --strict`
    exits 0.
  - Not gated by the spec hook (`docs/` is exempt), but sequenced last so it
    describes the shipped behaviour.

---

## 6. Checkpoint

- [ ] **6.1 — Full gate run**
  - Acceptance: `uv run pytest`, `uv run ruff check src/ tests/`,
    `uv run ruff format --check src/ tests/`, `uv run mypy src/`,
    `uv run lint-imports` — all green.
  - Walk `spec.md`'s A1–A7 item by item and record each as met.
  - `[verify-e2e:FULL]`

---

## Task Dependency Graph

Wave 0 is the decision gate: 1.1 touches `app/config.py`, and its answer can
change whether `boot.py` grows a second provider path, so 2.1 must not start
first. 3.1 produces the error 3.3 consumes. 4.1 produces the list 4.2 reads.
2.1 and 2.2 touch different files and are independent. 3.2 is table-only and
shares no file with 3.1.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1", "3.2", "4.1"] },
    { "id": 2, "tasks": ["3.3", "4.2"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["6.1"] }
  ]
}
```
