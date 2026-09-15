# 03 · The run model — one request in, one record through, one outcome out

This document makes one claim, and it is a claim about **order**, not about scope:

> The entrypoint audit and the pi-workflows roadmap are not two projects that happen to
> touch the same files. The audit's entry consolidation is a **prerequisite** for the
> roadmap's durable run layer. Building item 8 first is possible, and it would cost nine
> instrumentation sites and produce a tenth authority.

Everything below is the argument for that sentence.

---

## A. A run has no identity

Follow one run through the codebase and ask, at each stage, *what object represents it?*

| Stage | What represents the run | Where |
|---|---|---|
| A door decides to run something | nothing — a name, a function, and 11 loose keyword arguments | the nine doors, [01 §A](01-current-state.md) |
| The engine executes it | `ExecutionContext` — real, but constructed *inside* `execute()` and never returned | `_engine/executor.py` |
| The run is in progress | **nothing durable.** A `@workflow` gets a `WorkflowScope` record; a plain job gets nothing until it ends | `_primitives/scope_store.py` |
| The run ends | `JobResult` | `_types/` |
| The run is remembered | a history entry — **only if `invoke_depth == 0`** | `executor.py:705` |
| The run is reported | nine translation sites decide independently | [02 §B.1](02-audit-corrections.md) |

Read down that column. The run is a **function call** for its whole life, and the codebase's
name for it changes four times. There is no object you can hold that means "this run".

That is the reason for both bodies of work, and it is why they are one body.

## B. Why the audit's fix and the roadmap's fix are the same fix

The audit proposes `RunRequest`: freeze everything a run *needs* into one frozen value
object, so the engine signature stops being the extension point.

The roadmap proposes a durable run layer: an event log, lifecycle verbs, leases, timeouts,
an effects outbox — i.e. a persistent, addressable record of everything a run *did*.

These are the two halves of one object.

```
RunRequest  ──►  engine.run()  ──►  RunRecord  ──►  outcome
  what the run needs            what the run did      how it reads
  (audit, C-I)                  (roadmap item 8)      (audit, C-III)
```

`RunRequest` is the run's identity **on the way in**. The run record is its identity **on
the way out**. A durable layer that cannot say what request produced a record is a log, not
a ledger — and the only place a request currently exists is spread across 11 parameters
assembled differently by nine callers.

## C. The concrete cost of the other order

Suppose item 8 is built first, against the code as it stands. The durable layer must, at
minimum: open a record when a run starts, emit `run.started`, and close it when the run ends.

**Where does that code go?**

The engine has one execution method, so `run.started` is easy — one site. But the record must
carry *what was requested*, and that is exactly what the engine does not receive as an object.
So the durable layer must either:

1. **Reconstruct the request inside the engine** from the 13 parameters — inventing, in the
   durable layer, the value object the audit says should exist. That is `RunRequest`, built
   in the wrong layer, by the wrong feature, with no obligation on any door to fill it. Two of
   the doors do not pass `group_option_values` at all ([07](07-surface-parity.md)), so the
   record would faithfully log that they were absent, which is true and useless.

2. **Instrument the doors** so each reports its own provenance. Nine sites. Each one an
   independent decision about what to report. This is the mechanism described in
   `audit-engine-encapsulation.md` §1 Cause 1, applied to a new feature: *every feature adds
   a parameter; every surface independently decides whether to pass it.*

There is a third cost, and it is the expensive one. **Item 8's lease needs to fence a run,
and a fencing token has to be checked somewhere every writer passes through.** Today there
are two writers into a walk's state — the walker, and `guarded_execute`'s resume path — and
nine ways to become one. A lease installed before the doors converge protects the door it
was installed behind.

## D. The evidence that this is not theoretical

Four things already happened, in this codebase, in this order.

**1. `--scope-id` was the same defect, one feature earlier.** The audit names it: gate-resume
could not reach a surface because resuming was a *parameter*, and each door decided
separately whether to pass it. The fix shipped in 0.3.0 by deleting the parameter and adding
a verb — but the mechanism that produced it was untouched.

**2. `guarded_execute` is a proto-`engine.run()`.** PR #35 made the CLI's `resume` verb
actually advance a walk, which created a second job-executing door. The response was to build
**one funnel** and route all three workflow surfaces through it, with a policy object deciding
what may pass (`app/_workflow_control.py:176`). That is this document's design, discovered
independently, scoped to one third of the problem. It shipped and it works.

**3. `wire_status()` is a proto-outcome-module.** Same release: MCP's execution doors
disagreed about how a status reaches the wire, so a single translator was written and all
four doors routed through it. Its docstring says *"Three doors disagreed."* Same move, same
release, different corner — and it produced a **ninth** global translation site because there
was no global one to join.

**4. The 0.3.0 release notes shipped a known unfenced race.** Two `resume` invocations against
one scope both walk it; the file lock serialises writes so nothing corrupts, but the second
overwrites the first's step records. It was shipped deliberately, with the fix named as
roadmap item 8's lease. **That is a durable-run-layer defect, created by making an entry
surface easier.** The two bodies of work were already entangled before either was designed.

Points 2 and 3 are the load-bearing ones. Twice in one release, faced with divergence, the
right local fix produced a new local authority — because the global one does not exist. The
codebase is not drifting through carelessness. It is drifting because **the correct action
and the drifting action are currently the same action.**

## E. What the model is

Five authorities, each with exactly one home.

| # | Authority | Home | Replaces |
|---|---|---|---|
| 1 | **What a run needs** | `RunRequest` — one frozen value object, `_types/run_request.py` | 13 parameters assembled by 9 doors |
| 2 | **Which function is this name** | `engine.run(request)` | 8 production resolution sites |
| 3 | **What a run is doing** | the run record + event log | nothing (does not exist) |
| 4 | **What a run's collaborators are** | `EngineHost`, wired once by `build_engine(host)` | 5 post-hoc private writes across 2 boot paths |
| 5 | **What an outcome means** | one outcome module in `_types/` | 9 translation sites |

And one deliberate non-authority: **what a run's artifacts are is the job's business**
([11 §B](11-boundaries.md)). The framework hands the job its freshness verdict; where and how
to store a result is domain knowledge the framework does not have.

## F. Why this is the third application of a move the codebase already trusts

ADR-001 collapsed five interactivity concepts into three. ADR-004 collapsed a namespace
re-derived in about seven places into one `GroupTrie`. Each time: find the single authority,
collapse the re-derivations, seal the boundary. Neither added a layer or a registry.

Both **partially regrew**, and the audit diagnoses why: they collapsed *rules* while leaving
the *protocol that demands per-surface re-derivation*. `execute(name, function, **knobs)`
still forced every door to resolve, assemble and thread, so every later feature re-entered
through the same door.

The test of this design is therefore not "did it collapse the rules" but **"is there still an
API by which a surface can diverge?"** After F1 there is no API that accepts a function.
After F2 there is no second failure-set. After F3 there is no writable engine attribute.
Divergence stops being a forgotten convention and becomes a failing test:

| Regrowth attempt | What fails |
|---|---|
| A new door resolves its own function | Nothing to resolve with — `execute(name, function, …)` is deleted |
| A new door restates the failure set | Panel≡table parity test |
| A new door re-spells a flag | `flag_grammar` round-trip test |
| An owner writes `engine._x = …` | Absence test, `test_typer_isolation.py` style |
| A facade grows past budget | LOC tripwire test |

## G. What this document is not claiming

- **Not** that the door *count* should shrink. It will keep growing; that is what surfaces
  do. The audits disagreed on the count (17 vs the documented 9) and the resolution is that
  the count must become **irrelevant**, not smaller. A tenth door should be cheap and boring.
- **Not** that the lifecycle changes. `_execute_lifecycle`'s 20 steps are a Template Method
  whose order is a contract, pinned by `tests/engine/test_lifecycle_order.py`. Every feature
  here keeps that test green at every commit; it is the proof the moves were pure.
- **Not** that this is one release. It is nine features across several
  ([13-roadmap.md](13-roadmap.md)).
- **Not** that a compatibility path is needed. Pre-release: `execute(name, function, …)` is
  deleted, not deprecated (`.spec/CONSTITUTION.md` → Pre-Release Stance, and *Forbidden
  Patterns* → no shims).
