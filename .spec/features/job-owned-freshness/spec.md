# Feature — job-owned-freshness

Implements **F9** of `contributor/architecture/run-model/13-roadmap.md`: hand a job the
freshness verdict its own declaration produced, and let a job that wants to act on it do so.

**Depends on:** nothing. **Blocks:** nothing.

This feature exists because of a boundary this document set draws deliberately
(`11-boundaries.md` §B): **storing an artifact is the job's business — the framework owes the
job its verdict, not its storage.** That boundary is only free if the verdict actually reaches
the job. It does not.

---

## 1. The problem

### 1.1 The framework decides, and the body never runs

`_engine/executor.py:1026`:

```python
if preflight_decision is not None and not preflight_decision.should_run:
    return self._preflight_result(job_name, context, preflight_decision, start_time)
```

When the pre-flight says a job is fresh, the engine **returns before the body**. So a job
cannot express:

> *"I am fresh — return my cached artifact instead of rebuilding it."*

The engine has already decided, and the body is never entered. A job author who wants to own
their own caching has no seam to own it from.

### 1.2 The verdict already exists, one layer away

`PreflightDecision` (`_engine/preflight.py:57-64`) carries exactly what is needed:

```python
__slots__ = (
    "declared_generates",
    "declared_sources",
    "key",
    "recorded_value",
    "source_map",
    "verdict",
)
```

`verdict` is a `GuardVerdict` with a `GuardState` — `SKIP_FRESH`, `SKIP_SATISFIED`, and the
rest. The object is constructed, consulted, and then either used to return early or discarded.

Nothing on `RunContext` exposes it: `rg -c 'freshness|verdict|is_fresh'` over
`_engine/capabilities/runcontext.py` returns **0**.

### 1.3 This exact shape has an ADR, and it was solved once already

`_engine/capabilities/sources.py`:

> *"A job declares the files it depends on, the pre-flight expands that glob and records
> `{path: {mtime, size, sha256}}` for each match on **every run**, uses it to decide freshness
> — and then threw it away. The body, about to read exactly those files, had no way to reach
> it, so every job restated the glob its own declaration had just run. Two statements of one
> intent, free to drift."*

ADR-012's fix was **not** a file-reading service. It was to stop discarding what the pre-flight
already had: `PreflightDecision` *"now carries what it used to discard"*, bound to the body by
`Sources._bind` once the decision is in hand.

The same sentence, with "freshness verdict" in place of "resolved sources", describes this
feature.

### 1.4 The ordering that makes it delicate, and it is already documented

Also from `sources.py`:

> *"DI resolution runs **before** the pre-flight, so at injection time the data does not
> exist. The instance is therefore injected empty and populated by `Sources._bind` once the
> decision is in hand, before the body is called. That is exactly the shape
> `wiring-discipline.md` warns about — a capability that resolves and does nothing — which is
> why the binding carries a sabotage check on both the cold and warm paths rather than a unit
> test alone."*

`CapabilitySpec(name="Sources", …, factory=lambda ctx: Sources())` with a comment saying the
factory is *"deliberately empty"* (`sources.py:160-166`). This feature copies that shape
exactly, including the sabotage discipline.

---

## 2. User stories

- **US-1** As a job author whose job produces a Docker image, I check my own freshness verdict
  and return the existing tag instead of rebuilding — because only I know that a rebuild is
  wasteful but a re-tag is not.
- **US-2** As a job author, I can see *why* I was considered fresh — which declared sources
  matched, and what the recorded key was — without restating my own `Fingerprint`.
- **US-3** As a job author who does nothing, nothing changes: my job is still skipped when it
  is fresh, exactly as today.

---

## 3. Behaviour

### 3.1 The verdict reaches the body

A capability exposes the pre-flight's verdict to a running job: the state, the key it was
computed under, the recorded value, and the declared sources and generates that produced it.
Bound after the pre-flight and before the body, `Sources`-shaped.

### 3.2 A job may declare that it decides

> The default is unchanged: **the engine skips a fresh job.** A job opts out by declaring it
> handles its own freshness, and only then is its body entered when the verdict says fresh.

This is the feature's only declaration-surface change and its only real design decision. The
declaration is on `Fingerprint`, beside the `sources`, `generates` and `method` that produce
the verdict — not on `@job`, because it is a property of *how this job's freshness works*, not
of the job as a whole.

### 3.3 An opted-in job still gets a skip result if it wants one

A job that opts in and then decides it really is fresh returns whatever it likes; the run is
recorded as it would be for any other body. It does **not** get a way to fabricate
`RunStatus.SKIPPED` — the distinction between *"the framework skipped me"* and *"I ran and
decided to do nothing"* stays honest in history.

### 3.4 What must not change

- The default. A job with no new declaration behaves exactly as today, including the exit
  code and history entry for a skipped run.
- `force` and `force_fresh` semantics (`executor.py:1000-1025`) — `force_fresh` overrides only
  `SKIP_FRESH`, `force` also overrides `SKIP_SATISFIED`, neither overrides a failing
  `Precondition` or a gate.
- The lifecycle's 20-step order.
- `Sources`, which stays exactly as it is — this feature sits beside it, not on top of it.

---

## 4. Acceptance criteria

- **AC-1** A running job can read its own freshness verdict: the `GuardState`, the key, the
  recorded value, and the declared sources and generates.
- **AC-2** The verdict is bound **after** the pre-flight and **before** the body, and is
  populated on both the cold and the warm path.
- **AC-3** A job that does not opt in is still skipped when fresh — same result, same exit
  code, same history entry as today.
- **AC-4** A job that opts in **has its body entered** when the verdict says `SKIP_FRESH`, and
  can read that verdict.
- **AC-5** Opting in does not bypass a failing `Precondition` or a blocking gate. It affects
  `SKIP_FRESH` only, exactly as `force_fresh` does.
- **AC-6** The verdict a job reads is the same object the engine decided with — not
  recomputed. Proven by a test that changes the decision and observes the job's reading change.
- **AC-7** Sabotage: breaking the binding fails a test on **both** the cold and warm paths,
  not only one (the `Sources` discipline).
- **AC-8** The declaration is documented with a worked example of a job caching its own
  artifact, and the example runs in `pytest examples/`.

---

## 5. Out of scope, deliberately

- **A framework artifact store, content addressing, cache eviction, or a remote cache.**
  `11-boundaries.md` **N1** — this is the boundary this feature exists to make usable, not to
  erode. If a job author demonstrates the verdict is *insufficient* rather than merely less
  convenient than a built-in cache, that reopens N1; this feature does not.
- Changing what makes a job fresh. `Fingerprint`'s `method`, globs and ADR-013 path rules are
  untouched.
- Exposing the verdict to anything other than the running job.

## 6. Prior art

- **ADR-012 / `Sources`** — the same move, one release earlier, with the ordering hazard and
  the sabotage discipline already worked out. This feature is its second application.
- **`_engine/explain.py`** — `func builtin why` already renders a verdict for a human. The
  vocabulary a job reads must match what `why` prints, or a user and their job will disagree
  about the same run.
- **`wiring-discipline.md`** — *a capability that resolves and does nothing* is the named
  hazard here, and the reason AC-7 requires a two-path sabotage.
