# Rise / RiseKit foundation — plan

Plan for `spec.md` **revision 5: Rise v1 on the 0.5.0 cut** (the owner's
directive of 2026-10-10). Revision 4 was confirmed on 2026-10-05T17:27Z. The
4.1 and 5 changes are put to the owner with this task list (spec §11).

Base: `origin/master` at `4e816a0f`, the base of the 0.5.0 release PR #99.
Every count below was produced by the command printed beside it, on that base.
Counts first taken on `ba36b859` were re-checked and are unchanged.

## Alignment

**Shape Intent SD/5407068, v18, `Authority: Approved`.** It was approved by the
owner in inline comment 12648493, and it covers "Decisions 1–27 as of v16, plus
the owner decisions below (v17)". It was re-read live on 2026-10-05, with the
content unchanged from the confirmed read. It was re-read again on 2026-10-10:
version 18, same content hash.

**[5] Pending shape amendment A-1** (spec §0). This is provider-owned binding
through Functualize's public plugin seam until core class discovery ships. It
departs from D16's "Functualize discovers the methods through one generic
class-discovery path". The departure is only in *who calls the binding*: the
execution model is unchanged, and no Rise loader is added. Execute does not
start until the owner approves A-1 on the page.

**Vault.** SD/12779576 is now **v3, `Authority: Approved`** (2026-10-09), and
is **not implemented in 0.5.0**. Rise v1 uses the shipped v2 behaviour
(settled OD-1). Moving to v3 is a later migration.

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
  outside this Rise page." These are spec §6 P-1 to P-6. **[5] None of them
  gates v1.** P-1, P-8 and vault v3 are triggers for a later migration.
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
   plugin.py     [5] plugin = bind-and-register its OWN classes:
                 add_job_provider(StaticProvider(bind(CloudflareApiD1, CloudflareApiWorker)))
                 registered under functualize.plugins (existing group)
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
   binding.py      [5] bind(*classes) -> list[Job]: canonical job per (class, op),
                   group <ns>.<name>.<candidate>, merged JobDeclaration    → subject, roles
   validate.py     findings                                 → environment, descriptor
   diagnose.py     traversal, assessment, NDJSON            → environment, subject
   up.py           candidates, ordering, dispatch, record   → diagnose, realization
   jobs.py         rise validate | diagnose | up  (job fns; lazy-import the above)
   plugin.py       RisePlugin: add_job_provider(StaticProvider([...3 Jobs, group="rise"]))
        │ public API only:  functualize.job (job, Invoke) · functualize.plugin (Job,
        │ StaticProvider) · functualize.types (Secret, ExitCode) · functualize.app
        ▼
 functualize 0.5.0 (core) — UNCHANGED by this feature (B1, AC-2)
   plugin discovery (functualize.plugins, .functualize/plugins/) loads the provider plugin;
   StaticProvider registers the bound jobs; Invoke runs them; JobConfig chain resolves
   the subject model (explicit kwargs = environment literals > vault > env > file).
   later, NOT required: P-1 class discovery → providers delete plugin.py; jobs keep names
```

**Dependency direction.** Every arrow points down, and nothing points up into a
plugin from core. Every layer of core is untouched, so the seven import-linter
contracts are unaffected. They cannot see `plugins/` anyway: the root package is
`functualize`. The plugin boundary is held instead by gate **G-private**
(`rg -l 'functualize\._' <three package src dirs>` must be empty). That gate
also applies to the plugins' own tests, under `tests/plugins/rise/`.

**What crosses a boundary.**

- Rise → core: only `job`, `Invoke`, `Job`, `JobDeclaration`, `StaticProvider`,
  `RunRequest`, `Secret`, `ExitCode`, `FunctualizeApp` and pydantic. All are
  public; `__all__` checked by an `ast` walk. The one attribute convention
  used is `__functualize_job__`, which `docs/guides/jobs-discovery.md:377`
  documents.
- Provider → core: its own plugin calls `add_job_provider` once (public).
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
6. **[5] The 0.5.0 directive: Candidate E, provider-owned binding.** Wave 9 of
   revision 4.1 was a hard stop on P-1, which 0.5.0 does not have. The
   candidates for running without it were:
   - **Candidate B again** (Rise binds other packages' classes): still
     rejected, because it is a Rise loader.
   - **Candidate E:** each provider's *own* Functualize plugin calls a pure
     `bind()`. **Accepted, subject to A-1.** Discovery stays Functualize's
     plugin discovery, Rise scans nothing, and execution is unchanged. The
     guide's **Shotgun Surgery** (verbs listed twice) is removed, because
     `bind()` derives the verbs from the class. That is the improvement over
     the documented `SubjectsPlugin`.

   It introduces two new smells, declared below: a repeated ~10-line plugin per
   provider, and a read-and-replace of a documented declaration attribute. The
   probe (spec §0) settled the two seams it rests on. Literal kwargs win the
   explicit tier (F-4), and global job names force a group-qualified `name`
   (F-1).

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
| **Duplicate Code** (transitional) | every provider's `plugin.py`, about 10 lines (`StaticProvider(bind(...))`), and each project's `.functualize/plugins/` file for local subjects | Stands in for P-1 on 0.5.0 (spec §0, A-1). Rule of Three: a shared plugin *factory* is not worth it with one provider. Each file carries `# TRANSITIONAL(P-1): delete when core class discovery ships`. | **Yes.** It is shape amendment A-1. |
| **Inappropriate Intimacy** | `binding.py` reads `__functualize_job__` and writes a merged `JobDeclaration` back onto the wrapper | Re-applying `@job(...)` *replaces* an author's declaration (spec §0, F-5), so merging needs the existing value. The attribute is documented user surface (`docs/guides/jobs-discovery.md:377`), and `JobDeclaration` is public. It is confined to one function, `binding._merged_declaration`. | No |
| **Shotgun Surgery** (operator-facing, v1) | rotating a subject's token means one vault entry per operation job (`…api.up`, `…api.diagnose`) | 0.5.0 gives a plugin job only its job-name section (spec §0, F-7), and vault v3 is not implemented. It goes away with P-8 or vault v3. | **Yes**, as a v1 limitation (spec §11) |
| **Incomplete Library Class** (core) | P-1 to P-6, P-8, and the `get_job_config_section` disagreement (spec §0, F-7) | Owned outside this feature (B1). The F-7 disagreement is recommended as its own core ticket. | No (already decided, spec §6) |

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
4. **Binding** (T14, wave 6, revised in [5]). `bind(*classes) -> list[Job]`:
   - the canonical group and name of spec S4 / contracts C5;
   - `subject: <class>` as the config parameter, and `address: str`;
   - the generated tags merged into the method's own declaration;
   - refusal of a duplicate name within one call.

   The wrapper calls the unbound method on the resolved subject.
5. **The first production path** (T9, T11). `rise validate` is registered
   through `RisePlugin`, with findings 1–10 and 12.
   - Findings 11 and 13 need the bound jobs, and land in T16.
6. **Diagnosis and realization engines** (T8, T10). Pure, and unit tested with
   an injected `observe(address)`. The traversal is a topological walk over
   ordering edges, memoized by address. Acyclicity is guaranteed by S15.9;
   research.md § R-1 is honoured.
7. **The toolkit and the provider** (T12, T13). The RiseKit remote-resource
   substrate and conformance helper. The provider's contracts,
   implementations, fake transport, and its **own binding plugin**. It is
   tested offline through the bound jobs, not by calling methods directly.
8. **Dispatch** (T15, wave 9; no checkpoint since [5]). `rise diagnose` and
   `rise up` run through `Invoke(<canonical job>, address=…, **literal
   fields)`. Literal fields are the instance's `model_fields_set`, which is the
   explicit tier (spec §0, F-4). The step also covers single-candidate
   selection, the realization append, and the `TRANSITIONAL(T15)` markers
   removed.
9. **Findings 11 and 13, then the forcing case** (T16, T17). The descriptor is
   checked against the bound declaration, and every in-scope operation must
   have a registered job. Then the example project and the live tier (S32,
   C12).
10. **Closing checkpoint** (T18). Covers:
    - the traceability check (AC-14);
    - the B1/B5/B6 gates;
    - the five-command quality run;
    - the dead-code delta;
    - the per-operation vault-entry documentation for S7.

## Files to change

Every path is new except four: `uv.lock`, `tests/conftest.py`,
`.spec/ARCHITECTURE.md` and `.spec/STATUS.md`. `src/functualize/` is not
touched. The task list holds the per-task file sets.

## Dependencies

- **[5] None on unreleased core.** Every seam is in 0.5.0's public API, and the
  spec §0 probe exercised each one on `4e816a0f` (contracts C11).
- **Shape amendment A-1** must be approved on SD/5407068 before Execute.
- **Release R-1.** The three distributions ship in the first release after
  0.5.0. At release time, each new PyPI project needs a trusted publisher
  (`.spec/STATUS.md`, *Credential plugins and the portable bundle*, states the
  same for every published project).
- MCH-147 (Workers spike) proceeds independently. Vault v3 implementation, P-1
  and P-8 are later migration triggers, not dependencies.

## Risks

- **A-1 is not approved**, or is approved differently. Then waves 6–8 change
  shape. Mitigation: Execute waits for A-1. Waves 0–5 do not depend on it.
- **ADR number race.** T1 re-checks `ls contributor/adr` and takes the next
  free number.
- **Installing `functualize-rise` changes every workspace app**, by adding a
  `rise` group. The distributions stay out of `[all]` (C1), and the root suite
  hides them (T2).
- **A cross-plugin job-name collision is silent in core** (spec §0, F-1).
  `bind()` catches collisions within one call, and `rise validate` finding 13
  catches the rest. A core fix is outside B1.
- **Future annotations.** A module with `from __future__ import annotations`
  stores `-> Environment` as a string. T6 resolves it with
  `typing.get_type_hints`, and has a test for both forms.
- **Live tier cost.** Real D1 databases are created under `rise-test-`, the
  tier is skipped without credentials, and it runs only where the owner
  provides them.
