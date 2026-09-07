# Spec: The eager boot path uses the provider it builds

**Promoted from `.spec/shape-intents/eager-boot-uses-the-provider-it-builds.md`,
which stays as the authoring record.** Closes `.spec/STATUS.md` #30 and the
three defects found while auditing it. Depends on `job-name-collisions`, which
has landed: the collision diagnostic no longer lives only on the branch this
feature deletes, which is what unblocked it.

Every number below was measured against `6699af6` at authoring time and
**re-measured against `78d9ff4` (master, post-#29) before promotion** — the
double-import count, the key spelling, and the ignored filters all still hold.

## Decisions taken at promotion

Three questions the shape intent left open or answered differently:

| Question | Decision |
|---|---|
| The relative-path `exclude_patterns` bug found while re-measuring (below) | **Fold into this feature.** Without it "both paths honour your filters" is true only for absolute directory paths, and nothing says so |
| A module the configuration excludes is no longer imported, so its import-time side effects stop running | **Accepted.** It is the point of a pre-import filter, and it is what the lazy path already does |
| The defensive fallback branch that still calls the old scanner when no provider was wired | **Make it filter too.** The safety net stays; silently-unfiltered discovery is the exact bug class this feature exists to remove |

## The fourth defect found at promotion: `exclude_patterns` is ignored for a relative directory

Not in the shape intent, and it affects **both** paths, so fixing only the
eager path would leave them equally wrong:

```python
JobSources(directories=["jobs"])      + exclude_patterns=("skipme.py",)  ->  ['deploy-thing', 'skipped-job']   # ignored
JobSources(directories=["/abs/jobs"]) + exclude_patterns=("skipme.py",)  ->  ['deploy-thing']                  # honoured
```

`GlobExcludePreFilter` matches a candidate against the scan root that contains
it. A relative root never contains an absolute candidate path, so the match
never fires and the file is silently admitted. Probed directly:

```
build_pre_filter_from_config(..., Path("jobs"),      [Path("jobs")]).should_import(<abs>/jobs/skipme.py)      -> True   (admitted)
build_pre_filter_from_config(..., Path("<abs>/jobs"),[Path("<abs>/jobs")]).should_import(<abs>/jobs/skipme.py) -> False  (excluded)
```

`func --exclude` is unaffected: the CLI resolves its scan roots to absolute
first, and all three pattern spellings (`skipme.py`, `skipme*`, `*skipme.py`)
were verified working there. This is a library-mode defect, and the natural way
to write a directory (`"jobs"`) is the broken one.

Fixed by resolving the scan roots where the filters are built. A related
wrinkle disappears with it: relative and absolute spellings of one directory
share a cache entry today, so a run under one spelling can serve stale results
to the other.

---

Closes `.spec/STATUS.md` #30, and three defects found while auditing it.

## Problem statement

`boot_standard` builds a `DirectoryScanProvider` from the resolved
`DiscoveryConfig` — with `pre_filter` and `job_filter` — and adds it to the
resolution pipeline. On the eager path (`JobSources(lazy=False)`) it then
registers jobs by a different route entirely:

```python
if app._jobs_directories:
    if app._lazy_boot:
        _register_jobs_lazy(app)                                          # uses the provider
    else:
        app.job_registry.scan_and_register_headless(app._jobs_directories)  # ← ignores it
        _sync_registry_to_engine(app)

# Pipeline-based registration for non-directory providers
if app._resolution_pipeline.provider_count > (1 if app._jobs_directories else 0):
    all_descriptors = app._resolution_pipeline.resolve_all()
    already_registered = set(app.job_registry._registered_jobs.keys())
    new_descriptors = [d for d in all_descriptors if d.name not in already_registered]
```

`scan_and_register_headless` enumerates with `pkgutil.iter_modules` and takes no
discovery filter. One provider is built and bypassed; a second scanner runs
instead. Four observable defects follow, and they are one root cause.

### D1 — every job module is imported twice

Whenever `provider_count > 1`, the guard opens and `resolve_all()` calls
`list_jobs()` on **every** provider, including the directory provider whose work
`scan_and_register_headless` has already done.

Measured with a module-level side-effect counter, two job modules, **no
`DiscoveryConfig` at all**:

| Second provider | `lazy=False` imports | `lazy=True` imports |
|---|---|---|
| none (directories only) | 2 — correct | 2 — correct |
| `functions=[...]` | **4** | 2 — correct |
| a child project | **4** | 2 — correct |

The lazy column is the invariant the eager column should meet: one import per
admitted module, whatever else is in the pipeline.

A separate run with `exclude_patterns=("skipme.py",)` and a child project gives
the D4 picture below — `lazy=False` imports **3** (the unfiltered scan takes 2,
the filtered provider adds 1) while `lazy=True` imports **1**.

**Import-time side effects therefore run twice**, on the one path documented as
*"the escape hatch for users who need import-time side effects"*
(`contributor/architecture/developer-modes.md:48`). It also doubles the cost of
a path whose measured budget is already ~2000 ms against `lazy=True`'s ~125 ms.

D1 needs **no** `DiscoveryConfig`. It needs only a second provider, which
`functions=[...]` supplies — a far more common shape than a child project.

**This regressed last session.** Before `1f24356`, `boot_standard` added exactly
one provider (verified: no other `add_provider` call existed in that function),
so the guard could never open without a child project. `wire_declared_job_sources`
fixed `JobSources.functions` being silently ignored and, in doing so, gave
`boot_standard` a second provider. The fix was correct; this consequence was
not noticed.

### D2 — `_registered_commands` is keyed by the Python name, and goes stale

The eager path writes `f"{job_group or '__top__'}::{attr_name}"` — the Python
attribute name. Every consumer expects the canonical descriptor name:

| Consumer | Expects |
|---|---|
| `app/core.py:496` — `refresh()` eviction | `key.split("::")[-1] in {d.name}` |
| `app/adapters/cli.py:1262-1265` — `_show_job_config` | a user-typed canonical name (`key.endswith(f"::{job_name}")`) |

Verified for a job named `deploy_thing` (canonical `deploy-thing`):

```
lazy=False   descriptor: deploy-thing   key: __top__::deploy_thing
lazy=True    descriptor: deploy-thing   key: __top__::deploy-thing
```

The consequence is not unbounded growth — the write is idempotent — but
**staleness**: after the job file is deleted and `refresh()` runs, `lazy=False`
still reports `__top__::deploy_thing` while `get_jobs()` returns nothing.
`refresh()` exists for exactly the long-lived consumers (TUI, MCP server) that
would observe this. D2 needs no `DiscoveryConfig` either.

### D3 — discovery filters are ignored

The original #30. `exclude_patterns`, every `require_*`, and
`DiscoveryConfig.pre_filter` have no effect on the eager path.

### D4 — …except partially, and confusingly

When the guard is open *and* a filter is set, the provider half **does** filter —
3 imports rather than 4, against `lazy=True`'s 1 — but its descriptors are then
discarded by the
`already_registered` dedupe, because the unfiltered scan got there first. So the
filter changes which modules are imported and not which jobs exist. A
half-applied filter is worse than none: it makes the symptom depend on whether
some unrelated second provider happens to be present.

### Reach — narrower than #30 implied, and stated plainly

`lazy` is a `JobSources` field and nothing else. All three `JobSources(...)`
constructions in `_cli` hardcode `lazy=True` (`main.py:509`, `:1210`, `:1330`)
and there is no flag, config key, or environment variable. The CLI's eight
discovery flags — `--exclude`, `--require-file-{prefix,postfix,import,marker}`,
`--require-job-{prefix,postfix,decorators}` — therefore only ever reach the
*correct* path.

A library-mode app receives filters only if the host hand-built them:
`self._discovery_config = discovery_config` (`app/core.py:169`) is the sole
assignment in the tree, and nothing merges `[tool.functualize.discovery]` into a
library app.

So:

| Defect | Requires |
|---|---|
| D1, D2 | `lazy=False` alone (D1 also needs a second provider) |
| D3, D4 | `lazy=False` **and** a hand-passed `DiscoveryConfig` |

D1 and D2 are the reason this is worth fixing now. D3 and D4 come free with the
same change.

## User stories

- **As a library-mode host** using `lazy=False` for import-time side effects, my
  modules are imported **once**, so those side effects happen once.
- **As the same host**, a long-lived process that calls `refresh()` stops
  reporting jobs whose files I deleted.
- **As a host** who hand-built a `DiscoveryConfig`, it is honoured on both boot
  paths, and honoured the same way.
- **As a maintainer**, there is one directory-scanning path in production rather
  than two that must agree forever — the drift that produced all four defects.

## Behavior

### One scan, from the provider boot already built

With `jobs_directories` set and `lazy=False`, boot registers the descriptors the
pipeline's directory provider yields. Each admitted module is imported exactly
once regardless of how many other providers are present.

### The escape hatch keeps every promise it makes

| Promise | Preserved because |
|---|---|
| Every admitted job module imported at boot | `DirectoryScanProvider` imports each admitted module to extract descriptors |
| Import-time side effects run at boot | same — and now exactly once |
| DI validation at boot, not first use | `DirectoryScanProvider` sets `function=attr` (`providers.py:653`), so `register_descriptors` takes the live-function branch (`boot.py:1243`) rather than a `LazyJobFunction` proxy; `validate_di_bindings()` at `boot.py:674` skips only proxies, so a live entry is still validated at boot |
| All errors at boot | same; nothing is deferred |

One promise is **withdrawn deliberately**: a module the configuration excludes is
no longer imported, so its import-time side effects no longer run. That is the
D3 fix, and it is called out because a host relying on a side effect in an
excluded module would notice.

### Both paths admit the same set

For a given `DiscoveryConfig` and directory set, the eager and lazy paths
discover the same job names. "Both filter" is not the property — two independent
filter applications that agree today and drift tomorrow is what produced this.

### One key spelling everywhere

`_registered_commands` is keyed `<group or __top__>::<descriptor.name>` on every
registration path, so `refresh()` eviction and `builtin info --job` behave
identically whichever path registered the job.

### `lazy=True` is untouched

## Acceptance criteria

Executable; measurements taken against `6699af6` at authoring time with a
module-level side-effect counter.

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | With `lazy=False` and `functions=[...]`, each job module is imported exactly once | **twice** (2 modules → 4 imports) |
| A2 | Same, with a child project instead of `functions` | **twice** (2 modules → 4 imports) |
| A3 | A module-level side effect on the eager path fires exactly once | fires twice |
| A4 | With `lazy=False` and no second provider, imports stay at one per module | already correct (2 modules → 2 imports) — a control, so A1/A2 cannot pass by disabling the eager scan wholesale |
| A5 | `_registered_commands` keys use the canonical descriptor name on the eager path | keyed `__top__::deploy_thing` for descriptor `deploy-thing` |
| A6 | After deleting a job file, `refresh()` on the eager path leaves no key behind | phantom `__top__::deploy_thing` survives |
| A7 | `lazy=False` honours `exclude_patterns`, every `require_*`, and `pre_filter` | ignored |
| A8 | The eager and lazy paths return the **same** job-name set for the same `DiscoveryConfig` | differ whenever any filter is set |
| A9 | A module excluded by config is **not imported** on the eager path (asserted by side effect, not by the job list) | imported |
| A10 | A DI-binding error in an admitted job is still **found while constructing** under `lazy=False`, rather than deferring to first use | holds; must keep holding. **Amended by `parameter-type-support`:** the disposition changed from raising for the whole app to reporting per job (ADR-018). The substance — eager boot validates rather than defers — is what this criterion protects, and it is unchanged |
| A11 | `grep -rn "scan_and_register_headless(" src/` — the eager branch no longer calls it | **2** (`boot.py:1144` eager, `boot.py:1452` defensive fallback) |
| A12 | `TestTheEagerPathFiltersNothing` is inverted, not deleted — the class still documents the defect and now asserts the fixed behaviour | pins the broken behaviour |
| A13 | Full gates green, `lint-imports` included | — |
| A14 | `exclude_patterns` is honoured for a **relative** `directories` entry, on both paths | ignored on both |
| A15 | Every `require_*` setting is honoured for a relative entry too, on both paths | `require_file_prefix` already worked; the glob filter did not |
| A16 | Relative and absolute spellings of one directory resolve to the same admitted set | differ, and share one cache entry |
| A17 | The defensive fallback applies the same filters as the real path | scans unfiltered |

## Out of scope

- **The `lazy=True` path.** Untouched.
- **Deprecating `lazy=False`.** The maintainer chose to fix it (2026-09-07).
- **`scan_and_register_headless` itself** keeps its second caller, the
  defensive fallback for when no cached provider was wired. **Revised at
  promotion:** that caller now applies the same filters (A17), rather than
  leaving the question open — an unfiltered fallback means filters silently
  stop applying if it ever fires.
- **`scan_and_register`** (the CLI-wiring sibling): no production caller.
- **Exposing `lazy` to the CLI or config.** It stays programmatic.
- **Child-project providers being built without filters** (`boot.py:1084`).
  Deliberate per ADR-011 and unchanged here.

---
