# from-step-walk-reads

`FromStep("x")` reads **this walk's** recorded value for **any** node `x` of
the workflow — a step's result or a gate's answer — wherever it is written: a
`Tool(...)` binding on a gate, a step job's parameter annotation, or the
workflow's epilogue body. It never runs anything, never reads a value from
another run, and a reference that cannot be satisfied fails with an error that
names `FromStep`, the node and the parameter — never with a silent default and
never with a Python arity error.

Shape: *Shape Intent — FromStep Resolution Across a Walk (one rule
everywhere: step, gate, epilogue)*, Confluence SD page 16777218, version 3,
`Authority: Approved` (read live 2026-10-13). The chosen model is the page's
option (i). This spec is the behaviour that option promises; where the page's
own experiment disagrees with option (i), the disagreement is stated in
§ *Decisions*, settled by the maintainer and recorded there.

Words used below:

- **walk** — one run of a `@workflow` graph, identified by its scope id. A walk
  can stop at a gate and be resumed later, in another process.
- **node** — an entry of the graph: a `Step`, a `Gate`, or an `AgentStep`.
  Node names are unique within one graph.
- **epilogue** — the decorated workflow function's own body. It runs once,
  after the walk reaches `END`.
- **ordered before** — node `a` is ordered before reader `r` when `a` is an
  ancestor of `r` in the graph: some path of edges leads from `a` to `r`. This
  is the relation `FromJob` validation already uses
  (`src/functualize/_engine/workflow_validation.py:25-38`). Every node is
  ordered before the epilogue. Being ordered before does not guarantee having
  run: a conditional edge may take another branch (B5).

## The defect

All measurements below are from throwaway probes run against `master` at
`c03dfb72`, during authoring (see `research.md` for the probe and its full
output).

1. **The epilogue reads nothing, silently.** A one-step walk
   `Step(plan) → END` whose epilogue declares
   `seen: Annotated[str, FromStep("plan")] = "MISSING"` succeeds and returns
   `'MISSING'`. The same epilogue with `FromJob("plan")` returns `'PLAN-1'`.
2. **A step after a gate cannot read the gate's answer.** With
   `Step(plan) → Gate("approve", awaits=Approval) → Step(act)` and
   `act(ok: Annotated[Approval, FromStep("approve")])`: boot blocks at the gate
   (correct); the answer `{"ok": true}` is accepted; the resume fails and `act`
   is never entered. The step record for `act` is `failed`. The answer **is**
   recorded — both on the gate's request and as the gate node's own step record
   `approve::` with `return_value = {"ok": True}`.
3. **A job run outside any walk** with that same parameter fails with
   `act() missing 1 required positional argument: 'ok'` — an error that names
   Python, not the missing reader.
4. **A name that is not a node of the graph is never checked.** A step
   declaring `Annotated[str, FromStep("nope")] = "DEF"` runs and receives
   `"DEF"`; the walk succeeds.
5. **`FromJob` cannot name a gate at all.** `FromJob("approve")` on the step
   after the gate is refused at boot with
   `WorkflowDeclarationError: Workflow 'gwf' has a Step referencing unknown job 'approve'.`
   This is correct and stays (a gate is not a job).

What already works and must keep working:

- `Tool(read_file, allowed=FromStep("setup-vfs"))` on a gate resolves to the
  walk's recorded result for `setup-vfs`. Measured: the same resolver also
  resolves a *gate* name today — `FromStep("approve")` in a binding returned
  `{'ok': True}` after the gate was answered.
- `FromJob` everywhere, unchanged (see § *Non-goals*).

Cause, in one sentence: `FromStep` is not a declared read. The only walk over
parameter annotations (`from_job_refs`, `src/functualize/_types/from_job.py:152-171`)
keeps `FromJob` metadata only (`:168-169`), so boot validation, ordering and
injection never see a `FromStep` annotation; the one place that does read
`FromStep` — the tool-binding resolver — works on a different path.

## User stories

- **US1 — approval workflow.** As a workflow author, I model *plan → a person
  approves → apply what was approved* as three nodes, and the apply step
  receives the approval as a typed value after the walk is resumed — even
  when the resume happens days later in a new process.
- **US2 — epilogue summary.** As a workflow author, I read a step's result or a
  gate's answer in the epilogue body by annotating a parameter, exactly as the
  `FromStep` and `Gate` docstrings already promise.
- **US3 — mistakes are loud and early.** As a workflow author, a misspelled
  node name, or a read of a node that comes later in the graph, is refused when
  the application boots — before any walk starts or any person is asked to
  approve anything — with a message naming `FromStep`, the node, the parameter
  and the workflow.
- **US4 — no foreign values.** As an operator, a `FromStep` read can never
  hand a step a value produced by a different run, a different workflow, or an
  earlier attempt — only this walk's own record.

## Behaviour

### B1 — where a `FromStep` reference may be written

A `FromStep("x")` reference is honoured in exactly three positions, all with
the same meaning:

| Position | Example |
|---|---|
| A gate tool's binding | `Gate(..., tools=[Tool(read_file, allowed=FromStep("setup-vfs"))])` |
| A parameter of a job used as a `Step` | `def act(ok: Annotated[Approval, FromStep("approve")]) -> ...` |
| A parameter of the workflow function (the epilogue) | `def flow(ok: Annotated[Approval, FromStep("approve")]) -> ...` |

`x` may be given by name or by the decorated function, as today; both
normalise to the node's canonical (hyphenated) name.

### B2 — what a read returns

- Naming a **step** (or an `AgentStep`): that step's recorded result in this
  walk.
- Naming a **gate**: the answer the gate accepted in this walk — the same value
  the walk itself uses when it replays past that gate.
- The value is rebuilt into the parameter's declared type, as `FromJob` does
  today: `Annotated[Approval, FromStep("approve")]` receives an `Approval`
  instance, not a `dict`. In a `Tool` binding (no declared type) the recorded
  value is passed as recorded, as today.
- If the recorded value could not be persisted (a live handle), the value the
  walk still holds in this process is used, as `FromJob` does today. If the
  walk is resumed in a new process and that value is gone, the read fails
  (B5).
- A caller that passes the argument explicitly always wins: an explicitly
  supplied value is never replaced by a read.

### B3 — a read never causes work and never leaves this walk

- Resolving a `FromStep` reference never runs a step, never opens or answers a
  gate, and never adds a dependency edge.
- It never reads a fingerprint (the cache of a job's last result across runs),
  and never reads another scope's record. Of two walks of the same workflow,
  each reads only its own records.
- A `FromStep` parameter contributes nothing to the dependency pass that runs
  before a job: a job whose only upstream reference is `FromStep` has no
  dependencies from it.

### B4 — boot validation (before any walk starts)

When the application validates workflow declarations at boot, every
`FromStep` reference in every position of B1 is checked against the graph that
contains it. Each of these is a `WorkflowDeclarationError`, raised at boot,
whose message names `FromStep`, the referenced name, the parameter (or tool
argument), the reader, and the workflow:

1. The name is not a node of that workflow's graph.
2. The reader is a step, and the named node is not ordered before it (it is
   the step itself, comes after it, or is on no path into it).
3. The reader is a gate's tool binding, and the named node is not ordered
   before that gate — including the gate itself, whose answer cannot exist
   while its tools are being called.
4. A job used as a step in **several** workflows is checked against each of
   them; a reference valid in one workflow and invalid in another is refused
   for the invalid one.
5. A parameter carrying both a `FromJob` and a `FromStep` reference is refused:
   one parameter has one source.

These checks see annotations written under
`from __future__ import annotations` exactly as without it
(`contributor/reference/pitfalls.md` §4).

### B5 — failures at run time

A reference that passed boot validation can still be unsatisfiable in one
particular walk. In each case the reader is **not** called and the walk
records a failure whose message names `FromStep`, the node, the parameter and
the scope — never a Python arity error, and never a silently substituted
value except as § *Decisions* D2 allows:

- the named node is ordered before the reader but did not run in this walk
  (a conditional edge took another branch);
- its recorded value cannot be carried and is not held in this process (B2);
- the job is executed **outside any walk** (run directly, or as a dependency of
  a non-workflow job) and the caller did not pass the argument explicitly.

### B6 — documentation tells the truth

After the change, every statement about `FromStep` in the repository agrees with
B1–B5: the `FromStep` and `Gate` docstrings, `docs/guides/workflows.md`
(including a worked "read a gate's answer" example under *Getting values into a
step*), `contributor/reference/workflow-walker.md`, and the bundled
`skills/functualize/references/{workflows,idiomatic}.md`. The `FromStep`
docstring's contrast table says "this walk's nodes", not "this scope's steps
only". The walker reference's row that says `FromStep` injection "implies a
dependency edge … otherwise run upstream" is corrected.

## Acceptance criteria

Each is an executable gate; `plan.md` names the test that carries it. "Today"
is `master` at `c03dfb72`.

| # | Given / when | Then | Today |
|---|---|---|---|
| AC1 | `Step(plan) → Gate("approve", awaits=Approval) → Step(act)`, `act` and the epilogue both declare `Annotated[Approval, FromStep("approve")]`; first execution | `RunStatus.BLOCKED` at `approve`; no arity error anywhere | passes |
| AC2 | AC1's walk, answered and advanced through the CLI **in a fresh process** (`func builtin workflow resume <scope> --input '{"ok": true}'`) — the parked-for-days case, not the same-process path | `act` is entered once with `Approval(ok=True)`; the epilogue receives an equal `Approval`; walk status `success` | fails |
| AC3 | One-step walk, epilogue `Annotated[str, FromStep("plan")] = "MISSING"` | returns the step's value, not `"MISSING"` | fails |
| AC4 | A step reads `FromStep("nope")` (not a node) | boot raises `WorkflowDeclarationError` naming `FromStep`, `nope`, the parameter and the workflow; no walk starts | fails (silent default) |
| AC5 | A step reads a node that comes after it; a gate binding reads its own gate | each refused at boot (B4.2, B4.3) | fails |
| AC6 | Two walks of one workflow; the first ran `plan`, the second is parked before `plan`; a fingerprint record for `plan` exists | a `FromStep("plan")` read in the second walk never yields the first walk's value or the fingerprint's (B3) | not measured |
| AC7 | The `act` job run directly, outside any walk, without the argument | fails with the B5 message naming `FromStep`; not `missing 1 required positional argument` | fails |
| AC8 | `Tool(read_file, allowed=FromStep("setup-vfs"))` with `setup-vfs` a prior step; and with a prior **gate** | resolves to the step's result / the gate's answer, on both the in-core and MCP tool surfaces | passes |
| AC9 | A conditional walk where the read node is on the branch not taken | with a declared default the reader gets the default; without one, the B5 failure (D2) | not measured |
| AC10 | A depositing answer for a node that is a step (`deposit … gate="act"`) | refused (`GateNotFoundError`) — unchanged | passes |
| AC11 | AC1–AC5 with the fixture module compiled with and without `from __future__ import annotations` | identical outcomes | n/a |
| AC12 | `FromJob` behaviour suites (`tests/test_from_job.py`, the workflow-as-job, dependency and fingerprint suites) | unchanged, green | passes |
| AC13 | The documentation surfaces named in B6 | contain no statement contradicting B1–B5 (checked by `rg` for the old phrases) | fails |

AC1, AC2 and AC3 are the shape page's experiment steps 1–3; AC10 is its step 4
(measured: already refused); AC4 is its step 6. The page's step 5 is superseded by D1.

## Non-goals

- **`FromJob` does not change.** It may still run its node, still reads
  fingerprints, still forms a dependency edge, and still cannot name a gate.
- **The subscript form** `FromStep[x]` / `FromJob[x]` is not built
  (`contributor/reference/workflow-walker.md:44-50`); `FromJob.__class_getitem__`
  keeps refusing it.
- **The decision path is not changed.** `ChoiceDecision(state=FromStep(...))`
  keeps its own resolver (`src/functualize/_gate/decision_strategy.py:71-77`);
  this feature adds no check there and claims none (see `research.md` R3).
- **No new persistence, no new gate lifecycle, no new node kind.** Everything a
  read needs is already recorded (`research.md` H1).
- **The epilogue is not added to graph ordering.**
- **No new public name.** `FromStep` is already exported from
  `functualize.workflow`; its constructor does not change.

## Deliberate behaviour changes

- A `FromStep` reference that today is silently ignored (epilogue, step
  parameter) starts working — and one that names something invalid starts
  failing at boot. A project carrying such an annotation today, with a default,
  will fail to boot after upgrading if the name is wrong; that is the point.
- A `Tool` binding whose `FromStep` names a node that did not run in this walk
  currently receives `None`. Two tests pin that, both on the MCP surface:
  `tests/integration/test_part_i_remaining_cells.py:285-286` and
  `tests/plugins/test_gate_tool_narrowing.py:661-669`. Under B5 and D2 it fails
  with the named error instead; both assertions change deliberately.

## Decisions (settled 2026-10-13)

The maintainer confirmed this spec and settled both open decisions in one
answer (issue comment `01a136fd-9871-73a2-8afe-7cdcefbb417f`,
2026-10-13T20:39:11Z, verbatim: *"Confirm, D-1 allow it, D-2 (b)"*). Both
**supersede** the shape page's experiment steps 5 and 6, which say the
opposite; `plan.md` → *Alignment* records the supersession.

- **D1 — a gate tool binding may name an earlier gate.**
  `Tool(read_file, allowed=FromStep("approve"))` resolves to the answer of an
  `approve` gate ordered before the binding's gate. A binding naming its own
  gate, or a node not ordered before its gate, is refused at boot (B4.3).
- **D2 — a node a conditional branch skipped yields the parameter's declared
  default; with no default the read fails (B5).** Only the
  "ordered before but did not run in this walk" case falls back. Every boot
  error (B4) fails regardless of a default, and so do the other two B5 cases
  (value not carriable; outside a walk). In a `Tool` binding there is no
  default, so a skipped node always fails.

## Out of scope, recorded

- Two readers of a step record exist today; `plan.md` settles that the
  feature replaces them with one (architecture gate).
