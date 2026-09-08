# 13 · Roadmap

The previous study's three workstreams (W1 durable run layer · W2 agent step contract ·
W3 observation) are still the right decomposition. What changes is **what comes before
them**, and **the shape of W2**.

Items 0–4 are small, independent of each other, and together close more of the practical
agent gap than W1 does.

---

## Tier 0 — defects, not features

### 0. Stop `scopes` being silently discarded — **blocking**

`load_state` degrades any unreadable state to `empty_state()`
(`state_format.py:168-175`); `normalize_state` does the same on a `format_version`
mismatch (`:150-151`); every writer is `update_state` = load → mutate → save
(`:296-310`). So the next ordinary write persists the empty envelope.

The header comment justifies it (`:41-42`):

> *A version mismatch discards the file (runtime state is derived, never a source of
> truth — the worst case is one extra run).*

The next line of the same comment lists `scopes (per-scope step records, recorded branch
choices, gate payloads, blocked position, epilogue record)`. **A blocked run holding a
human's approval is not derived state.** The rationale was written when the envelope held
only fingerprints.

Proven by experiment (transcript in [evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md)): set up a blocked scope with a
deposited approval, bump `format_version`, write one unrelated fingerprint — scope gone,
no error, no backup.

Same root cause, second symptom: **`func builtin state clear`** writes `empty_state()`
(`state_store.py:361-365`) under help text that says *"fingerprints, history"* and
*"Reset runtime state"*. It never mentions scopes.

**Fix:** either give `scopes` its own file and version, or fail closed on a
scopes-bearing mismatch — rename to `state.json.bak-v1`, refuse, print the recovery
command, the way pi-workflows does (`SQLITE_STATE.md:47-67`). And make `state clear` name
what it destroys, with a `--keep-scopes` default or an explicit confirmation.

*Do this first: it is the only item where delay costs users data, and item 4 adds a
field to the same envelope.*

### 1. Return `metadata` from every MCP execution door

`run_job`, `run_job_async`/`get_execution_status`, `_execute_job`. Today an agent that
blocks a workflow receives `"Blocked"` and nothing else, and must call
`list_active_workflows()` and guess which scope is its own.

Take the two adjacent fixes in the same change: normalize `RunStatus` (`_execute_job`
returns the raw `Enum`, `run_job` returns `.value`), and decide whether the wire value is
`"Blocked"` or `"blocked"` — the docs say one, the code says the other.

**Size:** three return dicts. **Unblocks:** every agent story, and the per-job-tool
reduction in item 5.

### 2. Make `cancel` mean something

`cancel_workflow`'s description says *"Cancelled scopes are not resumable."* Nothing
enforces it — `cancelled` appears zero times across the executor, walker and runner.

Either enforce it (one status check in `WorkflowRunner.prelude`, which already receives
the store) or delete the sentence. Enforcing is three lines and is the more useful half
of a real `cancel`; stopping a *live* walk is separate and belongs in W1.4.

### 3. Lift the scope projection — one implementation, four callers

`_describe` (`_workflow_tools.py:471-509`) computes the full graph, position, branch
choices, per-step return values and resolved inputs, and gate schemas. The CLI's
`_scope_summary` emits five fields over the same store.

Lift `_describe`/`_topology` into `src/functualize/app/` beside `_workflow_resume.py` —
the same lift `deposit_gate_input` already received — splitting projection from rendering
per `_cli/info.py`'s `job_catalog` / `render_catalog_text` / `resolve_renderer` pattern.
Then four thin callers: `builtin workflow list`/`state`, MCP
`list_active_workflows`/`get_workflow_state`, `--wf-status`, and `--wf-resume`'s
ambiguity error path. Also lift `call_gate_tool`, which is MCP-only today for no reason.

This is the previous study's **W3.1**, sequenced behind W1's event log for no reason, and
it is **the same work as the `--wf-status` handoff** — see
[08-handoff-critique.md](appendix-a-handoff-critique.md). Doing them together is strictly cheaper
than doing either alone, and it is what makes the CLI↔MCP parity claim true rather than
aspirational.

**Cut from scope until state supports them:** every time column, and `--actor`. Scope
records carry no timestamps at all (`_blank_scope`, `state_store.py:45-56`), and the
gate-level `blocked_at` resets on every re-block, so it measures the last resume attempt
rather than the wait ([01 §C.6-C.7](01-current-state.md)).

---

## Tier 1 — the continuation gap

### 4. Gate answers: partial, whole, corrected

Full design in [07](07-gate-answers.md). A `draft` slot beside `payload`;
`payload` still only ever written by a complete, valid `model_dump()`. Fixes the
raw-dict-vs-`model_dump()` divergence between the answer and strategy paths as a
precondition. Adds `answer_gate(id?, gate?)` joint addressing on MCP, which restores the
parity the previous study assumed already held.

No engine change, no walker change, no new state section.

### 5. The three-tier surface — `answer`, `resume`, and the `--wf-*` subset

The whole of [05](05-target-surface.md), landed as one release: the rich `builtin
workflow` verbs, MCP at parity behind the parity test, and the nine `--wf-*` convenience
flags. `--scope-id` is deleted here, both spellings ([12](12-scope-id.md)), and
`--wf-resume [id]` replaces it.

Everything needed already exists — `deposit_gate_input` validates, the walker re-enters on
a scope id. The work is one command path per verb, one shared implementation in `app/`,
and the per-dispatch-mode tests the repo demands for state-addressing flags.

**Two prerequisites, both tiny.** Item 4 makes `deposit_gate_input` store `model_dump()`,
without which fusing an answer with a resume shows the raw-dict divergence inside a single
command. Item 2 fixes `cancel`, because a survey that lists cancelled scopes beside a
resume verb turns a latent contract violation into a routine one.

**Ambiguity rule:** zero candidates → error naming the survey verb; exactly one → use it;
several → list and exit 2. Never "newest wins" — `blocked_at` resets on every re-block, so
it is not computable anyway.

**Also here:** fix the SINGLE_FILE cwd crash ([12 §4](12-scope-id.md)), which otherwise
blocks one of the five per-mode tests.

### 6. Trim the MCP tool surface

Per [04 §3](04-mcp.md): a `job_tools: "all" | "tagged" | "none"` mode in
`MCPConfig`, and stop appending examples to per-job tool descriptions when the schema
already carries them. Depends on item 1 — turning per-job tools off must not cost
information the generic door lacks.

---

## Tier 2 — the previous study's W1/W2/W3, re-shaped

### 7. W2 as a port, not a node kind

Per [03 §1](03-pi-workflows.md). One Protocol with declared capability flags —
`enforces_tool_allowlist`, `preserves_active_time_budget`, visible-output support — and
an engine that **refuses** a workflow needing a capability the executor lacks rather than
degrading. Implementations: MCP-elicitation, CLI-prompt, `functualize-ai`.

This is what functualize's own constitution already prescribes (ports-as-Protocol), and
it is the same ladder shape as `GateStrategy` / `PromptCollector`. It also supersedes the
previous study's honest-boundary hedge about tool restriction: type the boundary, do not
document it.

### 8. W1 durable run layer

Events, lifecycle verbs, runner + leases, per-step timeouts, thin effects outbox. Largely
as the previous study described, with two corrections:

- **W1.3 source identity:** canonicalize the *graph projection* (`workflow_shape_of` →
  `to_dict()`), not the file. Ship the revision/legacy-mapping story with it, not after —
  see [03 §2](03-pi-workflows.md). Without it the first shipped workflow change
  strands every in-flight run.
- **Item 0 must land first.** W1 will bump the state format.

### 9. W3 remainder — loops, failure routing, watch, notify

Unchanged in substance. When failure routing lands, copy pi-workflows' typed outcome
vocabulary (`timed_out` / `cancelled` / `failed`, [03 §6](03-pi-workflows.md)) —
routing on a boolean discards the distinction that makes fix-loops useful.

Demoted from the previous study: **`--wf-retry-failed` is largely redundant.** Failed
steps already re-run on resume ([02 §9](02-prior-study-corrections.md)). `--wf-retry-epilogue` is the
one that is genuinely needed, because the epilogue record *is* sticky on failure.

---

## Sequencing

| Tier | Items | Depends on | Shape |
|---|---|---|---|
| 0 | 0, 1, 2, 3 | — | Four small independent fixes. Ship together. |
| 1 | 4, 5, 6 | 1 (for 6), 0 (for 4) | The continuation story. One release. |
| 2 | 7 | 5 | The port. One release. |
| 2 | 8 | 0 | Multi-release. |
| 2 | 9 | 8 | Incremental. |

## Parity tests (unchanged from the previous study, still the right ones)

1. An agent in Claude Code (MCP only) starts a workflow, executes two agent steps,
   handles one validation rejection, publishes progress, and drives it to completion —
   no human typing at any point.
2. `kill -9` the runner mid-workflow; a new runner resumes from the last committed node;
   an effect step re-runs exactly once.
3. A human edits the workflow **graph**; resume refuses. A human edits an unrelated job
   in the same file; resume **succeeds**. *(Second half added — it is the test that
   fails if W1.3 hashes the file.)*
4. A gate marked *protected* cannot be answered by the agent even though the agent
   answered the previous checkpoint.
5. `func builtin workflow watch` shows the live graph while the above runs.
6. **New:** bump `STATE_VERSION`; every blocked scope survives, or the run refuses to
   start with a recovery instruction. Never silently empty.
