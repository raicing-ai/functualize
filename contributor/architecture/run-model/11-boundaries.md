# 11 · Boundaries — what belongs to the framework, the job, a plugin, and nobody

A design document is judged as much by what it refuses as by what it builds. Every refusal
below carries the reason, so that a later reader can tell a decision from an omission.

---

## A. The three-way split

| Concern | Owner | Why |
|---|---|---|
| What a run needs, what it did, what it means | **core** | These are the five authorities of [03 §E](03-the-run-model.md). A plugin cannot own them because every plugin needs them |
| How a run is reached, and how its outcome is rendered | **adapter / plugin** | Syntax and medium are genuinely per-surface. The family choice is one greppable word ([06 §D](06-outcome-authority.md)) |
| What a run *produces*, and where it goes | **the job** | §B |

The rule that survives from the pi-workflows set and is reaffirmed here:

> **Never gate workflow *behaviour* on an optional install.** Presentation may degrade;
> outcomes may not. (pi-workflow-parity decision **F2**.)

And its mechanism:

> **Name the package, never import it.** A `*_PROVIDERS` table plus a grep test, failing as a
> block with a diagnostic that names the missing distribution. (**F3**, **F4**.)

## B. Artifact storage is the job's business — and this is a decision, not a deferral

The entrypoint audit surveyed Dagger and recorded content-addressed artifact caching as the
highest-value gap it did not cover: *"functualize has freshness decisions but no artifact
cache."* It proposed pursuing it as its own shape intent.

**This set rejects it outright.**

Storing a result is domain knowledge the framework does not have and cannot acquire. The job
knows the format, the location, the retention, whether the artifact is a file or a row or a
pushed image, and whether last week's copy is still valid for reasons no fingerprint can see.
A framework-owned artifact store would have to model all of that, get it wrong for most jobs,
and become the second place a job's outputs live.

What the framework owes the job is the **verdict**, not the storage:

> The framework decides whether the declared inputs changed. The job decides what to do about
> it. Handing over the verdict is cheap and complete; owning the artifact is expensive and
> never complete.

That is a sharper boundary than "defer the cache", and it costs nothing to hold.

### What it cost, and what F9 did about it

The engine decides freshness and **returns before the body runs**
(`_engine/executor.py`):

```python
if preflight_decision is not None and not preflight_decision.should_run:
    return self._preflight_result(job_name, context, preflight_decision, start_time)
```

So "let the job decide whether to skip" was not expressible. The verdict already exists on
`PreflightDecision` (`_engine/preflight.py:49-64`, alongside `key`,
`recorded_value`, `source_map`, `declared_sources`, `declared_generates`) — it simply never
reached a body that had been skipped.

**ADR-012 is the precedent, and it is exact.** `Sources` solved the identical shape: the
pre-flight computed `{path: {mtime, size, sha256}}`, used it, *"and then threw it away. The
body, about to read exactly those files, had no way to reach it, so every job restated the
glob its own declaration had just run."* The fix was not a file service; it was to stop
discarding what the pre-flight already had.

Feature **F9** applied that precedent, and it has landed. `Freshness` reaches the body the
way `Sources` does — injected empty, bound with the decision after the pre-flight and before
the body — and `Fingerprint(decides=True)` makes the early return above conditional for a job
that declares it handles its own freshness. Nothing else moved: the return is unchanged for
every job that does not opt in, `decides` carries `force_fresh`'s scope (`SKIP_FRESH` only),
and the framework still owns no artifact — it knows a declared `generates` path exists and
never reads it. The worked example is
[`examples/standalone/freshness_lab/`](../../../examples/standalone/freshness_lab/), the
guide is `docs/guides/task-runner.md` § *Deciding your own freshness*, and the sabotage
discipline it inherited from `Sources` is in `contributor/guides/wiring-discipline.md`.

The refusal in this section is unchanged. Handing over the verdict is what makes "the job
owns its artifact" usable; it is not the first step toward a cache.

## C. Out of scope, with reasons

| # | Not doing | Because |
|---|---|---|
| **N1** | A framework artifact store / content-addressed cache | §B. The verdict is the contract; the storage is the job's |
| **N2** | Declarative `RunContext` capability exposure (audit D6) | ADR-014 derives *injection*; exposure is still 58 hand-written delegations. Deriving them is defensible, but each `rc.` method is a deliberate public-API decision, and automating that decision is a separate argument. F3 *shrinks* the facade ([05 §E.3](05-engine-seal.md)); it does not derive it |
| **N3** | The `app/utils.py` corridor | 2,068 LOC, 93 re-exports, growing at +18 per release ([02 §B.2](02-audit-corrections.md)). It is the next surface-boundary question and it is a large one. Its open wound — `read_group_options_from_cache` cannot honour the cache fingerprint (`utils.py:1589`) — is picked up in **F8** because it is small and bounded; the corridor itself is not |
| **N4** | Reducing the door count | [03 §G](03-the-run-model.md). The count must become irrelevant, not smaller. A tenth door should be cheap |
| **N5** | Changing `_execute_lifecycle`'s 20 steps | The order is a contract pinned by `tests/engine/test_lifecycle_order.py`. Every feature here keeps it green at every commit — that is the proof the moves were pure |
| **N6** | Compatibility shims for `engine.execute` | `.spec/CONSTITUTION.md` → Pre-Release Stance and *Forbidden Patterns*. A shim would preserve the exact door this work exists to close |
| **N7** | Collapsing the two CLI parsers into one | Pre-boot exists so `func` can route without importing job modules — a ~3 ms, zero-import budget ([12 §A](12-performance.md)). They share a **vocabulary**, not a syntax |
| **N8** | A message bus, or engine reads of notes | Carried from pi-workflow-parity **N1**/**N2**: *"That is A2A/AMQ. The moment `to` becomes load-bearing you own a broker."* |
| **N9** | A second nesting model | pi-workflow-parity **N4**. Child scopes are the one model |
| **N10** | pi-workflows' server-first architecture | pi-workflow-parity **N11**. It forfeits the < 5 ms `boot_static` and the in-process `Invoke` |
| **N11** | The `spec/subject-modeling` direction | A different strategic axis (subjects, a type system, routing). It is 8,125 lines of intent on its own branch and deserves its own decision, not absorption into this one |

## D. Two honest limits on the Open/Closed claim

This set claims the engine becomes closed for modification and open for extension. Two
qualifications, stated so the claim is not read wider than it is meant.

**1. Extension machinery was deliberately not added.** Mediator, Command, Strategy and new
registries were all rejected by the depth audit, and this set agrees: the defect is missing
*authorities*, not missing variation. The lifecycle already extends by declaration
(`CapabilitySpec.preflight_bind`, gate resolvers). Adding a registry to a design whose
complaint is "too many places" would be self-defeating.

**2. The fix is on the surface/entry axis only.** The DI-capability axis is healthy:
ADR-014's declared-beside `CapabilitySpec` plus an import-time name invariant already killed
the five-site capability chore. This design *generalizes that precedent* and leaves it
untouched. Its one residual is N2.

## E. What a later reader should re-open

Not everything above is settled forever. These are the ones worth revisiting, and the
condition under which:

| Refusal | Re-open when |
|---|---|
| **N3** `app/utils.py` | It crosses ~2,500 LOC, or a re-export is found that no `_cli` module uses — the orphan-scan shape |
| **N2** `RunContext` exposure | A capability ships whose `rc.` surface is forgotten and the omission reaches a user |
| **N1** artifact store | A job author demonstrates that F9's verdict is *insufficient* — not merely less convenient than a built-in cache |
| **N11** subject modeling | After F5. The durable run layer is the thing subject modeling would build on, and doing them in the other order repeats this document's own argument |
