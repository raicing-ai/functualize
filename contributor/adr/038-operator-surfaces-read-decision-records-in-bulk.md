# ADR-038: The Operator Surfaces Read a Scope's Decision Records in Bulk, and the Engine Sorts Them

**Status**: accepted
**Date**: 2026-10-20
**Deciders**: maintainer, by the approved shape intent for the recorded-route
feature and the spec decisions D2–D7 recorded from it.

## Context

A workflow's *route* — which branch a conditional edge took, and where a failed
node was sent — is durable, but it was not visible. On a documents project
`workflow show` printed every decision record under one `Branches:` line, raw
keys included, so `publish\u0000onfailure` sat beside `score-submission` and a
notification marker looked like a branch. On a relational project it printed
nothing: `_port_record` hard-coded `"branches": {}`
(`src/functualize/app/_workflow_view.py`). The two stores disagreed, and the
relational answer was indistinguishable from *never branched* — the silent
absence the projection exists to prevent.

The port had exactly one member for this data, `WorkflowReader.branch(scope_id,
decision_key)`, and it is a **per-key** read. The projection holds a scope, not a
key: at that point the only way to fill `branches` was either to read nothing
(what it did) or to enumerate the candidate keys from the **declaration** and
ask `branch()` for each. The second is worse than the first. A scope whose
workflow is no longer loadable — the workflow changed, the module moved, the
scope is a week old — has no declaration to enumerate from, so the projection
would report `{}` for a route it simply could not ask about. That is the same
defect wearing a different hat.

Two further facts constrained the shape:

- `WorkflowReader` and `RuntimeStore` are **public** — exported from
  `functualize.plugin` and exercised by third-party stores through
  `functualize.testing.conformance`. Any member added is a contract every store
  must implement, not an internal convenience.
- The decision-key encoding (`<node>\x00onfailure`, `\x00notify\x00`,
  `"\x00end"`) lives in the walker, which is where the walk writes it. The
  projection is in `app/`; making it parse the encoding would be Feature Envy
  across a layer boundary, and a second encoding site is exactly what
  [ADR-025](025-engine-owns-transition-meaning.md) says must not exist: the
  engine owns what a transition *means*.

[ADR-033](033-the-walks-scope-io-goes-through-the-selected-store.md) had already
put the walk's scope I/O on the selected store and left the operator surfaces
reading scopes through it. This decision finishes the read half of that promise
for one member and stops there.

## Decision

**1. One bulk reader on `WorkflowReader`.**

```python
def branches(self, scope_id: str) -> Mapping[str, str]: ...
```

It returns `{decision_key: chosen_target}` **raw** — exactly what
`RecordBranch` wrote, bookkeeping keys included — iterating in recording order.
An unknown scope, or one with no records, is an empty mapping, never an error.
Sorting records into kinds is not the store's job, so the member is one read and
one meaning on every backend: `_DocumentWorkflowReader` returns the stored
object, `SqlWorkflowReader` runs one query over `workflow_branches` ordered by
`rowid`.

The projection makes **one** call per scope. `show` on the relational store
issues one more query than before; `list` goes from `3N+1` to `4N+1` for `N`
listed scopes — one read per scope, never one per record. A per-key read would
add `K` queries per scope, `K` being every key the walk could have written.

**2. The engine sorts, the view renders.** `_engine/decision_keys.py` gains
`recorded_route(raw) -> RecordedRoute`, a frozen pair of dicts, and owns the
whole encoding: `failure_key`, `notify_key`, `ROUTED_TO_END` and now the
decoder. A key with no NUL is a conditional choice; `<node>\x00onfailure` is a
failure route; anything else containing NUL is a marker and is dropped. The view
calls `recorded_route` and never parses `\x00`. The encoders moved out of
`workflow_walker.py` into the same module, so encoding and decoding change
together — the walker's three call sites now import them.

**3. `END` reads `"END"`.** A failure route to the terminal node is recorded as
`ROUTED_TO_END` (`"\x00end"`) and rendered as the public authoring spelling
`"END"`. It cannot collide with a node name: names are canonical lowercase
(`Step("END").name == "end"`), and the graph's own `edges` spells `END` as
`null`, which the string→string projection cannot carry.

**4. The projection carries two objects, not one.** `branches` holds conditional
choices only and `failure_routes` is a new, always-present object holding failure
routes only. Markers are not rendered anywhere. Both keys are present on every
projection, so a consumer distinguishes *nothing recorded* from *something read*;
`show` prints `Branches:` and `Failure routes:` unconditionally, `-` when empty.

**5. A store that cannot list its records refuses, it does not report `{}`.**
Raising is the only truthful answer for a store whose `workflows` has no
callable `branches`: the alternative is the silent absence this change exists to
remove. The refusal reuses `ScopeStoreUnreadableError`, which every surface
already maps — CLI exit `2` (`ExitCode.USAGE`) with the message on stderr under
an `Error: ` prefix, MCP `scope_store_unreadable` — rather than a new exit code
or a second error spelling. The message names the store's scheme, the missing
`WorkflowReader.branches`, and the fix (upgrade the plugin that provides it).

That promise is only kept if it reaches **every** operator surface, so the two
that did not map it were repaired here: MCP `resume_workflow` read the legacy
document store instead of the selected one and answered `workflow_not_found` for
a scope that existed, and both click wrappers (`--wf-show` on the eager and the
lazy path) resolved the `--wf-*` flags outside `prelude_refusal`, so the refusal
escaped as a traceback with exit `1`.

**6. `branches` joins the conformance baseline.** `run_baseline` gains a
`record branch and branches` check beside `record branch and branch`, so a store
that implements the port and omits the bulk reader is non-conformant — and fails
with an assertion that names the missing member — rather than quietly partial.
Both in-tree stores implement it.

**7. The public member gets an example caller.**
`examples/standalone/workflow_store_read/test_workflow_store_read.py` reads
`runtime.workflows.branches(...)` from a booted app, satisfying the repository
rule that every public member of a public class has a caller under `examples/`
(`contributor/reference/public-api-example-coverage.md`).

### What is deliberately not here

`retry_epilogue` and `--wf-input` still reach a relational store through the
document-only API. They are operator verbs, not reads of a decision record, and
moving them is the rest of ADR-033's open migration, not this member's
consequence. The switch in `_workflow_view` that picks the raw map's source for
`suspend`, `cancel`, `reclaim` and `purge` survives for the same reason.

## Consequences

### Positive

- A relational project shows its recorded route. The defect's `{}` is gone, and
  with it the ambiguity between *nothing recorded* and *nothing read*.
- Documents and relational projects answer identically, through the same
  sorting code, so the two stores cannot drift on what a route means.
- Reading a scope's route costs one read per scope, independent of how many
  records it has or whether its workflow is still loadable.
- A third-party store that lacks the reader is refused loudly on every surface
  at once — CLI exit 2, MCP `scope_store_unreadable` — instead of projecting a
  confidently wrong `{}`.
- The decision-key encoding has one module. A change to it is one import switch,
  not Shotgun Surgery across `_engine` and `app`.

### Negative

- The public port grew by one member, and it is a contract: every store,
  in-tree and third-party, must implement `branches` to conform.
- Documents projects see a **change in what `branches` holds**: failure routes
  move to `failure_routes`, notification markers are no longer listed, and a
  script that read `branches["publish\u0000onfailure"]` breaks. The key was
  never documented; the replacement is `failure_routes["publish"]`.
- `list` costs `N` more queries than it did. On the relational store that is
  measurable; it is the price of not reading per key.
- The `isinstance(store, RuntimeStore)` switch in `_workflow_view` still exists,
  and `ScopeStore` and `RuntimeStore` still offer different interfaces for the
  same operator need.

### Neutral

- Records, keys, values, `workflow_branches` and `scopes.json` are unchanged.
  Recording order is preserved: the documents store now writes JSON members
  unsorted, and records written before that keep their stored order with no
  backfill and no schema migration.
- Node names gained a refusal for `\x00` in `Step`, `Gate` and `AgentStep`. A
  NUL in a name would be a second encoding in the same string that the decision
  key already uses.

### Surviving smells

| Smell | Where | Why it survives |
| --- | --- | --- |
| **Primitive Obsession** | the NUL-delimited decision key, now confined to `_engine/decision_keys.py` | Replacing it with a typed record kind changes what is recorded and needs a `workflow_branches` / `scopes.json` migration, which the shape rules out. This change confines it: one module encodes and decodes, no other module parses NUL. |
| **Switch Statements** | `_workflow_view._scopes` / `_read_scope` (`isinstance(store, RuntimeStore)`) | Removing it means moving `cancel`, `reclaim`, `purge` and `suspend` onto the port for documents too — ADR-033's open migration. |
| **Alternative Classes with Different Interfaces** | `ScopeStore` vs `RuntimeStore` as the operator store | Same root, same owner. |

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
| --- | --- | --- | --- |
| Keep the per-key `branch()` reader and enumerate keys from the declaration | No port change, no new contract for store authors | A scope whose workflow is no longer loadable reads nothing and reports `{}` — defect 1 again; `K` reads per scope | It cannot answer the question the projection asks, and its failure mode is silent |
| Decode the encoding in the projection (`app/_workflow_view.py`) | No new module | Feature Envy: `app` parses an encoding it does not own; a future encoding change becomes Shotgun Surgery across `_engine` and `app` | The page's owner table puts the encoding in the engine |
| Put the decoder in `workflow_walker.py` as module functions | Legal, encoders and decoder together | `app` would import a 1 100-line module for four lines of decoding, and it grows the pre-existing Large Class | A new module owns the encoding; the walker only imports it |
| Move the documents operator path fully onto the port in the same change, deleting the switch | Removes the Switch Statements smell | Requires `cancel`, `reclaim`, `purge` and `suspend` on the port for documents — ADR-033's migration, out of scope here | Scope; this ADR records the read half only |
| Keep projecting `{}` for a store that cannot list its records | No refusal, no error mapping to reuse | The `{}` is indistinguishable from *never branched*, which is the defect being fixed | It reports a confident answer that was never read |
| Amend ADR-033 instead of a new ADR | One fewer file | ADR-033 is accepted and decides *where* a walk's scope I/O goes; this decides a public port member, engine-owned decoding, and a visible documents-path change | Rewriting an accepted ADR hides the decision |

## References

- [ADR-025](025-engine-owns-transition-meaning.md) — the engine owns what a
  transition means; the decoder is the engine's.
- [ADR-033](033-the-walks-scope-io-goes-through-the-selected-store.md) — the
  walk's scope I/O goes through the selected store; this finishes the operator
  read half for one member.
- `contributor/reference/runtime-persistence-data-model.md` — the port's shape
  and the conformance baseline.
