# Rise / RiseKit foundation — specification

Status: **Specify — awaiting member confirmation** (decisions D-1…D-3 in
`plan.md` § *Decisions for the member*). Nothing in this set authorizes Execute
until those are answered.

Base: `origin/master` at `ef1939d`. Every count below was produced by the
command printed beside it, on that base.

## 1. Problem

Rise and RiseKit are accepted prerequisites of the 1.0 journey. The later
packaging slice, the cloud path and the release proof must go through them
rather than around them. Today nothing in the repository carries either
name:

```
git grep -i -c risekit origin/master | wc -l      # 0
git grep -E -l '\bRise\b' origin/master | wc -l   # 0
```

The concepts exist only in the product design space: a canonical shape intent
with fifteen accepted decisions on the model. The repository has no account of
where the line between Rise and RiseKit runs, which side owns each piece, or how
either one relates to the Functualize layers the constitution fixes. Without that
line, the first Cloudflare package would set the boundary by accident, wherever
its code happened to land.

This feature does two things. It **draws the line** and records it as a
decision. Then it **builds the smallest machinery on each side** that makes the
line testable, using the Cloudflare D1 and Worker capabilities as the forcing
case.

## 2. Vocabulary (defined here, because the repository has none)

| Term | Meaning in this feature |
|---|---|
| **Functualize** | The runtime: jobs, plugins, discovery, `Invoke`, config, secrets, stores. It knows nothing about Rise. |
| **Rise** | The convention, plus the **judge** that checks a package against it. It owns the declaration schema, the diagnosis record envelope, the conformance rules, and the `validate` and `diagnose` operations. |
| **RiseKit** | The **author's side**. It holds the typed authoring helpers that make a conformant declaration the easy one to write, the standard library of capability contracts in the namespaces RiseKit owns, and the reference provider packages. |
| **Rise Package** | A logical compatibility boundary: a set of Functualize-discovered jobs that share one package id. It is *not* necessarily a Python distribution (shape intent, Decision 14). |
| **Rise capability contract** | A namespaced, versioned promise such as `cloudflare.d1@1`. It names its subject kind, its operations, and the observation fields its diagnosis must carry. **Never call it just "capability" in code or docs**: in Functualize, "capability" already means a DI-injectable such as `Log` or `Invoke` (`rg -c -i '\bcapabilit' src/functualize` sums to **592**). |
| **Subject** | A durable or externally meaningful thing that a package manages, such as one D1 database or one Worker script. |
| **Operation** | Something done *to* a subject (`provision`, `diagnose`). Every operation is an ordinary Functualize job. |
| **Relation** | A typed edge from one subject to another, marked `required` or `optional`. |
| **Diagnosis record** | One JSON object on one line: the universal envelope plus a typed `observation` payload. |

## 3. The boundary (the decision this feature exists to make)

**Rise judges; RiseKit authors; Functualize runs.** Dependencies point one
way only:

```
functualize (public API)  ◄──  rise  ◄──  risekit  ◄──  risekit.cloudflare
```

Each side has one rule that makes it falsifiable:

- **B1 — Functualize knows nothing of Rise.** No module under `src/functualize/`
  imports either package. Every Rise seam this feature needs already exists in
  core (plan.md § *Seams*). So the foundation adds **no** core change.
- **B2 — Rise does not need RiseKit.** A package written by hand, importing
  nothing from RiseKit, validates and diagnoses exactly like one built with
  RiseKit. Rise never imports RiseKit. Without this property Rise is not a
  convention; it is RiseKit's internal format.
- **B3 — RiseKit invents no semantics.** Everything RiseKit emits (metadata,
  contract artifacts, diagnosis records) is something Rise defines and
  validates. A RiseKit-built package that Rise rejects is a RiseKit defect.
- **B4 — Execution stays Functualize-native.** Rise runs an operation by calling
  `Invoke` with the operation's job name. It never calls provider code directly
  (shape intent, Decision 15).

### Which side each named piece enters from

| Piece | Enters from | Notes |
|---|---|---|
| Declaration schema (package id, contract ref, subject, operation, relation + criticality) | **Rise** | |
| Capability-contract *format* (machine-readable) | **Rise** | |
| `validate`: does a declaration conform to the contracts it claims? | **Rise** | RiseKit makes passing easy; it never decides pass or fail |
| `diagnose`: traversal, per-record status, required/optional aggregation, cycle/duplicate handling, NDJSON stream, exit status | **Rise** | |
| Diagnosis envelope (`rise`, `record`, `id`, `contract`, `status`, `observation`, `issues`, `requires`, `diagnosis_id`, `observed_at`) | **Rise** | |
| Typed observation models and the observation → record builder | **RiseKit** | provider code fills in only what it alone knows |
| `@operation` authoring decorator, contract-declaration helpers | **RiseKit** | emits the Rise metadata; adds none of its own |
| Contract *instances* `cloudflare.d1@1`, `cloudflare.worker@1` | **RiseKit** | RiseKit owns the `cloudflare` namespace for now |
| D1 `provision` / `diagnose` and Worker `diagnose` provider jobs | **RiseKit** reference package `cloudflare` | |
| The D1 *runtime store* (persisting runs in D1) | **Functualize plugin**, network-provider slice | not Rise: Functualize must persist without Rise (Decision 13) |
| Running a Functualize operation *inside* a Worker | **Functualize adapter plugin**, cloud-execution slice | not Rise. Rise/RiseKit own *deploying* it, not *being* it |
| Cloudflare credentials | **Functualize** config / secrets | Rise reads them through ordinary job parameters |
| `rise-lock`, operation strategies, preference policy, origin/binding/authority | Rise semantics, RiseKit authoring | **deferred**; plan.md § *Stage 5 consumption list* |
| No-import static analyzer, LSP | **Rise** | **deferred** |
| Registry, distribution, provenance, trust | **Functualize** (generic) | out of scope by Decision 13 |
| Jira / Confluence / repository-spec intent flow | **Neither**: process authority, not runtime machinery | premise change P-1 |

## 4. Behaviour

### 4.1 Declaring

- **S1.** A job takes part in Rise by carrying Rise metadata through the
  existing plugin-extension seam: `__functualize_ext_rise__`, merged by
  discovery into `JobDescriptor.metadata["plugins"]["rise"]`. The metadata names
  the package id, the contract (`<namespace>.<name>@<major>`), the subject id,
  the operation name, and the subject's relations.
- **S2.** A job without Rise metadata behaves exactly as it does today. A job
  with Rise metadata still behaves as an ordinary job when Rise is not
  installed: boot gives the existing orphan warning, the job is not refused, and
  it still runs.
- **S3.** The Rise plugin owns the `rise` namespace, so a booted app with Rise
  installed produces **no** orphaned-metadata warning for Rise metadata.

### 4.2 Validating

- **S4.** `func rise-validate --package <id>` checks every declaration of the
  package against the contract each one claims, and reports one line per
  finding. It mutates nothing and runs no operation.
- **S5.** It refuses, with a named finding each:
  1. an unknown contract;
  2. a contract version the package does not declare;
  3. an operation the contract does not define;
  4. a required contract operation that has no implementing job;
  5. two jobs claiming the same (subject, operation);
  6. a relation that targets an undeclared subject;
  7. a relation without criticality;
  8. Rise metadata that is not JSON-serializable or fails the schema.
- **S6.** Exit status is 0 when there are no findings and non-zero otherwise.

### 4.3 Diagnosing

- **S7.** `func rise-diagnose --package <id> [--subject <id>]` writes one NDJSON
  record per diagnosed subject to stdout, then one root record for the package.
  Each record is complete on its own line. A failed observation is a record with
  `status: "fail"` and structured `issues`; it is never a traceback in the
  stream.
- **S8.** `status` is `pass` or `fail`, derived from the contract's assessment
  of the typed observation. It is never taken from a free-form provider
  judgement. `observation.state` is domain-specific and the contract defines it.
- **S9.** A subject fails if its own assessment fails **or** any `required`
  relation target fails. An `optional` target's failure is still emitted, but
  does not fail the parent. The parent carries a `required_dependency_failed`
  issue that references the child record by id; the child's detail is not
  copied.
- **S10.** Traversal continues past failures, so every subject that can be
  observed is emitted. A subject reached twice is observed once. A relation
  cycle is reported as an issue and does not recurse.
- **S11.** The process exit status follows the root record: 0 when it passes,
  non-zero when it fails. The exact non-zero taxonomy stays open.
- **S12.** Each diagnose operation runs through `Invoke` by job name, so it
  carries normal child-run ancestry, events and timeouts.

### 4.4 The forcing case — Cloudflare D1 and Worker

- **S13.** `cloudflare.d1@1`: subject *D1 database*, identified by
  (account id, database name). Operations: `diagnose` (observe presence, uuid
  and state) and `provision` (diagnose first; create only if absent; re-running
  against an existing database changes nothing and reports that). No `delete`
  in this feature. Destructive operations need the positive-identity rule
  (shape intent, Decision 11), which is deferred.
- **S14.** `cloudflare.worker@1`: subject *Worker script*, identified by
  (account id, script name). Operation: `diagnose`. It can declare a
  `binds → <d1 subject>` relation, `required` by default. `deploy` is **not** in
  this feature (§6).
- **S15.** Credentials arrive as ordinary job parameters resolved by Functualize
  config and secrets (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, the same
  names the D1 probe already uses). Nothing in Rise or RiseKit reads the
  environment directly.
- **S16.** A repository-local Rise package (an example project) declares
  `worker.production` with relation `binds → d1.production` (`required`).
  Against a fake transport, `rise-diagnose` emits three records: d1, worker and
  root. When the database is absent, the worker and the root both fail, the d1
  record's issue says why, and the exit status is non-zero. After `provision`,
  the same diagnosis passes, provided the Worker exists.

## 5. Acceptance criteria

| # | Criterion | How it is shown |
|---|---|---|
| AC-1 | Rise and RiseKit have separate one-sentence responsibility statements and a defined boundary | §3 here, ADR-031, the `.spec/ARCHITECTURE.md` section |
| AC-2 | B1 holds: no core import of either package, and no core change | gate G1 (tasks.md), `git diff --stat origin/master -- src/functualize` empty |
| AC-3 | B2 holds: a hand-written, RiseKit-free fixture package validates and diagnoses | T5's test; gate G3 |
| AC-4 | B3 holds: every RiseKit-built package in the tree passes `rise-validate` | T7, T8 and T9 tests |
| AC-5 | The smallest executable Rise path: validate plus recursive diagnose with aggregation, through `func` | T3 and T4 end-to-end tests |
| AC-6 | The smallest usable RiseKit path: the D1 contract and provider, provisioned idempotently and diagnosed, offline against a fake transport and live when credentials exist | T8 offline tests plus a live tier that skips without credentials |
| AC-7 | The Worker → D1 required relation fails the parent when D1 is absent and passes after provision | T10 example (pytest-collected) |
| AC-8 | The stage-5 consumption list is stated in one place, in order | plan.md § *Stage 5 consumption list* |
| AC-9 | Jira stays the delivery state, Confluence the decision context, and repository code and specs the contracts. No Rise artifact duplicates any of them | P-1; review of T11 |

## 6. Out of scope (owned elsewhere, in the order stage 5 consumes them)

Deploying a Functualize operation into a Worker. The D1 runtime store.
`rise-lock`. Operation strategies and preference policy. Origin, binding and
lifecycle authority, and `delete`. The no-import static analyzer. Registry
acquisition. The full ordered list, and what each item consumes from this
feature, is in plan.md § *Stage 5 consumption list*.

## 7. Premise changes against the tracker's accepted premise

These are recorded here and in `research.md`, and raised on the tracker
thread. None of them reopens *whether* Rise and RiseKit are required.

- **P-1. Rise is not a delivery-intent pipeline.** The tracker's scope asks how
  "Confluence/Jira intent, repository specifications, implementation,
  verification, and packaged capabilities flow through the machinery". The
  continuation queue describes the Rise slices as taking "accepted
  intent/specification into a usable, verifiable capability workflow". The
  canonical shape intent (fifteen decisions) defines Rise as an
  operational-package convention and says nothing of delivery intent. This
  feature therefore builds **no** runtime path that reads Jira or Confluence.
  The source-of-truth acceptance criterion (AC-9) is met by *where* each
  artifact lives, not by machinery. **Needs member confirmation (D-1).**
- **P-2. "The Cloudflare Worker + D1 capability" is two contracts and two
  Functualize plugins, not one Rise thing.** Rise and RiseKit own the
  provisioning, diagnosis and (later) deployment contracts. Run persistence in
  D1 and execution inside a Worker are generic Functualize plugins. The
  repository wins here: the shape intent's Decision 13 says Functualize must be
  usable without Rise, the constitution's completed invariant extracts delivery
  adapters to monorepo plugin packages (core ships only `CliAdapter` and
  `TuiAdapter`), and the network provider slice's own criterion keeps the D1
  store provider a plugin.
- **P-3. The forcing case is diagnosed and provisioned, not deployed.**
  Deploying a Functualize operation needs a Worker runtime adapter, and none
  exists. The tracker's criterion that the Worker + D1 slice "has an explicit
  dependency on working Rise/RiseKit machinery" is met by stage-5 ordering, not
  by this feature.
