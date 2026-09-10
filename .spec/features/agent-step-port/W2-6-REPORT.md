# W2–6 report — `agent-step-port`, waves 2 to 6 (T3, T4, T5, T6, T7)

Worktree `agent-f6-agent-step-w2`, branch `agent/f6-agent-step-w2`.
**No git command was run** (per the shared rules). Every undo — including every
sabotage restore — was an edit of the file, verified by `md5sum` against a copy
kept in `/tmp/f6-backup/`.

Waves 0–1 were already on the branch. `tasks.md` checkboxes are **not** flipped:
that file is not in my brief and the orchestrator owns it (requested at the end).

## Retrieval — verified before starting

```
$ ls graphify-out/graph.json .serena/project.yml && du -sh .zvec-grep
.serena/project.yml
graphify-out/graph.json
74M	.zvec-grep
```

All three present. `graphify` (committed graph) and `serena` (`.serena/project.yml`)
were used for the "who consumes `WorkflowShape`/`step_refs`" questions;
`zvec-grep` reads prose, so it is what found `contributor/architecture/run-model/09-agent-step-port.md`
(§C, the ADR-014 shape AC-11 comes from) and `wiring-discipline.md` §5.

### Environment: this worktree's venv was under-synced (pre-existing, fixed)

`tests/` collected with **48 errors** on arrival — `functualize_mcp`,
`functualize_http`, `functualize_ai` and others were not installed, which is
*every* `tests/plugins/*` module plus `tests/workflow/test_workflow_surface_parity.py`:

```
$ uv run pytest tests/ -q --no-header --collect-only | tail -2
10593 tests collected, 48 errors in 23.16s
```

`uv sync --all-packages --all-extras` restored the intended environment:

```
$ uv run pytest tests/ -q --no-header --collect-only | tail -1
11364 tests collected in 11.04s
```

No source change was involved — the same gap would have made the mandatory
full-suite run meaningless (and would have hidden real failures behind a
collection error). Both syncs also fixed the 6 `mypy` errors in
`_cli/tui/functualize_autocomplete.py` that came from `textual-autocomplete`
being absent.

---

## T3 · `AgentStep`, `_NODE_TYPES`, and the validation refusals

### What changed

| File | Lines | Change |
|---|---|---|
| `src/functualize/_types/workflow.py` | 614 → **766** (+152) | `AgentStep` (frozen dataclass, 6 fields, validated `__post_init__`), `IMPLIED_CAPABILITIES` + `implied_capabilities()`, `_node_kind()`, `WorkflowDeclaration` widened to `Step \| Gate \| AgentStep`, `WorkflowNodeShape.kind` gains `"agent"`, `to_dict`/`from_dict` round-trip `{"agent": name}`, module docstring "Two node kinds" → three |
| `src/functualize/_engine/agent_step.py` | **new, 262** | `AgentStepRegistry` (register/names/resolve/check/execute) — the refusals, and (T5) `CliPromptExecutor` |
| `src/functualize/_engine/workflow_runner.py` | 160 → **204** (+44) | `agent_step_registry` + `request` arguments; `_run_agent_step`; the refusal call at the top of `prelude` |
| `src/functualize/_engine/executor.py` | 2682 → **2686** (+4) | `agent_step_registry` constructor argument + attribute; passed to the runner |
| `src/functualize/_app/boot.py` | 1793 → **1827** (+34) | registry built beside `_gate_registry` (both boot paths), passed to the engine (both paths), core executor registered (T5) |
| `src/functualize/workflow/__init__.py` | +3 | `AgentStep` public re-export |
| `src/functualize/workflow/_validation.py` | 61 → **89** (+28) | `_NODE_TYPES = (Step, Gate, AgentStep)`, widened signatures, docstring split (decoration-time vs boot-time) |
| `src/functualize/workflow/_decorator.py` | 57 → **61** (+4) | `@workflow(steps=…)` accepts `AgentStep` |
| `tests/workflow/test_agent_step_refusals.py` | **new, 549** | T3 + T6 (+1 AC-1 test) |
| `tests/test_public_api_surface.py` | +3 | `AgentStep` in `functualize.workflow`'s expected exports |

**Files outside the brief's list, and why** (the brief's `**Files:**` lines for T3
name only `workflow/__init__.py`, `workflow/_validation.py` and the test):

- `_types/workflow.py` — unavoidable. The lint-imports contract *Internal never
  imports public* forbids `_engine`/`_discovery` from importing
  `functualize.workflow`, so a node kind that boot, discovery and the walker all
  read has to live beside `Step`/`Gate`. (`functualize.workflow` only
  re-exports it.)
- `_engine/agent_step.py`, `_engine/workflow_runner.py`,
  `_engine/executor.py`, `_app/boot.py` — the refusal cannot be decided from the
  declaration alone: it needs the live executor registry, which lives on the app.
  These are the wiring files for that.
- `workflow/_decorator.py` — `@workflow(steps=…)` was typed `Sequence[Step | Gate]`
  and rejected `AgentStep` at type-check time (Pyright flagged it on the T5 test).
- `tests/test_public_api_surface.py` — the door-contract test; W1 did the same
  for the plugin door.

### The design decisions this task made

**Where the refusal fires.** `WorkflowRunner.prelude`, immediately after the
cancelled-scope check and **before** `FrontierWalk.start` writes anything. That
method's own docstring already argues the case: *"this is the one point every
continuation passes through — the CLI, the MCP tools and the `--wf-*` flags all
reach a walk by constructing a runner and calling this"*. Two consequences fall
out for free:

- *Never a node-level refusal* (risk R-b): refusing halfway through a walk is
  worse than not starting, and `prelude` is upstream of every node.
- *Zero step records* is structural, not asserted-into-existence: the store is
  untouched at the moment of refusal (T3's test asserts `get_scope(...) is None`,
  with an ordinary `Step` placed *before* the agent step so a node-level check
  would have run it).

The alternative — threading executors into
`validate_workflow_declarations` — was rejected for a specific reason:
`JobExecutionEngine._validate_workflows_once` memoizes on
`(len(self._registered_jobs), id(self._job_graph))`. Executor registration does
not move that token, so a workflow validated once could be re-walked with a
different executor set and never re-checked — a guard that silently stops
firing. `prelude` runs per invocation and cannot go stale.

**`executor=None` means "the only registered executor", or it is refused.**
`contracts.md` §2 says *"None = the single registered one, else by name"*. Two
registered executors and a step naming none is a refusal
(`AgentExecutorUnavailableError` with `registered=(...)`), not a preference
order: nothing is guessed. Consequence worth stating plainly, since it is a
sharp edge: with core's `cli-prompt` registered, a step that names `None` in a
project that also installs `functualize-ai` resolves to neither — the author has
to name the executor. That is the literal contract and the safe direction.

**The implied capability is folded into `requires` at construction.** Declaring
`tools=[…]` implies `enforces_tool_allowlist`; declaring `time_budget_s` implies
`preserves_active_time_budget`. Folding rather than deriving at the check site
means anything reading `step.requires` gets the set the engine will check, so the
implication cannot be missed by reading the declaration (risk R-c).

**The two boot paths.** `boot_static` and `boot_standard` each build
`app._agent_step_registry` and pass it to `JobExecutionEngine`. This is the
"two entry points" hazard `surface-boundary.md` names, and it is why the
executor is registered by a *call* in both paths rather than by a class
attribute.

### Gates

**Gate — the node vocabulary is open**
```bash
rg -n '_NODE_TYPES = ' src/functualize/workflow/_validation.py
```
before (`28: _NODE_TYPES = (Step, Gate)`), after:

```
29:_NODE_TYPES = (Step, Gate, AgentStep)
```

**Gate — the hint returns an empty string for a core name** (AC-8, W1's table)
```bash
uv run python -c "from functualize._engine.agent_providers import missing_executor_hint as h; print(repr(h('cli-prompt')), repr(h('ai')))"
```
```
''  'install functualize-ai to register it'
```

### Falsifiers the task did not choose (different spelling, same question)

A count of one spelling is not the answer. Two independent ways of asking "can
an `AgentStep` reach the walk?", neither of them a grep (script:
`/tmp/f6-falsify-t3.py`):

```
$ uv run python /tmp/f6-falsify-t3.py
AST: ('Step', 'Gate', 'AgentStep')
decorated ok; entry= 'draft-migration' kind= agent
```

The first line resolves the bound tuple from the AST rather than from the source
text; the second decorates a graph whose `AgentStep` arrives through a
module-level alias, so the decoration path is exercised instead of the type name.

### Sabotage (T3)

The refusal call deleted from `prelude` (six tests must notice):

```
$ uv run pytest tests/workflow/test_agent_step_refusals.py -q
6 failed, 10 passed in 0.55s
FAILED ...::TestAnExecutorThatCannotHonourTheStepIsRefused::test_tools_against_an_executor_with_no_capabilities - Failed: DID NOT RAISE <class '...AgentCapabilityRefusedError'>
FAILED ...::TestAnExecutorThatCannotHonourTheStepIsRefused::test_a_budget_against_an_executor_that_cannot_preserve_it - Failed: DID NOT RAISE <class '...AgentCapabilityRefusedError'>
FAILED ...::TestAStepWithNoExecutorIsRefused::test_a_named_executor_nobody_registered_names_its_package - Failed: DID NOT RAISE <class '...AgentExecutorUnavailableError'>
FAILED ...::TestAStepWithNoExecutorIsRefused::test_a_registered_executor_the_step_did_not_name_is_not_substituted - Failed: DID NOT RAISE <class '...AgentExecutorUnavailableError'>
FAILED ...::TestAStepWithNoExecutorIsRefused::test_no_executor_registered_at_all_refuses - Failed: DID NOT RAISE <class '...AgentExecutorUnavailableError'>
FAILED ...::TestAStepWithNoExecutorIsRefused::test_no_executor_named_where_two_are_registered_is_refused - Failed: DID NOT RAISE <class '...AgentExecutorUnavailableError'>
```

Restored by editing the call back; `md5sum` matches the backup
(`6ad6ff6eb5a68812e66231a286316ed0`), `grep -c SABOTAGE` → `0`, and
`16 passed` again.

---

## T4 · Open the node dispatch

### What changed

| File | Lines | Change |
|---|---|---|
| `src/functualize/_engine/workflow_walker.py` | 484 → **596** (+112) | `_NodeRun`, `_Ledger`, `_NodeHandler`, `_NODE_HANDLERS`; the loop's two-way type test replaced by a table lookup; the two inline bodies extracted to `_service_gate` / `_service_step`; `_service_agent` added; `run_agent_step` argument |
| `src/functualize/_engine/workflow_runner.py` | (shared with T3) | `_run_agent_step` handed to the walker |

### What deliberately did **not** move (risk R-a)

`visited`, `_ready`, the deferral counter, the replay-skip, `_build_predecessors`,
`_advance` and `_choice_for` are byte-identical. Two mechanical consequences of
extracting the bodies, both neutral and both checked against the suites below:

- the per-node `step_inputs` dict is gone — a handler returns its inputs, and the
  loop passes `run.inputs` to `_advance`; `FrontierWalk.complete` does
  `dict(inputs or {})`, so `None` and `{}` are the same write;
- the running account (`executed`/`replayed`/`results`) is one `_Ledger` object
  handed to the handlers, so a handler that ends the walk (a block, a nested
  block) still carries the account *as it stands* into its `WalkReport`. This is
  why the ledger exists rather than three list arguments.

### Gates

**Gate — the dispatch is no longer a type test**
```bash
rg -c 'isinstance\(node, ' src/functualize/_engine/workflow_walker.py
```
before: `1` (`:261`) — the task also claims `:313`, which is **stale**: the file
has one such test, in the loop. after: `0`.

**Gate — the walk's own mechanics are untouched**
```bash
rg -c 'visited' src/functualize/_engine/workflow_walker.py
```
before: `3` · after: `3`.

The first version of the new comment spelled the removed literal
(`` ``isinstance(node, Gate)`` ``), which kept gate A at `1` — the branch's
documented trap, hit exactly as described. The comment now describes the test
rather than quoting it.

**Independent falsifier — the dispatch is data, and the loop tests no node
type** (script: `/tmp/f6-falsify-t4.py`):

```
$ uv run python /tmp/f6-falsify-t4.py
table keys: ['AgentStep', 'Gate', 'Step']
type tests / lookups in run(): ['_NODE_HANDLERS.get(type(node))', 'isinstance(run, WalkReport)']
```

That output is the whole remaining answer, stated plainly rather than trimmed:
`run()` uses the node's class **as a key** and never compares it to a node
class, and the one surviving `isinstance` is on the *result* a handler returned,
not on the node. Adding a kind means adding a row.

### Verification

```
$ uv run pytest tests/workflow/ tests/test_workflow_walker.py tests/test_workflow_as_job.py \
      tests/gate/ tests/integration/test_workflow_as_job_e2e.py tests/engine/ -q --no-header
297 passed, 24 skipped in 192.46s (0:03:12)
```

### Sabotage (T4) — two breaks, both on the production call path

**a · the `AgentStep` row deleted from `_NODE_HANDLERS`:**

```
$ uv run pytest tests/workflow/test_agent_step_walk.py -q
5 failed, 1 passed in 1.89s
... exception=RuntimeError("no handler for node kind 'AgentStep'") ...
```

**b · `run_agent_step=self._run_agent_step` removed from the walker
construction:**

```
$ uv run pytest tests/workflow/test_agent_step_walk.py -q
5 failed, 1 passed in 2.07s
... RuntimeError("no agent step executor is reachable from this walk
    (WorkflowRunner supplies the registered one)") ...
```

Both restored by editing the lines back; `md5sum` matches
(`workflow_walker.py db3d6252e373d1f0fdc14c1e63e0dce5`), `grep -c SABOTAGE` → `0`,
`6 passed` again.

---

## T5 · The core `cli-prompt` executor, and registration

### What changed

| File | Lines | Change |
|---|---|---|
| `src/functualize/_engine/agent_step.py` | (new in T3) | `CliPromptExecutor` — `name = "cli-prompt"`, `capabilities = frozenset()`, `execute` asks the active collector |
| `src/functualize/_app/impl.py` | 876 → **899** (+23) | `register_agent_step_executor(app, executor)` |
| `src/functualize/app/core.py` | 1374 → **1403** (+29) | the facade method (AC-2's door), `AgentStepRegistry` annotation, `AgentStepExecutor` import |
| `src/functualize/_app/boot.py` | (shared with T3) | `CliPromptExecutor(app)` registered through the public method, in both boot paths |
| `src/functualize/_engine/capabilities/registry.py` | 141 → **178** (+37) | `_check_name_agreement` extended; new `_check_agent_capability_coverage` |
| `tests/workflow/test_agent_step_walk.py` | **new, 230** | the port through the public entry point |
| `tests/engine/test_capability_registry.py` | 172 → **211** (+39) | AC-11's agreement + its falsifier |

### The production call path this task wires (wiring-discipline §2)

```
app.register_agent_step_executor(executor)            # the door (AC-2)
  → _app/impl.register_agent_step_executor → AgentStepRegistry.register
boot_static / boot_standard
  → app.register_agent_step_executor(CliPromptExecutor(app))
  → JobExecutionEngine(agent_step_registry=app._agent_step_registry)
FunctualizeApp.execute → JobExecutionEngine.run
  → _run_workflow_prelude → WorkflowRunner(prelude) → AgentStepRegistry.check
  → WorkflowWalker._NODE_HANDLERS[AgentStep] → _service_agent
  → WorkflowRunner._run_agent_step → AgentStepRegistry.execute
  → CliPromptExecutor.execute → active_collector(app).collect(PromptRequest)
```

**AC-11's mechanism** is the ADR-014 shape, applied to the flags an executor
declares: `AgentCapability` (the vocabulary) and
`_types.workflow.IMPLIED_CAPABILITIES` (which declaration makes a step require
each flag) must agree, asserted at **import** of
`_engine/capabilities/registry.py`. It lives there because that module is where
the engine already keeps its import-time capability-name invariants; the check
is a second clause of `_check_name_agreement`, not a second mechanism.
Registration also refuses an object that does not satisfy the Protocol, which is
the same "forgotten declaration fails where it is declared" rule one level up.

### Gates

**Gate — the registration door exists**
```bash
rg -c 'def register_agent_step_executor' src/functualize/_app/impl.py
```
before: `0` · after: `1`

**Gate — AC-11 (the task's own command cannot fail, so it was re-derived)**
```bash
rg -c 'def _check_name_agreement' src/functualize/_engine/capabilities/registry.py
```
before: `1` · after: `1` — **this command asks nothing**. The claim behind it
("a forgotten capability-flag declaration is a startup failure") is falsified by
removing a declaration, so that is the gate actually run — see the sabotage
below.

**Independent falsifier — introspection, not a grep** (script:
`/tmp/f6-falsify-t5.py`):

```
$ uv run python /tmp/f6-falsify-t5.py
enum  : ['enforces_tool_allowlist', 'preserves_active_time_budget', 'supports_visible_output']
table : ['enforces_tool_allowlist', 'preserves_active_time_budget', 'supports_visible_output']
agree : True
CliPromptExecutor used in: ['src/functualize/_app/boot.py', 'src/functualize/_engine/agent_step.py']
```

The last line is the reachability question answered mechanically: the class has
exactly one production consumer, boot's registration call — which is the line
sabotage 5a deletes.

### Verification

```
$ uv run pytest tests/workflow/test_agent_step_walk.py tests/workflow/test_agent_step_refusals.py \
      tests/engine/test_capability_registry.py -q --no-header
32 passed in 2.47s
```

### Sabotage (T5)

**a · the core registration deleted from both boot paths** — the task's own line
("delete the registration call; the walk test must fail with
`AgentExecutorUnavailableError`, **not** with a human prompt"):

```
$ uv run pytest tests/workflow/test_agent_step_walk.py -q
5 failed, 1 passed in 2.86s
AgentExecutorUnavailableError: Agent step 'draft' has no executor registered for it
  (no executor is registered at all). The step is refused — it is never answered
  by prompting a human instead.
```

Restored by editing back; `md5sum` matches
(`boot.py 84654def8508d58b80364650e05cf34c`), `grep -c SABOTAGE` → `0`,
`6 passed`.

**b · the implication row deleted from `IMPLIED_CAPABILITIES`** (AC-11): the
import itself must refuse to start:

```
$ uv run python -c "import functualize._engine.capabilities.registry"
  File ".../capabilities/registry.py", line 129, in _check_name_agreement
    _check_agent_capability_coverage()
RuntimeError: AgentCapability and _types.workflow.IMPLIED_CAPABILITIES disagree —
declared as a flag but no AgentStep declaration can require it:
['preserves_active_time_budget']; reachable from a declaration but not a declared
flag: []. A flag nothing can require is one the engine can never refuse a step for.
```

Restored; `md5sum` matches (`_types/workflow.py f895ba9973b59ccb021252a60acb1816`),
`grep -c SABOTAGE` → `0`, `import ok`, and the targeted suites green again.

**c · `@runtime_checkable` deleted from `AgentStepExecutor`** (AC-1; see T7):

```
$ uv run pytest tests/workflow/test_agent_step_refusals.py -q
13 failed, 7 passed in 1.78s
FAILED ...::TestThePortIsAPort::test_the_executor_port_is_a_runtime_checkable_protocol_not_an_abc - AssertionError: assert False
FAILED ...::TestRegistration::test_an_object_without_capabilities_cannot_be_registered - AssertionError: Regex pattern did not match.
  Actual message: 'Instance and class checks can only be used with @runtime_checkable protocols'
```

Restored; `md5sum` matches (`_types/protocols.py 68fa514a89774598a1072e29b2095c9f`),
`20 passed`.

---

## T6 · A protected gate refuses an agent — parity test 4

### What changed

`tests/workflow/test_agent_step_refusals.py` (+~150 lines, same file as T3):
`TestAPreviouslyAnsweredCheckpoint`, three tests. **No source change** — the task
is the test.

### Reading of parity test 4, stated because the vocabulary does not exist here

Nothing in this repo defines a *protected gate*; `grep -rn protected src/` returns
only a threading lock and its docstring. The roadmap settles which feature owns
the test and how it is satisfied — `13-roadmap.md:169` *"A protected gate cannot
be answered by an agent that answered the previous one — **F6** (capability-flag
refusal)"*, and `10-graph-semantics.md:133` repeats it. So a node is *protected*
when it requires a capability its executor does not declare, and the refusal is
the capability-flag one T3 built.

That fixes how "even though" has to be modelled. The refusal is designed to fire
**before** the walk (R-b), so it cannot be observed inside one walk after an
earlier node of that walk ran — the whole point is that it is not a node-level
check. The property is therefore about *resume*, and it is a single graph and a
single scope:

1. **run one** — `checkpoint` is answered by executor `agent-x` (recorded
   `success`), the walk then blocks at the `approve` gate;
2. **run two** — the same scope, the same declaration, the executor now
   declaring *less*: the prelude refuses `apply`
   (`AgentCapabilityRefusedError`, `enforces_tool_allowlist`), with `apply`'s
   record absent and `checkpoint`'s `success` still sitting in the scope.

That is the "the agent's authority is per-gate, not per-scope" claim: an answer
this same executor already gave in this same scope is not a grant. The third test
is the **control** — a capable executor resumes that same scope past the
protected node to `COMPLETED` — because a test that only asserts the refusal
would also pass for a framework that simply cannot resume agent steps at all.

### Verification

```
$ uv run pytest tests/workflow/test_agent_step_refusals.py -q --no-header
20 passed in 0.33s
```

### Sabotage (T6)

The capability comparison neutralised in `AgentStepRegistry.check`
(`missing = node.requires - executor.capabilities` → `frozenset()`):

```
$ uv run pytest tests/workflow/test_agent_step_refusals.py -q
3 failed, 16 passed in 0.25s
FAILED ...::TestAnExecutorThatCannotHonourTheStepIsRefused::test_tools_against_an_executor_with_no_capabilities - Failed: DID NOT RAISE <class '...AgentCapabilityRefusedError'>
FAILED ...::TestAnExecutorThatCannotHonourTheStepIsRefused::test_a_budget_against_an_executor_that_cannot_preserve_it - Failed: DID NOT RAISE <class '...AgentCapabilityRefusedError'>
FAILED ...::TestAPreviouslyAnsweredCheckpoint::test_the_protected_node_refuses_the_same_executor_on_resume - Failed: DID NOT RAISE <class '...AgentCapabilityRefusedError'>
```

Restored; `md5sum` matches
(`agent_step.py 3831edd59492ea378b0ebedeec2d5248`), `grep -c SABOTAGE` → `0`,
`147 passed, 24 skipped` across `tests/workflow/`.

---

## T7 · Feature gate

### The one existing test this feature broke, and how it was handled

`tests/test_workflow_decorator.py::TestValidateWorkflowGraph::test_non_node_entry_rejected`
asserted `TypeError, match="must be Step or Gate"` against
`_validate_workflow_graph`. Adding a third node kind changes that message
(`"Workflow steps must be Step, Gate or AgentStep objects, got str"`), so the
test went red — correctly.

It was **not** re-pinned to the new string. The property worth keeping is "the
refusal names every kind it accepts", so the test now derives the expected names
from `_validation._NODE_TYPES` and asserts each is *mentioned* in the message:

```python
named = {word for word in re.findall(r"\b[A-Z]\w*\b", self._node_type_error())}
assert {kind.__name__ for kind in _NODE_TYPES} <= named
```

That catches the real drift (a kind added to the validator but not to the
diagnostic) and stops the test from needing an edit every time the vocabulary
grows; a transcribed literal would have kept the count of the wrong question at
1 forever. Sabotage, deleting `AgentStep` from the message:

```
$ uv run pytest tests/test_workflow_decorator.py -q
1 failed, 19 passed in 0.15s
FAILED ...::TestValidateWorkflowGraph::test_non_node_entry_rejected -
  AssertionError: assert {'AgentStep', 'Gate', 'Step'} <= {'Gate', 'Step', 'Workflow'}
  Extra items in the left set: 'AgentStep'
```

Restored; `grep -c SABOTAGE` → `0`; `20 passed`.

### AC → the thing that catches its regression

| AC | The claim | What catches a regression |
|---|---|---|
| AC-1 | `AgentStepExecutor` is a `@runtime_checkable Protocol`, no ABC | `tests/workflow/test_agent_step_refusals.py::TestThePortIsAPort` (asserts `_is_protocol`, `_is_runtime_protocol`, no ABC in the MRO) + `TestRegistration::test_an_object_without_capabilities_cannot_be_registered` (isinstance, which raises without the decorator). Sabotage 5c turns 13 tests red. |
| AC-2 | Registered by an app method, nothing auto-discovered | `tests/workflow/test_agent_step_walk.py::TestAnAgentStepRuns::test_the_registered_executor_performs_the_step` — driven through `app.execute`, and the only producer of a registration is boot's call on the public method. T5 sabotage 5a (delete that call) turns 5 tests red; `test_an_executor_that_is_not_registered_refuses_before_anything_runs` shows an unregistered executor is refused, not found. |
| AC-3 | A step performed by an agent, edges/gates/conditions unchanged | `TestAnAgentStepInsideAGraph::test_a_conditional_edge_branches_on_what_the_agent_returned` (Step → AgentStep → ConditionalEdge → only the chosen branch runs) + `TestTheDeclaration::test_a_workflow_accepts_an_agent_step_beside_edges_and_gates`; `tests/test_workflow_walker.py`, `tests/test_workflow_as_job.py`, `tests/integration/test_workflow_as_job_e2e.py` unchanged and green. |
| AC-4 | Executors declare flags; steps declare needs | `TestTheDeclaration::test_declaring_tools_implies_the_capability_that_enforces_them` / `…a_time_budget_implies…` / `…an_explicit_requirement_is_widened…` and `TestAnExecutorThatCannotHonourTheStepIsRefused` (the two sets compared). |
| AC-5 | A capability mismatch refuses **at validation**, before the walk | `TestAnExecutorThatCannotHonourTheStepIsRefused::test_tools_against_an_executor_with_no_capabilities` — refuses with `recorder.calls == []`, `executor.calls == []` and `store.get_scope(...) is None`, with an ordinary `Step` deliberately placed *before* the agent step. |
| AC-6 | The refusal names the missing capability and the executor | Same test: `caught.value.capability is ENFORCES_TOOL_ALLOWLIST`, `caught.value.executor == "cli-prompt"`, and the message contains the flag name. `test_a_budget_…` covers `declared=`. |
| AC-7 | No registered executor → refuse, naming the package, no fallback | `TestAStepWithNoExecutorIsRefused::test_a_named_executor_nobody_registered_names_its_package` (`hint == "install functualize-ai to register it"`), `…test_a_registered_executor_the_step_did_not_name_is_not_substituted` (the registered one's `execute` is never called), `…test_no_executor_registered_at_all_refuses` (empty hint for a core name), plus the end-to-end `test_an_executor_that_is_not_registered_refuses_before_anything_runs`. |
| AC-8 | `EXECUTOR_PROVIDERS`/`CORE_EXECUTORS` exist; hint empty for a core name | W1's `tests/gate/test_provider_tables.py` (16 tests, parametrized over both tables — `test_a_core_name_gets_no_install_hint` is the AC) + `…test_no_executor_registered_at_all_refuses` for the empty hint. |
| AC-9 | `src/` never imports the plugins | `tests/gate/test_provider_tables.py::…::test_core_names_the_plugins_without_importing_them` (the **wider** spelling from W01 finding 3: `(^|\s)(from\|import)\s+(functualize_ai\|functualize_mcp)`) + the checkpoint below. |
| AC-10 | The dispatch is no longer a two-way type test | T4's gate (`rg -c 'isinstance(node, '` → `0`) + `_NODE_HANDLERS` introspection + T4 sabotage (a) — deleting the row fails 5 tests; the loop's own mechanics gate (`visited` → `3`) holds. |
| AC-11 | A forgotten capability-flag declaration is a startup failure | `tests/engine/test_capability_registry.py::test_the_agent_capability_flags_are_all_reachable_from_a_declaration` and `…test_the_agent_capability_guard_actually_fires`; sabotage 5b makes the *import itself* raise. `TestRegistration::test_an_object_without_capabilities_cannot_be_registered` is the same rule at the registration door. |
| AC-12 | Parity test 4: a protected node refuses, even though the checkpoint was answered | `tests/workflow/test_agent_step_refusals.py::TestAPreviouslyAnsweredCheckpoint` (3 tests: the premise, the refusal on resume, and the capable-executor control). Sabotage 6 turns the refusal red. |

### Orphan scan over every added symbol

Production references exclude the defining file; "0" is only meaningful if the
symbol is used inside its own module, so each is checked (wiring-discipline §6 —
a review question, not a gate):

```
AgentStep                          prod=10 tests=5
AgentStepRegistry                  prod=3  tests=1
CliPromptExecutor                  prod=1  tests=0
IMPLIED_CAPABILITIES               prod=1  tests=1
register_agent_step_executor       prod=4  tests=0
_run_agent_step                    prod=1  tests=0

_NodeHandler / _NODE_HANDLERS      prod=0  tests=0   → used in workflow_walker.py (the table itself)
_Ledger / _NodeRun                 prod=0  tests=0   → used in workflow_walker.py (types of the handlers)
_service_gate/_service_step/_service_agent  prod=0  → the table's rows, in workflow_walker.py
implied_capabilities               prod=0  tests=0   → AgentStep.__post_init__, in _types/workflow.py
_check_agent_capability_coverage   prod=0  tests=1   → _check_name_agreement, in registry.py
```

No symbol is reached only by a test. `CliPromptExecutor`'s single production
reference is `_app/boot.py`, which is the wiring this task is about; its effect
is observed through `app.execute` in `test_agent_step_walk.py`.

### Wiring-discipline §5 — the cached path

The concern is code that reads a fact off a job *function*, which a warm boot
hands over as a deferred-import stand-in. Nothing here does: the agent step's
declaration is read from `__functualize_workflow__` on the materialized function,
exactly as every other node kind already was, and `_run_workflow_prelude` is only
reached when that declaration exists. What *is* new on the cached path is the
node kind inside `WorkflowShape` (`{"agent": name}`), which I extended and pinned
with a `to_dict`/`from_dict` round-trip test
(`TestTheDeclaration::test_the_cached_shape_keeps_an_agent_node_distinct_from_a_step`).
Had it been cached as `{"step": name}`, every listing surface would have named a
job nobody runs — the §5 failure shape, caught in the cache layer rather than at
the walk.

---

## Verification actually run

### Static gates (re-run after the last code change)

```
$ uv run ruff check src/ tests/ plugins/
All checks passed!

$ uv run ruff format --check src/ tests/
1114 files already formatted

$ uv run mypy src/
Success: no issues found in 336 source files

$ uv run lint-imports
Contracts: 6 kept, 0 broken.
```

(`ruff check`/`format` initially flagged one file of mine,
`tests/workflow/test_agent_step_walk.py`; the `format` output in the first
attempt was `Would reformat: tests/workflow/test_agent_step_walk.py` and
`1113 files already formatted`. Fixed before the runs below.)

Then the targeted run — the last thing run against the final tree. It includes
every suite this feature can move: the walker, the runner, the decorator, the
gate tables, the engine, the e2e workflow job and the public-API door.

```
$ uv run pytest tests/workflow/ tests/test_workflow_walker.py tests/test_workflow_as_job.py \
      tests/test_workflow_decorator.py tests/gate/ tests/engine/ \
      tests/integration/test_workflow_as_job_e2e.py tests/test_public_api_surface.py \
      -q --no-header
371 passed, 24 skipped in 57.86s
```

### The full suite, and the examples

**Run 1** — before the one test fix below, moderate machine load:

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
2 failed, 11234 passed, 139 skipped, 3089 warnings in 824.22s (0:13:44)
```

Both failures, and what each actually is:

**1 · `tests/integration/test_warm_cold_boot.py::TestWarmBootPerformance::test_warm_boot_scales_linearly`
— `Per-module cost 1.113ms exceeds hard limit of 1ms`.** A parallelism artifact,
and measured rather than asserted. Re-run alone it passes (three consecutive
runs, the 0.2ms soft target never even warning), and the measurement the test
makes, printed directly (`/tmp/f6-warm-measure.py`), is:

```
$ uv run python /tmp/f6-warm-measure.py
modules: 100
warm total: 5.541ms   per module: 0.0554ms
agent_step imported by the warm path: False
newly imported modules: []
```

18× under the hard limit in isolation, and the warm path imports **nothing
new** — `functualize._engine.agent_step` is not on it at all. This is the same
test class the W1 report filed under "passes when re-run serially"
(`Per-module cost 12.315ms …` there). I did not weaken it.

**2 · `tests/test_workflow_decorator.py::TestValidateWorkflowGraph::test_non_node_entry_rejected`
— `Expected regex: 'must be Step or Gate'`.** Mine, and real: adding a node kind
changed the message the validator must produce, so the test's transcribed
literal went stale. Handled under T7 above, not by re-pinning.

**Run 2** — after that fix, while **two other agents were running their own full
`--run-slow -n auto` suites on this machine** (`agent-f8-adjacent-w567`,
`agent-f3-engine-seal`; `ps -eo etime,args | grep pytest --run-slow` showed three
concurrent suites, load average **56** on 12 threads):

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
3 failed, 11232 passed, 141 skipped, 3087 warnings in 1570.83s (0:26:10)

FAILED tests/context/test_runcontext_properties.py::TestRunContextInitialState::test_initial_start_time_within_tolerance
       - AssertionError('assert 1.644164 < 1.0') [single exception in FlakyFailure]
FAILED tests/core/test_job_descriptor_properties.py::TestJobDescriptorRetentionProperty::test_get_descriptors_empty_when_no_jobs
       - DeadlineExceeded('Test took 8015.62ms, which exceeds the deadline of 5000.00ms.') [single exception in FlakyFailure]
FAILED tests/e2e/test_interactive.py::TestPtyBasics::test_help_in_pty
       - pexpect.exceptions.TIMEOUT: Timeout exceeded.
```

All three are load artifacts by their own text — a 1.64s wall-clock tolerance, a
Hypothesis deadline of 8.0s against 5s, and a 10s pexpect timeout waiting for a
PTY child to reach EOF — and all three pass when re-run by themselves:

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -q --no-header -p no:randomly \
    tests/context/…::test_initial_start_time_within_tolerance \
    tests/core/…::test_get_descriptors_empty_when_no_jobs \
    tests/e2e/test_interactive.py::TestPtyBasics::test_help_in_pty
3 passed in 12.39s
```

The decorator test that failed in run 1 **does not appear in run 2** — that is
the fix, verified. The warm-boot timing test also passed in run 2. What run 2
lost is three *different* timing tests, none of them in code this branch touches
and all three green in isolation; run 1's counts (11234 passed / 139 skipped)
and run 2's (11232 / 141) differ only by those flakes and the order `-n auto`
hands tests to workers.

### Plugin suites (run one package at a time, per AGENTS.md)

```
$ uv run pytest plugins/functualize-mcp/tests -q --no-header
16 passed in 1.52s
$ uv run pytest plugins/functualize-ai/tests -q --no-header
17 passed in 0.71s
$ uv run pytest plugins/functualize-inline/tests -q --no-header
50 passed in 1.01s
$ uv run pytest plugins/functualize-state/tests -q --no-header
6 passed in 0.47s
$ uv run pytest plugins/functualize-flow-viz/tests -q --no-header
25 passed in 0.40s
```

### `examples/` — run, but only with a path workaround (pre-existing defect, **not mine**)

The mandated command fails on arrival in *this* worktree, at collection:

```
$ uv run pytest examples/ -q
ERROR collecting examples/standalone/deploy_tool/tests/test_deploy_tool.py
  examples/standalone/deploy_tool/deploy_tool/main.py:24: in <module>
    from functualize.app.adapters import CliAdapter
  .../app/adapters/cli.py:27: in <module>
    import click
E   ModuleNotFoundError: No module named 'click'
...
  File ".../_hypothesis_pytestplugin.py", line 400, in pytest_terminal_summary
    from hypothesis.internal.observability import _WROTE_TO
ModuleNotFoundError: No module named 'hypothesis'
```

Both packages are installed; `examples/quickstart/step*/conftest.py` deletes them
from `sys.path`:

```python
# Remove any conflicting 'weather' from other step directories
sys.path = [p for p in sys.path if "step" not in p or p == this_dir]
```

That filter means "drop the other quickstart `step*` directories", but it matches
any path containing `step` — including this worktree's own
`.venv/lib/python3.13/site-packages`, because the worktree is named
`agent-f6-agent-`**`step`**`-w2`. The venv leaves `sys.path` mid-collection and
every later import fails. W1 ran in a worktree called `pi-parity` and never saw
it; every `agent-*-step-*` worktree will. Fixing it is outside my brief (the file
is `examples/`, and the fix is a filter that should name the sibling directories
rather than substring-match the whole path) — reported rather than touched.

With the venv reachable at a path that does not contain `step`, the same command:

```
$ ln -sfn "$PWD/.venv/lib/python3.13/site-packages" /tmp/f6-site
$ PYTHONPATH=/tmp/f6-site uv run pytest examples/ -q
194 passed in 226.12s (0:03:46)
```

**`194 passed` — the same count W1 recorded, with no failures and nothing skipped.**

### The AC-9 checkpoint (the wider spelling, per W01 finding 3)

```bash
grep -rn -E '(^|[[:space:]])(from|import)[[:space:]]+(functualize_(ai|mcp))' src/ | wc -l
```
```
0
```

The narrow spelling the task names (`import functualize_(ai|mcp)`) returns `0`
too, but it cannot see `from functualize_ai import x` — W01's finding 3, and the
reason `tests/gate/test_provider_tables.py` asks the wider question.


## Could not do, and questions

1. **`tasks.md` checkboxes.** Not in my file list and the orchestrator owns the
   file. T3–T7 are all `[ ]` in it; the gate table below says what each one's
   state is.
2. **`FunctualizeError` still does not exist** (W01 finding 1). `contracts.md` §5
   writes both new errors as deriving from it; they derive from `Exception`, like
   every other class in `_types/errors.py`. Unchanged by this wave — inventing a
   base class with two users is a separate decision that adds a public name.
3. **`issubclass` still raises on `AgentStepExecutor`** (W01 finding 2). The
   registry uses `isinstance` throughout, as that finding requires.
4. **`AgentStepContext.inputs` is always empty.** `AgentStep` declares
   `instructions`, not input bindings, and `contracts.md` §2 adds no field, so
   there is nothing for the walk to resolve into it. Stated in the code beside
   `_NO_INPUTS`; a feature that adds `FromStep`-style bindings for agent steps
   would fill it, and that is not this one's scope (§5).
5. **`AgentStepResult.tool_calls` is carried, not recorded.** The port returns
   it; nothing persists it. Durable recording of an agent step's work is
   explicitly F5 (spec §5), and the walker records the value only.
6. **The task's T4 gate claims `isinstance(node, …)` at `:313` and `:261`.**
   There is one such site (`:261`); the second was already gone on this branch.
   Reported rather than "fixed".
7. **T5's AC-11 gate command cannot fail** (`rg -c 'def _check_name_agreement'`
   is `1` either way). The claim behind it is falsified by sabotage 5b instead.
8. **Question for the orchestrator:** `executor=None` with two registered
   executors refuses (contracts §2 read literally). If the intended product
   behaviour is "prefer the non-core executor", that is a different decision and
   the table `EXECUTOR_PROVIDERS` is where it would have to be expressed. I chose
   the literal reading and the safe direction — nothing is guessed, and the
   refusal lists both names.

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T3 (`AgentStep`, `_NODE_TYPES`, refusals) | yes | `rg -n '_NODE_TYPES = '` → `(Step, Gate)` | `(Step, Gate, AgentStep)`; 20 tests green; sabotage: 6 red |
| T4 (open the dispatch) | yes | `rg -c 'isinstance\(node, '` → `1`; `visited` → `3` | `0`; `3` (unchanged); 297 passed scoped; sabotage: 5 red ×2 |
| T5 (`cli-prompt` + registration + AC-11) | yes | `rg -c 'def register_agent_step_executor'` → `0`; `rg -c 'def _check_name_agreement'` → `1` (vacuously) | `1`; `1`, with a new clause — sabotage makes the import raise |
| T6 (parity test 4) | yes | test absent | `TestAPreviouslyAnsweredCheckpoint`, 3 tests; sabotage: 3 red |
| T7 (feature gate) | yes | — | see the verification block |
