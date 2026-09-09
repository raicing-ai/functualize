# Contracts — agent-step-port

External interfaces only.

---

## 1. The port

```python
class AgentCapability(str, Enum):
    ENFORCES_TOOL_ALLOWLIST = "enforces_tool_allowlist"
    PRESERVES_ACTIVE_TIME_BUDGET = "preserves_active_time_budget"
    SUPPORTS_VISIBLE_OUTPUT = "supports_visible_output"


@runtime_checkable
class AgentStepExecutor(Protocol):
    """Executes a workflow step by delegating it to an agent."""

    name: str
    capabilities: frozenset[AgentCapability]

    def execute(self, ctx: AgentStepContext) -> AgentStepResult: ...
```

`@runtime_checkable Protocol`, never an ABC — `.spec/CONSTITUTION.md` → *Ports*.

```python
@dataclass(frozen=True)
class AgentStepContext:
    request: RunRequest          # F1's object — provenance and inputs, not a new shape
    step_name: str
    instructions: str
    tools: tuple[str, ...]
    inputs: Mapping[str, Any]
    time_budget_s: float | None

@dataclass(frozen=True)
class AgentStepResult:
    value: Any
    tool_calls: tuple[Mapping[str, Any], ...] = ()
```

> `AgentStepContext` **carries** a `RunRequest` rather than restating its fields. That is why
> this feature is sequenced behind F1: built earlier it would have invented a parallel shape.

## 2. The declaration

```python
@dataclass(frozen=True)
class AgentStep:
    name: str
    instructions: str
    executor: str | None = None                  # None = the single registered one, else by name
    tools: Sequence[str] = ()
    requires: frozenset[AgentCapability] = frozenset()
    time_budget_s: float | None = None
```

`_NODE_TYPES` (`workflow/_validation.py:28`) becomes `(Step, Gate, AgentStep)`.

**Declaring `tools=[…]` implies `requires={ENFORCES_TOOL_ALLOWLIST}`.** An author who
constrains tools has stated an intent, and satisfying it silently-not-at-all is the failure
this feature exists to prevent. It can be widened explicitly, never narrowed implicitly.

## 3. Registration

```python
app.register_agent_step_executor(executor: AgentStepExecutor) -> None
```

Registered, never auto-discovered — `GateResolver`'s shape (`_gate/_resolver.py`).

## 4. The provider table

```python
# src/functualize/_engine/agent_providers.py
EXECUTOR_PROVIDERS: dict[str, str] = {
    "cli-prompt":      "functualize",       # core
    "mcp-elicitation": "functualize-mcp",
    "ai":              "functualize-ai",
}

CORE_EXECUTORS: frozenset[str] = frozenset({"cli-prompt"})

def missing_executor_hint(name: str) -> str:
    """Empty string for a core name — if a core executor is unregistered the
    answer is not "install something", it is that the registry was built by hand."""
```

Copied from `_gate/_strategy.py:40-66`, including `CORE_*`. Ships **before** there are two
implementations (decision **C5**).

## 5. Errors

```python
class AgentExecutorUnavailableError(FunctualizeError): ...   # none registered — names the package
class AgentCapabilityRefusedError(FunctualizeError): ...     # registered, cannot honour `requires`
```

Both raised at **validation**, before the walk starts. Each maps to an exit code through F2's
outcome module — no new exit code, no second vocabulary.

## 6. Public re-exports

```python
from functualize.workflow import AgentStep
from functualize.plugin import AgentStepExecutor, AgentCapability, AgentStepContext, AgentStepResult
```

## 7. Unchanged

- `Step`, `Gate`, `Edge`, `ConditionalEdge`, `END`.
- `GateResolver`, `GateStrategy`, `GateContext`, `STRATEGY_PROVIDERS`.
- The walk's BFS, `visited` set, join readiness and replay-skip.
- `_execute_lifecycle`'s 20 steps.
