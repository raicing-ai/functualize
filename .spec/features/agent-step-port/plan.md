# Plan — agent-step-port

---

## 1. The approach in one line

**Copy the gate-resolver port and its provider table exactly, add capability flags whose
mismatch refuses at validation, and open the walker's two-way `isinstance` into a dispatch that
does not need editing for a third kind.**

## 2. Why almost nothing here is new

| Piece | Already exists |
|---|---|
| A registered, `@runtime_checkable` port | `GateResolver` (`_gate/_resolver.py:18-40`) |
| A provider table naming packages without importing them | `STRATEGY_PROVIDERS` (`_gate/_strategy.py:40-66`) |
| A grep test enforcing that | `tests/gate/test_registry.py:298-306` |
| Refusal at import time for a forgotten declaration | `_check_name_agreement` (`_engine/capabilities/registry.py:114`) |
| A context object carrying a run's inputs | `RunRequest` (F1) |

What is genuinely new: one declaration type, three capability flags, and opening the walker's
dispatch.

## 3. Files to change

### New

```
src/functualize/_engine/agent_providers.py        EXECUTOR_PROVIDERS, CORE_EXECUTORS, the hint
src/functualize/_engine/agent_step.py             the dispatch and the refusal checks
tests/workflow/test_agent_step_refusals.py
tests/workflow/test_agent_step_walk.py
tests/gate/test_provider_tables.py                extends the existing grep test
```

### Modified

```
src/functualize/_types/protocols.py               AgentStepExecutor, AgentCapability
src/functualize/workflow/__init__.py              AgentStep, public re-export
src/functualize/workflow/_validation.py           _NODE_TYPES gains AgentStep; the refusal checks
src/functualize/_engine/workflow_walker.py        node dispatch opened
src/functualize/_app/impl.py                      register_agent_step_executor
src/functualize/plugin/__init__.py                the plugin-facing re-exports
src/functualize/_types/errors.py                  two errors
```

## 4. Risks

- **R-a · The dispatch change touches the walk's hot loop.** `workflow_walker.py:261` and
  `:313` are inside the BFS that also owns the `visited` set, join readiness and replay-skip.
  *Mitigation:* open the dispatch **without** changing any of those — a table lookup replacing a
  type test, nothing else in the loop moves. The existing workflow suites are the gate, and
  `tests/engine/test_lifecycle_order.py` stays green.

- **R-b · Capability refusal fires at the node instead of at validation.** Refusing halfway
  through a walk is a worse experience than not starting: side effects have already happened.
  *Mitigation:* the check lives in `_validate_workflow_graph`, and a test asserts the refusal
  happens with **zero** step records written.

- **R-c · `tools=[…]` implying a required capability surprises someone.** *Mitigation:* it can
  be widened explicitly and never narrowed implicitly; the error message says the implication
  out loud; documented with the declaration.

- **R-d · The port grows an agent protocol.** The temptation is to standardise messages, retries
  or streaming. *Mitigation:* the Protocol has one method and the spec says so; anything an
  implementation needs beyond `AgentStepContext` is the implementation's business.

- **R-e · A second provider table drifts from the first.** Two tables, two hint functions, two
  grep tests. *Mitigation:* one shared test parametrized over both tables
  (`tests/gate/test_provider_tables.py`), so a third table joins a list rather than copying a
  file — the `pitfalls.md` §6 shape.

- **R-f · Nothing implements the port, so nothing proves it.** *Mitigation:* the `cli-prompt`
  core executor ships with it — the one that asks a human, declaring **no** capabilities, so it
  is also the test fixture for every refusal path.

## 5. Ordering

```
W0  the Protocol, the flags, the two errors        (declaration only)
W1  EXECUTOR_PROVIDERS + the shared provider-table test
W2  AgentStep + _NODE_TYPES + the validation refusals
W3  the walker's dispatch opens
W4  the core `cli-prompt` executor, and registration
W5  parity test 4 (a protected gate refuses an agent)
W6  checkpoint
```

W2 before W3 is deliberate: the refusals must exist before a node kind can reach the walk, so
there is never a commit where an agent step runs unchecked.

## 6. What this plan does not do

It does not make an agent step durable (**F5**), does not route failures around it (**F7**),
and does not ship an executor that talks to a model — `cli-prompt` asks a human, and the two
real executors are plugin work named in the table.
