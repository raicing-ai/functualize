# Rise / RiseKit foundation — tasks

Execute against `spec.md`, `contracts.md`, `plan.md`. Wave ordering is
binding: no task in wave N+1 starts while wave N holds an unchecked task.
D-1…D-3 (plan.md § *Decisions for the member*) must be answered before T2
runs; T1 is records only and may land first.

## Gates

| Gate | Command / check | Asserts | Authoring-time state |
|---|---|---|---|
| G1 | `git diff --stat origin/master -- src/functualize` | empty output — B1, AC-2 | **Run 2026-10-01 on this branch: empty.** Re-run in T12 |
| G2 | T6's test selection: `uv run pytest plugins/domains/functualize-rise/tests/test_orphan_behavior.py -q` | with the rise plugin loaded: no orphaned-metadata warning for `rise`; with it disabled: warning present, job still runs (S2, S3) | lands with T6 |
| G3 | T5's test selection: `uv run pytest plugins/domains/functualize-rise/tests/test_handwritten_parity.py -q` | a RiseKit-free, hand-written fixture package validates and diagnoses identically to its RiseKit-built twin (B2, AC-3) | lands with T5 |
| G4 | T3's test selection (S5 finding names asserted one by one; exit 0 clean / non-zero findings, S6) | `rise-validate` behaviour | lands with T3 |
| G5 | T4's test selection (C6 keys and types per line, package record last, S9–S11 aggregation, cycle, exit status) | `rise-diagnose` behaviour | lands with T4 |
| G6 | T8's test selection (skip-without-credentials naming the missing var; `rise-test-` prefix only, C8) | live-tier convention | lands with T8 |
| G7 | `uv run pytest examples/ -q` | the example project is collected and green (AC-7) | lands with T10 |

Plugin tests run as `uv run pytest plugins/domains/<pkg>/tests/ -q` — root
pytest does not collect them (AGENTS.md § *Plugin tests*). T2 and T7 touch
`pyproject.toml`/`uv.lock` (shared infrastructure): the step-tier mapper
exits 3 there, so their verification is a tip-tier dispatch, not a local
full run.

## Wave 0 — the record

- [ ] **T1** ADR-031 + the committed-reference sections
      Record the boundary as a decision: `ADR-031` (template
      `contributor/adr/000-template.md`, status *proposed* until D-2 is
      answered), the `.spec/ARCHITECTURE.md` judge/author/run section, and
      the `.spec/STATUS.md` open-features entry. While in
      `.spec/ARCHITECTURE.md`, refresh the *Monorepo Plugin Packaging* tree
      to the real grouped layout — the current listing predates it
      (`ls plugins/` → `adapters credentials domains substrates`, run
      2026-10-01).
      *Files:* `contributor/adr/031-rise-judges-risekit-authors-functualize-runs.md` (new), `.spec/ARCHITECTURE.md`, `.spec/STATUS.md`
      *Gate:* ADR carries B1–B4 and the side-ownership table; the refreshed
      tree matches `ls plugins/`.

## Wave 1 — the judge's skeleton

- [ ] **T2** `functualize-rise` package, plugin, schema and contract types
      The distribution `functualize-rise` (import `functualize_rise`, version
      `0.4.0`, `LICENSE` + `NOTICE` + `README.md`), `RisePlugin` under
      `functualize.plugins` declaring `functualize_ext_namespaces =
      ("rise",)`, the declaration schema and `CapabilityContract` /
      `OperationContract` / `FieldRule` frozen types with the identity
      grammar (C3, C4), and the `[tool.uv.sources]` + lock wiring. No
      validate/diagnose behaviour yet.
      *Files:* `plugins/domains/functualize-rise/**`, `pyproject.toml`, `uv.lock`
      *Gate:* `uv sync --frozen --all-extras --all-packages` clean; plugin
      tests green; `uv run lint-imports` still 7/7 kept;
      `rg -l 'functualize_rise' src/` → empty (B1's import half).

## Wave 2 — validating

- [ ] **T3** The `rise-validate` job (S4–S6)
      Published under `functualize.jobs`, reachable as `func
      rise-validate --package <id>`. All eight S5 findings by name, one
      human line each, mutate nothing, run nothing.
      *Files:* `plugins/domains/functualize-rise/src/functualize_rise/jobs.py` (+ tests)
      *Gate:* **G4**, end-to-end through `func` on a fixture package
      (AC-5's first half).

## Wave 3 — diagnosing

- [ ] **T4** The `rise-diagnose` job (S7–S12)
      Post-order traversal with a visited set, per-subject records then the
      package record last, required/optional aggregation with
      `required_dependency_failed` referencing the child by id, cycle
      report without recursion, one `diagnosis_id` per invocation, each
      observation through `Invoke` (B4, S12), NDJSON per C6, exit status
      per S11.
      *Files:* `plugins/domains/functualize-rise/src/functualize_rise/diagnose.py` + `jobs.py` (+ tests)
      *Gate:* **G5**, end-to-end through `func` (AC-5's second half).

## Wave 4 — the boundary proven

- [ ] **T5** The hand-written fixture twin (B2, AC-3)
      A RiseKit-free jobs module whose declarations are raw
      `__functualize_ext_rise__` dicts (C3's JSON, written by hand), plus
      the identical declarations built through RiseKit once it exists —
      one test, parametrized over both twins, asserts identical validate
      and diagnose results.
      *Files:* `plugins/domains/functualize-rise/tests/_handwritten/`, `plugins/domains/functualize-rise/tests/test_handwritten_parity.py`
      *Gate:* **G3** (parametrized over the RiseKit twin from wave 5; until
      then the risekit parametrization is marked
      `TRANSITIONAL(T5→T7)` and skipped with reason — the hand-written half
      alone is the B2 proof).
- [ ] **T6** Orphan behaviour both ways (S2, S3)
      With rise loaded: a booted app over rise-metadata jobs warns nothing.
      With the plugin disabled: the warning names `rise`, and the job still
      runs.
      *Files:* `plugins/domains/functualize-rise/tests/test_orphan_behavior.py`
      *Gate:* **G2**.

## Wave 5 — the authoring kit

- [ ] **T7** `functualize-risekit` package and `@operation` helpers
      Distribution `functualize-risekit` (import `functualize_risekit`,
      `0.4.0`, `LICENSE` + `NOTICE` + `README.md`), depending on
      `functualize-rise` and `functualize` public API. The `@operation`
      decorator and the observation→record builder emit exactly Rise's
      schema fields — nothing of their own (B3). Job-publishing pattern, no
      plugin class (`contributor/guides/plugin-development.md`).
      *Files:* `plugins/domains/functualize-risekit/**`, `pyproject.toml`, `uv.lock`
      *Gate:* schema-equality test — helper-built metadata is structurally
      equal to T5's hand-written twin; `rg -l 'functualize_risekit'
      plugins/domains/functualize-rise/src/ src/` → empty (B2's import
      half, run 2026-10-01: empty); resolve T5's `TRANSITIONAL` skip.

## Wave 6 — the forcing case

- [ ] **T8** `cloudflare.d1@1` — contract, diagnose, idempotent provision (S13, S15)
      The contract instance under `functualize.rise_contracts`; the D1 jobs
      against a `D1Transport` Protocol (fake in tests, HTTP live) resolved
      as an ordinary job parameter; provision diagnoses first and creates
      only if absent.
      *Files:* `plugins/domains/functualize-risekit/src/functualize_risekit/cloudflare/**` (+ tests)
      *Gate:* **G6**; offline fake-transport tests for S13 idempotence;
      `cloudflare-d1-provision` exit semantics per C7 row 3.
- [ ] **T9** `cloudflare.worker@1` — contract, diagnose, the required relation (S14)
      The Worker contract and diagnose job; `binds → <d1 subject>` with
      `required` default via the helper; aggregation proven on the fake
      transport: d1 absent → worker and root fail (S16's first half).
      *Files:* `plugins/domains/functualize-risekit/src/functualize_risekit/cloudflare/**` (+ tests)
      *Gate:* T9's test selection green (AC-4's third leg with T7, T8).

## Wave 7 — the proof a user sees

- [ ] **T10** The example Rise package (S16, AC-7)
      `examples/rise-cloudflare-d1/`: declares `worker.production` with
      `binds → d1.production` (`required`), pytest-collected, fake transport
      bound in the example's tests. Asserts: three records; d1 absent →
      worker and root fail, the d1 record says why, exit non-zero; after
      `provision` (and with the Worker present) the same diagnosis passes.
      *Files:* `examples/rise-cloudflare-d1/**`
      *Gate:* **G7**.

## Wave 8 — close

- [ ] **T11** The AC-9 review record
      Review the delivered set against AC-9: no Rise artifact duplicates
      Jira's delivery-state role or Confluence's decision-context role;
      the boundary record lives in ADR-031/`.spec/ARCHITECTURE.md`; the
      tracker thread carries the premise changes. Write the finding into
      `research.md` § *AC-9 review*. Check `docs/guides/plugins.md` still
      tells the truth about the seam; extend only if the generic text is
      now insufficient.
      *Files:* `.spec/features/rise-risetkit-foundation/research.md`, `docs/guides/plugins.md` (only if the review finds drift)
      *Gate:* the review paragraph exists and cites what it checked.
- [ ] **T12** Boundary gates and release records
      Re-run G1 (and G2–G7 selected re-runs), the five local checks scoped
      to the change (`ruff check`, `ruff format --check`, `mypy src/`,
      `lint-imports`, plugin test dirs + examples), and write the
      hand-written `CHANGELOG.md` entry.
      *Files:* `CHANGELOG.md`, this file's checkboxes
      *Gate:* G1 empty; all checks green; no `Co-authored-by` trailer, no
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
        "T8",
        "T9"
      ]
    },
    {
      "id": 7,
      "tasks": [
        "T10"
      ]
    },
    {
      "id": 8,
      "tasks": [
        "T11",
        "T12"
      ]
    }
  ]
}
```
