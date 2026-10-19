# contracts.md — walk-recorded-route

External interfaces only: what a user types and sees, what an MCP client
receives, and what a store author implements. Internal sorting, module
placement and test files are `plan.md`'s. Section numbers are stable, and
`plan.md` and `tasks.md` cite them.

Marks follow the Shape Intent's §7. **Binding** values were fixed by the
approved page. **Finalized** values were provisional there and are fixed
here (spec § *Decisions*).

## 1. `func builtin workflow show` — text

```none
$ func builtin workflow show release-ba7bd1bb
Workflow: release
State:    completed  (status: completed)
Position: None
Steps:
  score-submission: success -> {'score': 0.93}
  auto-approve: success -> 'approved'
  publish: failed -> None
  rollback: success -> 'rolled back'
Branches: score-submission -> approve
Failure routes: publish -> rollback
Pending gates: -
Epilogue: success
$ echo $?
0
```

| # | Row | Mark |
| --- | --- | --- |
| 1.1 | `Branches:` is printed on every `show`, immediately after the `Steps:` block (or after `Position:` when there is none) | Binding (Q2 a) |
| 1.2 | `Failure routes:` is printed on every `show`, immediately after `Branches:` and before `Pending gates:` | Binding shape (Q2 a); label Finalized |
| 1.3 | An entry renders as `<key> -> <value>`; entries are joined with `, ` | Binding (unchanged from today) |
| 1.4 | An empty map renders as `-`: `Branches: -`, `Failure routes: -` | Binding (Q2 a) |
| 1.5 | Entries appear in recording order (§4.3) | Finalized |
| 1.6 | Every other line of `show` (`Workflow:`, `State:`, `Position:`, `Steps:`, `Pending gates:`, `Epilogue:`) is unchanged | Binding |

A walk that never branched:

```none
$ func builtin workflow show nightly-4c1e
Workflow: nightly
State:    completed  (status: completed)
Position: None
Steps:
  fetch: success -> 'ok'
Branches: -
Failure routes: -
Pending gates: -
Epilogue: success
```

## 2. The projection — JSON keys

```json
{
  "workflow_id": "release-ba7bd1bb",
  "...": "…every existing key, unchanged…",
  "branches": {"score-submission": "approve"},
  "failure_routes": {"publish": "rollback"},
  "...": "…"
}
```

| # | Row | Mark |
| --- | --- | --- |
| 2.1 | `branches` is an object `{<source node>: <condition label>}` holding **conditional choices only** | Binding |
| 2.2 | `failure_routes` is a new, always-present object `{<failed node>: <target node>}` holding **failure routes only** | Binding shape (Q1 a); spelling Finalized |
| 2.3 | Both keys are always present; `{}` means *nothing of that kind was recorded* | Binding |
| 2.4 | Every key and value in both objects is a string; neither contains `\x00` | Binding |
| 2.5 | A failure routed to `END` has the value `"END"` | Finalized (spec D4) |
| 2.6 | Object member order is recording order (§4.3) | Finalized |
| 2.7 | `failure_routes` is placed immediately after `branches`; every other key, its name, type and position is unchanged | Binding |
| 2.8 | For the same decision records, both objects are identical on the documents store and the relational store | Binding (acceptance property) |

A failure routed to `END`:

```json
"failure_routes": {"publish": "END"}
```

```none
Failure routes: publish -> END
```

## 3. Surfaces that carry §2

Each one returns or renders the same projection, so §1–§2 hold on all of
them. No surface gains or loses a parameter.

| # | Surface | Carries |
| --- | --- | --- |
| 3.1 | `func builtin workflow show <id>` | text per §1 |
| 3.2 | `func builtin workflow show <id> --format json` | §2; byte-identical to 3.3 (existing guarantee, `docs/cli/workflow.md:180`) |
| 3.3 | MCP `get_workflow_state(workflow_id)` | §2 |
| 3.4 | `func builtin workflow list --format json` | §2 in every element of `workflows` |
| 3.5 | MCP `list_workflows(...)` | §2 in every element of `workflows` |
| 3.6 | the app flag `--wf-show` | §2 (it prints the projection as JSON) |
| 3.7 | a resume result's `scope` (CLI `workflow resume --format json`, MCP `resume_workflow`) | §2 |

Not touched: `workflow list` text, `--wf-status`, `workflow watch` events,
the TUI.

## 4. Port — `WorkflowReader.branches`

`WorkflowReader` and `RuntimeStore` are public (`functualize.plugin`). The
reader gains one member:

```python
from collections.abc import Mapping
from functualize.plugin import WorkflowReader


class WorkflowReader(Protocol):
    def branch(self, scope_id: str, decision_key: str) -> str | None: ...  # unchanged
    def branches(self, scope_id: str) -> Mapping[str, str]: ...            # new
```

| # | Row | Mark |
| --- | --- | --- |
| 4.1 | `branches(scope_id)` returns every decision record of the scope as `{decision_key: chosen_target}`, **raw**: keys and values exactly as `RecordBranch` wrote them, markers included | Binding |
| 4.2 | An unknown scope, or a scope with no records, returns an empty mapping; it does not raise | Binding |
| 4.3 | Iteration order is the order the records were written | Finalized |
| 4.4 | One call reads the whole scope; it is the only branch read the projection makes per scope | Binding (spec D2) |
| 4.5 | `branch(scope_id, decision_key)` keeps its signature and behaviour | Binding |
| 4.6 | Both in-tree stores implement it: documents (`DocumentRuntimeStore`) and relational (`functualize-substrate-sqlite`) | Binding |
| 4.7 | The member name is `branches` | Finalized |
| 4.8 | The public member has a caller under `examples/` | Repository rule (spec D7) |

Store-author view, on a scope that took one branch and routed one failure:

```python
store.workflows.branches("release-ba7bd1bb")
# {'score-submission': 'approve', 'publish\x00onfailure': 'rollback'}
```

The raw form is the store's contract. The operator-facing form is §2. A
store author never sorts records into kinds.

## 5. Conformance — `functualize.testing.conformance.run_baseline`

| # | Row | Mark |
| --- | --- | --- |
| 5.1 | `run_baseline(make_store)` gains a check that, after `RecordBranch` writes `("fork" → "left")` then `("join" → "right")` on one scope, `branches(scope)` equals `{"fork": "left", "join": "right"}` in that order, and `branches("missing")` equals `{}` | Binding (shape §5) |
| 5.2 | The check also holds after the store is rebuilt over the same directory (the suite's existing reopen contract) | Binding |
| 5.3 | A store without `branches` fails `run_baseline` with an `AssertionError` naming the missing reader | Finalized |
| 5.4 | The check runs for documents and sqlite in `tests/conformance/test_baseline.py` (already parametrized over both, lines 54-59) | Binding |
| 5.5 | The check's name in `BASELINE` reads `"record branch and branches"` (beside `"record branch and branch"`) | Finalized |

## 6. Refusal — a store that cannot list its records

Raised as the existing `ScopeStoreUnreadableError`, so both surfaces' existing
mapping carries it (spec D5).

```none
$ func builtin workflow show deploy-77aa
Error: the runtime store 'pg' cannot list a scope's recorded branches
(WorkflowReader.branches is missing), so workflow show would report none where
some may exist. Upgrade the plugin that provides 'pg'.
$ echo $?
2
```

```json
{"error": "scope_store_unreadable",
 "message": "the runtime store 'pg' cannot list a scope's recorded branches (WorkflowReader.branches is missing), so …"}
```

| # | Row | Mark |
| --- | --- | --- |
| 6.1 | Every surface in §3 refuses instead of emitting `{}` | Binding |
| 6.2 | CLI: message on stderr prefixed `Error: `, exit code `2` (`ExitCode.USAGE`) | Finalized (page had exit 1 provisional) |
| 6.3 | MCP: the existing error object with code `scope_store_unreadable` | Finalized |
| 6.4 | The message names the store's scheme, the missing `WorkflowReader.branches`, and what to do (upgrade the providing plugin); wording beyond that is the plan's | Finalized shape |
| 6.5 | An unknown scope id keeps today's refusal: `Error: no workflow scope '<id>'.`, exit 1; MCP `workflow_not_found` | Binding (unchanged) |

## 7. Declaration — node names refuse NUL

```python
from functualize.workflow import Step, Gate, AgentStep

Step("publish\x00onfailure")
# ValueError: Step name must not contain a NUL character ('\x00'): 'publish\x00onfailure'
```

| # | Row | Mark |
| --- | --- | --- |
| 7.1 | `Step`, `Gate` and `AgentStep` raise `ValueError` at construction when the node name contains `\x00` | Binding (page H2; spec B7) |
| 7.2 | The message names the node kind, says a NUL character is not allowed, and shows the name with `repr` | Finalized shape |
| 7.3 | The refusal happens where the empty-name refusal happens today (`Step job reference must not be empty`, `Gate name must be a non-empty string`) | Binding |
| 7.4 | Every name without `\x00` canonicalizes and is accepted exactly as today | Binding |

## 8. Unchanged external surfaces

| # | Surface | Guarantee |
| --- | --- | --- |
| 8.1 | What a walk records (`RecordBranch`, its keys and values), `workflow_branches`, `scopes.json` | identical bytes; no migration |
| 8.2 | Replay of pinned choices on resume | unchanged |
| 8.3 | `edges`, `steps`, `results`, `pending_gates`, `epilogue`, `state`, `status` in the projection | unchanged |
| 8.4 | Every CLI verb's and MCP tool's parameters | unchanged (verb-parity test unaffected) |
| 8.5 | Config keys, environment variables, files | none added |

## 9. Documentation and changelog

| # | Row |
| --- | --- |
| 9.1 | `docs/cli/workflow.md` § `func builtin workflow show` names `branches` and `failure_routes`, shows both text lines including the `-` form, and states that bookkeeping records are not listed |
| 9.2 | `CHANGELOG.md` `[Unreleased]` records: relational projects now show recorded branches and failure routes; on documents projects failure routes move from `branches` to `failure_routes` and notification markers are no longer listed; store authors implement `WorkflowReader.branches` (checked by `run_baseline`); node names may not contain NUL |
| 9.3 | The ADR that records the port widening (spec D7) is linked from 9.1's neighbourhood only if `plan.md` places one there; otherwise from `CHANGELOG.md` |
