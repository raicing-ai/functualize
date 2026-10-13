# Schema — tool-call-approval

Internal types and formats. Public surface is in `contracts.md`; this file
holds what sits underneath.

## `_FilterApproval` — `functualize_ai/_tool_scope.py` (new, private)

```python
@dataclass(frozen=True)
class _FilterApproval:
    # Gates declared for this filter, in declaration order.
    # Empty tuple = approval required with NO gate = deny every call.
    gates: tuple[Callable[[str, dict[str, Any], ToolCallContext], bool], ...] = ()
```

`_ScopeFilter` gains `approval: _FilterApproval | None = None`
(`None` = filter is ungated; stamped = its tools require approval).
`_ScopeFilter` stays frozen; stamping replaces the filter instance, never
mutates it.

## Gate folding — `to_tool_defs()` time (private)

For each resolved tool name, the gates from **every** filter that matched
the name concatenate in filter order:

- 0 gates, stamped → `ToolDef(requires_approval=True, approval_gate=None)`
  (deny every call, D2a)
- 1 gate → `approval_gate` is that gate, identity-preserved
- N gates → one closure, strict-AND:

```python
def _fold_gates(gates):
    if not gates:
        return None
    if len(gates) == 1:
        return gates[0]
    def combined(tool_name, args, context):
        return all(g(tool_name, args, context) is True for g in gates)
    return combined
```

Short-circuit `all(... is True ...)`: a later gate never runs after an
earlier denial; a raising gate's exception propagates untouched (D3.3a).

## Refusal message — exact format (produced and matched in one place)

```python
def refusal_message(tool_name: str) -> str:
    return f"Tool call refused: approval required for '{tool_name}'."

def is_tool_refusal(result: Any, tool_name: str) -> bool:
    return result == refusal_message(tool_name)
```

`functualize_ai/_approval.py` owns both; the translator wrapper produces,
the three `AI_TOOL_CALLED` emitters match. Single source; no literals
elsewhere (enforced by review — the string appears in exactly one
non-test source file).

## Gate-failure marker — exception attribute (private)

```python
_GATE_FAILURE_ATTR = "_functualize_ai_approval_gate_failure"

def mark_gate_failure(exc: BaseException) -> BaseException   # best-effort setattr, returns exc
def unwrap_gate_failure(exc: BaseException) -> BaseException | None
```

`unwrap_gate_failure` checks `exc` itself first; if pydantic-ai ever
wraps tool exceptions, it then walks `__cause__` (one level is enough for
the observed wrapping styles) and returns the deepest marked exception,
else `None`. Verified on 1.107.0: no wrapping occurs today — the check on
`exc` itself is the live path. If `setattr` fails (exotic slots-bearing
exception), the exception propagates unmarked and is relabelled —
fail-loud on the relabel, never silently admitted; a gate that raises has
still not run the tool.

## `evaluate_tool_approval` — the single decision function (private module, public behavior)

```python
def evaluate_tool_approval(tool_def: ToolDef, args: dict[str, Any]) -> str | None:
```

- `tool_def.requires_approval` false → `None` (run; zero overhead beyond
  one attribute read).
- No gate → refusal message (deny every call).
- Gate called positionally `(tool_def.name, args, ToolCallContext(...))`;
  result `is True` → `None` (run); anything else → refusal message.
- Gate raises → `mark_gate_failure(exc)`; bare `raise`.

The translator's `_wrapper` is the only caller (D7a enforcement point):

```python
def _wrapper(**kwargs):
    refusal = evaluate_tool_approval(tool_def, kwargs)
    if refusal is not None:
        return refusal
    return original_fn(**kwargs)
```

## Event payload values

`AI_TOOL_CALLED.status` ∈ {"success", "denied"} — `"denied"` is new;
emitted exactly when `is_tool_refusal(tc.result, tc.tool_name)` holds for
that record. No other payload field changes.

## State

None. No registries, no module-level mutable state, no persistence — the
approval state is immutable data flowing scope → `ToolDef` → wrapper.
