# Rise / RiseKit foundation — plan

Plan for `spec.md` **revision 6: Rise v1 on 0.5.0 as released, including core
class discovery (MCH-184) and scoped vault v3 (MCH-185)**. These are the
owner's decisions of 2026-10-13. Revision 4 was confirmed on 2026-10-05T17:27Z;
the open items are in spec §11.

Base: `origin/master` at `c75a476e`. Revision 5's counts were taken on
`4e816a0f`. The negatives this revision rests on were re-run on `c75a476e`
(spec header).

**Execute is gated** on a released 0.5.0 that contains both prerequisites and
meets contracts C11 (T14, wave 0). Discovery-dependent tasks are stated against
the C11 requirements, not against an interface that does not exist yet. Their
exact call shapes are fixed when 0.5.0 is released.

## Alignment

**Shape Intent SD/5407068, v18, `Authority: Approved`.** It was approved by the
owner in inline comment 12648493, and it covers "Decisions 1–27 as of v16, plus
the owner decisions below (v17)". It was re-read live on 2026-10-05, with the
content unchanged from the confirmed read. It was re-read again on 2026-10-10:
version 18, same content hash.

**[6] No shape amendment.** Revision 5's A-1 is withdrawn, because the owner
declined it. D16's "one generic class-discovery path" is consumed as written.
SD/5407068 was re-read live on 2026-10-13: v18, same content hash.

**Vault.** SD/12779576 **v3**, `Authority: Approved` (2026-10-09), re-read on
2026-10-13. It is consumed in 0.5.0 through MCH-185, and OD-1 is superseded.

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
  outside this Rise page." These are spec §6 P-1 to P-6. **[6]** P-1 (MCH-184)
  and P-7 v3 (MCH-185) ship in 0.5.0 and gate Execute (T14). P-2 to P-6 are
  not consumed.
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
   [5] measured on 4e816a0f (0.5.0 base): a plugin job reads ONLY its job-name
       config section, while configuration.get_job_config_section() reports the
       group (spec §0 F-7)
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
 functualize 0.5.0 (released) — UNCHANGED by this feature (B1, AC-2)
   P-1 class discovery (MCH-184) ──discovers──► subject classes in providers/projects
        one canonical job per (class, op), invoked with an address (contracts C11 R1.x)
   P-7 vault v3 (MCH-185) ── subject address as vault group, env-qualified (C11 R7.x)
```

**Dependency direction.** Every arrow points down, and nothing points up into a
plugin from core. Every layer of core is untouched, so the seven import-linter
contracts are unaffected. They cannot see `plugins/` anyway: the root package is
`functualize`. The plugin boundary is held instead by gate **G-private**
(`rg -l 'functualize\._' <three package src dirs>` must be empty). That gate
also applies to the plugins' own tests, under `tests/plugins/rise/`.

**What crosses a boundary.**

- Rise → core: public API only. That is `job`, `Invoke`, `Job`,
  `StaticProvider` (for Rise's own three commands), `Secret`, `ExitCode`,
  `FunctualizeApp` and pydantic, plus whatever public surface the released
  P-1 and P-7 v3 add. **[6]** Rise does not read `__functualize_job__`.
- Provider → core: none beyond being discovered (P-1).
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
6. **[5] Candidate E, provider-owned binding: withdrawn [6].** Revision 5
   accepted it subject to shape amendment A-1. The owner declined A-1 on
   2026-10-13, so the class-discovery path stays in core (P-1). The revision 5
   probe is kept: its rows are now the measured basis of the P-1 requirements
   (contracts C11, R1.3, R1.6, R1.7 and R1.8). The AFTER shape returns to
   revision 4.1's, and Rise adds no binding module.

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
| **Incomplete Library Class** (core) | P-1 and P-7 v3, until a released 0.5.0 contains them | Owned by MCH-184 and MCH-185 (B1). Rise does not patch core and does not work around it. Execute waits (T14). | No (the owner's decision, 2026-10-13) |

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
4. **Entry gate** (T14, wave 0) [6]. Before any code task:
   - a released 0.5.0 exists and contains MCH-184 and MCH-185;
   - each C11 requirement (R1.1–R1.10, R7.1–R7.5) is checked against it;
   - each discovery-dependent task below gets its concrete call shape recorded
     from the released API.

   If any requirement is unmet, the feature returns to Specify.
5. **The first production path** (T9, T11). `rise validate` is registered
   through `RisePlugin`, with findings 1–10 and 12. Findings 11 and 13 need
   discovered canonical jobs, and land in T16.
6. **Diagnosis and realization engines** (T8, T10). Pure, and unit tested with
   an injected `observe(address)`. The traversal is a topological walk over
   ordering edges, memoized by address. Acyclicity is guaranteed by S15.9;
   research.md § R-1 is honoured.
7. **The toolkit and the provider** (T12, T13). The RiseKit remote-resource
   substrate and conformance helper. The provider's contracts,
   implementations and fake transport. The provider is reached through core
   class discovery (C11 R1.1), and ships **no** binding plugin.
8. **Dispatch** (T15). `rise diagnose` and `rise up` invoke each subject's
   canonical job with its address (R1.4), with declaration literals fixed
   (R1.6). The step also covers single-candidate selection and the realization
   append.
9. **Findings 11 and 13, then the forcing case** (T16, T17). The descriptor is
   checked against the discovered job's declaration (R1.8), and a missing
   canonical job is reported (R1.3). Then the example project, with the token
   stored **once** under the subject address (R7.1), and the live tier.
10. **Closing checkpoint** (T18). Covers:
    - the traceability check (AC-14);
    - the B1/B5/B6 gates;
    - the five-command quality run;
    - the dead-code delta.

## Files to change

Every path is new except four: `uv.lock`, `tests/conftest.py`,
`.spec/ARCHITECTURE.md` and `.spec/STATUS.md`. `src/functualize/` is not
touched. The task list holds the per-task file sets.

## Dependencies

- **[6] MCH-184 (core class discovery) and MCH-185 (scoped vault v3)**, both
  inside 0.5.0 (children of MCH-157). Execute waits for a **released** 0.5.0
  containing both (T14). Their requirements are contracts C11.
- **Release.** The three Rise distributions follow the repository's lockstep
  release, after 0.5.0. Each new PyPI project needs a trusted publisher before
  its first tag (`.spec/STATUS.md`).
- MCH-147 (Workers spike) proceeds independently.

## Risks

- **The prerequisites ship differently from C11.** A requirement may be met
  with a different shape than the plan assumes. Mitigation: T14 records the
  released call shapes before code. An unmet requirement returns this feature
  to Specify rather than being worked around.
- **0.5.0's timing is outside this feature.** Execute cannot start until it is
  released; waves 1+ wait in full.
- **ADR number race.** T1 re-checks `ls contributor/adr` and takes the next
  free number.
- **Installing `functualize-rise` changes every workspace app**, by adding a
  `rise` group. The distributions stay out of `[all]` (C1), and the root suite
  hides them (T2).
- **Future annotations.** A module with `from __future__ import annotations`
  stores `-> Environment` as a string. T6 resolves it with
  `typing.get_type_hints`, and has a test for both forms.
- **Live tier cost.** Real D1 databases are created under `rise-test-`, the
  tier is skipped without credentials, and it runs only where the owner
  provides them.
