# ADR-011: Complete the Discovery Fingerprint at Every Provider

**Status**: accepted
**Date**: 2026-08-29
**Deciders**: Hakim
**Supersedes**: the `base_dir` non-goal in
[ADR-010](010-discovery-cache-filter-awareness.md)

## Context

ADR-010 added `discovery_hash` to the cache header and closed X1–X4. An adversarial
review of the branch that shipped it confirmed that fix and found three defects it left
open or introduced. All three trace to one shape: **the digest is supplied at one of
four provider construction sites, and it omits one of the filter stack's inputs.**

### The fingerprint omits `base_dir` (F1)

`_app/boot.py` derives `base_dir` from `jobs_directories[0]` and hands it to
`GlobExcludePreFilter`, which relativizes each candidate against it and **admits
anything not under it**. So which files an `exclude_patterns` entry can even reject
depends on which scan root happens to be listed first — an input no fingerprinted field
records.

`a/keep_a.py`, `a/test_x.py`, `b/keep_b.py`, `b/test_y.py`, `exclude_patterns =
["test_*.py"]`, `jobs_directories` reordered between runs:

```
COLD ["a","b"]  discovery_hash: sha256:42f9df15dfd882167c1044fbfe3ca6c2589ed188…
                entries: ['keep_a.py::keep-a', 'keep_b.py::keep-b', 'test_y.py::yb']
COLD ["b","a"]  discovery_hash: sha256:42f9df15dfd882167c1044fbfe3ca6c2589ed188…
                entries: ['keep_a.py::keep-a', 'keep_b.py::keep-b', 'test_x.py::xa']
```

Same file, **identical digest**, mirror-image correct contents — so the warm transition
serves the stale one. X3 exactly, one setting over.

ADR-010 excluded `base_dir` on the reasoning that the residual exposure "changes the
scan set and is already reconciled by the sync algorithm". Both halves are false:
reordering does not change the scan set (every listed directory is scanned either way),
and nothing reconciles it.

### The behaviour being fingerprinted is itself undocumented (F9)

`docs/cli/discovery.md:114` — *"Patterns use `fnmatch` semantics against the file's path
relative to **the scanned directory**."* `discovery_lab/README.md:52` says the same.
Neither describes "relative to `jobs_directories[0]`, and unconditionally admitted
elsewhere". No document anywhere describes the shipped behaviour.

### `None` is safe to read past and ruinous to write (F2, F3)

`discovery_hash=None` means "this provider does not know the config", and such a
provider *skips* the check. That is correct for a reader. Two writers pass it anyway:

**`cache rebuild`** unlinks the cache file and *then* builds a bare provider, so there
is nothing to load and it persists `"discovery_hash": null`. The next command
invalidates and rescans — in a project with no filters at all:

```
$ func builtin cache rebuild
Cache rebuilt with 2 entries.
### next plain run, stderr:
WARNING …Cache invalidated: discovery config changed (cached=None, current='sha256:d7b0753…')
### control (two plain runs):     no invalidation
### base c1b6c26, same sequence:  no invalidation
```

**Child projects** are worse. `find_functualize_dir` searches *upward*, so a child under
a parent that has `.functualize/` resolves to the **parent's** cache file, and writes
last. Three consecutive boots:

```
HEAD                                      BASE (c1b6c26)
boot 1  discovery_hash: None              boot 1  discovery_hash: None
boot 2  Cache invalidated: … (cached=None) boot 2  (no warning)
boot 3  Cache invalidated: … (again)      boot 3  (no warning)
```

The warning is new. The fault is not: at base the same file already alternated between
parent and child entries, each boot destroying the other's, silently.
`build_cached_provider(project_root=child_path)` evidently *intends* the child to have
its own cache; the upward walk defeats that intent.

## Decision

### 1. `exclude_patterns` matches relative to the scan root that contains the file

`GlobExcludePreFilter` takes the scan roots, not one `base_dir`, and relativizes each
candidate against the **deepest** root that is an ancestor of it. A file under no root
is still admitted, unchanged.

This was chosen over the conservative alternative — adding `base_dir` to the digest —
for three reasons:

- It makes `docs/cli/discovery.md:114` and `discovery_lab/README.md:52` true, rather
  than making the cache a faithful record of behaviour no document describes.
- The shipped behaviour is not defensible as intent. In a two-root project one
  `exclude_patterns` entry governing the first root and silently not the second is a
  filtering bug in its own right, independent of caching.
- It **removes** `base_dir` as an input instead of widening the fingerprint, so the
  digest stays at the nine `DiscoveryConfig` fields and
  `test_fingerprint_covers_every_discovery_config_field` remains exactly the right
  guard.

The blast radius runs in the safe direction: root-relative matching only ever excludes
**more** files, never fewer. A user who wrote an exclusion and found it applied to one
of two job directories was not relying on that.

### 2. The `func builtin cache` provider is built from the resolved discovery config

`_build_provider_for_cwd` resolves the config with `resolve_cli_config()` — which
`_cli/builtins.py` already imports — and passes it to `build_discovery_cache_provider`,
which derives the pre-filter, job filter and digest exactly as boot does. `cache
rebuild` then rebuilds **filtered** and writes a correct fingerprint, so the next
command reuses it. This also closes ADR-010's open "rebuild is unfiltered" follow-up.

The `None` default and its skip semantics stay: no shipped path passes it any more, but
it remains correct for programmatic `build_cached_provider` use, and it is defended by
`test_cache_show_leaves_a_matching_cache_byte_identical`.

### 3. Child projects resolve their cache within the child

`build_cached_provider` gains `ancestor_search`. Child wiring passes `False`, so the
lookup considers only the child's own `.functualize/` before falling back to the
platform cache keyed by the child's project id — and passes
`discovery_hash_from_config(None)`, the honest digest for "no filters applied".

This fixes the new warning and the pre-existing clobbering together, and it restores
what `project_root=child_path` was always for.

Children still do **not** inherit the parent's filters. That is unchanged behaviour, not
a decision this ADR makes; whether they should is a separate question.

### 4. `CACHE_VERSION` 16 → 17

Decision 1 changes what a correct cache contains for any multi-root project with
`exclude_patterns`, and the digest cannot see that change — the nine fields did not
move. Only the version bump reaches caches already on disk.

## Consequences

### Positive

- The fingerprint's coverage is now auditable as "every input to the filter stack",
  because there is only one such input left that is not a `DiscoveryConfig` field, and
  decision 1 removes it.
- `cache rebuild` does useful work again, and does it under the user's filters.
- A monorepo parent's discovery cache survives a boot for the first time.
- Two published documents become true without being edited.

### Negative

- One forced rebuild for every existing project, from the `CACHE_VERSION` bump. This is
  the intended cost and it is silent.
- Multi-root projects with `exclude_patterns` will see the pattern apply to roots it
  previously skipped. This is the fix, but it is a behaviour change and is called out in
  the CHANGELOG.

### Neutral

- `GlobExcludePreFilter`'s single-root construction is unchanged and still tested; the
  new parameter defaults to empty, which is what keeps the existing unit tests honest
  rather than merely passing.

## Notes

The generalisable lesson is recorded in
[`contributor/reference/pitfalls.md`](../reference/pitfalls.md): a fingerprint is only
worth the number of construction sites that supply it, and an "unknown" sentinel that is
safe to read past is ruinous to write. ADR-010's repair for exactly this — have a
`None` provider *adopt* the loaded fingerprint — shipped unreachable, because the one
path that would have used it deletes the file before reading it. It was removed in
`84a6278` after a full-suite run proved its absence changed nothing.
