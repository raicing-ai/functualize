# Plan — tool-call-approval

## Alignment

Approved Shape Intent: Confluence SD page
`15007864` — *Shape Intent — Tool-Call Approval for
ToolScope.approval_required() (gate contract, denial, per-tool scope)*,
**version 3**, updated 2026-10-13 07:08:25 UTC, field table `Status |
Approved`, `Authority | Approved` (read live at authoring time; the
approval moved only those two field rows from v2, so the decisions stand
**as drafted** with no `Dn → x` override).

Surfaces in scope, in the shape's own words (boundaries table):

- "What happens when the model calls a tool resolved from a scope marked
  `approval_required()`, on every in-tree path (`AI.run`,
  `PydanticAI.run_agent_loop`, `PydanticAI.run_with_history`)"
- "The gate's call contract (inputs, return, error behaviour)"
- "What the model and the caller see on a denial"
- "How approval composes under `ToolScope.__add__` and `with_instructions`"
- "Adding approval members to the public `ToolDef` (a plugin-API change,
  called out)"
- "`docs/guides/ai.md:103` and the method docstrings agreeing with the
  code"
- "Tests that drive a gated scope through the agent loop and observe the
  refusal, plus an ungated control"

Surfaces out of scope, in the shape's own words:

- "A UI, CLI prompt or remote service for humans to approve calls. The
  gate is a callable, and what the callable does is the user's business"
- "Durable pause/resume of an AI run waiting for a human (pydantic-ai
  deferred tools, D2b/D7b), recorded as a follow-up direction"
- "Redesigning core's `awaits_input` / gate registry (the issue body puts
  this out of scope)"
- "**Any functualize core public-API change.** None is needed under the
  recommendation"
- "Third-party `AIProvider` implementations outside this repository
  (Risk 3)"

Decisions implemented, as approved: D1=A (enforce), D2=2a (no gate ⇒ deny
every call), D3=3.1a/3.2a/3.3a/3.4 (positional triple, strict `True`
admits, gate exception ends the run unrelabelled, sync only), D4=4a+4.2a
(refused tool result, loop continues, `AI_TOOL_CALLED status="denied"`,
`ToolCallRecord` unchanged), D5=5a (approval follows each tool; AND on
double-apply and on duplicate names; gated wins regardless of order),
D6=6a (`requires_approval` + `approval_gate` on `ToolDef`; AND-folded at
`to_tool_defs`), D7=7a (the scope's own gate, enforced in the translator's
wrapper; 7b/7c are recorded follow-ups, not built), D8=8a (docs rewrite
with a real gate and the deny-all form). Risk 3 (third-party providers)
is left open by the maintainer exactly as the shape records it — no
protocol change, no 7d double-gating.

## Architecture gate

### Retrieval record (what was actually run, at base `c75a476e`)

- **rg / git grep** (counts and negatives, each re-runnable):
  - `git grep -n -E 'requires_approval|approval_gate|approval_required|_approval'` over `src plugins docs tests examples` → outside `_tool_scope.py`, `tests/plugins/test_tool_scope.py`, `docs/guides/ai.md:103`: no consumers (`tests/test_error_types.py:76,81` is an unrelated core gate-error field). The defect premise.
  - `git grep -n -E 'tool_def\.function|\.function\(' -- plugins` (non-test, non-README) → exactly `_tool_translator.py:60,79`. H1's positive half.
  - `git grep -n -E '\.function\b' -- src` → all hits are core's `Job`/`JobDescriptor.function`, a different type. H1's negative half.
  - `git grep -n 'to_tool_defs'` → call sites `_ai.py:207,209`, `_pydantic_ai.py:223` only.
  - `git grep -n '\.translate(' -- plugins` → `ToolScopeTranslator.translate` called from `_provider.py:115`, `_pydantic_ai.py:99,177`; the `functualize-mcp` hits are that plugin's own descriptor translator, a different class that never touches `ToolDef.function`.
  - `git grep -n 'status="success"' -- plugins` → exactly the three `AI_TOOL_CALLED` emitters: `_pydantic_ai.py:128,204`, `_ai.py:260`.
- **zvec-grep** (prose pass, index built this session, scoped globs):
  `zg query "tool call approval gate ToolScope approval_required enforce"` → hits only in `_tool_scope.py` and `docs/guides/ai.md`; no ADR or guide decides tool-call approval. `zg query "documented control nothing enforces it resolves but does nothing"` → no decision record for this control; the pitfall class is known generically (`docs/guides/workflows.md` capabilities prose, ADR-012 negative sections). Prior art = the shape page + DC-116 (SD/10158118), already read live.
- **serena**: `get_symbols_overview` on `_tool_scope.py` (ToolScope surface: 12 methods) and `_tool_translator.py` (`ToolScopeTranslator.translate/_translate_single`); reference questions answered by the git greps above (recorded as such).
- **graphify**: not run — no `graphify-out/` index exists in this checkout, and building one for a two-package region whose call graph is already fully enumerated above (three entry paths, one choke point, verified by rg) buys nothing the three completed passes have not already established. Recorded here because the architecture gate names all three tools; a reader can weigh the omission.
- **Runtime experiment** (design-critical, on the locked `pydantic-ai` 1.107.0, `TestModel`): a tool exception escapes `agent.run_sync` as the **original** exception type, unwrapped (E5's precondition); a refusal string returned as the tool result flows through and the run completes (E2's precondition).

### BEFORE

```
functualize-ai (domain plugin, provider-agnostic)      functualize-ai-pydantic (implementation plugin)
───────────────────────────────────────────            ──────────────────────────────────────────────
ToolScope                                              AI.run(tools=scope)            _ai.py:171
  __init__/_approval_required/_approval_gate ──┐         │ to_tool_defs([])  _ai.py:207,209
  __add__ merges approval scope-wide           │         ▼
  requires_approval / approval_gate (props)◄───┼─ only readers
  to_tool_defs()  _tool_scope.py:207           │        PydanticAI.run_agent_loop  _pydantic_ai.py:96,99
        │ never consults approval              │        PydanticAI.run_with_history _pydantic_ai.py:174,177
        ▼                                      │              │ _resolve_tool_defs → to_tool_defs  :223
     list[ToolDef]  ── no approval member ─────┼──────┐       │
        (public surface, crosses the           │      ▼       ▼
         plugin boundary into any              │   PydanticAIProvider.run _provider.py:113-115
         AIProvider)                           │        │ translate(tools)
                                               │        ▼
                                               └──► ToolScopeTranslator.translate/_translate_single
                                                        _tool_translator.py:48
                                                        _wrapper(**kwargs)  :81
                                                        return original_fn(**kwargs)  :82  ◄ runs ungated
                                                        Tool.from_schema(..., takes_ctx=False) :88-94
                                                        pydantic_ai.Agent(model, tools=…)  :250/:298

AI_TOOL_CALLED emitters (3): _ai.py:260, _pydantic_ai.py:128, :204 — all status="success", hardcoded
Generic-exception relabelers (3): _ai.py:289-292, _pydantic_ai.py:110-114, :186-190 — AINotAvailableError(str)
```

Smells the BEFORE carries (catalogue names):

- **Dead code** — `_approval_required` / `_approval_gate` and their merge
  in `__add__` have no consumer beyond the two properties; the documented
  control does nothing (Refactoring.Guru: unused code that will
  eventually rot). This feature is the removal-by-consumption of it.
- **Implicit callable convention** — `gate: Callable[..., Any] | None`
  and `approval_gate: Callable[..., Any] | None` are untyped callables;
  the Constitution bans this shape for ports, and the same reasoning
  (no IDE support, no contract) applies to a safety-critical callback.
  C3's typed signature removes it.

### AFTER

```
functualize-ai                                          functualize-ai-pydantic
────────────                                            ─────────────────────
ToolScope                                                 (same three entry paths)
  _ScopeFilter.approval: _FilterApproval|None  ◄ per-filter      │
  approval_required(gate) stamps EVERY filter                │ (unchanged plumbing)
  __add__ concatenates filters unchanged                    ▼
  requires_approval: any filter gated (property)         ToolScopeTranslator._translate_single
  approval_gate: first gate, "not authoritative"             _wrapper(**kwargs):
        │                                                       if tool_def.requires_approval:
        ▼                                                         refusal = evaluate_tool_approval(tool_def, kwargs)   ◄── _approval.py
     to_tool_defs()                                                │            strict is True; gate exceptions marked + re-raised
        first-seen dedup for the def itself,                       ▼ refused  → return refusal message (C5 text)
        approval from EVERY matching filter AND-folded ──►        ▼ admitted → return original_fn(**kwargs)
     ToolDef(requires_approval=…, approval_gate=folded) ──►  Tool.from_schema(...) (unchanged)
  _types.py: ToolCallContext (frozen; job_name, description) ── consumed by _approval.py, exported publicly
  _approval.py (new, provider-agnostic, pure):
     refusal_message(tool_name) / is_tool_refusal(result, tool_name)
     evaluate_tool_approval(tool_def, args) -> str | None
     mark_gate_failure(exc) / unwrap_gate_failure(exc) -> BaseException | None

Event emitters (3, unchanged sites): status = "denied" if is_tool_refusal(tc.result, tc.tool_name) else "success"
Relabelers (3, unchanged sites):    original = unwrap_gate_failure(exc); if original is not None: raise original
```

Boundary crossings in the AFTER, checked against the seven import-linter
contracts: `functualize_ai_pydantic → functualize_ai` (implementation →
domain, already the established direction — `from functualize_ai import
AI, ToolScope, …` and `from functualize_ai._errors import …` exist
today); `ToolDef`/`ToolCallContext` cross from the domain plugin to the
implementation plugin and to any third-party provider as declared public
surface. No `src/functualize/**` module is touched; no contract sees a
new edge. `ToolScope` stays at zero imports from implementation plugins
(`test_zero_ai_plugin_dependencies` keeps guarding that; `_approval.py`
imports nothing provider-side).

Smells the AFTER introduces — checked per the gate loop:

- The refusal-predicate couples producer and consumers by an observable
  string, not a typed field (see *Surviving smells* S1).
- The exception marker is an informal protocol on exception instances
  (S2).
- No forbidden pattern from the Constitution's list is introduced: no
  peer-layer import (plugins, not core), no god-object growth
  (`_tool_scope.py` stays well under 500 LOC; `_approval.py` is ~60), no
  global mutable state (the marker is per-exception, not module state),
  no ABC, no `DeprecationWarning` shims — the old scope-level merge
  fields are **removed**, not deprecated (pre-release stance).

## Design skills consulted

- `.claude/skills/python-design-patterns` (the repo's own skill: KISS,
  separation of concerns, single responsibility, composition over
  inheritance) — the per-filter stamp keeps approval a property of the
  filter it was declared on (single responsibility) rather than a
  scope-wide flag blurring every filter's meaning.
- Session-available user skill `design-patterns-refactoring` (carries the
  Refactoring.Guru catalogue used for the smell names above and below —
  *dead code*, *implicit callable convention* is the catalogue's
  "function with no clear contract" family; confirmed present in the
  session listing, and named here as the vocabulary source).

## Surviving smells

- **S1 — primitive obsession on the refusal discriminator** (`_approval.py`
  `is_tool_refusal`, consumed by the three `AI_TOOL_CALLED` emitters). A
  raw string equality decides `status="denied"` because shape D4.2a
  fixes `ToolCallRecord` unchanged, so no typed field exists to carry
  "this result was a refusal". Accepted, not flagged for maintainer
  review: it is the direct, approved consequence of D4.2a; the producer
  and the matcher share one helper (C5), so they cannot drift; and the
  only failure mode is an honest tool that returns the exact refusal
  text for its own name being *reported* as denied — an event-field
  misclassification, never a gating error. Revisit if `ToolCallRecord`
  ever gains a status member.
- **S2 — informal protocol via an exception attribute**
  (`_approval.py` `mark_gate_failure` / `unwrap_gate_failure`). The gate's
  exception must reach the caller **as its own type** (D3.3a, E5), so it
  cannot be wrapped in a typed error, and the three generic relabelers
  cannot isinstance-check an arbitrary user exception — so the marker
  rides on the exception instance and the relabelers look for it.
  Accepted, not flagged: the alternative (a typed wrapper) would change
  the exception type the caller sees, which the approved decision
  forbids; verified feasible and unwrapped end-to-end on the locked
  pydantic-ai 1.107.0. If pydantic-ai ever wraps tool exceptions, the
  marker check extends to the `__cause__` chain — noted in schema.md.

No other smell survives: the BEFORE's dead code is consumed, and the
implicit callable convention is typed away (C3).

## Technical approach

1. `functualize_ai/_types.py`: add `ToolCallContext`; add the two
   `ToolDef` members (C2). Export `ToolCallContext` from
   `functualize_ai/__init__.py` (`__all__` + lazy map, next to `ToolDef`).
2. `functualize_ai/_approval.py` (new, pure, provider-agnostic):
   `refusal_message`, `is_tool_refusal`, `evaluate_tool_approval`
   (strict `is True`; marks + re-raises gate failures),
   `mark_gate_failure`, `unwrap_gate_failure`.
3. `functualize_ai/_tool_scope.py`: `_FilterApproval` frozen dataclass;
   `_ScopeFilter.approval`; `approval_required()` stamps every filter
   (append gate to each filter's tuple — double-apply ANDs by
   construction); `__add__` concatenates filters unchanged, drops the
   scope-level merge; properties computed from filters (C4);
   `with_instructions` passes filters through; `to_tool_defs()` keeps
   first-seen-wins for the def, AND-folds approval from every matching
   filter, gated wins regardless of order, folds gate tuples into one
   `approval_gate` callable (0 gates ⇒ `None` + `requires_approval=True`).
4. `functualize_ai_pydantic/_tool_translator.py`: `_wrapper` calls
   `evaluate_tool_approval(tool_def, kwargs)` before `original_fn`;
   returns the refusal message on denial; gate failures propagate marked.
5. `functualize_ai_pydantic/_pydantic_ai.py`: both loops — event
   `status` via `is_tool_refusal`; relabel arm checks
   `unwrap_gate_failure` first and re-raises the original.
6. `functualize_ai/_ai.py`: `run()` — same two changes at its emission
   and relabel sites.
7. `docs/guides/ai.md:101-104` — D8's exact replacement block + three
   prose sentences; docstrings of `approval_required`,
   `requires_approval`, `approval_gate`, `ToolDef`, `ToolCallContext`.
8. Tests: `tests/plugins/test_tool_scope.py` (scope-level: stamping,
   properties, AND, gated-wins, E10) and
   `plugins/domains/functualize-ai-pydantic/tests/test_tool_approval.py`
   (E1–E9 with `TestModel`, incl. `AI.run` path via `PydanticAIProvider`
   and event-bus capture).

## Files to change

- `plugins/domains/functualize-ai/src/functualize_ai/_types.py`
- `plugins/domains/functualize-ai/src/functualize_ai/_approval.py` (new)
- `plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py`
- `plugins/domains/functualize-ai/src/functualize_ai/_ai.py`
- `plugins/domains/functualize-ai/src/functualize_ai/__init__.py`
- `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_tool_translator.py`
- `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py`
- `tests/plugins/test_tool_scope.py` (additions; existing approval tests reviewed for the property-semantics change)
- `plugins/domains/functualize-ai-pydantic/tests/test_tool_approval.py` (new)
- `docs/guides/ai.md`

## Risks

- **Risk 3 (shape, open by maintainer):** third-party `AIProvider`s
  receive `ToolDef`s that declare approval but nothing forces them to
  check. Not fixed here (7a as approved); the shape records 7d / a
  documented protocol obligation as the options if it ever bites.
- **H2 (shape):** a plain refusal string is assumed enough for real
  models to re-plan. E2 pins the scripted-model half; real-model
  behavior stays a hypothesis, exactly as the shape states.
- **pydantic-ai drift:** the unwrapped-exception and
  refusal-as-result behaviors were verified on the locked 1.107.0 this
  session; a future unlock that wraps tool exceptions would surface as
  E5 failing (marker then needs the `__cause__`-chain walk, prepared in
  the design).
- **Intended behavior change** (disclosed, not a risk to mitigate):
  `a.approval_required(g) + b` no longer gates `b`'s tools; the
  scope-level stored fields and their `__add__` merge are removed
  (pre-release, no back-compat obligation). Existing property-based
  tests were grepped: none reference approval beyond
  `tests/plugins/test_tool_scope.py`, whose `test_union_merges_approval`
  asserts `requires_approval is True` on a mixed union — still true under
  the any-filter property semantics, so it stands; `to_tool_defs`
  behavior tests are added fresh.
