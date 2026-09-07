# Plan

## Approach

One directory-scanning path in production instead of two that must agree
forever. The drift between them produced all four defects.

`resolve_and_register_jobs` (`_app/boot.py`) currently branches:

```python
if app._lazy_boot:
    _register_jobs_lazy(app)                                          # uses the provider
else:
    app.job_registry.scan_and_register_headless(app._jobs_directories)  # ignores it
    _sync_registry_to_engine(app)
```

The eager branch registers the descriptors the pipeline's directory provider
yields, exactly as the lazy branch does — the difference between the two
collapses to *which provider* is used, not *which code path*:

| | provider | descriptors carry |
|---|---|---|
| `lazy=True` | `CachedDirectoryScanProvider` | a live function cold, a proxy warm |
| `lazy=False` | `DirectoryScanProvider` (uncached) | always a live function |

Both then go through `register_descriptors`, which already takes the
live-function branch when `descriptor.function` is set — so boot-time DI
validation, the promise `lazy=False` exists for, is preserved without a special
case (`validate_di_bindings` skips only proxies).

That single change closes D1 (one provider consulted, so one import per
module), D3 and D4 (the provider carries the filters), and D2 comes with it
because `register_descriptors` writes `_registered_commands` by canonical name.

### The folded-in fix: resolve the scan roots

`boot_standard` builds the filters from `app._jobs_directories` as given:

```python
scan_roots = [Path(d) for d in app._jobs_directories]   # relative if the caller wrote them relative
```

`GlobExcludePreFilter` matches a candidate against whichever root contains it,
and a relative root contains no absolute path, so the exclusion silently never
fires. Resolving the roots there fixes both paths at once, and makes the cache
digest describe one directory rather than two spellings of it.

### The fallback

`_register_jobs_lazy`'s defensive branch (no cached provider was wired) keeps
its safety net and gains the filters, so if it ever fires the answer is right
rather than silently unfiltered.

## Files

| File | Change |
|---|---|
| `src/functualize/_app/boot.py` | eager branch registers provider descriptors; resolve scan roots; filter the fallback |
| `tests/app/test_eager_boot_provider.py` | new — import counts, key spelling, filter parity, DI validation still eager |
| `tests/discovery/test_relative_scan_roots.py` | new — A14–A16 |
| `tests/app/test_job_sources.py` | extend — the eager path's existing expectations |

## Risks

**The import-count assertion is the whole feature.** A1/A2/A4 use a
module-level side-effect counter rather than a job list, because a job list
cannot tell one import from two. A4 is the control: it fails if the fix works
by disabling the eager scan wholesale rather than by routing it.

**DI validation must stay eager.** A10 is a "must keep holding" criterion, not
a new one. If `register_descriptors` took the proxy branch for eager
descriptors, a DI error would move from boot to first use and the escape hatch
would lose the guarantee it exists for. The provider sets `function=attr`, so
it takes the live branch — asserted, not assumed.

**Excluded modules stop being imported.** Deliberate (A9), and the one
behavioural break. A host relying on a side effect in an excluded module would
notice.

**`scan_and_register_headless` keeps a caller.** A11 counts the call sites and
expects the eager branch gone but the fallback present, so "delete the function"
is not silently substituted for "stop using it on the boot path".

**Feature 1 removed the objection to this work.** Routing eager through the
provider used to delete the only place a normalization collision was caught.
It is now caught by the name index and the pipeline, on every path.
