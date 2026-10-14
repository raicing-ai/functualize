# plan.md — from-step-walk-reads

Base: `master` at `c03dfb72`. Spec: `spec.md` (confirmed by the maintainer,
2026-10-13T20:39:11Z, with D1 and D2 settled).

## Alignment

Shape: *Shape Intent — FromStep Resolution Across a Walk (one rule
everywhere: step, gate, epilogue)*, Confluence SD page 16777218, **version 3,
`Authority: Approved`**, read live 2026-10-13.

In scope, in the shape's own words (its *Candidate models*, option (i), chosen):

> `FromStep("x")` reads *this walk's* record for **any** node `x` — step or
> gate — wherever it is written: a `Tool(...)` binding, a step job's parameter
> annotation, or the epilogue body. It never runs anything, it is invisible to
> ordering by construction (a read-only reference orders nothing, …), and a
> name the walk has not produced yet is an error, not a default.

Out of scope, in the shape's own words (*Boundaries and non-goals*):

> `FromJob` **semantics do not change.** · **The subscript form is out of
> scope.** · **The decision path stays step-only.** · **No new persistence, no
> new gate lifecycle, no new graph node kind.** · **A read never runs
> anything** — not a step, not a gate, not a fingerprint lookup that could
> resurrect an earlier run's value. · **The epilogue is not added to graph
> ordering.**

**Two explicit supersessions.** The page's *Next falsifiable experiment*
steps 5 and 6 are superseded by the maintainer's answer on the carrying issue
(comment `01a136fd-9871-73a2-8afe-7cdcefbb417f`, 2026-10-13T20:39:11Z,
verbatim *"Confirm, D-1 allow it, D-2 (b)"*):

| Page says | This plan builds |
|---|---|
| 5. `Tool(read_file, allowed=FromStep("approve"))` naming a gate "is refused — a binding narrows to a step's value" | D1: allowed when `approve` is ordered before the binding's gate; refused at boot for its own gate or a later node. Consistent with option (i), and with the measurement that a gate's answer *is* a step record (`research.md` H1). |
| 6. "…has not run yet, raises the H2-style error and no default is substituted" | D2: a node a conditional branch skipped yields the parameter's declared default; with none, the error. Unknown and unordered names still fail at boot, default or not. |

The page's own text has not been amended yet (a maintainer action, raised on
the issue); verification reads this table, not the page's steps 5–6.

## Retrieval performed

| Pass | Tool | What it established |
|---|---|---|
| 3a prose | `zg query` (index built for this worktree, 14 325 entities) | gate answers have one reader, `FrontierWalk.gate_payload` (`_engine/frontier.py:496-512`); prior design ADR-005 item 6; pitfall §4 |
| 3a surface | serena `get_symbols_overview` / `find_referencing_symbols` on `FromStep` | 14 referencing files; two `_resolve_bound` bodies; `ChoiceDecision.state` (`_types/decision.py:166`) is a `FromStep` holder this feature must not validate |
| 3a direction | graphify `get_neighbors` on `FromStep`, `_validate_workflow_from_job_refs()` (graph 60 commits behind HEAD — used for shape only) | `FromStep` ← `app/_workflow_control.py`, `workflow/__init__.py`, MCP `WorkflowToolProvider`; validation → `from_job_refs`, `descendants` |
| 3a codemaps | `contributor/architecture/codemaps/{overview,modules,dependencies}.md` | `_engine/` is a peer layer; `JobExecutionEngine` is the execution entry (`entry-points.md:87`) |
| 3b blast radius | serena refs + `rg` | below, per task |
| probes | `research.md` | gate answer stored as `steps['<gate>::']`; duplicate names refused; invoked children run outside the walk (`workflow_scope_id` reset by `nested_request`, `_engine/capabilities/invoke.py:855-866`) |

## Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`) —
  KISS, single responsibility, God-class decomposition.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — the
  smell names below and their routing (Duplicate Code → Extract Method /
  pull into one function; Large Class → Extract Class; Shotgun Surgery → Move
  Method into one place).

## BEFORE

```
 PUBLIC  workflow/__init__.py ──exports──► FromStep
 ───────────────────────────────────────────────────────────────────────────────
 _types/ (foundation)
   from_job.py   FromJob, FromStep, from_job_refs ──filters isinstance(FromJob)──┐
   decision.py   ChoiceDecision.state: FromStep                                  │
   errors.py     WorkflowDeclarationError                                        │
 _primitives/ (foundation)                                                        │
   fingerprint.py reusable_return_value(record, …)  ◄──────┬────────┬───────┐    │
 ─────────────────────────────────────────────────────────┼────────┼───────┼────┼─
 _engine/ (peer layer)                                     │        │       │    │
   workflow_validation.py  _validate_workflow_from_job_refs ◄───────────────┼────┘
        (Step jobs only; FromStep invisible)               │        │       │
   executor.py  JobExecutionEngine (2 813 LOC)             │        │       │
        _inject_from_job ─► _from_job_value ──────────────┘        │       │
             in a walk: runtime_store.workflows.steps(scope) → record dict
             no match → fingerprints  (FromStep never consulted)    │       │
   gate_service.py / frontier.py   gate answer → ledger.results → steps['g::']
 ─────────────────────────────────────────────────────────────────┼───────┼──────
 PUBLIC app/ (audience: public package, private module)            │       │
   _workflow_control.py  _resolve_bound(scope_doc, bound) ─────────┘       │
        copy #1: scope["steps"] by name; missing → None                   │
 ─────────────────────────────────────────────────────────────────────────┼──────
 PLUGIN functualize-mcp                                                   │
   _workflow_tools.py  WorkflowToolProvider._resolve_bound ────────────────┘
        copy #2, byte-for-byte the same body
```

Smells the BEFORE carries:

- **Comments (lying docstrings)** — `FromStep` docstring
  (`_types/from_job.py:260-261`) and `Gate` docstring
  (`_types/workflow.py:289-291`) promise reads that do not exist.
- **Duplicate Code** — `_resolve_bound` exists twice
  (`app/_workflow_control.py:836-870`,
  `functualize_mcp/_workflow_tools.py:439-473`), and the step-record lookup
  ("first record whose key before `::` is the name") a third time in
  `executor._from_job_value` (`executor.py:2205-2213`).
- **Shotgun Surgery** — consequence of the above: any change to "how a
  walk's record is read" touches three files in two distributions.
- **Large Class** — `JobExecutionEngine`, `executor.py` 2 813 lines. Growing it
  further is a *Forbidden Pattern* (god-object growth), so the AFTER must not
  add the new injection there.

## Candidate AFTERs considered

1. **Add `_inject_from_step` to `JobExecutionEngine`, patch both
   `_resolve_bound` copies.** Rejected: grows the Large Class (forbidden), and
   writes the new rules into three copies — introduces more Duplicate Code
   and keeps the Shotgun Surgery.
2. **Route `FromStep` through `_from_job_value`.** Rejected: inherits the
   fingerprint fallthrough (`executor.py:2229-2235`) — R1, and B3 forbids it.
3. **One pure reader in `_primitives/`, one injection module in `_engine/`,
   both tool surfaces calling the reader.** Chosen (below). Smells introduced:
   none new; it removes two of the three copies and puts no logic in the
   executor beyond a call line.

## AFTER

```
 PUBLIC  workflow/__init__.py ──exports──► FromStep            (unchanged)
 ───────────────────────────────────────────────────────────────────────────────
 _types/ (foundation)
   from_job.py   FromJob, FromStep, from_job_refs (unchanged, FromJob-only)
                 + from_step_refs(func) -> {param: FromStepParam(ref, type, default)}
   errors.py     WorkflowDeclarationError, + FromStepUnavailableError
 _primitives/ (foundation; imports _types only)
   fingerprint.py  reusable_return_value                      (unchanged)
   walk_reads.py   NEW, pure, no I/O
       read_node(records, node, expected_type) -> Recorded(value) | NotRecorded | NotCarriable
       resolve_bound_values(records, bound) -> dict           (raises FromStepUnavailableError)
          ▲            ▲                         ▲
 ─────────┼────────────┼─────────────────────────┼─────────────────────────────────
 _engine/ │ (peer)     │                         │
   walk_reads.py  NEW  │                         │
       step_records(runtime_store, scope)  (StepView → record mapping; port only)
       inject_from_step(function, context, scope_id, records, live) ─► read_node
   executor.py   _inject_from_job ─► _from_job_value ─► step_records + read_node   (refactor, same behaviour)
                 + one call: inject_from_step(...) beside _inject_from_job;
                   FromStepUnavailableError → _failure_before_execution
   workflow_validation.py
       _validate_workflow_from_job_refs                        (unchanged)
       + _validate_workflow_from_step_refs: step jobs, the epilogue, gate tool bindings
 ─────────────────────────────────────────────────────────────────────────────────
 PUBLIC app/_workflow_control.py   _resolve_bound deleted → resolve_bound_values(scope["steps"].items(), bound)
 PLUGIN functualize-mcp            _resolve_bound deleted → resolve_bound_values(...)
```

Boundaries crossed, against the seven import-linter contracts:

| Edge | Contract | Legal? |
|---|---|---|
| `_primitives/walk_reads` → `_types/from_job`, `_types/errors`, `_primitives/fingerprint` | *Primitives import nothing internal* (forbids `_events`, peers, `_app`, `_cli` — not `_types`) | yes |
| `_engine/walk_reads` → `_primitives`, `_types` | *Peer layers are independent* (no other peer imported) | yes |
| `app/_workflow_control` → `_primitives/walk_reads` | *Internal never imports public* (direction is public → internal) | yes; existing edge to `_primitives/fingerprint` is replaced |
| `functualize_mcp` → `_primitives/walk_reads` | none (separate distribution; it already imports `_primitives.fingerprint` and `_types.from_job` on this path) | yes |

`uv run lint-imports` is part of every wave's gate.

## Technical approach

1. **`from_step_refs`** (`_types/from_job.py`). Same resolved-hints walk as
   `from_job_refs` (PEP 563 safe, pitfall §4), returning each `FromStep`
   parameter with its `Annotated` base type and whether it declares a default.
   `from_job_refs`, `from_job_names`, `from_job_types` are not touched (B3:
   `FromStep` never becomes a dependency name). A parameter carrying both
   markers is reported so validation can refuse it (B4.5).
2. **`_primitives/walk_reads.py`.** `read_node` finds the record whose key
   before `::` equals the canonical node name (names are unique per graph,
   R2), and returns a three-way result. It calls `reusable_return_value` for
   the rebuild into the declared type. It never touches a fingerprint (B3).
   `resolve_bound_values` maps it over a binding: `Recorded` → the value;
   anything else → `FromStepUnavailableError` with the contract §3 message.
3. **`_engine/walk_reads.py`.** `step_records(runtime_store, scope_id)` reads
   through the port, the same port call `_from_job_value` makes today.
   `inject_from_step` applies B2/B5/D2: explicit argument wins;
   no scope → error; `Recorded` → inject; `NotCarriable` → live value or
   error; `NotRecorded` → default if declared (D2) else error.
4. **Executor.** One call beside `_inject_from_job` (`executor.py:1456`),
   inside a `try` that turns `FromStepUnavailableError` into
   `_failure_before_execution(...)` (`executor.py:1627`) — the reader is not
   called and no arity error appears. `_from_job_value`'s in-walk branch is
   rewritten to use `step_records` + `read_node` (behaviour-identical;
   `FromJob` suites pin it). Net executor size must not grow: the gate is
   `wc -l` ≤ 2 813.
5. **Validation.** `_validate_workflow_from_step_refs` runs beside the
   `FromJob` check in `validate_workflow_declarations`
   (`workflow_validation.py:184`). It reuses the ancestor computation
   (`descendants` over successors, `:52-66`) — extracted to a small helper
   shared by both checks rather than copied. Readers: every `Step` job of the
   workflow, the workflow function itself (every node is ordered before the
   epilogue, so only B4.1 and B4.5 apply), and every `Tool` binding of every
   `Gate` (ancestors of the gate, excluding the gate). `ChoiceDecision.state`
   is deliberately not checked (non-goal). Module stays < 500 lines.
6. **Tool surfaces.** Both `_resolve_bound` bodies are deleted; `_bound_values`
   in each surface calls `resolve_bound_values(scope["steps"].items(), …)`.
   Their existing `except Exception` already turns the raised error into the
   `tool_unresolvable` response, whose message carries the §3 text.
7. **Docs** (B6), last, against the shipped behaviour.

## Files to change (hit sets of the 3b queries)

| File | Why (query that found it) |
|---|---|
| `src/functualize/_types/from_job.py` | `from_job_refs` filter (`:168-169`); `FromStep` docstring (`:246-282`) |
| `src/functualize/_types/errors.py` | home of `WorkflowDeclarationError`; new error beside it |
| `src/functualize/_types/workflow.py` | `Gate` docstring `:289-291` |
| `src/functualize/_primitives/walk_reads.py` | new |
| `src/functualize/_engine/walk_reads.py` | new |
| `src/functualize/_engine/executor.py` | `_inject_from_job` call `:1456`; `_from_job_value` `:2185-2236` |
| `src/functualize/_engine/workflow_validation.py` | `validate_workflow_declarations` `:184`; ancestor walk `:52-66` |
| `src/functualize/app/_workflow_control.py` | `_resolve_bound` `:836-870`, caller `:892` |
| `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py` | `_resolve_bound` `:439-473`, caller `:508` |
| tests (not gated) | `tests/test_from_job.py`, `tests/primitives/test_walk_reads.py` (new), `tests/engine/test_walk_reads.py` (new), `tests/engine/test_the_walk_on_both_stores.py`, `tests/integration/test_from_step_reads_e2e.py` (new), `tests/integration/test_part_i_remaining_cells.py:285-286`, `tests/plugins/test_gate_tool_narrowing.py:650-675` |
| docs (not gated) | `docs/guides/workflows.md:437-458,495-511`, `contributor/reference/workflow-walker.md:44-50,89,127`, `skills/functualize/references/workflows.md:58,98`, `skills/functualize/references/idiomatic.md:162-166` |

## Risks

- **R1 fingerprint resurrection** — closed by construction (the reader has no
  fingerprint input) and pinned by AC6.
- **R2 name collisions** — settled: duplicate node names are refused
  (`workflow/_validation.py:76-77`, measured).
- **R3 decision path** — untouched; not validated by the new check.
- **R4 jobs invoked from inside a step** — run with `workflow_scope_id` reset
  (`invoke.py:855-866`), so they are *outside a walk*: a `FromStep` parameter
  there fails with the §3 message unless passed explicitly. Pinned in T7.
- **R5 two stores** — the engine path reads through the port, so it is
  store-agnostic; pinned on SQLite in T7. The tool path keeps reading the
  scope document it reads today; no store behaviour changes there.
- **R6 boot breaks a project that has a wrong `FromStep` today** — deliberate
  (spec, *Deliberate behaviour changes*).

## Surviving smells

1. **Duplicate Code — the MCP plugin's gate-tool call path.**
   `WorkflowToolProvider._call_gate_tool` / `_bound_values`
   (`functualize_mcp/_workflow_tools.py`) parallel the core `call_gate_tool` /
   `_bound_values` (`app/_workflow_control.py`). This plan removes the
   duplicated *resolver* they share but leaves the two call paths. Why
   accepted: folding the plugin onto `call_gate_tool` changes the plugin's
   error envelope and its `PluginHost` boundary — a refactor of its own, not
   needed to make `FromStep` truthful. **Needs maintainer review:** yes —
   whether to file it as follow-up work.
2. **Large Class — `JobExecutionEngine` (2 813 lines).** Pre-existing. This
   plan adds no logic to it (one call line and a `try`), and moves the in-walk
   record lookup out, so its line count must not rise (T5 gate). Not
   reduced further here. **Needs maintainer review:** no.

No *Forbidden Pattern* survives: no peer cross-import, no growth of the
executor, no global state, no new port.

## Waves

See `tasks.md`. Summary: W1 vocabulary (refs helper, error, pure reader) →
W2 engine (validation; injection + executor) → W3 tool surfaces → W4
end-to-end and both-stores witnesses → W5 docs.
