# Tasks: one parameter contract behind every surface

The confirmed `spec.md`, `contracts.md`, `schema.md` and `plan.md` are the inputs.

- **`[F]` is each task's allowed edit scope.** It is the hit set of the retrieval query named in the
  task (`matrix/evidence/blast-radius.txt`, `gates-authoring.txt`).
- **Counts in `Gate` were measured at authoring time on `da912d76`.**
- **Reachability** (constitution, *Quality Gates*): each task names the production call path to its
  code and proves it by removing that call and watching a named test fail. Commit first, sabotage
  second, restore third.
- **Transitional states are labelled in code** with `# TRANSITIONAL(<task>): …` and removed by the
  named task.
- **SS-3 = B (member, comment `01a201b6-3d91-7eb2-8587-df5f212bf69f`, 2026-11-22T05:24:10Z).**
  `FieldDescriptor.type_annotation` is removed in this change, not kept as a display label.
  - No task adds a new read of `type_annotation`.
  - A task that edits a file which reads it replaces that read with the contract:
    `contract.display` where a human needs a type label, and the contract's fields
    (`verdict`, `shape`, `cli`) where behaviour depends on it.
  - Waves 9 and 10 remove what is left, and 10.1 deletes the field.
- **Plugin package tests run separately (2026-11-22).** The root `tests` package and each plugin's
  own `tests` package cannot be collected in one pytest invocation (`ImportPathMismatchError`), and
  the root suite (`testpaths = ["tests"]`) runs none of them. Wave 0's gate therefore covered no
  plugin test, and missed a substrate failure caused by 0.2. Two rules follow:
  - a task whose `[F]` touches `plugins/<group>/<package>/**` runs
    `uv run pytest plugins/<group>/<package>/tests` as **its own invocation** in its gate, never
    combined with root test paths;
  - **every wave barrier** runs every plugin package separately, because fallout can be indirect
    (0.2 changed only `_types/` and broke the substrate):
    `for d in plugins/*/*/tests; do uv run pytest "$d" -q || exit 1; done`.
    Measured on `21c4bb81`: 11 of 12 packages green, and the substrate red at
    `tests/test_migrations.py::test_each_status_check_equals_its_machines_state_set[runs-machine1]`
    (`matrix/evidence/plugin-suites-21c4bb81.txt`).
- **Every wave barrier also runs the whole root suite.** Run `uv run pytest tests -q -n auto`;
  when one invocation would exceed the 600-second call cap, partition `tests/` into disjoint
  foreground chunks that cover every root test file exactly once, and report each command and
  result. This catches cross-package fallout that neither a task's narrow gate nor the plugin
  loop sees. Eight root test modules use the bare `_group` import name; run each in its own pytest
  process, outside the large chunks, to avoid import collisions. A wave does not complete while
  any root or plugin chunk is red.
- **Every task's gate also includes** `uv run lint-imports` (baseline "7 kept, 0 broken"), plus
  `uv run ruff check`, `ruff format --check` and `mypy src/` on the files it touches.

## Wave 0 — the record, the outcome row, the table, two independent fixes

### [x] 0.1 Contract types, the descriptor field, the cache codec

- **Input:** `schema.md` (types, invariants 3 and 5, cache encoding).
- **[F]:**
  - `src/functualize/_types/parameter_contract.py` (new);
  - `src/functualize/_types/descriptors.py`;
  - `src/functualize/_primitives/cache_format.py`;
  - `tests/types/test_parameter_contract_codec.py` (new);
  - `tests/types/test_descriptor_owner_class.py` (scope repair, 2026-11-22, see below);
  - `tests/discovery/test_job_declaration_discovery.py` (scope repair, 2026-11-22, see below).
- **Scope repair (2026-11-22, added after the first tick; the task is reopened).** The plan missed
  the fallout of 0.1's own `CACHE_VERSION` bump from 25 to 26. Two tests pin the constant's current
  value, and both are red by construction once 0.1 lands:
  - `tests/types/test_descriptor_owner_class.py:40`, `assert CACHE_VERSION == 25`;
  - `tests/discovery/test_job_declaration_discovery.py:169`, `assert data["version"] == CACHE_VERSION == 25`.

  They move to 26. The other version literals near them are **poison values that stay**: they set a
  deliberately old version to test refusal and rebuild, and editing them would delete the tests'
  meaning. Those are `test_descriptor_owner_class.py:44` (`"version": 22`),
  `test_job_declaration_discovery.py:133` (`21`), `test_nfkc_cache_rebuild.py:35` (`21`) and
  `test_discovery_failures.py:674` (`version=20`).

  Census at the time of the repair (`matrix/evidence/cache-version-pins.txt`):
  - `rg -n 'CACHE_VERSION\s*(==|!=|>=)\s*[0-9]+|"version"\s*:\s*2[0-9]' tests/` → 3 hits: the 2
    pins plus the `:44` poison literal;
  - `rg -n -e "== 25\b" -e "CACHE_VERSION.*25" tests/ plugins/*/*/tests/` → the 2 pins plus one
    unrelated `age.default == 25`.

  Every other test reads the symbol `CACHE_VERSION`, not a number.

  The task was ticked when its first gate passed, and is reopened, because the constitution allows
  `[x]` only when its gate is green against the code as it stands, and the repaired gate is red until
  both pins move. The code committed in `70c2a202` stands; only the two assertions change.
- **Work:**
  - Add the frozen dataclasses and enums.
  - Add `FieldDescriptor.contract` (optional, default `None`). Do **not** touch
    `type_annotation`, its `type` alias or the codec's `"type"` key here: their removal is placed in
    waves 9 and 10 (SS-3 = B).
  - Encode and decode it in `_field_to_dict` / `_field_from_dict` (`descriptors.py:631`, `:685`),
    with `default_json` as JSON-native.
  - Bump `CACHE_VERSION` from 25 to 26 (`cache_format.py:178`).
- **Invariant:** `_types/parameter_contract.py` imports stdlib only. A descriptor with a contract
  round-trips through the codec equal to itself.
- **Gate/evidence:**
  - `uv run pytest tests/types/test_parameter_contract_codec.py tests/test_descriptor.py tests/discovery/test_cache_manager.py tests/config/test_descriptor_cache_fidelity.py tests/types/test_descriptor_owner_class.py tests/discovery/test_job_declaration_discovery.py`;
  - `rg -n "^CACHE_VERSION = 26" src/functualize/_primitives/cache_format.py` → 1 hit (today
    `CACHE_VERSION = 25`, 1 hit);
  - `lint-imports` "Types import nothing internal" KEPT.
- **Depends on:** none.

### [x] 0.2 One new outcome: `RunStatus.INVALID`

- **Input:** `plan.md` § *The refusal outcome*; `_types/enums.py:31-50`; `_types/exit_codes.py:41`;
  `_types/http_status.py:54-74`.
- **[F]:**
  - `src/functualize/_types/enums.py`;
  - `src/functualize/_types/exit_codes.py`;
  - `src/functualize/_types/http_status.py`;
  - `src/functualize/_types/outcome.py`;
  - `tests/types/test_outcome_invalid.py` (new).
  - `tests/context/test_runcontext.py` (member-count and terminal-state repair);
  - `tests/context/test_runcontext_status.py` (terminal-state repair).
- **Work:** add `INVALID` ("the call could not be bound to the job's declaration — nothing ran").
  Map it once per family: exit `USAGE` (2), HTTP 400, Lambda 400. Make it terminal and not
  resumable.
- **Invariant:** `REFUSED` keeps exit 3 / HTTP 412. Every family's table maps `INVALID`.
- **Gate/evidence:** `uv run pytest tests/types/`, which includes the existing
  `test_every_surface_declares_its_family.py`.
- **Execute finding (2026-11-22), resolved by scope repair.** This gate was red at
  `tests/types/test_descriptor_owner_class.py::test_cache_reader_refuses_version_22`, which asserted
  `CACHE_VERSION == 25`. The cause is not this task: 0.1's version bump has fallout that 0.1 now
  owns (see 0.1's scope repair, with the second pin at
  `tests/discovery/test_job_declaration_discovery.py:169`). 0.2's outcome code is committed
  (`7a610a7d`). The task is ticked when `uv run pytest tests/types/` is green, after 0.1's repair
  lands.
- **Execute repair (2026-11-22):** the root suite exposed two additional status pins outside the
  original scope. The member count now includes `INVALID`, and the independent context status
  table asserts it is terminal and not resumable. `uv run pytest tests/context/test_runcontext.py
  tests/context/test_runcontext_status.py tests/types/ -q` → 618 passed, 2 skipped. The reopened
  task is ticked against this gate.
- **Depends on:** none.

### [x] 0.3 The declaration table

- **Input:** `matrix/rows.py` (166 rows); `matrix/report.py::proposed` (each row's expected verdict).
- **[F]:** `tests/_support/parameter_matrix.py` (new).
- **Work:** each row is data: id, declaration source, expected verdict, and per-surface expectations
  (spelling, requiredness, delivered type). Proposed verdicts are as on page v5. H166 and the other
  missing-provider rows are `REJECTED_DISCOVERY`, *reported*, per DC-1 = B. Generated module sources
  compile both with and without `from __future__ import annotations`.
- **Invariant:** the table is the single source that 1.1's unit tests, 11.2's parity test and 11.1's
  docs table read (page §5.8).
- **Gate/evidence:** `uv run python -c "from tests._support.parameter_matrix import ROWS; assert len(ROWS) == 166"`.
- **Execute evidence (2026-11-22):** 166 rows; all 332 generated modules compile across the two
  annotation modes; each row has nine surface expectations. The missing-provider rows C085, C087,
  E138, E139 and H166 are `REJECTED_DISCOVERY`. This is test data, so it has no production call path;
  its planned consumers are 1.1's contract tests and 11.1/11.2's docs/parity tests.
- **Correction (2026-11-22, designer):** 10 of the 166 rows encoded today's measurement, or an
  undecided provider case, instead of intent. `matrix/report.py::proposed()` is corrected and
  `matrix/evidence/table-corrections.txt` gives each row's spec clause. Task 1.1 corrects the table
  rows, because 1.1 is the table's first reader and the table is test code. The tick stands: this
  task's gate (166 rows) is unaffected.
- **Depends on:** none.

### [x] 0.4 Lambda docstrings name the shared envelope (F-28)

- **Input:** `gates-authoring.txt` `lambda-kwargs-doc`: 4 hits, at `__init__.py:8`, `:154`, `:178`
  and `:220`.
- **[F]:** `plugins/adapters/functualize-lambda/src/functualize_lambda/__init__.py`.
- **Work:** the docstrings describe `{"job": …, "arguments": {…}}`. No code change: the envelope
  already reads `arguments` (`run_request.py:343`).
- **Gate/evidence:**
  - `rg -n '"kwargs"' plugins/adapters/functualize-lambda/src` → 0 hits (today 4);
  - `uv run pytest plugins/adapters/functualize-lambda/tests` (its own invocation). This line was
    added 2026-11-22 under the plugin-package rule, after the task was ticked. Run on `21c4bb81`:
    59 passed (`plugin-suites-21c4bb81.txt`). The tick stands.
- **Depends on:** none.

### [x] 0.5 One import environment for every command (F-30)

- **Input:** `matrix/evidence/plugin-lib-order.txt`. The candidate mechanism: `cli_app` applies
  `cli_config.import_libs` (`_cli/main.py:300`), while project boots apply
  `effective[IMPORT_LIBS.key]` (`:1250`, `:1405`).
- **[F]:**
  - `src/functualize/_cli/main.py`;
  - `tests/cli/test_plugin_import_environment.py` (new).
- **Work:** confirm the mechanism with the repro, then make the builtin path add the same convention
  directories before plugins load.
- **Gate/evidence:** the new test runs the `plugin-lib-order.txt` repro in a subprocess for
  `func h1`, `--help`, `mcp schema`, `builtin info schema` and `builtin shell-init bash`. All 5 must
  show the provider registered. Today 2 of 5 print `registration failed`.
- **Execute evidence (2026-11-22):** the new test failed 2 of 5 paths before the fix (both
  builtins), then all 5 passed. With the builtin import-libraries call temporarily removed after
  commit, the same 2 builtin paths failed again; restored. `uv run pytest
  tests/cli/test_plugin_import_environment.py tests/cli/test_import_libs.py
  tests/cli/test_convention_dirs.py` → 24 passed.
- **Depends on:** none.

## Wave 1 — the classifier

### [x] 1.1 `build_contract`

- **Input:** `spec.md` B-1 to B-8 and B-14 (B-2 *revised in Execute*); `contracts.md` §1;
  `schema.md` (invariant 1, `admit`); task 0.1 types; task 0.3 table; `matrix/table_diff.py`,
  `table-corrections.txt`.
- **[F]:**
  - `src/functualize/_primitives/parameter_contract.py` (new);
  - `tests/primitives/test_build_contract.py` (new);
  - `tests/_support/parameter_matrix.py` (the table correction below; added 2026-11-22).
- **Work:**
  - Classify from `resolved_hints()` and the markers. The capability names come from
    `_primitives/capability_names.py:49`; also `Provide`, `FromJob` and `Secret`.
  - **Never** consult a DI registry (F-21).
  - Produce `json_schema` from `TypeAdapter(...).json_schema()` of the declared shape (D4).
  - Produce `reject_reason` text in the §5.7 shape.
  - Admit `timedelta` as an ISO 8601 duration.
  - **`admit(contract, has_provider)`** (`schema.md` invariant 1), in the same module. It is pure:
    `has_provider(provider_type: str, qualifier: str | None) -> bool` is passed in, and nothing from
    `_primitives/di.py` is imported.
    - `build_contract` fills `Injection.provider_type`, the declared type's qualified name, for
      `Provide("q")` **and** for an unmarked class. It fills `qualifier` for `Provide("q")`.
  - **Correct the table** (`tests/_support/parameter_matrix.py`) to `report.proposed()`. Set each
    row's raw cells, which `_surface_expectations` expands to the nine surfaces:

    | row | `expected_verdict` = `proposed` | `cli_spelling` | `wire_spelling` | `required` | `delivered_type` |
    | --- | --- | --- | --- | --- | --- |
    | C081 | `INVOCATION_ONLY` | `()` | `("p",)` | `True` | `"tuple"` |
    | C082 | `INVOCATION_ONLY` | `()` | `("p",)` | `True` | `"dict"` |
    | C083 | `INVOCATION_ONLY` | `()` | `("p",)` | `False` | `"dict"` |
    | C084 | `INVOCATION_ONLY` | `()` | `("p",)` | `True` | `"set"` |
    | D105 | `REJECTED_DISCOVERY` | `()` | `()` | `False` | `None` |
    | F150, F151 | `REJECTED_DISCOVERY` | `()` | `()` | `False` | `None` |
    | H165 | `REJECTED_DISCOVERY` | `()` | `()` | `True` | `None` |
    | E138, E139 | `REJECTED_DISCOVERY` (only the `proposed` text changes) | unchanged | unchanged | unchanged | unchanged |

    - An `INVOCATION_ONLY` row has no spelling on help, bash, zsh, SmartBar or TUI, and is a supplied
      input on info, MCP, HTTP and Lambda (B-5, B-15).
    - Add `PROVIDERS = frozenset({("provlib.ProvWidget", None), ("provlib.ProvWidget", "w")})`: the
      registry the matrix project boots with (`matrix/plugin_probe.py`; `report.MATRIX_PROVIDERS`).
    - Add a per-row `declared_verdict`, the verdict before `admit`. It is `INJECTED` for C085, C086,
      C087, E138, E139 and H162–H166, and equals `expected_verdict` everywhere else.
- **Invariant:** one verdict per parameter. PEP 563 makes no difference (E142, F-32). Under the
  ~500-LOC cap.
- **Gate/evidence:**
  - `python3 .spec/features/parameter-contract/matrix/table_diff.py` → no rows, exit 0 (today 10
    rows, exit 1);
  - `uv run pytest tests/primitives/test_build_contract.py` passes for every row of the table in
    both annotation modes:
    - `build_contract(row).verdict == declared_verdict`, with no registry anywhere in the test;
    - `admit(build_contract(row), has_provider=PROVIDERS)` gives `expected_verdict`;
    - **F-21/UC-6 property:** with `("builtins.str", "s2")` added to the providers, H165 becomes
      `INJECTED` and every other row's verdict is unchanged;
  - `wc -l src/functualize/_primitives/parameter_contract.py` ≤ 500;
  - `lint-imports` "Primitives import nothing internal" KEPT.
- **Execute finding (2026-11-22):** implementation paused before code. `spec.md` B-5 requires
  `INVOCATION_ONLY` for fixed tuples, `dict[str, T]`, and `set[T]`, while the pinned table expects
  `REJECTED_DISCOVERY` for C081–C084. Also, B-2 and this task forbid a DI registry lookup, but the
  table distinguishes E138/E139 and H162–H166 by whether providers are registered. A builder
  receiving only a declaration cannot reproduce those availability-dependent verdicts. The
  every-row gate needs a designer correction; no row or requirement was silently reinterpreted.
- **Designer correction (2026-11-22):**
  - The table, not B-5, was wrong for C081–C084.
  - B-2 is narrowed, in the page's own terms, to one availability rule (`spec.md` B-2), applied by
    `admit` against an explicit provider set. The builder still reads no registry.
  - E139 (`Provide("s")`) and H165 (`Provide("s2")`) are different qualifiers. In the matrix
    registry neither has a provider, so both are `REJECTED_DISCOVERY`; the old table's `INJECTED` for
    H165 assumed the `PC_STR_PROVIDER=1` experiment.
  - Ten rows are corrected in all (`table-corrections.txt`).
- **Execute evidence (2026-11-22):**
  - `python3 .spec/features/parameter-contract/matrix/table_diff.py` → `0 rows differ`, exit 0.
  - `uv run pytest tests/primitives/test_build_contract.py` → 1172 passed, 4 skipped. Every row passes
    `declared_verdict` (no registry in the test) and `admit(…, PROVIDERS)` → `expected_verdict` in both
    annotation modes. Contracts are equal across the two modes for 165 rows. The skips are E142 in
    eager mode: there `FromJob[...]` raises `TypeError` when the module imports, which the test
    asserts before skipping; under PEP 563 the builder refuses it. The F-21 property holds: adding
    `("builtins.str", "s2")` moves exactly one contract in the table, H165 `p`, to `INJECTED`.
  - `wc -l src/functualize/_primitives/parameter_contract.py` → 499. `lint-imports` → 7 kept, 0
    broken. `mypy src/`, `ruff check`, `ruff format --check` clean.
  - Wave tier (`tests/primitives/ tests/types/ tests/spec/` and the isolation/hygiene modules) →
    2321 passed, 10 skipped. The step mapper exits 3 because `tests/_support/` changed. Its only
    importer is the new test (`rg -l parameter_matrix` outside `.spec/`: 1 file).
  - **Not yet reachable, disclosed.** No production code calls the module yet. It carries
    `# TRANSITIONAL(parameter-contract/2.1)`. Its first production path is task 2.1:
    `func <job>` → `DirectoryScanProvider` → `extract_parameters_from_signature` →
    `build_contracts`, then `admit` at boot. Task 2.2 adds `build_field_contract`. The sabotage
    below proves the gate is not vacuous; it does not prove wiring.
  - **Sabotage, after committing the change (before this evidence was amended in):** `admit`'s provider check was replaced by `or True` (admit
    everything). The gate went red: 18 failed, 1154 passed. The failures were the 7 provider rows
    C085, C086, C087, E138, E139, H165 and H166 in both modes, the F-21 property in both modes, the
    exact-pair test and the reason test. `git checkout --` restored the file, and the tree was clean.
  - **Decisions inside B-1 to B-8, for the reviewer:**
    - A config-model or `GroupOptions` parameter is `INJECTED` with an empty `Injection()`: the
      engine fills it, and its fields get their own contracts.
    - `*args`, `**kwargs`, `self` and `cls` are skipped, as the engine skips them.
    - An unannotated parameter is `str` (C090, C091).
    - `Literal[...]` is an `ENUM` scalar.
    - `Annotated[Iterator[T], Stdin()]` stays a flag, keeping `stdin_reader`'s streaming form.
    - A config field accepts the B-3 scalars, `Secret[str]`, and `list`/`tuple` of a scalar. It
      refuses `dict`, `set`, fixed tuples and models (F-29).
    - A secret default is never encoded into `default_json`.
- **Depends on:** 0.1, 0.3.

### [x] 1.2 The SQLite substrate stores `invalid`: revision 6, and a runner that can rebuild a table safely

- **Input:**
  - `plan.md` § *The substrate status set*;
  - `matrix/evidence/rev6-experiment.txt`, `matrix/evidence/plugin-suites-21c4bb81.txt`,
    `matrix/evidence/substrate-version-pins.txt`;
  - `contributor/reference/runtime-persistence-data-model.md` §1.2 (the run machine is `RunStatus`
    "adopted as-is") and §7 (migration discipline).
- **[F]** (all under `plugins/substrates/functualize-substrate-sqlite/` unless stated):
  - `src/functualize_substrate_sqlite/_schema/0006_run_status_invalid.sql` (new);
  - `src/functualize_substrate_sqlite/_migrations.py`;
  - `src/functualize_substrate_sqlite/_driver.py`;
  - `src/functualize_substrate_sqlite/_legacy_source.py`;
  - `tests/test_migrations.py`, `tests/test_runtime_store.py`, `tests/test_gate_interactions_sql.py`,
    `tests/test_legacy_import.py`, `tests/test_driver.py`;
  - `tests/test_plugin_selection.py` (added 2026-11-22, scope repair: its `:125` pins the head
    revision, `[(5,)]` → `[(6,)]`);
  - `tests/conformance/sqlite_hooks.py` (repository root; head revision pin);
  - `tests/substrate_probe/tier_a.py` (repository root; minimum batch-only driver probe);
  - `contributor/reference/runtime-persistence-data-model.md` (repository root).
- **Work, the recipe** (`plan.md` § *The substrate status set*):
  - **Revision 6, `0006_run_status_invalid.sql`, contains, in order:**
    1. `DROP TRIGGER run_tags_fixed_on_delete`. Its body names `runs`, and modern SQLite refuses the
       rename in step 5 while it exists: `error in trigger run_tags_fixed_on_delete: no such table:
       main.runs` (measured).
    2. `CREATE TABLE runs_rebuild (…)`, identical to `0001`'s `runs` except that the status `CHECK`
       adds `'invalid'`.
    3. `INSERT INTO runs_rebuild SELECT … FROM runs`, naming every column.
    4. `DROP TABLE runs`.
    5. `ALTER TABLE runs_rebuild RENAME TO runs`.
    6. The four `runs_*` indexes, recreated with `0001`'s exact text.
    7. `run_tags_fixed_on_delete`, recreated with `0005`'s exact text.
  - **The revision is applied with foreign keys off.** This is the measured reason: with them on, the
    same SQL applies **without error** and silently cascades away every `run_attempts`,
    `run_events`, `artifact_refs` and `run_tags` row. `foreign_key_check` and `integrity_check` then
    report clean, because the children are gone (`rev6-experiment.txt`).
    - `PRAGMA foreign_keys` is a no-op inside a transaction, so the runner sets it **outside** the
      revision's batch. A revision declares the need with a first-line marker,
      `-- migration: foreign-keys-off` (spelling provisional).
    - The driver gets one capability for it, as a separate protocol checked by the runner, not a
      new `SqlDriver` member (`_driver.py:72`). `LocalSqliteDriver` (`_driver.py:90`) is the only
      implementation. A driver without the capability gets `MigrationRefused` for such a revision,
      never a silent foreign-keys-on apply. `tests/conformance/sqlite_hooks.py`'s `_FaultingDriver`
      wraps a store's driver after migration and is unaffected.
    - After the batch, the runner runs `PRAGMA foreign_key_check`, restores `foreign_keys=ON`, and on
      any violation raises `MigrationRefused` with repair steps (restore from a backup).
  - **The partial-state check** (`_check_objects`) subtracts the names a revision renames away
    (`ALTER TABLE <x> RENAME TO <y>` ⇒ `<x>` is not expected on disk). Otherwise the next boot
    refuses, because `_CREATED` finds `runs_rebuild` (measured).
  - **`SHIPPED_MIGRATIONS`** gains `_load(6, "run_status_invalid")`. `0001`–`0005` stay
    byte-identical, so their checksums still match every existing ledger.
  - **The legacy import map** `_ATTEMPT_FOR_RUN` gains `"invalid": "failed"`, following the
    precedent `"refused": "failed"`: nothing ran in either case.
  - **The data-model doc.** §7 names revisions `0001` → `0006` and the foreign-keys-off rule. Its
    stale "empty → `0004`" sentences are corrected to the shipped state.
- **Version pins that move, in this task's tests** (census `substrate-version-pins.txt`, 13 hits):
  - `migrate(driver) == 5` becomes `== 6` at `test_migrations.py:85,157,217,278,390,438` and
    `test_gate_interactions_sql.py:182`;
  - the test names at `test_migrations.py:82` and `test_runtime_store.py:51` (and that test's
    `[(5,)]`) name version 6 and six ledger rows;
  - `test_migrations.py:430` (revision 5 additive, revision 4 a rollback target) and `:441`/`:449`
    (an applied revision 5 whose table is gone) keep testing revision 5, from a ledger stopped at
    5; only their "migrate to head" expectations move to 6;
  - the remaining two hits are not version pins and stay: `test_readers.py:294` (a count of views),
    `test_import_cli.py:120` (an exit code);
  - the data-model doc's stale "empty → `0004`" (`runtime-persistence-data-model.md:574,589`) is
    corrected in the same task.
- **Tests to add** (the doc's "start from every supported historical schema"):
  - empty → 6, with six ledger rows;
  - a **populated** revision-5 database → 6, with every run, attempt, event, artifact reference and
    tag preserved, compared row for row. This is the regression test for the cascade trap;
  - `invalid` insertable after 6, and `run_tags` triggers still firing;
  - a revision-6 database whose `runs` lacks `invalid` in its `CHECK` refused as partial state;
  - `_check_objects` accepting a rename;
  - the legacy import of an `invalid` run.
- **Rollback consequence (stated, not hidden):** revision 5 is no longer a rollback target. A
  revision-5 build meeting a revision-6 database refuses at boot ("ledger ahead of the shipped set",
  today's rule). `CHANGELOG.md` (task 11.1) records it.
- **Gate/evidence:**
  - `uv run pytest plugins/substrates/functualize-substrate-sqlite/tests` (its own invocation) →
    green, including `test_each_status_check_equals_its_machines_state_set[runs-machine1]`, red today;
  - `git diff 21c4bb81 -- plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/000[1-5]*.sql`
    → empty;
  - `rg -n '\[\(5,\)\]' plugins/substrates/functualize-substrate-sqlite/tests` → exactly one hit,
    `test_migrations.py:554`. That is the deliberate one: a driver without the capability is refused
    and its ledger stays at 5. `test_plugin_selection.py:125` must no longer appear;
  - the plugin-package loop (wave barrier) → all green.
- **Scope repair (2026-11-22, designer):** `tests/test_plugin_selection.py` joins `[F]`. A sweep of
  every substrate test and the root suite found no other head-revision pin
  (`matrix/evidence/substrate-revision-pins-b5f588bc.txt`):
  - every `migrate(driver) == 6` and every `[(6,)]` is already moved;
  - the `== 5`/`== 4`/`== 2`/`== 1` hits are prefix migrations `SHIPPED_MIGRATIONS[:n]`, which
    stay;
  - `test_readers.py:294` and `test_import_cli.py:120` are not revisions;
  - `tests/conformance/sqlite_hooks.py:221` reads `max(version)` without pinning a number.
- **Execute repair (2026-11-22):** the later root-suite sweep found another head pin at
  `tests/conformance/sqlite_hooks.py:143`, now 6; its other version reads are derived from
  `latest_version` or `max(version)`. The batch-only substrate probe keeps its minimum driver
  interface and migrates only through revision 5. The test asserts that the same driver refuses
  revision 6 with `MigrationRefused`, leaving its ledger at 5. `uv run pytest tests/conformance
  tests/substrate_probe -q` → 120 passed, 7 skipped; the separate substrate package gate →
  230 passed. The reopened task is ticked against these results.

  The dispatched glob `plugins/substrates/*/*/tests` matches nothing (the evidence shows the `rg`
  error), so the sweep used `plugins/substrates/*/tests`.
- **Execute finding (2026-11-22):** revision 6 and its runner, driver, legacy map, tests and §7
  documentation are committed, but the package gate is `227 passed, 3 failed`: all three variants
  of `test_sqlite_configured_selects_the_sqlite_store_migrated` in
  `tests/test_plugin_selection.py:125` still pin `[(5,)]`. That file is outside this task's `[F]`.
  Scope repair must add it and move the current-version assertion to 6 before this box is ticked.
  The populated-database test failed under post-commit sabotage that omitted the FK-off scope:
  attempts, events, artifact references and tags were all deleted; the runner was restored.
- **Execute evidence, scope repair applied (2026-11-22):**
  - `tests/test_plugin_selection.py:125` moved from `[(5,)]` to `[(6,)]`. That is the only edit in this
    commit. Revision 6, the runner, the driver capability, the legacy map and §7 are unchanged since
    the first attempt. They were re-read against the recipe: the trigger is dropped before the rename;
    all 11 `runs` columns are copied by name; the four `runs_*` indexes and `0005`'s trigger are
    recreated verbatim; `foreign_key_check` runs before foreign keys are back on; and
    `_check_objects` subtracts renamed-away names.
  - `uv run pytest plugins/substrates/functualize-substrate-sqlite/tests -q` (its own invocation) →
    230 passed. The run includes `test_each_status_check_equals_its_machines_state_set[runs-machine1]`
    (confirmed with `--co`).
  - `git diff 21c4bb81 -- …/_schema/000[1-5]*.sql` and `git diff 77ea0292 -- …/_schema/000[1-5]*.sql`
    are both empty.
  - `rg -n '\[\(5,\)\]' plugins/substrates/functualize-substrate-sqlite/tests` → exactly one hit,
    `test_migrations.py:554`.
  - Wave barrier, each package in its own invocation: 12 of 12 green. The counts are flow-viz 25,
    http 63, inline 50, lambda 59, mcp 33, secrets-aws 72 (+1 skipped), secrets-bitwarden 125
    (+1 skipped), ai-pydantic 27, ai 22, tasks-local 15, tasks 15, and substrate-sqlite 230.
  - **Reachability:** `boot(project, "sqlite:")` → `SqliteRuntimeStore` → `migrate(driver)` →
    `_apply` applies revision 6. `test_sqlite_configured_selects_the_sqlite_store_migrated` observes
    it through the public boot, as ledger head 6.
  - **Sabotage, after committing the change (before this evidence was amended in):**
    `_load(6, "run_status_invalid")` was removed from `SHIPPED_MIGRATIONS`. All three boot variants of
    that test failed: `boot_static`, `func-cold` and `func-warm` (3 failed, 16 passed). `git checkout --`
    restored the file, and the tree was clean.
- **Depends on:** 0.2 (`RunStatus.INVALID`, committed in `7a610a7d`).

## Wave 2 — discovery writes contracts; the binder exists

**Barrier audit (2026-11-22).** The root suite's 976 test files were assigned exactly once to
three bounded `uv run pytest -q -n auto` chunks and eight single-file chunks. Those eight files
import a temporary module named `_group`; collecting them with other root files can reuse an
earlier fixture's module and produce false import failures, so each ran in its own process. Final
root totals after the 2.1 scope repair: 16,321 passed, 1,726 skipped, **0 failed**. Chunk 2 was
rerun with its original 323-file manifest; the other ten chunks stand on `23b56c5d` because the
repair changed only two CLI assertions and this task record. The plugin loop was green: 12
packages, 736 passed, 2 skipped. Wave 2 is complete.

### [x] 2.1 Signature parameters get contracts; refusals are reported, not fatal

- **Input:** 1.1. ADR-018's `UnsatisfiableParameter` is at `_app/boot.py` (`gates-authoring.txt`
  `unsatisfiable`: 1 hit).
- **[F]:**
  - `src/functualize/_discovery/providers.py`;
  - `src/functualize/_discovery/registry.py`;
  - `src/functualize/_app/boot.py`;
  - `tests/discovery/test_contract_discovery.py` (new).
  - `tests/app/test_eager_boot_provider.py` (scope repair: single provider report);
  - `tests/integration/test_lazy_true_engine_materialization.py` (same, cold and warm);
  - `tests/cli/test_parameter_types.py` (scope repair: CLI single-report assertion).
- **Work:**
  - `extract_parameters_from_signature` sets `contract` on every parameter it emits, and
    `type_annotation` keeps today's value until wave 9, and new readers read `contract.display`
    (SS-3 = B).
  - `JobRegistry._extract_descriptors_from_module` (`registry.py:359-551`) does the same, so library
    mode agrees (plan R-5).
  - A `REJECTED_DISCOVERY` parameter records `DiscoveryFailure(error_type="UnsupportedParameter")`
    and a boot warning. The job stays registered (DC-1 = B).
  - **Availability (spec B-2, added 2026-11-22).** After plugins register their providers, boot
    passes every `INJECTED` contract through `admit`.
    - The predicate is built from `app.di`'s **exact** `(type, qualifier)` entries, keyed by the
      type's qualified name. Use `available_types()` / `available_qualifiers()`, not
      `DIRegistry.has(T)`: that call answers true for a type registered only under other qualifiers,
      which `resolve` refuses as ambiguous.
    - Do this on cold **and** warm boots, from the descriptor's contract, not the live function.
      `validate_di_bindings` skips lazy entries, which is F-33.
    - A `REJECTED_DISCOVERY` result is reported like any other. The cached descriptor keeps the
      contract **before** `admit`.
- **Invariant:** cold and warm descriptors compare equal.
- **Gate/evidence:** `uv run pytest tests/discovery/test_contract_discovery.py tests/discovery/test_discovery_failures.py tests/integration/test_warm_cold_boot.py`. The new test boots each table row cold and warm in a subprocess.
- **Reachability:** `func <job>` → `DirectoryScanProvider` → `extract_parameters_from_signature`.
- **Execute finding (2026-11-22): PARTIAL, left `[ ]`.** The code is committed and its own gate is
  green, but it reddens three tests outside `[F]`. Scope repair and one designer decision are needed.
  - **What landed.**
    - `extract_parameters_from_signature` sets `contract` on every parameter it emits.
      `JobRegistry._extract_descriptors_from_module` calls it (`registry.py:522`), so library mode
      needed no edit.
    - `report_unsupported_parameters` runs on both boot paths (`boot.py`), after
      `report_unsatisfiable_jobs` and before the registry freezes. It builds an exact
      `(qualified name, qualifier)` set from `available_types()` / `available_qualifiers()`, applies
      `admit` to each descriptor contract, and keeps the result in `app._admitted_contracts`
      (`# TRANSITIONAL(parameter-contract/5.1)`). It reports each refusal as `UnsupportedParameter`
      with a warning. The descriptor and the cache keep the contract from before `admit`.
  - **Gate:** `uv run pytest tests/discovery/test_contract_discovery.py tests/discovery/test_discovery_failures.py tests/integration/test_warm_cold_boot.py`
    → 676 passed, 2 skipped. The new test boots the whole table as one project through the real
    `func`, in a subprocess, cold and then warm, in both annotation modes. Every row's declared and
    admitted verdicts match the table. Cold and warm contracts are equal, and the warm boot is
    proven lazy. Every refusal is reported with its file and job, and appears in stderr. A
    qualified-only provider (`QOnly` under `"x"`) does not satisfy a bare `p: QOnly`. The cache holds
    no `admit` result. Library mode (`FunctualizeApp(job_sources=…)`) admits identically.
  - **Sabotage, after committing the change (before this evidence was amended in):**
    - Replacing both `report_unsupported_parameters(app)` calls with `pass` failed 493 of the new
      test's cases.
    - Replacing the exact-pair predicate with a type-only match, `DIRegistry.has`'s behaviour,
      failed H166 on both boots and both modes and the `QOnly` test (6 failed).
    - Each was restored with `git checkout --`, and the tree was clean.
  - **Follow-up commit (still 2.1's `[F]`, `boot.py`):** the boot report also walks
    `descriptor.config_fields`, so the config-field refusals 2.2 creates (F150, F151) are reported on
    both boots. Each name is decided once, because a convention job's `config_fields` are its
    `parameters`. 2.2's test exercises this walk. Group fields live in `GroupOptionsSpec`, not on a
    job descriptor, and are not walked: no table row refuses a group field.
  - **Not emitted, so no contract.** Capability and `FromJob` parameters are kept off `parameters`, as
    before (30 capability rows, plus E140 and E141). Their descriptors carry no contract for them.
    5.1, which "reads `contract.verdict`", must classify them from the live function, or a task must
    start emitting them.
  - **Decided 2026-11-23 (designer):** neither. Their contracts go on the descriptor, in
    `JobDescriptor.omitted_contracts`, through new task 3.2 (`plan.md` § *The contract gap*). The
    single-report ruling is now in `spec.md` B-9, which names the three surviving
    `UnsatisfiableParameter` cases.
  - **The conflict (resolved by scope repair).** A missing provider was reported twice on a cold
    boot: ADR-018's `UnsatisfiableParameter` from `validate_di_bindings`, and the new
    `UnsupportedParameter`. A warm boot reports only the new one; the old check skips lazy entries
    (F-33). Three tests outside `[F]` pin exactly one report:
    - `tests/app/test_eager_boot_provider.py::TestTheBootTimePromisesSurvive::test_a_di_error_is_still_found_at_construction`
      (`assert len(messages) == 1`);
    - `tests/integration/test_lazy_true_engine_materialization.py::TestDeferredDiValidation::test_cold_boot_still_validates_at_boot`
      and `::test_lazy_false_escape_hatch_validates_at_boot` (`== ['UnsatisfiableParameter']`).

    All three pass at `7a7b9124` and fail with this change. The plan says "next to ADR-018's
    `UnsatisfiableParameter`" but does not say what happens when both fire. B-2 ("the only registry
    input to any verdict") and 5.1 ("no second availability check") point to retiring the old report
    for parameters a contract covers. That also matches the old message's remedy, "annotate with
    Arg()/Option()", which B-8 now refuses for an unconvertible class (D105). Either answer needs
    those three files in `[F]`.
- **Execute repair:** `report_unsupported_parameters` now runs before the legacy validator and is
  the sole availability report for a contract-covered parameter on cold and warm boots. The old
  `UnsatisfiableParameter` report survives for DI errors without a descriptor contract: directly
  registered functions and factory-resolution failures, plus any uncovered binding the legacy
  validator finds. The legacy remedy no longer suggests `Arg()/Option()` for an unconvertible
  class (D105). The three scope-repaired tests assert one `UnsupportedParameter` with source file,
  job, parameter and provider-registration remedy. Targeted gate: 4 passed; 2.1 gate: 676 passed,
  2 skipped. Import, type and format gates pass. After committing, removing the covered-parameter
  filter failed all three single-report tests; the committed filter was restored.
- **Reopened by the whole-root barrier:** `tests/cli/test_parameter_types.py` pins the retired
  report type in two surface variants. The approved single-report decision applies to this
  contract-covered dependency. The file was outside `[F]`, so the box remained open until scope
  repair added it and the repaired gate and root barrier passed.
- **Scope repair closed (2026-11-22):** both CLI variants now assert exactly one
  `UnsupportedParameter` report, including the source file, `deploy`, `db`, and the provider
  registration remedy. `uv run pytest tests/cli/test_parameter_types.py -q` → 42 passed;
  `uv run pytest tests/cli tests/app tests/integration -q -n auto` → 2836 passed, 474 skipped;
  `uv run pytest tests/discovery/test_contract_discovery.py -q` → 627 passed, 2 skipped.
  Root chunk 2, using the unchanged 323-file manifest, → 5310 passed, 487 skipped (previously
  5308 passed, 487 skipped, 2 failed). The other ten root chunks stand on `23b56c5d`: this repair
  changes only the two CLI assertions and this task record; it changes no production code, test
  imports, or other test files. The prior plugin loop also stands for the same reason.
- **Depends on:** 1.1.

### [x] 2.2 Config and group fields get contracts; the config-type refusal runs (F-29)

- **Input:** 1.1. `validate_job_config_types` executed 0 of 42 statements under `func`
  (`cov_census.txt`).
- **[F]:**
  - `src/functualize/_discovery/schema_extractor.py`;
  - `src/functualize/_discovery/group_options_extractor.py`;
  - `tests/discovery/test_config_field_contracts.py` (new).
- **Work:**
  - `extract_field_descriptors` and `extract_group_options_fields` attach contracts.
  - An unsupported config field type (`dict`, nested model) becomes a `REJECTED_DISCOVERY` contract
    on every boot path.
- **Gate/evidence:** `uv run pytest tests/discovery/test_config_field_contracts.py tests/group_options/test_group_options_discovery.py`. Rows F150 and F151 are reported, not run.
- **Execute evidence (2026-11-22):**
  - `extract_field_descriptors` gives each config field `build_field_contract` (`CONFIG_FIELD`, or a
    refusal for `dict` and nested models). `extract_group_options_fields` replaces it with the
    group-level `ACCEPTED_FLAG` contract.
  - The refusal is reported through 2.1's boot step. That step walks `config_fields` since the 2.1
    follow-up commit, and it is the one place that decides availability. `validate_job_config_types`
    (`_config/job_config.py`, outside `[F]`) is not wired: the contract is now the refusal, on every
    boot path.
  - Gate → 48 passed. F143–F152 get their verdicts in both annotation modes; G160 and G161 are
    group-level flags. Field contracts survive the cache codec. Through the real `func builtin info
    --json`, cold and then warm, F150 and F151 each appear exactly once as `UnsupportedParameter`
    naming their file, with the warning on stderr. No other config row is reported, and both jobs
    stay listed. The test never runs them; the door that refuses a run is 5.1.
  - **Found by the existing suite, fixed in scope:**
    `tests/config/test_descriptor_cache_fidelity.py::…::test_a_secret_default_is_never_written_to_the_cache`.
    A plain `str` field marked `json_schema_extra={"secret": True}` had its default encoded into
    `contract.default_json`, and from there into the cache. The classifier sees only the `Secret`
    type. Both extractors now drop a secret-marked default from the contract
    (`schema_extractor.without_secret_default`), and a new test covers config and group fields. For
    the reviewer: `build_field_contract` itself cannot see `json_schema_extra`, so any future caller
    must apply the same rule.
  - Wave tier: `tests/discovery tests/group_options tests/config tests/app tests/integration
    tests/core tests/tui_group_options` → 4159 passed. The only failures are 2.1's three known
    double-report tests. `tests/_cli tests/cli` → 3306 passed.
  - **Reachability:** `func <job>` → `CachedDirectoryScanProvider` → descriptor `config_fields` via
    `extract_field_descriptors` → `report_unsupported_parameters` at boot.
  - **Sabotage, after committing the change (before this evidence was amended in):**
    - `contract=None` in `extract_field_descriptors` failed 23 of 39.
    - Walking only `descriptor.parameters` at boot (reverting the 2.1 follow-up) failed the cold/warm
      `func` report test.
    - Each was restored with `git checkout --`, and the tree was clean.
- **Depends on:** 1.1.

### [x] 2.3 `bind`

- **Input:** `schema.md` § *Binding*; `spec.md` B-23 to B-26; 1.1.
- **[F]:**
  - `src/functualize/_primitives/argument_binding.py` (new);
  - `tests/primitives/test_argument_binding.py` (new).
- **Work:**
  - Refuse unknown keys, injected keys, missing required arguments and non-converting values with
    `BindRefusal(argument, reason)`.
  - Apply defaults from `default_json`.
  - Convert with a `TypeAdapter` built from the live annotation and cached on the binder instance
    (not module state), honouring `Field()` constraints (subsumes `ArgValidator`).
- **Gate/evidence:** `uv run pytest tests/primitives/test_argument_binding.py`. Record the in-process
  timing as `matrix/binder_cost.py` measures it; at authoring time it was ~18 µs per call for 15
  arguments.
- **Execute evidence (2026-11-22):**
  - `ArgumentBinder.bind(function, contracts, raw, *, surface)` in
    `_primitives/argument_binding.py`. It refuses unknown keys, injected keys, config-field keys,
    missing required arguments, non-converting values, and any call to a job holding a
    `REJECTED_DISCOVERY` contract (DC-1 = B). Each refusal is `BindRefusal(argument, reason)`.
  - Defaults are decoded from `default_json`. `None` stays `None`. A default the adapter cannot
    decode falls back to the signature's own default.
  - Values are converted by a `TypeAdapter` of the live annotation, cached per `(function, name)` on
    the instance, so `Field(...)` holds.
  - On a command-line surface, a missing required `INVOCATION_ONLY` parameter reads "can only be
    supplied over MCP, HTTP or Lambda" (B-15).
  - Imports `_types`, `_primitives` and pydantic (lazily). `lint-imports` → 7 kept, 0 broken.
    `# TRANSITIONAL(parameter-contract/5.1)`: no production caller until the engine door.
  - Gate `uv run pytest tests/primitives/test_argument_binding.py` → 410 passed. Every
    caller-supplied row of the table, in both annotation modes, arrives as its declared type
    (`list` as `list`, `tuple` as `tuple`, `set`, `dict`, `Enum` member, `Path`, `UUID`, ISO
    `timedelta`). Absent, each gives its signature default, or a refusal naming it when required.
    Also tested: the B-24 cross-surface identity, the refusals one by one, and `Field(ge=1)`.
  - **Timing** (load average 3–4, three runs each).
    - `binder_cost.py` as authored: bind median 16.9 / 17.4 / 19.1 µs, and adapter build 85–97 µs per
      parameter.
    - The same 15-argument signature through `ArgumentBinder.bind`: first call 3.3–5.1 ms (it builds
      the 15 adapters), then median 40.4–41.7 µs per call over 2000 calls.
    - The difference from the bare adapters is the binder's contract walk and refusal checks. This is
      the in-process number 5.1 reads (`scratch` script; not kept in the repo).
  - **Sabotage, after committing the change (before this evidence was amended in):** `_convert`
    returned the raw value without converting it. 132 failed, 278 passed. `git checkout --`
    restored the file, and the tree was clean.
- **Depends on:** 1.1.

## Wave 3 — the one click renderer

### [x] 3.1 `render_click_params(contracts)` for every click command

- **Input:**
  - 2.1 and 2.2;
  - `serena find_referencing_symbols`: `build_click_params` (3 production callers: `click_params.py:1416`, `:1530`, `:1571`);
  - `build_click_params_from_fields` (production callers: `_cli/main.py:898`, `_cli/completions/data.py:73,87`, `_cli/tui/smart_bar_autocomplete.py:320`, `app/adapters/cli.py:442`, `click_params.py:287`).
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `src/functualize/app/adapters/lazy_command.py`;
  - `src/functualize/app/adapters/cli.py`;
  - `tests/adapters/test_render_click_params.py` (new);
  - `tests/cli/test_parameter_types.py` (scope repair, 2026-11-23: routing the CLI through
    contracts refuses `Annotated[Widget, Option()]` (B-8, D105), and four of its assertions encoded
    the retired acceptance).
- **Work:**
  - One renderer from contracts for the live job command, the warm lazy command, plugin command
    callbacks (contracts built on the fly) and group options.
  - Never pass `default=None` with `required=True` (F-07; click 8.4.1, `f07-click.txt`).
  - Parse `timedelta` as ISO 8601 (F-05), and leave already-typed defaults alone (F-04).
  - Repeatable options for `list[T]` and `tuple[T, ...]`.
  - A choice is spelled `str(value)`, never `enum_values` taken as strings. After 4.4 an `int` set
    holds `int`s (`spec.md` B-3, *choice sets*); before it they are already strings, so `str()`
    changes nothing.
  - **The `Enum` bridge (added 2026-11-23, Execute finding).** Where the factory holds a live
    function (`create_job_click_command(name, function, …)`, `click_params.py:1382-1385`), an `ENUM`
    shape whose live annotation is an `Enum` class renders through the existing `_EnumChoice`
    (`click_params.py:112-167`). Its enum type is taken from that function. It is marked
    `# TRANSITIONAL(parameter-contract/5.1)`.
    - **This is the only place a click parameter converts a token.** The contract describes shapes
      and values and deliberately carries no Python type (`schema.md`, *Type identity*), so turning
      `'red'` into `Color.RED` needs a live class. 5.1's binder owns that conversion from wave 5 and
      deletes this branch.
    - **Every other shape renders from the contract alone.** That includes a `Literal` choice set,
      whose value is its own value and needs no class.
    - **The descriptor-only lazy command** (`app.cli` with a lazy entry, `cli.py:407` →
      `make_lazy_command`) has no live function. It renders the contract's plain choice, as it
      renders `click.Choice(field.choices)` today (`click_params.py:272-273`). Member conversion
      on that path arrives with 5.1.
    - Measured on `0d0deb46` (`enum-bridge-0d0deb46.txt`): `func <job>` builds its command through
      `create_job_click_command` with the live function on **cold and warm** boots, and
      `_EnumChoice` converts `'red'` → `Color.RED` on both.
  - Refuse two CLI markers at discovery, not here (F-16 via 1.1).
  - Keep `build_click_params`, `build_click_params_from_fields` and
    `build_click_params_from_descriptor` as delegating wrappers marked `# TRANSITIONAL(7.3)`, so
    their existing callers and tests keep working until wave 7.
- **Invariant:** the cold and the warm command for one job are built by the same function from equal
  contracts.
- **Gate/evidence:** `uv run pytest tests/adapters/ tests/cli/test_option_marker_unit.py tests/cli/test_arg_marker_unit.py`.
  - `uv run pytest tests/cli/test_enum_parameter_roundtrip.py -q` → 5 passed, 2 skipped, the same as
    on `0d0deb46` (`enum-bridge-0d0deb46.txt`). The contract-only experiment gave 2 failed
    (`body=str:'red'`), so the bridge cannot land by silently failing it.
  - `rg -n 'TRANSITIONAL\(parameter-contract/5\.1\)' src/functualize/app/adapters/click_params.py`
    → exactly 1 hit: the `ENUM` branch.
  - `uv run pytest tests/cli/test_parameter_types.py -q` (scope repair, 2026-11-23), including
    `TestAnExplicitMarkerNoLongerOutranksTheTypeList`.
  - Plus the kit:
  - `probes.sh`: no `Traceback` for timedelta;
  - `func d094`: exit 2, `Missing option '--p'`;
  - `func b053 --p a --p b`: `p=['a', 'b']` once 5.1 binds; `('a', 'b')` before 5.1 is acceptable
    and noted.
- **Reachability:** `func <job>` → `_cli/main._handle_job` → `create_job_click_command` → the
  renderer.
- **Execute evidence (2026-11-23):** `render_click_params` reads the stored verdict, shape and CLI
  spelling; the live `build_click_params` wrapper supplies contracts and the one temporary Enum
  class bridge. Cached fields and group options use the same renderer when their contracts are
  present; contractless field callers and the non-Click direct callable retain marked legacy
  adapters until 7.3. The descriptor-only lazy command remains on text for Enum values until 5.1.
  - `uv run pytest tests/adapters/ tests/cli/test_option_marker_unit.py tests/cli/test_arg_marker_unit.py -q`
    → 199 passed, 6 skipped. The new tests cover required `Option`, typed duration defaults,
    repeated list and tuple flags, cached spellings, group options and the live Enum bridge.
  - `uv run pytest tests/cli/test_enum_parameter_roundtrip.py -q` → 5 passed, 2 skipped;
    `rg -c 'TRANSITIONAL\(parameter-contract/5\.1\)' src/functualize/app/adapters/click_params.py`
    → 1.
  - The matrix `probes.sh` on the generated 166-row project: `a039 --p PT1H` exit 0 with a
    `timedelta`, `--p 3600` and `--p 1:00:00` exit 2 with a usage error, and no `Traceback`.
    Separate real `func` calls: `d094` exits 2 with `Missing option '--p'`;
    `b053 --p a --p b` delivers `('a', 'b')` before 5.1 (permitted intermediate shape).
  - `uv run mypy src/` → 425 source files clean; `uv run lint-imports` → 7 kept, 0 broken;
    Ruff check and format check pass on the touched files.
  - After committing, replacing the renderer's return with `[]` made
    `tests/cli/test_enum_parameter_roundtrip.py::test_the_cli_delivers_the_member[func]`
    fail with exit 2, `Got unexpected extra argument (red)`. The committed renderer was restored;
    the same test returned 1 passed, 1 skipped. This proves the real `func` command reaches the
    renderer, not only that the renderer's unit tests call it.
- **Review repair (2026-11-23):** The live config path now consumes
  `schema_extractor.extract_field_descriptors`' contracts. That extractor reads both `Secret[str]`
  and `json_schema_extra={"secret": True}` from the model JSON schema and removes secret defaults
  before caching; the live path no longer has a second secret rule. Two adapter cases compare live
  and cached option help as exact strings, retain a visible non-secret default, and invoke each
  job's Click `--help`. The real `func` test checks both markers on cold and warm boots. Before the
  repair, the schema-marked case leaked in both tests (2 failed); after it, the scoped gate
  `uv run pytest tests/adapters tests/discovery/test_config_field_contracts.py
  tests/cli/test_parameter_types.py -q` reports 239 passed, 8 skipped. The completed 2.1
  transition comments in `_primitives/parameter_contract.py` and `_types/descriptors.py` were
  retired: production discovery now calls the builder and populates the descriptor contract.
- **Completed at `6686cade`, not `69a95c99`** (corrected 2026-11-23). The tick at `69a95c99` stood
  on a gate that omitted `tests/cli/test_parameter_types.py`, a file the change itself broke:
  `TestAnExplicitMarkerOutranksTheTypeList` measured 4 passed at `8bd9bf45`, 4 failed at
  `69a95c99` and at `98d846d0`, and 4 passed at `6686cade`, renamed
  `TestAnExplicitMarkerNoLongerOutranksTheTypeList` (`spec.md` B-8, *the marker and a type nothing
  converts*).
- **Depends on:** 2.1, 2.2.

### [x] 3.2 Every signature parameter's contract reaches its descriptor, the omitted ones included

- **Input:**
  - `plan.md` § *The contract gap*;
  - `schema.md` invariant 6 and § *Cache encoding*;
  - `contract-gap-ea688446.txt`, `cache-version-pins-ea688446.txt`;
  - `spec.md` B-1, B-9 (*one report per parameter*);
  - 2.1's disclosure (*Not emitted, so no contract*).
- **[F]:**
  - `src/functualize/_types/descriptors.py`: `JobDescriptor.omitted_contracts` and its codec in
    `to_dict` / `from_dict`;
  - `src/functualize/_primitives/cache_format.py`: `CACHE_VERSION` 26 → 27;
  - `src/functualize/_discovery/providers.py`: `extract_signature`, and its three internal call sites;
  - `src/functualize/_discovery/registry.py`, `src/functualize/_discovery/sync.py`,
    `src/functualize/_app/impl.py`: the other four call sites;
  - `src/functualize/_app/boot.py`: `report_unsupported_parameters` and `contract_covers` read
    `omitted_contracts` too;
  - `tests/discovery/test_omitted_contracts.py` (new);
  - `tests/types/test_descriptor_owner_class.py` (`:40`, 26 → 27);
  - `tests/discovery/test_job_declaration_discovery.py` (`:169`, 26 → 27).
- **Work:**
  - **One function decides both halves.** The skip loop in `extract_parameters_from_signature`
    (`providers.py:104-135`) returns the `FieldDescriptor`s it emits **and** the contracts of the
    parameters it omits: capability types (`:122`), `FromJob` (`:118`) and a `GroupOptions`
    injection point (`:133`).
    - Each omitted contract is the one `_parameter_contracts` already built (`:104`). No
      classification is added.
    - The loop moves into a new `extract_signature(func)` (name provisional), which returns both
      halves.
    - All seven production call sites (`contract-gap-ea688446.txt`) call `extract_signature` and set
      `omitted_contracts` on the descriptor they build.
    - `extract_parameters_from_signature` stays as `extract_signature(func).parameters`: the
      parameters half, kept for the `_discovery` export and for 67 test references in 7 files.
      Renaming it would migrate those tests for no behaviour. Expect it to show as `TESTS_ONLY` in
      the dead-code delta.
  - **`JobDescriptor.omitted_contracts: tuple[ParameterContract, ...] = ()`.**
    - Encode it with 0.1's contract codec under `"omitted_contracts"`, in signature order.
    - Bump `CACHE_VERSION` to 27.
    - The two pins move. The poison literal `test_descriptor_owner_class.py:44` (`"version": 22`)
      stays.
  - **Boot.** `report_unsupported_parameters` walks `omitted_contracts` as well, so an omitted
    `REJECTED_DISCOVERY` is reported once (B-9). `contract_covers` counts them as covered.
    `admit` already leaves capability and `FromJob` contracts unchanged.
  - **Retire the stale survivor list** in `report_unsatisfiable_jobs`'s comment
    (`_app/boot.py:1879-1882`). Its "(for example, directly registered functions and
    factory-resolution errors)" contradicts B-9: `register_dynamic_job` keeps a descriptor with
    contracts (`_app/impl.py:820`, `:856`), so its parameters are covered. Replace the parenthetical
    with a pointer to B-9's three survivors:
    - a job with no retained descriptor;
    - the classifier-crash fallback;
    - a factory's missing dependency.
  - **No surface reads `omitted_contracts`.** Its only planned reader is 5.1.
- **Invariant:** for every descriptor with a live function:
  - the names of `parameters`' contracts and of `omitted_contracts` are disjoint;
  - their union equals `build_contracts(function)`'s names;
  - `parameters` and `config_fields` are unchanged.
- **Gate/evidence:**
  - `uv run pytest tests/discovery/test_omitted_contracts.py` covers every table row, cold and warm,
    in both annotation modes:
    - the disjoint-union invariant holds;
    - E108–E137 carry an `INJECTED` contract with `Injection.capability` set, and E140 and E141 with
      `Injection.from_job` set, all in `omitted_contracts`;
    - no capability or `FromJob` name appears in `parameters`;
    - the cold and warm `omitted_contracts` are equal;
    - **published surfaces are unchanged:** the click params and `job_input_schema` built from each
      descriptor equal those built from the same descriptor with `omitted_contracts=()`;
  - `rg -n 'extract_parameters_from_signature\(' src plugins` → 1, its own definition (today 8: the
    definition and seven production calls);
  - `rg -n 'extract_signature\(' src` → 9: the definition, the seven sites, and the
    `extract_parameters_from_signature` wrapper body `return extract_signature(func).parameters`
    that this Work prescribes (corrected 2026-11-23; measured 9 at `98d846d0`);
  - `rg -n 'directly registered functions' src` → 0 (today 1, `_app/boot.py:1881`);
  - `rg -n 'CACHE_VERSION\s*(==|!=|>=)\s*[0-9]+|"version"\s*:\s*2[0-9]' tests/ plugins/*/*/tests/` →
    the two pins at 27, plus the `:44` poison literal at 22;
  - `uv run pytest tests/discovery/test_contract_discovery.py tests/cli/test_parameter_types.py tests/app/test_eager_boot_provider.py tests/integration/test_lazy_true_engine_materialization.py`
    (2.1's gate and its single-report tests);
  - the wave barrier: the whole root suite and the plugin-package loop (header rule).
- **Reachability:** `func <job>` → `DirectoryScanProvider` → the extraction → `JobDescriptor` →
  `cache.json`. The reader is 5.1 (`build_resolution_plan`). Until 5.1 lands, the field carries
  `# TRANSITIONAL(parameter-contract/5.1)`.
- **Execute evidence (2026-11-23):**
  - **What landed.**
    - `extract_signature(func) -> SignatureExtraction(parameters, omitted_contracts)`
      (`_discovery/providers.py`). The skip loop is unchanged: the three existing `continue`s
      (`FromJob`, capability type, `GroupOptions`) each first keep the contract that
      `_parameter_contracts` already built. No condition was added or moved.
    - `extract_parameters_from_signature` is now `extract_signature(func).parameters`.
    - The seven sites call `extract_signature`. Five of them build a descriptor and set
      `omitted_contracts`: `registry.py:522`, `sync.py:277`, `sync.py:739`, the entry-point
      `_build_descriptor`, and `impl.py:820`. The two `_extract_parameters` methods return the
      extraction. `StaticProvider`'s caller sets the field from it. `DirectoryScanProvider`'s has no
      caller in `src`, before or after.
    - `JobDescriptor.omitted_contracts`, marked `TRANSITIONAL(parameter-contract/5.1)`, is encoded
      under `"omitted_contracts"` with 0.1's contract codec. `CACHE_VERSION` 27.
    - `report_unsupported_parameters` and `contract_covers` read `omitted_contracts`. The stale
      parenthetical is replaced by B-9's three survivors.
  - **Gate: `tests/discovery/test_omitted_contracts.py` → 676 passed.** It covers all 166 rows,
    cold and warm, through the real `func`, in both annotation modes:
    - the halves are disjoint, and their union equals `build_contracts(function)`'s names;
    - E108–E137 carry `injection.capability` and E140/E141 `injection.from_job`, all omitted and
      absent from `parameters`;
    - cold and warm `omitted_contracts` are equal, and the warm boot is proven lazy;
    - for every descriptor, cold and warm, `build_click_params_from_descriptor` and
      `job_input_schema` serialise identically with and without `omitted_contracts`;
    - an extra job, `capmark(p: Annotated[Log, Option()])`, is omitted and refused, and is reported
      exactly once as `UnsupportedParameter` on both boots;
    - E142 in eager mode raises at import and has no descriptor; the test asserts that.
  - **Grep gates:**
    - `extract_parameters_from_signature\(` in `src plugins` → 1, the definition.
    - `directly registered functions` in `src` → 0.
    - Cache pins: the two pins are at 27, and the `:44` poison literal stays at 22.
    - **`extract_signature\(` in `src` → 9, not 8.** The ninth hit is `providers.py:93`, the
      `return extract_signature(func).parameters` this task's own Work prescribes for
      `extract_parameters_from_signature`. The gate's count missed the wrapper. It is not an extra
      call site, and the code was not bent to fit the number.
  - **2.1's gate** (`test_contract_discovery.py test_parameter_types.py test_eager_boot_provider.py
    test_lazy_true_engine_materialization.py`) → 686 passed, 2 skipped, 4 failed. The 4 were
    `tests/cli/test_parameter_types.py::TestAnExplicitMarkerOutranksTheTypeList::{test_an_unlisted_type_becomes_an_option,test_the_value_reaches_the_job_as_that_type}[func|app]`.
    They failed identically at base `69a95c99` (detached checkout with its own `src` first on
    `PYTHONPATH`: 4 failed). The cause was not 3.2: `Annotated[Widget, Option()]` is D105, now
    refused, so `--w` no longer renders and the run reports `UnsupportedParameter`. The file is
    outside 3.2's `[F]`; it is in 3.1's, by that task's scope repair. `6686cade` made them pass as
    `TestAnExplicitMarkerNoLongerOutranksTheTypeList::{test_help_offers_no_option_for_it,test_a_call_is_a_usage_error_and_the_body_never_runs}[func|app]`.
  - Suites this change touches (`tests/types tests/discovery tests/config tests/app
    tests/integration tests/adapters tests/test_descriptor.py`, `-n auto`) → 4542 passed, 233
    skipped. `mypy src/` clean, `ruff` clean, `lint-imports` 7 kept, 0 broken. The wave barrier is
    run by the leader.
  - **Sabotage, after committing the change (before this evidence was amended in):**
    - `_omit` kept nothing (`if False:`): 144 failed, 532 passed.
    - Boot ignoring `omitted_contracts`, in both `contract_covers` and the report walk: the four
      `test_an_omitted_refusal_is_reported_once` cases failed.
    - Each was restored with `git checkout --`, and the tree was clean.
- **Depends on:** 2.1.

## Wave 4 — completion, SmartBar, the TUI door, the pre-boot walk

### [x] 4.1 Completion and SmartBar offer exactly the rendered spellings (F-06, F-27)

- **Input:**
  - 3.1;
  - `gates-authoring.txt` `name-skip` (2 hits, both in `smart_bar_autocomplete.py`);
  - `injection-by-type-name` (`smart_bar_autocomplete.py:554`);
  - `job-param-string-reads` (`smart_bar_autocomplete.py:559`).
- **[F]:**
  - `src/functualize/_cli/completions/data.py`;
  - `src/functualize/_cli/tui/smart_bar_autocomplete.py`;
  - `src/functualize/_cli/completions/flag_filtering.py`.
- **Work:**
  - Both read the rendered params' `opts` and `secondary_opts`, excluding hidden params.
  - Delete `_candidates_flag`'s own field loop, the name skip, `_extract_short_names` and the
    `"list["` test.
  - `FlagDescriptor.is_list_type` comes from the contract.
  - Drop the `annotation_utils.unwrap_annotated` import at `smart_bar_autocomplete.py:842`, which
    8.1 deletes.
- **Gate/evidence:**
  - `rg -n '"rc", "run_context", "log"' src` → 0 (today 2);
  - `rg -n annotation_utils src/functualize/_cli/tui/smart_bar_autocomplete.py` → 0 (today 1);
  - `uv run pytest tests/_cli/test_completion_flag_pairs.py tests/_cli/test_flag_filtering.py`;
  - kit `surf_check.py` W-bar → 0 rows (today 65).
- **Execute evidence (2026-11-23, after 4.4, so on final choice types):**
  - **SmartBar.** `_candidates_flag` reads the rendered `click.Option`s (`opts` and
    `secondary_opts`, hidden excluded) through `_rendered_options`. Each parameter becomes one
    `FlagDescriptor`:
    - its primary long spelling;
    - its short spelling;
    - `is_list_type` from the contract's `cli.repeatable`, falling back to the rendered
      `multiple` for a field with no contract;
    - its other long spellings (`--no-x`), so using either retires the flag.
  - The positional candidates read the rendered `click.Argument` order.
  - **Deleted:** the field loop, both `"rc", "run_context", "log"` name skips,
    `_extract_short_names` with its `annotation_utils` import, the `"list["` test, and the
    `_injection_type_names` helper, whose only caller was that loop. None was load-bearing
    elsewhere: `rg -n '_extract_short_names|_injection_type_names' src tests` → 0.
  - **The type labels** in the two rewritten candidate builders read `contract.display` (SS-3). A
    contract-less field, a plugin or builtin node, keeps `type_annotation` under
    `# TRANSITIONAL(parameter-contract/9.3)`.
  - **Completion data** (`data.py`) skips hidden params. Flag choices come from the rendered
    `click.Choice`, not the field's own `choices`.
  - `flag_filtering.FlagDescriptor` gains `other_long_names` and `field_name`.
  - **Gates:**
    - `rg -n '"rc", "run_context", "log"' src` → 0;
    - `rg -n annotation_utils src/functualize/_cli/tui/smart_bar_autocomplete.py` → 0;
    - `uv run pytest tests/_cli/test_completion_flag_pairs.py tests/_cli/test_flag_filtering.py` →
      4 passed, 5 skipped;
    - every test file that names the SmartBar, completion data or flag filtering (15 files) plus
      `tests/group_options/` → 439 passed, 38 skipped;
    - kit, regenerated at this change (`gen.py` 255 s, `surfaces.py` 326 s, `surf_check.py`) →
      `W-bar: 0 rows`.
  - The other W-predicates are other tasks' gates and are unchanged by this one: W-collapse 34
    (4.2) and W-inject, W-type, W-default, W-crash (5.1).
  - **Sabotage, after committing the change (before this evidence was amended in):** the three
    `[F]` files were restored to their pre-4.1 state, at the same HEAD, and `surfaces.py` was re-run
    against the same `out.json`. W-bar became 49 rows:
    - `bar=--p help=∅` 41, positionals and refused parameters offered as flags;
    - `bar=--p help=--no-p --p` 4, A013–A016, the missing `--no-` half;
    - `bar=--f help=∅` 2, F150 and F151.

    `git checkout HEAD --` restored the files, and the tree was clean.
- **Depends on:** 3.1.

### [x] 4.2 The TUI bar parses with the CLI grammar (D8, F-26)

- **Input:** 3.1; `gates-authoring.txt` `tui-parser`: `parse_cli_args_to_kwargs`, 12 hits in 5
  files.
- **[F]:**
  - `src/functualize/_cli/tui/cli_arg_parser.py`;
  - `src/functualize/_cli/tui/app.py`;
  - `src/functualize/_cli/inline_tui.py`;
  - `src/functualize/_cli/tui/chain_resolution.py`;
  - `src/functualize/_cli/tui/sync.py`;
  - `src/functualize/_cli/tui/job_execution.py` (the TUI run door renders a Click refusal);
  - `tests/_cli/test_orchestrator_handoff.py`,
    `tests/_cli/test_preflight_summary_content_pbt.py`,
    `tests/_cli/test_secret_masking_wiring.py`,
    `tests/cli/test_pending_execution_integration.py`, and
    `tests/tui_group_options/test_write_back_contract.py` (the retired parser's callers and the
    list/choice fixed point).
- **Work:**
  - Replace `parse_cli_args_to_kwargs` with a parse through the job's rendered click command.
  - The emitter `sync.build_command_line` repeats list flags and reads arity from the contract, and
    keeps `emit(resolve(text)) == text` (`data-flow.md` §7).
  - The injection filter (`app.py:2274`) reads the verdict.
- **Gate/evidence:**
  - `rg -n -w parse_cli_args_to_kwargs src` → 0 (today 12);
  - `uv run pytest tests/tui_group_options/test_write_back_contract.py tests/tui/test_command_path_surface.py tests/cli/tui/test_descriptor_fields.py tests/cli/test_pending_execution_integration.py`;
  - kit `tui_extra.py` → 0 rows (today 91), W-collapse → 0 (today 34).
- **Reachability:** TUI run → `job_execution.run_job` → `app.job_kwargs_for` → the click parse.
- **Execute evidence (2026-11-23):** The previous quota-limited run's 11-file diff was retained
  after review: it routes the TUI and inline handoff through the rendered Click parameters, reads
  the injection verdict, and keeps repeated values as repeated flags. The `[F]` list above records
  the run door's necessary Click refusal and tests that imported the retired parser. Two explicit
  fixed-point cases now assert `emit(resolve(text)) == text` for `--p a --p b` and an integer choice.
  `rg -n -w parse_cli_args_to_kwargs src` → no hits (exit 1). The four named test modules →
  54 passed. Three touched `_cli` modules → 24 passed, 1 skipped; both group-option suites →
  335 passed, 20 skipped. The regenerated 166-row kit (`gen.py`, `surfaces.py`) reports
  `tui_extra.py` → `0 rows`, `surf_check.py` → `W-collapse: 0 rows` and `W-bar: 0 rows`.
  `mypy src/` → 0 issues; `lint-imports` → 7 kept, 0 broken; Ruff check and format pass.
- **Depends on:** 3.1.

### [x] 4.3 Bar readiness and the pre-boot group walk read the contract (F-10)

- **Input:** 3.1; `job-param-string-reads` hits at `bar.py:294` and `dispatch.py:715`.
- **[F]:**
  - `src/functualize/_cli/tui/bar.py`;
  - `src/functualize/_cli/dispatch.py`;
  - `src/functualize/app/commands.py` (read-only audit: `JobNode.params` already returns cached
    descriptors with contracts);
  - `tests/cli/tui/test_bar_properties.py` and
    `tests/group_options/test_group_options_dispatch.py` (arity and repeatability regressions);
  - `tests/types/test_flag_grammar_consumer_count.py` (the pinned consumer set shrank when
    SmartBar stopped reading flag grammar; recorded in `427ef3d9`).
- **Work:**
  - Arity comes from `contract.shape`, not `== "bool"`.
  - `walk_group_path` accumulates repeated group flags into a list for repeatable group fields.
  - `JobNode.params()` keeps returning cached descriptors, now carrying contracts.
- **Gate/evidence:**
  - `rg -n -F 'type_annotation == "bool"' src/functualize/_cli/dispatch.py` → 0 (today 1);
  - the kit's `func g160g --p a --p b run` gives `['a', 'b']` (today `['b']`);
  - `uv run pytest tests/cli/tui/test_bar_properties.py tests/cli/test_pre_boot_resolution.py`.
- **Execute evidence (2026-11-23):** SmartBar readiness uses the job's rendered Click parameters
  for option spellings and positional order, then `contract.shape` for presence-flag arity.
  `walk_group_path` uses the cached shape for arity and `contract.cli.repeatable` to append each
  group value. A contractless legacy group field falls back to its rendered Click parameter.
  `JobNode.params()` already returns the cached descriptor records without reconstructing them;
  its implementation was audited and did not need an edit. The two test files above were added to
  `[F]` to cover boolean arity and repeated group values. `rg -n -F 'type_annotation == "bool"'
  src/functualize/_cli/dispatch.py` → no hits (exit 1). In the regenerated kit project,
  `func g160g --p a --p b run` exits 0 and prints `OBS p=['a', 'b'] type=list`. The two named
  modules → 14 passed, 10 skipped; `tests/group_options/ tests/tui_group_options/` → 336 passed,
  20 skipped. `mypy src/` → 0 issues; `lint-imports` → 7 kept, 0 broken; Ruff check and format pass.
- **Depends on:** 3.1.

### [x] 4.4 Choice sets keep their declared value type (spec B-3, review question S1)

- **Input:**
  - `spec.md` B-3 (*choice sets*) and B-8;
  - `schema.md` invariant 7 and § *Binding*;
  - `plan.md` § *Choice sets and config scalars*;
  - `literal-path-2c32077e.txt`, `matrix/literal_probe.py`.
- **[F]:**
  - `src/functualize/_types/parameter_contract.py`: the `enum_values` annotation;
  - `src/functualize/_primitives/parameter_contract.py`: `_scalar`, `_python_type`, and the refusal
    reason;
  - `src/functualize/_primitives/argument_binding.py`: the token-to-choice mapping;
  - `src/functualize/_primitives/cache_format.py`: `CACHE_VERSION` 27 → 28;
  - `tests/types/test_descriptor_owner_class.py` (`:40`, 27 → 28);
  - `tests/discovery/test_job_declaration_discovery.py` (`:169`, 27 → 28);
  - `tests/primitives/test_choice_sets.py` (new).
- **Work:**
  - **Keep each value's type.** `_scalar` keeps `Literal` arguments and `Enum` member values as
    declared, instead of applying `str(...)` (`parameter_contract.py:330`, `:335`). `_python_type`
    builds `Literal[...]` from those typed values, so `shape_json_schema` publishes `"type":
    "integer"` for an `int` set. Pydantic does this unaided (`literal-path-2c32077e.txt`, last
    section).
  - **Refuse every other set** as `REJECTED_DISCOVERY`: mixed `str`/`int`, any `bool` (including
    `Literal[True]`), `float`, `None`, or a non-JSON value. The reason names the declaration, and
    the remedy reads "use an `Enum` whose values are all `str` or all `int`".
  - **Binding** (`ArgumentBinder`): for a choice shape whose values are `int`, a `str` value is
    mapped to the choice whose `str()` equals it before the `TypeAdapter` runs. A `str` set needs no
    mapping.
  - **Unchanged:** `display`, and the text spelling `str(value)` that 3.1 and 4.1 render.
- **Invariant:** for every supported choice set, each value the published schema advertises is
  accepted by the binder, and so is its `str()` token. Today the binder refuses both for an `int`
  set.
- **Gate/evidence:**
  - `uv run pytest tests/primitives/test_choice_sets.py`, in both annotation modes. It covers
    `Literal["low", "high"]`, `Literal[1, 2]`, a `str` and an `int` `Enum`, and `list[...]` of
    each:
    - the schema's `type` and `enum` are typed;
    - each advertised value **and** its `str()` token bind to the declared value;
    - `Literal["a", 1]`, `Literal[True]`, `Literal[1.5]` and a mixed-value `Enum` are
      `REJECTED_DISCOVERY` with the remedy;
  - `uv run --frozen python .spec/features/parameter-contract/matrix/literal_probe.py`. Every
    `advertised` line reads `accepted`. Today 4 `REFUSED` lines remain for the supported sets
    `s_int` and `e_int`; `s_mixed` and `s_bool` instead become refusals at discovery;
  - `uv run pytest tests/primitives tests/types tests/discovery/test_contract_discovery.py`;
  - `python3 .spec/features/parameter-contract/matrix/table_diff.py` → no rows, exit 0. No table
    row has a non-`str` choice set; A045–A048's `Color` is `str`-valued;
  - the cache-version census: the two pins at 28, and the `:44` poison literal at 22;
  - the wave barrier: the whole root suite and the plugin-package loop (header rule).
- **Reachability:** `func <job>` → discovery → `build_contract` → `shape_json_schema`. The binder
  mapping has its first production caller in 5.1.
- **Execute evidence (2026-11-23, done first in wave 4 so that 4.1–4.3 land on final types):**
  - `_scalar` hands `Literal` arguments and `Enum` member values, unconverted, to a new
    `_choices`. It keeps a set whose value types are exactly `{str}` or `{int}`, which excludes
    `bool` because `type(True) is bool`. Anything else raises the `choice_set` refusal:
    "'<declaration>' is a choice set whose values are not all str or all int. Use an Enum whose
    values are all str or all int".
  - `_python_type` was unchanged; it already built `Literal[...]` from `enum_values`.
  - `ValueShape.enum_values` is now `tuple[str | int, ...]`. `CACHE_VERSION` is 28.
  - `ArgumentBinder` gained `_choice_tokens`. For an `int` set, a `str` token becomes the choice
    whose `str()` equals it, before the adapter runs: scalar, `list`/`tuple`/`set`, `dict` values
    and fixed-tuple members. A fixed tuple of the wrong length is passed through unmapped, so the
    adapter refuses it rather than a truncation being accepted.
  - `wc -l src/functualize/_primitives/parameter_contract.py` → 499. Three docstrings were
    shortened to stay under the cap.
  - `uv run pytest tests/primitives/test_choice_sets.py` → 28 passed, in both modes:
    - typed `type`/`enum` for scalar and `list[...]`, for `Literal["low", "high"]`,
      `Literal[1, 2]`, a `str` `Enum` and an `int` `Enum`;
    - each advertised value and its `str()` token bind to the declared value or member;
    - `Literal["a", 1]`, `Literal[True]`, `Literal[1.5]`, a mixed `Enum` and `list[Literal["a", 1]]`
      are `REJECTED_DISCOVERY` with the remedy; the reason names the declaration;
    - a token outside the set is still refused.
  - `literal_probe.py`: every `advertised` line reads `accepted`. `s_int` and `e_int` publish
    `{"enum": [1, 2], "type": "integer"}`. `s_mixed` and `s_bool` are `REJECTED_DISCOVERY` with
    `schema=null`, so no refused value is advertised.
  - `table_diff.py` → `0 rows differ`, exit 0. Cache census: the two pins are at 28, and `:44` stays
    at 22.
  - `tests/primitives tests/types tests/discovery tests/adapters tests/config` (`-n auto`) → 5690
    passed, 206 skipped. `plugins/adapters/functualize-mcp/tests` → 33 passed. `mypy src/` clean,
    `lint-imports` 7 kept, 0 broken.
  - **Finding outside `[F]`:** `functualize_mcp/_schema_export.py:288-289` renders every `enum`
    value quoted (`f'"{v}"'`). An `int` set therefore exports to TypeScript as `"1" | "2"`. The
    exports are B-21's, derived from the one schema in wave 7.
  - **Sabotage, after committing the change (before this evidence was amended in):**
    - Restoring `str(...)` in `_scalar` for both `Literal` and `Enum`: 19 failed, 9 passed.
    - Removing the binder's `_choice_tokens` call: 4 failed, the `int` sets' `str()` tokens.
    - Each was restored with `git checkout --`, and the tree was clean.
- **Depends on:** 3.2 (`CACHE_VERSION` 27).

## Wave 5 — the engine door

### [ ] 5.1 Bind at the door; DI fills only `INJECTED`; kind from the contract

- **Input:**
  - 2.1 to 2.3, 3.2, 4.4, and 0.2;
  - `plan.md` § *The contract gap* and § *The door's inputs*; `schema.md` invariant 6;
  - `gates-authoring.txt` `engine-old-binding`: 7 hits (`executor.py` 3, `validation.py` 4);
  - `registry-kind`: 2 hits in `resolution.py`;
  - `door-scope-b2719ab8.txt` (scope repair, 2026-11-23);
  - `id-keyed-caches-2ccc4cde.txt` and the leader's seven rulings on the 5.1 draft (R-1 to R-7,
    2026-11-23: draft = `2ccc4cde` + the preserved 18-path stash; the whole root found 46 failures
    in 11 files, against 16 for the old gate line);
  - `validation-retire-2eeb5658.txt`, `matrix/varkw_probe.py` (second scope repair, 2026-11-23: the importers of the deleted
    `validation.py`).
- **[F]** (scope repaired 2026-11-23 on the implementer's measured report; each addition says why):
  - `src/functualize/_engine/executor.py`;
  - `src/functualize/_engine/resolution.py`;
  - `src/functualize/_engine/validation.py` (deleted);
  - `src/functualize/_engine/middleware.py`, `src/functualize/_engine/job_middleware.py`: the other
    two `build_resolution_plan` callers (`middleware.py:227`, `job_middleware.py:247`);
  - `src/functualize/_types/protocols.py`: `EngineHost.admitted_contracts` (option A, below);
  - `src/functualize/app/core.py`: `FunctualizeApp` implements it in one delegating line (budget:
    see *Work*);
  - `src/functualize/_app/boot.py`: per-job admit extracted so dynamic registration shares it, and
    the `:2024` marker retired;
  - `src/functualize/_app/impl.py`: `register_dynamic_job` admits the job it registers;
  - `src/functualize/_types/descriptors.py`: the `:291` marker retired; comment text only;
  - `src/functualize/_primitives/argument_binding.py`: the `:21-22` marker comment retired;
    **comment lines only, no code change** (see *Config fields*);
  - `src/functualize/app/adapters/click_params.py` (3.1's `Enum` bridge deleted; added 2026-11-23);
  - `tests/execution/test_resolution_plan.py`, `tests/test_resolution_plan_properties.py`: they
    call the signature this task removes (15 and 13 calls);
  - `tests/engine/test_unexpected_keyword.py` (**deleted**): it imports `unexpected_keyword_error`
    (`:18`) from the deleted module;
  - `tests/config/test_pep563_annotation_sites.py`: **`TestArgumentValidation` only** (`:172-211`,
    three lazy imports at `:178`, `:192`, `:204`). The rest of the file is the F-32/E142 PEP 563
    instrument and is not touched;
  - `tests/validation/test_arg_validator_properties.py` (**deleted**): it imports `ArgValidator`
    (`:19`);
  - `tests/engine/test_binding_door.py` (new);
  - **Third scope repair (2026-11-23, rulings R-2 to R-4): 18 → 25 files.**
    - `src/functualize/_primitives/parameter_contract.py`: R-2 (`FromStep` skipped) and R-3
      (capability names matched before `unevaluable`);
    - `tests/config/test_config_injection_pep563.py`,
      `tests/config/test_missing_config_prompt.py`, `tests/engine/test_class_job_receiver.py`,
      `tests/workflow/test_launch_validation.py`,
      `tests/integration/test_declared_capabilities_e2e.py`,
      `tests/execution/test_tty_live_capabilities.py`: the six R-4 files, which pinned outcomes the
      spec replaced (*Re-homed claims*, below).
    - R-1 and R-5 add no production file: `executor.py`, `middleware.py`, `job_middleware.py`,
      `resolution.py`, `boot.py` and `click_params.py` are already listed.
- **Work:**
  - At `executor.py:1393-1486`, replace `unexpected_keyword_error` (workflows only) and
    `ArgValidator` with `bind`, before DI resolution and before `PRE_EXECUTE`.
  - DI fills `INJECTED` names only. A caller key for one never arrives, because `bind` refuses it.
  - **`build_resolution_plan(contracts)` is the one plan builder,** for jobs and middleware alike.
    It keeps its name, so `_engine/__init__.py`'s re-export is unchanged. It takes contracts, not a
    function and not `registered_types`, so `base_type in registered_types` and "Optional[T] is
    always classified as di" go, and `registered_types` leaves `_engine` entirely.
    - **The source of each value comes from the `Injection` fields:**
      - `capability` → the engine's per-invocation capability, looked up by name;
      - `from_job` → the upstream result;
      - `provider_type` (with `qualifier`) → DI;
      - any other verdict → `bind` for a job, and *skip* for middleware.
    - No type name and no annotation is inspected here. The 15 capability names stay named constants
      read only by the classifier (`_primitives/capability_names.py:49`).
  - **Where a job's contracts come from.** `EngineHost.admitted_contracts(name)` returns the
    admitted contracts of the job's `parameters`, `config_fields` and `omitted_contracts` (2.1,
    3.2): exactly what boot's admit wrote (`_app/boot.py:2026`). Every signature parameter has one
    (`schema.md` invariant 6).
    - The absent answer is `None`, per the port's own convention (`_types/protocols.py:562`): no
      host, or a job the host never admitted.
    - Only a hostless engine (unit tests, embedding) meets `None` for a registered job. Its door
      then takes the job's contracts from `build_contracts(function)`, once per function, cached
      by weak reference to the function, **never by `id()`** (R-1, below). That is the one
      classifier, because nothing was discovered to read.
    - Those contracts are not admitted, so a missing provider surfaces from DI resolution as today.
      The door makes no availability decision of its own.
  - **Middleware** (`_resolve_middleware_kwargs` in `middleware.py` and `job_middleware.py`).
    - A middleware callable is not a job: it has no descriptor and no admit. Its plan is
      `build_resolution_plan(build_contracts(middleware_fn))`, built once per callable. The
      cache is keyed by weak reference to the callable, **not by `id()` as today** (R-1
      supersedes the 2026-11-23 instruction to keep that cache's key).
    - Only `INJECTED` contracts resolve:
      - a `RunContext` capability → the run context in `job_middleware.py` (today's `runcontext`
        source), and in `middleware.py` only what `context.capabilities` holds (today it passes
        `runcontext_type=None`);
      - a provider → DI, with today's failure rule kept: an optional parameter gets `None`, any
        other is skipped (`middleware.py:259-262`);
      - every other verdict is *skip*.
    - If `build_contracts` raises for a callable, the plan is all-*skip*, which is today's direct
      path.
    - **The only behaviour change is F-21's:** a registered `str` provider no longer turns a
      middleware `str` parameter into a DI parameter.
  - **The admit result reaches the engine through the port: option A** (decided 2026-11-23,
    `plan.md` § *The door's inputs*).
    - `EngineHost` gains `admitted_contracts(name) -> Mapping[str, ParameterContract] | None`.
      `FunctualizeApp` implements it over the store boot writes. `FunctualizeApp` is at 311 of its
      320 executable-line budget, pinned at line 116 of the facade budget test. One delegating
      method fits, and that test is in the gate. The test file is not edited.
    - **B is rejected.** It would make `RegisteredJob` (frozen) carry the admitted set, but three
      of its four construction sites cannot supply it:
      - `_discovery/registry.py:429` runs at discovery, before admit exists;
      - `app/adapters/lazy_command.py:141` materialises from a descriptor that carries only
        `omitted_contracts`;
      - `_app/impl.py:792` is the imperative entry;
      - so B needs a fifth data source, or a new descriptor field and a `CACHE_VERSION` bump.
    - **C is rejected** by this task's own rule: "there is no second availability check".
  - **A job registered after boot is admitted once, at registration.** `FunctualizeApp.__init__`
    boots (`app/core.py:237-239`), so `register_dynamic_job` always runs after boot's admit, and
    today it admits nothing (`door-scope-b2719ab8.txt`).
    - The per-job body of `report_unsupported_parameters` is extracted as one function in
      `_app/boot.py`, called by boot's loop and by `register_dynamic_job`.
    - It uses the same exact-pair predicate (the registry is frozen after boot, so it is the same
      answer) and gives the same single B-9 report.
    - Every app-hosted job, discovered or registered, then has an admitted set (`spec.md` B-2).
  - **Config fields.** Keys naming a job's `CONFIG_FIELD` contracts (`--city Tokyo` for a job
    declaring `config: Cfg`) are partitioned off before `bind` and handed to config resolution
    (`_resolve_config_model`), as today.
    - So `argument_binding.py`'s code does not change. `ArgumentBinder.bind` refusing a
      `CONFIG_FIELD` key is correct, and stays.
  - **Delete 3.1's `Enum` bridge.** That is the `ENUM` branch in `click_params.py` marked
    `# TRANSITIONAL(parameter-contract/5.1)`.
    - The click token reaches the door as text, and the binder converts it to the member through
      the live annotation's `TypeAdapter`, with 4.4's token → choice mapping.
    - That holds on the live command and on the descriptor-only lazy command alike, which closes
      the lazy path 3.1 leaves on text.
  - **Every `TRANSITIONAL(parameter-contract/5.1)` marker is retired** (constitution, *Transitional
    Changes*). Four exist today:
    - `click_params.py:468`: deleted with the bridge;
    - `argument_binding.py:22` ("no production caller yet"): deleted; the door is its caller;
    - `boot.py:2024` ("read by the engine door"): replaced by a plain comment naming
      `EngineHost.admitted_contracts` as the reader;
    - `descriptors.py:291` ("the engine door is their only reader"): replaced by a plain comment
      naming `build_resolution_plan` via the door as the reader.
  - A missing provider refuses before the call, on cold and warm alike (F-33). The refusal reads
    the admitted contracts; there is no second availability check.
  - `BindRefusal` becomes `JobResult(status=INVALID)`.
  - **R-1 · no cache keyed by `id()`** (`spec.md` B-7 invariant; `schema.md` invariant 8).
    Measured at `2ccc4cde` (`id-keyed-caches-2ccc4cde.txt`), four keys are taken from `id()` of a
    callable:
    - `_resolution_plan_cache` (`executor.py:1802`);
    - `_group_options_cache` (`executor.py:2493`);
    - the middleware plan caches (`middleware.py:218`, `job_middleware.py:238`);
    - and the draft adds a fifth, `_hostless_contract_cache`.

    All are keyed on the callable by `weakref.WeakKeyDictionary`. A callable that cannot be weakly
    referenced is resolved uncached. `ResolutionPlan.function_id` is removed, because the `id()`
    key was its only purpose. The docstrings that describe id-keying are corrected with them.
  - **R-2 · `FromStep` parameters are not parameters** (`spec.md` B-1).
    - `build_contracts` skips a parameter whose `Annotated` metadata holds a `FromStep`, exactly
      as it skips `self`/`*args`/`**kwargs`. The leader's measured probe shape is acceptable:
      `_reads_from_step(annotation)`, checked before `build_contract`.
    - The walk keeps seeding `context.call_kwargs` before the door binds (`_engine/walk_reads.py`,
      the only supplier).
    - A caller key naming the step's parameter is refused as unknown (B-26).
  - **R-3 · a capability named by a string** (`spec.md` B-6).
    - In `_classify`'s string branch, an annotation string whose stripped text is in
      `INJECTED_PARAM_TYPE_NAMES` becomes `INJECTED` with `Injection(capability=<name>)` before
      any evaluation is tried.
    - Only a string that is neither is refused as `unevaluable`.
  - **R-5 · the materialised route admits** (`spec.md` B-2, *the routes that admit*).
    - `admit_job_descriptor`'s contract loop (`_app/boot.py`) is extracted as
      `admit_contracts(app, job_name, contracts, source)`.
    - Boot, `register_dynamic_job` and `create_job_command` (`click_params.py`, via
      `build_job_engine_callback`) all call it. `create_job_command` admits the contracts it
      already builds.
    - The 7 failing tests of `tests/config/test_unified_config_integration.py`
      (`missing 1 required positional argument: 'rc'`) then pass **unchanged**, so that file does
      not enter `[F]`.
    - Retiring `create_job_command` is not this ticket: it is a documented embedder entry point,
      referenced by 11 test files, `_discovery/registry.py` and
      `contributor/architecture/developer-modes.md`.
  - **R-4 · re-homed claims.** Each file keeps every claim it makes, and only the verdict the spec
    replaced changes: never deleted, never a waiver.

    | file | fails on the draft | spec clause | the claim, as it now reads |
    | --- | --- | --- | --- |
    | `tests/config/test_config_injection_pep563.py` | 1 | B-9, `unevaluable` | an unevaluable annotation ends `INVALID`, and the refusal names the missing name; it does not end `SUCCESS` |
    | `tests/config/test_missing_config_prompt.py` | 2 | B-8 (nested config model, F-29) | `INVALID`, and the prompt collector is never asked |
    | `tests/engine/test_class_job_receiver.py` | 1 | B-25 | `call_kwargs` is `{"force", "opts"}`, because the binder supplies `force`'s default; the `self`-absence assertions stay verbatim |
    | `tests/workflow/test_launch_validation.py` | 9 | B-26 | the same claims, with `Invalid` plus `BindRefusal` in place of `Failure` plus `TypeError` |
    | `tests/integration/test_declared_capabilities_e2e.py` | 1 | F-20, B-30 | an explicit value for an injected parameter is **refused**, naming it |
    | `tests/execution/test_tty_live_capabilities.py` | 2 | plan source vocabulary | the source is `"capability"`, not `"di"`; only `"capability"` reaches the per-invocation branch |

    R-7: two of these refusals stay refusals. The `Missing` case of `test_config_injection_pep563`
    and the nested-config cases are DC-1 = B working as designed: the job stays listed and refuses
    with its remedy.
  - **The `CHANGELOG.md` entries this task carries in its implementation push** (gate 1(c); the
    designer writes none of them):
    1. a job declaring `**kwargs` no longer receives unknown keys: they are refused (B-26);
    2. middleware: a registered `str` provider no longer turns a middleware `str` parameter into
       DI (F-21);
    3. a `FromStep` parameter is not a caller input: it is published on no surface, and a caller
       key naming it is refused (B-1);
    4. a refused call (unknown, missing, non-converting, or injected key) ends `Invalid`, not
       `Failure` with a `TypeError`, including at a workflow launch (B-26);
    5. a job whose config model nests a model or a `dict` is refused at discovery and ends
       `Invalid` on every call (B-8, F-29);
    6. an explicit value for an injected parameter is refused (B-30).
  - **The three importers of `validation.py` (second scope repair, 2026-11-23).** Exactly these three
    files outside the earlier `[F]` import the deleted module (`validation-retire-2eeb5658.txt`).
    Four other hits are prose only and are not touched: `test_option_marker_unit.py:208`,
    `test_argument_binding.py:254`, `_constrained_functions.py:5` and
    `test_validation_hooks_property.py:33-34`. Their docstrings describe history, not a live
    reference.
    - **`tests/engine/test_unexpected_keyword.py`: retire (delete).** Each of its claims is either
      carried or reversed:
      - B1, an unaccepted keyword is refused: carried by `test_argument_binding.py::test_an_unknown_key_is_refused_naming_it`
        (unit), and by `test_binding_door.py` through the engine for a workflow launch, which is
        where `unexpected_keyword_error` ran;
      - B3, a missing DI argument is not a launch error: carried by
        `test_argument_binding.py::test_injected_parameters_are_left_for_di`;
      - B6, an accepted keyword passes: carried by `test_a_supplied_value_arrives_as_the_declared_type`;
      - "a DI parameter may be supplied explicitly" (`:60-67`): **reversed** by B-26 and B-30, and
        carried by `test_a_value_for_an_injected_parameter_is_refused`;
      - B5, `**kwargs` accepts anything: **reversed** by B-26 (clarified 2026-11-23). Measured:
        today's rule accepts `zzz` for `def job(version="1", **kwargs)`, and the binder refuses it
        with `Unknown argument 'zzz'. This job accepts: version`. The door test pins the refusal,
        and `CHANGELOG.md` records it in the same push;
      - `TestTheMessage` (parity with Python's own `TypeError` wording): retired. The refusal now
        names the argument and what the job accepts (B-26). It is rendered per surface (6.2), not as
        Python's message.
    - **`tests/config/test_pep563_annotation_sites.py`: migrate `TestArgumentValidation` to the
      binder.** It stays in the same file, as the PEP 563 instrument's binding row. Its three tests
      become `ArgumentBinder().bind(fn, build_contracts(fn), raw, surface=…)` over both module forms:
      - both forms give equal contracts and bind `count=5` to `5`;
      - under PEP 563, `count=99` is a `BindRefusal`;
      - both forms refuse `count=-1`.
      
      The guarantee the class exists for, that `Field()` constraints hold under PEP 563, is kept.
    - **`tests/validation/test_arg_validator_properties.py`: retire (delete).**
      - Property 4 (validation idempotence) is **carried**. `test_binding_door.py` asserts that, for
        every table row with a caller verdict, binding `bind`'s output again yields equal values.
      - Property 5 (only `Field`-constrained parameters are validated; others pass untouched) is
        **reversed by design**. B-24 converts every supplied value to its declared type, so an
        unconstrained `UUID` arriving as text is converted, not passed through.
    - **The constraint refusal `ArgValidator` performed does not vanish.**
      `test_argument_binding.py::test_field_constraints_hold_at_the_door` proves it in the binder
      (`Annotated[int, Field(ge=1)]`). `test_binding_door.py` proves it through `engine.run`: a
      constrained parameter given an out-of-range value ends as `INVALID`, in both annotation modes,
      with the job body never run.
  - **The two plan test files migrate to the contract form**,
    `build_resolution_plan(build_contracts(fn))`.
    - The tests that pin a kind decided by `registered_types` are rewritten to the declaration
      rule:
      - `test_resolution_plan.py`: `test_detect_registered_di_type`,
        `test_unregistered_type_is_skipped` (an unmarked class is now `INJECTED` and resolves by
        DI), and `test_optional_unregistered_resolves_to_di`;
      - `test_resolution_plan_properties.py`: `test_all_registered_type_params_resolved_from_registry`,
        where kind no longer follows registration.
    - Every other assertion keeps its meaning: caching by identity, `self`/`cls`/`*args` skipping,
      qualifiers, `RunContext`, optional-without-provider → `None`, and DI over defaults.
- **Invariant:** `JobExecutionEngine` does not grow: `ast` line count ≤ 2,747 (`executor.py:213-2959`
  at `da912d76`).
- **Gate/evidence:**
  - `rg -n -w -e ArgValidator -e unexpected_keyword_error src` → 0 (today 7);
  - `rg -n 'base_type in registered_types' src/functualize/_engine/resolution.py` → 0 (today 1);
  - `rg -n 'registered_types|get_type_hints' src/functualize/_engine/resolution.py` → 0 (today 6,
    `contract-gap-ea688446.txt`);
  - `rg -n registered_types src/functualize/_engine` → 0 (today 12: `executor.py` 3,
    `middleware.py` 3, `job_middleware.py` 3, `resolution.py` 3; `door-scope-b2719ab8.txt`);
  - `rg -n 'TRANSITIONAL\(parameter-contract/5\.1\)' src` → 0 (today 4). This covers 3.1's
    `Enum` bridge and the three markers above;
  - `git diff b2719ab8 -- src/functualize/_engine/__init__.py` → empty;
  - `git diff b2719ab8 -- src/functualize/_primitives/argument_binding.py` → only the marker's
    comment lines removed;
  - `uv run pytest tests/cli/test_enum_parameter_roundtrip.py -q` green through the door, with the
    member delivered by the binder, not by a click type. `tests/engine/test_binding_door.py` adds the
    same `Color.RED` round trip through the descriptor-only lazy command;
  - `tests/engine/test_binding_door.py` also asserts, cold and warm:
    - for every table row, each parameter's resolution source equals the one its contract's
      `Injection` names;
    - `admitted_contracts(name)` is not `None` for every app-hosted job: discovered cold,
      discovered warm, and registered by `register_dynamic_job`;
    - a dynamically registered job with a missing provider is reported once (B-9) and refused as
      `INVALID` at the door;
    - a config-field key reaches the config model, not `bind`;
    - with a `str` provider registered, a middleware `str` parameter is not resolved by DI
      (F-21 for middleware);
  - **The pytest gate is the whole root suite and the two plugin packages the door reaches**
    (R-6, 2026-11-23). It replaces the narrower line, which found 16 of the draft's 46 failures:
    - `uv run pytest -q` (as `ci.yml:239`; `ci.yml:559` runs it with `-n auto`). It may run in the
      header rule's disjoint chunks, with the eight `_group` modules isolated, but nothing is
      excluded;
    - `uv run pytest -q plugins/adapters/functualize-mcp/tests` and
      `uv run pytest -q plugins/substrates/functualize-substrate-sqlite/tests`, each package in its
      own invocation per the header rule;
    - three known xdist-load flakies are recorded, not waived. They must pass when run
      sequentially together:
      `test_timeout_is_lease_expiry::TestTheWalkActuallyRenews::test_a_walk_renews_during_a_blocked_step`,
      `test_invoke_capture::TestCapture::test_a_timed_out_child_returns_what_it_recorded_by_the_deadline`,
      `test_run_record_run_tags::test_a_shelled_out_func_is_tagged_and_has_no_parent`
      (measured on the draft: 8 passed in 19.94s);
  - `rg -n -e 'id\((function|hints_subject|middleware_fn)\)' src/functualize/_engine` → 0
    (today 14 at `2ccc4cde`, including the docstrings that describe id-keying and the two in the
    deleted `validation.py`; `id-keyed-caches-2ccc4cde.txt`);
  - `tests/engine/test_binding_door.py` also asserts that two distinct functions sharing an address
    in turn never share contracts or a plan: the first is collected and the second is allocated
    into its slot. This is R-1's regression test;
  - `uv run pytest -q tests/integration/test_from_step_reads_e2e.py tests/engine/test_the_walk_on_both_stores.py tests/integration/test_workflow_as_job_e2e.py`
    → green (72 passed on the leader's probe), and a caller key naming a `FromStep` parameter is
    refused as unknown;
  - `uv run pytest -q tests/config/test_unified_config_integration.py` green with that file
    unchanged (R-5): `git diff 2ccc4cde -- tests/config/test_unified_config_integration.py` →
    empty;
  - `test ! -e src/functualize/_engine/validation.py && test ! -e tests/engine/test_unexpected_keyword.py && test ! -e tests/validation/test_arg_validator_properties.py`;
  - `rg -n '_engine\.validation|unexpected_keyword_error|ArgValidator|_build_validation_model' tests/config/test_pep563_annotation_sites.py`
    → 0 (today 8: `:173`, `:178`, `:182-183`, `:192`, `:195`, `:204`, `:207`);
  - `rg -n 'from functualize\._engine\.validation|_engine\.validation import' src tests plugins examples`
    → 0 (today 7: `executor.py:41`, which 5.1 already removes; the three tests' five import lines;
    and one docstring line in the retired properties file);
  - `git diff 2eeb5658 -- tests/config/test_pep563_annotation_sites.py` changes only
    `TestArgumentValidation` (`:172-211` at `2eeb5658`);
  - `tests/engine/test_binding_door.py` also asserts, through `engine.run`:
    - a workflow launch with an unknown key ends `INVALID`;
    - a `**kwargs` job given an unknown key ends `INVALID`;
    - a `Field(ge=1)` parameter given `0` ends `INVALID` with the body not run, in both annotation
      modes;
    - re-binding the bound values is idempotent for every table row with a caller verdict;
  - kit `str-provider.txt` repro: every `str` job runs;
  - kit `unknown-keys.txt` repro: all five surfaces refuse `zzz`;
  - kit `surf_check.py` W-inject → 0 (today 35), W-crash → 0 (today 50), W-type → 0 (today 49),
    W-default → 0 (today 14);
  - `cold_compare.py` → 0 real differences (today F-33 rows C085, C087, E138, H166).
- **Reachability:** `FunctualizeApp.execute(RunRequest)` → `engine.run` → `_execute_lifecycle` →
  `bind`; and the engine's middleware chain → `_resolve_middleware_kwargs` → `build_resolution_plan`.
- **Depends on:** 2.1, 2.2, 2.3, 3.2, 4.4, 0.2.

## Wave 6 — the one schema

### [ ] 6.1 `job_input_schema` reads contracts and merges group options once (D4, F-02, F-13, F-34)

- **Input:**
  - 2.1 and 2.2;
  - `type-maps` gate: `job_schema.py` 3 hits;
  - `injection-by-type-name`: `job_schema.py:185`.
- **[F]:**
  - `src/functualize/_primitives/job_schema.py`;
  - `src/functualize/_cli/info.py`;
  - `src/functualize/app/utils.py`.
- **Work:**
  - The properties are `contract.json_schema`. `required` is the contracts' requiredness.
  - Group options are merged inside `job_input_schema`, so `info` and MCP are identical by
    construction.
  - `TYPE_MAP` goes.
- **Gate/evidence:**
  - `rg -n -w TYPE_MAP src/functualize/_primitives/job_schema.py` → 0 (today 3);
  - kit `check.py` predicates `array`, `type`, `identity` and `required` → 0 rows (today 17, 8, 2
    and 19);
  - `uv run pytest tests/cli/test_schema_surface_parity.py tests/app/test_dynamic_registration.py`.
- **Depends on:** 2.1, 2.2, 4.4.

### [ ] 6.2 The CLI renders `INVALID` as a one-line usage error (pitfalls §25)

- **Input:** 0.2; `click_params.prelude_refusal`.
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `tests/cli/test_invalid_call_rendering.py` (new).
- **Work:** add an `INVALID` arm to `prelude_refusal` and the result delivery: exit 2, one line, no
  frames.
- **Gate/evidence:** the new test runs `func` in a subprocess for a missing, an unknown, an injected
  and a non-converting argument. It asserts `stderr` contains no `File "` and the exit code is 2.
- **Depends on:** 0.2, 5.1. 3.1 has already changed this file (an earlier wave), and 5.1 deletes 3.1's
  `Enum` bridge from it.
- **Moved 2026-11-23** from wave 5 (formerly 5.2) to wave 6: 5.1 now also edits `click_params.py`,
  and two tasks in one wave may not share a file.

## Wave 7 — MCP, the AI tool scope, and the wrappers retired

### [ ] 7.1 MCP registers from the schema, without `exec`, and reports failures (F-12, F-24, F-31)

- **Input:** 6.1; `gates-authoring.txt` `mcp-exec` (1 hit) and `type-maps` (`_server.py` 2,
  `_schema_export.py` 3); fastmcp 4.0.3 `Tool.parameters`, `Tool.run(arguments)`,
  `FastMCP.add_tool(tool)`.
- **[F]:**
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py`;
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py`;
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_schema_export.py`.
- **Work:**
  - One `Tool` subclass per job carries `parameters=job_input_schema(...)`; its `run` builds a
    `RunRequest`.
  - The translator stops merging group options, because 6.1 merges them.
  - A failed run returns `isError: true` with the reason.
  - The schema exports read the one schema. The JSON → TypeScript name map stays: it maps JSON types,
    not Python ones.
  - An enum value is rendered by its JSON type: `1`, not `"1"`. `_schema_export.py:288-289` quotes
    every value today (`spec.md` B-3, *choice sets*; 4.4).
- **Gate/evidence:**
  - `rg -n 'exec\(fn_source' plugins/adapters/functualize-mcp/src` → 0 (today 1);
  - kit: `func mcp serve` starts with G156 present, and every `tools/call` row agrees with HTTP;
  - `uv run pytest plugins/adapters/functualize-mcp/tests` (its own invocation), then
    `uv run pytest tests/plugins/test_mcp_translator.py tests/plugins/test_mcp_translation_properties.py tests/plugins/test_mcp_tools.py`.
- **Depends on:** 6.1.

### [ ] 7.2 The AI `ToolScope` reads the one schema (spec revision S-1)

- **Input:** 6.1; `type-maps` gate: `_tool_scope.py` 4 hits.
- **[F]:** `plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py`.
- **Work:** `_fields_to_schema`, `_python_type_to_json_type` and `_annotation_to_json_type` are
  replaced by `job_input_schema`.
- **Gate/evidence:**
  - `rg -n -e _python_type_to_json_type -e _annotation_to_json_type plugins/domains/functualize-ai/src` → 0 (today 4);
  - `uv run pytest plugins/domains/functualize-ai/tests/`.
- **Depends on:** 6.1.

### [ ] 7.3 Retire the transitional click wrappers

- **Input:** 3.1's `# TRANSITIONAL(7.3)` markers; the 13 test modules in `blast-radius.txt`
  `click_builders`.
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `src/functualize/_cli/main.py`;
  - `tests/adapters/test_click_params_parity.py`, `tests/adapters/test_boolean_negation.py`;
  - `tests/cli/test_arg_marker_unit.py`, `tests/cli/test_positional_arg_properties.py`;
  - `tests/group_options/test_group_options_surfaces.py`;
  - `tests/test_lazy_wrapper.py`, `tests/test_lazy_wrapper_properties.py`;
  - `tests/types/test_flag_grammar_roundtrip.py`;
  - `tests/config/test_surface_boot_config_parity.py`.
- **Work:**
  - Delete the wrappers, `_click_type_for`, `_field_click_type`, `_resolve_type_string`,
    `_option_from_marker` and `_get_list_inner_type`.
  - Callers, including `_cli/main.py:898` `_render_group_option_rows`, call the renderer.
  - Rewrite those tests against `render_click_params`.
- **Gate/evidence:**
  - `rg -n -e TRANSITIONAL\(7.3\) -e _resolve_type_string -e _click_type_for -e _get_list_inner_type src` → 0;
  - `uv run pytest tests/adapters/ tests/cli/ tests/types/ tests/group_options/`.
- **Depends on:** 3.1, 4.1, 4.2, 4.3, 6.2. This file was last changed in wave 6.

## Wave 8 — D7 deletions

### [ ] 8.1 Dead code in `_cli`

- **Input:** `gates-authoring.txt` `dead-symbols`: 17 hits.
- **[F]:**
  - `src/functualize/_cli/annotation_utils.py` (deleted; `parse_annotation` has no remaining caller
    after 7.3);
  - `src/functualize/_cli/completions/engine.py`, `src/functualize/_cli/completions/__init__.py`;
  - `src/functualize/_cli/tui/type_hint_formatter.py` (deleted), `src/functualize/_cli/tui/__init__.py`;
  - `src/functualize/_engine/stdin_reader.py` (a docstring that names the deleted module);
  - `tests/cli/test_annotation_utils_properties.py`, `tests/cli/test_cli_compatible_type.py`;
  - `tests/_cli/test_type_hint_formatter.py`, `tests/cli/tui/test_completer_properties.py`.
- **Work:**
  - Delete `SwappableCompleter`, `format_type_hint` and its `_TYPE_MAP`, and
    `parse_annotation`/`AnnotationInfo` (including the write-only `field_metadata`).
  - Their tests go with them. Any assertion still meaningful moves to 1.1's tests first.
- **Gate/evidence:**
  - `rg -n -w -e SwappableCompleter -e format_type_hint -e field_metadata src` → 0 (today 17 with `coerce_kwargs`, which is 8.2's);
  - `rg -n 'annotation_utils' src plugins/*/*/src -g '*.py'` → only the prose mention in
    `_engine/stdin_reader.py:241`, which is updated (today 4 hits);
  - `uv run pytest tests/cli tests/_cli`.
- **Depends on:** 7.3.

### [ ] 8.2 Dead and superseded code in `app/utils`, `_discovery`, `_config`, `_app`

- **Input:**
  - `dead-symbols`: `coerce_kwargs`, `_resolve_type` (`app/utils.py`);
  - `optional-unwrappers`: 5 hits; `list-unwrappers`: 3 hits;
  - `type-maps`: `providers.py` 6 and `schema_extractor.py` 5;
  - `validate-config`: 5 hits.
- **[F]:**
  - `src/functualize/app/utils.py`;
  - `src/functualize/_discovery/providers.py`;
  - `src/functualize/_discovery/schema_extractor.py`;
  - `src/functualize/_config/job_config.py`;
  - `src/functualize/_app/boot.py`;
  - `tests/test_coerce_kwargs.py`, `tests/test_property_type_coercion_roundtrip.py`;
  - `tests/test_schema_extractor_properties.py` (it references the deleted names 3 times).
- **Work:**
  - Delete `coerce_kwargs` and `_resolve_type`, `_annotation_to_type_str` (the display label now
    comes from the contract), `_unwrap_optional` ×4 and `_unwrap_list` ×2 where a contract now
    answers, and `schema_extractor`'s type maps.
  - `validate_job_config_types` and its boot wiring go; 2.2's refusal replaces them.
  - So do `validate_config_types` (no production caller), `_is_supported_type` and
    `SUPPORTED_TYPES` (`_config/job_config.py:26`). Their only readers are the two validators, so
    the config field set is the contract's B-3 set on every boot path (`spec.md` B-3, *config
    fields*; `literal-path-2c32077e.txt`).
  - Keep any unwrapper still used outside parameter classification, and say which in the task
    record.
- **Gate/evidence:**
  - `rg -n -w -e coerce_kwargs -e _resolve_type -e _annotation_to_type_str -e _JSON_SCHEMA_TYPE_MAP -e validate_job_config_types src` → 0;
  - `rg -n -w -e SUPPORTED_TYPES -e _is_supported_type -e validate_config_types src plugins` → 0
    (today 10 lines, all in `_config/job_config.py`);
  - the behaviour-pattern gate (`job-param-string-reads` plus `injection-by-type-name`) → 0 (today
    7 + 3);
  - `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`, with every finding
    classified;
  - `uv run pytest tests/discovery tests/config`.
- **Depends on:** 7.3, 5.1, 6.1.

## Wave 9 — stop depending on `type_annotation` (SS-3 = B)

Counts measured at authoring time on `6ff7182a` (`matrix/evidence/ss3b-counts.txt`,
`ss3b-remaining.txt`):

- `rg -n '\.type_annotation' src plugins -g '*.py' -g '!**/tests/**'` gives **22 occurrences in
  10 files**.
- `rg -l -w type_annotation src plugins -g '*.py' -g '!**/tests/**'` gives **27 files** (re-run on
  `2058c56b`; the earlier "26" came from a query that left out `plugins/conftest.py`).
  - **17** are already in a wave 0–8 task's `[F]` and are cleared by the rule above.
  - **10** are scoped here:
    - 9.2: `_cli/data/toml_writer.py`, `_cli/tui/panels/config_table.py`,
      `_cli/tui/settings_panel.py`, `_cli/tui/source_chain_detail.py`;
    - 9.3: `plugins/conftest.py`, `_cli/introspect.py`, `_cli/tui/preflight_summary.py`,
      `_cli/tui/source_chain_providers.py`, `_types/flag_grammar.py`, `app/_workflow_view.py`.
  - 9.2 also edits `_cli/tui/chain_resolution.py`, one of the 17 (task 4.2), for the `FieldDef`
    rename.
- Test and fixture files mentioning it: **53**. 8 are in earlier tasks' `[F]`; the other 45 are
  scoped in wave 10.

### [ ] 9.1 The descriptor stops carrying the string: alias and codec keys go, the field becomes transitional

- **Input:**
  - `_types/descriptors.py:87-89` (the `type` property, "Backward-compatible alias for
    type_annotation");
  - `:636` (the codec writes `"type_annotation"`);
  - `:700-701` (the decoder accepts `"type_annotation"` or the legacy `"type"`).
- **[F]:**
  - `src/functualize/_types/descriptors.py`;
  - `tests/test_descriptor.py`, `tests/test_property_field_descriptor_extraction.py`.
- **Work:**
  - Delete the `type` property. Its only reader is `tests/test_descriptor.py:386` (serena
    `find_referencing_symbols`). The one production fallback to a `type` attribute,
    `_tool_scope.py:422`, is rewritten by 7.2.
  - The codec stops writing `type_annotation` and stops reading `type_annotation` **and** the
    legacy `"type"` key. **Decision: no legacy key survives.** Task 0.1 bumped `CACHE_VERSION` from
    25 to 26, so a cache written by an older version is not decoded but rebuilt, once
    (`pitfalls.md` §5). Task 3.2 has since moved it to 27; the argument is unchanged.
  - `type_annotation` gets the default `""`, marked `# TRANSITIONAL(10.1): removed once every
    reader and test is off it`.
- **Gate/evidence:**
  - `rg -n -F -e 'def type(' -e 'else "type"' src/functualize/_types/descriptors.py` → 0 (today 2: `:87`
    the alias, `:701` the legacy key);
  - `uv run pytest tests/test_descriptor.py tests/test_property_field_descriptor_extraction.py tests/discovery/test_cache_manager.py`.
- **Depends on:** 8.1, 8.2.

### [ ] 9.2 The TUI row model's field is renamed `type_label`

- **Input:** `FieldDef` (`_cli/tui/panels/config_table.py:73`) is a separate TUI view-model class
  with its own `type_annotation: str = "str"` (`:86`). It is constructed at `chain_resolution.py:156`,
  `:269`, `settings_panel.py:359` and `source_chain_detail.py:429`, and described in
  `_cli/data/toml_writer.py:6`, `:60` and `:86`.
- **[F]:**
  - `src/functualize/_cli/tui/panels/config_table.py`;
  - `src/functualize/_cli/tui/chain_resolution.py`;
  - `src/functualize/_cli/tui/settings_panel.py`;
  - `src/functualize/_cli/tui/source_chain_detail.py`;
  - `src/functualize/_cli/data/toml_writer.py`.
- **Work:**
  - Rename the field to `type_label`. Job rows fill it from `contract.display`; settings rows fill
    it from `Setting.type` as today.
  - **Why rename a field SS-3 did not name:** it is private TUI state, and with the old name the
    removal gate `rg '\.type_annotation'` could never reach 0 honestly.
- **Gate/evidence:**
  - `rg -n -w type_annotation src/functualize/_cli/tui/panels/config_table.py src/functualize/_cli/tui/chain_resolution.py src/functualize/_cli/tui/settings_panel.py src/functualize/_cli/tui/source_chain_detail.py src/functualize/_cli/data/toml_writer.py` → 0;
  - `uv run pytest tests/cli tests/_cli -k "chain or preflight or settings or toml"`.
- **Depends on:** 8.1, 8.2.

### [ ] 9.3 The remaining production readers read the contract

- **Input:** `ss3b-remaining.txt`, production files not in an earlier task's `[F]`, minus 9.2's.
- **[F]:**
  - `src/functualize/_cli/introspect.py`;
  - `src/functualize/_cli/tui/preflight_summary.py`;
  - `src/functualize/_cli/tui/source_chain_providers.py`;
  - `src/functualize/_types/flag_grammar.py`;
  - `src/functualize/app/_workflow_view.py`;
  - `plugins/conftest.py`, `plugins/adapters/functualize-mcp/tests/conftest.py`.
- **Work:**
  - Display reads become `contract.display`.
  - `flag_grammar.py:153`'s `!= "bool"` becomes `contract.shape.scalar is Scalar.BOOL`.
  - The two plugin conftests build descriptors with `contract=`.
- **Gate/evidence:**
  - `rg -n -w type_annotation` over these 7 files → 0;
  - `uv run pytest tests/cli/test_introspector.py tests/types/`; then, as separate invocations,
    `uv run pytest plugins/adapters/functualize-mcp/tests` and the plugin-package loop, because
    `plugins/conftest.py` is shared by every plugin package.
- **Depends on:** 8.1, 8.2.

## Wave 10 — `type_annotation` is deleted (SS-3 = B)

The tasks in this wave are independent. Each migrates only its own test files. 10.1 deletes the
field, and the wave is complete when the whole suite is green with it gone.

### [ ] 10.1 Delete `FieldDescriptor.type_annotation`

- **[F]:** `src/functualize/_types/descriptors.py`.
- **Work:** remove the field and its `TRANSITIONAL(10.1)` marker. Every constructor already passes
  `contract=` (2.1, 2.2, 4.3).
- **Gate/evidence:**
  - `rg -n '\.type_annotation' src plugins -g '*.py'` → 0 (today 22 occurrences in 10 production
    files);
  - `rg -n -w type_annotation src plugins -g '*.py' -g '!**/tests/**'` → 0 (today 72 occurrences in
    27 files);
  - after 10.2–10.4: `rg -l -w type_annotation tests plugins -g '*.py'` → 0 (today 53);
  - `uv run pytest` (the root suite, at the end of the wave), **and** the plugin-package loop
    `for d in plugins/*/*/tests; do uv run pytest "$d" -q || exit 1; done`.
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.2 Migrate the CLI test modules

- **[F]:**
  - `tests/cli/`:
    - `test_chain_drill_down.py`, `test_chain_kind_aware.py`, `test_cross_panel_sync.py`;
    - `test_diff_view_wiring.py`, `test_enum_parameter_roundtrip.py`;
    - `test_introspect_values.py`, `test_introspect_values_unit.py`, `test_introspector.py`;
    - `test_param_kind.py`, `test_pending_execution_integration.py`;
    - `test_preflight_compact.py`, `test_preflight_enriched.py`, `test_preflight_truncation.py`.
  - `tests/_cli/`:
    - `test_completion_flag_pairs.py`, `test_inline_tui_v2_autocomplete_integration.py`;
    - `test_orchestrator_handoff.py`, `test_secret_masking_surfaces.py`.
- **Work:** construct descriptors with `contract=`, and assert `contract.display` where a test
  checks a type label.
- **Gate/evidence:** `rg -l -w type_annotation` over these 17 files → 0; `uv run pytest tests/cli tests/_cli`.
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.3 Migrate the plugin and discovery test modules

- **[F]:**
  - `tests/plugins/`:
    - `test_mcp_server.py`, `test_mcp_tools.py`, `test_mcp_translation_properties.py`;
    - `test_mcp_translator.py`, `test_mcp_visibility_properties.py`;
    - `test_schema_export.py`, `test_schema_export_properties.py`;
    - `test_three_doors_agree.py`, `test_tool_scope.py`.
  - `tests/discovery/`:
    - `test_di_exclusion_properties.py`, `test_parameter_extraction.py`, `test_schema_extractor.py`;
    - `test_transform_group_filter_property.py`, `test_transform_identity_property.py`;
    - `test_transform_namespace_property.py`, `test_transform_rename_property.py`.
- **Work:** as 10.2.
- **Gate/evidence:** `rg -l -w type_annotation tests/plugins tests/discovery` → 0;
  `uv run pytest tests/plugins tests/discovery`.
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.4 Migrate the remaining test modules

- **[F]:**
  - `tests/test_schema_extractor_properties.py`;
  - `tests/config/test_pep563_annotation_sites.py`;
  - `tests/app/test_dynamic_registration.py`;
  - `tests/group_options/`:
    - `test_combination_matrix.py`, `test_group_options_discovery.py`;
    - `test_group_options_dispatch.py`, `test_tui_group_flags.py`;
  - `tests/tui_group_options/test_write_back_contract.py`.
- **Work:** as 10.2.
- **Gate/evidence:** `rg -l -w type_annotation` over these 8 files → 0; `uv run pytest tests/group_options tests/tui_group_options tests/config tests/app tests/test_schema_extractor_properties.py`.
- **Depends on:** 9.1, 9.2, 9.3.

## Wave 11 — documentation and the parity test

### [ ] 11.1 Docs, changelog, ADR amendments, codemap correction

- **[F]:**
  - `docs/guides/jobs-discovery.md`, `docs/guides/job-config.md`;
  - `CHANGELOG.md`;
  - `contributor/adr/010-job-schema-in-core.md`, `contributor/adr/018-unsatisfiable-jobs-are-reported-not-fatal.md`;
  - `contributor/architecture/codemaps/data-flow.md`.
- **Work:**
  - `jobs-discovery.md` gains *Which parameters are inputs*, rendered from the table.
  - `job-config.md:47-69` now describes the refusal that actually runs.
  - `CHANGELOG.md` lists every visible change (`spec.md` § *Evidence and constraints*), including
    the public API removal of `functualize.types.FieldDescriptor.type_annotation` and its `type`
    alias (SS-3 = B), with the replacement: `FieldDescriptor.contract`.
  - ADR-010 records that its renderer now reads contracts. ADR-018 records the cold-path fix and
    the `UnsupportedParameter` sibling.
  - `data-flow.md` §2's priority line matches the code: the caller never reaches an `INJECTED`
    parameter.
- **Gate/evidence:** `uv run mkdocs build --strict` (`mkdocs.yml` is at the repository root), and
  11.2's docs-table test.
- **Depends on:** 10.1, 10.2, 10.3, 10.4.

### [ ] 11.2 The parity test (AC-10), with the three cross-builder tests folded in

- **[F]:**
  - `tests/surfaces/test_parameter_surface_parity.py` (new), `tests/surfaces/test_parameter_docs_table.py` (new);
  - `tests/adapters/test_cold_warm_parity.py`, `tests/config/test_click_builder_agreement.py` and
    `tests/cli/test_schema_surface_parity.py` (deleted, assertions migrated).
- **Work:**
  - From `tests/_support/parameter_matrix.py`, drive help, bash, zsh, SmartBar, the TUI door, info,
    the MCP schema and call, HTTP and Lambda for every row, cold and warm, in both PEP 563 modes.
    Use subprocesses where `pitfalls.md` §23 and §25 require them.
  - Assert the row's verdict on every surface.
- **Gate/evidence:** green under `uv run pytest tests/surfaces/`, and runnable within the 600 s
  tool-call cap. If not, split it by row group, as the `test-tiers` skill prescribes.
- **Depends on:** 10.1, 10.2, 10.3, 10.4. The docs-table half also depends on 11.1.

## Wave 12 — checkpoint

### [ ] 12.1 Acceptance checkpoint (AC-1 to AC-13)

- **Work:** run every gate in `spec.md` § *Acceptance checks* from `matrix/`, cold and warm, in both
  PEP 563 modes. That includes the coverage census (0 executed statements in deleted symbols:
  vacuous, because they are gone, so the census also confirms their files no longer exist) and the
  repository's five checks (`pytest` meaning the root suite **plus** the plugin-package loop
  `for d in plugins/*/*/tests; do uv run pytest "$d" -q || exit 1; done`).
- **Gate/evidence:** every AC row's "must show after the change" column, pasted as command plus
  output into the task record.
- **Depends on:** all earlier tasks.

## Wave 13 — artifact clearing

### [ ] 13.1 Two-push clearing sequence

- **Work:**
  - Migrate the durable half (the decision to ADRs, already done in 11.1; the status to
    `.spec/STATUS.md`).
  - Push the feature commits and let validation pass.
  - Then make one deletion-only commit, `git rm -r .spec/features/parameter-contract`, and push it.
- **Gate/evidence:** `git ls-files .spec/features/parameter-contract` is empty; `git show --stat HEAD`
  shows deletions only; `spec-artifacts-cleared` passes.
- **Depends on:** 12.1.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["0.1", "0.2", "0.3", "0.4", "0.5"]},
    {"id": 1, "tasks": ["1.1", "1.2"]},
    {"id": 2, "tasks": ["2.1", "2.2", "2.3"]},
    {"id": 3, "tasks": ["3.1", "3.2"]},
    {"id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4"]},
    {"id": 5, "tasks": ["5.1"]},
    {"id": 6, "tasks": ["6.1", "6.2"]},
    {"id": 7, "tasks": ["7.1", "7.2", "7.3"]},
    {"id": 8, "tasks": ["8.1", "8.2"]},
    {"id": 9, "tasks": ["9.1", "9.2", "9.3"]},
    {"id": 10, "tasks": ["10.1", "10.2", "10.3", "10.4"]},
    {"id": 11, "tasks": ["11.1", "11.2"]},
    {"id": 12, "tasks": ["12.1"]},
    {"id": 13, "tasks": ["13.1"]}
  ]
}
```
