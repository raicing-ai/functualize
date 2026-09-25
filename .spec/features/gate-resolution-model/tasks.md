# FUN-4 — Tasks

Authored 2026-09-25 against `03fbb64`. There are thirteen tasks in nine waves, and
**19 counting gates**. Every `now:` below was produced by running the command on this
branch at authoring time.

**The Execute phase reads only this file from the feature directory** (context anchor:
`AGENTS.md`, `.spec/CONSTITUTION.md`, `.spec/ARCHITECTURE.md`, `.spec/TESTING.md`,
`.spec/STATE.md`, this file). Each task therefore carries its own behaviour references.
Rule ids **R1–R10** are defined in `spec.md` §4.2, and the task text restates what each
task needs.

Each task touches 1–3 files, T9 excepted (four one-line edits), and fits in one context
window. **Wave ordering is binding:** never start a task in wave N+1 while wave N has
unchecked tasks.

**Do not start Execute** until the member has answered `spec.md` §8 (D-1…D-5, Q-2). If
an answer changes scope, revise `spec.md`/`plan.md` and re-author the affected gates
before writing code.

## How to read a gate

A fenced `bash` block holding a **count**, followed by `now:` (the measured value today)
and `after:` (the value the task must produce). `tests/spec/test_task_gates_still_hold.py`
re-runs every gate of every `[x]` task against HEAD for the life of the branch. Each gate
here was chosen to stay true through every later task. Any comment or docstring that
matches a pattern counts too, so do not mention a removed symbol in prose inside the
counted files. Weakening a gate is a scope decision, and has to be disclosed
(`.spec/CONSTITUTION.md` → *Transitional Changes*).

## Why the gate suite is red until T6

`test_the_parser_actually_found_gates` needs **≥ 12** gates owned by `[x]` tasks. The
running count as tasks are ticked is:
T1 `2` · T2 `5` · T3 `7` · T4 `9` · T5 `11` · T6 `13` · T7 `16` · T8 `18` · T9 `19`.

So the suite is red from this file's first commit until T6 is ticked. That is a disclosed
transitional state. **Do not loosen the assertion.** Once T6 is ticked, 13 ≥ 12 and the
suite goes green. T10 and T11 add no counting gates, and the final cleanup commit (T13)
empties `.spec/features/`, so the test then skips.

## Standing rules for every task

- Run `ruff check --fix`, `ruff format`, `mypy src/`, `lint-imports` and targeted `pytest`
  (at most 2 invocations), with output redirected to `/tmp/functualize-<cmd>.log`.
- **Reachability precedes `[x]`.** For every task from T5 on, name the production call
  path in the task's completion note, then prove it: commit, break the call, watch a
  named test fail, restore with `git checkout -- <file>`, and amend the commit.
- Mark every site that is transitional with `# TRANSITIONAL(FUN-21): …`.
- Peer independence: `_engine` never imports `_gate`, and `_gate` never imports
  `_engine`.

---

## Wave 0 — vocabulary

### [ ] T1 — resolution values

*Files:* `src/functualize/_types/gate_resolution.py` (new), `tests/types/test_gate_resolution_values.py` (new)

Values only, stdlib plus `_types.persistence`, frozen dataclasses. Define:
- `EvaluationOutcome(StrEnum)`: `ACCEPTED`, `INVALID`, `FAILED`, `UNAVAILABLE`,
  `NOT_REACHED`, with lowercase values.
- `CandidateEvaluation(outcome, detail: str = "", errors: tuple[tuple[str, str], ...] = ())`.
- `GateCandidate(candidate_id, request_id, ordinal, source, submitted_at, evaluation,
  payload=None)`.
- `LadderOutcome(rungs, model=None, blocked_reason="")`, where `rungs` is
  `tuple[tuple[str, CandidateEvaluation, Any], ...]`.
- `GateResolution(request: InputRequest, candidates, accepted_id)`.

Define `__all__`. The import direction is `gate_resolution → persistence`, and
`persistence` names `GateCandidate` only under `TYPE_CHECKING`. The test asserts that
direction with an AST check.

```bash
rg -c '^class (EvaluationOutcome|CandidateEvaluation|GateCandidate|LadderOutcome|GateResolution)\b' src/functualize/_types/gate_resolution.py
```
now: `0` · after: `5`

```bash
rg -c '^    (ACCEPTED|INVALID|FAILED|UNAVAILABLE|NOT_REACHED) = ' src/functualize/_types/gate_resolution.py
```
now: `0` · after: `5`

### [ ] T2 — the port amendment

*Files:* `src/functualize/_types/persistence.py`, `src/functualize/_types/errors.py`, `tests/types/test_runtime_store_port.py`

Make these changes to the port:
- `InputRequest` gains **`request_id: str` as the first field**.
- `SuspendAtGate` gains `request_id: str` (after `gate_name`), `model: str = ""` and
  `tools: tuple[Mapping[str, Any], ...] = ()`.
- A new frozen command `ConsumeInput(scope_id: str, generation: int, request_id: str,
  now: datetime)`, added to `__all__`.
- `InputWriter.append(self, candidate: GateCandidate) -> None` replaces the three-argument
  form.
- New `InputWriter.consume(self, cmd: ConsumeInput) -> None`.
- New `InputReader.request(self, request_id: str) -> InputRequest | None`.
- New `InputReader.candidates_for(self, request_id: str) -> Sequence[GateCandidate]`.

The docstrings must state the store rules:
- appending to a request that is not `open` raises `InputRequestNotOpenError` and
  applies nothing from the unit;
- an `accepted` candidate moves the request to `accepted`;
- consuming a request that is already `consumed` is a no-op;
- the ids are minted by the recorder, and why (the accumulating port cannot reference a
  store-minted id inside one batch).

In `errors.py`, add `InputRequestNotOpenError(Exception)` with `request_id` and `status`.
`GateResolutionError.__init__` gains `evaluations: tuple = ()` as a keyword argument,
stored as `self.evaluations`. The message must not change.

The document backend will not type-check against the new port until T5. If `mypy` flags
`document_store.py`, it is only because this wave changed the protocol. Record that in
the completion note and do **not** edit `document_store.py` here.

```bash
rg -c '^    request_id: str$' src/functualize/_types/persistence.py
```
now: `0` · after: `3`

```bash
rg -c '^class (ConsumeInput|InputRequestNotOpenError)\b' src/functualize/_types/
```
now: `0` · after: `2`

```bash
rg -c 'def (consume|request|candidates_for)\(self' src/functualize/_types/persistence.py
```
now: `0` · after: `3`

---

## Wave 1 — pure logic (T3 ∥ T4, disjoint files)

### [ ] T3 — the document representation and its guard

*Files:* `src/functualize/_primitives/gate_requests.py` (new), `tests/primitives/test_gate_requests.py` (new)

Write module-level functions over **public `ScopeStore` methods only**: `get_gate`,
`put_gate`, `get_scope`, and `batch()` for atomicity. **Add no method to `ScopeStore`.**
The module docstring carries exactly one `TRANSITIONAL(FUN-21)` marker: requests and
candidates live inside `scopes.json` until FUN-21's durable slice replaces this module.

Functions:
- `open_request(store, scope_id, gate_name, *, request_id, schema, prompt, model, tools, now)`
  — **R1.** If a live request (`open`/`accepted`) or a consumed one exists for the gate,
  return its id unchanged and do not reset `blocked_at`. Otherwise write a new gate
  record: `request_id`, `status: "open"`, `candidates: []`, `input_schema`, `prompt`,
  `model`, `tools`, `payload: None`, `blocked_at`. A superseded record's history is
  kept under `superseded: [...]`.
- `append_candidate(store, scope_id, gate_name, candidate)` — **R6 and R4.** Inside one
  `batch()`, re-read the status. If it is not `open`, raise `InputRequestNotOpenError`
  and write nothing. Otherwise append the candidate dict. If the candidate is
  `accepted`, set `status: "accepted"` and `payload`.
- `consume_request(store, scope_id, gate_name, request_id, now)` — **R5.** Moves
  `accepted` to `consumed` and stamps `consumed_at`. `consumed` is a no-op. Anything
  else raises.
- `supersede_request(store, scope_id, gate_name, *, new_request_id, now)` — **R7.** Moves
  `accepted` to `cancelled` with reason `reopened`, pushes the old record to
  `superseded`, opens a new request, and seeds its `draft.values` with the old payload.
- `request_for(scope_id, gate_name, record, generation) -> InputRequest` — the read
  projection, including **R9**: a record without `request_id` gets id
  `f"{scope_id}::{gate_name}"`, zero candidates, and its status derived from
  `consumed_at` / `payload` exactly as `document_store._input_request` does today.
- `candidates_for(record) -> tuple[GateCandidate, ...]`, ordered by ordinal.

Tests:
- open reuses a live request;
- a legacy record is projected, not synthesised;
- **two writers each `append_candidate` an accepted candidate through two `ScopeStore`
  instances on one substrate: exactly one is recorded and the other raises;**
- supersede keeps the old candidates;
- consuming twice is a no-op.

If the two-writer test cannot pass over the public surface, **STOP** and raise it (see
`plan.md` → *Risks*). Do not add a `ScopeStore` method.

```bash
rg -c '^def (open_request|append_candidate|consume_request|supersede_request|request_for|candidates_for)\(' src/functualize/_primitives/gate_requests.py
```
now: `0` · after: `6`

```bash
rg -c 'TRANSITIONAL\(FUN-21\)' src/functualize/_primitives/gate_requests.py
```
now: `0` · after: `1`

### [ ] T4 — the enumerating ladder

*Files:* `src/functualize/_gate/_registry.py`, `src/functualize/_gate/_evaluation.py` (new), `tests/gate/test_registry.py`

**`GateRegistry.evaluate(model_class, *, gate_strategy=None, gate_name="unnamed",
resolved_fields=None, workflow_context=None, force_gate=False) -> LadderOutcome`** (R3).
It is pure: no store, no clock, no ids. Keep the existing algorithm (field
classification, the short-circuit when fully resolved and not forced, and strategy-list
expansion), but produce one rung per expanded entry, in order:
- `failed`: the resolver raised; the detail is `str(exc)`;
- `unavailable`: the strategy is unregistered; the detail is
  `missing_strategy_hint(name)`;
- `accepted`: the first success; the payload is `model.model_dump()`;
- `not_reached`: every rung after the accepted one.

Keep the two loud `ValueError` paths (an unregistered strategy inside a preset, and a
single explicitly-named unregistered strategy) raising exactly as now, with nothing
returned.

In the short-circuit case, return one rung `("resolve", accepted, payload)`.

**`resolve_gate` is rebuilt as `evaluate` plus a raise.** It returns `outcome.model`, or
raises `GateResolutionError(gate_name, strategies_attempted=len(rungs),
last_error=outcome.blocked_reason, evaluations=…)`.

`_gate/_evaluation.py`:
- `blocked_reason_from(rungs) -> str` is the **only** producer of the text. Unregistered
  names come first via `_unregistered_message` (move that helper here). After them come
  `"<name>: <detail>"` entries for each failure, joined with `"; "`, or
  `"no strategies attempted"`.
- `evaluate_submission(model_class, payload) -> tuple[CandidateEvaluation, dict | None]`
  (R4). One validation. On success: `accepted` plus the validated dump. On failure:
  `invalid` with `(field, message)` pairs taken from `ValidationError.errors()`, and
  `None`.

**R8 byte-identity.** Parametrise the existing `last_error` assertions in
`tests/gate/test_registry.py` over both `resolve_gate` and `evaluate(...).blocked_reason`.
Do not edit any expected string.

```bash
rg -c '    def evaluate\(' src/functualize/_gate/_registry.py
```
now: `0` · after: `1`

```bash
rg -c '^def (evaluate_submission|blocked_reason_from)\(' src/functualize/_gate/_evaluation.py
```
now: `0` · after: `2`

---

## Wave 2 — backend and recorder (T5 ∥ T6, disjoint files)

### [ ] T5 — the document backend implements the amended port

*Files:* `src/functualize/_primitives/document_store.py`, `tests/primitives/test_document_runtime_store.py`

Changes to `document_store.py`:
- `_DocumentInputWriter.append(candidate)` and `.consume(cmd)` buffer commands.
  `consume` buffers `ConsumeInput`; it is a scope-bearing command, so the one-aggregate
  guard applies.
- `_DocumentTransaction` dispatch calls `gate_requests.append_candidate` /
  `consume_request`. `_suspend` calls `gate_requests.open_request`, passing `request_id`,
  `model` and `tools` from `SuspendAtGate`, then sets position and status as today.
- **`_resume` no longer writes `consumed_at`** (R5, single owner).
- The `"::"` parse is deleted.
- `_DocumentInputReader` gains `request(request_id)` and `candidates_for(request_id)`
  through `gate_requests.request_for` / `candidates_for`. `_input_request` is replaced
  by `gate_requests.request_for`.
- Keep the class `# TRANSITIONAL(FUN-17/T7)` marker. Apply bodies live in
  `gate_requests`, so **`_DocumentTransaction` stays ≤ 500 lines**. Check with the AST
  walk in `plan.md` and paste the number into the completion note.

Reachability: at the end of this wave the production path is still **none**, because
the walker lands in T7. This task is `[x]` on its gates plus its unit tests. The
completion note must state that reachability is proved in T7, not here.

```bash
rg -c 'partition\("::"\)' src/functualize/_primitives/document_store.py
```
now: `1` · after: `0`

```bash
rg -c '"consumed_at": _iso\(cmd\.now\)' src/functualize/_primitives/document_store.py
```
now: `1` · after: `0`

### [ ] T6 — the input recorder

*Files:* `src/functualize/_engine/recording/input_recorder.py` (new), `src/functualize/_engine/recording/__init__.py`, `src/functualize/_engine/recording/workflow_recorder.py`

`InputRecorder` builds commands and holds no store, matching `WorkflowRecorder`.
- `opened(...) -> SuspendAtGate` mints `"req_" + uuid4().hex`.
- `ladder_candidates(request_id, outcome: LadderOutcome, *, first_ordinal, now) ->
  tuple[GateCandidate, ...]` maps each rung to `source=f"strategy:{name}"` and mints
  `"cand_" + uuid4().hex`.
- `submitted(request_id, source, evaluation, payload, *, ordinal, now) -> GateCandidate`
  validates that `source` is non-empty and at most 128 characters (R10), and raises
  `ValueError` otherwise.
- `consumed(...) -> ConsumeInput`.

`WorkflowRecorder.suspended` gains the `request_id`/`model`/`tools` pass-through, or
delegates to `InputRecorder.opened`. Pick one and delete the other path: there is one
builder of `SuspendAtGate`.

```bash
rg -c '    def (opened|ladder_candidates|submitted|consumed)\(' src/functualize/_engine/recording/input_recorder.py
```
now: `0` · after: `4`

```bash
rg -c 'InputRecorder' src/functualize/_engine/recording/__init__.py
```
now: `0` · after: `2`

---

## Wave 3 — the walker (first production path for AC-1, AC-2)

### [ ] T7 — extract `GateService`; gate transitions through the port

*Files:* `src/functualize/_engine/gate_service.py` (new), `src/functualize/_engine/workflow_walker.py`, `src/functualize/_engine/frontier.py`

Before editing:
- load the `python-design-patterns` skill;
- read `contributor/architecture/codemaps/data-flow.md`;
- run serena `find_referencing_symbols` on `WorkflowWalker._service_gate`,
  `WorkflowWalker._block` and `FrontierWalk.block` / `gate_payload`, activating serena
  by absolute worktree path.

**Extract Class.** `GateService.service(node, walk, registry, prompt_gates)` holds all of
today's `_service_gate` and `_block` logic. `WorkflowWalker._service_gate` becomes a
delegate of three lines or fewer, and `WorkflowWalker` gets shorter.

`FrontierWalk` gains four methods, each **one `RuntimeStore.transaction()` unit**:
- `open_request(...)` — `SuspendAtGate`;
- `record_candidates(...)` — `tx.inputs.append` for each candidate;
- `consume(request_id)` — `tx.inputs.consume`;
- `resolution(gate_name) -> GateResolution | None` — reads `runtime_store.inputs`.

Delete `FrontierWalk.block`'s `put_gate` and `gate_payload`'s `get_gate`.

Behaviour, in order:
- **R2 replay:** if the resolution's request is `accepted` or `consumed` and has an
  accepted candidate, feed that payload. If it is `accepted`, consume it.
- **R3:** if the request is open and the gate has a strategy list, call
  `registry.evaluate(...)` and record the rungs as candidates. `ordinal` continues from
  the recorded count.
  - If a rung was accepted, consume it and proceed.
  - If none was, block with `blocked_reason = outcome.blocked_reason`.
- Otherwise open the request (R1) and block.

The `blocked_reason` text **must not change**. `_engine` must not import `_gate`: use
the injected registry and the `_types` `LadderOutcome`.

Reachability, named: `app.execute(<workflow job>)` → `JobExecutionEngine` →
`WorkflowWalker.walk` → `_service_gate` → `GateService.service` →
`FrontierWalk.open_request` / `record_candidates` / `consume` →
`DocumentRuntimeStore.transaction`.

Sabotage: drop the `record_candidates` call, and watch T10's
`test_ladder_rungs_are_recorded` fail. Until T10 exists, use a test added here in
`tests/engine/test_gate_service.py`, which is allowed as a fourth file only for this
purpose. Run the MCP workflow tests (`tests/plugins/test_mcp_workflow_tools.py`): the
`model`/`tools` keys must survive.

```bash
rg -c '_store\.(put_gate|get_gate|deposit_gate_payload)\(' src/functualize/_engine/
```
now: `3` · after: `0`

```bash
rg -c 'GateResolutionError' src/functualize/_engine/workflow_walker.py
```
now: `2` · after: `0`

```bash
rg -c '^class GateService\b' src/functualize/_engine/gate_service.py
```
now: `0` · after: `1`

---

## Wave 4 — surfaces

### [ ] T8 — answer, deposit and reopen record candidates

*Files:* `src/functualize/app/_workflow_answer.py`, `src/functualize/app/_workflow_resume.py`, `tests/workflow/test_gate_drafts.py`

**`answer_gate(..., source: str = "api")`.** A commit with a complete draft does the
following:
- validate with `evaluate_submission`;
- `InputRecorder.submitted`;
- `gate_requests.append_candidate`, which replaces `deposit_gate_payload` plus
  `clear_gate_draft` for the payload write (keep the draft clear);
- map `InputRequestNotOpenError` to `gate_already_answered` (R6).

**`_reopen` success path.** Call `gate_requests.supersede_request` in place of
`store.reopen_gate` (R7). The refusal checks stay exactly as they are, including
`_walk_has_passed` (plan → *Surviving smells* #3).

**`gate_draft` result.** Gains `resolution`, built by **one** helper that reads
`gate_requests.request_for` / `candidates_for` and never validates (R8). The shape is
`{request_id, request_status, candidates: [{candidate_id, ordinal, source, submitted_at
(ISO), outcome, detail, errors}]}`, with no payloads.

**`deposit_gate_input(..., source: str = "api")`** (R4, R6):
- invalid input: record an `invalid` candidate and return the unchanged
  `validation_error` envelope;
- valid input: record an `accepted` candidate, and add `request_id` to the result;
- a request that is not open returns `gate_already_answered`.

Rewrite the module docstring's "invariant" paragraph. The invariant now is: a payload is
only written by an accepted candidate. Remove every mention of `deposit_gate_payload`
from both files, comments included.

Reachability: `func builtin workflow answer` → `_cli/builtins.py:1455` → `answer_gate` →
`gate_requests.append_candidate`. Sabotage the `append_candidate` call, and a
`test_gate_drafts.py` test must fail.

```bash
rg -c 'deposit_gate_payload' src/functualize/app/
```
now: `2` · after: `0`

```bash
rg -c '"resolution"' src/functualize/app/_workflow_answer.py
```
now: `0` · after: `1`

## Wave 5 — attribution

### [ ] T9 — surfaces say who answered

*Files:* `src/functualize/_cli/builtins.py`, `src/functualize/app/adapters/workflow_flags.py`, `src/functualize/app/_workflow_control.py`, `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

This task has four files, each a one-line mechanical change. The count was checked with
`rg -n "answer_gate\(|resume_scope\(" src plugins` at authoring time.
- `resume_scope(..., source: str = "api")` threads `source` to its `answer_gate` call.
- Pass `source="cli"` at `builtins.py`'s `answer_gate` (≈1455) and `resume_scope`
  (≈1554) calls, and at `workflow_flags.py`'s `answer_gate` (≈428).
- Pass `source="mcp"` at `_workflow_tools.py`'s `answer_gate` (≈287) and
  `resume_scope` (≈345).
- Fix the stale comment at `builtins.py:1095`, which claims the CLI uses
  `deposit_gate_input`. It does not.

`_cli/` still imports only `functualize.app.utils`.

```bash
rg -c 'source="(cli|mcp)"' src/functualize/_cli/builtins.py src/functualize/app/adapters/workflow_flags.py plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `0` · after: `5`

---

## Wave 6 — end-to-end gates, then docs (serialised)

### [ ] T10 — acceptance tests through public entry points

*Files:* `tests/workflow/test_gate_resolution_model.py` (new), `tests/integration/test_mcp_workflow_loop_e2e.py`

Each test drives `app.execute(...)`, `functualize.app.utils.answer_gate` /
`deposit_gate_input`, or the MCP tool provider. **None calls `gate_requests` or
`GateService` directly** (constitution → *Capability coverage*).

| Test | AC / rule |
|---|---|
| `test_blocked_gate_has_a_minted_request_id_stable_across_resume` | AC-1, R1 |
| `test_ladder_rungs_are_recorded` (functualize-ai absent → `unavailable`, prompt fails → `failed`, then resolve → `accepted`; later rungs → `not_reached`) | AC-2, R3 |
| `test_second_ladder_run_appends_with_continuing_ordinals` | R3 |
| `test_blocked_reason_text_is_unchanged` | R8 |
| `test_reading_a_resolution_never_revalidates` (monkeypatch the gate model's `model_validate` **and** `GateRegistry.evaluate` to raise, then call `gate_draft`; it must succeed and report the recorded outcomes) | AC-2 "not recomputed", R8 |
| `test_invalid_submission_is_recorded_and_gate_stays_open` | R4 |
| `test_second_deposit_is_refused_not_overwritten` | R6 |
| `test_reopen_supersedes_and_keeps_history` | R7 |
| `test_walk_past_gate_marks_consumed_once` | R5 |
| `test_legacy_gate_record_resumes_with_zero_candidates` (a hand-written pre-change `scopes.json`) | R9 |
| MCP e2e: the answer carries `source == "mcp"` in `resolution.candidates` | R10 |

```bash
uv run pytest tests/workflow/test_gate_resolution_model.py tests/integration/test_mcp_workflow_loop_e2e.py -q --no-header
```
Expected: all green. This block is a suite run, not a count, so the gate parser skips it.

### [ ] T11 — documentation parity

*Files:* `docs/guides/workflows.md`, `docs/guides/ai.md`, `contributor/reference/runtime-persistence-data-model.md`

- `workflows.md` gate section: request identity, the `resolution` field, reopen
  supersedes, and `gate_already_answered` on `deposit_gate_input`.
- `ai.md` §*What happens when the plugin is not installed*: the rung is now recorded
  as `unavailable`, and `blocked_reason` is unchanged.
- data-model reference §1.4 / §2.4: mark `request_id`, candidate evaluation and
  single-writer consumption as **landed at the port on the document backend**, with
  durable storage pending FUN-18/19/21.

Run the executable parity pass from `contributor/guides/docs-example-parity.md` for
every behavioural claim you add.

---

## Wave 7 — pre-merge lifecycle (serialised; `plan.md` → *Version-control lifecycle*)

### [ ] T12 — migrate the durable half; push 1

*Files:* `.spec/STATUS.md`, `contributor/adr/029-gate-resolution-is-recorded-not-recomputed.md` (new, from `contributor/adr/000-template.md`)

**STATUS entry.** State the following:
- AC-1 and AC-2 are delivered, with the storage location
  `TRANSITIONAL(FUN-21)`;
- **AC-3 is open**, pending FUN-18/19/21;
- the FUN-4 issue must not close until then;
- the D-1…D-5 answers.

**ADR-029** records the decisions:
- the engine mints request and candidate identity;
- candidates are append-only, with the evaluation recorded at submission;
- consumption has one writer;
- reopen supersedes;
- the relation to ADR-025.

Before pushing, read back `git log --format='%B' origin/master..HEAD`. It must contain
no Jira or Multica key, no agent identity and no `Co-authored-by:` agent trailer. Then
push, and wait for the validation jobs, including all three `test-full` legs.

### [ ] T13 — deletion-only cleanup commit; push 2

*Files:* `.spec/features/gate-resolution-model/` (deleted)

Run `git rm -r .spec/features/gate-resolution-model`. This must be the **last** commit
on the branch, and deletion-only. Confirm `git ls-files contributor/architecture/research/`
is empty, then push. `spec-artifacts-cleared` then passes. Open the PR afterwards,
following the PR hygiene rules above; the PR is the implementation wave's to open.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1", "T2"] },
    { "id": 1, "tasks": ["T3", "T4"] },
    { "id": 2, "tasks": ["T5", "T6"] },
    { "id": 3, "tasks": ["T7"] },
    { "id": 4, "tasks": ["T8"] },
    { "id": 5, "tasks": ["T9"] },
    { "id": 6, "tasks": ["T10", "T11"] },
    { "id": 7, "tasks": ["T12"] },
    { "id": 8, "tasks": ["T13"] }
  ]
}
```

Wave notes:
- **Wave 0.** T1 and T2 touch disjoint files, but T2's docstrings name `GateCandidate`
  only under `TYPE_CHECKING`, so neither blocks the other. If mypy objects, serialise
  them in order T1 → T2.
- **Wave 6.** T10 and T11 touch disjoint files. T10 is the checkpoint for AC-1 and AC-2.
- **Waves 7–8.** These are the lifecycle and stay serialised.
