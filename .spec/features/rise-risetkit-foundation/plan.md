# Rise / RiseKit foundation — plan

Status: **Plan — the architecture gate below is complete**; the set waits on
member answers to D-1…D-3 before Execute begins.

Base: `origin/master` at `ef1939d`, the state this plan was drawn against.
`spec.md` and `contracts.md` were written by an interrupted run and judged
against the tracker premise and `.spec/CONSTITUTION.md` before this plan
extended them; two corrections resulted (research.md § *Corrections*). The
retrieval evidence for every count quoted here is in research.md.

## Decisions for the member

These are the questions the set is parked on. Nothing in `tasks.md` may be
executed until each has an answer (spec.md § Status).

- **D-1 — Rise is not a delivery-intent pipeline (confirms premise change
  P-1).** The tracker's scope asks how accepted intent flows "through the
  machinery"; the shape intent defines Rise as an operational-package
  convention and says nothing of delivery intent. Proposed answer: **yes** —
  this feature builds no runtime path that reads Jira or Confluence, and
  AC-9's source-of-truth separation is met by *where* each artifact lives.
- **D-2 — the boundary itself (spec.md §3, recorded as ADR-031).** Confirm
  *Rise judges; RiseKit authors; Functualize runs* with the side-ownership
  table and B1–B4. Two sub-checks ride on this confirmation:
  1. the minimal assessment rule of contracts.md C4 (a contract may only name
     its passing states) is enough for the two Cloudflare contracts;
  2. **SM-3 below needs maintainer review**: the entry-point taxonomy has no
     kind for what Rise is, and this feature accepts the mislabel rather than
     growing the taxonomy (a stage-5 question).
- **D-3 — distribution and import naming (contracts.md C1).** Confirm
  `functualize-rise` / `functualize_rise` and `functualize-risekit` /
  `functualize_risekit` (reference package `functualize_risekit.cloudflare`),
  both under `plugins/domains/`, both versioned `0.4.0` with the workspace,
  neither in `functualize[all]` while experimental.

## The architecture gate

### Region map (all three retrieval tools, absolute paths)

Mapped with zvec-grep (`/usr/local/bin/zg query`, workspace index at 100 %,
853/853 files), serena (`get_symbols_overview` on
`/home/ubuntu/orca/workspaces/functualize/rise-foundation/src/functualize/_plugins/loader.py`)
and graphify (`query_graph` over the worktree's `graphify-out/graph.json`),
then read at the source. Codemaps read: `overview.md`, `dependencies.md`,
`modules.md`, `entry-points.md`, `data-flow.md` under
`contributor/architecture/codemaps/`. One diagram-vs-codemap finding is
recorded below (the `_gate` peer).

The region this feature touches is the *plugin-extension seam*, not any core
module: job functions carry dunders, discovery lifts them into descriptor
metadata, boot warns when no loaded plugin owns the namespace, entry points
publish plugins and jobs, and every job — Rise's own included — runs through
the single engine via `Invoke`. Evidence for each seam is in § *Seams*.

### BEFORE

Today `origin/master` has no Rise and no RiseKit anywhere (the negatives in
spec.md §1, re-run for this plan). A job opts into nothing but Functualize:

```
BEFORE (origin/master ef1939d — verified: 'risekit' 0 hits, '\bRise\b' 0 hits)

   a job module                discovery (peer layer)            boot (composition root)
  ───────────────────    ─────────────────────────────────    ──────────────────────────────
  jobs/infra.py            _discovery/providers.py              _app/boot.py
    JOB_GROUP="infra"       extract_ext_metadata(func)           validate_plugin_ext_metadata()
    def provision(...)        __functualize_ext_<ns>__    →        namespace owned ⇔ some loaded
         │                   → metadata["plugins"][ns]             plugin's name or an entry in
         │                        │                                its functualize_ext_namespaces
         │                        │                          orphan ns → warning
         │                        │                          (OrphanedPluginMetadataError
         │                        │                           only under plugins.strict)
         │                        ▼
         │                 JobDescriptor.metadata ──► _engine/executor.py  (single path)
         │                                                    ▲
         │                                                    │ Invoke("<job name>")
         │                        ┌─────────────────────────────┘
         │                 _plugins/loader.py  (peer layer)
         │                 PluginLoader(group="functualize.plugins")
         │                 loads plugin instances from entry points
         │                        ▲
         │                 _app/boot.py:214  EntryPointProvider()
         │                 reads group "functualize.jobs" ──► jobs by name
         ▼
  delivered by _cli/ as `func infra provision`

  THERE IS NO: package notion · contract format · judge · authoring kit.
  The first Cloudflare capability would set the Rise/RiseKit boundary
  wherever its code happened to land.
```

Pre-existing smells named on the BEFORE (catalogue names, with where they
live):

- **Primitive obsession** — `src/functualize/_discovery/providers.py:298`
  (`extract_ext_metadata`): the seam's payload is a JSON-serializable dict by
  contract, untyped at the core boundary. Deliberate: the value must cross a
  package boundary without an import. This feature *consumes* the smell
  rather than adding it; typed models exist only on the consumers' side.
- **Incomplete abstraction (taxonomy gap)** —
  `src/functualize/_primitives/plugin_kinds.py:56` (`classify_group`): the
  entry-point taxonomy knows adapter / domain / `*_providers` and nothing
  else, and the domain group (`functualize.domains`) carries reporting-only
  metadata, never a loadable plugin instance — so a *lifecycle plugin that
  owns a metadata namespace but adds no delivery surface* has no kind. See
  SM-3.

### AFTER

Two new workspace packages ride the seams above; **no file under
`src/functualize/` changes** (B1, gate G1):

```
AFTER (this feature — zero core change, gate G1: git diff vs origin/master
       over src/functualize/ is empty)

  layer: public folders (app/ job/ plugin/ types/ workflow/ testing/)
  ────────────────────────────────────────────────────────────────────────
  ┌─────────────────────────────────────────────────────────────────────┐
  │ functualize core — UNCHANGED (internal layers untouched)            │
  │   _discovery/providers.py · _plugins/loader.py · _app/boot.py       │
  │   · _engine/executor.py (Invoke) · _primitives/plugin_kinds.py      │
  └────▲───────────────────────────────────────────────────────▲────────┘
       │ imports PUBLIC API only (like functualize-decision-jev)│
  ┌────┴─────────────────────────────┐                          │
  │ functualize-rise                 │                          │
  │ plugins/domains/functualize-rise/│                          │
  │  RisePlugin                      │                          │
  │    entry point functualize.      │                          │
  │    plugins: rise                 │                          │
  │    functualize_ext_namespaces    │                          │
  │      = ("rise",)   ── owns ns    │                          │
  │  declaration schema +            │                          │
  │  CapabilityContract format       │                          │
  │  jobs: rise-validate,            │                          │
  │        rise-diagnose             │                          │
  │        (entry points under       │                          │
  │         functualize.jobs)        │                          │
  │  = THE JUDGE                     │                          │
  └────▲─────────────▲───────────────┘                          │
       │             │ imports rise + public API                │
       │      ┌──────┴────────────────────────────┐             │
       │      │ functualize-risekit               │─────────────┘
       │      │ plugins/domains/                  │  risekit.cloudflare
       │      │   functualize-risekit/            │   contracts: cloudflare.d1@1,
       │      │  @operation + authoring helpers   │             cloudflare.worker@1
       │      │  observation→record builder       │   jobs: cloudflare-d1-diagnose,
       │      │  = THE AUTHORING KIT              │        cloudflare-d1-provision,
       │      │  (emits Rise metadata only, B3)   │        cloudflare-worker-diagnose
       │      └──────▲────────────────────────────┘
       │             │ may import risekit — or NOT (B2)
  ┌────┴─────────────┴───────────────────────────────────────────────┐
  │ examples/rise-cloudflare-d1/ — a Rise package: jobs carrying     │
  │ __functualize_ext_rise__ (hand-written) or @operation (risekit)  │
  └──────────────────────────────────────────────────────────────────┘

  dependencies point one way, always:
    rise ──► functualize public API        (never src/functualize._*)
    risekit ──► rise, functualize public API
    rise ─✗► risekit   (B2: rise never imports risekit)
    functualize ─✗► rise, risekit  (B1: core is unchanged, knows nothing)
  execution: rise-diagnose calls Invoke("<operation job>") (B4) — the
  provider jobs are ordinary jobs through the single engine path.
```

Boundary crossings, against the seven import-linter contracts in
`pyproject.toml`: **none of the seven gains an edge.** Both packages live
outside `functualize` and import only its public folders — the same shape as
`functualize-decision-jev` (plugins/domains/functualize-decision-jev/
pyproject.toml:23-24). The constitution's "Internal never imports public"
and peer-independence contracts are untouched because core changes not at
all. What crosses the *package* boundary is data only: JSON-serializable
metadata (C3), observations (C5), NDJSON records (C6), entry-point tables
(C2), and environment-resolved credentials (C8).

Diagram-vs-codemap finding: `codemaps/dependencies.md` draws four peer
layers in its flow chart, while `pyproject.toml`'s independence contract —
the source of truth — lists five (`_gate` included). The codemap's prose
elsewhere counts seven contracts correctly; the AFTER diagram above avoids
naming peer membership and B1 makes the question moot for this feature, so
this is recorded, not fixed here.

Iteration between Plan and Specify produced two spec corrections (P-2's
wrong ADR citation; C4's dangling D-4 pointer — research.md § *Corrections*)
and one addition: the orphan-taxonomy finding above, which spec.md S3 already
implied and which becomes SM-3.

Candidate-AFTER smell check (what the AFTER *introduces*): checked for
**middle man** (rise-validate/diagnose are behaviour, not delegation — the
judgement logic lives in them), **god object** (each package stays small;
the 500-LOC bar applies per class), **shotgun surgery** (a contract-format
change currently touches rise + one risekit namespace — declared SM-2),
**divergent change** (rise changes for convention reasons, risekit for
authoring reasons — separated by the boundary itself), and the forbidden
patterns of `.spec/CONSTITUTION.md` (none carried: no ABC ports —
`CapabilityContract` is a frozen dataclass value, not a port; no global
state; no `_cli` internals; no peer imports). Forbidden patterns carried by
the AFTER: **none**.

## Seams (every core seam this feature rides, all pre-existing and verified)

| Seam | Where | What it already does |
|---|---|---|
| ext-metadata extraction | `src/functualize/_discovery/providers.py:298` | lifts `__functualize_ext_<ns>__` into `metadata["plugins"][ns]` |
| namespace ownership + orphan warning | `src/functualize/_app/boot.py:2102` | plugin owns `ns` via its `name` or `functualize_ext_namespaces`; orphan → warn, `plugins.strict` → `OrphanedPluginMetadataError` (`src/functualize/_types/errors.py:123`) |
| plugin loading | `src/functualize/_plugins/loader.py:193` | `PluginLoader(group="functualize.plugins")`; `PluginMetadata` protocol (name/version/description + register callable); precedent: `jev = "functualize_decision_jev:JevPlugin"` |
| job publishing | `src/functualize/_app/boot.py:214` | `EntryPointProvider` reads `functualize.jobs`, deferred import, `tests/discovery/test_entry_point_jobs.py` |
| execution | `src/functualize/_engine/executor.py` | single engine path; `Invoke("<job>")` carries ancestry/events/timeouts (S12) |
| credentials | config/secrets resolution | ordinary job parameters; names already used by `tests/substrate_probe/d1.py:74-76` |
| plugin wiring surface | `src/functualize/_app/extensions_facade.py:35` | `app.extensions` — what a plugin registers at wiring time |

B1 is therefore not an aspiration: the foundation adds **no** core change
because every seam it needs already ships.

## Surviving smells

This section is required; each entry names the smell by catalogue name,
where it lives, why it survives, and whether it needs maintainer review.

- **SM-1 — Primitive obsession** (catalogue: *Bloaters*), at the declaration
  seam: Rise declarations cross the job boundary as JSON dicts (C3) and
  records cross stdout as NDJSON lines (C6), not typed objects. Accepted
  because the seam's own contract *is* JSON-serializability
  (`extract_ext_metadata` docstring) — a typed object would demand an import
  from a package a hand-written package may not have (B2). Typed models exist
  on both sides (Rise validates; RiseKit authors). No maintainer review
  needed: the constraint is the feature's own boundary rule.
- **SM-2 — Shotgun surgery (single-instance)** (catalogue: *Change
  Preventers*) while only one namespace exists: a change to the
  contract *format* (C4) must land in `functualize-rise` and
  `functualize-risekit.cloudflare` together. Rule of Three says wait: with
  `cloudflare` as the only namespace the coupling is one edge, and AC-4's
  gates (every RiseKit-built package passes `rise-validate`) turn silent
  drift into a red test. Revisit when a second namespace appears. No
  maintainer review needed now; flagged for stage 5.
- **SM-3 — Incomplete abstraction in the entry-point taxonomy**
  (catalogue: *Dispensables/Speculative generality*, the inverse direction),
  in `src/functualize/_primitives/plugin_kinds.py:56`: `functualize.rise_contracts`
  classifies `UNKNOWN`, and the `rise` plugin — a lifecycle plugin owning a
  metadata namespace, no delivery surface — is labeled `ADAPTER` because
  only `functualize.plugins` loads instances and only `functualize.domains`
  is called a domain (reporting-only metadata; it cannot carry a loadable
  plugin). Accepted for this feature: the mislabel changes only what
  `func builtin plugin` prints, `classify_group` derives kinds from group
  names by design (its docstring forbids a package list), and growing the
  taxonomy is a stage-5 decision. **Needs maintainer review** — raised with
  D-2.

No other smell survives: the forbidden patterns of `.spec/CONSTITUTION.md`
are carried by none of the AFTER (checked above), and the remaining
candidates were checked and absent, not omitted.

## Design skills consulted

- `python-design-patterns` (in-repo,
  `.claude/skills/python-design-patterns` → `.agents/skills/python-design-patterns`):
  KISS (the assessment rule stays minimal), Single Responsibility (judge vs
  authoring kit vs runtime is the boundary), composition over inheritance
  (packages compose over the public API; no inheritance into core), Rule of
  Three (SM-2).
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue —
  the session's available-skills listing carried it): loaded for the smell
  catalogue names used above (primitive obsession, shotgun surgery,
  divergent change, middle man, incomplete abstraction) and the
  relations ladder — rise→functualize stays at *dependency*, the weakest
  relation that works.

## Stage 5 consumption list

What the later Rise/RiseKit slices consume from this feature, in the order
stage 5 is atomized (spec.md §6's order; this list is the single ordered
account AC-8 asks for):

1. **Deploying a Functualize operation into a Worker** (cloud-execution
   slice; a Functualize adapter plugin). Consumes: the Worker subject
   identity and `cloudflare.worker@1` contract, the idempotent-provision
   pattern of `cloudflare.d1@1`, relation mechanics.
2. **The D1 runtime store** (network-provider slice; generic Functualize
   plugin). Consumes: nothing from Rise — ordered here only; Functualize
   persists without Rise (P-2, Decision 13).
3. **`rise-lock`.** Consumes: contract identity grammar (C3), the package's
   declared set of contracts and operations.
4. **Operation strategies and preference policy.** Consumes: operations as
   ordinary jobs (B4), the diagnose traversal's aggregation rules (S9–S11).
5. **Origin, binding and lifecycle authority, and `delete`.** Consumes:
   subject identity, relations, criticality. Blocked on the positive-identity
   rule (shape intent Decision 11) — deliberately absent here (S13).
6. **The no-import static analyzer, and LSP on top of it.** Consumes: the
   declaration schema (C3), the contract registry format (C4).
7. **Registry acquisition** (registry, distribution, provenance, trust).
   Consumes: the Rise-package definition and package id. Generic Functualize
   machinery by Decision 13, so what this feature hands over is only the id
   and the boundary rule.

Stage 5 also inherits the open surface questions recorded in contracts.md
C1/C7 (the `func` spelling, `[all]` membership) and SM-3's taxonomy.

## Approach

Twelve tasks in nine waves (tasks.md); the shape:

- **Records first (T1, wave 0)** — ADR-031, the `.spec/ARCHITECTURE.md`
  boundary section (plus refreshing that section's stale plugin-tree
  listing to the grouped layout the repository actually has), and a
  `.spec/STATUS.md` open-features entry. None of these paths is gated, so
  wave 0 can run before anything else.
- **The judge (T2–T6, waves 1–4)** — `functualize-rise`: package + plugin
  (owns the `rise` namespace), declaration schema and `CapabilityContract`
  types, then `rise-validate` (S4–S6), then `rise-diagnose` (S7–S12:
  post-order traversal, visited-set, cycle report, required/optional
  aggregation, NDJSON envelope, `Invoke` per observation), then the B2
  proof (a hand-written RiseKit-free fixture twin) and the S2/S3 orphan
  behaviour both ways.
- **The authoring kit and the forcing case (T7–T9, waves 5–6)** —
  `functualize-risekit` (no plugin class: it publishes `@operation` helpers
  that emit exactly Rise's metadata, per the job-publishing pattern in
  `contributor/guides/plugin-development.md` § *Job-publishing
  distribution*), then `risekit.cloudflare`: `cloudflare.d1@1` with
  diagnose + idempotent provision against a fake transport (live tier skips
  without credentials, C8), then `cloudflare.worker@1` with the `binds → d1`
  required relation.
- **Proof and close (T10–T12, waves 7–8)** — the example Rise package
  (pytest-collected via `examples/`, fake transport, the S16 scenario), the
  AC-9 review record, and the final boundary gates plus the hand-written
  CHANGELOG entry.

Design notes the executor should not re-derive: contract instances are
frozen dataclasses loaded from the `functualize.rise_contracts` entry-point
group named by their identity; the fake transport is a Protocol injected
through ordinary job parameters/DI so offline tests bind it by configuration
and the live jobs change no code; `diagnosis_id` is one `uuid4` per
invocation shared by every record of that invocation.

## Files to change

Nothing below touches `src/functualize/**` or `plugins/**/src/**` *of an
existing package* — the two new packages' own `src/` trees are new files
(the gate keys on the wave graph this set lands).

| File | Size | Change |
|---|---|---|
| `contributor/adr/031-rise-judges-risekit-authors-functualize-runs.md` | new ~60 lines | the boundary decision, template `000-template.md`; 031 is the next free number (030 is the highest today) |
| `.spec/ARCHITECTURE.md` | existing | new section recording the judge/author/run boundary; refresh the *Monorepo Plugin Packaging* tree to the grouped layout (`adapters/ credentials/ domains/ substrates/`), which the section's current listing predates |
| `.spec/STATUS.md` | existing | open-features entry pointing at this feature |
| `plugins/domains/functualize-rise/` | new ~700 LOC + tests | package, plugin, schema, contracts, validate/diagnose |
| `plugins/domains/functualize-risekit/` | new ~800 LOC + tests | authoring helpers + `risekit.cloudflare` |
| `pyproject.toml` | existing | two `[tool.uv.sources]` entries; workspace glob `plugins/*/*` already covers the directories |
| `uv.lock` | existing | regenerated by `uv sync` |
| `examples/rise-cloudflare-d1/` | new ~150 LOC | example Rise package, pytest-collected |
| `CHANGELOG.md` | existing | hand-written entry |

## Risks

- **The taxonomy mislabel (SM-3)** is user-visible in `func builtin plugin`
  output. Recorded, member-flagged under D-2; not worked around — renaming
  the group to fit the taxonomy is exactly what stage 5 must decide.
- **Live-tier flake against Cloudflare** — mitigated the way the substrate
  probe already mitigates it: offline fake-transport tests carry the
  behaviour, the live tier skips (never fails) without either credential,
  names the missing variable, and touches only `rise-test-`-prefixed
  resources (C8).
- **Root `pyproject.toml`/`uv.lock` churn is shared infrastructure** — the
  step-tier mapper exits 3 on it, so T2/T7 land with a tip-tier dispatch,
  not a local fast run (`.spec/TESTING.md`).
- **Provision against a real account creates real resources** — the
  idempotence rule (S13) and the name prefix bound the blast radius; `delete`
  stays out of scope on purpose.
- **Names are provisional under the 1.0 promise** (contracts.md header) —
  every public name in C1–C8 may still change before 1.0; D-3 fixes the
  distribution names only.
- **The B2 fixture can rot into a second implementation** if hand-maintained
  — T5's gate keeps it structurally identical to its RiseKit twin by
  parametrizing one test over both.
