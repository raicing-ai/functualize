# Rise / RiseKit foundation — specification

Status: **Specify, revision 2.** The member's two corrections of 2026-10-02 are
applied: development traceability (formerly "D-1") and providers outside
RiseKit (formerly "D-3"). Neither is an approval of this set. **D-2, the
boundary, is still open** (plan.md § *The decision for the member*). Nothing in
this set authorizes Execute until D-2 is answered. T1 is records only and needs
the member's word separately.

Base: `origin/master` at `ef1939d`. Every count below was produced by the
command printed beside it, on that base. The live product sources behind every
responsibility are listed in §8 with page ids and versions.

## 1. Problem

Rise and RiseKit are accepted prerequisites of the 1.0 journey (FUN-3 delivery
principles; Initiative page 4882456 v11, "Rise and RiseKit are **accepted
prerequisites for the 1.0 North Star**"). The later packaging slice, the cloud
path and the release proof must go through them rather than around them.
Nothing in the repository carries either name today:

```
git grep -i -c risekit origin/master | wc -l      # 0
git grep -E -l '\bRise\b' origin/master | wc -l   # 0
```

The model exists only in the product design space, as a canonical shape intent
(page 5407068, v15) with fifteen decisions. The repository has no account of
where the line between Rise and RiseKit runs, which side owns each piece, or how
either one relates to the Functualize layers the constitution fixes. Without
that line, the first Cloudflare package would set the boundary by accident,
wherever its code happened to land.

This feature does two things. It **draws the line** and records it as a
decision. Then it **builds the smallest machinery on each side** that makes the
line testable, using a real Cloudflare D1 + Worker package as the forcing case.
That Cloudflare package is authored **with** RiseKit, by an author standing
outside RiseKit.

## 2. Vocabulary (defined here, because the repository has none)

| Term | Meaning in this feature |
|---|---|
| **Functualize** | The runtime: jobs, plugins, discovery, `Invoke`, config, secrets, stores. It knows nothing about Rise. |
| **Rise** | The convention, plus the **judge** that checks a package against it. It owns the declaration schema, the capability-contract format, the diagnosis record envelope, the conformance rules, and the `validate` and `diagnose` operations. |
| **RiseKit** | The **author's toolkit**. Typed authoring helpers that make a conformant package the easy one to write, and, later, the *common* capability vocabulary (contracts such as `javascript.npm@1` that several providers implement). It contains **no provider package**: no Cloudflare, no npm, nothing that manages a real resource. |
| **Provider package** | A Rise Package, in its own distribution, written by a package author **using** RiseKit. It defines the contracts of the namespace it owns, implements their operations as jobs, or both. The forcing case's provider package is `functualize-rise-cloudflare`, which owns the `cloudflare` namespace. |
| **Rise Package** | A logical compatibility boundary: a set of Functualize-discovered jobs that share one package id. It is *not* necessarily a Python distribution (shape intent, Decision 14). |
| **Rise capability contract** | A namespaced, versioned promise such as `cloudflare.d1@1`. It names its subject kind, its operations, and the observation fields its diagnosis must carry. Its **namespace owner** owns its meaning (Decision 12). **Never call it just "capability" in code or docs**: in Functualize, "capability" already means a DI-injectable such as `Log` or `Invoke` (`rg -c -i '\bcapabilit' src/functualize` sums to **592**). |
| **Subject** | A durable or externally meaningful thing that a package manages, such as one D1 database or one Worker script. |
| **Operation** | Something done *to* a subject (`provision`, `diagnose`). Every operation is an ordinary Functualize job. |
| **Relation** | A typed edge from one subject to another, marked `required` or `optional`. |
| **Diagnosis record** | One JSON object on one line: the universal envelope plus a typed `observation` payload. |

## 3. The boundary (the decision this feature exists to make — D-2)

**Rise judges; RiseKit authors; Functualize runs.** Package authors build on
RiseKit; nobody builds inside it. Dependencies point one way only:

```
functualize (public API)  ◄──  rise  ◄──  risekit  ◄──  provider packages
                                                       (functualize-rise-cloudflare, …)
```

Each layer may know the layer below it and never the one above. Each rule
below makes one part of that falsifiable:

- **B1 — Functualize knows nothing of Rise.** No module under `src/functualize/`
  imports any of the three packages. Every seam Rise needs already exists in
  core and is public (plan.md § *Seams*), so the foundation adds **no** core
  change.
- **B2 — Rise does not need RiseKit.** A package written by hand, importing
  nothing from RiseKit, validates and diagnoses exactly like one built with
  RiseKit. Rise never imports RiseKit. Without this property Rise is not a
  convention; it is RiseKit's internal format.
- **B3 — RiseKit invents no semantics.** Everything RiseKit emits (metadata,
  contract values, diagnosis records) is something Rise defines and validates.
  A RiseKit-built package that Rise rejects is a RiseKit defect.
- **B4 — Execution stays Functualize-native.** Rise runs an operation by calling
  `Invoke` with the operation's job name. It never calls provider code directly
  (Decision 15).
- **B5 — RiseKit carries no provider.** No provider package lives inside the
  RiseKit distribution, and RiseKit names no provider domain. A provider
  package depends on RiseKit; RiseKit never depends on a provider. This is the
  member's correction of 2026-10-02 made testable: "Risekit shouldn't contain
  packages for cloudflare etc, it should be used by other authors or package
  maintainers to create those cloudflare packages."
- **B6 — Rise adds no discovery.** Rise finds packages, jobs and contracts only
  through what Functualize already discovered: jobs and their metadata via the
  host's job lookup, and contracts by following the static reference that each
  job's own metadata carries. It registers no entry-point group of its own
  (Decision 14: "Rise introduces no parallel runtime loader").

### Which side each named piece enters from

| Piece | Enters from | Notes |
|---|---|---|
| Declaration schema (package id, contract identity + reference, subject, operation, relation + criticality) | **Rise** | |
| Capability-contract *format* (the `CapabilityContract` value type) | **Rise** | |
| How a contract is found: follow the job's static `contract_ref`, check its identity | **Rise** | B6; no registry, no entry-point group |
| `validate`: does a declaration conform to the contracts it claims? | **Rise** | RiseKit makes passing easy; it never decides pass or fail |
| `diagnose`: traversal, per-record status, required/optional aggregation, cycle/duplicate handling, NDJSON stream, exit status | **Rise** | |
| Diagnosis envelope (`rise`, `record`, `id`, `contract`, `status`, `observation`, `issues`, `requires`, `diagnosis_id`, `observed_at`) | **Rise** | |
| Typed observation models and the observation → record builder | **RiseKit** | provider code fills in only what it alone knows |
| `@operation` authoring decorator, contract-declaration helper | **RiseKit** | emit Rise's metadata and Rise's contract type; add nothing of their own |
| Common capability vocabulary (contracts several providers implement) | **RiseKit** | **none shipped in this feature**: no second provider needs one yet |
| Contract *instances* `cloudflare.d1@1`, `cloudflare.worker@1` | **Provider package** `functualize-rise-cloudflare`, as owner of the `cloudflare` namespace | Decision 12: the namespace owner owns the meaning |
| D1 `provision` / `diagnose` and Worker `diagnose` jobs | **Provider package** `functualize-rise-cloudflare` | authored with RiseKit |
| The D1 *runtime store* (persisting runs in D1) | **Functualize plugin**, the network-provider slice (FUN-22) | not Rise: Functualize must persist without Rise (Decision 13) |
| Running a Functualize operation *inside* a Worker | **Functualize adapter plugin**, cloud-execution slice | not Rise. Deploying it is a future operation of the provider package |
| Cloudflare credentials | **Functualize** config / secrets | the provider's jobs read them as ordinary job parameters |
| `rise-lock`, operation strategies, preference policy, origin/binding/authority, typed consumer proxy (`Requires[...]`) | Rise semantics, RiseKit authoring | **deferred**; plan.md § *Stage 5 consumption list* |
| No-import static analyzer, LSP | **Rise** | **deferred** |
| Registry, distribution, provenance, trust | **Functualize** (generic) | out of scope by Decision 13 |
| Jira and Confluence | **Neither**, at runtime | they authorize the *development* of all three packages (§8); no Rise, RiseKit or provider code reads them |

## 4. Behaviour

### 4.1 Declaring

- **S1.** A job takes part in Rise by carrying Rise metadata through the
  existing plugin-extension seam: `__functualize_ext_rise__`, merged by
  discovery into `JobDescriptor.metadata["plugins"]["rise"]`. The metadata names
  the package id, the contract identity (`<namespace>.<name>@<major>`), the
  contract reference (`<module>:<attribute>`, see C3), the subject id, the
  operation name, and the subject's relations.
- **S2.** A job without Rise metadata behaves exactly as it does today. A job
  with Rise metadata still behaves as an ordinary job when Rise is not
  installed: boot gives the existing orphan warning, the job is not refused, and
  it still runs.
- **S3.** The Rise plugin owns the `rise` namespace, so a booted app with Rise
  installed produces **no** orphaned-metadata warning for Rise metadata.
- **S4.** Rise reads package membership only through the host's job lookup
  (`PluginHost.get_jobs` / `get_job`). A job published under the
  `functualize.jobs` entry point enumerates **without** metadata until it is
  materialized (`app/commands.py:158-182`), so `rise-validate` and
  `rise-diagnose` materialize every entry-point job by name before reading its
  Rise metadata. That imports each job-publishing distribution once per command,
  never at boot. Directory-discovered jobs keep reading their metadata from the
  discovery cache, which preserves the warm-boot zero-import guarantee.

### 4.2 Validating

- **S5.** `func rise-validate --package <id>` checks every declaration of the
  package against the contract each one claims, and reports one line per
  finding. It mutates nothing and runs no operation.
- **S6.** Contract resolution: Rise imports the module named by `contract_ref`
  and reads the attribute. It must be a Rise `CapabilityContract` whose
  `identity` equals the declared `contract`. Only declaration modules are
  imported; no operation runs.
- **S7.** It refuses, with a named finding each:
  1. a contract reference that does not resolve;
  2. a reference that resolves to something other than a `CapabilityContract`,
     or to one whose identity differs from the declared contract;
  3. an operation the contract does not define;
  4. a required contract operation that has no implementing job;
  5. two jobs claiming the same (subject, operation);
  6. a relation that targets an undeclared subject;
  7. a relation without criticality;
  8. Rise metadata that is not JSON-serializable or fails the schema.
- **S8.** Exit status is 0 when there are no findings and non-zero otherwise.

### 4.3 Diagnosing

- **S9.** `func rise-diagnose --package <id> [--subject <id>]` writes one NDJSON
  record per diagnosed subject to stdout, then one root record for the package.
  Each record is complete on its own line. A failed observation is a record with
  `status: "fail"` and structured `issues`; it is never a traceback in the
  stream.
- **S10.** `status` is `pass` or `fail`, derived from the contract's assessment
  of the typed observation (Decision 5). It is never taken from a free-form
  provider judgement. `observation.state` is domain-specific and the contract
  defines it.
- **S11.** A subject fails if its own assessment fails **or** any `required`
  relation target fails. An `optional` target's failure is still emitted, but
  does not fail the parent. The parent carries a `required_dependency_failed`
  issue that references the child record by id; the child's detail is not
  copied (Decision 6).
- **S12.** Traversal continues past failures, so every subject that can be
  observed is emitted. A subject reached twice is observed once. A relation
  cycle is reported as an issue and does not recurse.
- **S13.** The process exit status follows the root record: 0 when it passes,
  non-zero when it fails. The exact non-zero taxonomy stays open.
- **S14.** Each diagnose operation runs through `Invoke` by job name, so it
  carries normal child-run ancestry, events and timeouts.

### 4.4 The forcing case — a Cloudflare provider package, authored with RiseKit

- **S15.** `functualize-rise-cloudflare` is a separate distribution. It depends
  on `functualize-risekit` (and through it `functualize-rise`) and on the
  Functualize public API, and on nothing else of this repository. It owns the
  `cloudflare` namespace and defines both of its contracts with RiseKit's
  declaration helper.
- **S16.** `cloudflare.d1@1`: subject *D1 database*, identified by
  (account id, database name). Operations: `diagnose` (observe presence, uuid
  and state) and `provision` (diagnose first; create only if absent; re-running
  against an existing database changes nothing and reports that). There is no
  `delete` in this feature: destructive operations need the positive-identity
  rule (Decision 11), which is deferred.
- **S17.** `cloudflare.worker@1`: subject *Worker script*, identified by
  (account id, script name). Operation: `diagnose`. It can declare a
  `binds → <d1 subject>` relation, `required` by default. `deploy` is **not** in
  this feature (§6).
- **S18.** Credentials arrive as ordinary job parameters resolved by Functualize
  config and secrets (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, the same
  names the D1 probe already uses). Nothing in Rise, RiseKit or the provider
  package reads the environment directly.
- **S19.** A repository-local Rise package (an example project) declares
  `worker.production` with relation `binds → d1.production` (`required`).
  Against a fake transport, `rise-diagnose` emits three records: d1, worker and
  root. When the database is absent, the worker and the root both fail, the d1
  record's issue says why, and the exit status is non-zero. After `provision`,
  the same diagnosis passes, provided the Worker exists.

## 5. Acceptance criteria

| # | Criterion | How it is shown | Authorized by (§8) |
|---|---|---|---|
| AC-1 | Rise and RiseKit have separate one-sentence responsibility statements and a defined boundary | §3 here, ADR-031, the `.spec/ARCHITECTURE.md` section | FUN-8 AC 1; Decision 1 |
| AC-2 | B1 holds: no core import of any of the three packages, and no core change | gate G1 (tasks.md), `git diff --stat origin/master -- src/functualize` empty | Decision 13 |
| AC-3 | B2 holds: a hand-written, RiseKit-free fixture package validates and diagnoses | T5's test; gate G3 | Decisions 1, 12 |
| AC-4 | B3 holds: every RiseKit-built package in the tree passes `rise-validate` | T7, T8 and T9 tests | Decisions 3, 4 |
| AC-5 | The smallest executable Rise path: validate plus recursive diagnose with aggregation, through `func` | T3 and T4 end-to-end tests | FUN-8 AC 2; Decisions 3, 5, 6 |
| AC-6 | The smallest usable RiseKit path: a provider package outside RiseKit, built with it, whose D1 contract is provisioned idempotently and diagnosed, offline against a fake transport and live when credentials exist | T8 offline tests plus a live tier that skips without credentials | FUN-8 AC 3; North Star step 6 |
| AC-7 | The Worker → D1 required relation fails the parent when D1 is absent and passes after provision | T10 example (pytest-collected) | Decision 6; North Star step 6 |
| AC-8 | The stage-5 consumption list is stated in one place, in order | plan.md § *Stage 5 consumption list* | FUN-8 AC 5; Initiative queue items 4–7 |
| AC-9 | Development traceability: every delivered package, public name and acceptance criterion traces to a §8 row naming its authorizing Confluence page/decision and Jira ticket; no runtime code reads Jira or Confluence | T11's traceability check; gate G10 | FUN-8 AC 4; Decision page 11370545 |
| AC-10 | B5 holds: RiseKit carries no provider, and the provider package is its own distribution depending on RiseKit | gate G8 | member correction 2026-10-02; Decision 12 |
| AC-11 | B6 holds: no new entry-point group; the repository's declared-group reader test stays green | gate G9 | Decision 14 |

## 6. Out of scope (owned elsewhere, in the order stage 5 consumes them)

Deploying a Functualize operation into a Worker. The D1 runtime store.
`rise-lock`. Operation strategies and preference policy. Origin, binding and
lifecycle authority, and `delete`. The typed consumer proxy. Namespace-ownership
proof. The first common-vocabulary contract. The no-import static analyzer.
Registry acquisition. The full ordered list, and what each item consumes from
this feature, is in plan.md § *Stage 5 consumption list*.

## 7. Premise changes and corrections

None of these reopens *whether* Rise and RiseKit are required.

- **Withdrawn — former P-1 ("Rise is not a delivery-intent pipeline").** The
  previous revision framed FUN-8's line about "Confluence/Jira intent …
  flow[ing] through the machinery" as a runtime question, and put it to the
  member. **The member corrected the framing** on 2026-10-02: "Jira or
  Confluence is NEVER required as part of Rise Runtime. The Fun-8 Scope was just
  to make sure the DEVELOPMENT of rise and risekit were aligned with what we
  have in confluence documentation and Jira tickets." It is therefore not a
  premise change at all. It is a development-traceability obligation, met by §8
  and checked by AC-9.
- **Withdrawn — former D-3 (naming that placed Cloudflare inside RiseKit).**
  The previous revision put the Cloudflare contracts and provider jobs in
  `functualize_risekit.cloudflare` and made RiseKit "namespace owner of
  `cloudflare`". **The member corrected this** on 2026-10-02 (quoted under B5).
  Canon agrees: Decision 1 says RiseKit provides "implementation machinery,
  authoring support, reusable building blocks, and reference packages that
  conform to it". This set reads "reference packages" as packages that conform,
  living outside the toolkit distribution. Decision 12 gives contract meaning to
  "an authorized namespace owner", which need not be RiseKit. The provider now
  lives in its own distribution (S15, C1).
- **P-2. "The Cloudflare Worker + D1 capability" is two contracts and two
  Functualize plugins, not one Rise thing.** The *namespace owner*, here the
  provider package, owns the provisioning, diagnosis and (later) deployment
  contracts. Rise judges them, and RiseKit is the toolkit they are written
  with. Run persistence in D1 and execution inside a Worker are generic
  Functualize plugins. The repository wins on this point: Decision 13 says
  Functualize must be usable without Rise; the constitution's completed
  invariant extracts delivery adapters to monorepo plugin packages; and FUN-22's
  own criterion keeps the D1 store a plugin ("The provider is a PLUGIN").
- **P-3. The forcing case is diagnosed and provisioned, not deployed.**
  Deploying a Functualize operation needs a Worker runtime adapter, and none
  exists. FUN-8's criterion that the Worker + D1 slice "has an explicit
  dependency on working Rise/RiseKit machinery" is met by stage-5 ordering, not
  by this feature.

## 8. Development traceability

What authorizes each piece of this feature. Every source below was read live on
2026-10-02 (research.md § *Live reads*). Confluence pages are in space `SD`;
Jira tickets are in project `FUN`. A delivered element with no row here is a
finding for T11.

| Element of this feature | Confluence authority (page id, version, decision) | Jira authority |
|---|---|---|
| Rise and RiseKit are required; build their machinery | 1.0 North Star 4882435 v6 (step 6, "Acquire cloud deployment as reusable operational knowledge"); Initiative 4882456 v11 (Scope; slice 6) | FUN-3 (delivery principle 3); FUN-8 (Outcome, Accepted premise) |
| Rise = convention + judge; RiseKit = authoring toolkit (§3, AC-1) | Shape Intent 5407068 v15, Decision 1 | FUN-8 Scope 1, AC 1 |
| Provider packages outside RiseKit (B5, S15, AC-10) | Shape Intent 5407068 v15, Decisions 1 and 12 | FUN-8 Scope 7 ("delivered **through** the accepted Rise/RiseKit model"); member correction on MCH-88, 2026-10-02 |
| Functualize knows nothing of Rise (B1, AC-2) | Shape Intent 5407068 v15, Decision 13 | FUN-3 delivery principle 3 |
| No parallel discovery; metadata over native discovery (B6, S1, S4, AC-11) | Shape Intent 5407068 v15, Decision 14 | — |
| Execution through `Invoke` (B4, S14) | Shape Intent 5407068 v15, Decision 15 | — |
| `validate` / `diagnose` as universal contracts (S5–S14) | Shape Intent 5407068 v15, Decisions 3 and 4 | FUN-8 AC 2 |
| Binary derived `status`, domain `state` (S10, C4) | Shape Intent 5407068 v15, Decision 5 | — |
| Required / optional aggregation (S11) | Shape Intent 5407068 v15, Decision 6 | — |
| Namespaced, owner-held contracts (C3, C4) | Shape Intent 5407068 v15, Decision 12 | — |
| No `delete`, no destructive operation (S16) | Shape Intent 5407068 v15, Decision 11 (deferred) | — |
| D1, not "R1" | Review decision D7, page 9273345 v1 | FUN-8 footnote; FUN-22 |
| D1 run persistence is a Functualize plugin, not Rise (P-2) | Runtime Persistence — Engine-Owned Design 6389761 | FUN-22 AC 2; FUN-16 |
| Hold generalisations no second package needs (C4's minimal rule; no common vocabulary yet) | Review decision D4, page 9273345 v1 | — |
| Stage-5 consumption order (plan.md) | Initiative 4882456 v11, continuation queue items 4–7 and ticket-creation policy | FUN-3 (Continuation planning) |
| Forward compatibility: identities stay stable enough to attach evidence later (package id, contract identity, `diagnosis_id`) | 2.0 North Star 4849705 v5 (**Proposed**), *Proof-carrying Rise packages* — a constraint, not a commitment | none: 2.0 has no Jira commitment by its own planning consequence |
| Where artifacts live: Jira holds claims, Confluence holds decisions (AC-9) | Decision 11370545 v4 (accepted 2026-10-01) | FUN-8 AC 4 |
| Run 1 stays Rise-independent | Run 1 page 5046398 v1 (no Rise content) | FUN-5 |
