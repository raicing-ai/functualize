# gate-name-resolution — Specification

Status: **Specify complete, awaiting member confirmation** (D1 below is open).
Base: `master` at `e7a93bf`. Branch: `fix/gate-name-resolution`.

## Problem

A workflow author declares `Gate(name="approve_refund", awaits=Approval)`. The
gate's name is canonicalized at declaration time (`src/functualize/_types/workflow.py:315`
— *"A gate name is a node address — the string used to resume it — so it
canonicalizes like every other address"*), so the walk opens, records and reports
the gate as `approve-refund`. Every public path that *answers* a gate then
compares the caller's string to that canonical key **byte for byte**, so the
spelling the author wrote in their own workflow cannot address the gate.

The repository already owns the policy that says it should:
`src/functualize/_types/naming.py:99` `resolve_name` — *"A job still has exactly
one identity — you simply cannot miss it by writing it the way Python spells it."*
No gate-answer path calls it (`rg -n "resolve_name" src/functualize/app` → only
`utils.py` re-export and `vault.py:243,251`).

### Observed on `e7a93bf` (probe, one blocked scope `rel-1`, gate declared `approve_refund`)

| Entry point, called with `"approve_refund"` | Returns today |
|---|---|
| `resolve_gate(store, "rel-1", …)` / `resolve_gate(store, None, …)` | `gate_not_found` |
| `answer_gate(app, store, "rel-1", …)` | `gate_not_found` |
| `resume_scope(…, gate="approve_refund", input=…)` | `gate_not_found` |
| `gate_draft(app, store, "rel-1", …)` | `gate_unresolvable` — *"AttributeError: 'NoneType' object has no attribute 'awaits'"* |
| `deposit_gate_input(app, store, "rel-1", …)` | `gate_unresolvable` — same AttributeError text |
| any of the above with `"approve-refund"` | works; `resume_scope` → `success` |

Pending list shows `['approve-refund']`; after all underscore attempts the scope
is still `blocked` with `payload None`.

### Premise corrections against the issue text

1. **There is no MCP `resume_gate` tool on `master`.** It was replaced by
   `answer_gate` and removed, not aliased (`tests/plugins/test_mcp_workflow_tools.py:273`).
   The MCP gate tools are `answer_gate`, `get_gate_draft`, `resume_workflow`,
   and `list_workflows(blocked_on=…)` (`plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py:244,272,317,338`).
2. **`deposit_gate_input` has no production caller.** `rg -n 'deposit_gate_input' src plugins`
   → the definition, its `utils.py` re-export (`:142,:210`) and docstrings only.
   The CLI `func builtin workflow answer` / `resume` and the fused `--wf-input`
   path call `answer_gate` / `resume_scope` (`_cli/builtins.py:1453,1455,1555`,
   `app/adapters/workflow_flags.py:422,428`). It stays in scope because it is a
   public, documented function (`docs/guides/workflows.md:226`).
3. **The failure is not uniformly `gate_unresolvable`.** Most entries refuse
   with `gate_not_found`; only the two that skip the store check and go straight
   to the model lookup misreport it as `gate_unresolvable` carrying an
   `AttributeError` — a *misclassified* refusal, which is a second defect.
4. **Every surface already refuses visibly.** The CLI maps both codes to exit 1
   (`_cli/builtins.py:1113,1116`); the fused `--wf-input` path exits 1 or 2
   (`workflow_flags.py:423-430`); MCP returns the envelope to the agent. The
   "caller can ignore it" risk is confined to direct Python callers of the
   `app.utils` functions — the same contract as the other 43 lines that build a
   refusal envelope in `app/_workflow_{answer,resume,control}.py`
   (`rg -c '"error"|_error\(' …` → 13 + 6 + 24).

## User stories

- **US-1** As a workflow author, I answer a gate by the name I declared
  (`approve_refund`), on any surface, and the walk resumes past it.
- **US-2** As an operator reading `func builtin workflow list`, I can paste the
  canonical name it prints (`approve-refund`) or the declared one — both work.
- **US-3** As a caller who mistypes a gate, I get `gate_not_found` naming the
  gates that *do* exist in that scope, never an internal `AttributeError`.

## Behavior

- **B-1** A gate reference is resolved against the gate names recorded in the
  addressed scope using the project's single naming policy (`resolve_name`):
  exact match first, then canonical-form match. Any spelling whose canonical
  form equals exactly one recorded gate addresses that gate.
- **B-2** Resolution happens **once per public entry**, before any store read,
  draft write, candidate append or model lookup, so every subsequent step —
  the store key, the draft key, the model lookup and the returned `gate`
  field — uses the canonical name.
- **B-3** The returned `gate` field (and every message naming the gate) carries
  the canonical name, so a response is directly reusable as input on any surface.
- **B-4** A reference matching no recorded gate returns `gate_not_found`, whose
  message names the scope and lists its gate names. A reference matching more
  than one returns `ambiguous_gate` with candidates (unreachable with today's
  declarations — `src/functualize/workflow/_validation.py:7` rejects duplicate
  node names, and names are already canonical — but defined).
- **B-5** `gate_unresolvable` is reserved for its documented meaning — *the
  model won't load* (the workflow cannot be materialized). A node missing from a
  loadable declaration is `gate_not_found`, never an `AttributeError` string.
- **B-6** The `blocked_on` filter of `list_scopes` (CLI `--blocked-on`, MCP
  `list_workflows(blocked_on=…)`) applies the same resolution, so the declared spelling filters
  the same as the canonical one.
- **B-7** Canonical-spelling behavior is unchanged: every existing test passes
  without edit.

## Decision D1 — unknown gate: raise, or return a correctly-classified envelope?  (OPEN, member)

Recommendation: **(b) return `gate_not_found`**, reclassified and informative.

| | (a) Raise a new `GateNotFoundError` | (b) Return `{"error": "gate_not_found", …}` (recommended) |
|---|---|---|
| Python API | Cannot be ignored | Same contract as the other refusals of these functions; still ignorable |
| CLI | `workflow answer`, `resume`, `--wf-input` each need a new `except` — otherwise a traceback + exit 1 (`contributor/reference/pitfalls.md` §25: *"This has now happened twice"*) | Already exit 1 via `_workflow_exits` (`_cli/builtins.py:1113`) — no change |
| MCP | Tool call becomes a protocol-level tool error instead of a structured envelope the agent can read `gate_not_found` + candidates from | Unchanged; the agent reads the gate list and retries |
| `resume_scope` / `workflow_flags._record` | Must catch and re-envelope, or change their own contracts | Unchanged |
| Consistency | One exception among 43 envelope sites in the same three modules | Consistent; `.spec/STATUS.md:1155` records *"the exception is returned, never raised"* as a deliberate invariant elsewhere |
| Conflict with PR #71 | New type lands in `_types/errors.py`, which PR #71 also edits (+97 lines) | None |

The issue's own acceptance line — *"an unknown name must fail loudly rather than
return a value a caller can ignore"* — is met by (a) only. (b) meets it on every
**surface** (CLI exit code, MCP envelope) but not for a direct Python caller who
discards the return. The root cause the issue observed (the declared name
silently not working) is fixed by B-1/B-2 under either option. Choosing (a)
adds tasks to the graph (exception type, three CLI catches, MCP translation) and
sequences this branch behind PR #71.

## Decision D2 — where to canonicalize  (SETTLED by evidence)

At the public entries in `app/`, **not** inside `Declaration.node()`.
Canonicalizing in `Declaration.node()` (`_types/workflow.py:902`) fixes only the
model lookup: the store is keyed by the canonical name the engine wrote
(`_primitives/gate_requests.py:180`, `_engine/gate_service.py:105,140,149`), and
`answer_gate` reads `store.get_gate(scope_id, gate)` with the raw string at
`_workflow_answer.py:195` *before* the model lookup — so it would still return
`gate_not_found`. It also edits `_types/workflow.py`, which PR #71 rewrites
(+123 lines), sequencing this branch behind that merge. The issue's proposed fix
(resolve inside `_resolve_gate_model`) has the same gap.

## Acceptance criteria

Fixture throughout: a workflow `build → Gate(name="approve_refund") → deploy → END`,
blocked at the gate in scope `rel-1`.

- **AC-1** `answer_gate(app, store, "rel-1", "approve_refund", {…complete…})`
  returns `status == "answered"`, `gate == "approve-refund"`; then
  `resume_scope(app, store, "rel-1")` returns `status == "success"` and `deploy`
  has a step record.
- **AC-2** `gate_draft(app, store, "rel-1", "approve_refund")` returns the draft
  report with no `error` key and `gate == "approve-refund"`.
- **AC-3** MCP: `answer_gate(values=…, gate="approve_refund")`,
  `get_gate_draft(workflow_id="rel-1", gate="approve_refund")`, and
  `resume_workflow(workflow_id="rel-1", input=…, gate="approve_refund")` each
  succeed, and the last one walks past the gate.
- **AC-4** CLI: `func builtin workflow answer rel-1 approve_refund --input '{…}'`
  exits 0 and answers the gate; the fused `<entry> release --wf-resume rel-1
  --wf-input '{…}' --wf-gate approve_refund` path records it and walks on
  (`workflow_flags.py:422` → `resolve_gate`).
- **AC-5** Near-miss: `"approve_refund"`, `"approve-refund"`, `"approveRefund"`
  and `"Approve_Refund"` each reach the one gate, through `resolve_gate` (both
  the scope-and-gate and the gate-only form), `answer_gate`, `gate_draft` and
  `deposit_gate_input`.
- **AC-6** Unknown name `"nope"`, through each entry of AC-5: `error ==
  "gate_not_found"`, the message names `approve-refund`, and contains no
  `AttributeError`. CLI `workflow answer rel-1 nope` exits 1 with an `Error:`
  line and no traceback. *(Under D1-(a) this AC becomes "raises
  `GateNotFoundError`; CLI exits 1 with no traceback".)*
- **AC-7** `deposit_gate_input(app, store, "rel-1", "approve_refund", {…})`
  returns `status == "input_accepted"` with `gate == "approve-refund"`.
- **AC-8** `list_scopes(app, store, blocked_on="approve_refund")`
  (`app/_workflow_view.py:261`; CLI `workflow list --blocked-on`, MCP
  `list_workflows`) returns `rel-1`.
- **AC-9** `gate_unresolvable` is returned only when the workflow cannot be
  materialized (a scope whose `workflow` names no registered job).
- **AC-10** Full suite green with no edit to an existing test.

## Out of scope

- `Declaration.node()` and `_types/workflow.py` (D2; PR #71 owns that file).
- The engine's gate-record key format (already canonical).
- Removing or re-homing `deposit_gate_input` despite its zero production callers
  — recorded as a surviving smell in `plan.md`, not acted on here.
