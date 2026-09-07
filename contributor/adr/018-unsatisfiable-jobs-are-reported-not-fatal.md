# ADR-018: An unsatisfiable job is reported, not fatal to the app

**Status**: accepted
**Date**: 2026-09-07
**Deciders**: Hakim
**Amends**: `.spec/CONSTITUTION.md` § Boot & Config — "DI resolution failures
are loud and early: `MissingProviderError` / `AmbiguousProviderError` at boot
or first invocation, never silent `None`"

## Context

`validate_di_bindings` walked every registered job at boot, collected every
unsatisfiable parameter, and raised one `DIValidationError` for the app. That
satisfied "loud and early" and nothing else about it was examined, because a
job with an unregistered dependency is an authoring error and failing on it is
correct.

What was not examined is the *blast radius*. Measured on 0.2.3, one job with an
unresolvable parameter present in a project:

| command | result on a cold boot |
|---|---|
| `func fine` (an unrelated, healthy job) | `DIValidationError` traceback |
| `func builtin info` | `DIValidationError` traceback |
| `func strpath --to /tmp/x` (a `str` job) | `DIValidationError` traceback |
| `func --help` | ok |

Two things make that worse than it first looks.

**The diagnostic commands are the ones that die.** `builtin info` and
`builtin self doctor` exist to answer "what is wrong with this project". They
were the two commands the fault took down, so the tool's answer to its own
misconfiguration was a twelve-frame traceback ending in an exception class
name.

**It presented as intermittent.** A warm boot registers cached jobs as lazy
proxies, and validation skips proxies — so the same project worked on the
second invocation and failed after a cache clear, on a fresh clone, or in CI.
That is the shape this project treats as worse than the original defect
(`contributor/reference/pitfalls.md`: four of its eighteen shipped defects were
visible only on the warm-cache path).

The trigger for looking at all was narrower: everything not a builtin was
assumed to be a dependency, so `def backup(to: Path)` — a job taking a
directory — was unsatisfiable. That classification bug is fixed separately
(`_primitives/parameter_types.py`). But fixing it would have left the blast
radius intact for the *genuine* case, waiting for the next unregistered
provider.

## Decision

`validate_di_bindings` **returns** per-job errors instead of raising. Boot
records each affected job as a `DiscoveryFailure` with
`error_type="UnsatisfiableParameter"` and continues.

The loudness is kept and the contagion is removed:

- the reason is published in `discovery_failures`, the same list that answers
  "why is my job missing?" for a module that failed to import and for a
  job-name collision — one list, one question;
- a warning is logged at boot;
- every other job still runs, and `builtin info` and `builtin self doctor`
  still work;
- invoking the affected job fails with a message naming the job, the parameter
  and the two fixes.

**The job is left registered.** Unregistering it was implemented first and
reverted, for two reasons: it made the cold boot disagree with the warm one,
where validation is necessarily skipped for lazy proxies and the job still
exists; and "no such command" is a worse answer than a message naming the
parameter. So the guarantee that holds on *both* paths is that invoking the job
explains itself, and the boot-time report is the extra a cold boot can offer.

The error message also gained the parameter name. It was built inside
`DIRegistry.resolve`, which is handed a type and nothing else, so it read
`job: '<unknown>'` even though the validator walking the signature knew
exactly which parameter of which job had asked.

## Consequences

**The constitution's "at boot" is now "found at boot, reported at boot,
enforced at invocation".** Recorded here rather than left as a silent
divergence, because a later reader finding a non-raising boot gate needs the
reason without archaeology.

**Library-mode hosts that catch `DIValidationError` around
`FunctualizeApp(...)` no longer see it from the boot gate.** Pre-release, no
deprecation window; the failure is available as
`app._unsatisfiable_jobs` and through `builtin info --json`.
`_ensure_materialized` still raises for a lazy job at first use, because there
the caller has asked for *that* job.

**A job that cannot run is now listed by `builtin info`.** That is the accepted
cost of cold/warm agreement. It is listed *with* its reason, and
`discovery-failure-surfaces` prints that reason above the job list rather than
below it.

## Alternatives considered

**Keep raising, format the message better.** Rejected: it leaves `builtin info`
dead in exactly the situation it exists for. A well-formatted message that a
user cannot reach by any command is not an improvement.

**Unregister the job.** Implemented, then reverted — see above.

**Validate lazily for every job, so cold and warm agree by never validating at
boot.** Rejected: that would require importing every module on a warm boot,
which is the cost lazy boot exists to avoid, and it would move a
find-at-authoring-time error to first use.
