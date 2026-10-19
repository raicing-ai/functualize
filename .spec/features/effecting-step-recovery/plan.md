# effecting-step-recovery — plan

**Phase:** Plan approved by the member on 2026-10-19: S-R1 to S-R4 confirmed, Large Class review answered (a), `tasks.md` approved for Execute.
**Baseline:** rebased onto `origin/master` `d1c7e40a`. The lease-heartbeat change has
landed. It moved every walk write behind the runtime-store port, so this plan maps
the **post-heartbeat** engine. `spec.md` line citations that predate it are
re-pointed below where they matter.

## Alignment

- **Shape:** *Shape Intent — Effecting Steps Across a Crash*, Confluence SD/15007820,
  `Authority: Approved` (v9, 2026-10-13). Decisions of record: D1 = A (attempt record
  before the call; resume on `attempting` stops in doubt), D2 = 2a′ (a declared
  recovery gate implied by `effecting=True`), D3 = 3a (reconciler deferred), D4 = 4a
  (no in-step marker), D5 = 5a (a raise stays `failed`).
- **Spec confirmations** (MCH-175, 2026-10-17): Q-1 the gate is named
  `<step>-in-doubt`; Q-2 the answer is `{"outcome": "ran" | "did_not_run", "value"?}`
  with no default.
- **Surfaces in scope**, in the shape's words: "`Step(effecting=True)` in a workflow
  walk: the attempt record, the `in_doubt` state, and how a resume stops on it"; "One
  way to resolve an `in_doubt` step (D2)"; "Correcting the `effecting` docstrings";
  "Extending `test_crash_and_resume.py` into the effect-before-record window".
- **Surfaces out of scope**, in the shape's words: "Lineage, discovery and the wider
  pending-work model"; "Distributed claiming"; "The notification outbox's own
  semantics"; "Idempotency keys *supplied by users*"; "`AgentStep`".

## Retrieval, as run

| Pass | Tool | Notes |
|---|---|---|
| Prose | `zg` 0.2.2 (`/usr/local/bin/zg`), index built in this worktree (13 681 entities, 1 m 43 s) | `08-durable-runs.md` §B/§E, `runtime-persistence-data-model.md` §2.4/§4, `workflow-walker.md` §4, `codemaps/data-flow.md` §8 |
| Symbols | serena, activated by absolute worktree path | `WorkflowDeclaration.node` (1 production caller), `StepView` (3 readers + 1 port), `GateService` surface |
| Direction | graphify `get_neighbors` | `graphify-out/graph.json` was built at `2269b8d3`, **69 commits behind HEAD**, and still shows the walker holding `ScopeStore`. Used only for the direction of dependencies, and every edge was re-checked in code |
| Codemaps | `contributor/architecture/codemaps/data-flow.md` §8 | Matches the code: the walk writes only through the port. No finding |
| Skills | `python-design-patterns` (in-repo), `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue) | Smell names below come from the latter |

## BEFORE

Layers: foundation `_types/`, `_primitives/` · peer `_engine/` · public `app/`,
`workflow/` · plugin `functualize-substrate-sqlite`. An arrow `A ──► B` means A imports
or calls B.

```
 public                     peer layer _engine/                                  foundation
 ───────                    ───────────────────                                  ──────────
 workflow/_validation.py ─────────────────────────────────────────────────────► _types/workflow.py
   (duplicate names)                                                              Step(effecting)  ◄─ flag declared
                                                                                  WorkflowDeclaration.node/gates/shape
                            workflow_orchestrator.py                              WorkflowShape.to_dict ─► graph digest
                              run_step(name) ─► engine.run(job)  (Deps, inv() run inside)
                                   ▲
                            workflow_walker.py  WorkflowWalker (767-line class)
                              _service_step:
                                record = walk.step(key)
                                if status ∈ TERMINAL_SUCCESS → replay
                                run_step(name)  ◄────────── crash window: no record exists
                                _advance → walk.complete(...)
                              _service_gate ─► gate_service.py GateService.service
                                                 ladder = _gate_strategy_list (prompt→resolve)
                                                 _open(position = gate name)
                                   │
                                   ▼
                            frontier.py  FrontierWalk (578-line class)
                              complete → CompleteStep(effecting=is_effecting) ─┐   _types/persistence.py
                              record   → RecordStep                            ├─► CompleteStep / RecordStep /
                              open_request → SuspendAtGate                     │   StepView / SuspendAtGate
                              claim → _step_that_went_silent → timed_out       │   (port vocabulary)
                                                                               ▼
 app/_workflow_answer.py ──► declaration.node(gate) ─► model           _primitives/document_store.py
   _walk_has_passed/_downstream_of (declared edges)                      _primitives/gate_requests.py
                                                                          (reuses a CONSUMED request)
                                                                         sqlite plugin _workflow_sql.py
                                                                          (reuses only open/accepted)
```

**Smells the BEFORE already carries** (catalogue names):

| Smell | Where | Note |
|---|---|---|
| **Speculative Generality** | `GraphModel.is_effecting` (`frontier.py:99`), and `effecting` on `CompleteStep` / `RecordStep` / `StepView` | A field threaded through the whole port, written and never read |
| **Comments** (as a smell: the comment says something the code does not do) | `Step.effecting` docstring (`_types/workflow.py:131-151`), `is_effecting` docstring | Promises exactly-once |
| **Large Class** | `WorkflowWalker`: 767 lines (`workflow_walker.py` 264–1031). `FrontierWalk`: 578 lines (`frontier.py` 177–755) | Both are already past the constitution's ~500 LOC threshold **before** this change |
| **Switch Statements** | `_gate_strategy_list` (`gate_service.py:46-65`), an if-chain on strategy strings | Pre-existing |
| *Divergent port semantics* (no catalogue name, so it is described plainly) | The document backend reuses a **consumed** gate request (`gate_requests.py:163`); SQLite reuses only `open`/`accepted` (`_workflow_sql.py:353`) | Not visible today, because `GateService` replays before it ever opens. It becomes visible the first time a gate must ask the same question twice |

## AFTER

```
 public                     peer layer _engine/                                  foundation
 ───────                    ───────────────────                                  ──────────
 workflow/_validation.py ──────────────── refuses a node named <step>-in-doubt ► _types/workflow.py
                                                                                  recovery_gate_name(step)
                            workflow_validation.py (boot)                         InDoubt (pydantic model)
                              refuses effecting=True on a workflow job            WorkflowDeclaration:
                                                                                    recovery_gate(step) / recovered_step(gate)
                            effect_recovery.py  EffectRecovery  ◄── NEW             node() and gates() include recovery gates
                              begin(walk, key, attempt)  → RecordStep(attempting)   shape(): step {"effecting": true},
                              verdict(walk, key, gate, …) → Ran | DidNotRun |              gate {"recovers": step}
                                                            WalkReport(blocked)
                                  │ asks via GateAsk          ▲
                                  ▼                           │ delegates (≈ +12 lines)
                            gate_service.py GateService.service(node, …, ask=GateAsk)
                              GateAsk(position, prompt, ladder, supersedes)  ◄── parameter object
                              default GateAsk() = today's behaviour
                            workflow_walker.py  WorkflowWalker._service_step
                              ─► EffectRecovery for effecting / doubting steps; otherwise as BEFORE
                              StepBlocked on an effecting step ─► record "blocked"
                                   │
                                   ▼
                            frontier.py  FrontierWalk (keyword pass-through only)
                              StepStatus += attempting, in_doubt, blocked (none in TERMINAL_SUCCESS)
                              record / complete carry attempt, started_at, effecting
                              open_request carries supersedes
                                   │                                              _types/persistence.py
                                   └──────────────────────────────────────────────► RecordStep/CompleteStep/StepView
                                                                                      += attempt, started_at
                                                                                    SuspendAtGate += supersedes
 app/_workflow_answer.py ──► declaration.node(gate)      _primitives/document_store.py  (+ keys only when set)
   _downstream_of(recovery gate) = {step} ∪ downstream   _primitives/gate_requests.py   (supersedes → archive)
                                                         sqlite plugin: migration 0003 (attempt), writer, reader
                                                         testing/conformance/baseline.py: both backends agree
```

**Boundary check.** Every new arrow points down a layer. `_engine` → `_types` and
`_primitives`, `app` → `_types`, and the plugin → `functualize.plugin` (the public
port re-exports) are all legal under the seven contracts. `EffectRecovery` imports
only `_types` and its siblings in `_engine`. No peer-layer import is added.
`uv run lint-imports` is part of each task's gate.

### Candidate AFTERs considered, and the smells each would have introduced

| Candidate | Rejected because |
|---|---|
| Put the attempt/doubt logic inline in `WorkflowWalker._service_step` | **Large Class** growth on a class already at 767 lines: a forbidden pattern (`.spec/CONSTITUTION.md` → *Forbidden Patterns*) |
| Synthesize recovery `Gate`s into `WorkflowDeclaration.nodes` | Every consumer of `.nodes` would see unreachable nodes: `_build_predecessors`, `workflow_validation.py:55`, `agent_step.py:203`, the graph model. That is **Shotgun Surgery** on readers that never asked. Lookup through `node()` / `gates()` / `shape()` reaches the three readers that need it |
| A `RecoveryGate(Gate)` subclass carrying `recovers` | **Refused Bequest** (it must refuse `decide`, `tools` and `strategy`), plus `isinstance` **Switch Statements** in `gate_service` and the answer path. Replaced by the declaration's `recovered_step()` mapping and the `GateAsk` parameter object |
| More keyword arguments on `GateService.service` (position, prompt, ladder, supersedes) | **Long Parameter List**. Applied *Introduce Parameter Object* (`GateAsk`) instead, whose default reproduces today's behaviour exactly |
| One request key per doubt (`refund-in-doubt@a2`) | **Primitive Obsession** on the gate key, and it breaks Q-1's public address. Replaced by `SuspendAtGate.supersedes` |
| Make `reclaim` write `in_doubt` | Unnecessary. `_step_that_went_silent` already leaves a step that has a record alone (`frontier.py:252-284`), so an `attempting` record is never overwritten with `timed_out`. The next walk records the doubt. Spec revision S-R1 |

## Spec revisions forced by the architecture pass (re-confirmation needed)

| # | Change | Why |
|---|---|---|
| **S-R1** | `reclaim` leaves `attempting` untouched. The walk that next reaches the step records `in_doubt`. AC-6 is unchanged in what it observes (reclaimed then resumed: `in_doubt`, never `timed_out`, job not run) | No takeover code change is needed: the record already suppresses `timed_out` |
| **S-R2** | The stored attempt fields are `attempt`, `started_at` and `effecting`. `attempt_key` is **derived** as `"<scope_id>:<step_key>:<attempt>"`, not stored. `generation` is not stored | Every write is already fenced by generation. A derivable key needs no migration later. This keeps the port delta to two fields, following the precedent of `effecting` (migration `0002`) |
| **S-R3** | An effecting step whose run ends `BLOCKED` (a guard block, `executor.py:2282`, or a nested gate) records the new step status **`blocked`**. This is an ending, not doubt. A resume re-runs it as today | B1 required "every way the attempt ends replaces `attempting`". `StepBlocked` today writes no step record (`walker._service_step` → `walk.move`) |
| **S-R4** | One answer per **doubt**, not only per loop pass. An answer given for attempt *n* never resolves the doubt of attempt *n+1*. The recovery request carries `prompt = {"step", "attempt", "iteration", "started_at"}`, and a stale consumed request is superseded, not replayed | Without it, `did_not_run` followed by a second crash would replay `did_not_run` and re-run silently. The document backend reuses consumed requests (BEFORE smell 5) |

## Technical approach

1. **Types (foundation).** `persistence.py` gains two fields and one field, each
   defaulting so that every existing construction site is unchanged.
   `workflow.py` gains `recovery_gate_name()`, the `InDoubt` model
   (`outcome: Literal["ran", "did_not_run"]` required, `value: Any = None`, `extra="forbid"`),
   and declaration lookups. The shape projects `"effecting": true` and the recovery
   gate **only when declared** (the `decision` precedent, `_types/workflow.py:780-783`),
   so pure graphs stay byte-identical.
2. **Backends.** The document store writes `attempt` / `started_at` keys only when
   set. `gate_requests.open_request(supersedes=…)` archives the consumed record onto
   the gate's existing `superseded` history (the reopen mechanism,
   `gate_requests.py:276-306`) and opens a new one. SQLite adds migration `0003`
   (`attempt INTEGER NOT NULL DEFAULT 0`; `started_at` already exists in `0001`),
   writes both, and reads both. `supersedes` needs no SQL change, because a new row is
   already the latest (`_readers.py:264`), but it is verified by conformance.
3. **Engine.** `EffectRecovery` owns the policy. `begin` writes the attempt.
   `verdict` (on `attempting` / `in_doubt`) records `in_doubt` and asks the recovery
   gate through `GateService` with
   `GateAsk(position=<step>, prompt={…}, ladder=["prompt"] if prompt_gates else None, supersedes=<stale id>)`.
   It returns `Ran(value, reusable)` / `DidNotRun` / the blocked report.
   `WorkflowWalker._service_step` delegates, and `_NodeRun` carries a `reusable`
   override so that `ran` without a value completes as not reusable.
4. **Answer path.** `_downstream_of(recovery gate)` = `{step} ∪ _downstream_of(step)`,
   so `--reopen` after the walk has moved past the step is refused like any gate.
   Answer validation already works through `declaration.node()`.
5. **Boot.** `validate_workflow_declarations` refuses `effecting=True` on a step
   whose registered function carries `__functualize_workflow__`.

## Files (the hit sets in `tasks.md`)

`_types/persistence.py`, `_types/workflow.py`, `workflow/_validation.py`,
`_engine/recording/input_recorder.py`, `_primitives/cache_format.py`,
`_primitives/document_store.py`, `_primitives/gate_requests.py`,
`plugins/substrates/functualize-substrate-sqlite/…/{_schema/0003_step_attempt.sql,_workflow_sql.py,_readers.py}`,
`testing/conformance/baseline.py`, `_engine/frontier.py`, `_engine/gate_service.py`,
`_engine/effect_recovery.py` (new), `_engine/workflow_walker.py`,
`_engine/workflow_validation.py`, `app/_workflow_answer.py`,
`docs/guides/workflows.md`, `docs/cli/workflow.md`, `CHANGELOG.md`, plus tests.

## Risks

| Risk | Mitigation |
|---|---|
| An exit path leaves `attempting` behind, so a *normal* run strands a doubt | AC-5 has one test per exit, each sabotage-checked (break the overwrite, watch it go red) |
| The heartbeat thread renews during the attempt and the attempt write races it | Both are fenced writes through the port under one generation. The attempt is one `RecordStep` unit, like `timed_out` today |
| The digest changes for effecting workflows, so parked scopes refuse once | Expected (AC-10, pre-1.0). `CHANGELOG.md` states it |
| The two backends drift on `supersedes` | Conformance case in T6, run against both (`tests/conformance/test_baseline.py`) |
| The notification gap (shape Risk 7) | Out of scope, recorded in `spec.md` *Known limitation* |

## Surviving smells

| Smell | Where | Why accepted | Needs maintainer review |
|---|---|---|---|
| **Large Class** (pre-existing, slightly grown) | `WorkflowWalker` (767 lines), `FrontierWalk` (578 lines) | Both are past the ~500 LOC forbidden-pattern threshold **before** this change. The plan adds no responsibility to either: the walker gains a delegation of about 12 lines, and the frontier gains keyword pass-through. The policy lives in the new `EffectRecovery`. Task gates cap the growth (T8 ≤ +15 lines for `FrontierWalk`, T9 ≤ +15 lines for `WorkflowWalker`, measured on the class spans). Splitting either class is not in this feature's scope | **Reviewed 2026-10-19: accepted, option (a).** The growth caps hold, and a separate extraction lane for `WorkflowWalker` is to be opened later |
| **Shotgun Surgery** (bounded) | Adding `attempt` / `started_at` touches the port type, the document backend, the SQLite writer, reader and migration, and conformance: 5 places | Inherent to one port with two backends, and the exact precedent `effecting` set (migration `0002`). Conformance keeps them in agreement | No |
| **Switch Statements** (pre-existing, unchanged) | `_gate_strategy_list` | The recovery gate's ladder is passed in through `GateAsk`. No new branch is added to the chain | No |
