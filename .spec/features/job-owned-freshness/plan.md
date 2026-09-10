# Plan — job-owned-freshness

---

## 1. The approach in one line

**Copy ADR-012's `Sources` binding exactly, for the verdict instead of the source map, and add
one declaration field that moves the skip decision from the engine to the job that asked for
it.**

## 2. Why this is small

Everything hard is already solved. The verdict object exists (`PreflightDecision.verdict`),
the binding shape exists (`Sources._bind`), the ordering hazard is documented
(`sources.py:13-20`), the injection mechanism is declarative (ADR-014's `CapabilitySpec`), and
the two-path sabotage discipline is already the house rule for exactly this hazard.

What is genuinely new is one `if` in the engine and one field on `Fingerprint`.

## 3. Files to change

### New

```
src/functualize/_engine/capabilities/freshness.py
tests/execution/test_freshness_capability.py
tests/execution/test_fingerprint_decides.py
examples/standalone/freshness_lab/jobs/self_caching_job.py   # AC-8, runs in pytest examples/
```

### Modified

```
src/functualize/_engine/executor.py               the skip becomes conditional on `decides`
src/functualize/_types/job_declaration.py         Fingerprint.decides
src/functualize/job/__init__.py                   public re-export
src/functualize/_primitives/di.py                 INJECTED_PARAM_TYPE_NAMES (ADR-014 invariant)
docs/guides/…                                     the worked example
```

The engine change is one line's worth of logic, in the same block that already handles
`force_fresh`:

```python
# executor.py, beside the existing force_fresh / force overrides at :1022-1025
if _state is GuardState.SKIP_FRESH and declaration_decides_its_own_freshness:
    preflight_decision = None      # the body runs; Freshness carries the verdict
```

Placing it **there** rather than at `:1026` is deliberate: `force_fresh` already means
"override SKIP_FRESH and run", and `decides` is the same override with a different trigger.
One block, one rule, one place to read them together.

## 4. Risks

- **R-a · The capability resolves and does nothing.** The named hazard from
  `wiring-discipline.md`, and the exact reason `Sources` carries a two-path sabotage.
  *Mitigation:* AC-7 — break the binding and confirm a test fails on **both** the cold and
  warm path. A single-path sabotage is what let this class of bug ship before.

- **R-b · `decides` silently changes behaviour for existing jobs.** It defaults to `False`,
  so it cannot — but a mis-wired condition could invert it. *Mitigation:* a test asserts the
  default path is byte-identical, including the history entry and exit code (AC-3), and it is
  written *before* the engine change.

- **R-c · The vocabulary drifts from `func builtin why`.** A user reading `why` and a job
  reading `Freshness` must agree about the same run. *Mitigation:* both consume `GuardState`;
  a test asserts `why`'s rendered verdict and the job's `verdict().state` describe the same
  run identically.

- **R-d · `decides` reads as "skip me" to a job author.** It is the opposite. *Mitigation:*
  the name says what the job does, the docstring leads with the worked example, and the
  example ships in `examples/`.

- **R-e · This looks like the first step toward a framework cache.** It is the decision *not*
  to build one (`11-boundaries.md` **N1**). *Mitigation:* the spec says so, the guide says so,
  and the example caches into a job-chosen location the framework never reads.

## 5. Ordering

```
W0  Freshness capability + CapabilitySpec + DI name    (injected, always None — inert)
W1  the binding: populated after the pre-flight        (verdict readable; no behaviour change)
W2  Fingerprint.decides + the engine override          (the one behaviour change)
W3  docs and the worked example
W4  checkpoint
```

W0 lands a capability that always reports `None` — deliberately inert, so the injection is
proven wired before it carries meaning. W1 gives it a value. Only W2 changes what a job does.

## 6. What this plan does not do

It does not store anything, read anything back, or add a cache. The example writes to a path
the job chose and the framework never looks at it — which is the entire point.
