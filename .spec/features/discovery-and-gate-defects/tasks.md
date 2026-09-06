# Tasks — Discovery and gate defects

Gates were run at authoring time against `a2f453d`; each task records the hit
count its command returned, so drift between authoring and execution is
visible. `[F]` equals the gate's hit set.

---

## 1. `job_providers`

**B1 is decided: WIRE IT.** (Maintainer, 2026-09-05. `plan.md` §3 recommended
deletion; the maintainer chose wiring, so the field must honour everything its
docstring promises rather than being removed.)

- [x] **1.1 — B1: wire `job_providers` on both boot paths**
  The field's providers reach the resolution pipeline, including the
  `(provider, [transforms])` tuple form the docstring promises.
  - `[F]` `src/functualize/app/config.py`, `src/functualize/_app/boot.py`, `tests/app/test_job_providers.py`
  - Acceptance: `grep -rn "job_providers" src/` returns ≥1 hit **outside**
    `app/config.py`. Authoring-time count: **2**, both inside it —
    `app/config.py:48` (docstring) and `:56` (field).
  - Second acceptance: a test for **each** boot path (`boot_static` and
    `boot_standard`), and a test for the tuple form. Three tests minimum.
  - The declared type stops being `list[Any]` and becomes what the docstring
    says (`contracts.md` §1).
  - Shares `_app/boot.py` with 2.1, which adds a provider path to
    `boot_standard` for the same reason — build **one** helper both use, or
    they will drift. Same wave, one task order: 1.1 then 2.1.

  **Done 2026-09-06.** `_app/boot.wire_declared_job_providers(app)` is the one
  helper, called from both paths after each has added the providers it derives
  itself — so pipeline order matches field declaration order (directories,
  functions, `job_providers`). 2.1 extends this function; it must not add a
  second one.

  - Acceptance met: `grep -rn "job_providers" src/ | grep -vc "app/config.py"`
    → **8** (was 0). Second acceptance met: 15 tests in
    `tests/app/test_job_providers.py`, covering both paths, the pair form on
    both paths, mixed entries, ordering against a directory provider,
    malformed entries, and equivalence with `add_job_provider`.
  - Type is now
    `list[JobProvider | tuple[JobProvider, list[JobTransform]]] | None`, with
    the protocols imported under `TYPE_CHECKING` (`app/config.py` is on the
    cold boot path, and `exclude_type_checking_imports` keeps `lint-imports`
    indifferent).
  - **Reachability, by sabotage.** Four mutations, each restored: removing the
    `boot_static` call → 2 failed; removing the `boot_standard` call →
    12 failed; ignoring `isinstance(entry, tuple)` → 7 failed; passing
    `None` instead of `transforms` → 4 failed. Baseline and restore both 15
    passed.
  - Full root suite after: **8726 passed, 1544 skipped, 0 failed** (8711
    before, +15 = exactly the new tests). `ruff`, `ruff format --check`,
    `mypy src/` (316 files), `lint-imports` (5 contracts) green.

  **Two adjacent findings, both left alone as out of scope.** Recorded because
  each looks like a bug in this wiring and is not:
  1. `is_fully_explicit()` reads `functions is not None`, so an app declaring
     *only* `job_providers` falls to `boot_standard`. Changing that condition
     is explicitly out of scope (`spec.md`), so the static-path tests pass
     `functions=[]`.
  2. `ResolutionPipeline.resolve_one("ns.alpha")` returns `None` for a
     namespaced descriptor that `resolve_all()` lists — the single-name lookup
     does not reach through `NamespaceTransform.transform_get`. It predates
     this change and is equally wrong for a declared and an added provider.
     Pinned by assertion in `test_both_paths_agree_on_the_pair_form` so a fix
     is noticed rather than assumed.

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
  - Third acceptance **(added 2026-09-05)**: assert the *downstream* payload,
    not only the descriptor. `contracts.md` §5 says "no caller changes", which
    is true of call **sites** but not of payloads: `job_detail` computes
    `fields = descriptor.config_fields or descriptor.parameters`
    (`_cli/info.py:136`) and feeds `inputSchema`. So populating `parameters`
    changes `job_detail["parameters"]` **and the MCP tool input schema** for
    every dynamically registered job. That is the desired outcome and it was
    uncovered by any gate. Assert the schema a dynamic job exposes is equal to
    the one its directory-discovered twin exposes.
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
  - **Downstream consequence (found 2026-09-05, reproduced).** Today
    `Gate(strategy="ai_inbound")` raises `ValueError` **out of
    `app.execute()`** — confirmed by running `examples/standalone/
    composition_lab` with the strategy flipped. On the Lambda surface that
    exception hits the handler's `except` branch and becomes a visible **500**.
    After this task it becomes a `BLOCKED` result, and the Lambda handler
    (`plugins/functualize-lambda/…/__init__.py:126`) never reads
    `result.status` — so a correct fix silently turns a 500 into
    `{"statusCode": 200, "body": null}`.

    That is STATUS follow-up #21, and it is closed in
    `features/remote-source-activation/` tasks **1.3** (the `RunStatus` → HTTP
    table in `_types/`) and **4.2** (the plugins consuming it). **This task
    must not land in a release without those**, or the release ships the
    regression.
  - `[verify-e2e:TARGETED]`

---

## 4. Diagnosis

- [ ] **4.1 — B5: retain discovery failures — parse *and* import**
  **Scope widened (maintainer, 2026-09-05).** As originally written this task
  covered import failures only, which would **not** have closed STATUS
  follow-up #12 ("a job module with a `SyntaxError` vanishes silently") — a
  `SyntaxError` never reaches the import path. It is swallowed earlier, in the
  AST/pre-filter stage, at **nine** sites verified at authoring time:
  `_primitives/pre_filter.py:115,143,188,266,329,387,431` and
  `_discovery/ast_extractor.py:37`.

  Shipping import-only would have displayed `import_failures: []` for a
  syntactically broken tree — which reads as "nothing is wrong" and is worse
  than today's silence.

  Both stages append `{module, path, error_type, message}` to one list, named
  `discovery_failures`.
  - `[F]` `src/functualize/_discovery/providers.py`, `src/functualize/_primitives/pre_filter.py`, `src/functualize/_discovery/ast_extractor.py`, `tests/discovery/test_discovery_failures.py`
  - Acceptance: a test with a module raising `ModuleNotFoundError` retains one
    record naming the module path and the exception type.
  - Second acceptance: a test with a module containing a **`SyntaxError`**
    retains one record with `error_type == "SyntaxError"`. This is the
    assertion that closes #12; without it the widening is not done.
  - Third acceptance: the nine swallow sites still **swallow** — a broken
    module must not become fatal. Discovery continues; it just records.
  - The list is per-scan. A cached/lazy boot that imported nothing reports no
    failures — assert that too, so a stale report cannot appear.
  - `_primitives` may not import `_discovery` (constitution). The record type
    therefore lives in `_types/` or is a plain tuple; `lint-imports` is the
    gate.

- [ ] **4.2 — B5: surface them**
  `builtin info` carries `discovery_failures` (empty list when none, never
  absent), per `contracts.md` §3.
  - `[F]` `src/functualize/_cli/info.py`, `tests/cli/test_info.py`
  - Acceptance: `func builtin info --json` on a tree with one broken module
    contains the record; on a clean tree the key is present and `[]`.
  - **Flag corrected (2026-09-05).** This gate previously read
    `func builtin info --output json`, which is **unexecutable** — verified:
    `Error: No such option '--output'`. The shipped flag is `--json` (bool).
    `--output` is the spelling *proposed* by
    `shape-intents/output-flag-normalization.md`, which is unimplemented; if
    that lands first, this command moves with every other, not ahead of them.
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

Wave 0 is 1.1. B1 is now decided as *wire it*, so 1.1 is real work rather than
a question — and because wiring `job_providers` adds a provider path to
`boot_standard`, it touches the same file and the same seam as 2.1. They must
not run concurrently, and 1.1 goes first because 2.1 should extend the helper
1.1 builds rather than introduce a second one.

3.1 produces the error 3.3 consumes. 4.1 produces the list 4.2 reads. 2.1 and
2.2 touch different files and are independent. 3.2 is table-only and shares no
file with 3.1. 4.1's widened scope adds `_primitives/pre_filter.py` and
`_discovery/ast_extractor.py`, neither of which any other wave-1 task touches.

**Cross-feature ordering.** 3.3 makes an unresolvable gate return `BLOCKED`
instead of raising, which regresses the Lambda surface until
`remote-source-activation`/1.3 and /4.2 land. Those are not tasks here, but no
release may contain 3.3 without them.

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
