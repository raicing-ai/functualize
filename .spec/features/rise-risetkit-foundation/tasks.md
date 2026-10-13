# Rise / RiseKit foundation — tasks

Execute against `spec.md` (**revision 6: Rise v1 on 0.5.0 as released,
including core class discovery and scoped vault v3**), `contracts.md` and
`plan.md`.

- **Wave ordering is binding.** No task in wave N+1 starts while wave N holds an
  unchecked task.
- **[6] Wave 0 (T14) is the entry gate.** No other task starts until a
  **released** 0.5.0 contains MCH-184 (core class discovery) and MCH-185
  (scoped vault v3), and meets contracts C11.
- **Execute does not begin** until the owner has confirmed revision 6
  (spec §11).
- Discovery-dependent tasks are stated against C11's requirements. Their exact
  call shapes come from the released API and are recorded in T14. They are not
  invented here.

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

## Wave 0 — entry gate [6]

- [ ] **T14** STOP until a released 0.5.0 contains both prerequisites
  - Not work: a gate.
  - *Gate:*
    - `git tag -l v0.5.0` exists, and its release notes include MCH-184 and
      MCH-185;
    - each requirement in contracts C11 (R1.1–R1.10, R7.1–R7.5) is checked
      against the released code, with one line of evidence per requirement,
      recorded here;
    - the call shapes T13 and T15–T17 will use are recorded here, taken from
      the released API: how a subject class is discovered, the canonical job's
      name and group, how an address and fixed literals are passed, and the
      vault `--group <address>` spelling.
    - **Any requirement unmet returns this feature to Specify. It is never
      worked around.**

## Wave 1 — the record

- [ ] **T1** ADR and the committed-reference section
  - Write ADR-031, from template `contributor/adr/000-template.md`. Re-check
    `ls contributor/adr` first and take the next free number. It carries
    B1–B6, the side-ownership table, and the AFTER diagram from plan.md.
  - Add a *Rise and RiseKit* section to `.spec/ARCHITECTURE.md`. It states the
    layering, cites SD/5407068 v18, and names core class discovery (P-1,
    MCH-184) and scoped vault v3 (P-7, MCH-185) as the 0.5.0 prerequisites it
    consumes.
  - *Files:* `contributor/adr/031-rise-layers-on-functualize.md` (new),
    `.spec/ARCHITECTURE.md`
  - *Gate:* the ADR contains "B1" through "B6" (`rg -c 'B[1-6]'` ≥ 6). No
    record links a gitignored path.

## Wave 2 — packaging

- [ ] **T2** Three workspace members, lock and suite isolation
  - Create `plugins/domains/functualize-rise/`, `plugins/domains/functualize-risekit/`
    and `plugins/substrates/functualize-rise-cloudflare/`. Each gets
    `pyproject.toml`, `README.md`, `LICENSE`, `NOTICE` and
    `src/<pkg>/__init__.py`, copied from the jev package's shape.
  - Dependencies follow C1, with `functualize>=0.5.0,<1.0.0`, the released 0.5.0 [6]. Only `functualize-rise` declares the
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

## Wave 3 — identities

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

## Wave 4 — roles and the realization port

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

## Wave 5 — the declaration model

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

## Wave 6 — environments and descriptors

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

## Wave 7 — the judges

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

## Wave 8 — the first production path, and the toolkit

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

## Wave 9 — the provider, offline

- [ ] **T13** `functualize-rise-cloudflare`: contracts, providers, transport
  - `D1Database` (`cloudflare.d1@1`) and `WorkerScript` (`cloudflare.worker@1`,
    with a `Ref` to D1, `required`), per C3.
  - `CloudflareApiD1` and `CloudflareApiWorker`.
  - A transport with a real HTTP client and a fake.
  - The token is a `Secret[str]` configuration field (S31).
  - **[6]** No binding plugin. The classes are reached through core class
    discovery, in the way T14 recorded (C11 R1.1).
  - *Files:* `plugins/substrates/functualize-rise-cloudflare/src/functualize_rise_cloudflare/contracts.py`,
    `…/providers.py`, `…/transport.py`, `tests/plugins/rise/test_cloudflare_offline.py`
  - *Gate:*
    - `assert_conformant` passes both providers;
    - in an app on the released 0.5.0, the canonical `up` and `diagnose` jobs
      of both classes are discovered (R1.1, R1.2);
    - run through the canonical job against the fake, `up` creates when absent
      and changes nothing when present (S29);
    - no Rise module names a provider class
      (`rg -n 'CloudflareApi' plugins/domains/functualize-rise` is empty).

## Wave 10 — dispatch

- [ ] **T15** `up.py`, and `rise diagnose` / `rise up` through `Invoke`
  - `observe` is bound to `Invoke` of the subject's canonical `diagnose` job
    with its address, and `up` likewise (B4, S21, S23; C11 R1.4). Declaration
    literals are passed as fixed values in the way T14 recorded (R1.6).
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
## Wave 11 — the discovered jobs judged

- [ ] **T16** Validate findings 11 and 13 against the discovered canonical jobs
  - Finding 11 compares the generated descriptor with the canonical job's
    merged declaration tags and parameters (C11 R1.8).
  - Finding 13 checks that every in-scope contract operation has its canonical
    job (S15.13; R1.3).
  - *Files:* `…/functualize_rise/validate.py`, `tests/plugins/rise/test_validate_discovered.py`
  - *Gate:*
    - `func builtin info` lists the three tags on a fixture's canonical job,
      next to an author's own `@job` option (R1.8);
    - a hand-edited descriptor mismatch yields finding 11;
    - a contract operation with no discovered job yields finding 13.

## Wave 12 — the forcing case end to end

- [ ] **T17** Example project and live tier (S32, C12)
  - An example project with `cloudflare_dev() -> Environment` holding
    `d1.main` and `worker.api`. It runs offline with the fake transport, plus a
    live tier that skips without `CLOUDFLARE_ACCOUNT_ID` or
    `CLOUDFLARE_API_TOKEN` and names the missing variable.
  - It creates only `rise-test-`-prefixed resources.
  - **[6]** The token is stored **once**, under the D1 subject's address, as a
    vault v3 group (C11 R7.1), using the spelling T14 recorded. Both `up` and
    `diagnose` resolve it (R7.4).
  - *Files:* `plugins/substrates/functualize-rise-cloudflare/examples/cloudflare_dev/` (new),
    `tests/plugins/rise/test_forcing_case.py`, `tests/plugins/rise/test_forcing_case_live.py`
  - *Gate:*
    - offline: three records; worker and root fail with D1 absent, with a
      non-zero exit; `up --scope cloudflare_dev.d1.main` then makes the
      diagnosis pass, and a second `up` changes nothing;
    - live: skips with a named reason when credentials are absent;
    - one vault entry serves both operations of the subject (R7.4).

## Wave 13 — closing checkpoint

- [ ] **T18** Traceability, status, the full quality run
  - Add the traceability table to `research.md` § *Traceability review*: every
    package, public name and acceptance criterion maps to a spec §8 row (AC-14).
  - Add the `.spec/STATUS.md` open-features entry.
  - Run every gate, the five quality commands
    (`ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`,
    `pytest`), and
    `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`.
    Classify each finding KNOWN or UNMARKED.
  - *Files:* `.spec/features/rise-risetkit-foundation/research.md`,
    `.spec/STATUS.md`
  - *Gate:*
    - all gates in § *Gates* are clean;
    - all five commands pass;
    - the dead-code delta lists no `TRANSITIONAL` marker (removed in T15).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T14"] },
    { "id": 1, "tasks": ["T1"] },
    { "id": 2, "tasks": ["T2"] },
    { "id": 3, "tasks": ["T3"] },
    { "id": 4, "tasks": ["T4", "T8"] },
    { "id": 5, "tasks": ["T5"] },
    { "id": 6, "tasks": ["T6", "T7"] },
    { "id": 7, "tasks": ["T9", "T10"] },
    { "id": 8, "tasks": ["T11", "T12"] },
    { "id": 9, "tasks": ["T13"] },
    { "id": 10, "tasks": ["T15"] },
    { "id": 11, "tasks": ["T16"] },
    { "id": 12, "tasks": ["T17"] },
    { "id": 13, "tasks": ["T18"] }
  ]
}
```
