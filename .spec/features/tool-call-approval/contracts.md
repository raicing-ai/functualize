# Contracts — tool-call-approval

External interfaces this feature declares or changes. All are surfaces of
the two AI plugin packages; functualize core's public API is untouched.

## C1. `ToolCallContext` — new public type (plugin-API change)

`functualize_ai._types.ToolCallContext`, re-exported from the
`functualize_ai` package `__all__` next to `ToolDef`:

```python
@dataclass(frozen=True)
class ToolCallContext:
    job_name: str | None   # ToolDef.job_name verbatim (None for plain callables)
    description: str       # ToolDef.description verbatim
```

Frozen; carries only what the translator wrapper holds. No
provider-private data (pydantic-ai's `RunContext` is expressly rejected by
the shape, D3.1c). Adding members later is additive; gates read it, the
plugin writes it.

## C2. `ToolDef` — two new public members (plugin-API change, called out)

Appended after `config_class`, both defaulted, additive — every existing
construction (positional and keyword) stays valid (E10):

```python
@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    job_name: str | None = None
    function: Callable[..., Any] | None = None
    config_class: type | None = None
    requires_approval: bool = False
    approval_gate: Callable[[str, dict[str, Any], ToolCallContext], bool] | None = None
```

Encoding: `(False, None)` = ungated (today's behavior);
`(True, None)` = deny every call (D2a); `(True, g)` = `g` must return
exactly `True`. `to_tool_defs()` folds multiple AND-ed gates into a single
`approval_gate` callable (shape D5 edge rules + D6 6a). A provider-agnostic
reader can tell gated tools apart without calling anything.

## C3. `ToolScope.approval_required` — typed signature (was untyped)

```python
def approval_required(
    self,
    gate: Callable[[str, dict[str, Any], ToolCallContext], bool] | None = None,
) -> ToolScope
```

Stamps required + gate on every filter already in the scope. No gate ⇒
deny every call from that scope. The old `Callable[..., Any]` form was an
implicit callable convention; the typed parameter closes it.

## C4. `ToolScope.requires_approval` / `ToolScope.approval_gate` — properties

- `requires_approval`: `True` iff **any** filter in the scope carries
  approval (i.e. any resolved tool would be gated).
- `approval_gate`: the first gate in filter order, or `None`. Docstring
  marks it **not authoritative for mixed scopes** — per-tool gating is
  read from the resolved `ToolDef`s (D5 edge rule).

## C5. Refusal message — observable format contract

A denied call's tool result, seen by the model, by the caller through
`AIResult.tool_calls[*].result`, and matched by the event emitters:

```
Tool call refused: approval required for '<tool_name>'.
```

Produced and recognized by the same helper in `functualize_ai._approval`
so the wrapper (producer) and the three `AI_TOOL_CALLED` emitters
(consumers) cannot drift apart.

## C6. `AI_TOOL_CALLED` event payload — new `status` value

The existing `status` payload field gains `"denied"`. A refused call is
emitted with `tool_name`, `args`, `duration_ms`, `status="denied"`, and
its `ToolCallRecord.result` is the refusal text. `"success"` remains the
value for every admitted call. Emission sites: `_ai.py` `AI.run`,
`_pydantic_ai.py` `run_agent_loop`, `_pydantic_ai.py` `run_with_history`
— all three today hardcode `"success"`.

## C7. Gate exception surfacing — error-contract change

A gate that raises ends the run with the gate's **own exception**,
unwrapped and unrelabelled, from all three entry paths (`AI.run`,
`run_agent_loop`, `run_with_history`). The generic
`except Exception → AINotAvailableError` relabeling still applies to every
other exception. Feasibility verified on `pydantic-ai` 1.107.0: a tool
exception escapes `agent.run_sync` as its original type.

## C8. Unchanged surfaces (fences)

- `ToolCallRecord` — unchanged (no `status` member; shape 4.2a).
- `AIProvider` protocol — unchanged. Third-party providers receive
  `ToolDef`s that declare approval but are not forced to check (shape Risk
  3, left open by the maintainer; options 7d / documented obligation
  recorded in the shape, not taken here).
- `ToolScope` factories (`only`, `tagged`, `group`, `functions`),
  `with_instructions`, `instructions`, `+` (union) — public behavior
  unchanged except where C3/C4 redefine the approval semantics.
- functualize core (`src/functualize/**`) — untouched.
