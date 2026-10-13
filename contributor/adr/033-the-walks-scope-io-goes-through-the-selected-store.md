# ADR-033: A Workflow Walk's Scope Reads and Writes Go Through the Selected Store

**Status**: accepted
**Date**: 2026-10-13
**Deciders**: maintainer, by the answer recorded as this feature's open decision —
option **a**: the operator surfaces move their scope reads and their
cancel/reclaim onto the port as well, rather than refusing on a store that is not
the document backend, or shipping blind.

## Context

Storage became pluggable and selectable — a URL decides which store a project
uses, not which plugin is installed ([ADR-026](026-persistence-ports-need-no-new-layer.md),
[ADR-027](027-engine-construction-moves-after-config.md),
[ADR-028](028-storage-is-pluggable-execution-is-not.md)). Execution stayed in the
engine, and the machinery that makes it durable is the *workflow walk*: replay
with memoised step records, pinned branches, a gate that suspends and resumes,
and a code-version fence (`_engine/workflow_walker.py`, `_engine/frontier.py`).

A walk's durability is exactly what it has written about its own scope: the
claim and its generation, entry, renewal and release, each completed or failed
step, each first-time branch, the position, the status, `State` set inside a
step, and the event log a resumed walk replays. Whoever holds those writes owns
resumption.

**Only the claim travelled the port.** At `0ede988b` the walk claimed through
the port (`_engine/frontier.py:224`) and then wrote everything else through the
legacy `ScopeStore` — 46 `self._store.*` call sites, 24 in `_engine/frontier.py`,
19 in `_engine/workflow_walker.py` and 3 in `_engine/workflow_runner.py`.

On a store that is not the document backend the two paths do not meet. The
claim lands in the relational `workflow_scopes`; the release looks in the legacy
`documents` scope, finds generation 0 and owner `nobody`, and raises
`StaleGenerationError`, so the walk stops **`SUPERSEDED`** instead of blocking at
its gate. That is one scope with two authorities — the split brain
[ADR-022](022-storage-is-a-substrate-not-a-key-value-domain.md) exists to
prevent, and the same one-owner-per-fact rule
[ADR-025](025-engine-owns-transition-meaning.md) applies to the transition
itself. `tests/integration/test_substrate_durability.py` recorded the gap as a
strict xfail marked `TRANSITIONAL`.

## Decision

**Every read and write a walk makes on its own scope goes through the selected
`RuntimeStore` port. The legacy `ScopeStore` is not a second path for the
walk's scope, on any store.**

The port gains six commands and one widening, each carrying what the walk
already wrote:

| Command | What it carries | Was |
|---|---|---|
| `StartWalk` | the walk's entry: status, position, the first event | `set_scope_status` + `set_position` + `append_event` |
| `RenewLease` / `ReleaseLease` | the lease, fenced by generation | `renew_scope` / `release_scope` |
| `CompleteStep` (widened) | the step's outcome and markers, the first-time branch, the new position and status, the events | `record_step` + `record_branch` + `set_scope_status` + `set_position` + `append_event` |
| `RecordStep` | a step record that moves nothing — a timeout on takeover, a routed failure, the body's return value under `EPILOGUE_STEP_KEY` | `record_step` |
| `RecordBranch` | a first-time branch decision, with no step around it | `record_branch` |
| `MoveScope` | status and position with no step | `set_scope_status` + `set_position` |

Four commands the port already carried are now the walk's only path rather than
one of two: `ClaimWorkflow` (the claim — the single write that travelled the port
before this work), `StateBatch` (`State` set inside a step, in the buffered and
the immediate path alike), `SuspendAtGate` and `ConsumeInput` (the gate request
and the answer the walk feeds forward), and `EventWriter.append` (the walk log a
resumed walk replays). The walk reaches all of them the same way, in the shape
the port already had: one command per `RuntimeStore.transaction()`, with the
held generation on every authoritative write.

The reads follow the same rule: `WorkflowReader.step`, `.steps`, `.branch`,
`.state`, `.workflow` (with `WorkflowView.graph_digest`) and `InputReader` are
what the walk reads back, and every one of the added commands and readers joins
the conformance `BASELINE` (`tests/conformance/test_baseline.py`), so a store
that implements the port and then omits them is non-conformant rather than
quietly partial.

**The rule is enforced, not documented.** `tests/spec/test_the_walk_writes_only_through_the_port.py`
walks the `ast` of every module under `src/functualize/_engine/` — a docstring
naming `ScopeStore` must not count, and a call hidden behind a helper must still
trip — and refuses an import of `functualize._primitives.scope_store`, a call to
`_scope_store(...)`, an attribute access through `.scopes`, and any
`ScopeStore`-only method name whose receiver is not the port, the walk's own
helper or the tracker homonym. The out-of-scope sites are an explicit allowlist
of *three* functions (`executor.py`'s `_scope_store`, `_scope_for`,
`_close_scope`) and *one* module (`capabilities/state.py` — the `State` a
non-walk context keeps), each with its reason in the assertion message, and a
second test refuses an allowlist entry that no longer exists.

**What stays on the legacy store, deliberately.** `State` written by a job run
that is not inside a walk and `executor.py`'s close of such a run's scope; the
rest of the suspension/resume rewiring beyond S-9; gate evidence and the outbox
dispatcher; network and workspace persistence. `ScopeStore` is not removed and
keeps its public export from `functualize.app.utils` — it still backs the
document store and non-walk state.

## Consequences

### Positive

- A workflow parked at a gate on the selected store is claimed, released and
  resumed by another process, from another directory, and runs to its end. The
  cross-process test that recorded the gap as an expected failure is an ordinary
  passing test.
- One authority per scope fact, which is what makes "this step already ran" and
  the code-version fence mean the same thing whoever asks.
- The fence reaches every authoritative write: each command carries the held
  generation in its predicate, so a walk that lost its lease writes nothing —
  zero rows on the relational store, the document store's compare-and-swap
  refusal — and the live holder's values survive.
- The operator surfaces (`list`, `show`, `cancel`, `reclaim`, and their MCP
  counterparts) read and write the scopes the walk actually wrote, so a parked
  walk is visible and reclaimable instead of invisible.

### Negative

- The port's surface grew by six commands, one widening and four readers
  (`.step`, `.steps`, `.branch`, `.state`, beside `WorkflowView.graph_digest`),
  and each is a contract: a third-party store must implement them to conform,
  and a reader of the port must now expect a step record, a branch and the walk
  log from it.
- Refusing a stale generation is best-effort and quiet on the lease path, as
  before; a lost lease surfaces at the next authoritative write rather than at
  the moment it was lost.
- A walk's writes stay one transaction per command. Nothing may wrap a job body
  (the reference's §4), so a multi-command step is not atomic as a whole and was
  not before either.

### Neutral

- The document backend implements every new command over the same `ScopeStore`
  methods the walk used to call, so a document-store project writes the same
  files it wrote before. The walk's own tests moved with it: the cross-process
  durability test's strict xfail became a passing assertion, and the MCP
  workflow-tool tests gained the relational case.
- The walk's scope IO is no longer a place where a second store-aware
  abstraction could be introduced: [ADR-026](026-persistence-ports-need-no-new-layer.md)
  already refused a new layer, and this decision keeps the walk inside the port
  that layer would have wrapped.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Move the walk's whole scope IO onto the port, and the operator surfaces with it (chosen) | One owner per scope fact on every store; a parked walk resumes cross-process; the fence covers every write; operators stay truthful | Port surface grows; every store must implement the commands | It is the only option where the selected store is the authority for the scope, which is what selecting a store promises |
| Keep the claim on the port and leave the rest on `ScopeStore`, documenting the limitation (dual write) | Smallest diff; no new commands | Two authorities for one scope; a release on a non-document store raises `StaleGenerationError` and the walk stops `SUPERSEDED`; indefinite shadow reads | It is the defect this work exists to remove, and the shape rejects *indefinite dual write; shadow reads* |
| Move the walk's scope IO and refuse the operator verbs loudly on a non-document store until the later slice | Walk is repaired without touching operator code paths | `list`/`show`/`cancel`/`reclaim` stop working on a store a user selected; a named refusal is still a regression for them | The maintainer chose the port for the operator surfaces; refusing a selected store's own scopes is a worse answer than reading them |
| Leave the operator surfaces blind on a non-document store | No operator work at all | Every operator call silently answers about a scope nobody writes; the CLI and MCP report an empty or stale world | Shipping a surface that lies about durable state is worse than either alternative above |
| Introduce a small walk-storage facade over both stores | The walk's call sites look unchanged | A second seam that must re-decide generation, status and event ordering; [ADR-026](026-persistence-ports-need-no-new-layer.md) refused exactly this new layer | Wrapping a port in a facade that re-implements its fence is how the two-seam split brain comes back |

## See also

- [`runtime-persistence-data-model.md`](../reference/runtime-persistence-data-model.md)
  §4 — the walk's transitions, command by command, and §5 — the fence every
  authoritative write carries.
- [`workflow-walker.md`](../reference/workflow-walker.md) §4 — resume semantics:
  what a resumed walk re-reads and what it reports — and §10 — a walk the store
  refuses at the door (`HELD`).
- The feature's own artifacts (`spec.md`, `contracts.md`, `plan.md`, `tasks.md`)
  lived in `.spec/features/workflow-persistence-atomic/` and are cleared as this
  branch's last commit; they remain reachable in the pull request's head, and
  `.spec/STATUS.md` carries the durable record of what landed.
