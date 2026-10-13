# Feature: tool-call-approval

Behavioral specification. What the change must do, not how. The decision
record for every choice below is the approved Shape Intent SD/15007864 v3
(`Authority: Approved`, 2026-10-13); where this file and that page could
disagree, the page wins and this file is wrong.

## Problem

`ToolScope.approval_required()` is documented as a safety control
(`docs/guides/ai.md:103`, "Add instructions and approval requirements") but
nothing consumes the flag or the gate:

- `_tool_scope.py:168-182` writes `_approval_required` / `_approval_gate`;
  the only readers are the two properties (`:193-201`).
- `to_tool_defs()` (`_tool_scope.py:207`) never consults either field.
- `ToolDef` (`functualize_ai/_types.py:50-59`) has no approval member.
- Every in-tree path to execution goes through
  `ToolScopeTranslator._translate_single`'s `_wrapper`
  (`functualize_ai_pydantic/_tool_translator.py:81-82`), which calls
  `original_fn(**kwargs)` ungated.

Verified at base `c75a476e` by `git grep -n -E
'requires_approval|approval_gate|approval_required|_approval'` over `src`,
`plugins`, `docs`, `tests`, `examples`: outside `_tool_scope.py` itself,
`tests/plugins/test_tool_scope.py`, and the docs line, there are no hits
(`tests/test_error_types.py:76,81` matches an unrelated core gate-error
field name).

## Required behavior

### 1. A gated tool call does not run unless the gate admits it

When the model calls a tool whose `ToolDef` carries approval state, the
gate runs **before** the tool function. The call executes only if the gate
returns exactly `True` (strict `is True`; `False`, `None`, and any truthy
non-bool deny — fail-closed against a gate that forgets to `return`).

### 2. `approval_required()` with no gate denies every call

The documented call form `scope.approval_required()` — no gate argument —
refuses every call to that scope's tools. The tools stay visible to the
model; each call returns the refusal text. Failing closed is the intent
(shape D2a).

### 3. The gate contract

- Signature: `gate(tool_name: str, args: dict[str, Any], context:
  ToolCallContext) -> bool`, called positionally. `ToolCallContext` is a
  plugin-owned frozen dataclass in `functualize_ai._types`, exported next
  to `ToolDef`, carrying `job_name: str | None` and `description: str` —
  exactly what the translator wrapper holds; nothing provider-private.
- Synchronous gates only (the wrapper is synchronous).
- A gate that raises: the tool does not run, and the gate's own exception
  propagates out of the AI call to the caller. It must **not** be
  relabelled `AINotAvailableError` (today `_pydantic_ai.py:110-114`,
  `_pydantic_ai.py:186-190`, and `_ai.py:289-292` relabel every generic
  exception). The exception surfaces unwrapped, verified feasible on the
  locked `pydantic-ai` 1.107.0 (a tool exception escapes `agent.run_sync`
  as the original type).

### 4. What a denial does

- The model sees the tool's result as the fixed refusal text:
  `Tool call refused: approval required for '<tool_name>'.`
- The agent loop continues; the run completes normally.
- Observability: a refused call emits `AI_TOOL_CALLED` with
  `status="denied"` (new value of the existing payload field; today all
  three emission sites hardcode `status="success"`). The record in
  `AIResult.tool_calls` keeps the refusal text as its `result`;
  `ToolCallRecord` itself is unchanged (shape 4.2a).

### 5. Approval follows each tool, not the combined scope

- `approval_required()` stamps required + gate on **each filter already in
  the scope**; `__add__` concatenates filters unchanged. So
  `a.approval_required(g) + b` gates `a`'s tools only; `b`'s tools run
  ungated (behaviour change from today's whole-scope merge — today's merge
  enforces nothing, so no user can depend on gating happening; the
  *property values* are preserved, see below).
- Applying approval twice to the same tools
  (`.approval_required(g1).approval_required(g2)`): both gates must admit
  (AND). A later call can never weaken an earlier one.
- The same tool reached through a gated and an ungated filter
  (`b + a.approval_required(g)` resolving the same name): the tool is
  gated, regardless of filter order. Approval requirements from every
  filter that matched the name combine (AND). First-seen-wins dedup
  otherwise keeps today's behavior for everything else about the def.
- `with_instructions` keeps per-filter approval unchanged.
- Properties on a mixed scope: `requires_approval` is `True` if **any**
  tool requires approval; `approval_gate` returns the first gate in filter
  order and is documented as not authoritative for mixed scopes.

### 6. The approval state travels on `ToolDef`

`ToolDef` gains `requires_approval: bool = False` and
`approval_gate: Callable[[str, dict[str, Any], ToolCallContext], bool] |
None = None`, appended after `config_class` with defaults, so every
existing construction stays valid. `(True, None)` encodes "deny every
call". AND-ed gates fold into a single `approval_gate` callable when
`to_tool_defs()` runs. This is a plugin-API change, called out in
`contracts.md`.

### 7. Enforcement point

The gate is enforced in `ToolScopeTranslator._translate_single`'s wrapper
(`_tool_translator.py`), the single choke point every in-tree entry path
crosses: `AI.run` → `PydanticAIProvider.run` (`_provider.py:115`),
`PydanticAI.run_agent_loop` (`_pydantic_ai.py:99`), and
`PydanticAI.run_with_history` (`_pydantic_ai.py:177`) all call
`ToolScopeTranslator.translate`. The translator reads only `ToolDef` —
it never reaches back into `ToolScope`.

## Regression fences (must not change)

- A scope that never called `approval_required()` behaves exactly as
  today: same tools, same schemas, same results, same events
  (`status="success"`).
- `ToolDef` construction that does not mention approval keeps working,
  positional and keyword (E10).
- `ToolCallRecord` is unchanged.
- No functualize core (`src/functualize/**`) change.

## Out of scope (shape boundaries, in the shape's own words)

- "A UI, CLI prompt or remote service for humans to approve calls. The
  gate is a callable, and what the callable does is the user's business"
- "Durable pause/resume of an AI run waiting for a human (pydantic-ai
  deferred tools, D2b/D7b), recorded as a follow-up direction"
- "Redesigning core's `awaits_input` / gate registry"
- "**Any functualize core public-API change.** None is needed under the
  recommendation"
- "Third-party `AIProvider` implementations outside this repository
  (Risk 3)" — under D7a they receive `ToolDef`s that declare approval,
  but nothing forces a provider outside this repo to check. Recorded as a
  residual risk, not fixed here.

## Acceptance criteria

The falsifiable tests E1–E10 are pinned exactly as the shape defines them.
All agent-loop tests (E1–E9) drive the loop with pydantic-ai's scripted
`TestModel` — no network, no API key.

| # | Setup | Must hold |
|---|---|---|
| E1 | `ToolScope.functions([delete])`, no approval; model calls `delete` | `delete` runs once; result/events identical to today (control) |
| E2 | `.approval_required()` (no gate); model calls the tool | tool **never runs**; model's tool result is the refusal text; run completes; `AI_TOOL_CALLED` has `status="denied"` |
| E3 | `.approval_required(lambda n, a, c: a["id"] != 1)`; model calls `delete(id=1)` then `delete(id=2)` | first refused, second runs; gate received `("delete", {"id": 1}, ToolCallContext(...))` |
| E4 | gate returns `None` / `1` / `"yes"` | denied in every case (strict `is True`) |
| E5 | gate raises `RuntimeError` | tool does not run; the `RuntimeError` reaches the caller, **not** as `AINotAvailableError` |
| E6 | `a.approval_required(deny_all) + b`; model calls one tool from each | `a`'s tool refused, `b`'s runs |
| E7 | `b + a.approval_required(g)`; both resolve the same tool name | the tool is gated, whatever the order |
| E8 | `.approval_required(allow_all).approval_required(deny_all)` | refused (AND) |
| E9 | E2's scenario via `AI.run(tools=scope)` **and** via `PydanticAI.run_agent_loop` **and** via `run_with_history` | identical refusal on all three entry points |
| E10 | construct `ToolDef(name=..., description=...)` positionally and by keyword | still valid; new members default to ungated |

Plus, at authoring time (verified, and re-run as task gates):

- `git grep -n -E '\.function\b'` over `plugins/**/src` and `src/**` lists
  every execution-reach of `ToolDef.function`; in-tree plugin sources hold
  exactly two mentions, both in `_tool_translator.py` (`:60` None-check,
  `:79` the captured `original_fn` called at `:82`). `src/` hits are
  core's `JobDescriptor.function`, a different type. This is H1 from the
  shape: the translator is the only in-tree place a `ToolDef.function`
  executes.
- `docs/guides/ai.md` and the code agree (AC4 of the carrying issue): the
  example block at `ai.md:101-104` is rewritten per shape D8 with a real
  gate, the no-gate deny-all form, and the three semantics sentences;
  `approval_required`, `requires_approval`, `approval_gate`, and `ToolDef`
  docstrings change with it.
