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

- [x] **2.1 — B2: `JobSources.functions` on `boot_standard`**
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

  **Done 2026-09-06.** The helper 1.1 built was extended rather than joined by
  a second one, and renamed to say what it now covers:
  `wire_declared_job_providers` → **`wire_declared_job_sources`**. It handles
  `functions` then `job_providers`; `boot_static`'s inline block is gone.

  - Acceptance met: `FunctualizeApp("a", job_sources=JobSources(functions=[alpha]))`
    yields `alpha` (was `[]`). 12 tests in `tests/app/test_job_sources.py`.
  - Ordering asserted: with a directory *and* `functions`, the pipeline reads
    `[DirectoryScanProvider, StaticProvider]`, and with `functions` +
    `job_providers` it reads functions-then-providers — matching the field
    order in `JobSources`, which is what keeps `StaticProvider`'s bare-name
    keying predictable.
  - `lazy=True` is covered explicitly. It is the default a real caller has and
    the static path never sees it, so a fix tested only at `lazy=False` would
    have missed the common case.
  - **Reachability, by sabotage** (each restored): deleting the `functions`
    block from the helper → 8 failed; removing the `boot_standard` call →
    19 failed; removing the `boot_static` call → 4 failed. Baseline and
    restore 24 passed.

- [x] **2.2 — B3: `register_dynamic_job` extracts parameters**
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

  **Done 2026-09-06.** Not one line — two extractions, because the one-line
  version made a whole class of job *worse*.

  **`config_fields` is the other half.** `job_detail` reads
  `config_fields or parameters`. A job declared `def needs(config: NeedsCity)`
  has exactly one signature parameter: `config`, of a Pydantic model type no
  CLI caller and no agent can supply. Populating `parameters` alone published
  *that* in place of the model's real fields — where before the fix, both were
  empty and nothing was published. So the dynamic path now applies discovery's
  full rule: fields from the config class if there is one, else the signature.
  An explicit `config_class=` argument wins over one detected on the signature,
  which is what `RegisteredJob` already does a few lines above.

  This half was **caught by sabotage, not by design**: the first version of
  this task added `config_fields` and three mutations of it — dropping the
  field, never detecting a class, ignoring the explicit argument — all passed.
  `TestAJobWithAConfigClass` (5 tests) closes that; the same three mutations
  now fail 5, 4 and 1.

  - Acceptance met: `grep -n "parameters=\[\]" src/functualize/_app/impl.py`
    → **0** (was 1, at `:732`).
  - Second acceptance met: `test_parameters_equal_the_discovered_twins`
    compares `(name, type_annotation, required, default)` tuples against a
    twin genuinely written to a file and scanned — not against the extractor
    called directly, which would only prove the extractor is deterministic.
  - Third acceptance met: `dynamic["inputSchema"] == discovered["inputSchema"]`
    and the same for `["parameters"]`. Before the fix a dynamically registered
    job published an **empty** `inputSchema` to `builtin info --json` and to
    every MCP client: an agent was told the job takes no arguments, called it
    with none, and got a `TypeError` from a job declared correctly.
  - `lint-imports` green — `_app` → `_discovery` is the composition root.
  - **Reachability, by sabotage** (4 mutations over 21 tests): `parameters=[]`
    → 9 failed; `config_fields` dropped → 5; no config class ever detected
    → 4; the explicit `config_class` ignored → 1. Baseline and restore 21
    passed.

  **Three test files outside `[F]` had to change, and the reason is the
  finding.** `tests/_cli/_tui_fixtures.py` carried this warning:

  > *dynamic jobs currently yield no field defs, so this default is only
  > suitable for SmartBar/keymap/modal flows, not panel-field flows*

  That was the defect, written down as a property of the framework and
  referenced from `contributor/guides/steering_textual_tui.md` §4.2. Removing
  it changed real behaviour in two places, both verified as improvements
  before anything was updated:

  1. `tests/_cli/test_snapshot_baseline.py` — two baselines regenerated. The
     entire diff is one new line, `● name: bob (cli) str` (and
     `name: world (default)` in the modal snapshot): the pre-flight row a
     dynamically registered job could not previously render. Confirmed by
     extracting the text nodes from both SVGs and diffing them.
  2. `tests/_cli/test_tui_failure_display.py` — two tests reached FAILURE by
     running a config job with nothing filled in, which only worked *because*
     the bar could not see the required field. The same job discovered from a
     file reported PENDING and opened the panel; a probe confirmed that,
     before the fixture was touched. Their assertions are unchanged; the run
     is now made to fail by a raising body instead, and
     `test_a_config_job_now_blocks_at_the_bar` pins the behaviour that
     replaced the old route.

---

## 3. Gate robustness

- [x] **3.1 — B4a: an unregistered strategy is a failed strategy, not a raise**
  In `GateRegistry.resolve_gate`, when the strategy list has more than one
  entry, an unregistered name records its failure and continues instead of
  raising. A single explicitly-named strategy still raises, and the
  preset branch keeps its distinct message.
  - `[F]` `src/functualize/_gate/_registry.py`, `tests/gate/test_registry.py`
  - Acceptance: a test asserts `resolve_gate(M, gate_strategy=["nope", "resolve"])`
    resolves via `resolve`, and `resolve_gate(M, gate_strategy="nope")` raises.
  - `GateResolutionError.last_error` names the unregistered strategies.

  **Done 2026-09-06.** Both acceptances met, in `tests/gate/test_registry.py`
  (17 tests). Three branches now, in this order: a preset reference still
  raises with its distinct message; a **single** entry — whether `"nope"` or
  `["nope"]` — still raises, so a typo in `gate_strategy="ai_inbund"` stays
  loud; anything longer records the name and continues.

  - `last_error` reports **both** causes when both occur: the unregistered
    names first (actionable), then the last resolver exception (usually a
    downstream symptom of having fallen that far). Dropping either half would
    leave the operator with only a cause or only a symptom.
  - Ordering matters and is pinned: a preset expands to *several* entries, so
    `len(...) == 1` does not distinguish it — `preset_source` does. Collapsing
    the two checks would silently make a broken preset fall through.
  - **Reachability, by sabotage**: forcing the old unconditional raise →
    6 failed; never raising for a single explicit name → 2 failed; removing
    the preset branch → 2 failed; dropping the unregistered names from
    `last_error` → 3 failed.

- [x] **3.2 — B4b: the strategy→plugin table**
  Add the fixed table from `contracts.md` §2 to `_gate/_strategy.py`, beside
  the enum. Core names the plugins; it must not import them.
  - `[F]` `src/functualize/_gate/_strategy.py`
  - Acceptance: `grep -rn "import functualize_ai\|import functualize_mcp" src/`
    returns **0** hits. Authoring-time count: **0** — this gate exists to keep
    it at zero.

  **Done 2026-09-06.** `STRATEGY_PROVIDERS`, `CORE_STRATEGIES` and
  `missing_strategy_hint()` sit beside the enum. The hint is what
  `_unregistered_message` in 3.1 renders into `last_error`.

  - Acceptance met and made **executable**, not just asserted: the grep runs
    inside `test_core_names_the_plugins_without_importing_them`, so it cannot
    silently stop being true. Still **0**.
  - `CORE_STRATEGIES` exists so `resolve` and `prompt` produce *no* hint.
    "Install something" is the wrong advice for those — if one is missing the
    registry was built by hand.
  - A second gate guards staleness: `set(STRATEGY_PROVIDERS)` must equal
    `_types.workflow._VALID_GATE_STRATEGIES`. A name a `Gate` accepts but the
    table omits would block with no hint, which is the failure the table
    exists to prevent.
  - **Divergence recorded, not fixed.** `GateStrategy` has three members;
    `_VALID_GATE_STRATEGIES` accepts four. The table follows the validator,
    because that is the set a `Gate` can actually declare, and `"ai_outbound"`
    is therefore a bare string here. Reconciling the two is out of scope
    (`spec.md`, "Redesigning gate strategy naming").
  - **Reachability, by sabotage**: making the hint always empty → 4 failed;
    dropping `ai_outbound` from the table → 3 failed.

- [x] **3.3 — B4c: the walk blocks, with a reason**
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

  **Done 2026-09-06.** `blocked_reason` is carried by three objects in
  sequence, and each hop is asserted separately so a break is attributable
  rather than merely visible at the top: `WalkReport` → `WorkflowRun` →
  `JobResult.metadata`.

  - **`[F]` extended (recorded):** `src/functualize/_engine/workflow_runner.py`
    and `src/functualize/_engine/executor.py`. The acceptance is written in
    terms of `RunStatus.BLOCKED` and `metadata["blocked_reason"]`, neither of
    which the walker produces — the walker returns a `WalkReport`, and the
    executor is what turns one into a `JobResult`. There was no way to meet
    the stated acceptance inside the declared scope.
  - Acceptance met: `Gate(strategy="ai_inbound")` with no resolver registered
    gives `RunStatus.BLOCKED`, `metadata["blocked_on"] == "triage"`, and a
    `blocked_reason` naming both `ai_inbound` and `functualize-ai`. It was a
    `ValueError` out of `app.execute()`.
  - Second acceptance met, parameterized: `strategy=None`, `"ai_outbound"`,
    and a registered-but-raising resolver all still return `BLOCKED`.
  - `blocked_reason` is **absent**, not empty, when there is nothing to say —
    a gate waiting by design, or `ai_outbound`, which blocks by policy so the
    walker never builds a strategy list for it. An always-present empty key
    would make every consumer guard for it.
  - A registered-but-raising resolver produces a reason with **no install
    hint**: the strategy exists, it failed, and "install functualize-ai" would
    send the operator the wrong way. Its text is the *last* rung's error, not
    the raising resolver's — the ladder keeps going, and
    `GateResolutionError.last_error` means last. Whether first would be more
    diagnostic is a pre-existing question about that field.
  - **STATUS #21 verified, not assumed.** Two tests assert
    `http_status_for_status(RunStatus.BLOCKED) != 200`, so the sequencing
    constraint this task carried is now executable rather than a note. Without
    `remote-source-activation` 1.3 and 4.2 this fix would have turned a visible
    Lambda 500 into `{"statusCode": 200, "body": null}`.
  - **Reachability, by sabotage** (6 mutations, each restored): restoring the
    registry's unconditional raise → 7 failed; the walker dropping
    `exc.last_error` → 3; `WalkReport` not carrying it → 3; `WorkflowRun` not
    carrying it → 3; the executor not publishing it → 3; publishing it
    unconditionally even when empty → 2. Baseline and restore 14 passed.

---

## 4. Diagnosis

- [x] **4.1 — B5: retain discovery failures — parse *and* import**
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

  **Done 2026-09-06.** New module `src/functualize/_types/discovery_report.py`:
  a frozen `DiscoveryFailure` (`module`, `path`, `error_type`, `message` — the
  four keys `contracts.md` §3 fixes) plus a ContextVar-scoped collector,
  `collecting_discovery_failures()` / `record_discovery_failure()`.

  A ContextVar rather than a threaded parameter because the parse sites live
  on `ModulePreFilter` implementations in `_primitives`, which have no
  reference to the provider running them and — by the constitution — cannot
  acquire one. A provider opens a scope around its scan; anything failing
  inside records. Outside a scope the call is a no-op, so a stray parse
  elsewhere in the process never lands in a discovery report. `lint-imports`
  green: `_types` still imports nothing internal.

  - **`[F]` extended (recorded, not silent):** `src/functualize/_discovery/cached_provider.py`
    was not in the declared scope and had to be. `lazy=True` is the default, so
    `CachedDirectoryScanProvider` is the provider a real boot uses; wiring only
    `providers.py` would have shipped a feature that reports nothing in the
    common case.
  - **Count corrected: eight sites, not nine.** The task says "nine" and then
    *lists* eight — seven in `_primitives/pre_filter.py` (six `should_import`
    methods plus `extract_function_decorators`) and one in
    `_discovery/ast_extractor.py`. Verified: `record_discovery_failure` now
    appears 7× in `pre_filter.py`, 1× in `ast_extractor.py`, and 2× more at
    the import sites (`providers.py`, `cached_provider.py`).
  - Acceptance met: `ModuleNotFoundError` retained with module path and
    exception type. Second acceptance met (**closes STATUS #12**): a
    `SyntaxError` module yields `error_type == "SyntaxError"`, reached both by
    calling a filter directly and end-to-end through a directory scan.
  - Third acceptance met, and made site-by-site rather than by sample: all six
    filter classes carry byte-identical `except` blocks, so
    `TestEverySwallowSite` parameterizes over every one and asserts both
    halves — it records, **and** it still returns `False`. Both branches of
    `except (OSError, SyntaxError)` are covered.
  - **A finding better than the task anticipated.** The warm-boot blind spot
    applies to *one* of the two stages, not both:
    - **import** failures write no cache entry, so the file stays in the "new"
      set and is retried — and reported — on every pass;
    - **parse** failures persist a negative pre-filter decision keyed by
      mtime, so the second pass skips the file and reports nothing.

    Both are asserted, the second with its reasoning: the list answers "what
    did *this* pass fail to read". A standing inventory of broken files would
    have to survive the cache, which means writing the failure into the cache
    entry — a different feature, deliberately not this one.
  - **Reachability, by sabotage** (eight mutations, each restored): all six
    pre-filter sites → 14 failed; `extract_function_decorators` → 1;
    `DirectoryScanProvider` import site → 4; `CachedDirectoryScanProvider`
    import site → 2; either provider's scope → 4 and 3; the collector never
    active → 25; accumulating instead of replacing the list → 1. Baseline and
    restore 29 passed.

- [x] **4.2 — B5: surface them**
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

  **Done 2026-09-06.** `_cli/info.discovery_failures(app)` walks
  `app._resolution_pipeline._providers` and collects each provider's
  `discovery_failures`. `full_report` publishes the key **after** `jobs`,
  because building that key is what forces the scan under a lazy boot.

  - **Read by attribute access, not by import, and deliberately not through a
    public seam.** `_cli` may not import `_discovery` (constitution), and
    `spec.md` puts new public API out of scope for this feature — a
    host-facing seam belongs to `third-party-host-seams`. The shape matches
    the existing `getattr(app, "_group_options", None)` a few lines above.
    Two tests cover the degradation: an app with no pipeline, and providers
    (`StaticProvider`, anything a plugin adds) that do not scan.
  - Acceptance met: `func builtin info --json` on a tree with one broken
    module contains the record; on a clean tree the key is present and `[]`.
    Both stages arrive under the one key.
  - **Flag correction confirmed by execution**, not by reading:
    `func builtin info --output json` still prints
    `Error: No such option '--output'`. The shipped flag is `--json`, and that
    is what the tests use.
  - **Key name follows `tasks.md`, not `contracts.md`.** §3 calls it
    `import_failures`, written before the scope widened. `import_failures`
    would be actively wrong for a `SyntaxError`, which never reaches the
    import path.
  - The plain rendering prints the failures **above** the job list: this is
    the explanation for a list that looks too short, and an explanation
    printed below the thing it explains gets scrolled past.
  - **A defect found by executing this, in 4.1's code.** A composite
    pre-filter is several filters, each of which parses the file itself, so
    one broken module produced *three* identical records in a single scan.
    The count tracked the filter configuration rather than the tree.
    `record_discovery_failure` now collapses an identical record; a
    *different* failure for the same path (an `OSError` after a
    `SyntaxError`) is a separate fact and is kept.
  - **Reachability, by sabotage** (5 mutations over 53 tests): the key never
    published → 18 failed; the key always empty → 14; the plain rendering
    never showing them → 4; the reader looking at the `ProviderEntry` instead
    of its `.provider` → 14; no deduplication → 2.

---

## 5. Documentation

- [x] **5.1 — B6: state the gate-strategy constraints**
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

  **Done 2026-09-06.** The section was nine lines listing three names with no
  statement of what accepts which. It is now six subsections: strategies vs.
  presets (with the registered-by table from 3.2), the `Gate` constraint, the
  two APIs that do reach presets, what a missing plugin does, and the
  inbound/outbound axis collision.

  - Acceptance met: **every snippet was executed**, not reviewed. The
    `ValueError` text, the walker's expansion of `ai_inbound` into
    `["ai_inbound", "prompt", "resolve"]`, `app.resolve_gate` with a preset
    name, `rc.invoke(..., gate_strategy="ai")`, and the full
    `result.metadata` block are all transcripts of real runs.
  - `mkdocs build --strict` exits 0. The rendered HTML was checked, not just
    the build: the first admonition title used `\"ai\"`, which mkdocs escapes
    literally into `<code>\"ai\"</code>`. Fixed to `ai`.
  - A6 met: `grep -n "preset" docs/guides/ai.md` reaches
    "presets are unreachable from a `Gate`" plus the worked `ValueError`.
  - `blocked_reason` is documented with its **real** value, both halves
    included. The first draft showed only the install hint; the shipped string
    also carries the last rung's own error after a `;`.

  **A shipped defect found by executing the docs.** The `"ai"` preset — which
  `functualize-ai` registers — has `ai_outbound` as its first rung, and
  `functualize-mcp` registers that. Since 3.1 keeps the preset branch raising,
  installing **only** `functualize-ai` and writing `gate_strategy="ai"` gives

  ```
  ValueError: Unregistered gate strategy 'ai_outbound' referenced in
  preset 'ai'. Register the strategy before using the preset.
  ```

  — the one place a missing plugin is not a graceful block. Documented as a
  warning admonition pointing at `"ai_inbound"` instead, and pinned by two
  tests in `tests/gate/test_registry.py` that import the preset definitions
  from the plugin rather than restating them, so the doc claim cannot drift
  from what the plugin registers.

  Writing those two tests corrected the claim twice, which is why they exist:
  the `"ai_inbound"` preset is self-sufficient only because the same plugin
  registers `ai_inbound` *and* the preset in one call, and only because core
  registers `prompt` at boot (verified:
  `FunctualizeApp("x")._gate_registry._strategies == ['prompt', 'resolve']`).
  The preset branch raises on **any** unregistered rung, not just the first.

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
