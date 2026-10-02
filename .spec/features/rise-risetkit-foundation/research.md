# Rise / RiseKit foundation — research record

Findings and verification evidence for the set. This file is never a gate. It
records what was checked, when, and with what result. Base for every
repository command: `origin/master` at `ef1939d`, branch head `a86f2c1`
(revision 1) plus the revision-2 working changes, all in the worktree.

## Provenance

- **Revision 1** (`a86f2c1`). `spec.md` and `contracts.md` were written by a
  design run that read Jira and Confluence live and then died before
  committing. A second run judged both files, corrected two defects, and wrote
  `plan.md`, `tasks.md` and this record. That second run had no Atlassian
  access, and said so.
- **Revision 2** (this one, 2026-10-02). It applies the member's two corrections
  and the planning audit of 2026-10-02 on the tracker thread. It re-reads every
  product source live (§ *Live reads*), which retires revision 1's "not read
  live" limitation. It also re-verifies the new seams the revision relies on.
- **Revision 3** (2026-10-02, after the member answered D-2). It reads the
  owner's nine inline comments on page 5407068 live and corrects revision 2's
  "0 comments" record. It researches the three comments the owner deferred
  (§ *Owner comments*) and tracks the other six. Every cited source was
  re-checked live.

## Live reads (through the Atlassian connector on the design runtime)

Revision 2 read every source below at about 03:00Z on 2026-10-02. **Revision 3
re-read all of them between 06:06Z and 06:10Z the same day**, and every version
and updated-timestamp matched. One revision-2 fact is now false, as corrected
below. The re-read also covered FUN-5 (To Do, updated 2026-09-19T00:34:37Z) and
FUN-16 (To Do, updated 2026-09-21T09:35:02Z), and confirmed page 6389761 at v1.

| Source | Id | Version / state | What it contributed |
|---|---|---|---|
| Shape Intent — Rise/RiseKit Canonical Model | Confluence `SD` 5407068 | **v15**, updated 2026-09-28T10:29:34Z. The body is byte-identical between the 03:00Z and 06:06Z reads. **9 inline comments, all by the owner, created 03:28:45Z–04:16:22Z** (`confluence_get_inline_comments`, count 9). `confluence_get_comments` returns the same nine and no footer comment. *Revision 2 recorded "0 inline, 0 footer". That was true at its read and is false now.* | Decisions 1, 3–6, 11–15 as cited in spec.md §8; the nine comments as dispositioned in spec.md §9 |
| Functualize 1.0.0 North Star | `SD` 4882435 | v6, 2026-09-28T10:23:53Z | step 6 (acquire the Cloudflare package through Rise/RiseKit); planning consequence ("Rise/RiseKit package interface" is not a contract until accepted) |
| Initiative — 1.0.0 North Star Journey | `SD` 4882456 | v11, 2026-09-28T10:28:32Z | scope; slice 6; continuation queue items 4–7; ticket-creation policy ("When FUN-8 resolves the Rise/RiseKit boundary, update this queue first") |
| Functualize 2.0.0 North Star | `SD` 4849705 | v5, **Proposed**, 2026-09-20T11:06:03Z | *Proof-carrying Rise packages*: a forward-compatibility constraint only ("should not yet create a 2.0 Jira commitment") |
| Northstar 1.0 Journey — Run 1 | `SD` 5046398 | v1, 2026-09-18 | no Rise content; Run 1 is deliberately Rise-independent (FUN-5) |
| Decision — Claims live in Jira, decisions and sources live in Confluence | `SD` 11370545 | v4, accepted 2026-10-01 | where artifacts live (AC-9); the two preflight queries an agent runs before planning |
| 01 — Decisions Taken (D1–D7) | `SD` 9273345 | v1 | D4 (hold generalisations no second package needs); D7 (R1 means D1) |
| FUN-8 | Jira | In Progress, updated 2026-10-01T17:41Z, no comments | scope and acceptance criteria as cited |
| FUN-3 | Jira | To Do, updated 2026-09-19 | delivery principles; initial delivery order item 7 (FUN-8 in parallel) |
| FUN-22 | Jira (read 2026-10-01) | To Do | "D1 FIRST"; "The provider is a PLUGIN" |

Preflight per Decision 11370545 §4, run 2026-10-02:

- Open items: `project in (FOSS, FCLOUD) AND (labels in (area-rise, area-risekit, area-plugins, area-packaging) OR text ~ "rise" OR text ~ "risekit") AND statusCategory != Done`
  returned FOSS-80 (dead symbols in `functualize-ai`/`functualize-mcp`) and
  FOSS-75 (`ToolScope.approval_required()`). Neither touches this feature's
  files. No Rise or RiseKit item exists.
- Decision records: `type = page AND label = "decision"` returned one page
  (11370545). No area-labelled Rise decision exists. The Rise decisions are the
  Shape Intent's own.

## Verification (Retrieval Before Assertion evidence)

| Claim in the set | Command or read | Result |
|---|---|---|
| no `risekit` anywhere on master | `git grep -i -c risekit origin/master \| wc -l` | 0 |
| no `\bRise\b` anywhere on master | `git grep -E -l '\bRise\b' origin/master \| wc -l` | 0 |
| "capability" already means a DI-injectable (592 uses) | `rg -c -i '\bcapabilit' src/functualize`, summed | 592 |
| the ext seam exists | read `src/functualize/_discovery/providers.py:296-312` | as claimed |
| namespace ownership and orphan warning | read `src/functualize/_app/boot.py:2104-2148` | warning by default; raise under `plugins.strict` |
| the public host port has job lookup and DI | read `src/functualize/_types/host.py:106-122, 296-308` | `get_jobs`, `get_job`, `execute`, `di.provide` (revision 2) |
| entry-point jobs enumerate without metadata | read `src/functualize/_discovery/providers.py:700-740`, `src/functualize/app/commands.py:158-182` | as claimed; `get_job` materializes (revision 2, S4) |
| `Invoke` by name returns the callee's value | read `src/functualize/_engine/capabilities/invoke.py:96-125` | `-> JobResult` with `return_value` |
| an unread entry-point group fails the repository's tests | read `tests/spec/test_every_declared_group_has_a_reader.py`; ran it | refuses any `functualize.*` group not in `READ_GROUPS` and not a live domain's group; **30 passed** on this branch, 2026-10-02 (revision 2, gate G9) |
| the `functualize.plugins` → `ADAPTER` label is accepted | read `.spec/STATUS.md:2930-2933` | "Maintainer decision, 2026-09-17" |
| Jev registers the same way, from `plugins/domains/` | read `plugins/domains/functualize-decision-jev/pyproject.toml:23-24` | `jev = "functualize_decision_jev:JevPlugin"` |
| 9 plugin files already import `functualize._*` against the plugin guide | `rg -l 'from functualize\._\|import functualize\._' plugins/*/*/src \| wc -l` (2026-10-01) | 9; gate G11 forbids a tenth |
| zero plugins use the ext seam today | `rg -l '__functualize_ext_' plugins \| wc -l` (2026-10-01) | 0; Rise is its first consumer |
| core mentions Cloudflare only in prose | `rg -n -i cloudflare src/functualize` (2026-10-01) | 4 docstring hits in `_types/persistence.py`; **FUN-22's gate "`grep -rn 'cloudflare' src/functualize/` stays at 0" is already false**, so this set's gates are import-level |
| credential names already in use | `tests/substrate_probe/d1.py` | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| grouped plugin layout | `ls plugins/` | `adapters credentials domains substrates` |
| ADR-031 is the next free number | `ls contributor/adr/` | highest is 030; the dispatch's "016" was stale |
| G1 still empty | `git show --stat HEAD` (5 files under `.spec/features/`) plus `git status --porcelain` (4 of those files modified) | nothing under `src/functualize/` |

Prose pass (revision 1): `zg` over the worktree index. Its hits on ADR-016
(providers in plugins, `boto3` kept out of core) and ADR-026 ("One
implementation does not earn an abstraction package") are weighed in plan.md
§ *Candidate-AFTER smell check*.

## Corrections

Revision 1, to the inherited draft:

1. spec.md §7 P-2 cited ADR-016 as "puts providers in plugins". ADR-016 is the
   remote config layer. The citation was replaced with the constitution's
   completed invariant and FUN-22's own criterion.
2. contracts.md C4 pointed at an undefined "D4 review check". It was pointed at
   D-2 instead. (Revision 2 cites the actual source: review decision D4,
   page 9273345.)

Revision 2, from the member and the audit (2026-10-02):

3. **P-1 withdrawn.** It is now development traceability (spec.md §7, §8), as
   the member corrected.
4. **Providers moved out of RiseKit.** This affects C1, C2, spec.md §2–3, B5,
   S15, T8 and T9, as the member corrected.
5. **P-2 reworded.** The *namespace owner* owns the Cloudflare contracts. Rise
   and RiseKit do not.
6. **Contract discovery replaced.** `functualize.rise_contracts` was excluded
   by Decision 14 and refused by the declared-group reader test. It is replaced
   by `contract_ref` (B6, C3, C4). Revision 1 would have failed CI at T8.
7. **S4 added.** Entry-point jobs carry no metadata until materialized, so
   revision 1's Rise would have read every provider job's Rise metadata as `{}`.
8. **T11 extended** past artifact non-duplication, to implementation
   traceability against live sources (AC-9, G10).

## Premise changes against the tracker

- **P-2**: "the Cloudflare Worker + D1 capability" is two provider-owned
  contracts plus generic Functualize plugins for run persistence and Worker
  execution.
- **P-3**: the forcing case is diagnosed and provisioned, not deployed. FUN-8's
  dependency criterion is met by stage-5 ordering.
- P-1 is withdrawn (correction 3). It was never a premise change.

The three plan pages 4882456, 4882435 and 4849705 each returned
`confluence_get_inline_comments` count 0 on the revision-3 read.

## Owner comments — research (revision 3)

The owner asked for research before deciding three things. Each answer below
ends in a recommendation that is **provisional**: it is the design lane's
proposal, not accepted design. The owner's ask is quoted from the live read.

### R-1 — cycle and deduplication mechanics for `rise-diagnose` (comment 11960322)

> "Research / look into lightweight python graph packages, or existing graph
> implementations already available (maybe not yet public API) in functualize
> codebase. We should elaborate on this before making a decision."

**What the traversal must do** (spec.md S10–S12):

- observe every reachable subject once, including a subject reached by two
  paths (a *diamond*);
- observe targets before the subjects that relate to them (post-order);
- report a *cycle* as an issue and keep going;
- emit records in a deterministic order.

**A finding against revision 1.** T4 said "post-order traversal with a visited
set". A bare visited set cannot tell a diamond from a cycle: both are "a node
seen before". The repository already records this trap at
`src/functualize/workflow/_validation.py:167-170`: "Three states rather than a
visited set: a node reached twice by different branches is a diamond, which is
legal, and only a node reached *while still on the path* is a cycle."

**What exists inside Functualize** (searched over `src/` and `plugins/`; none of
it is public API):

| Where | What | Usable by Rise? |
|---|---|---|
| `src/functualize/_primitives/graph.py:68-114` `topological_order` | `graphlib.TopologicalSorter` plus an alphabetical global frontier; raises `GraphCycleError` with the cycle path (`find_cycle`, `:150-175`) | No. It is a `functualize._*` import, which G11 forbids |
| `src/functualize/_primitives/graph.py:178-200` `descendants` | downstream-reachability walk | No, same reason |
| `src/functualize/workflow/_validation.py:149-196` `_find_cycle` | iterative three-state DFS (unvisited / on path / finished), with no recursion limit | No. It is private (underscore name) in a public package |
| `src/functualize/_engine/job_graph.py:41-49` | records why networkx was rejected: "measured at 499 ms — a hundred times this project's entire `<5ms` cold-start budget" | the rejection is prior art Rise should honour |

Public folders (`app/`, `job/`, `plugin/`, `types/`, `workflow/`, `testing/`)
export no graph helper: the search returned only unrelated `descendants`
prose.

**Measured on this host (2026-10-02):** `python -X importtime -c "import
graphlib"` gives **388 µs**. None of networkx, rustworkx, igraph or toposort is
installed in the workspace environment (`importlib.util.find_spec`). A probe of
`graphlib` (run from the design workdir, not committed) showed three things:

- a diamond `{root:[w1,w2], w1:[d1], w2:[d1], d1:[]}` orders as
  `[d1, w1, w2, root]`, so `d1` is observed once;
- a cycle raises `CycleError` carrying the path `['a', 'c', 'b', 'a']`;
- `prepare()` refuses the **whole** graph on a cycle, so continuing past one
  means cutting the edge and re-sorting. Ties come out in insertion order (`y`
  before `b`), not alphabetically.

| Option | Consequence |
|---|---|
| **A. Iterative three-state DFS in `functualize-rise`**, the pattern of `workflow/_validation.py:167-196`, with successors sorted | S10–S12 in one pass. A finished node is reused (the diamond is deduplicated), an on-path node is a `relation_cycle` issue and the walk continues, post-order falls out of the "finished" transition, and order is deterministic. No dependency, ~50 lines. Cost: it re-implements a pattern core has privately (duplicated code across a package boundary). |
| B. stdlib `graphlib` in `functualize-rise` | Ordering and deduplication come free, and it is the engine core itself uses. But S12's "keep going past a cycle" needs a loop of cut-the-edge-and-retry, once per cycle, and a hand-written alphabetical frontier (core's `graph.py:98-114`). More moving parts than A for the same result. |
| C. Import core's helpers | Breaks G11 (the plugin guide's "never import from `functualize._*`"). Rejected. |
| D. Publish core's graph helpers as public API | One implementation. But it is a core change, which breaks B1/AC-2, and every public name owes an ADR-level review and an `examples/` caller (AGENTS.md). Worth doing later if a second outside package needs it, and not before. |
| E. networkx / rustworkx / igraph | 499 ms for networkx by core's own measurement. Compiled wheels for the other two. All for graphs of tens of nodes. Rejected. |
| F. `toposort` (PyPI) | Duplicates stdlib `graphlib` on this repository's Python ≥3.11 floor. Rejected. |

**Provisional recommendation: A.** It is the only option that meets all four
requirements in a single pass with no dependency, and it is the repository's own
documented answer to the exact diamond-versus-cycle trap. B is the fallback if
the owner prefers stdlib over a local pattern. T4 records whichever the owner
accepts. Until then, T4's text names the behaviours, not the algorithm.

### R-2 — an operation-effect vocabulary and opt-in plan/dry-run (comments 11927557, 11927574)

> "… should we encourage / support dry-run type semantics (perhaps opt-in) to
> operations. Perhaps it should be easy to create operations that are diffable
> / dry-run with regards to what they will change and get reflected back in
> diagnosis." — 11927557
>
> "However should we provide markers for "destructive", or "mutating" /
> "side-effect" operations? Mutating and side-effect markers could perhaps be
> used for the dry-run / terraform-like idea in the previous comment. But as
> said before, we'll need to elaborate and discuss this first." — 11927574

**Candidate vocabulary.** Each `OperationContract` carries a set of effects; the
empty set means *read-only*.

| Effect | Meaning | Example |
|---|---|---|
| *(none)* | observes only; changes nothing anywhere | `diagnose` |
| `mutates` | changes the managed subject, within the strategy's declared scope (Decision 11's "mutation surface") | `provision` creating a D1 database |
| `destroys` | may remove the subject or lose its data irreversibly; implies `mutates` | a future `delete` |
| `external` | acts on something outside the subject graph that cannot be observed back (a message sent, a charge made) | a future "notify on deploy" |

**Opt-in plan, separate from the vocabulary.** An operation may declare
`plannable`. Invoked in plan mode, it performs no effect and returns a typed
plan: one entry per subject, each with an action (`create` / `update` /
`delete` / `none`) and field changes. Rise can emit that plan as its own record
kind next to the diagnosis stream, which is the owner's "reflected back in
diagnosis".

```json
{"rise":"1","record":"plan","id":"d1.production","contract":"cloudflare.d1@1",
 "operation":"provision","action":"create","changes":{"name":[null,"prod-db"]}}
```

Against an existing database, the same plan says `"action":"none"`. Idempotence
becomes visible *before* acting, not only after.

**What Rise could enforce, cheaply, if the vocabulary is adopted:**

1. a `diagnose` operation must declare no effects (a validate finding);
2. any operation with an effect requires a `diagnose` on the same subject,
   which is the convergence shape of Decision 3;
3. `destroys` is refused at validate time until the positive-identity rule of
   Decision 11 lands. The word is reserved, not usable.

**Limits, stated plainly:**

- **Effects are claims, not proofs.** Rise cannot detect a "read-only"
  operation that writes. Only running it in isolation (R-3) or the provider's
  own tests can.
- **A plan is a prediction.** The world can change between plan and act, which
  is Terraform's stale-plan problem. The mitigation is to re-diagnose after
  acting, which Rise already does.
- **`external` effects can only be described, not diffed.** "Will send 1
  message" is a plan line; there is no state to diff.

**Migration cost: the asymmetry that decides the timing.**

| Change made later | Cost |
|---|---|
| `mutating: bool` → an effects set | A contract-format change in `functualize-rise`, the RiseKit helper, and **every contract owner**, plus a schema generation bump (`"rise":"1"` → `"2"`). This is SM-2's shotgun surgery. Today there is one owner, in-tree, and the cost is minimal. It grows with every published provider, and outside providers are the point of Decision 12. |
| adding `plannable` and the plan record | **Additive:** an optional field and a new record kind. Old contracts and old consumers keep working. |

| Option | Consequence |
|---|---|
| a. Keep `mutating: bool` | No work now. The vocabulary question returns as a breaking change once outside providers exist. |
| **b. Effects set now; plan deferred** | Settles the shape that is expensive to change while it is still cheap; enforces rules 1 and 3; reserves `plannable` as a later additive slice. |
| c. Effects and plan now | Delivers the owner's dry-run idea at once, but designs the plan format against one provider with one mutating operation (review decision D4: hold generalisations no second package needs). |

**Provisional recommendation: b.** It is put to the member as **OS-1**
(plan.md § *Next member decision*), because it decides what every provider
author must declare. Nothing here commits Rise to Terraform-style planning.

### R-3 — a safe, isolated test harness for package authors (comment 11960331)

> "Risekit should have a feature that makes it easy for package creators /
> maintainers to test their implementation safely in an isolated environment.
> Perhaps like a docker or podman harness that can test the dev.mise@1 project
> vs user isolation without actually running it on the host computer."

**Does T7/T8's fake transport exercise that experience? Partly, and only for
one kind of provider.**

- **For a remote-API provider (Cloudflare), yes.** A fake transport scripts the
  provider's HTTP exchanges. It exercises everything the author wrote: request
  building, the provision-only-if-absent branch, observation mapping, and error
  records. It is the same instrument the repository's D1 probe uses
  (`tests/substrate_probe/d1.py`, a local stub). Nothing on the developer's
  machine is touched.
- **For a host-mutating provider (the owner's `dev.mise@1` example), no.** What
  needs proving there is isolation scope: project, user or host (Decisions 7–8).
  That can only be shown by letting the operation really run against a
  filesystem and user account that are not the developer's. A fake transport
  has nothing to fake: the "API" is the filesystem.

**Prior art in this repository**, none of which an outside author can use as-is:

- Tests that spawn `func` must set `HOME` and all three `XDG_*` roots (AGENTS.md,
  *Writing tests*). That is a process-level sandbox, and it is not shipped.
- The doc-verify runner has a `docker` engine and TOML scenarios
  (`.agents/skills/doc-verify/scripts/run-scenario`). A podman reproduction is
  recorded at `.spec/STATUS.md:450`. But `.agents/skills/` is contributor-only and
  never ships (AGENTS.md, *Two skill directories*). The docker tier runs only at
  the manual release gate (`.github/workflows/ci.yml:355-363`).

**Harness tiers a RiseKit author would need:**

| Tier | Isolation | Provides | Needed first by |
|---|---|---|---|
| a. fake transport, in-process | the provider's network calls | this feature (T8/T9) | `functualize-rise-cloudflare` |
| b. sandboxed `HOME` / `XDG_*` subprocess | user-scope state | a shipped `functualize_risekit.testing` fixture | the first user-scope provider |
| c. container (docker/podman) | host scope: package managers, system paths | a shipped harness that drives a container runtime | `dev.mise@1`-style host-vs-project providers |

**Provisional recommendation.** T7/T8 keep the fake transport, which is the
right instrument for the forcing case. The author harness (tiers b and c) is a
**separate RiseKit slice**, added to the stage-5 list and sequenced before the
first host-mutating provider. Tier c needs a container runtime on the
developer's or CI host. **No host-level execution is authorized by the comment,
and none was performed.**

### Tracked, not resolved here

- **11862020 — Terraform / Pulumi / Aspire as inspiration for provider
  conformance.** A candidate mapping for stage 5 to verify against each tool's
  current documentation (written from general knowledge, *not* verified this
  run):
  - Terraform's provider *Read*/refresh corresponds to `diagnose`;
  - Terraform's *plan* and Pulumi's *preview* correspond to R-2's `plannable`;
  - Pulumi's *Check* and Terraform's schema validation correspond to `validate`;
  - Aspire's resource health checks correspond to diagnosis `status`.

  This feature changes nothing because of it.
- **11960340 — Cloudflare deploy via Terraform, Pulumi or the Cloudflare CLI.**
  This is Decision 8's *operation strategies*: one `deploy` operation on
  `cloudflare.worker@1`, with strategies `wrangler`, `terraform` and `pulumi`,
  each with its own dependencies (e.g. a `hashicorp.terraform@1` contract).
  Worker deploy stays deferred (P-3). Recorded on stage-5 item 1.
- **11927566 — a copy of `rise-lock` under an XDG directory.** Decision 7 makes
  the lock local runtime provenance, which fits `$XDG_STATE_HOME`. Functualize
  already writes per-user state below the home directory: AGENTS.md (*Writing
  tests*) requires tests spawning `func` to set `HOME` and all three `XDG_*`
  roots, because `func` writes an install registry there. `rise-lock` stays deferred; recorded on stage-5 item 3.
- **11927583 — how Rise knows a contract's owner.** Candidate mechanisms for
  stage 5: the owning distribution's repository URL in its package metadata,
  verified provenance or attestation of that distribution, or a registry
  identity. Decision 12 leaves the mechanism open. Recorded on stage-5 item 7.
- **11927592 — reusing Functualize DI.** Part of the answer exists already:
  `RiseCatalog` reaches Rise's jobs through `PluginHost.di.provide`
  (`src/functualize/_types/host.py:116`). The open part is Decision 15's typed
  consumer proxy (`npm: Npm` resolved to a provider). Resolving it per
  invocation needs a factory registration. The public port omits
  `provide_factory` ("absent because no plugin source calls it",
  `src/functualize/_types/host.py:109`), and the constitution freezes the DI
  registry before execution. So the proxy needs either a core change to the port
  or a boot-time singleton resolver that resolves lazily at call time. Recorded
  on stage-5 item 6.

## Limitations of this pass

- Revision 2's and revision 3's sessions both refused serena and any shell
  search outside the run workdir.
  - Revision 2 checked by direct file reads, plus one test run.
  - Revision 3's searches (R-1's graph census) ran through a small Python line
    search over `src/` and `plugins/`, skipping `__pycache__` and `.venv`. Its
    regex is quoted in R-1's prose. It is not committed.

  graphify was not re-run. Neither revision adds a dependency-direction claim
  that graphify would be needed for: B1 means no core edge changes.
- The Terraform / Pulumi / Aspire mapping under *Tracked* is from general
  knowledge and is marked as unverified. Stage 5 verifies it.
- Sizes in plan.md § *Files to change* are estimates for new trees.
- The Shape Intent has no owner comments yet. T11 re-reads it before closing,
  and anything that arrives in the meantime is checked against the set then.
