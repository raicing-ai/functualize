# ADR-025: The Engine Owns What a Transition Means; Storage Owns Whether It Is Durable

**Status**: accepted
**Date**: 2026-09-23
**Deciders**: maintainer, during `runtime-persistence-ports` (FUN-17)

## Context

The runtime writes four kinds of record — runs, workflow scopes, job state and
events — and it is about to gain a second storage implementation. Before that
happens the project has to answer a question it has never answered explicitly:
**when a workflow step completes, who decides that it completed?**

Today the answer is "both, in different places, and nobody wrote it down". That
is survivable with one backend on one filesystem. With two implementations it
stops being survivable, because the two halves drift and there is no rule that
says which one is wrong.

### The question is not hypothetical — it has a wrong answer that looks right

The obvious shape for a persistence layer is a module that knows the state
machine: given a scope in state *running* and a step that finished, write the
step record, advance the frontier, and if that was the last step mark the
workflow *complete*. Call it `transitions.py`, put it next to the store, and
every backend inherits correct behaviour.

It is a genuinely attractive design and it was proposed for this work. It is
also the point at which the system acquires two owners for one fact.

The engine already decides what a transition means, and it decides it with
information a store does not have and should not be given:

- `_engine/workflow_walker.py` owns replay — whether a step is re-executed or
  its memoised result is reused.
- `_engine/frontier.py` owns which node is reachable next, including pinned
  branches and gate outcomes.
- `_engine/workflow_validation.py` owns `graph_digest()` (`:211`), the fence
  that refuses a resume when the workflow graph itself has changed under a
  suspended run.

A store that also decided "this step is complete" would need all three. The
`transitions.py` shape ends by pulling the walker into the storage layer, or by
duplicating it there.

### The failure has a precedent in this repository

[ADR-022](022-storage-is-a-substrate-not-a-key-value-domain.md) retired
`StateBackend`/`ExecutionStore` after a plugin-swappable scope store produced a
split brain: a resumed run could find its *steps* on one substrate and its
*variables* on another, because two seams at two levels each owned part of one
answer. The rule that ADR ended on — one seam, not two — is the same rule here,
one level up. Two owners for *what a transition means* is the same defect as two
owners for *where a record lives*.

### Storage genuinely does own something

This is not "the engine owns everything". Whether a write survives a crash,
whether two writes land atomically, whether a stale writer is fenced out — those
are properties of the backend, they differ between backends, and no amount of
engine logic can supply one a backend does not have. A filesystem substrate
cannot commit two documents as one unit. A SQL store can. That difference is
real, it is not the engine's business to paper over, and
[ADR-026](026-persistence-ports-need-no-new-layer.md) records how it is
declared.

## Decision

**The engine owns what a transition means. Storage owns whether it is durable.**

### The line, stated so it can be checked

A store implementation must never need to know *why* a transition is legal. The
operational test, and it is deliberately blunt:

> **A store implementation must not contain the word `resume` in a conditional.**

If it needs to branch on whether this is a resume, a retry, a replay or a fresh
walk, the logic is in the wrong module. Reviewers are expected to apply this
literally; it is cheap to check and it catches the drift early, when it is one
`if`.

### What that makes each side responsible for

| Concern | Owner |
|---|---|
| The lifecycle and its ordering | `_engine/executor.py` |
| Which transition happens next | `_engine/frontier.py`, `_engine/workflow_walker.py` |
| Whether a resume is legal at all | `_engine/workflow_validation.py` |
| Turning a lifecycle moment into a command | `_engine/recording/` |
| Whether a command commits atomically | the store implementation |
| Whether a stale writer is refused | the store implementation |
| What the store can promise | the store's declared capability record |

### The engine speaks to storage in commands, not in rows

The engine hands the store **values describing an intent** — `CompleteStep`,
`ClaimWorkflow`, `StartAttempt` — rather than calling methods that perform
updates. A command is a value: it can be put in a list, buffered, replayed in a
test, and applied by a backend that has no interactive transaction at all.

This is what keeps the line enforceable rather than aspirational. A store
receiving `CompleteStep` cannot second-guess it without inventing the walker; a
store receiving `update_scope(status="complete")` has already been handed the
decision.

### Recorders are thin, and that is the point

`_engine/recording/` translates a lifecycle moment into a command and does
nothing else — no decisions of its own. If a recorder acquires a branch, the
decision it is making belongs either in the walker above it or in the store
below it, and the branch is the signal that it landed in neither.

## Consequences

### Positive

- **One owner per fact.** "This step completed" is decided in exactly one place,
  and a second storage backend inherits that decision instead of re-deriving it.
- **Backends stay cheap to write.** A new store implements commands and reads.
  It does not implement the workflow state machine, which is the part that is
  hard and the part that is already tested.
- **Incapability becomes sayable rather than silent.** Separating the two
  ownerships is what allows a store to declare it cannot commit two aggregates
  together, instead of quietly applying half.
- **The rule is testable.** The `resume`-in-a-conditional test is a grep, not a
  judgement call.

### Negative

- **A backend cannot optimise a transition end-to-end.** A SQL store that could
  collapse "complete this step and advance the frontier" into one clever
  statement is not allowed to, because advancing the frontier is not its
  decision. Accepted: the optimisation is small and the coupling is permanent.
- **Commands are a layer of indirection** between the engine and the write. A
  reader tracing "what actually hits the disk" passes through one more hop.

### Neutral

- The engine keeps its current responsibilities exactly. This ADR records a
  boundary that was already implicit in where the code lives; it does not move
  the walker, the frontier or the validator.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| A `transitions.py` beside the store that owns the state machine | Every backend inherits correct behaviour; one obvious home | Needs the walker, the frontier and the graph fence; ends by importing the engine into storage | Two owners for one fact — the ADR-022 defect one level up |
| Let each backend own its own transition semantics | Backends can optimise freely | Guarantees divergence between implementations; no reviewable rule | The drift this ADR exists to prevent |
| Keep it implicit, as today | No work | Survivable with one backend, not with two; nothing to point at in review | The second backend is the reason this is being written |
| Engine calls typed update methods rather than passing commands | Fewer types; reads more directly | A method that performs an update has already received the decision; not implementable where there is no interactive transaction | Fails both the ownership test and the portability one |

## What would reopen this

A transition whose *legality* genuinely depends on storage state that the engine
cannot see — for example a database-enforced retention policy that has already
discarded the step a resume wants to replay. The answer then is still not to
move the state machine into the store: it is to make that storage fact readable
by the engine, through a reader named for the question, so the decision stays in
one place and only the *input* to it crosses the boundary.
