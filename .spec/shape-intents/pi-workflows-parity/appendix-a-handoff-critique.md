# Appendix A · Critique — `handoff-wf-status-decision.md`

Source: `../functualize-vs-pi-workflows/handoff-wf-status-decision.md`

**Assessment: good instincts, unsafe as written.** The decision framing is sound and
Candidate C is the right answer. But the handoff carries four factual errors — one of
which will make an implementer break the build — and specifies a surface whose headline
columns cannot be rendered from state that exists. Do not hand this to an implementer
unamended.

---

## Verdict on the open question: **C, with one correction the handoff misses**

C is right, and for the reason given: `--wf-resume` must print the survey inline when it
errors ambiguously, so the survey logic has to be callable from the job side regardless
of whether a flag exists.

**The correction:** the handoff says to implement the survey *"over existing state only —
`StateStore.get_scope/scope_ids`, `pending_gates`, gate records' `input_schema`"*. That
is an instruction to hand-roll, from primitives, a projection that **already exists**:
`_describe` in `plugins/functualize-mcp/.../_workflow_tools.py:471-509` computes the
declared graph (`steps` + `edges`), `current_position`, `branches`, `pending_gates` with
schemas and bound-arg-stripped tool summaries, and per-step `status` / `return_value` /
`inputs` / `completed_at` — with `_topology` (`:511-536`) falling back to the live
declaration for plugin-registered workflows.

Following the handoff literally produces a **third** implementation of scope summarizing
(CLI `_scope_summary`, MCP `_describe`, new `--wf-status`) — and directly violates the
handoff's own stated principle two paragraphs earlier: *"one implementation both CLI and
MCP call; preserve that pattern."*

### The shape to build instead

Lift `_describe`/`_topology` out of the plugin the way `deposit_gate_input` was lifted,
and follow the repo's own convention for exactly this kind of surface —
`src/functualize/_cli/info.py`, which the handoff already points at:

| `info.py` precedent | workflow survey equivalent |
|---|---|
| `job_catalog(app)` / `job_detail(app, name)` — pure projections | `scope_catalog(store, app, filters)` / `scope_detail(store, app, scope_id)` |
| `render_catalog_text` / `render_report_text` | `render_scope_table` / `render_scope_detail` |
| `resolve_renderer(json_flag, cli_config)` | same function, reused |

Then **four** thin callers, no duplicated logic:

1. `func <wf> --wf-status` (job side, filtered to that workflow)
2. `func builtin workflow list` / `state` — which today emits five fields over a store
   holding all of the above
3. MCP `list_active_workflows` / `get_workflow_state` — re-pointed at the lifted code
4. `--wf-resume`'s ambiguity error path

This merges the handoff's work with roadmap item 3 ([13](13-roadmap.md)): they are the
same work, and doing them together is strictly cheaper than doing either alone.

---

## Factual errors — fix before implementing

### E-1 · "three call sites" of `_scope_id_option()` — there are **two**, and the third named one is a trap

Handoff, implementation step 2: *"pattern: `_scope_id_option()` in `click_params.py:56-72`
and its three call sites — `create_job_click_command`, `build_click_params_from_descriptor`
path, `lazy_command.py:167-168`."*

Verified: `_scope_id_option` is referenced at exactly two injection points —
`click_params.py:1233` (cold path, gated on `_declares_workflow(function)`) and
`lazy_command.py:168` (warm path, gated on `descriptor.workflow is not None`).

`build_click_params_from_descriptor` (`click_params.py:214-225`) returns
`build_click_params_from_fields(descriptor.config_fields)` and **does not add the
option**. It has exactly one caller: `lazy_command.py:163`, which appends the option
*after* the call.

An implementer who follows this instruction and adds `--wf-status` inside
`build_click_params_from_descriptor` **double-adds it on the lazy path**. Click will
either raise on the duplicate or silently shadow one with the other, and the failure will
surface only on a warm cache — the exact conditions under which the documented
cold-cache bug (`main.py:2075-2081`) was hard to find.

### E-2 · Decision 3's parity premise is false today

*"Builtin workflow commands keep 1:1 parity with the functualize MCP workflow tools."*

They do not. CLI `func builtin workflow resume <workflow_id> <gate>`
(`builtins.py:900-911`) addresses **both**. MCP `resume_gate(gate, input)` addresses a
gate only; `resume_workflow(workflow_id, input)` addresses a scope only; each refers the
caller to the other on ambiguity, and no MCP tool accepts both. `list`/`state` drift too
(five fields vs. the full `_describe` projection).

Treating a false premise as binding preserves the drift. Restate decision 3 as an
*intent* and add joint addressing to the MCP tool as part of this work.

### E-3 · Instruction 5 widens the drift it invokes parity to justify

*"Mirror on MCP only if trivial: `list_active_workflows` gains optional `workflow_name`
filter (parity with builtin `list --workflow`)."*

If the builtin gains `--workflow`, `--status`, `--actor` and `--blocked-on` (Candidate B)
and MCP gains only `workflow_name`, the surfaces are **less** aligned after this change
than before. Either add the same filter set to both, or make the filter set smaller on
both. The lift in §"the shape to build instead" makes "the same set on both" nearly free.

### E-4 · Minor citation drift

| Handoff | Actual |
|---|---|
| `_scope_id_option()` at `click_params.py:56-72` | `:56-73` |
| `workflow_runner.py:104-133` | `prelude` is `:101-127`; `record_body` `:129-144` |
| `_cli/builtins.py:819-949` | workflow group is `:820-951` |

---

## Design blockers the handoff does not know about

### B-1 · Scope state has **no timestamps at all**

`_blank_scope()` (`state_store.py:45-56`) is:

```python
{"workflow", "status", "steps", "branches", "gates", "position", "epilogue", "tool_calls"}
```

No `started_at`, no `updated_at`, no `blocked_at`. The only time data anywhere is
`blocked_at` on **gate** records and `completed_at` on step/epilogue records.

Candidate A's spec asks for "last actor", and doc 07's mock output — which the handoff
inherits — has three time columns:

```
a3f9c2e1b7d4  blocked    at approve   gate: approval   awaiting 2h   resumed-by: human
7f01cc9e2244  running    at deploy    —                started 5m ago
0c81b3a6f002  completed  (epilogue done: success)      finished 1d ago
```

`started 5m ago` has **no source in state**. `resumed-by: human` requires the provenance
schema from doc 06, which is a design, not code. `finished 1d ago` is derivable from the
epilogue's `completed_at`. And `awaiting 2h` is wrong for the reason in B-2.

So *"No engine changes needed for the survey"* is only true if you drop those columns.
Adding them means writing timestamps at scope creation and at block — a store change, and
one that touches the same envelope as [13 item 0](13-roadmap.md).

**Recommendation:** ship the survey **without** time columns and without `--actor`, and
say so. Add `started_at` / `blocked_at` to the scope root in the same change that lands
provenance, not before.

### B-2 · `blocked_at` measures the last *poke*, not the wait

`_block(node)` calls `FrontierWalk.block(...)` with `blocked_at=_now()`
(`workflow_walker.py:459-472` → `frontier.py:164-200`), and `put_gate`
(`state_store.py:215-222`) **replaces the whole gate record**.

`_block` runs on *every* walk that reaches a still-unanswered gate. So every
`func <wf> --scope-id X` that re-blocks resets `blocked_at` to now.

Two consequences:

- doc 07's `awaiting 2h` column would report time since the last resume attempt, not time
  waiting — actively misleading on exactly the scope a human is poking at.
- **the "newest-blocked" tiebreak is unimplementable correctly**, because "newest" would
  mean "most recently re-attempted".

(The payload itself is safe: `_block` is only reached when `payload is None`, so a
deposited answer is never clobbered.)

### B-3 · The handoff contradicts itself on the ambiguity rule

| Decision 2 | Implementation step 2 |
|---|---|
| *"with no id it resumes the workflow's single/**newest-blocked** scope"* | *"several → list them, exit 2. **Never silently pick.**"* |

These are incompatible: "newest wins" *is* silently picking. Given B-2, "newest" is also
not correctly computable.

**Recommendation:** adopt step 2's rule — zero → error naming `--wf-status`; exactly one →
use it; several → list and exit 2 — and strike "newest" from decision 2. This also
matches source doc `07-workflow-job-flags.md` §2, which the handoff's decision 2
paraphrases incorrectly.

### B-4 · `--wf-input` will ship a payload-shape bug into the fused path

`deposit_gate_input` (`app/_workflow_resume.py:82-90`) validates with `model(**payload)`
and then stores the **raw dict** — discarding Pydantic defaults and coercions. The
walker's own strategy path stores `model.model_dump()` (`workflow_walker.py:270-277`).

Today the divergence is easy to miss because deposit and execution are separate commands
run minutes apart. `--wf-resume --wf-input` fuses them, so the node consumes the
defaults-less payload **in the same command**, and the user watches it happen.

**Fix first** (two lines): make `deposit_gate_input` store `model(**payload).model_dump()`.
This is also a precondition for the partial-deposit design in
[04-gate-deposit.md](07-gate-answers.md), which must not accumulate raw fragments.

### B-5 · The survey makes an existing latent bug reachable

`--wf-status --wf-all` includes `cancelled` scopes. A user will then run `--wf-resume
<that-id>` — which **works**: `WorkflowRunner.prelude` never reads scope status
(`workflow_runner.py:101-127`), `FrontierWalk.start` returns the persisted position
without a status check (`frontier.py:95-107`), and the string `cancelled` appears **zero
times** across `executor.py`, `workflow_walker.py` and `workflow_runner.py`.

Meanwhile `cancel_workflow`'s MCP description states *"Cancelled scopes are not
resumable."*

Shipping a surface that lists cancelled scopes next to a resume flag turns a latent
contract violation into a routine one. Land the three-line status guard in `prelude` (or
delete the sentence) **with** this work — [13 item 2](13-roadmap.md).

### B-6 · `--actor` requires provenance that does not exist

Both Candidate A ("last actor") and Candidate B (`--actor`) specify a field from
`06-provenance-metadata.md`, which is a design document. Nothing writes an actor today.
Either sequence provenance ahead of the survey or cut `--actor` from this scope and say
so in the acceptance criteria. Leaving it in the candidate descriptions invites an
implementer to invent a capture mechanism ad hoc.

---

## What the handoff gets right (keep)

- **Candidate C, and the reason for it** — `--wf-resume`'s ambiguity path needs the
  survey inline, so the logic must be shared regardless.
- **"Never silently pick"** on ambiguity. Correct, and consistent with the repo's
  explicit-over-hidden principle.
- **Exit 0 on an empty listing** — *"emptiness is data, not error."* Correct.
- **Decision 4, rejecting `--fresh`** — absence of a resume flag already means a new
  scope; a second spelling for "new" adds a cold-cache plumbing risk for nothing.
- **Decision 1, keeping the early-parse layer untouched.** Stronger than the handoff
  argues: only two builders add the per-command option, and the warm one is gated on the
  discovery cache carrying workflow topology — the documented cold-cache hazard. The
  pre-command global is the only spelling guaranteed on every dispatch mode.
- **The cold-cache guard test requirement**, one test per dispatch mode. Well-sourced
  (`main.py:2075-2081`) and non-negotiable.
- **Pointing at `_cli/info.py`** for output shaping. Exactly the right precedent — the
  handoff just does not follow it through to "so lift the projection".
- **Not adding advance-on-resume to MCP in this change.** Sensible scoping; it is a
  separate decision with a separate blast radius.

---

## Amended instructions — what to hand the implementer

1. **Land two prerequisites first**, both tiny, both independently correct:
   `deposit_gate_input` stores `model_dump()` (B-4); `prelude` refuses a `cancelled`
   scope, or the `cancel_workflow` sentence is deleted (B-5).
2. **Lift `_describe`/`_topology`** into `src/functualize/app/` beside
   `_workflow_resume.py`, split projection from rendering per `_cli/info.py`. Re-point
   MCP `get_workflow_state` / `list_active_workflows` at the lifted code — behaviour
   preserving, and it is what makes the parity claim true.
3. **Re-point `func builtin workflow list`/`state`** at the same projection. This is the
   change with the largest ratio of user-visible improvement to code written: the human
   surface goes from five fields to the full graph with results.
4. **Then** add `--wf-status` / `--wf-blocked-only` / `--wf-all` as a thin filtered
   caller, and `builtin workflow list` filters (`--workflow`, `--status`,
   `--blocked-on`) — **the same filter set on the MCP tool**, per E-3.
5. **Then** `--wf-resume` / `--wf-input` / `--wf-gate`, with step 2's ambiguity rule and
   no "newest" (B-3).
6. **Cut from scope, with a note in the acceptance criteria:** `--actor` (B-6), and every
   time column (B-1, B-2).
7. Add the two injection points for each new per-command flag —
   `click_params.py:1233` and `lazy_command.py:168` — **not** three (E-1).
8. Cold-cache guard tests per dispatch mode, as specified. Unchanged.

### Amended acceptance criteria

Keep the handoff's four, and add:

- `func builtin workflow state <id> --format json` returns the same projection as MCP
  `get_workflow_state` for the same scope. *(The parity claim, made testable.)*
- A gate model with a defaulted field, answered via `--wf-input`, reaches the node with
  the default populated — identical to the same gate answered by a `prompt` strategy.
  *(B-4, made testable.)*
- Resuming a cancelled scope either refuses or the `cancel_workflow` description no
  longer claims it cannot. *(B-5, made testable.)*
- `--wf-status` output contains no column that state cannot source. *(B-1.)*
