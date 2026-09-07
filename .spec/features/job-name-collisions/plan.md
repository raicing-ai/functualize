# Plan

## Approach

**Corrected during execution.** The plan first named `register_descriptors`
(`_app/boot.py`) as the one place both boot paths meet, following STATUS #32's
note. Probing the default path showed that function never sees a collision:

```
DirectoryScanProvider.list_jobs()        -> [('build-wheel','buildWheel'), ('build-wheel','build_wheel')]
CachedDirectoryScanProvider.list_jobs()  -> [('build-wheel','build_wheel')]          <- collapsed here
app.job_registry._registered_jobs         -> ['build-wheel']
```

The cached provider — which is what every `func` invocation boots — collapses
the pair first, in `_add_entry`:

```python
key = f"{descriptor.source_file}::{descriptor.name}"   # identical for both claimants of shape A
self._entries[key] = descriptor
self._by_name[descriptor.name] = descriptor            # collapses shape B too
```

So the choke point is the cached provider's **name index**, and the fix has to
survive a warm boot, where no module is imported and the loser was never
persisted.

### The change

1. **Key retained entries by Python name, not job name.**
   `f"{source_file}::{python_name or name}"`. Both claimants of shape A are then
   retained and persisted; shape B already retains both (different files). This
   is what makes a collision re-detectable on a warm boot with no new cache
   section and no record to keep in sync — the *evidence* is cached, and the
   *finding* is derived from it every boot.
2. **One `_reindex_by_name()` builds the name index from retained entries**, and
   is the only writer of it. Last claimant wins (today's outcome); every
   displaced claimant is recorded as a `DiscoveryFailure` through the collector
   the provider already opens around its scan, so it reaches
   `builtin info --json` with no new plumbing. Called after scan, after cache
   load, and after refresh — a single writer removes the "which mutation forgot
   the index" bug class that produced this defect.
3. **`CACHE_VERSION` 19 → 20.** The persisted key formula changes. `from_dict`
   reads fields by name, so an unbumped cache would not raise — it would
   silently key old entries the old way and under-report, which is worse.
4. **Eager path (`_discovery/registry.py`) drops its `ValueError`** and records
   through the same builder. This is what unblocks `eager-boot-provider`: the
   diagnostic no longer lives only on the path that feature deletes.
5. **`register_descriptors` keeps a last-line guard** for descriptors that
   arrive already collided from a provider the cache does not front —
   `StaticProvider`, a plugin's own provider. Same rule, same record.

## Files

| File | Change |
|---|---|
| `src/functualize/_types/discovery_report.py` | the collision record builder; a way to record a prebuilt finding |
| `src/functualize/_discovery/cached_provider.py` | entry key by Python name; `_reindex_by_name()` as sole index writer |
| `src/functualize/_primitives/cache_format.py` | `CACHE_VERSION` 19 → 20 |
| `src/functualize/_discovery/registry.py` | drop the `ValueError`; record instead |
| `src/functualize/_app/boot.py` | `register_descriptors` guard for uncached providers |
| `tests/discovery/test_discovery_failures.py` | the record; the collision report, cold and warm |
| `tests/discovery/test_job_name_collisions.py` | new — both shapes, both paths, winner identity |

## Risks

**The winner must not move.** A2/A4 assert the *specific* surviving function,
not the count, because "report and skip" reads like first-wins and implementing
it that way would change which function runs for any project that already
collides.

**Warm boot is the real gate.** The first design would have reported cold and
gone silent warm — the intermittent shape this project treats as worse than the
original defect (`contributor/reference/pitfalls.md`; four of its eighteen
defects were visible only on the warm-cache path). A6 is the criterion that
catches it, and step 1 above is the reason it can pass.

**Cache key collisions in the other direction.** Keying by Python name means
two *different* job names from one file that share a Python name cannot occur
(one attribute, one name), so the new key is at least as unique as the old for
retention purposes. The reverse — one Python name, two job names via
`@job(name=...)` overrides — is not possible either: `@job(name=)` is gone
(`_discovery/providers.py` comment), only `group` overrides identity.

**Layer rules.** `_cli` reads the report by attribute access through the
provider, exactly as it does today; no new import edges. `lint-imports` gates
every task here.
