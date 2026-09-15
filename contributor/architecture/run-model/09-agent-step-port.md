# 09 · The agent-step port — a Protocol with capability flags, failing closed

Roadmap item **7**, and pi-workflow decision **C5**. The previous study framed the agent step
as a new *node kind*; the roadmap re-shaped it as a **port**, and this document takes that as
settled and asks what the port must look like given what exists.

---

## A. What exists today

**The node vocabulary is a closed pair.** `workflow/_validation.py:28` accepts `Step` and
`Gate` and nothing else. Node kind is decided by `isinstance` dispatch inside the walker
(`_engine/workflow_walker.py:261`, `:313`). **There is no step kind, and no pluggable step
executor.** Adding one today means editing the walker's dispatch — the exact "open for
modification" shape this document set exists to close, one layer down.

**Gate resolution, by contrast, is already a port** — and it is the template.

## B. The template, and it is one table and one Protocol

The codebase has exactly **one** `*_PROVIDERS` table. The agent-step port copies it rather
than inventing a second convention.

### B.1 The table — `_gate/_strategy.py:40-45`

```python
STRATEGY_PROVIDERS: dict[str, str] = {
    GateStrategy.RESOLVE.value:     "functualize",
    GateStrategy.PROMPT.value:      "functualize",
    GateStrategy.AI_INBOUND.value:  "functualize-ai",
    "ai_outbound":                  "functualize-mcp",
}

CORE_STRATEGIES: frozenset[str] = frozenset({RESOLVE.value, PROMPT.value})
```

Two details worth copying exactly, because both are hard-won:

- **`CORE_STRATEGIES` exists so the diagnostic can shut up.** `missing_strategy_hint`
  (`:56-66`) returns an **empty string** for a core strategy, because *"if `resolve` is
  unregistered the answer is not 'install something', it is that the registry was built by
  hand."* A provider table that always suggests an install lies in the one case where the
  bug is internal.
- **The table's own comment records a known inconsistency rather than hiding it**: the
  validator accepts four names, the table follows the validator, and reconciling the two is
  explicitly out of scope with a pointer to where. The agent-step table will inherit the same
  obligation.

### B.2 The enforcement — a grep test, `tests/gate/test_registry.py:298-306`

```python
def test_core_names_the_plugins_without_importing_them(self) -> None:
    """Naming a package in a diagnostic is not a dependency; importing one
    would invert the dependency graph, since both plugins depend on core."""
    result = subprocess.run(
        ["grep", "-rn", "-E", r"import functualize_(ai|mcp)", "src/"], ...
    )
    assert result.stdout == "", f"core imports a plugin:\n{result.stdout}"
```

This is pi-workflow decisions **F3** and **F4** in executable form: *name the package, never
import it*, pinned by a test that fails as a block with a diagnostic.

### B.3 The Protocol — `_gate/_resolver.py:18-40`

```python
@runtime_checkable
class GateResolver(Protocol):
    def resolve(self, ctx: GateContext) -> BaseModel: ...
```

**Registered, never auto-discovered** (`app.register_gate_strategy()`). A missing
implementation is reported as *"unregistered … install `<pkg>` to register it"* via
`GateResolutionError.last_error` (`_gate/_registry.py:24-37`, `:180-203`).

## C. Failing closed — the mechanism already exists

The roadmap's requirement is that the engine **refuse** rather than degrade. ADR-014 already
built that, for capabilities, and it is stronger than a runtime check:

`_engine/capabilities/registry.py:97-123` — `_check_name_agreement` runs at **import time**
and compares the declared `CapabilitySpec` names against `INJECTED_PARAM_TYPE_NAMES`.
Forgetting the string is a **startup crash by construction**, not a silent no-op discovered
by a user three surfaces later.

That is the shape the capability flags take: a flag a provider forgets to declare must be a
startup failure in the provider's own package, not a degraded run.

## D. The port

```python
@runtime_checkable
class AgentStepExecutor(Protocol):
    """Executes a workflow step by delegating to an agent."""

    #: Declared capabilities. The engine refuses a step whose declaration
    #: requires a capability this executor does not claim.
    capabilities: frozenset[AgentCapability]

    def execute(self, ctx: AgentStepContext) -> AgentStepResult: ...
```

with the three flags the roadmap names, each mapping to a refusal rather than a downgrade:

| Flag | The engine refuses when |
|---|---|
| `enforces_tool_allowlist` | the step declares `tools=[…]` and the executor cannot constrain them — running the step anyway would silently grant every tool |
| `preserves_active_time_budget` | the step is under a time budget the executor cannot honour |
| `supports_visible_output` | the step's output must reach a live surface and the executor can only return at the end |

And a table beside it, in core, from day one — pi-workflow decision **C5** is explicit that
`EXECUTOR_PROVIDERS` lives in core even before there are two implementations, because a table
added later is a table that has already been worked around:

```python
EXECUTOR_PROVIDERS: dict[str, str] = {
    "mcp-elicitation": "functualize-mcp",
    "cli-prompt":      "functualize",      # core; hint returns ""
    "ai":              "functualize-ai",
}
CORE_EXECUTORS: frozenset[str] = frozenset({"cli-prompt"})
```

## E. Why this is sequenced after F1, and what it gains

The roadmap marks item 7 **Next** and unblocked, and on its own terms it is: its stated
dependency (item 5) shipped in 0.3.0. This set sequences it after **F1** anyway, for one
reason that is not a technicality.

An agent step is the first node type whose execution is **not a local function call**. It
runs somewhere else, it can take a long time, it can be refused, and it can fail in ways a
`try/except` around a callable does not describe. Every one of those needs a request object
to carry provenance in and a record to carry the outcome out. Built before F1, the port
would define its own context and result types; built after, `AgentStepContext` is a
`RunRequest` with the step's declaration attached, and `AgentStepResult` folds into the run
record ([08](08-durable-runs.md)) for free.

It does **not** need F5. An agent step that cannot be durably recorded is still a working
agent step — so F6 runs in parallel with F5, not behind it.

## F. What this feature does not do

- **No auto-discovery.** Registered, like `GateResolver`. Auto-discovery is how a surface
  acquires behaviour nobody declared.
- **No default executor.** A workflow declaring an agent step with no registered executor
  **refuses at validation**, naming the package — it does not fall back to prompting a human,
  because a fallback that changes who answers is a different program.
- **No agent protocol of its own.** The port says *what the engine needs*; how an
  implementation talks to Claude, an MCP client, or a terminal is entirely the
  implementation's business.
