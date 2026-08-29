# ADR-010: Fingerprint the Discovery Config Into the Cache Header

**Status**: accepted — the `base_dir` non-goal is **superseded by ADR-011**
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
Such a provider skips the check. Without the skip, `func builtin cache show`
would fail the check against any cache written under an active filter and
**delete it** — an inspection command destroying what it inspects.

The first implementation also had such a provider *adopt* the loaded fingerprint,
so that a later persist could not downgrade a good value to absent. That branch
was removed as unreachable: the only bare provider that persists is
`cache rebuild`, and it unlinks the cache file *before* building the provider, so
there is never anything to adopt. Deleting it left the full suite byte-identical
— 8820 passed, 9 skipped, either way.

`CACHE_VERSION` goes 15 → 16. Not cosmetic: anyone who ran `--exclude` on 0.1.0
has a poisoned cache on disk, and only the version check reaches it, because a
0.1.0 cache carries no `discovery_hash` to compare against. Both the provider and
the pre-boot fast-path readers compare `version`, so the repair lands on the
first 0.1.1 invocation whichever surface runs first.

**`base_dir` was left out of the fingerprint — and the reasoning was wrong.**
As first recorded: `GlobExcludePreFilter` matches relative to it, boot derives it
from `jobs_directories[0]` while the builtins path has no equivalent, including it
would thrash two providers over one cache file, and the residual exposure — a
project changing `jobs_directories` — "changes the scan set and is already
reconciled by the sync algorithm".

Both halves of that last clause were refuted by measurement during review.
Reordering `jobs_directories` does **not** change the scan set: every listed
directory is scanned either way. What changes is `base_dir` — and
`GlobExcludePreFilter` admits any file *not* under it, so one `exclude_patterns`
entry governs the first root and silently not the rest. Cold runs over `["a","b"]`
and `["b","a"]` produce mirror-image correct contents under an **identical
digest**, so the warm transition serves the stale one. That is X3 exactly, one
setting over, and nothing reconciles it.

**Superseded by ADR-011**, which fixes the filter instead of the fingerprint:
matching becomes relative to whichever scan root contains the file — what
`docs/cli/discovery.md` already documented — which removes `base_dir` as an input
and leaves nothing to fingerprint.

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
- `func builtin cache rebuild` still rebuilds unfiltered, and — **worse than
  first recorded here** — writes no fingerprint at all, because it unlinks the
  cache file before building the provider, leaving nothing to carry one. The next
  command therefore invalidates and rescans, with a WARNING on stderr, in every
  project including one with no filters configured. The cost is not the wrong
  entry count first recorded; the rebuild is simply discarded. New at this change:
  at `c1b6c26` the same sequence reused the cache silently. Fixed in ADR-011.

### Neutral

- Child-project providers (`_app/boot.py`) receive no discovery config and so
  skip the check. **This is not neutral, as first recorded.** Because
  `find_functualize_dir` searches *upward*, a child under a parent that has
  `.functualize/` resolves to the **parent's** cache file and writes last. The
  parent's provider then finds `discovery_hash: null` and invalidates on **every**
  boot, forever, with a WARNING on stderr. The warning is new at this change; the
  underlying fault is not — at `c1b6c26` the same file already alternated between
  parent and child entries, each boot destroying the other's, silently. Fixed in
  ADR-011.

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
