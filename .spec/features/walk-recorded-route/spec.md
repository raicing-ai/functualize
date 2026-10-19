# walk-recorded-route

Every store shows the route a walk recorded, in one readable shape.
`func builtin workflow show`, its `--format json`, `workflow list --format json`
and the MCP tools `get_workflow_state` / `list_workflows` report a walk's
**conditional choices** under `branches` and its **failure routes** under
`failure_routes`. The answer is identical on the documents store and the
relational (SQLite) store, and the engine's internal bookkeeping records never
appear.

Shape: *Shape Intent — A Walk's Recorded Route, the Same on Every Store
(branches and failure routes in workflow show / get_workflow_state)*,
Confluence SD page 18972707, **version 2, `Authority: Approved`**, read live
2026-10-19 (updated 2026-10-19 02:56:37 UTC). The selected model is the page's
§9 candidate **B, split by kind, both stores**. The maintainer's answers to
the page's open questions are **Q1 (a)** and **Q2 (a)** (MCH-186 comment
`01a15217-dc05-773c-8970-69a07878d17d`). This spec is the behaviour that
candidate promises. Where this spec finalizes something the page marked
*provisional*, or where a measurement here disagrees with the page, it says
so under § *Decisions*.

Words used below:

- **walk**: one run of a `@workflow` graph, identified by its scope id.
- **decision record**: one row the engine writes through
  `RecordBranch(scope_id, generation, decision_key, chosen_target, now)`
  (`src/functualize/_types/persistence.py:292-305`). It is immutable once
  written, and its docstring names three kinds: *"a conditional choice, a
  failure route, a marker"*.
- **conditional choice**: the label a `ConditionalEdge`'s condition returned,
  recorded under the edge's source node.
- **failure route**: where an `OnFailure` sent a raising step, recorded under
  the failing node.
- **marker**: a record the engine writes for its own idempotence, not a
  route. Today the only kind is a notification marker (`Notify` delivered:
  `→ "sent"`).
- **documents store / relational store**: the two in-tree `RuntimeStore`s.
  `runtime_store.url` unset selects documents; `"sqlite:"` selects relational
  (`docs/guides/workflows.md` § *Runtime stores*).
- **the projection**: the dict `describe_scope` / `list_scopes` build
  (`src/functualize/app/_workflow_view.py`). Every operator surface renders it
  or returns it unchanged.

## The defect

All measurements were taken on base **`91947bb`** during authoring. Base
`91947bb` and the page's `d1c7e40a` differ by one commit, and it touches none
of the files below (`git diff --stat d1c7e40a 91947bb -- <those files>` is
empty).

The probe is one `release` workflow: `score-submission` → `ConditionalEdge` →
`auto-approve` → `publish` (raises) → `OnFailure` → `rollback` → `END`. It
runs once per store, with `HOME` and the four `XDG_*` roots isolated:

```none
# documents project
$ func builtin workflow show release-358ab33c
Steps:
  auto-approve: success -> 'approved'
  publish: failed -> None
  rollback: success -> 'rolled back'
  score-submission: success -> {'score': 0.93}
Branches: publish onfailure -> rollback, score-submission -> approve
Pending gates: -
Epilogue: success
$ … --format json   →  "branches": {"publish\u0000onfailure": "rollback", "score-submission": "approve"}

# relational project (config.base.toml: [runtime_store] url = "sqlite:")
$ func builtin workflow show release-9386e154
Steps:
  score-submission: success -> {'score': 0.93}
  auto-approve: success -> 'approved'
  publish: failed -> None
  rollback: success -> 'rolled back'
Pending gates: -
Epilogue: success
$ … --format json   →  "branches": {}
```

1. **A relational project never shows a recorded route.** The SQLite
   `workflow_branches` table holds both rows
   (`('score-submission','approve')`, `('publish\x00onfailure','rollback')`).
   But `_port_record` hard-codes `"branches": {}`
   (`src/functualize/app/_workflow_view.py:434`), so `show` prints no
   `Branches:` line, and the JSON's `{}` cannot be told apart from *never
   branched*. `docs/cli/workflow.md:176` promises that `show` prints *"every
   recorded branch choice"*.
2. **A documents project shows the engine's bookkeeping as branches.** The
   document path copies the raw record map verbatim
   (`_workflow_view.py:484`). So a failure route appears under the internal
   key `publish\x00onfailure`. The terminal shows the NUL as a gap, and JSON
   shows it as `\u0000`.
3. **A documents project shows notification markers as branches.** A
   straight-line two-step walk with `Notify(on="completed", to="ops")`, walked
   on a `ScopeStore` and projected through `_describe`, gives
   `"branches": {"\u0000notify\u0000completed\u0000\u0000ops": "sent"}`. That
   walk has no `ConditionalEdge` or `OnFailure`.
4. **A failure route to `END` records an internal value.** `OnFailure(…,
   target=END)` records the target `"\x00end"` (`_ROUTED_TO_END`,
   `src/functualize/_engine/workflow_walker.py:1098`, written at `:657-658`).
   The documents path would print that value verbatim.
5. **Nothing asserts any of it.** `rg -n "Branches:" tests/` finds no
   assertion on the CLI line; its only hit is a class name,
   `tests/test_scope_store.py:142`. `rg -n '"branches"' tests/` finds one
   fixture, one raw-record check and one marker check
   (`tests/test_state_cli_scopes.py:43`,
   `tests/workflow/test_failure_routing.py:439`,
   `tests/workflow/test_notify.py:339`). None of the three reads the
   projection. The conformance check `record_branch_and_branch`
   (`src/functualize/testing/conformance/baseline.py:412`) covers the
   per-key read only.

**Prior art.** ADR-033 rejected *"Leave the operator surfaces blind on a
non-document store … the CLI and MCP report an empty or stale world —
shipping a surface that lies about durable state is worse"*
(`contributor/adr/033-the-walks-scope-io-goes-through-the-selected-store.md`,
§ *Alternatives Considered*). Defect 1 is a residue of exactly that rejected
alternative. `ScopeStoreUnreadableError`
(`src/functualize/_types/errors.py:272`) states the refusal doctrine this
spec reuses: an unreadable store *"**Never** degrades to 'no scopes' … a
refusal, not an empty list"*.

## User stories

- **US-1 (operator, relational project).** I read a finished walk and see
  which branch it took and where a failed step was routed, exactly as on a
  documents project. (Shape UC-1.)
- **US-2 (operator, any store).** For a walk that never branched, `show`
  tells me *nothing was recorded*, not nothing at all. (Shape UC-2.)
- **US-3 (MCP agent / script).** I read `failure_routes["publish"]` from
  `get_workflow_state` without knowing the engine's key encoding, and get the
  same payload from either store. (Shape UC-3.)
- **US-4 (store author).** The conformance suite tells me to implement the
  bulk reader. A store that lacks it is refused by name, never shown as
  *no branches*. (Shape UC-4.)

## Behaviour

### B1 — what the projection reports

For a scope whose decision records are `R`, the projection carries two keys,
both always present:

- `branches`: one entry per **conditional choice** in `R`,
  `{<source node>: <condition label>}`.
- `failure_routes`: one entry per **failure route** in `R`,
  `{<failed node>: <target node>}`, where a route to `END` reads `"END"`.

Markers, and any record that is neither a conditional choice nor a failure
route, appear in **neither** key. No key or value either map contains has a
NUL character. Entries are in the order they were recorded. A scope with no
such records reports `{}` for each key, and `{}` then means *nothing was
recorded*, on every store.

### B2 — the same answer on every store

Two scopes holding the same decision records produce identical `branches`
and `failure_routes`, key for key and in the same order, whether the selected
store is documents or relational. This holds for every surface that carries
the projection (B4).

### B3 — `workflow show`, text form

`func builtin workflow show <id>` prints two lines between `Steps:` (or
`Position:`, when no step ran) and `Pending gates:`, always, in this order:

```none
Branches: <key> -> <value>, <key> -> <value>
Failure routes: <key> -> <value>
```

An empty map prints `-` (`Branches: -`, `Failure routes: -`), the same
convention `Pending gates: -` already uses. A line is never omitted.

### B4 — every surface carries the same projection

The projection, and so B1–B2, reaches every surface that already renders or
returns it:

- `func builtin workflow show` (text and `--format json`);
- `func builtin workflow list --format json` (each row);
- the MCP tools `get_workflow_state` and `list_workflows` (each row);
- the app flag `--wf-show`;
- the `scope` embedded in a resume result (`app/_workflow_control.py:398`).

The existing guarantee that `show --format json` and `get_workflow_state`
return byte-identical payloads (`docs/cli/workflow.md:180`) continues to hold.

### B5 — a store that cannot list its records is refused, not believed

When the selected store cannot list a scope's decision records (a store
written before this change), a surface that needs the projection refuses with
a named error. It never reports `{}`. The CLI exits non-zero, and MCP returns
an error object instead of a payload (contracts §6).

### B6 — what is recorded does not change

Walks record exactly what they record today, under the same keys and values,
in both stores. No row or document is migrated. A resumed walk reads its
pinned choices as today. The per-key reader `WorkflowReader.branch` is
unchanged.

### B7 — a node name cannot contain NUL

A workflow node (`Step`, `Gate`, `AgentStep`) whose name contains `\x00` is
refused when the node is constructed, the same moment and error family as an
empty name today. Today such a name is accepted: on `91947bb`,
`Step("a\x00onfailure")` and `Step("\x00notify\x00x")` each build and pass
`WorkflowDeclaration` construction. That makes a node indistinguishable from
the engine's own record keys. The shape's H2 makes this refusal the condition
for B1's sorting to be trustworthy.

### B8 — documentation tells the truth

`docs/cli/workflow.md` § `workflow show` names both keys and both lines, and
states that bookkeeping records are not listed. The `CHANGELOG.md`
`[Unreleased]` entry records three visible fixes:

- the relational fix;
- the documents-path change (`failure_routes` replaces the NUL-keyed entry;
  markers leave `branches`);
- the new reader that store authors must implement.

## Acceptance criteria

Each criterion runs on **both** stores unless it says otherwise. The probe
and the projection tests are the executable gates.

| # | Check | Observable result |
| --- | --- | --- |
| AC-1 | The § *The defect* probe, relational project, after the change | `show` prints `Branches: score-submission -> approve` and `Failure routes: publish -> rollback`; JSON `"branches": {"score-submission": "approve"}`, `"failure_routes": {"publish": "rollback"}`; exit 0 |
| AC-2 | Same probe, documents project | byte-identical `branches` / `failure_routes` to AC-1; no `\u0000` anywhere in either map |
| AC-3 | A straight-line walk with no `ConditionalEdge` / `OnFailure` | `Branches: -` and `Failure routes: -` printed; JSON `{}` for both |
| AC-4 | A walk with `Notify(on="completed", to="ops")` and a registered notifier | the marker appears in neither key, on either store; the stored marker is unchanged (`tests/workflow/test_notify.py:339` still passes) |
| AC-5 | `OnFailure(source="publish", target=END)` | `failure_routes == {"publish": "END"}`; `Failure routes: publish -> END` |
| AC-6 | `workflow list --format json`, `list_workflows`, `--wf-show`, a resume result | each carries the same `branches` / `failure_routes` as `show --format json` for the same scope |
| AC-7 | `show --format json` vs `get_workflow_state` | byte-identical (the existing test keeps passing, now with both keys present) |
| AC-8 | `run_baseline` from `functualize.testing.conformance` | holds every registered store to the bulk reader (contracts §5); passes for documents and sqlite in `tests/conformance/test_baseline.py` |
| AC-9 | A store whose `workflows` reader has no bulk reader | `show` exits 2 with the contracts §6 message; `get_workflow_state` returns `scope_store_unreadable`; `{}` is never emitted |
| AC-10 | `Step("a\x00b")`, `Gate(name="g\x00x", …)`, `AgentStep(name="x\x00y", …)` | each raises `ValueError` naming the node kind and the NUL; ordinary names unchanged |
| AC-11 | Recording order, documents vs relational | for a walk whose records are written in order *k₁, k₂*, both stores list them *k₁, k₂* |
| AC-12 | Regression | AC-1's relational assertion and AC-2's no-NUL assertion fail on `91947bb` and pass after the change |
| AC-13 | Read cost, relational | `show` issues one more scope read per scope than on `91947bb`, and `list` one more per listed scope, never one per record (§ *Decisions* D2) |
| AC-14 | Reachability | each production path of B4 is named in `plan.md`, and breaking the call on it makes a test fail (`contributor/guides/wiring-discipline.md`) |

## Non-goals

- Changing what a walk records, any key encoding, `workflow_branches`, or
  `scopes.json` (B6).
- A notifications surface. Markers are hidden, not shown elsewhere.
- Any other `_port_record` gap, and any other part of the workflow-persistence
  work's scope (ADR-033).
- `workflow list`'s text table, `--wf-status`, the TUI. None of them renders
  branches today, and none starts.

## Deliberate behaviour changes

| Surface | Before (`91947bb`) | After |
| --- | --- | --- |
| documents `branches` | every decision record, raw keys | conditional choices only |
| documents failure route | `"publish\u0000onfailure": "rollback"` inside `branches` | `"failure_routes": {"publish": "rollback"}` |
| documents notification marker | inside `branches` | not shown |
| relational `branches` | always `{}` | the recorded conditional choices |
| `show` text | `Branches:` line only when non-empty | `Branches:` and `Failure routes:` always, `-` when empty |
| store authors | per-key `branch()` only | must also implement the bulk reader; `run_baseline` checks it |

## Decisions

These are carried from the approved page or finalized here, with the page
section that fixes or permits each.

- **D1 — parity is asserted per store, not in the verb-parity file (carried,
  page §3).** FUN-27 and the trigger brief name
  `tests/workflow/test_workflow_surface_parity.py`. That file asserts CLI↔MCP
  *verb and parameter* parity, derived from the live click tree and MCP tool
  list (its module docstring). Store parity is a different property. It is
  asserted by the conformance baseline (AC-8) and by projection tests that
  run over both stores (AC-1–AC-6). Where those tests live is `plan.md`'s
  call. FUN-27's acceptance surface is kept: relational `show` displays
  recorded branches, the silent absence is gone, and tests assert the result
  for both stores.
- **D2 — one bulk read per scope, not a per-key read (carried, page §7
  binding).** Measured on `91947bb` by counting
  `LocalSqliteDriver.query` calls:
  - `show` on the relational store issues 8 queries. 4 are boot or schema;
    4 are scope reads (`workflow_scopes` 1, `workflow_steps` 2,
    `input_requests` 1).
  - `list --format json` over 3 scopes issues 14 queries: 4 boot, 1
    `workflow_scopes`, and 3 per scope.

  The bulk reader adds exactly one `workflow_branches` read per scope, so
  `list` goes from 3N+1 to 4N+1. A per-key read would add K reads per scope,
  K being the decision keys the walk could have written. Worse, it can only
  enumerate keys from the **declaration**, so a scope whose workflow is no
  longer loadable would read nothing and report `{}`. That is defect 1
  again. The existing one-read-set-per-scope shape of `list` is unchanged and
  out of scope.
- **D3 — the engine sorts records into kinds (carried, page §8 owner
  table).** The encodings live in `_engine/workflow_walker.py`
  (`_failure_branch`, `_notify_key`, `_ROUTED_TO_END`). The view never parses
  `\x00`.
- **D4 — `END` reads `"END"` (finalized here; the page did not cover it).**
  Defect 4 is a NUL in a *value*, and the page binds *"no NUL byte or internal
  encoding"* and *"plain string→string objects"*. So the value must be a
  string with no internal encoding. `"END"` is the public authoring spelling
  (`repr(END) == "END"`, `docs/api/workflow.md` § `OnFailure`). It cannot
  collide with a node, because node names are canonical lowercase: on
  `91947bb`, `Step("END").name == "end"` and `Gate(name="END", …).name ==
  "end"`. The graph's own `edges` key spells `END` as `null` (`"to": null`).
  `null` would break the page's string→string binding, so it is not used
  here.
- **D5 — the refusal reuses `ScopeStoreUnreadableError`; CLI exit 2, MCP
  `scope_store_unreadable` (finalized here; the page marked exit 1
  provisional).** Both surfaces already map that error
  (`src/functualize/_cli/builtins.py:1141-1156` →
  `ExitCode.USAGE`;
  `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py:91-100`),
  and its documented doctrine is this case's. A new exit code or MCP error
  code would be a second spelling of one refusal.
- **D6 — node names refuse NUL (carried, page §10 H2).** The page made this
  conditional on whether a node name can contain `\x00`. Measured: it can
  (B7). So the condition holds, and the refusal is in scope.
- **D7 — the bulk reader is a public API change, so an ADR and an example
  are required (carried from repository rules; settles the page's R1).**
  `WorkflowReader` and `RuntimeStore` are exported from `functualize.plugin`
  (`src/functualize/plugin/__init__.py:77,91,277,279`), and the conformance
  suite from `functualize.testing.conformance`. `AGENTS.md` makes an ADR
  mandatory for a new public API surface. The maintainer's 2026-09-17 rule
  requires an `examples/` caller for every public member of a public class
  (`contributor/reference/public-api-example-coverage.md`).
  `rg -ln "WorkflowReader|RuntimeStore|run_baseline" examples/` returns
  nothing today. Whether the decision is a new ADR or an amendment to ADR-033
  is `plan.md`'s call.
- **D8 — spellings finalized from *provisional*.** These spellings were
  provisional on the page and are now fixed:
  - the JSON key `failure_routes`;
  - the text label `Failure routes:`;
  - the entry order: recording order (B1, AC-11).

## Out of scope, recorded

These were observed on the same probes and are not filed. Each belongs to its
own ticket if wanted:

- `show` lists steps alphabetically on documents and in walk order on the
  relational store.
- The projection's `edges` do not mark an `OnFailure` edge as one. On this
  probe, `{"from": "publish", "to": "rollback"}` reads like a plain edge.
- `func builtin data show` on a relational project reported
  `Scopes: 0 … state.db#scopes (absent)` while a scope existed (page §8).
- Where `runtime_store.url` may be declared (page §8; MCH-186 thread,
  2026-10-13).

## Confirmation gate

This specification and `contracts.md` require member confirmation before
`plan.md` and `tasks.md` are written. D4, D5 and D7 are the items this spec
settles beyond the page's own words. Confirming the spec confirms them.
