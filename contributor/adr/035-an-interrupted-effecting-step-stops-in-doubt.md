# ADR-035: An Interrupted Effecting Step Stops In Doubt

**Status**: accepted
**Date**: 2026-10-20
**Deciders**: maintainer, through the approved shape intent *Effecting Steps
Across a Crash* and the spec confirmations of 2026-10-17 and 2026-10-19
(decisions of record D1–D5).

## Context

`Step(effecting=True)` exists for the step whose job causes an effect that
must not blindly repeat — a card charge, a mail, a ticket. Its docstring
promised that such a step "must run exactly once across a crash and a
resume", but the flag was recorded and never read: a step had no record until
its job returned and `complete()` committed, so a process that died after the
effect and before that commit left no trace, and the resume ran the job
again. The card was charged twice.

No engine can fix this by observing the effect. Nothing sees an effect from
outside the store, and any write made after the effect can be lost in the
same crash that interrupts the step. The one fact the engine *can* record
durably, before the risk window opens, is that control was handed to the
job. The question is what a resume does with that fact when the ending never
arrived.

## Decision

An interrupted effecting step is never re-run without a decision, and it is
exactly-once once that decision is made.

- **The attempt is committed before the job runs.** Through the walk's scope
  transaction, the step is recorded `attempting` — the attempt number, the
  start time, `effecting: true` — before the job callback is entered. Every
  ordinary ending (return, raise, cancel, `BLOCKED`, a routed failure, a
  fingerprint skip) replaces the record exactly as today's records do; a
  `BLOCKED` ending is an ending, not doubt.
- **A found attempt stops the scope in doubt.** A walk that reaches a step
  whose current record is `attempting` (or `in_doubt`) never enters the job.
  It records `in_doubt`, stops the scope `blocked` on that step's derived
  recovery gate `<step>-in-doubt`, with a `blocked_reason` naming the step,
  the attempt and the start time, and runs nothing downstream. A `reclaim`
  of an abandoned scope leaves an `attempting` record untouched — it never
  writes `timed_out` over it.
- **The doubt is answered only by a person or a deposited answer.** The
  recovery gate is a declared node of the graph — addressable by every
  existing gate surface (status, `answer`, `--wf-resume --wf-input`, the
  answer-and-resume command, the API/MCP gate tools) — and is opened only
  when a walk finds the step in doubt. Its answer schema is
  `{"outcome": "ran" | "did_not_run"}` with an optional `value` and no
  default; the config chain, AI strategies, decision providers, defaults,
  cancelled prompts and timeouts are all barred from answering it.
- **The verdict is binding and per-doubt.** `ran` records the step `success`
  without calling the job; a supplied `value` is the step's result, and
  without one the result is marked not reusable so a downstream
  `FromJob`/`FromStep` fails loudly instead of inventing a value.
  `did_not_run` discards the attempt and runs the next one. An answer is
  keyed to its `(attempt, iteration)`; a later doubt — a different loop pass,
  or a second crash after `did_not_run` — asks again and never replays an
  earlier answer.
- **A raise stays the job's own account.** Failure routing is unchanged; an
  effecting job that raises after its effect happened must say so itself.

The delivery boundary this creates is deliberate: attempts are delivered
**at least once**, and execution becomes exactly-once only through the
recorded decision. The engine does not claim to detect effects.

Declaring `effecting=True` changes the workflow's shape and graph digest (the
flag plus the recovery gate), so a scope parked under the old digest is
refused on resume with the existing graph-changed error, once. Workflows with
no effecting step project and digest byte-for-byte as before. A step whose
job is itself a workflow is refused at boot validation, and a declared node
named `<step>-in-doubt` is refused at declaration time.

## Consequences

### Positive

- A crash inside an effecting step can no longer silently repeat the effect;
  the harmful case the flag was created for is closed.
- The decision is auditable: the record shows the step was in doubt, which
  attempt, when it started, and the verdict that settled it.
- No new answer surface: the doubt rides the existing gate machinery, so
  CLI, API/MCP and deposited answers all work unchanged.
- Pure steps and effect-free workflows are untouched, byte-for-byte.

### Negative

- **An in-doubt step blocks its scope until the gate is answered.** That is
  the point, and it has no timeout: a scope can wait for an operator
  indefinitely, and an unwatched one stays parked.
- Declaring the flag breaks resumption once for scopes parked under the old
  digest (accepted under the pre-release stance; the release note says so).
- The recovery gate adds one declared node per effecting step to every
  workflow that uses the flag.

### Neutral

- `Notify(on="blocked")` is keyed per declaration and scope, so an earlier
  blocked stop may swallow the notification for a later in-doubt stop in the
  same scope; the stop itself stays visible through `status` and
  `blocked_reason` (per-request notification is owned elsewhere).
- A future reconciler that asks the provider whether the effect happened has
  a reserved rung on the gate's ladder; this decision neither builds nor
  forecloses it.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|--------------|
| Re-run blindly on resume (the status quo) | No operator burden; simplest resume; correct for pure steps | Repeats the effect — the exact harm the flag names; the promise "exactly once across a crash and a resume" stays unwritten in behaviour | The flag exists to forbid this; a step that declares it must not be re-entered on the resume's own authority |
| Refuse to resume any scope holding an `attempting` record | Never re-runs; no new gate | No path forward — the scope is bricked with no way to say "it ran, continue"; the operator's knowledge is wasted | Doubt must be *answerable*, not terminal; the verdict (`ran`/`did_not_run`) is exactly the missing channel |
| Hold a process (or cluster-wide) lock around effecting steps | Shrinks the window inside one process; no schema change | Locks do not survive SIGKILL or machine loss; the doubt window is between two durable writes, not between two lock operations; no closer to observing the effect | The crash *is* the window; a lock cannot make the engine know whether the effect happened |
| An in-step "effect committed" marker written after the job | Would turn doubt into knowledge | The marker is a write after the effect, lost in the same crash; pushes the same unsolved problem into user code | Deferred by the shape (D4), not adopted; the recovery gate asks instead of pretending to know |
