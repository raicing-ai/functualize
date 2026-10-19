# effecting-step-recovery — specification

**Phase:** Plan. Specify was confirmed on 2026-10-17 (Q-1, Q-2 as recommended). Revisions S-R1 to S-R4, forced by the architecture pass (`plan.md`) and marked *[S-Rn]*, were confirmed by the member on 2026-10-19. The spec is fixed from here.
**Shape:** *Shape Intent — Effecting Steps Across a Crash* (Confluence SD/15007820),
`Authority: Approved` (v9, 2026-10-13). Decisions of record: D1 = A, D2 = 2a′,
D3 = 3a, D4 = 4a, D5 = 5a. "The matrix" means the Part I composition matrix.
**Baseline:** `origin/master` at `d1c7e40a` (rebased; the lease-heartbeat change has landed). Findings that shaped this file are in
`research.md` (R1–R10).

## Problem

`Step(effecting=True)` promises that a step "must run **exactly once** across a crash
and a resume" (`_types/workflow.py:131-133`, `_engine/frontier.py:99-107`). Today the
flag is recorded and never read. `rg -n is_effecting src plugins` returns two lines:
the definition (`frontier.py:99`) and one write into the step record (`frontier.py:479`).

A step has no record until its job returns and `complete()` commits. If the process
dies after the job has caused its effect and before that commit, a resume finds no
record and runs the job again. The card is charged twice.

Nothing can observe an effect outside the store. The engine sees only its own
writes, and any write after the effect can be lost in the same crash. So this
feature does not claim to detect effects. It records the one fact the engine can
know — *the job was handed control* — and when that fact is not enough to decide,
it stops and asks.

**The guarantee, in the approved words:** *an in-flight effecting step is never
re-run without a decision, and it is exactly-once once that decision is made.*

## Users

- **Workflow author.** Marks a step `effecting=True` because running it twice is
  harmful (a charge, an email, a ticket). Expects the flag to change behaviour, not
  just documentation.
- **Operator.** Resumes or reclaims a workflow after a crash. Must be told when the
  engine cannot know whether an effect happened, and must be able to answer from
  any surface that answers a gate (CLI, API/MCP, and Slack once that lands).
- **Reviewer or auditor.** Reads a scope's record afterwards and must be able to see
  that a step was in doubt, who decided, and what they decided.

## User stories

1. As an author, when the process dies inside my effecting step, the resumed
   workflow does not run that step again on its own.
2. As an author, when the process dies *before* my effecting step began, the resumed
   workflow runs it normally, with no question asked.
3. As an operator, a workflow that stopped in doubt tells me which step, which
   attempt and when it started, and waits for my answer for as long as it takes.
4. As an operator, I answer "it ran" and the workflow continues without repeating
   the effect. Or I answer "it did not run" and the step runs again, because I
   decided it should.
5. As an author of a workflow with no effecting step, nothing about my workflow's
   behaviour, records or digest changes.

## Behaviour

### B1 — The attempt

Before the engine hands control to an effecting step's job, it durably records that
an attempt has begun: status `attempting`. That record carries the attempt number,
the start time, and `effecting: true`. The attempt key is derived from the scope,
the step key (including loop pass) and the attempt number, and is not stored.
Writes are fenced by the walk's lease generation, which is not stored either.
*[S-R2]*

Every way the attempt ends replaces `attempting` with that ending, exactly as
today's records do:

| The step… | Recorded |
|---|---|
| returns | `success` |
| raises | `failed` (D5 = 5a) |
| is cancelled | `cancelled` |
| ends `BLOCKED` (a guard block, or a nested gate) | `blocked`. This is an ending, not doubt, and a resume re-runs the step as today *[S-R3]* |
| takes a routed failure (`OnFailure`) | `failed`, then the declared route |
| is skipped as fresh (fingerprint) | `success` |

A pure step (`effecting=False`, the default) records no attempt.

### B2 — Doubt

A step is **in doubt** if and only if, when a walk reaches it, its record for the
current loop pass has status `attempting`. On reaching an in-doubt step, a walk:

- never runs the job;
- records the step `in_doubt`;
- stops `blocked` on the step's **recovery gate** (B3), with a reason naming the
  step, the attempt number and the attempt's start time;
- runs nothing downstream of the step.

The decision follows the **record**, not the current declaration. What the step
*was* when it started is what counts.

A takeover of an abandoned scope (`reclaim`) whose position holds an `attempting`
record leaves it untouched; it never writes `timed_out` over it. The walk that next
reaches the step records `in_doubt` and stops as above. *[S-R1]*

### B3 — The recovery gate

`effecting=True` implies exactly one **declared** gate per effecting step, named
`<step>-in-doubt` (contracts C2). It is part of the workflow's declared graph. It is
addressable everywhere a declared gate is: status and `blocked_on`, answer, the
answer-and-resume command, API/MCP gate tools, and the workflow's shape and graph
digest.

It is **opened only when a walk finds the step in doubt**. A normal run never opens
it.

Its answer has exactly two outcomes, `ran` and `did_not_run`, with **no default**,
and an optional `value`.

- **`ran`** records the step `success`. The return value is the answer's `value`.
  When no value is given, the return value is empty and marked not reusable, so a
  downstream `FromJob` / `FromStep` fails loudly instead of reading an invented
  value. The walk continues as if the step had completed.
- **`did_not_run`** discards the attempt. The step runs again as attempt *n+1*, with
  the same attempt rules (B1). The walk continues.

An invalid answer is refused and the gate stays open.

### B4 — Nobody answers by default

The recovery gate is answered only by an explicit answer:

- a person at an interactive prompt (when prompt-gates is on), or
- a deposited answer (`answer` / `--wf-resume --wf-input`).

It is **never** answered by:

- the config chain (`resolve`);
- an AI strategy (`ai_inbound`, `ai_outbound`);
- a decision provider (`decision`);
- a default value, or a cancelled or empty prompt;
- a timeout. It has none.

Ctrl+C or the absence of a TTY leaves it pending (Northstar D-3, Q-8).

### B5 — One answer per doubt

Each doubt is asked and answered once. An answer given for one doubt never resolves
another:

- a different loop pass: an answer for pass *n* never resolves a doubt on pass *m* ≠ *n*;
- a later attempt: after `did_not_run`, a second crash in attempt *n+1* asks again
  and never replays the first answer. *[S-R4]*

The question shown to whoever answers names the step, the attempt, the loop pass
and the attempt's start time.

### B6 — Composition (the Part I matrix, E axis)

| Cell | Behaviour |
|---|---|
| E×D (the step's job has `Deps`) | The attempt covers the dependencies. A crash while a dependency runs leaves the step in doubt. Doubt is per step, never per dependency |
| E×I (the job body calls `inv()`) | The attempt covers invoked children. A crash inside one leaves the step in doubt |
| E×W×W (the step's job is itself a workflow) | **Refused at boot validation.** The child's own steps declare their own flag |
| E×G (a gate before an effecting step, ADR-030) | Unchanged. The recovery gate is separate and comes after |
| E×Loop | per pass (B5) |
| E×OnFailure | a raise is `failed` and is routed as today (B1) |
| E×fingerprint SKIPPED | `success`. No doubt |
| E×Notify | an in-doubt stop is a `blocked` stop. See *Known limitation* |

### B7 — The declaration

- A workflow that declares a node whose name equals a derived recovery-gate name is
  refused **at declaration time**, alongside the existing duplicate-name refusal.
- The workflow's shape and graph digest include each effecting step's flag and its
  recovery gate. A workflow with no effecting step projects and digests
  byte-for-byte as before.
- A scope parked under a digest recorded before this change refuses to resume with
  the existing graph-changed refusal. This happens once, and only for workflows with
  an effecting step. It is the pre-1.0 stance (`.spec/CONSTITUTION.md` →
  *Pre-Release Stance*), and the release note says so.

### B8 — What the documentation says

The `Step.effecting` docstring (`_types/workflow.py:131-151`), `is_effecting`
(`frontier.py:85-93`) and the workflows guide (`docs/guides/workflows.md`) state the
guarantee in the approved words. They make no unqualified "exactly once" claim and
no "at-most-once" claim. They also state D5: a raise is the job's own account, so an
effecting job that raises after its effect has happened must say so itself.

## Acceptance criteria

Each criterion is an executable check. The kill tests use a real `SIGKILL`, as
`tests/integration/test_crash_and_resume.py` does today. The *window* is the
interval between the attempt committing and the completion committing.

| # | Criterion | Issue criterion / shape experiment |
|---|---|---|
| AC-1 | `effecting=True`, killed inside the window (the effect has happened and the job has not returned), then resumed: the marker shows the effect **once**; the step is `in_doubt`; the scope is `blocked` with `blocked_on` = `<step>-in-doubt` and a reason naming the step and attempt; the next step did not run | 1, 3, 5 / E1 |
| AC-2 | `effecting=True`, killed before the attempt commits, then resumed: the step runs once and is never `in_doubt` | 2 / E5 |
| AC-3 | AC-1, then answer `{"outcome": "ran"}` (with and without `value`): the effect still shows once; the walk completes; downstream ran once; without `value`, a downstream `FromJob` on the step fails loudly | E2 |
| AC-4 | AC-1, then answer `{"outcome": "did_not_run"}`: the effect shows twice, by explicit choice; the step's record shows attempt 2; the walk completes | E3 |
| AC-5 | With no crash, each exit in B1 (return, raise, cancel, `BLOCKED` ending, routed failure, fingerprint skip) leaves no `attempting` record, and the recovery gate is never opened | 2 / E6 |
| AC-6 | A scope abandoned with `attempting` at its position, then reclaimed and resumed: the step is `in_doubt`, never `timed_out`, and the job does not run | E7 |
| AC-7 | `effecting=False`, the same kill: the step re-runs as today; no attempt record is written; a scope with no effecting step is byte-identical in the store to today; that workflow's graph digest equals today's | 4 / E4, E10 |
| AC-8 | The recovery gate is resolvable by name through status, `answer`, `--wf-resume --wf-input`, and the MCP gate tools; an answer outside the schema is refused and the gate stays open | D2 = 2a′ |
| AC-9 | At the recovery gate: Ctrl+C and no-TTY leave it pending; a configured value for its field does not answer it; no AI or decision strategy is attempted; there is no timeout | E8 |
| AC-10 | A graph with one effecting step digests differently from today's, and the difference is exactly the effecting flag and the recovery gate. A scope parked under the old digest refuses to resume with the existing graph-changed error | E10 |
| AC-11 | Declaring a node named `<effecting step>-in-doubt` fails at declaration time | B7 |
| AC-12 | `effecting=True` on a step whose job is a workflow fails boot validation with `WorkflowDeclarationError` | E9 / Risk 8 |
| AC-13 | In a `Loop`, a doubt on pass 2 is not resolved by an answer recorded for pass 1; and after `did_not_run`, a second crash in attempt 2 stops in doubt again instead of replaying the first answer, on both storage backends | B5 *[S-R4]* |
| AC-14 | A kill while one of the step's `Deps` runs, and a kill inside an `inv()` child, each leave the step `in_doubt` | E9 |
| AC-15 | `rg -n "exactly once\|exactly-once\|at-most-once\|at most once"` over `_types/workflow.py`, `_engine/frontier.py` and `docs/guides/workflows.md` returns only lines that carry the approved qualified wording | 6 |
| AC-16 | A watcher subscribed to the walk's events sees the in-doubt stop: `step.end` with the blocked outcome for the step, and the stop's `blocked_on` is the recovery gate | B2 |

## Out of scope

- A reconciler that asks the provider (D3, follow-up). This feature only records
  the attempt key that a reconciler will need.
- An in-step "effect committed" marker (D4).
- Treating a raise as doubt (D5).
- Per-request notification. Owned by FUN-21; see below.
- `AgentStep`, which has no flag. The flag is also absent from `inv()`, standalone
  runs and `Deps`, none of which is ever resumed.
- Idempotency keys supplied by users, distributed claiming, and the outbox's own
  semantics.

## Known limitation (recorded, not fixed here)

An in-doubt stop may notify nobody. `Notify(on="blocked")` is keyed per declaration
and scope, and `_notify` skips a key the scope has already sent
(`_engine/workflow_walker.py:916-919`). In the guide's refund example,
`approve_refund` blocks first, so a later doubt on `refund` pages no one. FUN-21
(Northstar M-1 (a)) closes this. Until then the stop is visible through status and
`blocked_reason`.

## Questions for confirmation (answered 2026-10-17: both as recommended)

- **Q-1 — the recovery gate's name: `<step>-in-doubt`.** The shape's example was
  `refund.in_doubt`. A `.` is the group separator, so that name would read as a job
  in a group, and a bare answer would be ambiguous once two steps are effecting
  (`research.md` R2). Recommended: `refund-in-doubt`. This refines the shape's
  illustration, not its decision.
- **Q-2 — the answer's field names: `outcome` (`"ran"` / `"did_not_run"`) and an
  optional `value`.** These are as drafted in the shape and restated here because
  they become a public answer schema.

## Ordering

Implementation begins after the in-flight lease-heartbeat change lands. It edits
`_engine/frontier.py` and `_engine/workflow_walker.py`, the two files this feature
changes (shape, Risk 5). The specification does not wait for it.
