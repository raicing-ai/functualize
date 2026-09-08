# Tasks — workflow-continuation

Every gate below is an executable command that was **run at authoring time** against
`24c5cc0`; the `now:` line is what it returned then. A task is done when the gate returns
its `after:` value.

Run gates from the worktree root.

---

## Wave 1 — four independent fixes

### [x] T1 · MCP execution doors return `metadata`, and `status` as a lowercase string

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_tools.py`,
`plugins/functualize-mcp/src/functualize_mcp/_server.py`

Add `"metadata": dict(result.metadata or {})` to the return of `run_job`,
`get_execution_status` and `_execute_job`. Normalize `status` through one helper —
`getattr(s, "value", str(s)).lower()` — so all four doors agree (`_execute_job` returns
the raw `Enum` today). The key is **always present**, `{}` when empty, so no caller
branches on absence. Spec AC-1, AC-2, AC-3.

**Gate**
```bash
grep -c '"metadata"' plugins/functualize-mcp/src/functualize_mcp/_tools.py \
                     plugins/functualize-mcp/src/functualize_mcp/_server.py
```
now: `_tools.py:0`, `_server.py:0` · after: `_tools.py:2`, `_server.py:1`

**Test:** a blocked workflow through `run_job` reports its own `workflow_scope`; the same
run through `get_execution_status` reports the same keys.

---

### [x] T2 · `cancelled` is terminal, and the engine enforces it

**Files:** `src/functualize/_engine/workflow_runner.py`, `src/functualize/_types/errors.py`

`WorkflowRunner.prelude` already receives the store. Read the scope status; if
`cancelled`, raise `ScopeCancelledError(scope_id)` rather than walking. The CLI turns it
into exit 2; the MCP funnel into `{"error": "scope_cancelled"}`. Spec AC-4, AC-5.

**Gate**
```bash
grep -c 'cancelled' src/functualize/_engine/workflow_runner.py
```
now: `0` · after: `≥1`

**Sabotage:** delete the status check; `test_cancel_is_terminal.py` must fail.

---

### [x] T3 · SINGLE_FILE registration no longer crashes in the file's own directory

**Files:** `src/functualize/_cli/main.py`

`_register_single_file_peers` re-registers a function directory discovery already
registered. Skip a name the registry already holds — research R5: this is **one job
registered twice**, not two jobs contending, so the fix belongs in the peer loop and
`register_dynamic_job` stays strict (its check is what catches genuine collisions).
Spec AC-24.

**Gate** (reproduced verbatim at authoring time)
```bash
cd "$SCRATCH/sf" && func weather.py trip_planner --help; echo "exit=$?"
```
now: `ValueError: Cannot register dynamic job 'forecast'` + traceback, exit≠0
after: usage text, exit 0

---

### [x] T4 · **DROPPED — the premise is false.** Descriptions do not repeat the schema

**Files:** none.

`04-mcp.md` §3 claimed the description builder *"appends examples unconditionally"*
while *"the schema builder inlines field-level `description` and `examples`
(`:229-268`)"*, and asked for the description copy to go.

**Measured against `24c5cc0`, and the second half is not true.** The schema carries no
examples anywhere. `_build_input_schema` delegates to core's `job_input_schema` →
`input_schema` → `field_property`, and `field_property` emits exactly `type`,
`description`, `default` and `enum`. `FieldDescriptor` has no `examples` attribute at
all.

Generated a tool for a job declaring two examples:

```
DESCRIPTION: 'Ship the build to an environment.\n\nExamples:\n  - func deploy --env
              prod\n  - func deploy --env staging --dry-run'
SCHEMA:      {"type":"object","properties":{"env":{...},"dry_run":{...}}}
examples in schema?: False
```

The examples are **job-level invocation examples**, not field-level ones, and the
description is their only carrier. Removing them would delete information rather than
duplication — and would make tool *selection* worse, which is the one job a description
has.

Nothing to deduplicate, so nothing to do. The real context cost is the per-job tool
*count*, which T6 addresses. Spec AC-28 is withdrawn.

---

## Wave 2 — the payload-shape precondition, and the MCP tool-surface mode

### [x] T5 · Both deposit paths store `model_dump()`

**Files:** `src/functualize/app/_workflow_resume.py`

`deposit_gate_input` validates with `model(**payload)` then stores the **raw dict**;
`workflow_walker.py:275` stores `model.model_dump()`. Store the dump on both.

Research R7: this must land **before** drafts exist. A partial-deposit feature that
accumulated raw fragments would make the divergence permanent, because the draft would
then be the canonical accumulation format. Spec AC-10.

**Gate**
```bash
grep -c 'model_dump' src/functualize/app/_workflow_resume.py
```
now: `0` · after: `≥1`

**Test:** a gate model with a defaulted field, answered through `deposit_gate_input` and
resolved by a strategy, yields **equal** stored payloads.

---

### [x] T6 · `MCPConfig.job_tools` — `all` | `tagged` | `none`

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_config.py`,
`plugins/functualize-mcp/src/functualize_mcp/_server.py`

`job_tools` decides the **candidate set**; the existing `include_tags` / `exclude_tags` /
`exclude_jobs` / `visibility` filters then narrow it. Default `"all"` — today's
behaviour. Safe because T1 made the generic door lossless. Spec AC-26, AC-27.

**Gate**
```bash
grep -c 'job_tools' plugins/functualize-mcp/src/functualize_mcp/_config.py
```
now: `0` · after: `≥2` (the field and its tag selector)

---

## Wave 3 — the projection lift

### [x] T7 · `app/_workflow_view.py` — one projection, one derived state

**Files:** `src/functualize/app/_workflow_view.py` (new), `src/functualize/app/utils.py`

Move `_describe`, `_topology`, `_live_workflow_shape`, `_gate_summary` and
`_tool_summaries` out of the MCP plugin into `app/`. Add `derived_state` (schema §3) and
`list_scopes` with the three filters. Re-export through `app.utils` — the only route
`_cli` may legally import.

The projection gains `state`, `epilogue` and per-gate `draft`. **Additive only**; no key
removed or retyped (plan R-a). Spec AC-6, AC-7, AC-8.

**Gate**
```bash
python -c "from functualize.app.utils import describe_scope, list_scopes, derived_state"
```
now: `ImportError` · after: exit 0

---

## Wave 4 — repoint both surfaces onto the lifted projection

### [x] T8 · MCP reads the lifted projection; `list_workflows` replaces `list_active_workflows`

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

`_describe`/`_topology` become calls into `app.utils`. `list_active_workflows()` becomes
`list_workflows(workflow_name?, state?, blocked_on?)`. **Removed, not aliased** — pre-release,
no shims.

**Gate**
```bash
grep -c 'list_active_workflows' plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `6` · after: `0`

---

### [x] T9 · `builtin workflow list` gains filters; `state` becomes `show`

**Files:** `src/functualize/_cli/builtins.py`

`_scope_summary`'s five hardcoded fields are deleted and replaced by `list_scopes`.
`state <id>` becomes `show <id>`, rendering the **full** projection — same argument,
strictly more output. `pitfalls.md` §6: the second copy goes away rather than being kept
in sync.

**Gate**
```bash
grep -c 'def _scope_summary' src/functualize/_cli/builtins.py
```
now: `1` · after: `0`

**Test:** `show --format json` and MCP `get_workflow_state` are byte-identical (AC-6).

---

## Wave 5 — the draft slot

### [ ] T10 · Gate records carry a `draft`

**Files:** `src/functualize/_primitives/scope_store.py`,
`src/functualize/_primitives/state_store.py`

Five accessors (schema §2), forwarded verbatim by `StateStore` — the façade pattern
`24c5cc0` established, so no caller outside `_primitives` learns which file a section
lives in. **No `SCOPES_VERSION` bump**: the key is additive and its absence means "no
draft". `_blank_scope` is unchanged — gate records are made by `put_gate`.

`reopen_gate` is a store-level move with **no policy**; the position guard lives in the
app layer, which is the only layer that can see the graph (`pitfalls.md` §22).

**Gate**
```bash
grep -c 'draft' src/functualize/_primitives/scope_store.py
```
now: `0` · after: `≥5`

---

## Wave 6 — the answer implementation

### [ ] T11 · `app/_workflow_answer.py` — merge, unset, clear, show, commit, reopen

**Files:** `src/functualize/app/_workflow_answer.py` (new), `src/functualize/app/utils.py`

`answer_gate`, `gate_draft`, `resolve_gate` (joint addressing, each identifier optional
when unambiguous). Auto-commit by default. `missing`/`invalid` come from the same
`ValidationError.errors()` the commit path already produces.

`--reopen` refuses when the walk has passed the gate: the walker records the gate node as
replayed and advances (`workflow_walker.py:298-301`), so reopening would diverge recorded
results from the answer that produced them. Spec AC-11–AC-15.

**Gate**
```bash
python -c "from functualize.app.utils import answer_gate, gate_draft, resolve_gate"
```
now: `ImportError` · after: exit 0

---

## Wave 7 — the answer surfaces

### [ ] T12 · `func builtin workflow answer`

**Files:** `src/functualize/_cli/builtins.py`

Contracts §6.1. `--set K=V` takes JSON-typed values and dotted keys for nested models.

**Gate**
```bash
func builtin workflow answer --help >/dev/null 2>&1; echo $?
```
now: `2` (no such command) · after: `0`

---

### [ ] T13 · MCP `answer_gate` replaces `resume_gate`

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

Takes `workflow_id` **and** `gate`, each optional when unambiguous — closing the hole
where `resume_gate` and `resume_workflow` each referred the caller to the other.

**Gate**
```bash
grep -c 'resume_gate' plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `11` · after: `0`

---

## Wave 8 — the control lift

### [ ] T14 · `app/_workflow_control.py` — the funnel, the gate tool, and the advance

**Files:** `src/functualize/app/_workflow_control.py` (new), `src/functualize/app/utils.py`

Research R2, plan §3. Holds `_guarded_execute` (the gate-policy chokepoint),
`GateToolPolicy`, `call_gate_tool`, `resume_scope`, `advanceable_scopes`, `cancel_scope`
and `purge_scopes`.

**`resume_scope` is the verb this whole feature exists for.** It optionally deposits gate
input first, then walks. Every job-executing path — CLI, MCP, `--wf-resume` — goes through
`_guarded_execute`, so the gate-tool policy cannot be bypassed by a new caller.

The MCP plugin keeps a thin `GateToolPolicy` re-export so `_server.py` is unchanged in
shape.

**Gate**
```bash
python -c "from functualize.app.utils import resume_scope, call_gate_tool, purge_scopes"
```
now: `ImportError` · after: exit 0

**Sabotage:** make `_guarded_execute` skip the policy check; the gate-tool refusal test
must fail.

---

## Wave 9 — the control surfaces

### [ ] T15 · CLI `resume` advances; `gate-tool` and `purge` arrive

**Files:** `src/functualize/_cli/builtins.py`

`resume` stops depositing-and-hinting and walks. Plan R-b: its exit code becomes the
walk's, including 5 for a still-blocked run. `purge` refuses live scopes (schema §5).

**Gate**
```bash
grep -c '@workflow_app.command' src/functualize/_cli/builtins.py
```
now: `4` · after: `7` (`list`, `show`, `answer`, `resume`, `gate-tool`, `cancel`, `purge`)

---

### [ ] T16 · MCP `resume_workflow` advances; `purge_workflows` arrives

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

`resume_workflow` becomes the advance verb, `workflow_id` optional when exactly one scope
is advanceable. This makes `docs/guides/mcp.md:55` (*"Advance a paused workflow"*) true
for the first time.

**Gate**
```bash
grep -c 'mcp.add_tool' plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `6` · after: `6` (`get_workflow_state`, `list_workflows`, `answer_gate`,
`resume_workflow`, `call_gate_tool`, `cancel_workflow`) **+1** for `purge_workflows` = `7`

---

## Wave 10 — the `--wf-*` family

### [ ] T17 · Nine flags, one helper, two injection points

**Files:** `src/functualize/app/adapters/workflow_flags.py` (new),
`src/functualize/app/adapters/click_params.py`,
`src/functualize/app/adapters/lazy_command.py`

Schema §4. One module builds the option list **and** resolves it into a
`WorkflowFlagOutcome`; both constructors call it. Plan R-c — `pitfalls.md` §23 is exactly
this pair, and they have diverged once already.

`--wf-status`/`--wf-show` short-circuit at the top of `wrapper`, before `requires_tty`,
before DI, before the engine (research R1). Spec AC-16–AC-21, AC-25.

**Gate**
```bash
grep -rho -- '--wf-[a-z-]*' src/ | sort -u | wc -l
```
now: `0` · after: `7`

**Sabotage:** remove the `lazy_command.py` call; the warm half of
`test_wf_flags_dispatch_matrix.py` must fail. (This is the exact check that caught the
untested warm path in `workflow-state-durability`.)

---

## Wave 11 — the removal

### [ ] T18 · `--scope-id` deleted, both spellings

**Files:** `src/functualize/_cli/dispatch.py`, `src/functualize/_cli/main.py`,
`src/functualize/app/adapters/click_params.py`, `src/functualize/app/adapters/cli.py`,
`src/functualize/app/_workflow_resume.py`

Contracts §6.3. `app._workflow_scope_id` is **kept** and documented as an API-only seam
for embedded hosts (research R4) — removing it re-opens the hole `_scope_id_option` was
written to fix. The two hits in `_workflow_resume.py` are emitted hint text and must now
name `--wf-resume`. Spec AC-22, AC-23.

Sequenced two waves after T17 deliberately (plan R-d): removing the only advance spelling
before its replacement is wired would strand every blocked run.

**Gate**
```bash
grep -rho -- '--scope-id' src/ | wc -l
```
now: `14` · after: `0`

---

## Wave 12 — the parity test and the docs

### [ ] T19 · The parity test enumerates; it does not sample

**Files:** `tests/workflow/test_workflow_surface_parity.py` (new)

Research R3. Builds the verb/parameter set from the **live Click command tree** and the
**live registered MCP tool list**, then asserts set equality. A hardcoded list would be a
sixth copy (`pitfalls.md` §6); this is §19's rule — *a parity test is the parity*.

Records the one honest exception in the test itself: `--prompt-gates` is CLI-only because
MCP's strategy is `ai_outbound`, which always blocks by design. Spec AC-29.

**Gate**
```bash
pytest tests/workflow/test_workflow_surface_parity.py -q
```
now: file does not exist · after: passes

**Sabotage:** add a parameter to one surface only; the test must fail.

---

### [ ] T20 · Docs, README and CHANGELOG

**Files:** `docs/cli/workflow.md`, `docs/guides/mcp.md`, `docs/guides/workflows.md`,
`docs/guides/composition.md`, `README.md`, `CHANGELOG.md`,
`contributor/reference/workflow-walker.md`, `contributor/architecture/surface-boundary.md`

`surface-boundary.md` §"Worked example — `--scope-id`" is the whole worked example of the
surface rule, built on a flag that no longer exists. It is **rewritten around `--wf-*`**,
not deleted: the rule it teaches is still correct and the new family is a better example
of it (one helper, two injection points, no pre-command spelling).

Research R8: `resume_gate` and `list_active_workflows` appear in prose that must be
**rewritten**, not renamed — `answer_gate` has different addressing. The CHANGELOG names
three breaking changes (`--scope-id` gone, `resume` now advances, two MCP tools removed)
and, per plan §6, states plainly that concurrent `resume` is not fenced.

**Gate**
```bash
grep -rl 'scope-id\|list_active_workflows\|resume_gate' docs/ README.md contributor/ | wc -l
```
now: `7` — `docs/cli/workflow.md`, `docs/guides/{workflows,composition,mcp}.md`,
`README.md`, `contributor/reference/workflow-walker.md`,
`contributor/architecture/surface-boundary.md` · after: `0`

---

## Task Dependency Graph

```json
{
  "waves": [
    {"wave": 1,  "tasks": ["T1", "T2", "T3", "T4"]},
    {"wave": 2,  "tasks": ["T5", "T6"]},
    {"wave": 3,  "tasks": ["T7"]},
    {"wave": 4,  "tasks": ["T8", "T9"]},
    {"wave": 5,  "tasks": ["T10"]},
    {"wave": 6,  "tasks": ["T11"]},
    {"wave": 7,  "tasks": ["T12", "T13"]},
    {"wave": 8,  "tasks": ["T14"]},
    {"wave": 9,  "tasks": ["T15", "T16"]},
    {"wave": 10, "tasks": ["T17"]},
    {"wave": 11, "tasks": ["T18"]},
    {"wave": 12, "tasks": ["T19", "T20"]}
  ]
}
```

**Why these boundaries**

- W1's four tasks touch four disjoint file sets and none depends on another.
- **W2 before W6** — T5 must land before drafts exist (research R7), or the raw-dict
  divergence becomes the draft's canonical format.
- **W3 before W4** — the lift must exist before either surface can call it.
- **W5 before W6** — the accessors before the logic that uses them.
- **W8 before W9** — the funnel before the verbs that must not bypass it (research R2).
- **W10 before W11, with a wave between** — the replacement is wired and asserted before
  the only existing spelling is deleted (plan R-d).
- W12 last: the parity test can only enumerate a surface that exists, and the docs can
  only describe what shipped.

**File-disjointness within each wave** — the pairs that share a wave:

| Wave | Tasks | Files |
|---|---|---|
| 1 | T1 / T2 / T3 / T4 | `_tools.py`+`_server.py` / `workflow_runner.py`+`errors.py` / `main.py` / `_translator.py` |
| 2 | T5 / T6 | `_workflow_resume.py` / `_config.py`+`_server.py` |
| 4 | T8 / T9 | `_workflow_tools.py` / `builtins.py` |
| 7 | T12 / T13 | `builtins.py` / `_workflow_tools.py` |
| 9 | T15 / T16 | `builtins.py` / `_workflow_tools.py` |
| 12 | T19 / T20 | new test file / docs |

No two tasks in a wave share a file. `app/utils.py` is touched by T7, T11 and T14 — all
three are alone in their waves.
