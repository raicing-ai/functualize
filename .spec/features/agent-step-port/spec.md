# Feature — agent-step-port

Implements **F6** of `contributor/architecture/run-model/13-roadmap.md` — pi-workflows roadmap
**item 7**, and decisions **C5**, **F3**, **F4**.

**Depends on:** `run-request-entry` (F1). **Does not depend on F5** — an agent step that cannot
be durably recorded is still a working agent step.
**Blocks:** nothing.

---

## 1. The problem

### 1.1 The node vocabulary is a closed pair, and kind is an `isinstance`

`src/functualize/workflow/_validation.py:28`:

```python
_NODE_TYPES = (Step, Gate)
```

and the walker decides kind by type test — `_engine/workflow_walker.py:261`
(`isinstance(node, Gate)`) and again at `:313`.

**There is no step kind and no pluggable step executor.** Adding one today means editing the
walker's dispatch — the exact "open for modification" shape this document set exists to close,
one layer down.

### 1.2 A workflow cannot ask an agent to do a step

Today an agent can *answer a gate* — that is what 0.3.0 shipped. It cannot *perform a step*. A
workflow that wants "have an agent write the migration, then run the tests" has to model the
agent's work as a gate, which is a lie: a gate waits for input, a step does work.

### 1.3 The alternative is worse than the gap

The previous study framed this as a new **node kind**. The roadmap re-shaped it as a **port**,
and that re-shaping is the load-bearing decision (**C5**), because an agent step is the first
node whose execution is:

- not a local function call,
- capable of taking arbitrarily long,
- capable of being *refused* rather than failing,
- and dependent on capabilities the executor may or may not have.

A node kind hard-codes one answer to all four. A port lets the engine **refuse** when the
executor cannot honour what the step declared — which is the requirement, and the thing a
silently-degrading implementation would get wrong.

---

## 2. User stories

- **US-1** As a workflow author, I declare a step performed by an agent, and the rest of my
  graph is unchanged — edges, gates and conditions work as they always did.
- **US-2** As a workflow author, I declare that an agent step may use only certain tools, and
  if the registered executor cannot enforce that, **my workflow refuses to start** rather than
  running with every tool available.
- **US-3** As an operator with no agent plugin installed, a workflow declaring an agent step
  tells me which package to install, and does not fall back to asking me the question myself.
- **US-4** As a plugin author, I implement one Protocol and declare what I can enforce.

---

## 3. Behaviour

### 3.1 The agent step is a port

`AgentStepExecutor` is a `@runtime_checkable Protocol`, registered — never auto-discovered.
`GateResolver` (`_gate/_resolver.py:18-40`) is the template, down to registration by an app
method rather than entry-point scanning.

> Auto-discovery is how a surface acquires behaviour nobody declared. This feature does not
> add any.

### 3.2 Capability flags, and the engine **refuses**

An executor declares what it can enforce. A step declares what it needs. **A mismatch refuses
at validation** — before the walk starts, not at the node.

| Flag | The engine refuses when |
|---|---|
| `enforces_tool_allowlist` | the step declares `tools=[…]` and the executor cannot constrain them — running anyway would silently grant every tool |
| `preserves_active_time_budget` | the step is under a time budget the executor cannot honour |
| `supports_visible_output` | the step's output must reach a live surface and the executor can only return at the end |

> **Refusing is the feature.** A silently degrading agent step is worse than no agent step: the
> workflow appears to have enforced a constraint it did not.

### 3.3 The provider table is copied, not invented

The codebase has exactly **one** `*_PROVIDERS` table — `STRATEGY_PROVIDERS`
(`_gate/_strategy.py:40`). `EXECUTOR_PROVIDERS` copies it exactly, including two details that
are easy to miss and were hard-won:

- **`CORE_*` exists so the diagnostic can shut up.** `missing_strategy_hint`
  (`_gate/_strategy.py:56-66`) returns an **empty string** for a core name, because *"if
  `resolve` is unregistered the answer is not 'install something', it is that the registry was
  built by hand."* A table that always suggests an install lies in the one case where the bug
  is internal.
- **The table records its own known inconsistency** rather than hiding it — its comment notes
  that the validator accepts four names while the table follows the validator, and points at
  where reconciling them is scoped.

The table ships **in core from day one**, before there are two implementations (decision
**C5**), because a table added later is a table that has already been worked around.

### 3.4 Naming a package is not importing one

Enforced by the existing grep test (`tests/gate/test_registry.py:298-306`):

```python
result = subprocess.run(["grep", "-rn", "-E", r"import functualize_(ai|mcp)", "src/"], ...)
assert result.stdout == "", f"core imports a plugin:\n{result.stdout}"
```

Decisions **F3** and **F4** in executable form. The new table extends that test's pattern.

### 3.5 Missing means refused, not substituted

A workflow declaring an agent step with no registered executor **refuses at validation**,
naming the package to install. It does **not** fall back to prompting a human — a fallback that
changes who answers is a different program.

### 3.6 What must not change

- `Step`, `Gate`, `Edge`, `ConditionalEdge`, `END` and every existing declaration.
- The walk's BFS, its `visited` set, its join readiness, and its replay-skip.
- `_execute_lifecycle`'s 20-step order.
- `GateResolver` and the gate strategies — this sits beside them.

---

## 4. Acceptance criteria

- **AC-1** `AgentStepExecutor` is a `@runtime_checkable Protocol` in `_types/protocols.py`.
  No ABC.
- **AC-2** An executor is **registered** by an app method; nothing is auto-discovered.
- **AC-3** A workflow may declare a step performed by an agent, and every existing edge, gate
  and condition works unchanged around it.
- **AC-4** An executor declares its capability flags, and a step declares what it needs.
- **AC-5** A step needing `enforces_tool_allowlist` against an executor without it **refuses at
  validation**, before the walk starts.
- **AC-6** The refusal names the missing capability and the executor that lacks it.
- **AC-7** A workflow declaring an agent step with **no** registered executor refuses, naming
  the package from `EXECUTOR_PROVIDERS`.
- **AC-8** `EXECUTOR_PROVIDERS` and `CORE_EXECUTORS` exist in core, and the hint returns an
  empty string for a core name.
- **AC-9** `rg 'import functualize_(ai|mcp)' src/` stays empty — core names packages, never
  imports them.
- **AC-10** The walker's node dispatch is no longer a two-way `isinstance`; adding a node kind
  does not require editing it.
- **AC-11** A forgotten capability-flag declaration is a **startup** failure, not a runtime
  surprise — the ADR-014 shape (`_engine/capabilities/registry.py:114`).
- **AC-12** pi-workflows parity test **4**: a gate marked *protected* cannot be answered by an
  agent, even though the agent answered the previous checkpoint.

---

## 5. Out of scope

- Any agent protocol of its own. The port says what the **engine** needs; how an
  implementation talks to Claude, an MCP client or a terminal is entirely its business.
- Durable recording of an agent step's work — **F5**. This feature does not depend on it.
- Loops and failure routing around agent steps — **F7**.
- A default executor. §3.5.

## 6. Prior art

- **`_gate/_strategy.py:40-66`** — the one `*_PROVIDERS` table, and the `CORE_*` subtlety.
- **`_gate/_resolver.py:18-40`** — the port template: `@runtime_checkable`, registered, missing
  implementation reported with the package to install.
- **`tests/gate/test_registry.py:298-306`** — the grep test that makes "name it, never import
  it" executable.
- **ADR-014 / `_engine/capabilities/registry.py:114`** — `_check_name_agreement` runs at import
  time, so a forgotten name is a startup crash by construction. That is the refusal mechanism
  this feature reuses rather than reinvents.
