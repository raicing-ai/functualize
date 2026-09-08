# 16 · Without a compat constraint: deleting `--scope-id`, and replacing it entirely

Two questions, taken together because the second answers the first properly:

1. *We don't need to think about existing users — how does that change the `--scope-id`
   recommendation?*
2. *What would need to be added to the builtin / MCP / CLI verb lifecycle to **replace**
   `--scope-id`?*

Supersedes [15](15-scope-id-early-parse-removal.md)'s D1e mechanism and part of
[09](09-target-matrix-and-lifecycles.md)'s invocation-layer matrix.

---

## 1. Answer to (1): the refusal collapses to a plain deletion

[15 §4.1](15-scope-id-early-parse-removal.md) recommended removing the early-parse flag as
a **refusal** rather than a deletion, on two grounds. Audited against "no existing users":

| Ground | Survives? |
|---|---|
| Courtesy to muscle memory | **No** — that was the compat argument outright. |
| Keeping the flag recognised so `detect_mode` still consumes its value | **No, on inspection** — see below. |

The second looked like a parser-mechanics argument. It isn't. `_GLOBAL_OPTIONS_ALWAYS_VALUE`
exists so `detect_mode` can skip a flag **and its value** while hunting the first
positional (`dispatch.py:207-211`). But after removal the *correct* spelling is
post-command — `func release-pipeline --scope-id X` — where `detect_mode` stops at
`release-pipeline` before ever reaching the flag. **The recognition set only matters for
the invocation that is now invalid.** So ground two is also just error-message quality,
i.e. ground one.

### Verified: plain deletion fails loud, never silently

`detect_mode`'s scan (`dispatch.py:199-235`) skips boolean flags, always-value flags,
optional-value flags, `--opt=value` forms and short options. A bare `--unknown-flag` with
no `=` matches **none** of those and falls through to the `break` at `:253` — so **the
flag itself becomes the first positional**, and its value is never examined:

```
$ func --not-a-flag somevalue trip-planner --help
Error: Unknown command 'not-a-flag'.
Run 'func' to see all available commands.
$ echo $?
1
```

Applied to the real flag: `Error: Unknown command 'scope-id'`, exit 1. Confusing, but
**loud, non-zero, and incapable of running the wrong thing** — the stray scope id can
never be mistaken for a job name because the scan stops before it.

**Revised recommendation: delete it outright.** Remove `"--scope-id"` from
`_GLOBAL_OPTIONS_ALWAYS_VALUE`, drop `scope_id` from `GlobalOptions` and the four handler
signatures, and add no refusal branch. Less code, no vestigial member in a set whose
purpose is to enumerate *global* flags, and no permanent apology for a spelling nobody
used. §5 makes the error good anyway, by other means.

### 1.1 The same premise reopens D1 — your call, not mine

D1 kept `resume` because *"it is referenced by generated hints, docs and skills, so
keeping it costs nothing."* That is a compat argument, and it has just been withdrawn.

Worth knowing before you re-decide: **every peer system uses `resume` to mean *advance*.**

| System | `resume` means |
|---|---|
| Temporal | resume a paused workflow — advance |
| pi-workflows | `/workflow resume`, `resumeRun` — advance |
| LangGraph | `Command(resume=…)` — advance |
| Argo | `argo resume` — advance |
| **functualize** | **deposit gate input — does not advance** |

functualize is the outlier, and [14](14-resume-deposit-collisions.md) showed the word
means deposit on every user-facing surface today. Without compat pressure the
industry-aligned split is available:

- **record layer: `answer`** (pi-workflows' word for exactly this) or `deposit`
- **invocation/lifecycle layer: `resume`** — its universal meaning

That **inverts D1b**. Instead of renaming the new flag to `--wf-continue` to dodge a
collision, you free `resume` by renaming the old verb — and then §2 makes the flag
unnecessary altogether, so the collision never arises.

---

## 2. Answer to (2): what replaces `--scope-id`

### 2.1 The enabling observation

`--scope-id` exists because **the invocation names the job and the flag names the scope.**
But a scope record already knows its own workflow: `scope["workflow"]`
(`_blank_scope()`, `state_store.py:45-56`). So *the job name is derivable from the scope
id* — which means a scope can be addressed by id **alone**, with no job on the command
line and therefore no flag to attach to it.

That is why the replacement is a **verb**, not a flag.

### 2.2 The two things the scope record does *not* know

Both are already specified elsewhere in this repo. Neither is optional.

**(a) The launch parameters.** `.spec/shape-intents/workflow-run-parameters.md` is
unambiguous — *"there is no run-scoped channel of any kind"* (`:34`), so a resumed walk
re-resolves every not-yet-recorded step against whatever config and environment the
*resuming* process happens to have. That doc's own demonstration (`:66-70`):

```
$ LAB__STRICT=true func lab release --scope-id <sid>
```
> **One run, one `scope_id`, two answers, selected by the operator's shell.**

A record-layer `continue <id>` with no parameter record would make that defect
**permanent and invisible** — there would no longer even be a shell command carrying the
override. So that shape intent's **Option A** (parameters validated at launch, persisted
with the scope, resolved by later steps) is a hard prerequisite, not an enhancement.

Note the inversion this produces: once parameters are recorded, `continue` is **strictly
better** than `--scope-id`, because it replays the launch-time values instead of
inheriting the resuming shell's.

**(b) The source / entry point.** `_blank_scope()` records no source. So a record-layer
`continue` can only re-enter workflows that ordinary directory discovery finds. Unreachable
without it: a single-file workflow outside the cwd (`func ../sf/weather.py trip_planner`),
a `#!/usr/bin/env -S func` PEP 723 script elsewhere, and anything from
`register_dynamic_job`.

This is **D14** (source identity), already accepted for a different reason — refusing
resume when the graph changed. It pays twice. Today the deposit hint *guesses* the entry
from `argv[0]` at deposit time (`_workflow_resume.py:95-101`); recording it at start is
strictly better and is the same field.

### 2.3 The replacement surface

> **Superseded by [18](18-three-tier-surface.md).** This section deleted the job-side
> control surface entirely. The current design keeps it as a convenience subset:
> `--wf-continue [id]` replaces `--scope-id`, with the rich verbs on
> `builtin workflow` and MCP at parity. §1 (delete the early-parse flag) still stands.


**One new verb per surface. Nothing on the job.**

| Surface | Verb | Contract |
|---|---|---|
| builtin CLI | `func builtin workflow continue <id> [--input JSON] [--gate NAME] [--set K=V]` | advances the walk in-process to the next durable boundary |
| MCP | `continue_workflow(workflow_id, input?, gate?)` | same, in the server process |
| workflow job | — | **starting is the job command's only role** |

`--input`/`--gate` fuse answer-and-advance at the record layer, which is what
[09 §L1](09-target-matrix-and-lifecycles.md) wanted from `--wf-resume`/`--wf-input` —
delivered without a job flag. `--set` is the explicit, recorded parameter override that
replaces "resume under a different shell".

**Deleted by this design:**

- the early-parse `--scope-id` (§1)
- the **per-command** `--scope-id` (`_scope_id_option`, both injection points)
- `--wf-resume` / `--wf-continue` — never built
- `--wf-gate`, `--wf-input` — move to `continue`
- `run_job(scope_id=…)` — replaced by `continue_workflow`
- the whole "per-command wins over pre-command" precedence rule
  (`click_params.py:1040-1042`) and its tests

That is a strictly smaller surface than [09 §2.2](09-target-matrix-and-lifecycles.md)
proposed. This section supersedes that table's `--wf-resume` family.

### 2.4 The verb lifecycle, complete

| Phase | Verb | Layer | Advances? |
|---|---|---|---|
| start | `func <wf> [config…]` · MCP `run_job(name, config)` | execution | yes (first walk) |
| observe | `func builtin workflow list \| show <id>` · MCP `list_workflows` / `get_workflow_state` | record | no |
| answer | `func builtin workflow answer <id> <gate> [--set K=V \| --input JSON]` · MCP `answer_gate(...)` | record | **no** |
| **advance** | **`func builtin workflow continue <id> [--input JSON]`** · MCP `continue_workflow(id)` | record | **yes** |
| investigate | `func builtin workflow gate-tool <id> <tool>` · MCP `call_gate_tool` | record | no |
| recover | `continue <id> --retry-epilogue` | record | yes |
| end | `cancel <id>` · `purge` | record | no |

Two properties this buys that no flag arrangement can:

1. **The job command has exactly one contract: start a fresh run.** No mode switch, no
   flag that changes it from "run" to "resume", no `--help` that grows for `@workflow`
   jobs only.
2. **`resume`/`continue` sits on the surface a second actor already uses.** A scheduler,
   a CI job or an MCP agent addresses runs by id through one group — it never needs to
   know which job produced a scope, or how to spell its invocation.

### 2.5 What it costs, honestly

- **`builtin workflow` gains the ability to execute a job.** Today `list`/`state`/`cancel`
  read the store with no boot and `resume` boots only to materialize a gate model. A
  `continue` that walks a graph is a genuine boundary change for that group — deliberate,
  and it must route through the same `_execute_job` funnel so the gate-tool policy and
  refusal machinery still apply (`_server.py:239-242`).
- **`--set` needs a validated model** or it re-creates the untyped-override problem the
  run-parameters doc exists to solve. Take that doc's Option A shape, not an ad-hoc dict.
- **Two prerequisites are real work**: run-scoped parameters and source identity. Neither
  is invented here; both are already specified.
- **Concurrency becomes visible.** When advancing no longer requires knowing the job, two
  actors will `continue` the same scope. Today the flock serializes writers but nothing
  fences a stale walker ([02](02-corrections.md)) — so this raises the priority of the
  Tier-2 lease, from "durability nicety" to "the thing that stops two schedulers
  double-walking a run".

---

## 3. Sequencing

| Step | Depends on | Note |
|---|---|---|
| 1. Delete the early-parse `--scope-id` (§1) | D1f (SINGLE_FILE crash) | Standalone; per-command option keeps working |
| 2. Run-scoped parameters on the scope | — | The existing `workflow-run-parameters.md` Option A |
| 3. Source/entry identity on the scope | — | D14; also gives graph-change refusal |
| 4. `builtin workflow continue` + MCP `continue_workflow` | 2, 3 | The replacement |
| 5. Delete the per-command `--scope-id` | 4 | **Only after** `continue` covers every mode 15 §1.2 tested |
| 6. Re-decide D1/D1b vocabulary (§1.1) | — | Your call; cheapest before step 4 names its verbs |
| 7. Lease/fencing | 4 | Promoted — step 4 makes concurrent advance easy |

Step 5 is the gate that matters: **do not remove the per-command flag until `continue`
has been exercised in all five invocation paths** — JOB, GROUP, UNKNOWN, SINGLE_FILE and
the embedded app — because for the last two it depends on step 3 having recorded enough to
re-enter. That is the same per-mode test matrix [15 §1.2](15-scope-id-early-parse-removal.md)
built, reused as the acceptance criterion.

## 4. Recommendation in one paragraph

Without compat pressure, delete the early-parse flag outright — plain deletion fails loud
with exit 1 and cannot misexecute, so the refusal branch is not worth its code. But the
better answer to the real question is that **`--scope-id` should not be replaced by a
different flag; it should be replaced by a verb.** A scope already knows its own workflow,
so `func builtin workflow continue <id>` addresses a run without naming a job — which
deletes both `--scope-id` spellings, `--wf-resume`, `--wf-input` and `--wf-gate` at once,
and leaves the job command with exactly one contract: start. It needs two things the scope
record does not yet hold — the launch parameters and the source — and both are already
specified in this repo, one of them (D14) for an unrelated reason. Do those two, add one
verb per surface, and the flag has no remaining job.
