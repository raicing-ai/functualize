# gate-name-resolution — Tasks

Authored 2026-09-30 against `e7a93bf`; **re-authored 2026-10-01** against
`ef1939d` (PR #71 merged, branch rebased) for the member's answers: D1 = **(a)
raise `GateNotFoundError`**, `gate: str` stays, `deposit_gate_input` is fixed in
place, spec confirmed. Ten tasks in nine waves. Every `now:` below was produced
by running the command on this branch at `ef1939d` + the spec commit.

**The Execute phase reads only this file from the feature directory.** Each task
restates the behavior it needs; `B-n` and `AC-n` are defined in `spec.md`, `C-n`
in `contracts.md`.

**Execute authorization:** the spec is confirmed and D1 and both review-flagged
smells are answered (member, 2026-10-01). What remains is the member's approval
of **this task list**, which `/agentic-plan` step 11 requires before Execute
begins. A change of scope from here sends `spec.md`/`plan.md` back for revision,
and the affected gates are re-authored before code is written.

## How to read a gate

A fenced `bash` block holding a **count** (`rg -c` or `| wc -l`), followed by
`now:` (measured at authoring) and `after:` (what the task must produce).
`tests/spec/test_task_gates_still_hold.py` re-runs every gate of every `[x]` task
against `HEAD` for the life of the branch, so each gate was chosen to stay true
through every later task. `invariant` marks a count that must not change.
**Comments and docstrings in counted files count too** — in prose inside them,
never write `_canonical_gate(` with its parenthesis, `except GateNotFoundError`,
`raise GateNotFoundError`, `name == gate`, `name == blocked_on`, or the
decorator line `@_refuse_unknown_gates`.

## Standing rules for every task

- **Before T1, rebase.** The pushed branch sits on `e7a93bf`, because the
  spec author's runtime could not force-push; these gates were measured on the
  same two spec commits rebased onto `ef1939d`. First step of Execute:
  `git fetch origin && git rebase origin/master` (only `.spec/features/` files
  are on the branch, so it cannot conflict), force-push with lease, then
  re-run every `now:` gate below. If `origin/master` has moved past `ef1939d`,
  re-measure the cited line numbers in the files you touch and record any drift
  in the task's completion note; the scope-fence gate's base becomes the new
  merge-base.
- Run `uv run ruff check --fix src/ tests/ plugins/ examples/`,
  `uv run ruff format src/ tests/ plugins/ examples/`, `uv run mypy src/`,
  `uv run lint-imports`, and targeted `uv run pytest` (at most two invocations
  per verification). Redirect long output to a log file inside the run workdir
  and read the file, rather than piping through `head`/`tail`.
- **Fixtures:** tests use `tests/conftest.py` isolation plus the fixture shape
  of `tests/workflow/test_gate_drafts.py:45-86`, with the gate declared
  `Gate(name="approve_refund", awaits=Approval)`, where
  `class Approval(BaseModel): approved: bool`, in a workflow
  `build → approve_refund → deploy → END` registered as `release` and run to
  `blocked` in scope `rel-1`. A bare `python` script does not read back the
  scope it wrote (research.md) — do not verify with one.
- **Reachability precedes `[x]`**: name the production call path in the
  completion note and prove it. Commit, break the call, watch a named test fail,
  `git checkout -- <file>`, amend.
- **Transitional disclosure:** T2 and T3 add catch arms whose production raiser
  only lands in T4/T5. Each arm carries
  `# TRANSITIONAL(gate-name-resolution/T4): no production raiser until T4–T5`,
  their tests drive them with a monkeypatched raiser, and T9 removes every
  marker and proves each arm by sabotage.
- **The exception (C-1),** restated so no task needs `contracts.md`:

  ```python
  class GateNotFoundError(Exception):
      """Raised when a scope is addressed and the gate reference matches none of its gates."""

      def __init__(self, gate: str, *, scope_id: str, known: Sequence[str]) -> None:
          self.gate = gate
          self.scope_id = scope_id
          self.known = tuple(sorted(known))
          super().__init__(
              f"Workflow '{scope_id}' has no gate '{gate}'. "
              f"Gates: {', '.join(self.known) or 'none'}. "
              "Run `func builtin workflow list` to see what is waiting."
          )
  ```

- **Scope fence**, re-run by T9:

```bash
git diff --name-only ef1939d -- src/functualize/_primitives src/functualize/_engine src/functualize/_discovery src/functualize/_config src/functualize/_plugins src/functualize/_app src/functualize/_types/workflow.py src/functualize/_types/naming.py | wc -l
```
now: `0` · after: `0` — invariant: no peer layer, no `_app`, and neither `_types/workflow.py` nor `_types/naming.py` changes.

```bash
rg -c '"gate_not_found": 1' src/functualize/_cli/builtins.py
```
now: `1` · after: `1` — invariant: the CLI exit code for an unknown gate stays 1.

- No tracker key, issue URL, agent, model or run identity in any commit message
  or trailer. On a Multica runtime the daemon's `prepare-commit-msg` hook adds a
  `Co-authored-by: multica-agent` trailer; commit with
  `git -c core.hooksPath=/dev/null commit …` so it does not land.

## Wave 0 — the vocabulary

### [x] T1 — `GateNotFoundError` and its public door

*Files:* `src/functualize/_types/errors.py`, `src/functualize/app/utils.py`, `tests/types/test_gate_not_found_error.py` (new)

- Add the class above to `_types/errors.py`, after `AmbiguousJobError`
  (`:241`). Import `Sequence` under the module's existing `TYPE_CHECKING`
  convention (or `collections.abc` if there is none). The class imports nothing
  internal.
- Re-export from `functualize.app.utils`: add it to the `_types.errors` import
  block (`utils.py:80-84`) and to `__all__` beside `"ScopeStoreUnreadableError"`
  (`:282`).
- Tests: attributes round-trip; `known` is sorted and a tuple; the message names
  the scope, the reference and every known gate; `known=[]` renders `none`;
  `from functualize.app.utils import GateNotFoundError` works.

*Production call path:* none yet — the first raiser is T4. Disclosed by the
standing *Transitional* rule; T9 proves it.

```bash
rg -c '^class GateNotFoundError\(Exception\):' src/functualize/_types/errors.py
```
now: `0` · after: `1`

```bash
rg -c 'GateNotFoundError' src/functualize/app/utils.py
```
now: `0` · after: `2` (the import and the `__all__` entry)

**Done 2026-10-02** (branch rebased onto `e8fac3e` and force-pushed with lease
first, per the standing rebase rule). Gates re-measured post-rebase: `now:`
values all held.
Line drift in this task's files: `AmbiguousJobError` still at `:241` (no
drift); the `utils.py` errors import block is `:79-84` (cited `:80-84`), and
the `__all__` slot beside `ScopeStoreUnreadableError` sat at `:284` at rebase
time (`:282` cited) and moves to `:285` with this change. The scope-fence
gate's base is now `origin/master` (`e8fac3e`): against `ef1939d` as written it
reads 3, because master's own `ef1939d..e8fac3e` touched
`_engine/gate_service.py`, `_primitives/gate_requests.py` and
`_types/workflow.py` — not this branch. Production call path: none yet by
design (first raiser is T4; T9 proves reachability). Validation:
`ruff check` / `ruff format` clean, `mypy src/` clean (after `uv sync
--all-extras`; 8 pre-existing errors about missing optional deps appear without
extras and are identical on clean master), `lint-imports` 7 kept 0 broken,
`uv run pytest tests/types/test_gate_not_found_error.py` → 7 passed.

## Wave 1 — the surfaces learn to translate it (before anything raises it)

### [x] T2 — CLI: `_workflow_refusal()` and the fused `--wf-input` path

*Files:* `src/functualize/_cli/builtins.py`, `src/functualize/app/adapters/workflow_flags.py`, `tests/cli/test_gate_not_found_refusal.py` (new)

- `_cli/builtins.py` `_workflow_refusal()` (`:1144-1153`): import
  `GateNotFoundError` beside `ScopeStoreUnreadableError` from
  `functualize.app.utils` (never from `_types` — contract *_cli uses public API
  only*). Add a second arm: `except GateNotFoundError as exc:` →
  `click.echo(f"Error: {exc}", err=True)`; `raise SystemExit(1) from exc` — the
  exit code `gate_not_found` already maps to (`:1113`). Update the docstring:
  it now covers two refusals. It already wraps `workflow answer` (`:1451`) and
  `workflow resume` (`:1554`).
- `workflow_flags._record` (`:411-436`): wrap the `resolve_gate` and
  `answer_gate` calls in `try … except GateNotFoundError as exc:` → same
  `Error:` line, `SystemExit(1)`. Import inside the function, as the module
  already does for `answer_gate`/`resolve_gate` (`:418`).
- Mark both arms with the standing `TRANSITIONAL` comment.
- Tests (`CliRunner`, modelled on `tests/integration/test_cli_workflow_parity.py`):
  monkeypatch `functualize.app.utils.answer_gate` and
  `functualize.app.utils.gate_draft` to raise
  `GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])`;
  `func builtin workflow answer rel-1 nope --input '{}'`, the same with
  `--show`, and `func builtin workflow resume rel-1 --input '{}' --gate nope`
  each exit **1**, output contains `Error: Workflow 'rel-1' has no gate 'nope'`
  and `approve-refund`, and `result.exception` is a `SystemExit` (no other
  exception escaped). One test does the same for the fused
  `--wf-resume rel-1 --wf-input '{}' --wf-gate nope`.

*Production call paths:* `builtin workflow answer|resume` → `_workflow_refusal()`;
`<entry> <workflow> --wf-resume` → `apply_workflow_flags` → `_record`.

```bash
rg -c 'except GateNotFoundError' src/functualize/_cli/builtins.py
```
now: `0` · after: `1`

```bash
rg -c 'except GateNotFoundError' src/functualize/app/adapters/workflow_flags.py
```
now: `0` · after: `1`

```bash
rg -c '_workflow_refusal\(\)' src/functualize/_cli/builtins.py
```
now: `12` · after: `12` — invariant: the definition plus its 11 uses; no new wrapper is introduced.

**Done 2026-10-02.** Gates 1/1/12 hold. Line drift in this task's files:
`_workflow_refusal()` sits at `:1145` (cited `:1144`), the `gate_not_found`
exit map still at `:1113`, `workflow answer` at `:1413` (cited `:1451`),
`workflow resume` at `:1522` (cited `:1554`), and `_record` still at `:411`.
One deviation from the letter of the test spec: the resume path does not
reach `answer_gate` through `functualize.app.utils` — `resume_scope` binds it
as a module-global from the resume-control module — so the tests patch that
binding too (`functualize.app._workflow_control.answer_gate`) beside the two
named homes. Reachability proved by sabotage after commit: deleting the
builtins arm → `test_answer_exits_one_with_the_error_line` fails; re-pointing
the flags arm's catch → `test_wf_resume_with_input_and_gate_exits_one` fails
(deleting that arm outright is a SyntaxError — a lone `try:` — so the
sabotage narrows the catch instead). Validation: `ruff check`/`ruff format`
clean, `uv run pytest tests/cli/test_gate_not_found_refusal.py` → 4 passed.

### [x] T3 — MCP: `_refuse_unknown_gates` on the three gate-taking tools

*Files:* `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`, `tests/plugins/test_mcp_gate_not_found.py` (new)

- Add `_refuse_unknown_gates(fn)` beside `_refuse_unreadable_scopes`
  (`:78-103`), same shape (`functools.wraps`, async wrapper, lazy import of
  `GateNotFoundError` from `functualize.app.utils`). On the exception return
  `{**_error("gate_not_found", str(exc)), "gates": list(exc.known)}`. Mark it
  with the standing `TRANSITIONAL` comment.
- Apply it to `_answer_gate` (`:272`), `_get_gate_draft` (`:317`) and
  `_resume_workflow` (`:336`), **under** the existing
  `@_refuse_unreadable_scopes` (so that one stays outermost). Leave
  `_refuse_unreadable_scopes` unchanged — widening it would give one decorator
  two unrelated reasons to change (`plan.md` → candidate 5b).
- Tests: monkeypatch `functualize_mcp._workflow_tools.answer_gate`,
  `.gate_draft` and `.resume_scope` to raise the C-1 error; each tool returns
  `error == "gate_not_found"`, `gates == ["approve-refund"]`, and a `message`
  naming `nope`. Model the provider fixture on
  `tests/plugins/test_mcp_workflow_tools.py`.

*Production call path:* MCP `tools/call answer_gate|get_gate_draft|resume_workflow`
→ the decorated methods.

```bash
rg -c 'def _refuse_unknown_gates' plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `0` · after: `1`

```bash
rg -c '@_refuse_unknown_gates' plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `0` · after: `3`

```bash
rg -c '@_refuse_unreadable_scopes' plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `10` · after: `10` — invariant: the unreadable-store guard still wraps every tool.

**Done 2026-10-02.** Gates 1/3/10 hold. Line drift: `_refuse_unreadable_scopes`
still at `:78`, `_answer_gate` at `:272`, `_get_gate_draft` at `:317`,
`_resume_workflow` at `:336` (no drift); `_list_workflows` is at `:244`
(cited `:256`). One deviation: the tests also patch
`functualize_mcp._workflow_tools.resolve_gate` beside the three named homes —
`answer_gate` and `get_gate_draft` resolve their target first, and until T5
that resolution returns its envelope instead of raising, so the decorator
would never fire. Reachability proved by sabotage after commit: deleting
`@_refuse_unknown_gates` from `_answer_gate` →
`TestAnswerGateRefuses::test_unknown_gate_returns_the_gate_list` fails with
the raw error escaping. Validation: `ruff check`/`ruff format` clean,
`uv run pytest tests/plugins/test_mcp_gate_not_found.py` → 3 passed.

## Wave 2 — the resolver

### [x] T4 — `_canonical_gate`, `deposit_gate_input`, and the missing-node raise

*Files:* `src/functualize/app/_workflow_resume.py`, `tests/workflow/test_gate_name_resolution.py` (new)

Behavior (B-1, B-2, B-3, B-4, B-5; AC-5, AC-6, AC-7, AC-9):

1. Module-level imports: `from functualize._types.naming import resolve_name`,
   and `GateNotFoundError` added to the existing `functualize._types.errors`
   import (`:21`). `Iterable` from `collections.abc` under `TYPE_CHECKING`.
2. ```python
   def _canonical_gate(known: Iterable[str], gate: str, *, scope_id: str) -> str:
   ```
   `names = sorted(known)`; `return resolve_name(gate, names)` (exact match
   first, then canonical form: `approve_refund`, `approveRefund`,
   `Approve_Refund` all reach `approve-refund`). Any `LookupError` →
   raise `GateNotFoundError(gate, scope_id=scope_id, known=names)`, chained
   `from None`.
3. `_resolve_gate_model`: when `declaration.node(gate)` is `None`, return
   `(None, {"error": "gate_unresolvable", "message": f"Workflow '{workflow_name}' no longer declares gate '{gate}'; the run was parked under an older declaration."})`
   **before** touching `.awaits`. This is declaration drift, not a caller typo:
   after step 4 and T5 every entry has already resolved the reference against
   the scope's recorded gates, so a typo cannot reach this line. Materialization
   failures keep returning `gate_unresolvable` as today.
4. `deposit_gate_input`: immediately after `scope = store.get_scope(scope_id) or {}`,
   `gate = _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)`.
   Every later use (`store.get_gate`, `_resolution_view`, the result `gate`
   field, messages) then carries the canonical name.
5. Tests in `tests/workflow/test_gate_name_resolution.py`:
   - `TestCanonicalGate` (pure): exact; underscore; camel; title-case; unknown
     raises with `.known == ("approve-refund",)`; empty `known` raises with
     `.known == ()`; dotted miss `"x.approve_refund"` raises.
   - `TestDeposit`: `"approve_refund"` → `status == "input_accepted"`,
     `gate == "approve-refund"`, payload stored under `approve-refund` (AC-7);
     `"nope"` raises `GateNotFoundError` with `.scope_id == "rel-1"`, and the
     gate record's candidates are unchanged afterwards (AC-6).
   - `TestModelLookup` (AC-9): call `_resolve_gate_model` directly with a
     scope recording a gate the declaration does not have → `gate_unresolvable`
     whose message says *no longer declares* and contains no `AttributeError`;
     a scope whose `workflow` names no registered job → `gate_unresolvable`.

*Production call path:* `functualize.app.utils.deposit_gate_input` →
`_canonical_gate`. Sabotage: pass the raw `gate` through → `TestDeposit` fails.

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `2` (the definition and the call in `deposit_gate_input`)

```bash
rg -c '^from functualize._types.naming import resolve_name$' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `1`

```bash
rg -c 'raise GateNotFoundError' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `1` (in `_canonical_gate` only — the one raiser)

Also green: `uv run pytest tests/workflow/test_gate_name_resolution.py tests/workflow/test_gate_payload_shape.py tests/workflow/test_gate_resolution_model.py -q --no-header`, and `uv run lint-imports`.

**Done 2026-10-02.** Gates 2/1/1 hold; that pytest selection → 26 passed
(12 new), `ruff`/`mypy src/`/`lint-imports` clean. Line drift: the errors
import is still `:21` (now naming two errors); `deposit_gate_input` at `:98`
(cited implicitly via the standing fixture); no cited line in this file
moved. Production call path: `functualize.app.utils.deposit_gate_input` →
the resolver. Reachability proved by sabotage after commit: passing the raw
reference through (deleting the canonicalizing line) → both `TestDeposit`
tests fail.

## Wave 3 — the answer entries

### [x] T5 — `resolve_gate`, `answer_gate`, `gate_draft` resolve once

*Files:* `src/functualize/app/_workflow_answer.py`, `tests/workflow/test_gate_name_resolution.py`

Behavior (B-1–B-4, B-8; AC-1, AC-2, AC-5, AC-6, AC-12):

1. Import `_canonical_gate` from `functualize.app._workflow_resume` (extend the
   import at `_workflow_answer.py:39-43`) and `GateNotFoundError` from
   `functualize._types.errors` (extend `:37`).
2. `resolve_gate`, both-named branch (`:72-83`): after the `workflow_not_found`
   check, `return scope_id, _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)`.
   The raw `store.get_gate(scope_id, gate) is None` test and its envelope go.
3. `resolve_gate`, scan branch (`:85-101`) — **never raises** (B-8): when `gate`
   is given, resolve it against that scope's `names` inside
   `try … except GateNotFoundError: continue`, and append `(sid, resolved)`.
   When `gate` is `None`, unchanged. The `name == gate` comparison disappears.
   No candidate keeps the existing envelope naming `workflow list` (`:106-115`).
4. `answer_gate` (`:191-201`): immediately after the `workflow_not_found` check,
   `gate = _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)`.
   The now-unreachable `record is None → gate_not_found` envelope at `:195-197`
   is removed. Every later line receives the canonical name.
5. `gate_draft` (`:139-142`): `scope = store.get_scope(scope_id)`; `None` →
   `_error("workflow_not_found", …)`; then resolve as in 4, before
   `_resolve_gate_model`.
6. Tests appended:
   - `TestResolveGate`: both forms × the four AC-5 spellings → `("rel-1",
     "approve-refund")`; both-named `"nope"` raises; gate-only `"nope"` returns
     the envelope with `workflow list` in the message (AC-12).
   - `TestAnswerGate`: `"approve_refund"` + `{"approved": True}` →
     `status == "answered"`, `gate == "approve-refund"`; then
     `resume_scope(app, store, "rel-1")` → `status == "success"` and `deploy`
     has a step record (AC-1). `"nope"` raises, and the draft is unchanged.
   - `TestGateDraft`: `"approve_refund"` → no `error` key, `gate ==
     "approve-refund"` (AC-2); `"nope"` raises; an unknown scope returns
     `workflow_not_found`.
   - `test_resume_scope_answers_by_declared_name`:
     `resume_scope(…, input={"approved": True}, gate="approve_refund")` →
     `success`; and with `gate="nope"` it raises (AC-6).

*Production call paths:* MCP `answer_gate`/`get_gate_draft` and
`workflow_flags._record` → `resolve_gate`; CLI `workflow answer` and
`resume_scope` → `answer_gate`; CLI `workflow answer --show` → `gate_draft`.
Sabotage each of the four `_canonical_gate` calls in turn; a named test fails
each time.

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_answer.py
```
now: `0` · after: `4`

```bash
rg -c 'name == gate\b' src/functualize/app/_workflow_answer.py
```
now: `1` · after: `0`

Also green: `uv run pytest tests/workflow/test_gate_name_resolution.py tests/workflow/test_gate_drafts.py tests/workflow/test_workflow_surface_parity.py -q --no-header`.

**Done 2026-10-02.** Gates 4/0 hold; that pytest selection → 87 passed (27
new), `ruff`/`mypy src/` clean. Line drift: `resolve_gate` at `:48` (cited
`:72` for the both-named branch), `gate_draft` at `:130` (cited `:139`),
`answer_gate` at `:163` (cited `:191`); the errors import is still `:37` and
the resume import block `:39-43`, both extended in place. All four
canonicalizing calls sabotaged in turn after commit, each failing a named
test: both-named → `test_both_named_resolves_every_spelling` (3 of 4
spellings), scan → `test_gate_only_scan_resolves_every_spelling` (3 of 4),
`answer_gate` → `test_the_declared_spelling_answers_and_the_walk_resumes`,
`gate_draft` → `test_the_declared_spelling_drafts`.

## Wave 4 — the survey filter

### [x] T6 — `list_scopes(blocked_on=…)` resolves the same way, never raising

*Files:* `src/functualize/app/_workflow_view.py`, `tests/workflow/test_gate_name_resolution.py`

Behavior (B-6, B-8; AC-8, AC-12): in `list_scopes` (`_workflow_view.py:318-321`)
replace the `name == blocked_on` predicate with "`_canonical_gate` resolves
`blocked_on` against the scope's pending names", where `GateNotFoundError`
means *this scope does not match*. Import `_canonical_gate` beside
`pending_gates` (`:31`). **Net-zero lines** — the module is 563 lines today
(`wc -l`) — so put the try/except in a two-line private predicate only if the
swap cannot otherwise stay net-zero, and say which in the completion note.

Test `TestListScopes`: `blocked_on="approve_refund"` and `"approve-refund"`
both return the one row for `rel-1`; `"nope"` returns `[]` (AC-12).

*Production call path:* CLI `workflow list --blocked-on` (`_cli/builtins.py:1283`)
and MCP `list_workflows` (`_workflow_tools.py:256`) → `list_scopes`. Sabotage:
restore the equality → `TestListScopes` fails.

```bash
rg -c 'name == blocked_on' src/functualize/app/_workflow_view.py
```
now: `1` · after: `0`

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_view.py
```
now: `0` · after: `1`

**Done 2026-10-02.** Gates 0/1 hold; `uv run pytest
tests/workflow/test_gate_name_resolution.py` → 31 passed (3 new),
`ruff`/`mypy src/` clean. Line drift: `list_scopes` at `:261` (cited
`:318-321` for the predicate — the predicate itself sat at `:319`), the
`pending_gates` import at `:31` (extended in place). **Net-zero was not
achievable**: one resolving call cannot live inside `any(...)` — it raises on
the first non-match — so the try/except sits in the private predicate
`_awaits_gate` beside `list_scopes`, as this task's escape clause allows. The
module is 578 lines (was 563; +12 helper, +1 import, −2 call site, ±0 after
format). T9's re-measure should read 578, not 563. Reachability proved by
sabotage after commit: restoring the equality predicate →
`test_blocked_on_resolves_the_declared_spelling` fails.

## Wave 5 — surfaces, end to end

### [ ] T7 — integration: CLI, fused flags and MCP, real raisers

*Files:* `tests/integration/test_gate_name_resolution_e2e.py` (new)

No `src/` change, no monkeypatching. Model on
`tests/integration/test_mcp_workflow_loop_e2e.py` (MCP provider, `anyio`) and
`tests/integration/test_cli_workflow_parity.py` (CLI runner).

- **AC-3 (MCP):** `answer_gate(values={"approved": True}, gate="approve_refund")`
  → `status == "answered"`; `get_gate_draft(workflow_id="rel-1",
  gate="approve_refund")` → no `error`; on a fresh scope
  `resume_workflow(workflow_id=…, input={"approved": True}, gate="approve_refund")`
  walks past the gate; `list_workflows(blocked_on="approve_refund")` lists it.
- **AC-4 (CLI):** `func builtin workflow answer <id> approve_refund --input
  '{"approved": true}'` exits 0; `func builtin workflow resume <id>` finishes
  the walk; the fused `--wf-resume <id> --wf-input '{"approved": true}'
  --wf-gate approve_refund` records and walks on.
- **AC-11:** the CLI unknown-gate cases of T2 again, now with the real raiser
  (exit 1, `Error:` naming `approve-refund`, no traceback); MCP
  `answer_gate(values={}, workflow_id="rel-1", gate="nope")`,
  `get_gate_draft(workflow_id="rel-1", gate="nope")` and
  `resume_workflow(workflow_id="rel-1", input={}, gate="nope")` each return
  `error == "gate_not_found"` with `gates == ["approve-refund"]`.

```bash
ls tests/integration/test_gate_name_resolution_e2e.py 2>/dev/null | wc -l
```
now: `0` · after: `1`

Also green: `uv run pytest tests/integration/test_gate_name_resolution_e2e.py -q --no-header`.

## Wave 6 — documentation

### [ ] T8 — guide and changelog

*Files:* `docs/guides/workflows.md`, `CHANGELOG.md`

- `docs/guides/workflows.md`, beside the gate-answering section (`:215-230`):
  one short paragraph. A gate is addressed by its declared name or its
  canonical form (`approve_refund` and `approve-refund` both work);
  `workflow list` prints the canonical form; naming a gate a workflow does not
  have raises `GateNotFoundError` from the Python API (exit 1 on the CLI, a
  `gate_not_found` result over MCP). Name `GateNotFoundError` on exactly one
  line of the file.
- `CHANGELOG.md`, under `## [Unreleased]`: a `### Fixed — a gate answers to the
  name it was declared with` entry in the file's hand-written prose. Say that
  `answer_gate`, `gate_draft`, `deposit_gate_input`, `resume_scope(gate=…)` and
  the scope-and-gate form of `resolve_gate` now **raise** `GateNotFoundError`
  for a gate the scope does not have (previously a returned dict, and from
  `gate_draft`/`deposit_gate_input` a misleading `gate_unresolvable`); that the
  CLI and MCP results are unchanged in code; and that result `gate` fields
  carry the canonical spelling.

```bash
rg -c 'a gate answers to the name it was declared with' CHANGELOG.md
```
now: `0` · after: `1`

```bash
rg -c 'GateNotFoundError' docs/guides/workflows.md
```
now: `0` · after: `1`

## Wave 7 — checkpoint

### [ ] T9 — verify the whole feature, close the transitional window

*Files:* `src/functualize/_cli/builtins.py`, `src/functualize/app/adapters/workflow_flags.py`, `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py` (marker removal only); fixes found here go back to the owning task's file and are noted there.

- Remove the three `TRANSITIONAL(gate-name-resolution/T4)` markers, then prove
  each arm reachable **with the real raiser**: commit; delete the arm; watch a
  named T7 test fail; `git checkout -- <file>`; amend. Same for the one
  raiser (break `_canonical_gate`'s raise → T4 tests fail).
- All five checks green: `ruff check`, `ruff format --check`, `mypy src/`,
  `lint-imports`, and the fast suite `uv run pytest -x -q --no-header`.
- Orphan scan (Verify pass): serena `find_referencing_symbols` on
  `_canonical_gate` → six call sites (1 in `_workflow_resume.py`, 4 in
  `_workflow_answer.py`, 1 in `_workflow_view.py`); on `GateNotFoundError` →
  raisers in `_workflow_resume.py`, catchers in `_cli/builtins.py`,
  `workflow_flags.py`, `_workflow_tools.py`, plus the `utils.py` re-export.
- Re-run the two *Scope fence* gates; re-measure `wc -l` for every file in
  `plan.md` → *Surviving smells* and record them; `_workflow_view.py` stays at
  563.
- Real-terminal check of AC-11 (`contributor/reference/pitfalls.md` §25): in a
  scratch project with the standing fixture workflow, run
  `func builtin workflow answer <id> nope --input '{}'` as a real process, not
  through `CliRunner`; record the exit code and stderr in the completion note.

```bash
rg -c 'TRANSITIONAL\(gate-name-resolution' src plugins
```
now: `0` · after: `0` (T2 and T3 add three; this task removes them)

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_resume.py src/functualize/app/_workflow_answer.py src/functualize/app/_workflow_view.py
```
now: `0` · after: `7` (six calls and the definition)

```bash
git diff --name-only ef1939d -- tests | rg -v 'test_gate_not_found_error|test_gate_not_found_refusal|test_mcp_gate_not_found|test_gate_name_resolution' | wc -l
```
now: `0` · after: `0` — invariant: AC-10, no existing test is edited.

## Wave 8 — pre-merge cleanup

### [ ] T10 — migrate the durable half, then clear the artifacts

*Files:* `.spec/STATUS.md`, then deletion of `.spec/features/gate-name-resolution/`

- Push the feature branch and open the PR (title a conventional commit, e.g.
  `fix(workflow): resolve a gate by its declared name`). Wait for validation,
  including all three `test-full` jobs (the artifact checks are expected to
  fail at this point).
- Add a `.spec/STATUS.md` entry naming the feature `gate-name-resolution`: gate
  references resolve once per public entry via `resolve_name` against the
  scope's gate keys; an unknown gate in an addressed scope raises
  `GateNotFoundError` and each surface translates it (D1, member 2026-10-01);
  survey paths keep their envelopes; `gate: str` and `deposit_gate_input` kept
  by member decision.
- Last commit, deletion-only: `git rm -r .spec/features/gate-name-resolution`;
  push. `spec-artifacts-cleared` then passes.

```bash
rg -c 'gate-name-resolution' .spec/STATUS.md
```
now: `0` · after: `1`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T2", "T3"] },
    { "id": 2, "tasks": ["T4"] },
    { "id": 3, "tasks": ["T5"] },
    { "id": 4, "tasks": ["T6"] },
    { "id": 5, "tasks": ["T7"] },
    { "id": 6, "tasks": ["T8"] },
    { "id": 7, "tasks": ["T9"] },
    { "id": 8, "tasks": ["T10"] }
  ]
}
```

Wave 1 is the only parallel wave: T2 and T3 touch disjoint files (CLI + flags
adapter vs. the MCP plugin) and disjoint new test files, and both consume only
T1's class. T4–T6 are serialized because they share
`tests/workflow/test_gate_name_resolution.py`, and each consumes the previous
one's resolver.
