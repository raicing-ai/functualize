# Rise / RiseKit foundation — plan

Plan for `spec.md` revision 4.1. The owner confirmed revision 4 on
2026-10-05T17:27Z; the 4.1 amendments are put to the owner with this task list.

Base: `origin/master` at `ba36b859`. Every count below was produced by the
command printed beside it, on that base.

## Alignment

**Shape Intent SD/5407068, v18, `Authority: Approved`.** It was approved by the
owner in inline comment 12648493, and it covers "Decisions 1–27 as of v16, plus
the owner decisions below (v17)". It was re-read live on 2026-10-05, with the
content unchanged from the confirmed read. The vault dependency is SD/12779576
v2, `Authority: Approved`; its amendment is not on the page.

**In scope, in the shape's own words.** Each item names where it lands.

| The shape says | Lands in |
|---|---|
| "Capability contracts, subjects, configuration, observations, and realizations are typed Python classes. Operations remain ordinary Functualize jobs." (D16) | T5 |
| "Rise infers standard operation roles from names such as `validate`, `diagnose`, `up`, `down`, `start`, and `stop` … Rise generates `rise:op:*`, `rise:implements:<cap>@<major>/<op>`, and `effect:*` metadata from the typed declaration." (D16) | T4, T16 |
| "A subject's `self` identifies its instance through immutable, typed, serializable configuration … construction performs no operational I/O." (D17) | T5 |
| "Machine-readable JSON descriptors are generated from it on demand, cached locally" (D18) | T7 |
| "Any ordinary Functualize job returning `Environment` is an environment declaration … It is evaluated lazily and without operational side effects" (D22) | T6 |
| "`--scope <address>` selects what part of the author's tree to act on; the author decides what unscoped `func rise up` covers." (D25) | T6, T11 |
| "`validate` **and** `diagnose` **are first-class interoperability contracts**" (D3); "a flat universal envelope plus one typed `observation` payload" (D5); "Diagnosis status is compositional." (D6) | T9, T10 |
| "Diagnosis traverses acyclic ordering edges, treats informational relations as references, memoizes each identified subject once per diagnosis, and emits referential parent records" (D27) | T10 |
| "A base realization records subject, contract, candidate, identity, configuration fingerprint, isolation, time, and dependency chain; a persistence port supports local or remote lock backends." (D27) | T8 |
| "One generic resolver considers compatible candidates" (D19). In this feature: one candidate, or refuse | T15 |
| "Rise reuses Functualize exit codes." (D27) | T11, T15 |
| "The North Star forcing slice is a Cloudflare Worker plus D1 delivered through Rise/RiseKit." (D26) | T13, T17 |

**Out of scope, in the shape's own words.**

- "Approver authentication, GitHub Merge/Deploy authority, OAuth acquisition
  and refresh, and generic Functualize class/Gate/adapter machinery have owners
  outside this Rise page." These are spec §6 P-1 to P-6, and the class
  discovery of P-1 gates wave 9 (checkpoint T14).
- "Until that amendment is approved, SD/12779576 v2 remains the vault contract
  and no Rise spec may assume the group rule." (owner decision A1). This is
  settled OD-1.
- "The exact secret-push naming, hash record, and Worker runtime integration are
  design and spike work, not approved implementation details here." (D26). The
  spike is MCH-147, and "The local `release` path stays the fallback until P1–P5
  pass."
- "An optional new target preview is a separate proposal, not part of this
  decision." (D25)
- "Registry, provenance, evaluation, and trust are optional layers" (D13), with
  generated instance routes (D23), environment parameter tiers beyond fixed
  values (D24), and destructive operations and adoption (D11). These are spec
  §6 *Deferred*.

**Settled decisions carried in** (spec §10). OD-1 = job-scoped vault entries,
with per-instance secrets deferred to MCH-148. OD-2 = a local record marked
`shared: false`. B5 stands. The role override is a declaration on the
contract's abstract method (§ *Approach*).

## The architecture gate

### Retrieval run for this gate

- **zvec-grep.** The index was built in this worktree: 863/863 files, ready. The
  pass asked about class discovery, lazy routes, secret resolution order, and
  "shape intent Rise RiseKit subject capability provider". The last query
  surfaced `docs/guides/subjects.md`, which is the decisive prior art (PC-1).
- **serena.** It was activated at the absolute worktree path.
  `get_symbols_overview` on `_app/extensions_facade.py` returned
  `ExtensionsFacade`: `add_job_provider`, `add_job_transform`,
  `register_plugin_command` and 10 others. `find_referencing_symbols
  StaticProvider` reported 10 files, including the public re-export
  `plugin/__init__.py` and the seam test `tests/plugins/test_public_provider_seam.py`.
- **graphify.** `get_neighbors` was run on `EntryPointProvider` and
  `StaticProvider`. Both are built by `_app/boot.py` (`wire_entry_point_jobs`,
  `wire_declared_job_sources`) and live in `_discovery/providers.py`. The graph
  is **46 commits stale** (`built_at_commit 2269b8d3`), so it is trusted for
  shape only.
- **Codemaps.** `contributor/architecture/codemaps/overview.md`: "**13 official
  plugins** live in the `plugins/` workspace … `domains/` … each implementation
  is a *sibling* of the contract it implements". Rise, RiseKit and the provider
  follow that grouping.

### BEFORE — where a subject class meets Functualize today

```
 AUDIENCE: public API                      AUDIENCE: internal (underscore)
 ─────────────────────                     ───────────────────────────────
 functualize.plugin  ──re-exports──►  _discovery/providers.py   (peer layer)
   Job, StaticProvider,                  Job, StaticProvider, EntryPointProvider
   JobProvider, JobTransform             registry.py:400  reads module attrs'
 functualize.job                         __functualize_job__ only — classes ignored
   job(tags=…), Invoke ──────────►  _engine/capabilities/invoke.py  (peer layer)
 functualize.types                   _config/job_config.py, sources.py (peer layer)
   Secret, ExitCode                    JobConfig chain: override > CLI > vault > env > file > default
 functualize.workflow: Gate          _primitives/vault_identity.py (foundation)
                                     _app/boot.py (composition root) ──wires──► providers
                ▲
                │ public API only (convention; import-linter root is `functualize` alone)
 plugins/*/*  (13 packages; none publishes `functualize.jobs`)
                ▲
 user project ── per-project SubjectsPlugin (docs/guides/subjects.md):
                 instantiates each class with NO args, enumerates verbs BY HAND,
                 add_job_provider(StaticProvider([Job(bound_method, group=…)]))
```

**Smells the BEFORE already carries.** Names are from the Refactoring.Guru
catalogue.

- **Incomplete Library Class.**
  - `_discovery/registry.py:400` (predicate `_is_registerable_function`,
    `:586-605`) recognizes only module-level functions, so a
    subject class cannot become jobs without a hand-written plugin.
  - `EntryPointProvider` cannot know an entry-point job's group before
    materializing it (`providers.py:735-741`).

  Both are owned outside this feature: P-1, and a documented deferral in
  `.spec/STATUS.md`.
- **Shotgun Surgery / duplicated knowledge in the documented practice.** In the
  guide's `SubjectsPlugin`, the verbs exist twice: as methods on the class, and
  as a `("start", "stop", "backup")` tuple in the plugin. Adding a verb means
  editing both. Every project repeats the plugin. That is the gap Rise's
  generated metadata and P-1 close.
- **Primitive Obsession waiting to happen.** Nothing in core models a subject
  address. Every adopter of the guide invents a dotted string.

### AFTER — the settled shape

```
 user / example project
   jobs/environments.py: def cloudflare_dev() -> Environment   (ordinary job, D22)
        │ constructs instances of
        ▼
 plugins/substrates/functualize-rise-cloudflare   (provider; owns `cloudflare` ns)
   contracts.py  D1Database(RemoteResource) @contract("cloudflare.d1@1"), WorkerScript
   providers.py  CloudflareApiD1, CloudflareApiWorker      transport.py  (real + fake)
        │ depends on (public symbols only)
        ▼
 plugins/domains/functualize-risekit              (toolkit; NO provider — B5)
   substrates/remote_resource.py  RemoteResource, RemoteResourceObservation, builder
   testing.py                     assert_conformant(candidate) → runs Rise validate
        │ depends on
        ▼
 plugins/domains/functualize-rise                 (the convention)
   identity.py     ContractId, OperationId, Address        (no deps but stdlib)
   roles.py        role inference, tag generation          → identity
   subject.py      Subject, contract(), Realization, Observation, Ref → identity, roles
   environment.py  Environment tree, scope, root            → subject, identity
   descriptor.py   generate + cache                         → subject, roles
   realization.py  RealizationStore (Protocol) + LocalRealizationStore → identity
   validate.py     findings                                 → environment, descriptor
   diagnose.py     traversal, assessment, NDJSON            → environment, subject
   up.py           candidates, ordering, dispatch, record   → diagnose, realization
   jobs.py         rise validate | diagnose | up  (job fns; lazy-import the above)
   plugin.py       RisePlugin: add_job_provider(StaticProvider([...3 Jobs, group="rise"]))
        │ public API only:  functualize.job (job, Invoke) · functualize.plugin (Job,
        │ StaticProvider) · functualize.types (Secret, ExitCode) · functualize.app
        ▼
 functualize (core)  — UNCHANGED by this feature (B1, AC-2)
   _discovery ◄── P-1 class discovery (owned elsewhere): one canonical job per
                  (class, method), invoked with an address; class-contributed tags merge
```

**Dependency direction.** Every arrow points down, and nothing points up into a
plugin from core. Every layer of core is untouched, so the seven import-linter
contracts are unaffected. They cannot see `plugins/` anyway: the root package is
`functualize`. The plugin boundary is held instead by gate **G-private**
(`rg -l 'functualize\._' <three package src dirs>` must be empty). That gate
also applies to the plugins' own tests, under `tests/plugins/rise/`.

**What crosses a boundary.**

- Rise → core: only `job`, `Invoke`, `Job`, `StaticProvider`, `Secret`,
  `ExitCode`, `FunctualizeApp` and pydantic. All are public; `__all__` checked
  by an `ast` walk on this base.
- Provider → RiseKit → Rise: only symbols each package exports.
- Core → plugins: nothing.

### Iterations (what the candidate AFTERs introduced, and what changed)

1. **Candidate A: Rise's commands as `functualize.jobs` entry points** (the
   revision 3 shape). **Rejected.** The group is unknown before
   materialization (`providers.py:735-741`), so `func rise up` would list as a
   bare `up`. It would also make Rise the **first** plugin to publish
   `functualize.jobs`: `grep -l 'functualize.jobs' plugins/*/*/pyproject.toml`
   returns 0 files. Fixing that means a spec change: B6 is amended to register
   via `StaticProvider` (spec [4.1]).
2. **Candidate B: Rise binds provider classes itself through its plugin**, the
   way the guide's `SubjectsPlugin` does, to avoid waiting for P-1.
   **Rejected.** It is a second loader (forbidden by D14/B6). It also inherits
   the guide's **Shotgun Surgery**, because the verb tuple would be duplicated
   per class, and it makes Rise the owner of class discovery, which D16 assigns
   to "one generic class-discovery path".
3. **Candidate C: attach generated tags through a `JobTransform`** registered
   by the Rise plugin (`functualize.plugin.JobTransform`, an app-level
   transform). **Rejected.** The tags would exist only when the plugin is
   loaded, so a static reading of the class (D4, D14 "the same Rise declaration
   schema") would disagree with runtime, and S15.11 would fire on every
   hand-written provider. The tags are contributed at class creation through
   P-1's merge hook instead (contracts C11).
4. **Candidate D: addresses as plain dotted `str`.** It introduced **Primitive
   Obsession**: parsing and formatting the grammar would sit in `environment`,
   `diagnose`, `up`, `realization` and the NDJSON writer, which is **Shotgun
   Surgery** on every grammar change. Settled with an `Address` and `ContractId`
   value object in `identity.py` (*Replace Data Value with Object*). Every
   serializer calls `str(address)`.
5. **The spec premise check.** The architecture also showed that S6 had never
   said what wins between an environment literal and the `JobConfig` chain. The
   chain is keyed by the class-level job, so unset fields are per-class. That is
   now spec S6 [4.1] (fixed literal; chain only for unset fields) and S15.12
   (no secret literals). Neither changes scope; both are put to the owner at
   step 11.

### Design skills consulted

- `python-design-patterns` (in repository, `.claude/skills/python-design-patterns`):
  KISS, single responsibility, composition over inheritance, Rule of Three.
  The Rule of Three is why RiseKit ships one substrate, *remote resource*, and
  no common vocabulary.
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue): the
  smell names above and below; *Replace Data Value with Object*; Strategy vs
  Template Method for candidates. D19 makes a provider class a candidate, which
  is Strategy-shaped, so `up.py` holds no per-provider branches.

## Surviving smells

| Smell (catalogue name) | Where | Why it survives | Maintainer review? |
|---|---|---|---|
| **Parallel Inheritance Hierarchies** | every contract (`D1Database`) has a nested `Realized(Realization)` and an observation subtype | Canon requires it: "Each contract declares a realization type" (D18), and the observation is the typed diagnosis contract (D3, D5). Collapsing them would put untyped dicts back. | No |
| **Speculative Generality** | `realization.py`: a `RealizationStore` Protocol with one backend, plus the `shared` flag | The port is canon (D27: "supports local or remote lock backends"), and the second backend is the settled OD-2 follow-up. A Protocol, not an ABC, per *Forbidden Patterns*. | No |
| **Dead Code (transitional)** | `diagnose.py`, `up.py` and `realization.py` are reachable only from tests until T15, after the P-1 checkpoint (T14). Each carries `# TRANSITIONAL(T10/T8/T15): reached by rise diagnose/up after class discovery (P-1)` | `rise validate` is wired through the plugin in T11 (wave 7), so most of the package has a production path early. Dispatch cannot have one without P-1, and B6 forbids a substitute. The window lasts as long as P-1 takes, which nobody in this feature controls. | **Yes.** Choose between starting waves 0–8 now (the branch carries test-only code for the length of P-1) and holding Execute until P-1 is scheduled. Recommendation: start. Every gate in waves 0–8 is independent of P-1, and the dead-code delta classifies each finding as KNOWN through these markers. |
| **Incomplete Library Class** (core) | P-1 to P-6 | Owned outside this feature. Rise states what it requires (contracts C11) rather than patching core. | No (already decided, spec §6) |

None of the *Forbidden Patterns* entries appears:

- core is unchanged, so there is no peer cross-import;
- no ABC port (`RealizationStore` is a Protocol);
- no module-level mutable state, because the descriptor cache is on disk and
  instance-held;
- no hard-coded config path, because the cache uses Functualize's per-project
  cache directory (C6);
- no planned module over ~500 LOC. The largest are `diagnose.py` and
  `validate.py`, estimated at 250–350 lines each; T9 and T10 split them if they
  pass 400.

## Approach

1. **Records first** (T1). Write an ADR for the boundary (B1–B6) and a
   `.spec/ARCHITECTURE.md` section, so reviewers of every later wave judge
   against a committed boundary. ADR-031 is the next free number:
   `ls contributor/adr | sort | tail -1` → `030-…`.
2. **Packaging** (T2). Three workspace members under the existing `plugins/*/*`
   glob, and a refreshed `uv.lock`; this adds workspace members and bumps no
   dependency. The three distributions join `_DEFAULT_CHANGING_DISTRIBUTIONS`
   in `tests/conftest.py`, because the `rise` plugin adds a job group to every
   app the root suite builds. Tests live under `tests/plugins/rise/`, the jev
   precedent (`tests/plugins/test_jev_wire.py`), so the root `pytest` runs them
   with no CI workflow edit.
3. **The declaration model, bottom-up** (T3–T8). Pure Python over pydantic
   v2, which is a core dependency: `pydantic>=2.0.0`.
   - `Subject` is a frozen pydantic model, which gives D17's immutable, typed,
     serializable configuration directly.
   - `@contract("ns.name@major")` marks an abstract subject.
   - **Role-override spelling (OQ-2, settled here).** The contract's abstract
     method is wrapped with `@role("read-only")`. It is legal only on an
     abstract method of a contract or local subject; any other placement is a
     validation finding. Implementations inherit it. A role never comes from a
     tag string.
4. **The first production path** (T9, T11). `rise validate` is registered
   through `RisePlugin`, with findings 1–10 and 12. Finding 11 (descriptor vs
   runtime metadata) needs P-1's tags and lands in T14.
5. **Diagnosis and realization engines** (T8, T10). These are pure and unit
   tested. The engine takes an injected `observe(address) -> Observation`, so
   traversal, memoization, required/optional aggregation, deterministic order
   and NDJSON are proven before dispatch exists. The traversal is a topological
   walk over ordering edges, memoized by address. Acyclicity is already
   guaranteed by S15.9, so R-1's three-state DFS question reduces to "visited
   set + validate refuses cycles". research.md § R-1's recommendation is
   honoured, not overridden.
6. **The toolkit and the provider, offline** (T12, T13). The RiseKit
   remote-resource substrate and conformance helper. The provider's contracts,
   implementations and a fake transport, unit tested by calling methods on
   instances directly. That calling is test-only, never Rise's dispatch path.
7. **Checkpoint: P-1 is on master** (T14). This is a gate, not work: Execute
   stops here until class discovery has merged.
8. **Dispatch** (T15, T16, T17). Then `rise diagnose` and `rise up` through
   `Invoke` (canonical job + address), single-candidate selection, realization
   append, and the transitional markers removed. Finding 11 and tag generation
   ride P-1's merge hook. Last is the example project and the live tier (S32,
   C12).
9. **Closing checkpoint** (T18). The traceability check (AC-14), the B1/B5/B6
   gates, the full five-command quality run, and the dead-code delta.

## Files to change

Every path is new except four: `uv.lock`, `tests/conftest.py`,
`.spec/ARCHITECTURE.md` and `.spec/STATUS.md`. `src/functualize/` is not
touched. The task list holds the per-task file sets.

## Dependencies

- **P-1 (class discovery)** gates T15–T17. Its contract is in contracts.md C11:
  canonical job per method, address-carrying invocation, merge-not-replace
  tags, and literal-fixed fields.
- **P-7 has landed** (`ba36b859`, #88). Nothing in this plan waits on it.
- MCH-148 (vault amendment) and MCH-147 (Workers spike) proceed independently.
  Neither gates any task here.

## Risks

- **P-1's contract may differ from C11.** If class discovery ships without the
  merge hook or address-carrying invocation, T15/T16 cannot be built as
  planned. Mitigation: C11 is handed to the P-1 owner before T14, and a
  mismatch returns this feature to Specify rather than being worked around.
- **ADR number race.** Another open branch may claim 031. T1 re-checks
  `ls contributor/adr` at execution time and takes the next free number.
- **Installing `functualize-rise` changes every workspace app.** It adds a
  `rise` group to apps outside the root suite, such as examples and the
  standalone binary. Mitigations: the distributions stay out of `[all]` (C1),
  and the root suite hides them (T2).
- **pydantic frozen models and `Secret[str]`.** Whether a frozen model field
  annotated `Secret[str]` keeps the secret marker through Functualize's
  `JobConfig` chain is P-1's integration question. T5 records the expectation
  as a test that is marked `xfail(strict=True)` until T15.
- **Live tier cost.** It creates real D1 databases under `rise-test-`. It is
  skipped without credentials, and it runs only where the owner provides them.
