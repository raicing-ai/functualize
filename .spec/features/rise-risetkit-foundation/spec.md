# Rise / RiseKit foundation — specification

Status: **Revision 5 — Rise v1 on the 0.5.0 cut. Awaiting the owner's
confirmation.** On 2026-10-10 the owner directed: "We will create the first
version of rise, based on the 0.5.0 cut. Plan for it and adjust the shape and
implementation for it."

Revision 5 retargets the feature from "Rise once core class discovery
exists" to "**Rise v1 on Functualize 0.5.0's public API, with no core
change**". Where it changes revision 4.1, the change is marked **[5]**.

Revision 4 was confirmed by the owner on 2026-10-05T17:27Z (§10). The 4.1
amendments (B6, S6, S15.12) were never answered and are carried into the
revision 5 confirmation.

- **Canon.** Shape Intent SD/5407068 **v18**, `Authority: Approved`. It was
  re-read live on 2026-10-10: version 18, content hash unchanged since the
  2026-10-05 read. Revision 5 departs from one sentence of D16, the "one
  generic class-discovery path". That departure needs a **shape amendment**,
  which the owner approves on the page (§0, A-1). This spec does not approve
  it.
- **Vault canon moved.** SD/12779576 is now **v3, `Authority: Approved`**,
  approved by the maintainer on 2026-10-09. It covers subject-address groups
  with nearest-ancestor lookup, and environment-qualified entries. It is
  **not implemented in 0.5.0**: at the cut, `VaultIdentity` is still
  `(scope, target, field)`. See §0 and S7.
- **Re-read live for this revision** (2026-10-10):
  - SD/5407068 v18, updated 2026-10-05 09:27:54 UTC;
  - SD/12779576 v3, updated 2026-10-09 09:38:55 UTC;
  - Jira FUN-8, updated 2026-10-05 09:53:58 UTC, In Progress. It names no
    release.
- **Base.** `origin/master` at `4e816a0f`, the base of the 0.5.0 release PR #99
  (head `e889f3e9`, "Mechanical only: no product code, no behaviour change").
  Every count and negative below was produced by the command printed beside it,
  on that base. Revision 4.1 was measured on `ba36b859`, and every count is
  unchanged.
- `research.md` is unchanged. §0 holds this revision's feasibility evidence.

## 0. Target: Rise v1 on the 0.5.0 cut [5]

**Reading of the directive.** Rise v1 is built against Functualize 0.5.0's
public API **as released**, and changes nothing in `src/functualize/` (B1). The
three Rise distributions join the repository's lockstep release in the
**first release after 0.5.0**, requiring `functualize>=0.5.0`. They do not
hold the 0.5.0 release PR, which is mechanical and has "no feature PR to ride".
This reading is decision **R-1** for the owner (§10).

**What 0.5.0 lacks.** Of the prerequisites revision 4 named (§6), 0.5.0
contains none of P-1 to P-6. In particular, class discovery is absent at the
cut:

```
git grep -c -e isclass -e getmembers origin/chore/release-0-5-0 -- src/functualize/_discovery src/functualize/_app   # 0 files
```

**Probe: what 0.5.0's public API does allow.** The probe was a throwaway
script with public imports only (`functualize`, `functualize.app.config`,
`functualize.job`, `functualize.plugin`, `functualize.types`), run on
`4e816a0f`. It is not committed.

| # | Question | Result |
|---|---|---|
| F-1 | Can a plugin register a subject class's operations as jobs through `StaticProvider` + `Job(fn, name, group)`? | **Yes.** Both jobs listed and ran. **Job names are global:** two jobs both named `up` in different groups collide, and one is **silently dropped**. Names must therefore carry the group (`name=f"{group}.{verb}"`), as `docs/guides/subjects.md` already does. |
| F-2 | Can a frozen pydantic subject model be the job's config parameter? | **Yes.** `subject: D1` resolved `database_name` from the `config.base.toml` section `[<job name>]`, and the secret `api_token: Secret[str]` from `<JOB>_<FIELD>`. The run record printed it as `'•••'`. |
| F-3 | Can a `rise` command dispatch through `Invoke` by name? | **Yes.** `inv("<canonical job>", address=…)` from a plugin-registered `rise.up` returned a child `JobResult`. |
| F-4 | Does an environment-declared value act as a fixed literal? | **Yes, passed as flattened field kwargs** (`database_name="literal"`). That is the *explicit argument* tier, which outranks vault, environment variable and file. Passing a whole model instance (`subject=D1(...)`) did **not** win; the file value did. |
| F-5 | Do generated tags survive registration? | **Yes**, on `JobDescriptor.declaration.tags`. Re-applying `@job(tags=…)` **replaces** an author's existing declaration (their `category` was lost), so Rise must merge it. The declaration lives on the documented attribute `__functualize_job__` (`docs/guides/jobs-discovery.md:377`). `JobDeclaration` is public (`functualize.job`). |
| F-6 | Is an `-> Environment` job discoverable, and is its annotation readable? | **Yes.** A directory job `def cloudflare_dev() -> Environment` was listed, and `get_job(...).function.__annotations__["return"]` was the class. |
| F-7 | Can a subject's operation jobs share one config section, and so one vault target? | **No, not in 0.5.0.** For two plugin-registered jobs in group `cloudflare.d1.api`, a run reads only the job-name section: `[cloudflare.d1.api.up]` reached `up` and not `diagnose`, and `[cloudflare.d1.api]` reached neither (both in quoted and nested TOML form). `@job(config_section=…)` had no effect. **Core inconsistency found:** `app.configuration.get_job_config_section("cloudflare.d1.api.up")` returns `cloudflare.d1.api`, the group, and its docstring says it "mirrors the kernel" (`src/functualize/_app/configuration_facade.py:59-80`). So `info` and `env` would name a section the run does not read. This is reported for a separate ticket; it is not fixed here (B1). |

**Consequences carried into the behaviour below.**

- B6 and S4: providers bind their own subject classes through Functualize's
  plugin seam with a Rise helper. This is the transitional stand-in for P-1.
- S6: environment literals are passed as explicit field kwargs.
- S3: tags are merged into the author's declaration.
- S7: under the settled OD-1 the vault entry is per *operation job*, which
  F-7 makes a v1 limitation.

**Shape amendment the owner must approve** (proposed wording for SD/5407068;
this spec does not write the page):

> **A-1 (Rise v1 on Functualize 0.5.0).** Until Functualize ships generic class
> discovery, a provider binds its subject classes through Functualize's
> public plugin seam (`StaticProvider`), with a Rise helper that derives one
> canonical job per (class, operation). Discovery stays Functualize's: plugin
> entry points and `.functualize/plugins/`. Rise scans nothing, and the
> execution model is unchanged. When class discovery ships, providers drop the
> binding plugin and the job identities are kept.

## 1. Problem

Rise and RiseKit are accepted prerequisites of the 1.0 journey (FUN-8, *Accepted
premise*). The later packaging slice, the cloud path and the 1.0 release proof
must go through them rather than around them. Nothing in the repository carries
either name today:

```
git grep -i -l risekit origin/master | wc -l       # 0
git grep -E -l '\bRise\b' origin/master | wc -l    # 0
```

The repository already contains the *practice* that Rise turns into a
convention. `docs/guides/subjects.md` teaches subject classes
(substrate, actions, target) and stops at a deliberate edge:

> functualize ships **no concrete substrates, actions, or targets** … Concrete
> sets belong to a **vocabulary layer** — a package that supplies substrate base
> classes, action Protocols, validation, and tooling on top of this practice.
> (`docs/guides/subjects.md`, *What this guide does not define*)

This feature builds that vocabulary layer, which the approved canon names Rise
and RiseKit. It does three things:

1. It draws the boundary between Functualize, Rise, RiseKit and provider
   packages, and records that boundary as a decision.
2. It defines the declaration model: typed subjects, contracts, environment
   trees, operations and realizations.
3. It builds the smallest machinery that makes the model executable:
   `validate`, `diagnose` and `up` over a scope. That machinery is proven on a
   Cloudflare D1 + Worker provider package written with RiseKit by an author
   standing outside RiseKit.

## 2. Vocabulary

| Term | Meaning in this feature | Canon |
|---|---|---|
| **Functualize** | The runtime: jobs, plugins, discovery, `Invoke`, configuration, secrets, Gates, stores. It knows nothing about Rise. | D13 |
| **Rise** | "A convention and working ecosystem layered on Functualize for building compatible operational packages." It defines the declaration model, the identities, the operation roles, the diagnosis envelope, and the semantics of `validate`, `diagnose` and `up`. | D1 |
| **RiseKit** | "The reference toolkit and reusable package ecosystem implementing the Rise convention." In this feature it is a distribution of typed authoring building blocks. It holds no provider package (B5). | D1 |
| **Provider package** | A Rise Package in its own distribution. It defines contracts in a namespace it owns, implements them, or both. | D1, D12 |
| **Rise Package** | A logical compatibility boundary over Functualize-discovered components. It is not necessarily one Python distribution. | D14 |
| **Subject** | A durable or externally meaningful thing that is managed. In code it is a typed Python class. An *instance* is identified by immutable, typed, serializable configuration. | D2, D16, D17 |
| **Contract** | An abstract subject class carrying a namespaced, versioned identity (`ns.name@major`). It defines operation signatures and a realization type. The word is always **contract** or **Rise contract**, never bare "capability": in Functualize, a *capability* is an injected parameter such as `Log` or `Invoke` (`docs/guides/subjects.md`, note *Actions, not capabilities*). | D12, D18 |
| **Operation** | A method on a subject class. Each one is an ordinary Functualize job with one canonical job identity at class level. | D16, D23 |
| **Role** | The effect class Rise infers from an operation's name: `read-only`, `convergent`, `mutating` or `destructive`. | D16 |
| **Environment** | The value returned by an ordinary job annotated `-> Environment`. It is a lazily evaluated tree of subjects and nested scopes. | D22 |
| **Address** | A subject's address is its environment's job address joined to its local id. A **scope** selects an address subtree. | D22 |
| **Ref** | A typed configuration field that links one subject to another (`Ref[T]`, `Ref["address"]`). | D21, D22 |
| **Realization** | The Rise-visible result an `up` produces, recorded through a persistence port. | D18, D27 |
| **Diagnosis record** | One NDJSON line: the universal envelope plus a typed `observation`. | D3, D5 |

## 3. The boundary

**Functualize runs; Rise defines and judges; RiseKit makes the conformant path
the easy one; provider packages implement.** Dependencies point one way:

```
functualize (public API)  ◄──  rise  ◄──  risekit  ◄──  provider packages
                                 ▲                       (functualize-rise-cloudflare, …)
                                 └──── a hand-written provider may depend on rise alone
```

- **B1 — Functualize knows nothing of Rise.** No module under `src/functualize/`
  imports Rise, RiseKit or a provider package, and this feature's own diff
  leaves `src/functualize/` untouched. The Functualize-side prerequisites in §6
  are owned by separate tickets. They are generic Functualize features that do
  not name Rise (D13: "Functualize must remain fully usable without Rise").
- **B2 — Rise does not need RiseKit.** A provider that subclasses Rise's own
  base types and imports nothing from RiseKit validates, diagnoses and runs `up`
  exactly like one built with RiseKit. Rise never imports RiseKit.
- **B3 — RiseKit invents no semantics.** Everything RiseKit produces (substrate
  bases, observation models, contract-test helpers) is defined and validated by
  Rise. A RiseKit-built provider that Rise rejects is a RiseKit defect.
- **B4 — Execution stays Functualize-native.** Rise performs an operation by
  calling `Invoke` with the operation's canonical job and the subject address.
  It never calls provider code directly (D15, D23).
- **B5 — The RiseKit distribution carries no provider.** RiseKit names no
  provider domain, and no provider package depends the other way. Reference
  packages that conform to RiseKit are separate distributions in RiseKit's
  ecosystem. This is the member's correction of 2026-10-02, read against D1
  (§7, PC-2).
- **B6 — Rise adds no discovery and no loader.** Rise sees subject classes,
  operations and environment jobs only through Functualize discovery. Rise
  registers no entry-point group and scans no module (D14: "Rise does not add a
  separate runtime job/plugin loader").

  **[5] Binding on 0.5.0 (shape amendment A-1).** Functualize 0.5.0 has no
  class-discovery path (§0). Each **provider package** therefore binds its own
  subject classes from its own Functualize plugin:
  `app.extensions.add_job_provider(StaticProvider(functualize_rise.bind(<classes>)))`.
  The plugin is listed under the existing `functualize.plugins` group. A
  project binds its local subjects the same way from `.functualize/plugins/`.
  `bind()` is a pure function from classes to public `Job` values. It imports
  nothing it was not handed, and it is never called by Rise on another
  package's behalf. The loader, discovery and execution are all Functualize's.
  When core class discovery ships, providers delete the plugin and the job
  identities (S4) stay the same.

  **[4.1]** Rise's *own* three commands (`rise validate | diagnose | up`) are
  registered by its plugin through the public `add_job_provider` /
  `StaticProvider` seam, under the existing `functualize.plugins` group. They
  are not published under `functualize.jobs`. The reason is a documented
  limitation: an entry-point job's `@job(group=…)` is unknown until the job is
  materialized (`src/functualize/_discovery/providers.py:735-741`), so a
  `rise` command group cannot be listed from the entry-point table.

### Which side each piece enters from

| Piece | Enters from | Canon |
|---|---|---|
| `Subject` base, contract declaration (abstract subject + identity), `Ref`, `Environment`, `Realization` and `Observation` bases | **Rise** | D16–D18, D21, D22, D27 |
| Role inference from operation names; generated `rise:op:*`, `rise:implements:*` and `effect:*` job metadata | **Rise** | D16 |
| Descriptor generation from the Python declaration (JSON, on demand, cached) | **Rise** | D14, D18 |
| `validate`, `diagnose`, `up`; traversal, aggregation, NDJSON, exit status | **Rise** | D3, D5, D6, D27 |
| Candidate selection for `up` (this feature: exactly one candidate, or refuse) | **Rise** | D7, D9, D19 |
| Realization record and persistence port, plus a local backend | **Rise** | D7, D27 |
| Standard substrate base classes and their typed observation models (this feature: *remote resource* only) | **RiseKit** | D3, D27 |
| Contract-test helper that runs `validate` and the contract's checks against a provider's candidates | **RiseKit** | D19 |
| **[5]** `bind(*classes) -> list[Job]`: canonical job per (class, operation), merged tags, config parameter wiring | **Rise** (a pure helper) | D16, D23; amendment A-1 |
| **[5]** The plugin that calls `bind()` for a provider's classes | **Provider package**, or the project's `.functualize/plugins/` for local subjects | D14; amendment A-1 |
| `cloudflare.d1@1`, `cloudflare.worker@1` contracts and their implementations | **Provider package** `functualize-rise-cloudflare` | D12, D26 |
| Class discovery, Gates, `Setting()`, configuration resolution, vault, `ExitCode` | **Functualize** | D13, D16, D20, D24, D27 |
| Jira and Confluence | **Neither, at runtime.** They authorize *development* (§8) | member correction 2026-10-02 |

## 4. Behaviour

### 4.1 Declaring subjects and contracts

- **S1.** A subject is a class deriving from Rise's `Subject`. Its fields are
  typed configuration and immutable once constructed. Construction performs no
  operational I/O. Two instances with equal configuration are the same subject
  configuration (D17).
- **S2.** A **contract** is an abstract `Subject` subclass that declares a
  namespaced identity (`<namespace>.<name>@<major>`), its abstract operations
  with their signatures, and a realization type (D18). A concrete subclass
  *implements* that contract. A concrete subject with no contract ancestor is a
  local subject, with identity `local:<name>` (D16, D27). A local subject needs
  no published contract id.
- **S3.** An operation is a method of a concrete subject class. Rise infers its
  **role** from its name:
  - `validate` and `diagnose` are read-only;
  - `up` and `update` are convergent;
  - `start` and `stop` are mutating;
  - `down` is destructive;
  - any other name is mutating unless explicitly declared otherwise.

  From that typed declaration Rise generates the metadata `rise:op:<verb>`,
  `rise:implements:<ns.name@major>/<verb>` and `effect:<role>` on the
  operation's canonical Functualize job (D16). The author writes no
  Rise-specific decorator and no hand-maintained tag. When an author needs a
  Functualize feature (guards, caching, timeout), they use Functualize's
  existing `@job` metadata.

  **[5]** `bind()` **merges** the generated tags into the method's own
  `JobDeclaration` with `dataclasses.replace`. It never re-applies
  `@job(...)`, because that replaces the author's declaration (§0, F-5).
- **S4.** Each operation has **one canonical job identity at class level** (D23).
  Invoking it supplies the subject by address. The subject instance is built
  from configuration resolved for that address (S6). There is one job per
  operation, never one per instance.

  **[5] Naming.** Functualize job names are global, and a collision drops a job
  silently (§0, F-1). So the canonical job is
  `group = <namespace>.<name>.<candidate>` and
  `name = <group>.<verb>`. For example, `cloudflare.d1.api.up` runs as
  `func cloudflare d1 api up`.
  - `<candidate>` is a short name the implementing class declares, and is
    required.
  - A local subject uses `local.<snake_class_name>` as its group, unless the
    class declares a `group`.
  - `bind()` refuses a duplicate name **inside one call**, with an error naming
    both classes. A duplicate across two plugins cannot be seen by either one,
    so `rise validate` reports a contract operation whose expected canonical
    job is missing (S15.13).
  - The job's config parameter is the implementing subject model (F-2), and an
    `address` parameter carries the address into the run.
- **S5.** A descriptor is generated on demand from the declaration. It is a
  JSON document carrying the contract identity, operations, roles, signatures,
  realization type, configuration schema and `Ref` fields. Rise caches it
  locally. It is never a committed hand-maintained file (D18). The descriptor and
  the runtime metadata of S3 are **semantically equal**: both come from the same
  declaration (D14). Freezing descriptors into built distributions and attaching
  them for publication is deferred (§6).

### 4.2 Configuration and secrets

- **S6.** A subject's fields resolve through Functualize configuration (D17).
  The active configuration environment is Functualize's existing selector: the
  first valid value among `FUNCTUALIZE_ENV`, `ENVIRONMENT` and `ENV`, otherwise
  `DEV` (`src/functualize/_app/environment.py:18-24`). That value picks the
  matching `config.<env>.toml` overlay over `config.base.toml`. Rise adds **no**
  `--env` flag and no selector of its own. Scope and configuration environment
  are independent (D25).

  **[4.1] Literal or chain.** A field given a value in the environment
  declaration is **fixed**: no configuration source and no command-line flag
  overrides it (D24: authors choose which values are invocation flags). A field
  the declaration leaves unset resolves through the canonical operation job's
  `JobConfig` chain:

  ```text
  runtime override > explicit argument > vault > environment > config file > default
  ```

  (`docs/guides/configuration.md` § *JobConfig Field Resolution*). That chain is
  keyed by the class-level job, both for the `<JOB>_<FIELD>` variable and the
  `[<job>]` section, so an unset field's chain value is **shared by every
  instance of the class**. Per-instance values come from the declaration
  literal, and per-instance *secrets* arrive with MCH-148 (OD-1).

  **[5] How "fixed" is realized on 0.5.0.** Rise dispatches with the
  declaration's set fields (`model_fields_set`) as flattened field kwargs. That
  is the *explicit argument* tier, which outranks vault, environment variable
  and file (§0, F-4). Only a *runtime override* that the operation itself
  deposits could outrank it, and that is the author's own act.

  **[5] Section per operation job.** In 0.5.0 a plugin job reads only its
  job-name section (F-7). An unset field is therefore configured per operation:
  `[cloudflare.d1.api.up]`, `[cloudflare.d1.api.diagnose]`. That is a v1
  limitation. A shared per-subject section waits for core to honour a shared
  section for plugin jobs (§6, P-8).
- **S7.** A secret-marked subject field is configuration, never an invocation
  parameter (D17). It resolves under the **approved vault contract SD/12779576
  v2**: runtime override → explicit command-line value → vault → environment →
  config file → default. A stored but unreadable vault entry does not fall
  through. A run never contacts a remote secret provider.

  This feature does **not** assume the subject-address-as-vault-group rule
  (A1) or environment-qualified vault entries (A2). Both wait for the
  SD/12779576 amendment (MCH-148). How a subject's secret field maps to a v2
  vault identity until then is open decision **OD-1** (§10).

  **[5]** The amendment is now **approved** as SD/12779576 v3 (2026-10-09). It
  is **not implemented in 0.5.0**, so Rise v1 resolves secrets under v2, as
  settled by OD-1. With F-7, the entry is per operation job, for example
  `func builtin vault put --job cloudflare.d1.api.up --field api_token`, and the
  same again for `cloudflare.d1.api.diagnose`. The vault target's exact
  spelling for a plugin-registered grouped job is verified by T14's gate before
  any document states it. Rise v1 documents this. When
  v3 lands, a subject address becomes the vault group with nearest-ancestor
  lookup, and the per-operation entries become unnecessary. No field
  declaration changes.
- **S8.** A secret value never appears in a diagnosis record, a descriptor, a
  realization, a validation finding, or a Gate payload. A realization's
  configuration fingerprint excludes the plaintext of secret fields. It records
  only which secret fields were set and from which source class (vault,
  environment, file, explicit).

### 4.3 Environments, addresses and scope

- **S9.** Any ordinary Functualize job whose return annotation is `Environment`
  declares an environment. It needs no `@environment` decorator and no tag
  (D22). Its job address names the environment.
- **S10.** Rise evaluates an environment job **lazily and without operational
  side effects**. It is called only when a command's scope reaches it. The
  result is a tree of subject instances and nested named scopes. Ordinary Python
  functions provide reuse and parameterized composition. In this feature an
  environment job's parameters are **fixed values only**. `Setting()` values and
  author-exposed flags (D24) wait for prerequisite P-3.
- **S11.** A subject's **address** is the environment's job address followed by
  its scope path and local id, dot-joined. Within one environment tree an
  address is unique; a duplicate is a validation finding. `Ref["address"]`
  links an existing subject by address, and `Ref[T]` links it by type within the
  tree. An unresolvable or ambiguous `Ref` is a validation finding.
- **S12.** A `Ref` is either an **ordering** edge, the default, or an
  **informational** relation. An ordering edge has a criticality, `required`
  (the default) or `optional`. Ordering edges must form an acyclic graph; a
  cycle is a validation finding. Informational relations are references only.
  They never order work and never aggregate status (D27, D6).
- **S13.** `--scope <address>` selects that address's subtree. Without
  `--scope`, the command acts on **the author-declared root**, which the author
  names in Functualize configuration (D25, D27). Rise has no privileged hosting
  root, no `[rise] hosting` key, and no `protected_by`. If no root is declared,
  Rise uses the one environment job when there is exactly one. With none, or
  with several, Rise refuses with `USAGE` and lists the environment addresses it
  found. It never picks one.

### 4.4 Validating

- **S14.** `func rise validate [--scope <address>]` checks every subject in scope
  and every contract they claim. It reports one finding per line and changes
  nothing. It imports declaration modules and evaluates environment jobs (S10).
  It runs no operation.
- **S15.** It reports, each as a named finding:
  1. a contract identity that violates the grammar (C4);
  2. a concrete subject missing an operation its contract declares abstract;
  3. an operation whose signature differs from the contract's;
  4. an `up` whose declared return type is not the contract's realization type;
  5. a configuration field that is mutable or not serializable;
  6. a secret-marked field declared as an invocation parameter rather than
     configuration;
  7. a duplicate address;
  8. an unresolvable or ambiguous `Ref`;
  9. an ordering cycle;
  10. a `Ref` without a resolvable criticality;
  11. a generated descriptor that disagrees with the runtime metadata (S5);
  12. **[4.1]** a secret-marked field given a literal value in an environment
      declaration. A secret in source is a leak, and S8 forbids it;
  13. **[5]** a contract operation of an in-scope subject whose canonical job
      (S4) is not registered. This covers an unbound class, and a name lost to
      a cross-plugin collision.
- **S16.** Exit status: `OK` when there are no findings, non-zero otherwise.
  The mapping onto `ExitCode` is in C10.

### 4.5 Diagnosing

- **S17.** `func rise diagnose [--scope <address>]` writes one NDJSON record per
  diagnosed subject to stdout. Each record is complete on its own line. The last
  record is a **root record** for the scope. A failed observation is a record
  with `status: "fail"` and structured `issues`; it is never a traceback in the
  stream (D5).
- **S18.** `status` is `pass` or `fail`. It is **derived** from the contract's
  assessment of the typed observation, never taken from a free-form provider
  judgement. `observation.state` is domain-specific and defined by the contract
  (D5). The minimal assessment rule confirmed by the member on 2026-10-02 is
  kept: a contract names its legal states and its passing states, plus its
  required observation fields.
- **S19.** Traversal follows ordering edges and treats informational relations
  as references. It observes **each subject address once per diagnosis**
  (memoized). A subject fails if its own assessment fails **or** a `required`
  ordering target fails. An `optional` target's failure is emitted but does not
  fail the parent. The parent carries a `required_dependency_failed` issue that
  references the child record by id; the child's detail is not copied (D6, D27).
- **S20.** Traversal continues past failures wherever observation is still safe,
  so every observable subject is emitted (D6). The order of records is
  deterministic: dependencies before dependents, with ties broken
  alphabetically by address.
- **S21.** Each `diagnose` operation runs through `Invoke` as its canonical job
  with the subject address (B4). It therefore carries normal child-run ancestry,
  events and timeouts.
- **S22.** Exit status follows the root record: `OK` when it passes, non-zero
  when it fails (D6, D27; mapping in C10).

### 4.6 Bringing up

- **S23.** `func rise up [--scope <address>]` brings every subject in scope up,
  in ordering-edge order (dependencies first). For each subject it runs the
  `up` operation through `Invoke` (B4). `up` is **convergent**: it diagnoses
  first and acts only on the difference. Running it again against a converged
  subject changes nothing and says so.
- **S24.** **Candidates.** This feature implements the generic candidate step
  (D19) in its smallest form. The concrete classes implementing a contract that
  are visible to discovery are its candidates. Then:
  - with exactly one candidate, that candidate is selected;
  - with none, Rise refuses;
  - with more than one, Rise **refuses** (`REFUSED`) and lists the candidates
    with their explanation, rather than guessing (D7, D9, D10).

  Policy, remembered binding, strategies and the Gate-backed choice are
  deferred (§6).
- **S25.** A required dependency that fails its diagnosis after its own `up`
  stops the dependents' `up`. Those dependents are reported as not attempted,
  and the exit status is non-zero. Independent branches of the tree continue.
- **S26.** A successful `up` returns an instance of the contract's realization
  type. Rise records a **base realization** through the realization persistence
  port. Its fields are: subject address, contract, candidate, resolved identity,
  configuration fingerprint (S8), isolation, time and dependency chain (D27).
  Records are append-only; a later `up` appends and never rewrites (D7, D10).
  This feature ships the port and a **local** backend. How a remote subject's
  realization is recorded before a shared backend exists is open decision
  **OD-2** (§10).
- **S27.** This feature performs **no destructive operation**. `down` and every
  other destructive role are out of scope, because they need the positive
  identity evidence and lifecycle authority of D11. Rise refuses to run an
  operation whose role is `destructive`.

### 4.7 The forcing case — a Cloudflare provider package, written with RiseKit

- **S28.** `functualize-rise-cloudflare` is its own distribution. It depends on
  `functualize-risekit`, through it on `functualize-rise`, and on Functualize's
  public API. It depends on nothing else in this repository. It owns the
  `cloudflare` namespace (D12).
- **S29.** `cloudflare.d1@1` declares a *D1 database* subject, identified by
  (account id, database name). It derives from RiseKit's remote-resource
  substrate. Its operations are:
  - `diagnose`: observe presence, uuid and state;
  - `up`: diagnose, create only when absent, and return a realization that
    carries the database uuid.

  It has no `down` (S27).
- **S30.** `cloudflare.worker@1` declares a *Worker script* subject, identified
  by (account id, script name). Its only operation is `diagnose`. It carries a
  `Ref` to the D1 subject it binds to, `required` by default. Deploying a
  Worker is **not** in this feature (§6).
- **S31.** The Cloudflare API token is a secret-marked configuration field on
  the subject (S7). Nothing in Rise, RiseKit or the provider reads the process
  environment directly; Functualize resolves the value.
- **S32.** An example project declares an environment job `cloudflare_dev()`
  returning an `Environment` that holds `d1.main` and `worker.api`.
  `worker.api` has a `Ref` to `d1.main` (`required`). Against a fake transport:
  - with the database absent, `func rise diagnose` emits three records (d1,
    worker, root). The worker and the root fail, the d1 record says why, and the
    exit status is non-zero;
  - after `func rise up --scope cloudflare_dev.d1.main`, the same diagnosis
    passes, provided the Worker exists;
  - a second `up` changes nothing.

  A live tier runs the same steps against a real account when credentials exist,
  and skips otherwise (C12).

## 5. Acceptance criteria

| # | Criterion | How it is shown | Authorized by (§8) |
|---|---|---|---|
| AC-1 | Rise and RiseKit each have a one-sentence responsibility statement and a defined boundary | §3; an ADR; a section in `.spec/ARCHITECTURE.md` | FUN-8 AC 1; D1 |
| AC-2 | B1: no core import of Rise, RiseKit or a provider, and no `src/functualize/` change in this feature's diff | `git diff --stat origin/master -- src/functualize` is empty | D13 |
| AC-3 | B2: a hand-written provider with no RiseKit import validates, diagnoses and runs `up` | fixture package test | D1, D12 |
| AC-4 | B3: every RiseKit-built provider in the tree passes `rise validate` | provider tests | D3, D4 |
| AC-5 | Declaration model: role inference and generated metadata match S3; the descriptor equals the runtime metadata (S5) | unit tests over contract fixtures | D14, D16, D18 |
| AC-6 | Environment jobs, addresses, `Ref`, scope selection and unscoped-root rules behave as S9–S13; `FUNCTUALIZE_ENV` changes configuration and never the scope | end-to-end tests through `func` | D22, D25 |
| AC-7 | `rise validate` reports each finding of S15 and exits per C10 | one fixture per finding | D3, D4 |
| AC-8 | `rise diagnose`: NDJSON envelope, derived binary status, required/optional aggregation, single observation per address, referential parents, deterministic order, exit status | end-to-end tests | D3, D5, D6, D27 |
| AC-9 | `rise up`: dependency order, convergent and idempotent, through `Invoke` with the canonical job, a base realization appended through the port, refusal on several candidates | end-to-end tests | D15, D19, D23, D27 |
| AC-10 | Forcing case S32: offline against a fake transport, and live when credentials exist | provider tests plus a skipping live tier | FUN-8 AC 2–3; D26 |
| AC-11 | B5: the RiseKit distribution carries no provider, and the provider is its own distribution | dependency/manifest check | member correction 2026-10-02; D1, D12 |
| AC-12 | B6: no new entry-point group; Rise binds no class it was not handed, and `bind()` is called only from a provider's or project's own plugin [5]; the declared-group reader test stays green | `tests/spec/test_every_declared_group_has_a_reader.py`; a source check | D14 |
| AC-13 | S8: no secret byte in records, descriptors, realizations, findings or Gate payloads | a canary-secret test across all four commands' outputs | D17, D20; SD/12779576 v2 |
| AC-14 | Development traceability: every delivered package, public name and criterion traces to a §8 row; no runtime code reads Jira or Confluence | traceability check | FUN-8 AC 4 |

## 6. Dependencies and out of scope

### Functualize prerequisites (owned by separate tickets, not this feature)

These are generic Functualize features. This feature specifies only what it
**requires** of them (contracts.md § C11). It does not build them, and it does
not work around them with a Rise-side substitute, since B6 forbids that.

| # | Prerequisite | Needed by | Verified absent on `e8e3b86` |
|---|---|---|---|
| P-1 | Generic class discovery: one canonical job per subject-class method, invoked with a subject address | **[5] Not consumed by v1.** Provider-owned binding stands in (B6, A-1); a later migration removes it | `git grep -c -e isclass -e getmembers origin/chore/release-0-5-0 -- src/functualize/_discovery src/functualize/_app` → 0 files; `docs/guides/subjects.md`: "Directory discovery ignores classes entirely" |
| P-2 | Lazy child-route hook (generated per-instance CLI routes) | instance routes, deferred (D23) | `rg -n -i -e 'lazy.?child' -e 'lazy.?route' -e 'lazy.?group' -e 'child_routes' src/functualize` → 0 hits |
| P-3 | The `Setting()` marker on job parameters | environment parameter tiers (D24); S10 is fixed-values-only until it lands | `Setting` at `src/functualize/_types/settings.py:35` is the *app-settings* declaration, not a parameter marker |
| P-4 | Value-source provenance in run records (invoked route vs canonical job) | D23 route recording | `rg -n -i -e 'invoked_route' -e 'value_source' src/functualize/_types src/functualize/_engine` → 0 hits |
| P-5 | Gate resolution started from an ordinary job | candidate choice through a Gate (D20) | Gates are workflow nodes (`src/functualize/_types/workflow.py:286`) |
| P-6 | Person-required mechanism | a Gate that waits for a person to fix a credential (D20) | — |
| P-7 | The scoped vault | S7 | v2 landed in `ba36b859` (#88) and is in 0.5.0. **[5]** v3 (subject-address groups, environment-qualified entries) is approved (SD/12779576 v3, 2026-10-09) and **not in 0.5.0** (`VaultIdentity` is still `(scope, target, field)` at `e889f3e9`). v1 uses v2 (OD-1). |
| P-8 | **[5]** A plugin-registered grouped job reads its group's config section, and `get_job_config_section` agrees with the run | a shared per-subject section and vault target (S6, S7) | measured on `4e816a0f`, §0 F-7: the run reads the job-name section, while the facade reports the group |

**[5] Nothing in this table gates v1.** Revision 4.1 made P-1 a hard stop for
FUN-8's executable proof. Under the 0.5.0 directive the proof runs on
provider-owned binding instead (B6, A-1). P-1 and P-8 become the trigger for a
later migration: delete the binding plugins, and share sections and vault
targets per subject. That migration keeps every job identity.

### Deferred to stage 5 (consumed in the order the Confluence continuation queue sets)

- **[5] Migration off the v1 binding.** When P-1 ships, providers delete their
  binding plugins. When P-8 ships, sections are shared per subject. When vault
  v3 ships, secrets move to subject-address groups. Job identities (S4) are
  kept throughout.

- Candidate policy, remembered binding, strategies, and the Gate-backed choice
  (D7–D10, D19, D20).
- `rise-lock` as a full binding history, and the shared/remote realization
  backend (D7, D26, D27).
- Origin, binding, lifecycle authority, adoption, and `down` (D11).
- Generated instance routes (D23), environment parameter tiers (D24), and
  executing through a `Ref[Host]` (D21).
- Worker deployment, secret delivery and D1 migration (D26). The Python Workers
  spike is MCH-147, run by the owner.
- Package-level and capability-level diagnosis records (D3). This feature emits
  subject records and a scope root.
- The no-import static analyzer and LSP (D4, D15).
- The registry, distribution freezing, provenance and trust (D13, D14).
- Namespace-ownership proof (D12).
- The first common-vocabulary contract.
- The isolated author test harness (research.md § R-3).
- Plan/dry-run semantics (comment 11927557).
- The remaining standard substrates (D27).

## 7. Premise changes and corrections (revision 4)

None of these reopens *whether* Rise and RiseKit are required.

- **PC-1. The subjects guide contradicts the canon in two places.** The guide is
  prior art, so the conflict is stated here rather than overridden silently.
  `docs/guides/subjects.md` (*Rules the declaration must follow*, rule 3)
  says: "Constructors are inert. No-argument, no side effects, one instance per
  process". It also says, under *A subject class, bound*: "Configuration arrives
  per invocation, not at construction". v18 says otherwise:
  - D17: "A subject's `self` identifies its instance through immutable, typed,
    serializable configuration";
  - D22: an environment tree holds many instances;
  - D16: methods are found through generic class discovery, where the guide
    says "Directory discovery ignores classes entirely".

  The approved canon controls. The guide's "no operational I/O at construction"
  survives as S1. Revising the guide belongs with P-1. The guide's *vocabulary
  layer* paragraph agrees with this feature.
- **PC-2. B5 is kept, read against D1.** D1 says RiseKit provides "implementation
  machinery, authoring support, reusable building blocks, and reference
  packages that conform to it", and calls RiseKit a "reusable package
  ecosystem". The member's correction of 2026-10-02 reads: "Risekit shouldn't
  contain packages for cloudflare etc, it should be used by other authors or
  package maintainers to create those cloudflare packages". The two are
  consistent if reference packages are separate distributions within RiseKit's
  ecosystem and the toolkit distribution holds none. This set reads it that way.
  It is open question **OQ-1** only if the owner reads D1 differently.
- **PC-3. OS-1 is closed by D16.** Revision 3 asked the owner whether operations
  should declare effects (comments 11927557, 11927574). D16 answers that roles
  are inferred from verb names and that `effect:*` metadata is generated. The
  `mutating: bool` placeholder and the plan/dry-run question are withdrawn; the
  latter is deferred.
- **PC-4. Withdrawn: the `@operation` decorator and `__functualize_ext_rise__`
  job metadata** (revision 3, contracts C3). D16 says "Rise does not introduce
  another required decorator or a second hand-maintained tag declaration." Rise
  metadata is now generated from the typed declaration (S3).
- **PC-5. Withdrawn: the `CapabilityContract` dataclass and `contract_ref`
  strings** (revision 3, C4). A contract is now an abstract subject class (D18),
  and its string identity lives in the generated descriptor (S5).
- **PC-6. Withdrawn: credentials as ordinary job parameters** (revision 3, S18).
  D17 makes them secret-marked configuration (S7, S31).
- **PC-7. Commands change shape.** `func rise-validate --package <id>` becomes
  `func rise validate [--scope <address>]`, and likewise for `diagnose`; `up` is
  added (D23, D25). Diagnosis is scoped by address, not by package (§6).
- **PC-8. "Provision" is now `up`.** In revision 3, D1 had a `provision`
  operation. Under D16, `up` is the convergent verb that does the same job.
- **PC-9 [5]. Target is Functualize 0.5.0, not a future core.** The owner's
  directive of 2026-10-10 replaces revision 4.1's "wait for class discovery"
  with "Rise v1 on the 0.5.0 cut". The probe (§0) shows the public API carries
  the whole executable path, apart from a shared per-subject config section
  and per-subject vault entries. Revision 4.1's Candidate B (Rise binding
  classes itself) stays rejected. What changes is *who* binds: the provider,
  through its own Functualize plugin, with a pure Rise helper. That needs
  shape amendment A-1.
- **PC-10 [5]. Vault canon is v3.** SD/12779576 v3 is approved
  (2026-10-09) and SD/12779576 v2 "no longer applies" as *shape*. The shipped
  code in 0.5.0 is still v2, so OD-1 (a) remains the v1 behaviour. Moving to
  v3 identities is the later migration in §6.
- **Kept from revision 3:** the D1 + Worker forcing case; the provider package
  living outside RiseKit; Jira/Confluence as development traceability, never a
  runtime input; D1 run persistence as a Functualize plugin rather than Rise
  (FUN-22); the minimal assessment rule; NDJSON with derived binary status.

## 8. Development traceability

Every source below was read live on 2026-10-05 for this revision. Revision 3's
sources and versions are in `research.md` § *Live reads*.

| Element of this feature | Confluence authority | Jira / tracker authority |
|---|---|---|
| Rise and RiseKit are required; build their machinery | SD/5407068 v18 (Canonical status) | FUN-8 (Outcome, Accepted premise); FUN-3 |
| Boundary B1–B6 | SD/5407068 v18, D1, D13, D14, D15 | FUN-8 Scope 1, AC 1 |
| Provider packages outside the RiseKit distribution (B5) | SD/5407068 v18, D1, D12 | member correction on MCH-88, 2026-10-02 |
| Subject as typed config; contract as abstract class; derived descriptors | SD/5407068 v18, D16, D17, D18 | — |
| Roles and generated metadata (S3) | SD/5407068 v18, D16 | — |
| Environment, addresses, `Ref`, scope, unscoped root (S9–S13) | SD/5407068 v18, D21, D22, D25 | — |
| `validate` / `diagnose` semantics (S14–S22) | SD/5407068 v18, D3, D4, D5, D6, D27 | FUN-8 AC 2 |
| `up`, single-candidate selection, refusal (S23–S25) | SD/5407068 v18, D7, D9, D10, D19 | FUN-8 AC 2–3 |
| Realization record and port (S26) | SD/5407068 v18, D7, D18, D27 | — |
| No destructive operation (S27) | SD/5407068 v18, D11 | — |
| Configuration environment unchanged (S6) | SD/5407068 v18, D25 | — |
| Secret resolution (S7, S8) | SD/12779576 v2 (Authority: Approved); SD/5407068 v18, D17, D20; owner decisions A1 = b, A2 = a | MCH-148 (amendment pending) |
| Forcing case D1 + Worker (S28–S32) | SD/5407068 v18, D26 | FUN-8 Scope 7; FUN-22 (D1, not "R1") |
| Python Workers spike is not this feature | SD/5407068 v18, owner decision A3 = a | MCH-147 |
| **[5]** Rise v1 targets the 0.5.0 cut; binding by provider plugins | owner directive, MCH-151 comment `01a12610` (2026-10-10); proposed amendment A-1 to SD/5407068 (§0), pending | release PR #99 (0.5.0) |
| **[5]** Vault v3 approved, not in 0.5.0 | SD/12779576 v3 (Authority: Approved, 2026-10-09) | MCH-148 |
| Functualize prerequisites P-1 to P-6 are owned elsewhere | SD/5407068 v18, *Superseded alternatives and remaining boundaries* | MCH-151 description, Scope |

## 9. The owner's inline comments on SD/5407068

There are ten, read live (`confluence_get_inline_comments`, page 5407068,
count 10).

| Comment | Disposition in revision 4 |
|---|---|
| 11960322 (graph packages / existing implementations) | **R-1 stands.** Traversal behaviour is S19–S20. The mechanism is Plan's, with research.md § R-1 as input. |
| 11862020 (Terraform / Pulumi / Aspire inspiration) | Tracked; stage 5. |
| 11927557 (plan / dry-run) | Deferred (§6). D16's roles are the substrate a later plan feature would use. |
| 11960331 (isolated author harness) | **R-3 stands**; separate RiseKit slice (§6). |
| 11960340 (Cloudflare deploy via Terraform / Pulumi / CLI) | Maps to strategies (D8, D19); deferred with Worker deployment. |
| 11927566 (`rise-lock` copy in XDG) | Folded into OD-2 and the realization backend (S26). |
| 11927574 (destructive / mutating markers) | **Closed by D16** (PC-3). research.md § R-2's recommendation is superseded; its seam analysis still holds. |
| 11927583 (who owns a contract namespace) | Deferred: namespace-ownership proof (§6). |
| 11927592 (reuse Functualize DI) | Satisfied by B4 and S21: operations run as Functualize jobs through `Invoke`, so DI is Functualize's. |
| 12648493 ("Approved") | The approval this revision is written against. |

## 10. Settled decisions (owner, 2026-10-05T17:27Z)

The owner confirmed revision 4 and answered all four items. They are decisions
now, not open questions.

- **OD-1 = (a).** A subject's secret field uses the **canonical job scope** of
  vault v2 (`--job <class-level operation job> --field <name>`). Every instance
  of a class shares that entry. Per-instance secrets arrive with the
  SD/12779576 amendment (MCH-148) without changing any field declaration.
- **OD-2 = (a).** `up` records a remote subject's realization in the **local**
  backend, marked `shared: false`. Diagnosis is the truth (S19), and there is no
  destructive operation (S27), so a stale local record cannot act.
- **OQ-1: B5 stands.** The RiseKit *distribution* holds no provider. Reference
  provider packages are separate distributions in RiseKit's ecosystem (§3,
  AC-11; the member's correction of 2026-10-02). Revision 4 phrased this
  question backwards ("confirm only if … inside"). The confirmation is recorded
  in the sense the report put it: B5 stands.
- **OQ-2: no objection.** An explicit role override is a declaration on the
  contract's abstract method, never a hand-written tag. Plan fixes the
  spelling (plan.md § *Approach*).

## 11. For the owner's confirmation of revision 5 [5]

Put to the owner with this revision. None of them is approved by this spec.

- **A-1. Shape amendment to SD/5407068** (wording in §0). It covers
  provider-owned binding on 0.5.0 until core class discovery ships. It is the
  owner's to approve on the page; the spec's B6 and S4 depend on it.
- **R-1. Release reading.** Rise's three distributions ship in the first
  release *after* 0.5.0, requiring `functualize>=0.5.0`. The alternative is to
  hold 0.5.0 (release PR #99) for Rise.
- **Carried from 4.1, never answered.** B6's plugin-registered `rise` commands,
  S6's fixed literals, and S15.12, the refused secret literal.
- **New in 5.** S4's canonical naming with a required `<candidate>`, S15.13,
  and the v1 limitations in S6 and S7: per-operation sections and vault
  entries.
- **Withdrawn.** The step-11 question about the *Dead Code (transitional)*
  window. Under v1, dispatch is wired as soon as the binding and the `rise`
  jobs land, so there is no wait on P-1.

