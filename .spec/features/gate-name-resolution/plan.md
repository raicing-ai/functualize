# gate-name-resolution — Plan

Revised 2026-10-01 for the member's answers: D1 = **(a) raise**, `gate: str`
stays, `deposit_gate_input` fixed in place, spec confirmed. Base rebased to
`ef1939d` (PR #71 merged). The architecture below supersedes the 2026-09-30
draft for D1-(b); the BEFORE map and the rejected candidates are unchanged.

## Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`) —
  single responsibility, KISS.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — smell
  names and their routing (`cheatsheet.md`: Shotgun Surgery → Move Method;
  Primitive Obsession → Replace Data Value with Object).

## Layers and boundaries

- **Foundation:** `_types/errors.py` gains `GateNotFoundError`; `_types/naming.py`
  is consumed, unchanged. `_types` imports nothing internal (contract
  *Types import nothing internal*), and the new class imports nothing.
- **Public `app/`:** `_workflow_resume.py`, `_workflow_answer.py`,
  `_workflow_view.py`, `adapters/workflow_flags.py`, and the `utils.py`
  re-export. `app → _types` is legal and already used at module level
  (`_workflow_control.py:37`, `_workflow_answer.py:37`).
- **`_cli/`:** `builtins.py` may import only the public API (contract *_cli uses
  public API only*, `pyproject.toml:354-367`), so it takes the exception from
  `functualize.app.utils`, exactly as it takes `ScopeStoreUnreadableError`
  today (`_cli/builtins.py:1147`).
- **Plugin:** `functualize_mcp/_workflow_tools.py` takes it from
  `functualize.app.utils` too (the route `_refuse_unreadable_scopes` uses,
  `_workflow_tools.py:92`).
- No import-linter contract changes; `lint-imports` is in every task's gate.

## BEFORE

```
 surfaces (public / adapters)                        app/  (public)                                         internals
 ─────────────────────────────                       ─────────────────────────────────────────────          ─────────────────────────
 _cli/builtins.py  workflow answer ─raw gate──────▶ _workflow_answer.answer_gate ─┬─ store.get_gate(raw) ──▶ _primitives/scope_store
                   workflow resume ─raw gate──┐                  gate_draft ────┤   (keys = canonical,      (gate records keyed by
                   workflow list --blocked-on ┼─┐                               │    written by               node.name)
 app/adapters/workflow_flags._record ─raw─▶ resolve_gate (name == gate) ─┐      │    _engine/gate_service
 MCP _workflow_tools  answer_gate ──raw──▶ resolve_gate ─────────────────┤      │    :105,140,149)
                      get_gate_draft ─raw▶ resolve_gate ─────────────────┤      │
                      resume_workflow ─raw┐                              │      └─ _resolve_gate_model(raw)
                      list_workflows ──raw┼──────────────────────────────┼──────▶   declaration.node(raw) ─▶ _types/workflow.Declaration
                                          ▼                              │          None → .awaits
               _workflow_control.resume_scope ─raw─▶ answer_gate         │          AttributeError → "gate_unresolvable"
               _workflow_view.list_scopes  (name == blocked_on)          │
 (no production caller) ──────────▶ _workflow_resume.deposit_gate_input ─┘ ─raw─▶ same two lookups

                                          _types/naming.resolve_name   ◀── consumed by _engine, _discovery, app/vault.py
                                                                            NOT by any gate path
```

Arrows point from caller to callee. Every `raw` edge carries the caller's
string unchanged to one of **13 exact-match lookups** (research.md § 3b: 14
hits, one of them a false positive).

### Smells the BEFORE already carries

| Smell (catalogue) | Where | Evidence |
|---|---|---|
| **Shotgun Surgery** | the gate-name comparison is spread over `resolve_gate` (`_workflow_answer.py:79,100`), `answer_gate`, `gate_draft`, `deposit_gate_input`, `_resolve_gate_model`, `list_scopes` (`_workflow_view.py:319`) | Fixing the spelling rule today means touching every one of them; the issue's "proposed fix" touched one and missed the rest |
| **Primitive Obsession** | the gate reference is a bare `str` at every signature, indistinguishable from the canonical key it is compared to | A raw caller string and a store key have the same type, so nothing forces conversion before `store.get_gate` |
| **Duplicate Code** (the policy, not the text) | `resolve_name` (`_types/naming.py:99`) exists; gate paths re-implement "matching" as `==` | `rg resolve_name src/functualize/app` → no gate path |
| **Dead Code** (candidate) | `deposit_gate_input` — zero production callers | research.md premise table |
| Misclassified error via broad `except Exception` | `_resolve_gate_model` (`_workflow_resume.py:85`) turns a *lookup miss* into `gate_unresolvable` | probe output |

## Candidate AFTERs considered

1. **Canonicalize inside `Declaration.node()`** (the issue's "resolve before
   lookup" at the model layer). Rejected: fixes 1 of the lookups; the store key
   stays raw (`answer_gate` refuses before reaching the model); edits
   `_types/workflow.py`, which PR #71 rewrites. Introduces nothing new but
   leaves the Shotgun Surgery intact.
2. **Canonicalize inside `ScopeStore.get_gate`/`put_gate_draft`**. Rejected:
   pushes a namespace decision into the storage layer (`_primitives/`), which
   ADR-022 (*storage is a substrate, not a key-value domain*) keeps free of
   meaning; would also need the known-name set, which the store would have to
   read back — a reader rebuilding what the writer knows (`pitfalls.md` §22).
3. **Introduce a `GateRef` value object** (Replace Data Value with Object — the
   textbook answer to Primitive Obsession). Rejected for this fix: changes six
   public signatures, and the smell it removes is contained by (4) at far lower
   cost. Recorded as surviving.
4. **One resolver function in `app/_workflow_resume.py`, called once at the top
   of each public entry** (Move Method: the comparison moves to one place, the
   entries call it). **Chosen.** Checked for introduced smells: it adds one
   function and one call per entry — no Middle Man (it does real work: calls
   `resolve_name`, builds the refusal), no Feature Envy (it reads only the
   names it is handed), no new Shotgun Surgery (a future spelling rule
   changes `resolve_name` or this function only).

## Candidate AFTER for D1-(a): where the exception is translated

Prior art fixes the shape: `ScopeStoreUnreadableError` is **raised in the
library and translated at each surface** — the CLI's `_workflow_refusal()`
context manager (`_cli/builtins.py:1144-1153`, wrapping every `builtin
workflow` command, 11 uses) and the MCP `_refuse_unreadable_scopes` decorator
(`_workflow_tools.py:78-103`, 10 uses). `GateNotFoundError` follows it.

- **5a. Catch it in each `app/` caller and re-envelope** (`resume_scope`,
  `workflow_flags._record`). Rejected: it turns the exception back into a value
  one layer up, which is (b) with extra steps, and `resume_scope` would differ
  from `answer_gate`.
- **5b. Widen `_refuse_unreadable_scopes` to catch both.** Rejected: its name
  and docstring say *unreadable scopes*, and it wraps all 10 tools including
  ones that never take a gate. Widening it trades a clear name for
  *Divergent Change* (one decorator changing for two unrelated reasons).
- **5c. One new arm per surface, beside the existing one.** **Chosen.** CLI:
  one `except GateNotFoundError` arm in `_workflow_refusal()` (exit 1, the code
  `gate_not_found` already maps to); fused flags: one `try` in
  `workflow_flags._record`; MCP: a small `_refuse_unknown_gates` decorator on
  the three gate-taking tools. Checked for introduced smells: three translation
  sites is the number of surfaces, not *Shotgun Surgery* — each one is the
  surface's existing refusal seam, and a change to the error's *content*
  touches only C-1.

## AFTER

```
 surfaces                                          app/  (public)                                                 foundation (_types/)
 ────────                                          ─────────────────────────────────────────────                  ────────────────────
 _cli/builtins.py
   _workflow_refusal()  ◀── catches ──┐
     ├ workflow answer [--show] ──raw─┼─────────▶ answer_gate · gate_draft ─────────────┐
     ├ workflow resume --gate ────raw─┼─────────▶ resume_scope → answer_gate ────────────┤
     └ workflow list --blocked-on ─raw┼─────────▶ list_scopes (filter, never raises) ───┤
 app/adapters/workflow_flags._record  │                                                 │ raw, ONCE, first
   try/except ◀── catches ────────────┼──raw────▶ resolve_gate(scope, gate) · answer_gate┤
 functualize_mcp/_workflow_tools.py   │                                                 ▼
   @_refuse_unknown_gates ◀─ catches ─┤          _workflow_resume._canonical_gate(known, raw, scope_id)
     answer_gate / get_gate_draft /   │            known = scope's gate keys ─────────────────▶ _types/naming.resolve_name
     resume_workflow ───raw───────────┼─────────▶   → canonical str
   list_workflows ─raw────────────────┘              | raise GateNotFoundError ──────────────▶ _types/errors.GateNotFoundError
                                                    deposit_gate_input (no production caller) ─┘
                                                                  │ canonical
                                                                  ▼
                                   store.get_gate / get_gate_draft / put_gate_draft ──▶ _primitives/scope_store
                                   _resolve_gate_model(canonical) ──▶ _types/workflow.Declaration.node
                                      node is None (declaration drift) → gate_unresolvable, explicit message
                                      materialize fails → gate_unresolvable envelope (unchanged meaning)

   functualize.app.utils re-exports GateNotFoundError ──▶ the only door _cli/ and the plugin import it through
```

Arrows point from caller to callee; "catches" edges are where the raised error
is turned into the surface's own refusal (stderr + exit 1, or an MCP envelope).
New edges: `app/_workflow_resume → _types/naming` and `→ _types/errors` (both
foundation; legal), `app/utils → _types/errors.GateNotFoundError` (re-export),
`_cli/builtins` and `functualize_mcp/_workflow_tools → app.utils.GateNotFoundError`
(public door; legal). No edge into `_engine`, `_primitives` or another peer
layer.

## Technical approach

- **C-1** `GateNotFoundError(gate, *, scope_id, known)` in `_types/errors.py`;
  re-export in `app/utils.py` (import block `:80-84`, `__all__` beside
  `ScopeStoreUnreadableError` `:282`).
- `_canonical_gate(known: Iterable[str], gate: str, *, scope_id: str) -> str` in
  `app/_workflow_resume.py`: `return resolve_name(gate, sorted(known))`; any
  `LookupError` → `raise GateNotFoundError(gate, scope_id=scope_id,
  known=sorted(known)) from None`. Ambiguity cannot reach here with canonical
  keys (spec B-4); if a legacy scope makes it reachable, it raises the same
  error, whose `known` lists both keys.
  `resolve_name` step 3 (last-segment match) is harmless — gate names are
  single-segment — and a test pins a dotted miss to the exception.
- **Addressed entries resolve first:** `deposit_gate_input`, `answer_gate`,
  `gate_draft` call `_canonical_gate(scope.get("gates") or {}, gate,
  scope_id=scope_id)` immediately after the scope read. `gate_draft` gains the
  `scope is None → workflow_not_found` guard it lacks. `resolve_gate`'s
  both-named branch does the same and returns `(scope_id, canonical)`.
- **Survey paths never raise** (spec B-8): `resolve_gate`'s scan resolves per
  scope inside `try/except GateNotFoundError: continue`; no candidate keeps the
  existing envelope. `list_scopes` does the same as a filter (net-zero lines).
- `_resolve_gate_model`: `if node is None:` return a `gate_unresolvable`
  envelope saying the workflow *no longer declares* the gate, before `.awaits`.
  After B-2 a typo cannot reach this line — only declaration drift can — so it
  is not `GateNotFoundError` (which carries a `scope_id` this function does not
  have, and means a caller error). The broad `except` stays for
  materialization failures.
- **Surfaces:** CLI `_workflow_refusal()` arm → `click.echo(f"Error: {exc}",
  err=True)`, `SystemExit(1)`. `workflow_flags._record` → same. MCP
  `_refuse_unknown_gates` → `_error("gate_not_found", str(exc))` plus
  `"gates": list(exc.known)`.

## Files to change (hit set of research.md § 3b plus the D1-(a) census)

| File | Task |
|---|---|
| `src/functualize/_types/errors.py`, `src/functualize/app/utils.py` | T1 |
| `src/functualize/_cli/builtins.py`, `src/functualize/app/adapters/workflow_flags.py` | T2 |
| `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py` | T3 |
| `src/functualize/app/_workflow_resume.py` | T4 |
| `src/functualize/app/_workflow_answer.py` | T5 |
| `src/functualize/app/_workflow_view.py` | T6 |
| `tests/types/test_gate_not_found_error.py` (new) | T1 |
| `tests/cli/test_gate_not_found_refusal.py` (new) | T2 |
| `tests/plugins/test_mcp_gate_not_found.py` (new) | T3 |
| `tests/workflow/test_gate_name_resolution.py` (new) | T4, T5, T6 |
| `tests/integration/test_gate_name_resolution_e2e.py` (new) | T7 |
| `docs/guides/workflows.md`, `CHANGELOG.md` | T8 |
| `.spec/STATUS.md` | T10 |

No `schema.md`: no internal type moves. The census behind the surface rows:
`rg -n 'resume_scope\(|answer_gate\(|gate_draft\(|deposit_gate_input\(|resolve_gate\('
src plugins` (non-test, non-definition) → `_cli/builtins.py:1453,1455,1555`,
`workflow_flags.py:422,428`, `_workflow_tools.py:283,287,320,324,346`,
`_workflow_control.py:330`; the `_gate_registry.resolve_gate` hits
(`_app/impl.py`, `_app/gates_facade.py`, `_engine/capabilities/invoke.py`) are a
different, same-named method and are untouched.

## Risks

- **R1 — returned `gate` spelling changes** from the caller's string to the
  canonical one. Every in-repo consumer compares against canonical names; AC-10
  (no existing test edited) is the check.
- **R2 — the surfaces translate before anything raises.** T2 and T3 add catch
  arms in wave 1; the raisers land in waves 2–4. Between those waves the arms
  have no production raiser. Disclosed with `# TRANSITIONAL(gate-name-resolution/T4):`
  on each arm and removed by T9, which proves each arm reachable by sabotage.
  The reverse order would leave a window where the CLI prints a traceback.
- **R3 — a direct Python caller of `answer_gate` / `gate_draft` /
  `deposit_gate_input` / `resume_scope` that passed an unknown gate used to get a
  dict and now gets an exception.** That is D1's intent. No in-repo caller relies
  on the old dict for an *addressed* unknown gate: the three existing tests that
  assert `gate_not_found` all go through the survey paths B-8 keeps
  (`tests/workflow/test_gate_drafts.py:469-472`, `tests/plugins/test_mcp_workflow_tools.py:431-434`,
  `tests/integration/test_mcp_workflow_loop_e2e.py:191`) or accept either code
  (`tests/plugins/test_mcp_workflow_tools.py:508,688`).
- **R4 — test isolation.** A bare script does not see the scope it wrote
  (research.md probe note); tests use the repo fixtures.

## Surviving smells

| Smell | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| **Primitive Obsession** | the `gate: str` parameter on six public functions | **Answered** — member, 2026-10-01: *"it's ok the gate name stays plain string"*. `_canonical_gate` confines the raw→canonical step to one function called first in each entry | Answered |
| **Dead Code** (candidate) | `deposit_gate_input` — zero production callers | **Answered** — member, 2026-10-01: *"fix it in place"* | Answered |
| Two refusal styles in one function (plain description; no catalogue name fits) | `resolve_gate` raises for an addressed scope and returns an envelope for a survey | The split follows meaning, not convenience: "this scope has no such gate" is a caller error, while "no live workflow is waiting at that name" is a survey answer that also covers *answered, not pending*. Raising there would break the three survey tests in R3 and the MCP agent loop that reads `workflow list` from that envelope | No — stated to the member with the plan so they can overrule it |
| Duplicate Code (pre-existing, untouched) | `functualize_mcp/_workflow_tools.py:106` `_canonical` normalizes *tool* names with its own helper | Out of scope: tool names, not gate names; recorded so the next naming change finds it | No |

None is on `.spec/CONSTITUTION.md` → *Forbidden Patterns*. The god-object rule
(`CONSTITUTION.md:95`, a *class* past ~500 LOC) is not engaged — the `app/`
modules hold functions and `_types/errors.py` holds independent small classes —
but sizes are recorded: `wc -l` on `ef1939d` `_workflow_resume.py` 175,
`_workflow_answer.py` 454, `_workflow_view.py` **563**, `workflow_flags.py`
436, `_workflow_tools.py` 618, `_types/errors.py` 836, `_cli/builtins.py` 3033.
T6 is a net-zero-line predicate swap so `_workflow_view.py` does not grow; T9
re-measures all of them.
