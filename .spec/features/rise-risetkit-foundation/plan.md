# Rise / RiseKit foundation — plan

Status: **Plan, revision 3.** D-2 is answered: the member confirmed the split
and C4 on 2026-10-02. The owner's nine inline comments on Shape Intent 5407068
are incorporated (spec.md §9). One member decision is prepared and not yet
asked: **OS-1**, the operation-effect vocabulary (§ *Next member decision*). It
gates T2's freezing of `OperationContract`, not T1.

Base: `origin/master` at `ef1939d`, the state this plan was drawn against.
research.md holds the retrieval evidence for every count quoted here, and the
live-read record for every Confluence and Jira source.

## Corrections applied (not decisions)

The first revision asked the member three questions. Two of them were wrong
questions, and the member corrected them rather than answering them. The
corrections are applied throughout. They are recorded here so that nobody reads
them as approvals:

| Was | Member's correction (2026-10-02, MCH-88) | Now |
|---|---|---|
| **D-1** asked whether Rise should read Jira/Confluence intent at runtime, and proposed "no" | "Jira or Confluence is NEVER required as part of Rise Runtime. The Fun-8 Scope was just to make sure the DEVELOPMENT of rise and risekit were aligned with what we have in confluence documentation and Jira tickets." | The question was the wrong one. The obligation is **development traceability**: spec.md §8 maps every element to the page, decision and ticket that authorize it; AC-9 and T11 check it. Nothing at runtime touches Jira or Confluence. |
| **D-3** asked the member to confirm naming that put `functualize_risekit.cloudflare`, its contracts and its jobs **inside** RiseKit | "Risekit shouldn't contain packages for cloudflare etc, it should be used by other authors or package maintainers to create those cloudflare packages etc." | The Cloudflare contracts and jobs move to their own distribution, `functualize-rise-cloudflare`, authored with RiseKit (contracts.md C1). B5 makes this testable, and G8 gates it. Distribution naming follows the monorepo convention and is no longer a question. |

## D-2 — answered 2026-10-02

**Answer, verbatim:** "I confirm the split and C4. However I want to
investigate SM-3, why would rise\_contracts be in functualize as
functualize.rise\_contracts? It shouldn't, the layer is not clean."

The SM-3 concern was already resolved in revision 2, where the entry-point group
was withdrawn in favour of `contract_ref`. An independent review then
re-verified that resolution against the code. The text below is kept as the
record of what was confirmed, and it is what ADR-031 transcribes in T1.

### What was decided

How the work divides between three things that do not yet exist in this
repository, and which way they may depend on one another. The answer is
recorded permanently as ADR-031 and in `.spec/ARCHITECTURE.md`. Every later
Rise or RiseKit ticket is cut along this line.

- **Rise** is the convention plus the **judge**. It defines what a Rise package
  must declare (the schema), what a capability contract looks like (the
  format), and what a health report looks like (the diagnosis record). It
  answers two questions about any package, whoever wrote it:
  *does it conform?* (`validate`) and *is the thing it manages actually
  working?* (`diagnose`). Shape Intent 5407068 v15, Decision 1: "Rise is a
  convention and working ecosystem layered on Functualize". Decision 3: "Validate
  — contract truth", "Diagnose — runtime truth".
- **RiseKit** is the **author's toolkit**. It provides the typed helpers that
  make writing a conformant package the easy path. Later it will also hold the
  common contract vocabulary that several providers share. It never contains a
  provider. Decision 1: "Rise defines the compatibility model; RiseKit provides
  implementation machinery, authoring support, reusable building blocks"; and
  the member's correction above.
- **Functualize** is the **runtime**: jobs, plugins, discovery, `Invoke`,
  config, secrets, stores. It knows nothing about Rise. Decision 13: "Rise
  packages are discovered through Functualize. Functualize does not discover
  things through Rise."
- **Provider packages** are what authors build: separate distributions that
  depend on RiseKit.

The arrow is `functualize ◄── rise ◄── risekit ◄── provider packages`. Each
layer may know the layer below it and never the one above.

### Why it needs you

The repository has no account of this line (spec.md §1: zero occurrences of
either name on `master`). The first revision of this set showed how it gets
drawn by accident: it put the Cloudflare package inside RiseKit because that is
where the code was being written. Canon fixes the split in principle. What only
you can do is accept it as the repository's recorded boundary, together with the
two concrete choices that canon leaves open (sub-checks below).

### Effect on the plan

It decides which package T2–T6 build (`functualize-rise`), what T7 delivers
(authoring helpers only), where T8–T9 put the Cloudflare code (its own
distribution), what AC-1 and ADR-031 record, and how stage 5 is sliced
(§ *Stage 5 consumption list*). T1 records whatever you decide.

### Evidence

- Canon, quoted above (Shape Intent 5407068 v15, Decisions 1, 3, 12, 13, 14, 15;
  read live 2026-10-02, no inline or footer comments yet).
- B1 is achievable with zero core change. Every seam Rise needs is public:
  `PluginHost.get_jobs` / `get_job` / `di.provide` (`src/functualize/_types/host.py:296-302`),
  the extension-metadata seam (`src/functualize/_discovery/providers.py:296-312`),
  namespace ownership (`src/functualize/_app/boot.py:2104-2148`), and the `Invoke`
  capability.
- The first revision's contract discovery was illegal under repository law as
  well as canon (sub-check 2).

### Sub-check 1 — the minimal assessment rule (contracts.md C4)

A contract may say **only which observed states pass**. `status` is `pass` if
and only if the observed `state` is in `passing_states` and every required
observation field is present. There are no weights, thresholds or composite
health. Decision 5 asks exactly this: "`status` should normally be derived from
the applicable diagnosis/capability contract and the typed observation, rather
than being an arbitrary free-form provider judgment."

| Option | Consequence |
|---|---|
| **Accept the minimal rule** (recommended) | `cloudflare.d1@1` says `{present, absent, error}` / passes on `present`. Any later enrichment (a `degraded` state, a latency threshold) is a new contract version, `@2`, landing in `functualize-rise` (if the format grows) and in the provider at once. That coupling is SM-2. |
| Allow a richer rule now (thresholds, predicates) | More expressive from day one, but designed against one provider. Review decision D4 says to "hold every generalisation that no second package needs yet." |

### Sub-check 2 — how Rise finds a contract (was SM-3) — resolved, not open

The first revision loaded contracts from a new entry-point group,
`functualize.rise_contracts`, and asked you to accept the resulting
`UNKNOWN` label. That design is withdrawn, on two independent grounds:

- **Canon excludes it.** Decision 14: "Rise introduces no parallel runtime loader
  or mandatory physical package format. A component participates in Rise by
  carrying optional, statically representable Rise metadata over ordinary
  Functualize-discovered jobs and plugins." Decision 15 binds consumers
  "statically to a capability contract" through a typed symbol with a canonical
  string identity.
- **The repository refuses it.** `tests/spec/test_every_declared_group_has_a_reader.py:155-166`
  fails any shipped manifest that declares a `functualize.*` group with no
  reader in `src/`. The first revision's T8 would have landed red.

**Revised mechanism (B6):** each job's Rise metadata carries the contract's
identity *and* its static location, `contract_ref = "<module>:<attribute>"`.
RiseKit derives both from the contract symbol the author imports. Rise follows
the reference and checks the identity. There is no registry and no new group;
Rise reaches nothing that Functualize did not discover first. The only label
question left is that the `rise` plugin prints as `ADAPTER`. That label is
inherited: the maintainer accepted it for every `functualize.plugins` entry on
2026-09-17 (`.spec/STATUS.md:2930-2933`), and the Jev plugin already wears it.
**Nothing for you to decide here** unless you want to overrule that reading.

### A walk-through: an outside author

Dana maintains infrastructure tooling and wants Functualize users to manage D1
databases through Rise.

1. Dana creates a distribution, `acme-rise-d1`, depends on `functualize-risekit`,
   and owns the namespace `acme.d1`. Nothing in RiseKit changes and nothing in
   Rise changes.
2. In `acme_rise_d1/contracts.py` Dana writes
   `DATABASE = contract("acme.d1.database@1", states={...}, passing={"present"}, ...)`
   with RiseKit's helper. The helper returns Rise's `CapabilityContract` type.
3. Dana writes two ordinary Functualize jobs and decorates them:
   ```python
   @operation(DATABASE, "diagnose", subject="d1.main")
   def diagnose(account_id: str, api_token: Secret) -> dict: ...
   ```
   The decorator writes `contract = "acme.d1.database@1"` and
   `contract_ref = "acme_rise_d1.contracts:DATABASE"` into the job's metadata.
4. A user installs `acme-rise-d1`. Functualize discovers the jobs.
   `func rise-validate --package acme.d1` follows the reference, judges the
   package, and runs none of Dana's code. `func rise-diagnose` runs Dana's
   `diagnose` through `Invoke` and emits NDJSON.
5. Later Dana ships `acme.d1.database@2`. No Rise or RiseKit release is needed
   (Decision 12). Packages pinned to `@1` keep meaning what they meant.

`functualize-rise-cloudflare` in this feature is exactly Dana's package, written
in this repository so that FUN-8 has its proof in CI. Had it lived inside
RiseKit, as in revision 1, every one of steps 1–5 would have required a RiseKit
release.

### Options

| Option | Consequence |
|---|---|
| **Confirm the boundary and sub-check 1** (recommended) | T1 records ADR-031 as *accepted*. T2–T12 become executable in wave order, and stage-5 tickets can be cut from § *Stage 5 consumption list* once the Confluence queue is updated. |
| Confirm the boundary, reject sub-check 1 | The boundary is recorded. C4 is redesigned with a richer rule before T2, and this plan returns to the design lane. |
| Overrule sub-check 2 (keep a runtime contract group) | Needs a reader in `src/functualize/` (core change, breaking AC-2), or deletion of the declared-group reader test. Not recommended: both canon and the repository refuse it. |
| Do nothing | Free today: draft PR, planning files only. T2–T12, stage-5 promotion and the Cloudflare/D1 slice stay stalled. |

**Recommendation:** confirm *Rise judges; RiseKit authors; Functualize runs*,
with providers outside RiseKit, and accept sub-check 1. Canon already states
the split, and the corrections only narrowed RiseKit's rows.

### What proceeds regardless

*(As written when asked.)* Nothing in Execute starts until you answer. The
Confluence continuation queue is updated only after the answer, by the leader.
T1 (records only) is releasable on your word, independently of D-2.

## Next member decision — OS-1: should operations declare their effects?

Prepared for the leader to put to the member. The full research is
research.md § *R-2*. Recommendation: **provisional**.

**What the decision is.** Every *operation* in a capability contract (an
operation is something done to a managed thing: `diagnose`, `provision`, later
`deploy` or `delete`) can carry a label saying what running it does to the
world. Revision 1 gave it one yes/no flag, `mutating`. The owner asked whether
the labels should be richer ("destructive", "mutating", "side-effect"), and
whether operations should be able to *preview* their changes (dry-run or plan,
as Terraform and Pulumi do). The decision is which labels every provider author
must declare from now on. It is about the contract, not about building
previews.

**The effect on the long-term plan.**

- Consumed by **T2**, which freezes `OperationContract` (contracts.md C4).
- Consumed by every contract a provider author writes: `cloudflare.d1@1` in T8,
  and every outside package after it.
- If labels are richer, T3's validate gains two findings: a `diagnose` that
  claims an effect, and a `destroys` operation before Decision 11's identity
  rule exists.
- Plan/dry-run itself would become a later additive stage-5 slice in every
  option except c.

**The evidence.**

> "However should we provide markers for "destructive", or "mutating" /
> "side-effect" operations? … we'll need to elaborate and discuss this first."
> — Shape Intent 5407068, comment 11927574
>
> `mutating: bool  # PROVISIONAL` — contracts.md C4 (T2 may not freeze it)

The cost measurement lives in research.md § *R-2* (*Migration cost*). Changing a
flag into a set later touches the Rise type, the RiseKit helper and every
contract owner, and bumps the schema generation. Adding a plan later is purely
additive.

**Options.**

| Option | Consequence |
|---|---|
| a. Keep `mutating: bool` | Nothing to do now. Revisiting it after outside providers exist is a breaking change for all of them. |
| **b. An effect set now (`mutates`, `destroys`, `external`; empty = read-only); plan/dry-run deferred** | The expensive-to-change shape is settled while one in-tree provider is the only cost. Validate enforces "diagnose is read-only", and refuses `destroys` until Decision 11's identity rule lands. Previewing is a later, additive slice. |
| c. Effect set **and** plan/dry-run now | The owner's dry-run idea arrives immediately, but the plan format is designed against one provider with one mutating operation. Review decision D4 says to hold that. It also adds a task to this feature. |
| Do nothing | T2 cannot freeze `OperationContract`. T1 still lands, and T3–T12 wait behind T2. |

**Recommendation: b.** It settles the one part that gets costlier with every
published provider, and leaves the part that stays cheap (previewing) for when
a second provider can shape it.

**Scenario.** A provider author writes `cloudflare.d1@1`:

```python
D1 = contract("cloudflare.d1@1",
    operations={"diagnose": op(effects=set()),           # read-only: validate checks it
                "provision": op(effects={"mutates"})},   # changes the subject, in scope
    ...)
```

A month later someone adds `delete` with `effects={"mutates", "destroys"}`.
`func rise-validate` refuses it, with a finding that destructive operations need
positive identity (Decision 11) and it has not shipped yet. The unsafe operation
cannot land quietly. Under option a, the same `delete` declares `mutating=True`,
looks exactly like `provision`, and validates clean.

**What proceeds regardless.** T1 (records). The R-1 and R-3 research needs no
member decision: they are recommendations the owner reviews on the page. Stage
5 stays unpromoted either way.

## The architecture gate

### Region map

The region was mapped in revision 1 with zvec-grep (`/usr/local/bin/zg`,
worktree index), serena (`_plugins/loader.py` overview) and graphify (the
worktree `graphify-out/graph.json`), and read at the source. Revision 2
re-verified the seams it newly relies on by reading the source:
`src/functualize/_types/host.py` (the `PluginHost` port),
`src/functualize/app/core.py:482-494`, `src/functualize/app/commands.py:158-182`,
and `tests/spec/test_every_declared_group_has_a_reader.py`. This session refused
serena and shell search outside the run workdir, so revision 2's checks are
direct reads. research.md lists each one.

Codemaps read: the five under `contributor/architecture/codemaps/`. One
diagram-vs-codemap finding stands from revision 1 (the `_gate` peer, below).

### BEFORE

```
BEFORE (origin/master ef1939d — verified: 'risekit' 0 hits, '\bRise\b' 0 hits)

   a job module                discovery (peer layer)            boot (composition root)
  ───────────────────    ─────────────────────────────────    ──────────────────────────────
  jobs/infra.py            _discovery/providers.py              _app/boot.py
    def provision(...)      extract_ext_metadata(func)           validate_plugin_ext_metadata()
         │                   __functualize_ext_<ns>__    →        namespace owned ⇔ a loaded
         │                   → metadata["plugins"][ns]            plugin's name or an entry in
         │                        │                               its functualize_ext_namespaces
         │                        │                          orphan ns → warning
         │                        ▼
         │                 JobDescriptor.metadata ──► _engine/executor.py  (single path)
         │                        ▲                           ▲
         │                        │ get_jobs / get_job        │ Invoke("<job name>")
         │                 PluginHost (public port, _types/host.py)
         │                 _plugins/loader.py  PluginLoader(group="functualize.plugins")
         │                 _app/boot.py  EntryPointProvider: group "functualize.jobs"
         │                   (enumerates WITHOUT metadata; get_job materializes)
         ▼
  delivered by _cli/ as `func infra provision`

  THERE IS NO: package notion · contract format · judge · authoring kit.
```

Pre-existing smells on the BEFORE:

- **Primitive obsession**: `src/functualize/_discovery/providers.py:296`
  (`extract_ext_metadata`). The seam's payload is a JSON dict by contract,
  untyped at the core boundary. This feature consumes the smell; it does not
  add it.
- **Incomplete abstraction (taxonomy)**: `src/functualize/_primitives/plugin_kinds.py`
  (`classify_group`). Every `functualize.plugins` entry is labelled `ADAPTER`.
  The maintainer accepted this in writing on 2026-09-17.

### AFTER

```
AFTER (zero core change — gate G1: git diff vs origin/master over src/functualize/ empty;
       zero new entry-point groups — gate G9)

  ┌──────────────────────────────────────────────────────────────────────────┐
  │ functualize core — UNCHANGED                                             │
  │   public: functualize.plugin (PluginHost) · functualize.job (Invoke)     │
  └────▲──────────────────────────▲─────────────────────────────▲────────────┘
       │ public API only           │ public API only             │ public API only
  ┌────┴───────────────────────┐   │                             │
  │ functualize-rise           │   │                             │
  │ plugins/domains/…-rise/    │   │                             │
  │  RisePlugin (functualize.  │   │                             │
  │   plugins: rise; owns ns   │   │                             │
  │   "rise"; di.provide(      │   │                             │
  │   RiseCatalog(host)))      │   │                             │
  │  schema · CapabilityContract   │                             │
  │  jobs rise-validate,       │   │                             │
  │       rise-diagnose        │   │                             │
  │  = THE JUDGE               │   │                             │
  └────▲───────────▲───────────┘   │                             │
       │           │ imports rise  │                             │
       │    ┌──────┴───────────────┴─────┐                       │
       │    │ functualize-risekit        │                       │
       │    │ plugins/domains/…-risekit/ │                       │
       │    │  contract(...) helper      │                       │
       │    │  @operation decorator      │                       │
       │    │  observation→record builder│                       │
       │    │  = THE TOOLKIT (no provider│                       │
       │    │    inside — B5, gate G8)   │                       │
       │    └──────▲─────────────────────┘                       │
       │           │ depends on risekit (like any outside author)│
       │    ┌──────┴─────────────────────────────────────────────┴────┐
       │    │ functualize-rise-cloudflare                              │
       │    │ plugins/substrates/functualize-rise-cloudflare/          │
       │    │  contracts.py: D1 = cloudflare.d1@1, WORKER = …worker@1  │
       │    │    (namespace owner of "cloudflare")                     │
       │    │  jobs (functualize.jobs): cloudflare-d1-diagnose,        │
       │    │    cloudflare-d1-provision, cloudflare-worker-diagnose   │
       │    │  = A PROVIDER PACKAGE, authored with RiseKit             │
       │    └──────────────────────────────────────────────────────────┘
       │
  ┌────┴─────────────────────────────────────────────────────────────────┐
  │ hand-written fixture package (functualize-rise tests) — imports Rise │
  │ types only, never RiseKit (B2)                                       │
  └──────────────────────────────────────────────────────────────────────┘

  dependencies, always one way:
    rise ──► functualize public API         (never functualize._*)
    risekit ──► rise, functualize public API
    rise-cloudflare ──► risekit, rise, functualize public API
    rise ─✗► risekit, rise-cloudflare        (B2)
    risekit ─✗► rise-cloudflare              (B5)
    functualize ─✗► any of the three         (B1)
  discovery: Rise reads jobs via PluginHost.get_jobs/get_job, and contracts by
    following each job's contract_ref (B6) — no registry, no new group.
  execution: rise-diagnose → Invoke("<operation job>") (B4).
```

Boundary crossings against the seven import-linter contracts in
`pyproject.toml`: **none gains an edge**, because core does not change. The
three packages live outside `functualize`. They cross into it only through
public folders, which is the same shape as `functualize-decision-jev`. What
crosses a *package* boundary is data and two string-addressed references:
JSON metadata (C3), contract values reached through `contract_ref` (C4),
observations (C5), NDJSON records (C6), entry-point tables (C2) and
config-resolved credentials (C8).

Diagram-vs-codemap finding, carried from revision 1:
`codemaps/dependencies.md` draws four peer layers, while `pyproject.toml`'s
independence contract lists five (`_gate` included). It is recorded here, not
fixed: B1 makes the question moot for this feature.

### Iteration log

- **Revision 1 → 2, AFTER redrawn.** The member's correction moved the provider
  out of RiseKit. Redrawing showed that RiseKit's only remaining content is
  authoring helpers. The "standard library" role in Decision 2 waits until a
  second provider needs a shared contract (D4).
- **Revision 1 → 2, discovery redrawn.** The entry-point group was replaced by
  `contract_ref` (sub-check 2). The smell check below was re-run on the new
  shape.
- **New premise found while redrawing (S4):** entry-point jobs enumerate without
  metadata. Revision 1's design would have seen every provider job's Rise
  metadata as `{}` on enumeration. Rise now materializes by name.

### Candidate-AFTER smell check (what revision 2 introduces)

- **Speculative generality.** Is a three-package split premature, given
  ADR-026 ("one implementation does not earn an abstraction package")? No.
  Each package has a second user from day one: Rise judges both the
  hand-written fixture and the RiseKit-built provider, and RiseKit serves both
  the provider and the example project. The provider is a separate distribution
  because the member requires it, not as a speculative layer.
- **Inappropriate intimacy** via `contract_ref`. A string path couples a job to
  a module location. It is checked at validate time (S7.1–2), and the coupling
  is declared as SM-4.
- **Middle man.** RiseKit's decorator could have become pure forwarding. It is
  not: it derives two strings from one typed symbol, which is what Decision 14
  asks for. Its value is that the derivation exists, not that it does much
  work.
- **Shotgun surgery.** A contract-format change touches `functualize-rise`, the
  RiseKit helper and every contract owner. This is declared as SM-2.
- **Forbidden patterns** (`.spec/CONSTITUTION.md`): none. There are no ABC
  ports (`CapabilityContract` is a frozen value); no global state
  (`RiseCatalog` is an app-scoped DI instance holding the host, not a module
  singleton); no `_cli` internals; no peer imports; no `functualize._*` import
  in any of the three packages (gate G11).

## Seams (every core seam this feature rides, all pre-existing and verified)

| Seam | Where | What it already does |
|---|---|---|
| ext-metadata extraction | `src/functualize/_discovery/providers.py:296-312` | lifts `__functualize_ext_<ns>__` into `metadata["plugins"][ns]` |
| namespace ownership + orphan warning | `src/functualize/_app/boot.py:2104-2148` | a plugin owns `ns` via its `name` or `functualize_ext_namespaces`; orphan → warn, `plugins.strict` → `OrphanedPluginMetadataError` |
| plugin loading | `src/functualize/_plugins/loader.py` | `functualize.plugins` entry points; precedent `jev = "functualize_decision_jev:JevPlugin"` |
| job lookup, public | `src/functualize/_types/host.py:296-302` (`PluginHost.get_jobs`, `get_job`); `src/functualize/app/core.py:482-494` | every descriptor, and one materialized by name |
| entry-point jobs enumerate without metadata | `src/functualize/_discovery/providers.py:700-740`; `src/functualize/app/commands.py:158-182` | `get_job(name)` materializes; S4 relies on it |
| DI for the catalog | `PluginHost.di.provide` (`src/functualize/_types/host.py:116`) | app-scoped instance a job can inject |
| execution | `functualize.job` `Invoke`; `src/functualize/_engine/capabilities/invoke.py:96-125` | `Invoke("<job>") -> JobResult` with `return_value` (S14) |
| credentials | config/secrets resolution | ordinary job parameters; names already used by `tests/substrate_probe/d1.py` |
| declared-group reader test | `tests/spec/test_every_declared_group_has_a_reader.py` | refuses an unread `functualize.*` group; G9 relies on it |

B1 is therefore not an aspiration. The foundation adds **no** core change,
because every seam it needs already ships and is public.

## Surviving smells

Each entry names the smell by catalogue name, where it lives, why it survives,
and whether it needs maintainer review.

- **SM-1 — Primitive obsession** (*Bloaters*), at the declaration seam. Rise
  declarations cross the job boundary as JSON dicts (C3), and records cross
  stdout as NDJSON lines (C6). Accepted: the seam's own contract *is*
  JSON-serializability, and a typed object would demand an import that a
  hand-written package (B2) may not have. Typed models exist on both sides. No
  review needed.
- **SM-2 — Shotgun surgery** (*Change Preventers*). A change to the contract
  *format* (C4) lands in `functualize-rise`, the RiseKit helper and
  `functualize-rise-cloudflare` together. Rule of Three says wait. AC-4's gates
  turn silent drift into a red test. Revisit when a second contract owner
  appears. No review needed now; flagged for stage 5.
- **SM-3 — Incomplete abstraction (taxonomy label)**, resolved down to an
  inherited residue. The new entry-point group is gone (sub-check 2). What
  remains is that the `rise` plugin prints as `ADAPTER`, like every
  `functualize.plugins` entry. The maintainer accepted this on 2026-09-17
  (`.spec/STATUS.md:2930-2933`). It is not introduced here, and needs no new
  review.
- **SM-4 — Inappropriate intimacy** (*Couplers*), `contract_ref` as a module
  path. A job names where its contract lives, so moving a contract module breaks
  every reference to it. Accepted: the string is the static form of the typed
  symbol import Decision 15 prescribes; RiseKit derives it, so it is never typed
  by hand; and S7.1–2 turns a broken reference into a named finding rather than
  a silent miss. Stage 5's registry may add identity-based lookup *on top of*
  it. No review needed.

No other smell survives. The forbidden patterns of `.spec/CONSTITUTION.md` are
carried by none of the AFTER (checked above).

## Design skills consulted

- `python-design-patterns` (in-repo,
  `.claude/skills/python-design-patterns` → `.agents/skills/python-design-patterns`):
  KISS (the minimal assessment rule), Single Responsibility (judge, toolkit,
  provider and runtime are four responsibilities in four places), composition
  over inheritance (packages compose over the public API).
- `design-patterns-refactoring` (user-level Refactoring.Guru catalogue, loaded
  this session): the smell names above (primitive obsession, shotgun surgery,
  speculative generality, inappropriate intimacy, middle man) and the relations
  ladder (every arrow stays at *dependency*, the weakest relation that works).

## Stage 5 consumption list

What the later Rise/RiseKit slices consume from this feature, in order. This is
the single ordered account AC-8 asks for, and the list stage 5 is atomized from
after the leader updates the Initiative's continuation queue (page 4882456,
queue items 4–7).

1. **Deploying a Functualize operation into a Worker** (queue item 4, cloud
   execution). Two pieces: a Functualize Worker adapter plugin (generic), and a
   `deploy` operation added to `cloudflare.worker@1` in the provider package.
   Consumes: the Worker subject identity, the provider package, the
   idempotent-provision pattern of `cloudflare.d1@1`, relation mechanics. The
   owner's comment 11960340 makes the deploy mechanism selectable (`wrangler`,
   Terraform, Pulumi). That makes this item depend on item 4's operation
   strategies, or on shipping one strategy first and declaring the others.
2. **The D1 runtime store** (queue item 5; FUN-22). A generic Functualize plugin.
   It consumes nothing from Rise, and appears here only for ordering: its
   database is provisioned through `cloudflare-d1-provision`, so the deploy path
   cannot bypass Rise (FUN-8 AC 6).
3. **`rise-lock`** (Decision 7). Consumes: the contract identity grammar (C3),
   the package's declared contracts and operations. Open: whether a copy lives
   under `$XDG_STATE_HOME` (comment 11927566).
4. **Operation strategies and preference policy** (Decisions 8–10). Consumes:
   operations as ordinary jobs (B4), the aggregation rules (S11–S13).
5. **Origin, binding and lifecycle authority, and `delete`** (Decision 11).
   Consumes: subject identity, relations, criticality.
6. **Typed consumer proxy** (`Requires[...]`, Decision 15) and the **first
   common-vocabulary contract** in RiseKit. Consumes: `contract_ref` (the typed
   symbol it stands for), the RiseKit helper. Created only when a second
   provider needs a shared contract (D4). Open (comment 11927592): resolving the
   proxy per invocation through Functualize DI needs a factory registration
   that `PluginHost` does not expose, or a boot-time lazy resolver
   (research.md § *Tracked*).
7. **Namespace-ownership proof** (Decision 12). Consumes: `contract_ref`, package
   id. Owner's question (comment 11927583): repository URL, attestation or
   registry identity.
8. **The no-import static analyzer, then LSP** (Decisions 4, 14, 15). Consumes:
   the declaration schema (C3), `contract_ref` as a static string.
9. **Registry acquisition and proof-carrying packages** (Decision 13; 2.0 North
   Star 4849705, proposed). Generic Functualize machinery. Consumes: the package
   id, the contract identity, `diagnosis_id`.
10. **RiseKit author test harness** (comment 11960331; research.md § *R-3*,
    provisional). Two shipped tiers in `functualize_risekit.testing`: a
    sandboxed `HOME`/`XDG_*` subprocess, and a container (docker/podman) harness
    for host-scope isolation. Sequenced before the first host-mutating provider
    (a `dev.mise@1`-style package), not before the Cloudflare one. Consumes:
    `@operation`, the record builder, the effect vocabulary from OS-1 (the
    harness can check that a read-only operation changed nothing).
11. **Plan / dry-run for operations** (comment 11927557; research.md § *R-2*,
    provisional; only if OS-1 picks a or b). An optional `plannable` flag and a
    `plan` record kind. Additive. Consumes: OS-1's effect vocabulary, and item
    1's first mutating remote operation, so that a second provider shapes the
    plan format. Inspiration to verify: Terraform plan, Pulumi preview (comment
    11862020).

Stage 5 also inherits the open surface questions in contracts.md C1/C7 (the
`func` spelling, `[all]` membership, the provider's directory).

## Approach

Twelve tasks in ten waves (tasks.md):

- **Records (T1, wave 0)**: ADR-031, the `.spec/ARCHITECTURE.md` boundary
  section, and a `.spec/STATUS.md` entry. Releasable on the member's word.
- **The judge (T2–T6, waves 1–4)**: `functualize-rise`, its plugin and
  `RiseCatalog`, the schema and contract type, `rise-validate`, `rise-diagnose`,
  the B2 fixture twin, and the orphan behaviour.
- **The toolkit (T7, wave 5)**: `functualize-risekit`. Contract helper,
  `@operation`, and the record builder. No provider.
- **The provider (T8–T9, waves 6–7)**: `functualize-rise-cloudflare`, authored
  with RiseKit. D1 first, then the Worker with the required relation.
- **Proof and close (T10–T12, waves 8–9)**: the example project, the
  traceability review, and the final gates and CHANGELOG entry.

Design notes the executor should not re-derive:

- The fake transport is a Protocol bound through ordinary job parameters or DI,
  so offline tests bind it by configuration and the live jobs change no code.
- `diagnosis_id` is one `uuid4` per invocation, shared by every record of that
  invocation.
- `RiseCatalog` is provided by `RisePlugin` through `host.di.provide` and holds
  the host as an instance attribute. Rise jobs inject it.

## Files to change

Nothing below touches `src/functualize/**` or any existing package's
`plugins/**/src/**`. The three new packages' `src/` trees are new files, gated by
the wave graph this set lands.

| File | Size | Change |
|---|---|---|
| `contributor/adr/031-rise-judges-risekit-authors-functualize-runs.md` | new ~70 lines | the boundary decision; 031 is the next free number (030 is the highest) |
| `.spec/ARCHITECTURE.md` | existing | new boundary section; refresh the *Monorepo Plugin Packaging* tree to the grouped layout |
| `.spec/STATUS.md` | existing | open-features entry |
| `plugins/domains/functualize-rise/` | new ~700 LOC + tests | judge |
| `plugins/domains/functualize-risekit/` | new ~300 LOC + tests | toolkit |
| `plugins/substrates/functualize-rise-cloudflare/` | new ~500 LOC + tests | provider package |
| `pyproject.toml` | existing | three `[tool.uv.sources]` entries; the workspace glob `plugins/*/*` already covers the directories |
| `uv.lock` | existing | regenerated by `uv sync` |
| `.github/workflows/ci.yml` | existing | one plugin-test step per new package (plugin tests are not root-collected) |
| `examples/rise-cloudflare-d1/` | new ~150 LOC | example Rise package, pytest-collected |
| `CHANGELOG.md` | existing | hand-written entry |

## Risks

- **S4's materialization cost.** `rise-validate` and `rise-diagnose` import every
  `functualize.jobs`-publishing distribution once per command. This is bounded:
  it happens per command, never at boot, so warm boot is untouched. Measure it in
  T4 and record the result.
- **Live-tier flake against Cloudflare.** Offline fake-transport tests carry the
  behaviour. The live tier skips (never fails) without credentials and touches
  only `rise-test-` resources (C8).
- **Shared-infrastructure churn.** `pyproject.toml`, `uv.lock` and `ci.yml`: the
  step-tier mapper exits 3 on them, so T2, T7 and T8 verify with a tip-tier
  dispatch.
- **Provision creates real resources.** The idempotence rule (S16) and the name
  prefix bound the blast radius. `delete` stays out of scope on purpose.
- **Names are provisional** under the 1.0 promise (contracts.md header).
- **The B2 fixture can rot into a second implementation.** T5's single test,
  parametrized over both twins, keeps them structurally identical.
