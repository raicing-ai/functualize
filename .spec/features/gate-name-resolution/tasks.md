# gate-name-resolution — Tasks

Authored 2026-09-30 against `e7a93bf` (`origin/master`). Seven tasks in seven
waves, serialized: T1–T3 share the new unit-test file, and T4 depends on all
three. Every `now:` below was produced by running the command at authoring time
on this branch.

**The Execute phase reads only this file from the feature directory.** Each task
restates the behavior it needs; `B-n` and `AC-n` are defined in `spec.md`.

**Execute is NOT yet authorized.** `spec.md` awaits member confirmation, and
decision **D1** (unknown gate: returned `gate_not_found` envelope, recommended,
vs. a raised `GateNotFoundError`) is open. The tasks below implement D1-(b). If
the member picks (a), `spec.md` AC-6 and T1/T2 are re-authored and a CLI/MCP
translation task is inserted before T4. The two *needs maintainer review* smells
in `plan.md` → *Surviving smells* (Primitive Obsession on `gate: str`;
`deposit_gate_input` as dead-code candidate) must be answered too. Neither
answer changes these tasks unless the member widens scope.

## How to read a gate

A fenced `bash` block holding a **count** (`rg -c` or `| wc -l`), followed by
`now:` (measured at authoring) and `after:` (what the task must produce).
`tests/spec/test_task_gates_still_hold.py` re-runs every gate of every `[x]` task
against `HEAD` for the life of the branch, so each gate stays true through later
tasks. `invariant` marks a count that must not change. **Comments and docstrings
in counted files count too** — never write `_canonical_gate(` (with the
parenthesis), `name == gate` or `name == blocked_on` in prose inside them.

## Standing rules for every task

- Run `uv run ruff check --fix src/ tests/ plugins/ examples/`,
  `uv run ruff format src/ tests/ plugins/ examples/`, `uv run mypy src/`,
  `uv run lint-imports`, and targeted `uv run pytest` (at most two invocations
  per verification). Redirect output to `/tmp/functualize-<cmd>.log`.
- **Test fixtures:** tests use the repo's `tests/conftest.py` isolation plus the
  fixture shape of `tests/workflow/test_gate_drafts.py:45-86`, with the gate
  declared `Gate(name="approve_refund", awaits=Approval)` where
  `class Approval(BaseModel): approved: bool`. A bare `python` script does not
  read back the scope it wrote (research.md) — do not verify with one.
- **Reachability precedes `[x]`**: name the production call path in the
  completion note and prove it — commit, break the call (replace the
  `_canonical_gate` call in the named entry with the raw `gate`), watch a named
  test fail, `git checkout -- <file>`, amend.
- **Scope fence**, checked by every task:

```bash
git diff --name-only e7a93bf -- src/functualize/_types src/functualize/_primitives src/functualize/_engine src/functualize/_cli plugins | wc -l
```
now: `0` · after: `0` — invariant: no file outside `src/functualize/app/` changes; `_types/workflow.py` and `_types/errors.py` belong to PR #71.

```bash
rg -c 'gate_unresolvable' src/functualize/_cli/builtins.py
```
now: `1` · after: `1` — invariant: the CLI exit mapping is untouched.

- No tracker key, issue URL, agent, model or run identity in any commit message.
  Subjects are conventional commits, e.g. `fix(workflow): resolve a gate by its declared spelling`.

## Wave 0 — the resolver

### [ ] T1 — `_canonical_gate`, and the two `_workflow_resume.py` entries

*Files:* `src/functualize/app/_workflow_resume.py`, `tests/workflow/test_gate_name_resolution.py` (new)

Behavior (B-1, B-2, B-4, B-5):

1. Add, in `src/functualize/app/_workflow_resume.py`, a module-level import
   `from functualize._types.naming import resolve_name` and:

   ```python
   def _canonical_gate(known: Iterable[str], gate: str) -> str | dict[str, Any]:
   ```

   - `names = sorted(known)`; `return resolve_name(gate, names)` — exact match
     first, then the canonical form (`approve_refund`, `approveRefund`,
     `Approve_Refund` all reach `approve-refund`).
   - On `LookupError` whose message contains `"ambiguous"`: return
     `{"error": "ambiguous_gate", "message": f"{len(c)} gates match '{gate}'. Name one exactly.", "candidates": c}`
     where `c` is the names whose `normalize_name` equals `normalize_name(gate)`.
   - Any other `LookupError`: return
     `{"error": "gate_not_found", "message": f"No gate '{gate}'. Gates: {', '.join(names) or 'none'}.", "gates": names}`.
     The caller may prefix the scope id; the message must name the known gates.
   - Import `Iterable` under `TYPE_CHECKING` from `collections.abc`.
2. `_resolve_gate_model`: after `node = declaration.node(gate)`, if `node is
   None` return `(None, {"error": "gate_not_found", "message": f"Workflow '{workflow_name}' declares no gate '{gate}'."})`
   **before** touching `.awaits`. The broad `except` stays for
   materialization failures, which remain `gate_unresolvable`.
3. `deposit_gate_input`: immediately after `scope = store.get_scope(scope_id) or {}`,
   `resolved = _canonical_gate(scope.get("gates") or {}, gate)`; if it is a
   dict, return it; otherwise `gate = resolved` and continue unchanged. Every
   later use (`store.get_gate`, `_resolution_view`, the result `gate` field and
   messages) then carries the canonical name (B-3).
4. Tests in `tests/workflow/test_gate_name_resolution.py`, one class
   `TestCanonicalGate` (the helper, pure: exact, underscore, camel, title-case,
   unknown → `gate_not_found` with `gates`, empty known → `gate_not_found` with
   `gates == []`) and one class `TestDeposit` (AC-5, AC-6, AC-7 through
   `deposit_gate_input`: `"approve_refund"` → `status == "input_accepted"`,
   `gate == "approve-refund"`, payload stored under `approve-refund`; `"nope"` →
   `gate_not_found`, message contains `approve-refund`, not `AttributeError`).

*Production call path:* `functualize.app.utils.deposit_gate_input` →
`_canonical_gate`. Sabotage: pass the raw `gate` → `TestDeposit` fails.

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `2` (the definition and the call in `deposit_gate_input`)

```bash
rg -c '^from functualize._types.naming import resolve_name$' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `1`

```bash
rg -c 'if node is None' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `1`

Also green: `uv run pytest tests/workflow/test_gate_name_resolution.py tests/workflow/test_gate_payload_shape.py tests/workflow/test_gate_resolution_model.py -q --no-header`, and `uv run lint-imports`.

## Wave 1 — the answer entries

### [ ] T2 — `resolve_gate`, `answer_gate`, `gate_draft` resolve once

*Files:* `src/functualize/app/_workflow_answer.py`, `tests/workflow/test_gate_name_resolution.py`

Behavior (B-1–B-4; AC-1 unit half, AC-2, AC-5, AC-6):

1. Import `_canonical_gate` from `functualize.app._workflow_resume` (extend the
   existing import at `_workflow_answer.py:39-43`).
2. `resolve_gate`, both-named branch (`:72-83`): after the `workflow_not_found`
   check, replace the `store.get_gate(scope_id, gate) is None` test with
   `resolved = _canonical_gate(scope.get("gates") or {}, gate)`; a dict is
   returned as the refusal, with `gate_not_found`'s message kept as
   `Workflow '{scope_id}' has no gate '{gate}'.` plus the gate list; otherwise
   return `(scope_id, resolved)`.
3. `resolve_gate`, scan branch (`:85-101`): when `gate` is not `None`, resolve it
   against that scope's `names`; append `(sid, resolved)` only when the result
   is a `str`. When `gate` is `None`, unchanged. The `name == gate` comparison
   disappears.
4. `answer_gate` (`:191-201`): immediately after the `workflow_not_found` check,
   `resolved = _canonical_gate(scope.get("gates") or {}, gate)`; dict → return
   it; else `gate = resolved`. Every later line is unchanged and now receives
   the canonical name.
5. `gate_draft` (`:139-142`): read `scope = store.get_scope(scope_id)`; `None` →
   `_error("workflow_not_found", …)`; then resolve as in 4, before
   `_resolve_gate_model`.
6. Tests appended to `tests/workflow/test_gate_name_resolution.py`:
   `TestResolveGate` (both forms × the four spellings of AC-5; `"nope"` →
   `gate_not_found`), `TestAnswerGate` (`"approve_refund"` + complete values →
   `status == "answered"`, `gate == "approve-refund"`; then
   `resume_scope(app, store, "rel-1")` → `status == "success"` — AC-1),
   `TestGateDraft` (AC-2; `"nope"` → `gate_not_found`, message has no
   `AttributeError`), and `test_resume_scope_answers_by_declared_name`
   (`resume_scope(..., input={"approved": True}, gate="approve_refund")` →
   `success`).

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

## Wave 2 — the survey filter

### [ ] T3 — `list_scopes(blocked_on=…)` resolves the same way

*Files:* `src/functualize/app/_workflow_view.py`, `tests/workflow/test_gate_name_resolution.py`

Behavior (B-6, AC-8): in `list_scopes` (`_workflow_view.py:318-321`) replace the
`name == blocked_on` predicate with "`_canonical_gate([n for n, _ in
pending_gates(scope)], blocked_on)` returned a `str`". A refusal envelope means
*this scope does not match*, never an error. Import `_canonical_gate` beside the
existing `pending_gates` import (`:31`). **Net-zero lines**: the module is 563
lines today (`wc -l`), and this task must not grow it.

Test: `TestListScopes` — `list_scopes(app, store, blocked_on="approve_refund")`
and `blocked_on="approve-refund"` both return the one row for `rel-1`;
`blocked_on="nope"` returns `[]`.

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

## Wave 3 — surfaces, end to end

### [ ] T4 — integration: CLI, fused flags and MCP by the declared name

*Files:* `tests/integration/test_gate_name_resolution_e2e.py` (new)

No `src/` change. Model on `tests/integration/test_mcp_workflow_loop_e2e.py`
(MCP provider fixture, `anyio`) and `tests/integration/test_cli_workflow_parity.py`
(CLI runner). Workflow as in the standing rules.

- **AC-3 (MCP):** `answer_gate(values={"approved": True}, gate="approve_refund")`
  → `status == "answered"`; `get_gate_draft(workflow_id="rel-1",
  gate="approve_refund")` → no `error`; on a fresh scope
  `resume_workflow(workflow_id=…, input={"approved": True}, gate="approve_refund")`
  → the walk passes the gate (`deploy` has a step record);
  `list_workflows(blocked_on="approve_refund")` lists the scope.
- **AC-4 (CLI):** `func builtin workflow answer <id> approve_refund --input
  '{"approved": true}'` exits 0; `func builtin workflow resume <id>` then
  finishes the walk. The fused `--wf-resume <id> --wf-input '{"approved": true}'
  --wf-gate approve_refund` path records and walks on.
- **AC-6 (CLI, loud):** `func builtin workflow answer <id> nope --input '{}'`
  exits **1**, stderr starts `Error:` and names `approve-refund`, and the output
  contains no `Traceback`.

```bash
ls tests/integration/test_gate_name_resolution_e2e.py 2>/dev/null | wc -l
```
now: `0` · after: `1`

Also green: `uv run pytest tests/integration/test_gate_name_resolution_e2e.py -q --no-header`.

## Wave 4 — documentation

### [ ] T5 — guide and changelog

*Files:* `docs/guides/workflows.md`, `CHANGELOG.md`

- `docs/guides/workflows.md`: beside the gate-answering section (`:215-230`),
  one short paragraph: a gate is addressed by its declared name or its
  canonical form (`approve_refund` and `approve-refund` both work);
  `workflow list` prints the canonical form; an unknown name is refused with
  `gate_not_found` listing the scope's gates.
- `CHANGELOG.md`: under `## [Unreleased]`, a `### Fixed — a gate answers to the
  name it was declared with` entry in the file's hand-written prose style;
  mention that `gate_draft` and `deposit_gate_input` now report an unknown gate
  as `gate_not_found` rather than `gate_unresolvable`, and that result `gate`
  fields carry the canonical spelling.

```bash
rg -c 'a gate answers to the name it was declared with' CHANGELOG.md
```
now: `0` · after: `1`

## Wave 5 — checkpoint

### [ ] T6 — verify the whole feature

*Files:* none (fixes, if any, go back to the owning task's file and are noted there)

- All five checks green: `ruff check`, `ruff format --check`, `mypy src/`,
  `lint-imports`, and the fast suite `uv run pytest -x -q --no-header`.
- AC-10: `git diff --name-only e7a93bf -- tests | rg -v 'test_gate_name_resolution'`
  prints nothing — no existing test was edited.
- Orphan scan (Verify pass): serena `find_referencing_symbols` on
  `_canonical_gate` returns six call sites — 1 in `_workflow_resume.py`, 4 in
  `_workflow_answer.py`, 1 in `_workflow_view.py` (the gate below counts 7
  because it also matches the definition).
- Re-run the two *Scope fence* gates from the standing rules; both still read
  `0` and `1`.
- Re-measure `wc -l` for the three `app/_workflow_*` files and record them; none
  may exceed its authoring size by more than the plan states (175 → ≲205,
  454 → ≲470, 563 → 563).
- Real-terminal check of AC-6 (`contributor/reference/pitfalls.md` §25):
  run the unknown-gate `workflow answer` against a real project directory with
  `func`, not `CliRunner`, and record the exit code and stderr.

```bash
rg -c '_canonical_gate\(' src/functualize/app/_workflow_resume.py src/functualize/app/_workflow_answer.py src/functualize/app/_workflow_view.py
```
now: `0` · after: `7`

## Wave 6 — pre-merge cleanup

### [ ] T7 — migrate the durable half, then clear the artifacts

*Files:* `.spec/STATUS.md`, then deletion of `.spec/features/gate-name-resolution/`

- Push the feature branch; wait for validation including all three `test-full`
  jobs (the artifact checks are expected to fail at this point).
- Add a `.spec/STATUS.md` entry: the naming rule for gate references (resolved
  once per public entry via `resolve_name` against the scope's gate keys), D1's
  outcome and its reason, and the two surviving smells with the member's answers.
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
    { "id": 1, "tasks": ["T2"] },
    { "id": 2, "tasks": ["T3"] },
    { "id": 3, "tasks": ["T4"] },
    { "id": 4, "tasks": ["T5"] },
    { "id": 5, "tasks": ["T6"] },
    { "id": 6, "tasks": ["T7"] }
  ]
}
```
