# ADR-010: Fingerprint the Discovery Config Into the Cache Header

**Status**: accepted
**Date**: 2026-08-29
**Deciders**: Hakim

## Context

The discovery cache header fingerprinted four things — the format version, the
package version, the Python version, and the dependency hash — and not the fifth
that decides what the cache contains: the effective discovery configuration.

`exclude_patterns` and `--exclude` were therefore silently ignored against a warm
cache, in both directions. With a directory containing `alpha.py` (job `alpha`)
and `test_beta.py` (job `beta`), `func builtin cache clear` before each sequence:

| | Sequence | `func builtin info` listed | |
|---|---|---|---|
| X1 | cold cache → `--exclude 'test_*.py'` | `alpha` | correct |
| X2 | one plain run → `--exclude 'test_*.py'` | `alpha`, `beta` | exclusion ignored |
| X3 | plain run → add `[discovery] exclude_patterns` | `alpha`, `beta` | ignored until `cache clear` |
| X4 | `--exclude 'test_*.py'` once → then no flag | `alpha` | `beta` gone for good |

X4 is the one that matters. A single `--exclude` invocation removed a job from
the CLI permanently — no flag set, no config entry, no diagnostic. The job was
not shadowed or deprioritised; `func beta` answered `Unknown command 'beta'`.

The filter machinery was not at fault. `GlobExcludePreFilter.should_import`
(`_primitives/pre_filter.py`) fires correctly on a cold run, and
`func builtin config show` resolved the setting correctly. The defect was
entirely at the cache boundary, and it has two halves:

- `PreFilterDecision` persists **negative** pre-filter decisions by design — its
  own docstring says *"Only negative decisions (eligible=False) are persisted"* —
  with no record of which filter produced them. The next run replays
  `eligible: false` regardless of what the caller asked for. That is X4.
- A file already cached as a positive descriptor entry is returned without the
  pre-filter being consulted again. That is X3, and it is the likelier half to be
  hit, because it is the ordinary path: use the tool, then add a filter.

## Decision

Add a `discovery_hash` field to the cache header, beside `deps_hash`: a sha256
over the nine `DiscoveryConfig` filter settings. Treat a mismatch as a **full**
invalidation, on the same path a `CACHE_VERSION` mismatch already takes.

Three decisions inside that one:

**Whole-file invalidation, not per-entry.** `_load_cache`'s ladder bails out
before `entries`, `pre_filter_decisions`, `displays` and `group_options` are
deserialized, so one header field discards all four together. That is what makes
a single field sufficient: X3 needs `entries` gone and X4 needs
`pre_filter_decisions` gone, and the ladder does both. The alternative —
re-applying the pre-filter to cached entries on read — would need a per-entry
record of which filter produced each decision, and would still leave `get_job()`
wrong, since it never consults the pre-filter at all.

**`None` and `()` fingerprint differently.** To the filter factory, `None` means
"not configured" and an empty container means "configured empty" —
`require_job_decorators=()` even raises. Collapsing them would reintroduce this
bug one setting narrower.

**`None` on the provider means "does not know the config", not "no config".**
That is the state of the bare provider the `func builtin cache` commands build.
Such a provider skips the check and adopts the loaded fingerprint. Without this,
`func builtin cache show` would fail the check against any cache written under an
active filter and **delete it** — an inspection command destroying what it
inspects.

`CACHE_VERSION` goes 15 → 16. Not cosmetic: anyone who ran `--exclude` on 0.1.0
has a poisoned cache on disk, and only the version check reaches it, because a
0.1.0 cache carries no `discovery_hash` to compare against. Both the provider and
the pre-boot fast-path readers compare `version`, so the repair lands on the
first 0.1.1 invocation whichever surface runs first.

**`base_dir` is deliberately not in the fingerprint.** `GlobExcludePreFilter`
matches relative to it, and boot derives it from `jobs_directories[0]` while the
builtins path has no equivalent — including it would guarantee a mismatch between
two providers over one cache file, thrashing on every alternation. The residual
exposure is a project changing `jobs_directories`, which changes the scan set and
is already reconciled by the sync algorithm.

## Consequences

### Positive

- X2, X3 and X4 are closed, and covered by regression tests that run the
  *transitions* rather than the cold path. Every pre-existing filter test ran
  cold, which is why this survived to 0.1.0.
- Changing any discovery setting now rebuilds the cache automatically, so the
  documented `func builtin cache clear` workaround is no longer load-bearing.

### Negative

- One extra rebuild whenever the effective discovery config changes. This is the
  intended cost.
- `func builtin cache rebuild` still rebuilds unfiltered — it is unfiltered today
  and this change does not widen to fix it. Under the new semantics it writes no
  fingerprint and the next boot invalidates and rebuilds correctly, so it
  self-heals rather than poisons. Recorded as a follow-up.

### Neutral

- Child-project providers (`_app/boot.py`) still receive no discovery config and
  so skip the check. They have none plumbed today; unchanged by this decision.

## Notes

A wiring claim made while implementing this did not survive its own sabotage.
The pre-boot routing read (`read_routing_names_from_cache`) *looked* load-bearing
— routing resolves job names before the app boots, so a stale read should have
produced `Unknown command` — and the first implementation taught it the
fingerprint too. Removing that argument left every assertion green, including a
bare-listing pair added specifically to catch it: a routing miss falls through to
a path that boots anyway, and the provider's invalidation is reached on every
surface. The wiring was reverted rather than shipped, because it cost a
`resolve_cli_config()` call inside a read documented at a ~3ms budget and bought
behaviour no test could observe.

The lesson is the one `contributor/guides/wiring-discipline.md` already records:
a call path read off the source is a hypothesis. Only breaking it settles whether
it carries weight.
