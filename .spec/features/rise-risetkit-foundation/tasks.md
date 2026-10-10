# Rise / RiseKit foundation — tasks

Execute against `spec.md` (**revision 5: Rise v1 on the 0.5.0 cut**),
`contracts.md` and `plan.md`.

- **Wave ordering is binding.** No task in wave N+1 starts while wave N holds an
  unchecked task.
- **[5] No core dependency.** Every task runs on Functualize 0.5.0's public
  API. Revision 4.1's class-discovery checkpoint is removed, and provider-owned
  binding (T14) stands in for it.
- **Execute does not begin** until the owner has confirmed revision 5 (spec
  §11) and approved shape amendment A-1 on SD/5407068.

## Gates

Gates were measured on `ba36b859` + this branch, 2026-10-05, and re-checked on `4e816a0f` (0.5.0 base), 2026-10-10, with unchanged results.

| Gate | Command | Asserts | Authoring-time state |
|---|---|---|---|
| G-core | `git diff --stat origin/master -- src/functualize` | empty: B1, AC-2 | empty (0 lines) |
| G-core-import | `rg -l -e 'functualize_rise' -e 'functualize_risekit' src/functualize` | empty: B1 | 0 files |
| G-private | `rg -l -e 'from functualize\._' -e 'import functualize\._' plugins/domains/functualize-rise plugins/domains/functualize-risekit plugins/substrates/functualize-rise-cloudflare tests/plugins/rise` | empty: public API only | directories absent (`rg` exits 2). First real run in T2 |
| G-B2 | `rg -l 'functualize_risekit' plugins/domains/functualize-rise` | empty: Rise never imports RiseKit | absent; first run in T2 |
| G-B5 | `rg -n -i 'cloudflare' plugins/domains/functualize-risekit` and `rg -l 'functualize_rise_cloudflare' plugins/domains/functualize-rise plugins/domains/functualize-risekit` | both empty: AC-11 | absent; first run in T2 |
| G-groups | `uv run pytest -q --no-header tests/spec/test_every_declared_group_has_a_reader.py` | no new entry-point group: B6, AC-12 | **30 passed** |
| G-no-tracker | `rg -n -i -e atlassian -e jira -e confluence <the three package src dirs>` | empty: AC-14, no runtime path to either tool | absent; first run in T2 |
| G-secret | the canary test (T10, T15) | no secret byte in any output: AC-13 | lands with T10 |

**Test location.** Tests live in `tests/plugins/rise/`, collected by the root
`pytest` (`testpaths = ["tests"]`), following the jev precedent at
`tests/plugins/test_jev_wire.py`. No CI workflow change. The three
distributions are hidden from the root suite's entry-point discovery (T2), so
tests construct apps with `PluginSources(explicit_plugins=[RisePlugin()])`, or
use the `installed_plugins` marker where the entry point itself is under test.

**Shared infrastructure.** T2 touches `uv.lock` and `tests/conftest.py`. Verify
it with the tip tier, not a local full run.

## Wave 0 — the record

- [ ] **T1** ADR and the committed-reference section
  - Write ADR-031, from template `contributor/adr/000-template.md`. Re-check
    `ls contributor/adr` first and take the next free number. It carries
    B1–B6, the side-ownership table, and the AFTER diagram from plan.md.
  - Add a *Rise and RiseKit* section to `.spec/ARCHITECTURE.md`. It states the
    layering, cites SD/5407068 v18 and amendment A-1, and names provider-owned
    binding as the v1 stand-in for core class discovery (P-1).
  - *Files:* `contributor/adr/031-rise-layers-on-functualize.md` (new),
    `.spec/ARCHITECTURE.md`
  - *Gate:* the ADR contains "B1" through "B6" (`rg -c 'B[1-6]'` ≥ 6). No
    record links a gitignored path.

## Wave 1 — packaging

- [ ] **T2** Three workspace members, lock and suite isolation
  - Create `plugins/domains/functualize-rise/`, `plugins/domains/functualize-risekit/`
    and `plugins/substrates/functualize-rise-cloudflare/`. Each gets
    `pyproject.toml`, `README.md`, `LICENSE`, `NOTICE` and
    `src/<pkg>/__init__.py`, copied from the jev package's shape.
  - Dependencies follow C1, with `functualize>=0.5.0,<1.0.0` [5]. Only `functualize-rise` declares the
    `functualize.plugins` entry `rise = "functualize_rise.plugin:RisePlugin"`;
    `plugin.py` is a stub in this task.
  - Refresh `uv.lock`: workspace members are added, no dependency moves.
  - Add the three names to `_DEFAULT_CHANGING_DISTRIBUTIONS` in
    `tests/conftest.py`, with the reason "adds the `rise` job group".
  - *Files:* the three package trees (new), `uv.lock`, `tests/conftest.py`
  - *Gate:*
    - `uv sync --frozen --all-extras --all-packages` succeeds;
    - `git diff origin/master -- uv.lock | rg '^[-+]version'` shows no version
      line for an existing package;
    - G-private, G-B2, G-B5, G-groups and G-no-tracker are clean.

## Wave 2 — identities

- [ ] **T3** `identity.py`: `ContractId`, `OperationId`, `Address`
  - Frozen value objects that parse and format the C4 grammar.
  - `OperationId` reserves `+strategy`: it parses, and is refused at selection
    (S24).
  - `Address` joins and splits on dots, and refuses a local id that contains a
    dot.
  - *Files:* `plugins/domains/functualize-rise/src/functualize_rise/identity.py`,
    `tests/plugins/rise/test_identity.py`
  - *Gate:* `uv run pytest -q tests/plugins/rise/test_identity.py`. Every C4
    example round-trips, and each malformed form in a table of at least 8 is
    refused.

## Wave 3 — roles and the realization port

- [ ] **T4** `roles.py`: role inference, the `@role` override, tag generation
  - The defaults of C5.
  - `@role(<role>)` is legal only on an abstract method of a contract or a local
    subject. Implementations inherit it.
  - Tag strings come from `identity`.
  - *Files:* `…/functualize_rise/roles.py`, `tests/plugins/rise/test_roles.py`
  - *Gate:* the test covers every C5 row, an unlisted verb defaulting to
    `mutating`, an inherited override, and `@role` on a concrete method being
    refused.
- [ ] **T8** `realization.py`: `RealizationStore` Protocol, `LocalRealizationStore`
  - Append-only records with the C9 keys, `shared: false` (settled OD-2), and
    `secrets` as a source class only.
  - The file lives under Functualize's per-project cache directory. Use no
    module-level state.
  - Mark `# TRANSITIONAL(T15): reached by rise up when T15 wires dispatch`.
  - *Files:* `…/functualize_rise/realization.py`,
    `tests/plugins/rise/test_realization.py`
  - *Gate:* append-then-read returns records in order. A second append never
    rewrites the first. A canary secret value never appears in the file bytes.

## Wave 4 — the declaration model

- [ ] **T5** `subject.py`: `Subject`, `@contract`, `Realization`, `Observation`, `Ref`
  - `Subject` is a frozen pydantic model, so construction does no I/O (S1).
  - `@contract("ns.name@major")` marks an abstract subject and records its
    realization type (S2). A concrete class with no contract ancestor gets
    `local:<qualified name>`.
  - `Ref[T]` and `Ref["address"]` default to ordering + `required`. The
    optional and informational spellings are fixed here and documented in
    contracts.md C3; this task updates C3.
  - **[5]** Add a test that a `Secret[str]` field of a frozen subject keeps its
    marker and is masked (`'•••'`) in the run record's `resolved_inputs` when
    the subject is a job's config parameter. This was confirmed on 0.5.0 by
    the spec §0 probe (F-2).
  - *Files:* `…/functualize_rise/subject.py`,
    `tests/plugins/rise/test_subject.py`, `.spec/features/rise-risetkit-foundation/contracts.md`
  - *Gate:*
    - a frozen instance refuses mutation;
    - two equal configurations compare equal;
    - the contract identity is readable from the class without instantiating it;
    - the `Secret[str]` test passes on 0.5.0.

## Wave 5 — environments and descriptors

- [ ] **T6** `environment.py`: `Environment`, addresses, `Ref` resolution, scope, root
  - S9–S13. An environment is recognized by the return annotation
    `-> Environment` of a job function.
  - Evaluation is lazy and fixed-values-only (S10).
  - **[5]** Recognize `-> Environment` through `typing.get_type_hints`, so that a
    module using `from __future__ import annotations` also works. Test both
    forms.
  - The unscoped root is read from `[rise] root` in Functualize configuration.
    With no root and not exactly one environment, refuse with `USAGE` and list
    the addresses found.
  - *Files:* `…/functualize_rise/environment.py`,
    `tests/plugins/rise/test_environment.py`
  - *Gate:*
    - a nested tree yields the expected addresses;
    - `Ref` resolves by address and by type, and an ambiguous `Ref` is
      reported;
    - an environment job not in scope is never called (counter = 0);
    - `FUNCTUALIZE_ENV=prod` changes the configuration overlay and leaves the
      selected scope unchanged (AC-6).
- [ ] **T7** `descriptor.py`: generate and cache
  - C6 JSON from a contract or local class. It is cached keyed by
    `source_digest`, and never committed.
  - *Files:* `…/functualize_rise/descriptor.py`,
    `tests/plugins/rise/test_descriptor.py`
  - *Gate:*
    - the descriptor of a fixture contract equals a golden;
    - a second generation is a cache hit;
    - a changed source invalidates the cache;
    - no secret value appears, only `"secret": true`.

## Wave 6 — the judges, and the binding

- [ ] **T9** `validate.py`: findings 1–10 and 12 of S15
  - Finding 11 (descriptor vs runtime metadata) lands in T16.
  - Imports declaration modules and evaluates in-scope environment jobs. Runs no
    operation.
  - Split into `validate/` modules if it passes 400 lines.
  - *Files:* `…/functualize_rise/validate.py`,
    `tests/plugins/rise/test_validate.py`, `tests/plugins/rise/fixtures/` (new)
  - *Gate:* one fixture per finding, 11 in total. Each asserts its finding code;
    a clean fixture yields none.
- [ ] **T10** `diagnose.py`: traversal, assessment, NDJSON (engine only)
  - The engine takes an injected `observe(address) -> Observation`. It covers:
    - S17–S20: ordering edges only, memoized by address, required/optional
      aggregation, referential `required_dependency_failed`;
    - deterministic order (dependencies first, ties alphabetical);
    - a root record last;
    - a failed observation becomes a record, never a traceback.
  - Mark `# TRANSITIONAL(T15): observe() is bound to Invoke in T15`.
  - *Files:* `…/functualize_rise/diagnose.py`,
    `tests/plugins/rise/test_diagnose.py`
  - *Gate:*
    - every line parses as JSON with the C8 keys;
    - a diamond fixture observes the shared subject **once**;
    - an optional failure leaves the parent `pass`, and a required one fails it;
    - an observer that raises yields `observation_error`;
    - the canary secret is absent (G-secret).

- [ ] **T14** **[5]** `binding.py`: `bind(*classes) -> list[Job]`
  - One `Job` per (class, operation), named per contracts C5: group
    `<ns>.<name>.<candidate>` (local: the class `group` or
    `local.<snake_class_name>`), and name `<group>.<verb>`.
  - The wrapper's parameters are `subject: <class>` (the job config model) and
    `address: str`. It calls the unbound method on the resolved subject and
    returns its value.
  - The declaration is the method's own `JobDeclaration` (from
    `__functualize_job__`, documented at `docs/guides/jobs-discovery.md:377`),
    with `rise:op:*`, `rise:implements:*` and `effect:*` appended through
    `dataclasses.replace`. Never re-apply `@job` (spec §0, F-5).
  - Refuse a missing `candidate` on a contract implementation. Refuse a
    duplicate name within one call, naming both classes.
  - *Files:* `…/functualize_rise/binding.py`,
    `tests/plugins/rise/test_binding.py`
  - *Gate:* in an app booted with an explicit plugin that calls `bind`:
    - the jobs list as `cloudflare`-shaped fixture groups;
    - `declaration.tags` holds the three generated tags, **and** an author's
      `@job(category=…)` survives;
    - a field resolves from `[<group>.<verb>]` in `config.base.toml`;
    - a flattened kwarg beats that file value (the explicit tier, F-4);
    - **reachability:** dropping the `add_job_provider` call makes the listing
      test fail.

## Wave 7 — the first production path, and the toolkit

- [ ] **T11** `jobs.py` and `plugin.py`: `rise validate`
  - `RisePlugin` registers `Job(validate, name="validate", group="rise")`
    through `add_job_provider(StaticProvider([...]))` (C2).
  - Job bodies import the engine modules lazily.
  - `diagnose` and `up` are **not** registered yet.
  - Exit codes follow C10.
  - *Files:* `…/functualize_rise/jobs.py`, `…/functualize_rise/plugin.py`,
    `tests/plugins/rise/test_cli_validate.py`
  - *Gate:*
    - `func rise validate` runs in an app booted with `RisePlugin` and exits
      `OK` on a clean fixture and `JOB_RAISED` on findings;
    - unscoped with two environments, it exits `USAGE`;
    - **reachability:** commenting out the `add_job_provider` call makes the
      CLI test fail. Commit before sabotaging.
- [ ] **T12** RiseKit: remote-resource substrate and conformance helper
  - `RemoteResource(Subject)` and `RemoteResourceObservation` (states
    `present | absent | error`, passing `present`), with a builder that
    validates on construction.
  - `testing.assert_conformant(cls)` runs Rise's `validate` on a class.
  - *Files:* `plugins/domains/functualize-risekit/src/functualize_risekit/substrates/remote_resource.py`,
    `…/functualize_risekit/testing.py`, `tests/plugins/rise/test_risekit.py`
  - *Gate:*
    - a malformed observation is refused at construction;
    - `assert_conformant` passes a conformant fixture and raises on one that is
      missing `up`;
    - G-B5 and G-B2 are clean.

## Wave 8 — the provider, offline

- [ ] **T13** `functualize-rise-cloudflare`: contracts, providers, transport, binding plugin
  - `D1Database` (`cloudflare.d1@1`) and `WorkerScript` (`cloudflare.worker@1`,
    with a `Ref` to D1, `required`), per C3.
  - `CloudflareApiD1` and `CloudflareApiWorker`, each with `candidate = "api"`.
  - A transport with a real HTTP client and a fake.
  - The token is a `Secret[str]` configuration field (S31).
  - **[5]** `plugin.py`: a module-level `plugin` that registers
    `StaticProvider(bind(CloudflareApiD1, CloudflareApiWorker))`, marked
    `# TRANSITIONAL(P-1): delete when core class discovery ships`. Declare it
    under `functualize.plugins` as `rise-cloudflare` (contracts C2), in the
    package's `pyproject.toml`.
  - *Files:* `plugins/substrates/functualize-rise-cloudflare/src/functualize_rise_cloudflare/contracts.py`,
    `…/providers.py`, `…/transport.py`, `…/plugin.py`,
    `plugins/substrates/functualize-rise-cloudflare/pyproject.toml`,
    `tests/plugins/rise/test_cloudflare_offline.py`
  - *Gate:*
    - `assert_conformant` passes both providers;
    - in an app booted with the provider plugin, the jobs
      `cloudflare.d1.api.up` and `cloudflare.d1.api.diagnose` are listed;
    - run through `app.execute` against the fake, `up` creates when absent and
      changes nothing when present (S29);
    - no Rise module names a provider class
      (`rg -n 'CloudflareApi' plugins/domains/functualize-rise` is empty).

## Wave 9 — dispatch

- [ ] **T15** `up.py`, and `rise diagnose` / `rise up` through `Invoke`
  - `observe` is bound to `Invoke(<canonical diagnose job>, address=…,
    **literal_fields)`, and `up` likewise (B4, S21, S23). Literal fields are
    the instance's `model_fields_set`: the explicit tier (spec S6, F-4).
  - Single-candidate selection: several candidates refuse with `REFUSED` and
    list them (S24). A destructive role is refused (S27).
  - Dependency-ordered `up` (S25). Each realization is appended through
    `LocalRealizationStore` (S26).
  - Register the `diagnose` and `up` jobs in `RisePlugin`, and remove the
    T8/T10 `TRANSITIONAL` markers.
  - *Files:* `…/functualize_rise/up.py`, `…/functualize_rise/jobs.py`,
    `…/functualize_rise/plugin.py`, `…/functualize_rise/diagnose.py`,
    `…/functualize_rise/realization.py`, `tests/plugins/rise/test_cli_dispatch.py`
  - *Gate:*
    - the run record of each operation shows a child run under the `rise`
      command (ancestry);
    - a second `up` reports converged;
    - two candidates produce `REFUSED`;
    - the canary secret is absent from stdout, the NDJSON and the realization
      file;
    - **reachability:** removing the `Invoke` binding makes the dispatch test
      fail.
## Wave 10 — the binding judged

- [ ] **T16** **[5]** Validate findings 11 and 13 against the bound jobs
  - Finding 11 compares the generated descriptor with the bound job's
    `declaration.tags` and parameters.
  - Finding 13 checks that every in-scope contract operation has its canonical
    job registered (spec S15.13). That covers an unbound class and a name lost
    to a cross-plugin collision.
  - *Files:* `…/functualize_rise/validate.py`, `tests/plugins/rise/test_validate_bound.py`
  - *Gate:*
    - `func builtin info` lists the three tags on a fixture's canonical job;
    - a hand-edited descriptor mismatch yields finding 11;
    - an environment referencing a class whose plugin is not loaded yields
      finding 13;
    - so do two plugins binding the same canonical name.

## Wave 11 — the forcing case end to end

- [ ] **T17** Example project and live tier (S32, C12)
  - An example project with `cloudflare_dev() -> Environment` holding
    `d1.main` and `worker.api`. It runs offline with the fake transport, plus a
    live tier that skips without `CLOUDFLARE_ACCOUNT_ID` or
    `CLOUDFLARE_API_TOKEN` and names the missing variable.
  - It creates only `rise-test-`-prefixed resources.
  - *Files:* `plugins/substrates/functualize-rise-cloudflare/examples/cloudflare_dev/` (new),
    `tests/plugins/rise/test_forcing_case.py`, `tests/plugins/rise/test_forcing_case_live.py`
  - *Gate:*
    - offline: three records; worker and root fail with D1 absent, with a
      non-zero exit; `up --scope cloudflare_dev.d1.main` then makes the
      diagnosis pass, and a second `up` changes nothing;
    - live: skips with a named reason when credentials are absent.

## Wave 12 — closing checkpoint

- [ ] **T18** Traceability, status, the full quality run
  - Add the traceability table to `research.md` § *Traceability review*: every
    package, public name and acceptance criterion maps to a spec §8 row (AC-14).
  - Add the `.spec/STATUS.md` open-features entry. It records the v1
    limitations (per-operation config sections and vault entries, spec S6/S7),
    the core finding F-7 (`get_job_config_section` disagrees with the run) for a
    separate ticket, and the migration triggers P-1, P-8 and vault v3.
  - **[5]** Add a `README.md` section to the provider showing the
    per-operation vault entries. Verify the exact `--job` target spelling by
    running `func builtin vault put --job cloudflare.d1.api.up --field
    api_token` in a scratch project **before** writing it.
  - Run every gate, the five quality commands
    (`ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`,
    `pytest`), and
    `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`.
    Classify each finding KNOWN or UNMARKED.
  - *Files:* `.spec/features/rise-risetkit-foundation/research.md`,
    `.spec/STATUS.md`, `plugins/substrates/functualize-rise-cloudflare/README.md`
  - *Gate:*
    - all gates in § *Gates* are clean;
    - all five commands pass;
    - the dead-code delta lists no `TRANSITIONAL` marker (removed in T15).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T2"] },
    { "id": 2, "tasks": ["T3"] },
    { "id": 3, "tasks": ["T4", "T8"] },
    { "id": 4, "tasks": ["T5"] },
    { "id": 5, "tasks": ["T6", "T7"] },
    { "id": 6, "tasks": ["T9", "T10", "T14"] },
    { "id": 7, "tasks": ["T11", "T12"] },
    { "id": 8, "tasks": ["T13"] },
    { "id": 9, "tasks": ["T15"] },
    { "id": 10, "tasks": ["T16"] },
    { "id": 11, "tasks": ["T17"] },
    { "id": 12, "tasks": ["T18"] }
  ]
}
```
