# Rise / RiseKit foundation — tasks

Execute against `spec.md`, `contracts.md` and `plan.md`. Wave ordering is
binding: no task in wave N+1 starts while wave N holds an unchecked task.
**D-2 (plan.md § *The decision for the member*) must be answered before T2
runs.** T1 is records only and lands on the member's word.

## Gates

| Gate | Command / check | Asserts | Authoring-time state |
|---|---|---|---|
| G1 | `git diff --stat origin/master -- src/functualize` | empty output: B1, AC-2 | run 2026-10-01 on this branch: empty. Re-run in T12 |
| G2 | `uv run pytest plugins/domains/functualize-rise/tests/test_orphan_behavior.py -q` | with rise loaded, no orphan warning for `rise`; with the plugin disabled, the warning appears and the job still runs (S2, S3) | lands with T6 |
| G3 | `uv run pytest plugins/domains/functualize-rise/tests/test_handwritten_parity.py -q` | a RiseKit-free, hand-written fixture validates and diagnoses identically to its RiseKit-built twin (B2, AC-3) | lands with T5 |
| G4 | T3's test selection | S7's eight findings asserted one by one; exit 0 when clean, non-zero on findings (S8) | lands with T3 |
| G5 | T4's test selection | C6 keys and types per line; package record last; S11–S13 aggregation, cycle and exit status; S4 materialization | lands with T4 |
| G6 | T8's test selection | live tier skips without credentials and names the missing variable; `rise-test-` prefix only (C8) | lands with T8 |
| G7 | `uv run pytest examples/ -q` | the example project is collected and green (AC-7) | lands with T10 |
| G8 | `rg -n -i 'cloudflare' plugins/domains/functualize-risekit/` → no output; and `rg -n 'functualize_rise_cloudflare' plugins/domains/functualize-rise/ plugins/domains/functualize-risekit/ src/` → no output | B5, AC-10: no provider inside RiseKit; nothing below the provider names it | directories do not exist yet (`rg` exits 2). Run first in T7; re-run in T12 |
| G9 | `uv run pytest tests/spec/test_every_declared_group_has_a_reader.py -q` | no new `functualize.*` entry-point group (B6, AC-11) | **run 2026-10-02 on this branch: 30 passed.** Re-run in T2, T8 and T12 |
| G10 | T11's traceability table in `research.md` § *Traceability review* | every package, public name and AC delivered maps to a spec.md §8 row with page id + version and ticket; and `rg -n -i 'atlassian\|jira\|confluence' plugins/domains/functualize-rise/src plugins/domains/functualize-risekit/src plugins/substrates/functualize-rise-cloudflare/src` → no output (no runtime path to either tool) | lands with T11 |
| G11 | `rg -n 'from functualize\._\|import functualize\._' plugins/domains/functualize-rise/src plugins/domains/functualize-risekit/src plugins/substrates/functualize-rise-cloudflare/src` → no output; and `rg -n 'functualize_risekit' plugins/domains/functualize-rise/src` → no output | public API only (the plugin guide's rule; 9 existing plugin files break it today, and none may be added); B2's import half | run per package in T2, T7 and T8; re-run in T12 |

Plugin tests run as `uv run pytest plugins/<group>/<pkg>/tests/ -q`, because
root pytest does not collect them. T2, T7 and T8 touch `pyproject.toml`,
`uv.lock` and `.github/workflows/ci.yml` (shared infrastructure). The step-tier
mapper exits 3 on those files, so they verify with a tip-tier dispatch, not a
local full run.

## Wave 0 — the record

- [ ] **T1** ADR-031 and the committed-reference sections
      Record the boundary as D-2 answers it: `ADR-031` (template
      `contributor/adr/000-template.md`; status *proposed* until D-2 is
      answered, *accepted* after) carrying B1–B6, the side-ownership table and
      the four-layer arrow. Add the `.spec/ARCHITECTURE.md` judge/toolkit/
      provider/runtime section, and refresh its *Monorepo Plugin Packaging*
      tree to the grouped layout (`ls plugins/` → `adapters credentials
      domains substrates`). Add the `.spec/STATUS.md` open-features entry.
      Each record cites the Confluence page id and version it rests on (spec.md
      §8).
      *Files:* `contributor/adr/031-rise-judges-risekit-authors-functualize-runs.md` (new), `.spec/ARCHITECTURE.md`, `.spec/STATUS.md`
      *Gate:* the ADR carries B1–B6 and the ownership table; the refreshed tree
      matches `ls plugins/`; no record links a gitignored path.

## Wave 1 — the judge's skeleton

- [ ] **T2** `functualize-rise`: package, plugin, catalog, schema and contract types
      The distribution `functualize-rise` (import `functualize_rise`, version
      `0.4.0`, with `LICENSE`, `NOTICE` and `README.md`). `RisePlugin` under
      `functualize.plugins`, declaring `functualize_ext_namespaces = ("rise",)`
      and providing `RiseCatalog(host)` through `host.di.provide`. The schema
      types and the `CapabilityContract` / `OperationContract` / `FieldRule`
      frozen types with the identity grammar (C3, C4). `contract_ref`
      resolution (S6). The `[tool.uv.sources]` entry, the lock, and a
      `ci.yml` plugin-test step. No validate/diagnose behaviour yet.
      *Files:* `plugins/domains/functualize-rise/**`, `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`
      *Gate:* `uv sync --frozen --all-extras --all-packages` clean; plugin tests
      green; `uv run lint-imports` still 7/7 kept; G9; G11 (rise half);
      `rg -l 'functualize_rise' src/` → empty.

## Wave 2 — validating

- [ ] **T3** The `rise-validate` job (S5–S8)
      Published under `functualize.jobs` and reachable as `func rise-validate
      --package <id>`. It materializes entry-point jobs by name before reading
      their metadata (S4). It reports all eight S7 findings by name, one human
      line each, and mutates and runs nothing.
      *Files:* `plugins/domains/functualize-rise/src/functualize_rise/jobs.py`, `plugins/domains/functualize-rise/src/functualize_rise/validate.py` (+ tests)
      *Gate:* **G4**, end-to-end through `func` on a fixture package (the first
      half of AC-5). One fixture job is published by entry point, so that S4 is
      exercised: sabotage the materialization and watch G4 fail.

## Wave 3 — diagnosing

- [ ] **T4** The `rise-diagnose` job (S9–S14)
      A post-order traversal with a visited set: per-subject records first, the
      package record last. Required/optional aggregation, with
      `required_dependency_failed` referencing the child by id. A cycle is
      reported without recursion. One `diagnosis_id` per invocation. Each
      observation runs through `Invoke` (B4, S14). NDJSON per C6, and exit
      status per S13. Measure and record S4's materialization cost.
      *Files:* `plugins/domains/functualize-rise/src/functualize_rise/diagnose.py`, `plugins/domains/functualize-rise/src/functualize_rise/jobs.py` (+ tests)
      *Gate:* **G5**, end-to-end through `func` (the second half of AC-5).

## Wave 4 — the boundary proven

- [ ] **T5** The hand-written fixture twin (B2, AC-3)
      A RiseKit-free jobs module whose declarations are raw
      `__functualize_ext_rise__` dicts, with `contract` and `contract_ref`
      written by hand and its contract built from Rise's type directly. One
      test, parametrized over this twin and the RiseKit-built twin from T7,
      asserts identical validate and diagnose results.
      *Files:* `plugins/domains/functualize-rise/tests/_handwritten/`, `plugins/domains/functualize-rise/tests/test_handwritten_parity.py`
      *Gate:* **G3**. Until T7 lands, the RiseKit parametrization is marked
      `TRANSITIONAL(T5→T7)` and skipped with a reason. The hand-written half
      alone is the B2 proof.
- [ ] **T6** Orphan behaviour, both ways (S2, S3)
      With rise loaded, a booted app over rise-metadata jobs warns nothing.
      With the plugin disabled, the warning names `rise`, and the job still
      runs.
      *Files:* `plugins/domains/functualize-rise/tests/test_orphan_behavior.py`
      *Gate:* **G2**.

## Wave 5 — the toolkit

- [ ] **T7** `functualize-risekit`: contract helper, `@operation`, record builder
      Distribution `functualize-risekit` (import `functualize_risekit`,
      `0.4.0`, with `LICENSE`, `NOTICE` and `README.md`), depending on
      `functualize-rise` and the `functualize` public API, and declaring no
      entry point. `contract(...)` returns Rise's `CapabilityContract`.
      `@operation(<contract>, <op>, subject=…, relations=…)` derives `contract`
      and `contract_ref` from the symbol and emits exactly Rise's schema
      fields, nothing of its own (B3). The observation → record builder. **No
      provider and no provider-domain name** (B5). Add the
      `[tool.uv.sources]` entry, the lock and the `ci.yml` step.
      *Files:* `plugins/domains/functualize-risekit/**`, `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`
      *Gate:* a schema-equality test (helper-built metadata is structurally
      equal to T5's hand-written twin); **G8** (risekit half); **G11**
      (risekit half and B2 import half); T5's `TRANSITIONAL` skip resolved.

## Wave 6 — the provider package, D1

- [ ] **T8** `functualize-rise-cloudflare`: package and `cloudflare.d1@1` (S15, S16, S18)
      A separate distribution (`plugins/substrates/functualize-rise-cloudflare/`,
      import `functualize_rise_cloudflare`, `0.4.0`, with `LICENSE`, `NOTICE`
      and `README.md`) depending on `functualize-risekit`. It is written only
      against what an outside author would have. `contracts.py` defines `D1`
      with RiseKit's helper, as owner of `cloudflare`. The D1 jobs run against
      a `D1Transport` Protocol (a fake in tests, stdlib HTTP live, as in
      `tests/substrate_probe/d1.py`). `provision` diagnoses first and creates
      only if the database is absent. Published under `functualize.jobs` only.
      Add the `[tool.uv.sources]` entry, the lock and the `ci.yml` step.
      *Files:* `plugins/substrates/functualize-rise-cloudflare/**`, `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`
      *Gate:* **G6**; offline fake-transport tests for S16's idempotence;
      `rise-validate` clean on the package (AC-4); `cloudflare-d1-provision`
      exit semantics per C7 row 3; **G8**, **G9**, **G11** (provider half).

## Wave 7 — the provider package, Worker

- [ ] **T9** `cloudflare.worker@1`: contract, diagnose, and the required relation (S17)
      The `WORKER` contract and its diagnose job, with `binds → <d1 subject>`
      defaulting to `required` through the helper. Aggregation is proven on the
      fake transport: when d1 is absent, the worker and the root both fail
      (the first half of S19).
      *Files:* `plugins/substrates/functualize-rise-cloudflare/src/functualize_rise_cloudflare/**` (+ tests)
      *Gate:* T9's test selection green (with T7 and T8, the third leg of AC-4).

## Wave 8 — the proof a user sees

- [ ] **T10** The example Rise package (S19, AC-7)
      `examples/rise-cloudflare-d1/` declares `worker.production` with
      `binds → d1.production` (`required`). It is pytest-collected, with the
      fake transport bound in the example's tests. It asserts: three records;
      when d1 is absent, the worker and the root fail, the d1 record says why,
      and the exit status is non-zero; after `provision`, with the Worker
      present, the same diagnosis passes.
      *Files:* `examples/rise-cloudflare-d1/**`
      *Gate:* **G7**.

## Wave 9 — close

- [ ] **T11** The traceability review (AC-9)
      Two checks, written into `research.md` § *Traceability review*:
      1. **Implementation traceability.** For every delivered package, every
         public name in C1–C8, and every AC, name the spec.md §8 row that
         authorizes it. Re-read each cited Confluence page and Jira ticket live,
         and record its current version. A changed version, or an inline or
         footer comment from the owner, is re-checked against the delivered
         behaviour before this task closes. An element with no row, or a row
         whose source no longer says what it is cited for, is a finding: fix the
         code or raise it on the tracker. Never fix the citation to fit.
      2. **Artifact placement.** No Rise artifact duplicates Jira's
         delivery-state role or Confluence's decision role (Decision 11370545).
         The boundary record lives in ADR-031 and `.spec/ARCHITECTURE.md`, and
         the corrections live on the tracker thread.
      Also check that `docs/guides/plugins.md` still tells the truth about the
      seam, and extend it only if the generic text is now insufficient.
      *Files:* `.spec/features/rise-risetkit-foundation/research.md`, `docs/guides/plugins.md` (only if the review finds drift)
      *Gate:* **G10**.
- [ ] **T12** Boundary gates and release records
      Re-run G1, G8, G9 and G11, plus selected re-runs of G2–G7. Run the five
      local checks scoped to the change (`ruff check`, `ruff format --check`,
      `mypy src/`, `lint-imports`, and the three plugin test directories plus
      examples). Write the hand-written `CHANGELOG.md` entry.
      *Files:* `CHANGELOG.md`, this file's checkboxes
      *Gate:* G1 empty; all checks green; no `Co-authored-by` trailer and no
      tracker key in any commit of the branch.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "T1"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "T2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "T3"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "T4"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "T5",
        "T6"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "T7"
      ]
    },
    {
      "id": 6,
      "tasks": [
        "T8"
      ]
    },
    {
      "id": 7,
      "tasks": [
        "T9"
      ]
    },
    {
      "id": 8,
      "tasks": [
        "T10"
      ]
    },
    {
      "id": 9,
      "tasks": [
        "T11",
        "T12"
      ]
    }
  ]
}
```
