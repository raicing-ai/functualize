# gate-name-resolution — Plan

Prerequisite state: `spec.md` written, **member confirmation pending** (D1 open).
This plan is drafted for D1-(b). If the member picks (a), `spec.md` AC-6 and
this plan's T1/T2 change, and T4b (CLI/MCP translation) is added — see *Risks*.

## Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`) —
  single responsibility, KISS.
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — smell
  names and their routing (`cheatsheet.md`: Shotgun Surgery → Move Method;
  Primitive Obsession → Replace Data Value with Object).

## Layers and boundaries

All modules touched are in the public `app/` package; the one internal module
consumed is `_types/naming.py` (foundation). `app → _types` is legal: `app/` is
public and already imports `_types` at module level (`_workflow_control.py:37`,
`_workflow_answer.py:37`). No import-linter contract changes. `lint-imports`
is in every task's gate rather than assumed.

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

## AFTER

```
 surfaces (unchanged)                          app/  (public)                                                     internals
 ────────────────────                          ────────────────────────────────────────────────                   ─────────────────
 _cli/builtins.py answer/resume/list ──raw──▶ ┌────────────────────────────────────────────┐
 workflow_flags._record ──raw──────────────▶ │ public entries                              │
 MCP answer_gate/get_gate_draft/            │  resolve_gate · answer_gate · gate_draft   │
     resume_workflow/list_workflows ─raw──▶ │  deposit_gate_input · list_scopes(blocked_on)│
                                             │  resume_scope → answer_gate                 │
                                             └───────────────┬────────────────────────────┘
                                                             │ raw, ONCE, first statement
                                                             ▼
                                   _workflow_resume._canonical_gate(known, raw)
                                     known = the scope's gate keys            ──────▶ _types/naming.resolve_name
                                     → canonical str                                    (exact, then canonical form)
                                     | {"error":"gate_not_found", gates:[…]}
                                     | {"error":"ambiguous_gate", candidates:[…]}
                                                             │ canonical
                                                             ▼
                              store.get_gate / get_gate_draft / put_gate_draft ──▶ _primitives/scope_store
                              _resolve_gate_model(canonical)                    ──▶ _types/workflow.Declaration.node
                                 node is None → gate_not_found (explicit, no AttributeError)
                                 materialize fails → gate_unresolvable (unchanged meaning)
```

Dependency direction unchanged; one new edge `app/_workflow_resume → _types/naming`
(foundation; legal). `_workflow_answer` and `_workflow_view` already import
from `_workflow_resume`, so no new module-level edge between app modules.
No file in `_types/`, `_primitives/`, `_engine/`, `_cli/` or the MCP plugin
changes.

## Technical approach

- `_canonical_gate(known: Iterable[str], gate: str) -> str | dict[str, Any]`
  in `app/_workflow_resume.py`. Entries pass `scope.get("gates") or {}` — the
  keys the engine wrote, i.e. exactly the answerable gates; `resolve_gate`'s
  scan and `list_scopes` pass the pending names. Translate
  `resolve_name`'s `LookupError`: message contains `"ambiguous"` →
  `ambiguous_gate` with candidates computed as the names whose canonical form
  matches; otherwise `gate_not_found` with `gates`.
  **Note:** `resolve_name` step 3 (last-segment match for undotted candidates)
  is harmless here — gate names are single-segment — but the task's tests pin
  a dotted miss to `gate_not_found` anyway.
- `resolve_gate`: both-named branch replaces `store.get_gate(scope_id, gate) is
  None` with `_canonical_gate`; the gate-only scan compares by resolving
  against each scope's candidate list (pending or all), collecting
  `(sid, canonical)`.
- `answer_gate`, `gate_draft`, `deposit_gate_input`: after the scope read,
  `gate = _canonical_gate(scope, gate)`; return the envelope if it is one. In
  `gate_draft` add the missing `scope is None → workflow_not_found` guard it
  lacks today (it reads `or {}`, which would otherwise surface as
  `gate_not_found` with an empty list — acceptable but less precise).
- `_resolve_gate_model`: `node = declaration.node(gate)`; `if node is None:
  return None, gate_not_found envelope`, before touching `.awaits`. The broad
  `except` stays for materialization failures only.
- `list_scopes`: compare `blocked_on` by resolving against each scope's pending
  names; a `LookupError` means "does not match this scope", not an error.

## Files to change (hit set of research.md § 3b)

| File | Task |
|---|---|
| `src/functualize/app/_workflow_resume.py` | T1 |
| `src/functualize/app/_workflow_answer.py` | T2 |
| `src/functualize/app/_workflow_view.py` | T3 |
| `tests/workflow/test_gate_name_resolution.py` (new) | T1, T2, T3 |
| `tests/integration/test_gate_name_resolution_e2e.py` (new) | T4 |
| `docs/guides/workflows.md`, `CHANGELOG.md` | T5 |
| `.spec/STATUS.md` | T7 |

No `schema.md`: no internal type moves.

## Risks

- **R1 — returned `gate` spelling changes** from the caller's string to the
  canonical one. A caller comparing `result["gate"] == "approve_refund"` would
  change meaning. Every in-repo consumer compares against canonical names;
  AC-10 (no existing test edited) is the check.
- **R2 — D1 flips to (a).** Adds: `GateNotFoundError` in `_types/errors.py`
  (conflicts with PR #71 — branch must rebase after #71 merges), CLI catches in
  `_cli/builtins.py` `workflow answer`/`resume`, `workflow_flags._record`, and
  MCP translation in `_workflow_tools.py`, plus a real-terminal check for
  pitfall §25. Roughly doubles the file set.
- **R3 — test isolation.** A bare script does not see the scope it wrote
  (research.md probe note); integration tests must use the repo fixtures.

## Surviving smells

| Smell | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| **Primitive Obsession** | the `gate: str` parameter on six public functions | Removing it (a `GateRef` value object) changes six public signatures for no behavior the member asked for; `_canonical_gate` confines the raw→canonical conversion to one function called first in each entry | **Yes** — a later feature could introduce `GateRef`; asking whether that is wanted |
| **Dead Code** (candidate) | `deposit_gate_input` — zero production callers since `answer_gate` replaced it | Public and documented (`docs/guides/workflows.md:226`); removing a public function is a separate, member-level decision. This feature fixes it in place so it is not left behaving differently from its siblings | **Yes** — keep, deprecate, or remove in a follow-up |

Neither is on `.spec/CONSTITUTION.md` → *Forbidden Patterns*. The god-object
rule (`CONSTITUTION.md:95`, a *class* past ~500 LOC) is not engaged — all three
modules hold functions, not a class — but sizes are recorded because one is
already large: `wc -l` today `_workflow_resume.py` 175, `_workflow_answer.py`
454, `_workflow_view.py` **563**. T3 is written as a net-zero-line
predicate swap in `list_scopes` so it does not grow `_workflow_view.py`; T6
re-measures all three.
