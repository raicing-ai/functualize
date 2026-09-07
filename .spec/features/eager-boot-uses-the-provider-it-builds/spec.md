# Eager boot uses the provider it builds

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
`scan_and_register_headless` has already done. Measured with a module-level
side-effect counter:

| Configuration | Modules | Imports |
|---|---|---|
| `lazy=False`, directories only | 2 | **2** |
| `lazy=False` + `functions=[...]` | 2 | **4** |
| `lazy=False` + a child project | 2 | **4** |
| `lazy=True` + a child project | 2 | 1 |

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
| `app/adapters/cli.py:1264` — `_show_job_config` | a user-typed canonical name |

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
3 imports rather than 4 — but its descriptors are then discarded by the
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
| DI validation at boot, not first use | descriptors carry a live `function`, so `register_descriptors` registers directly with a detected `config_class`, not a `LazyJobFunction` proxy |
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
| A4 | With `lazy=False` and no second provider, imports are unchanged at one per module | already 1 — a control, so A1/A2 cannot pass by disabling the eager path wholesale |
| A5 | `_registered_commands` keys use the canonical descriptor name on the eager path | keyed `__top__::deploy_thing` for descriptor `deploy-thing` |
| A6 | After deleting a job file, `refresh()` on the eager path leaves no key behind | phantom `__top__::deploy_thing` survives |
| A7 | `lazy=False` honours `exclude_patterns`, every `require_*`, and `pre_filter` | ignored |
| A8 | The eager and lazy paths return the **same** job-name set for the same `DiscoveryConfig` | differ whenever any filter is set |
| A9 | A module excluded by config is **not imported** on the eager path (asserted by side effect, not by the job list) | imported |
| A10 | A DI-binding error in an admitted job still raises at boot under `lazy=False` | holds; must keep holding |
| A11 | `grep -rn "scan_and_register_headless(" src/` — the eager branch no longer calls it | **2** (`boot.py:1144` eager, `boot.py:1452` defensive fallback) |
| A12 | `TestTheEagerPathFiltersNothing` is inverted, not deleted — the class still documents the defect and now asserts the fixed behaviour | pins the broken behaviour |
| A13 | Full gates green, `lint-imports` included | — |

## Out of scope

- **The `lazy=True` path.** Untouched.
- **Deprecating `lazy=False`.** The maintainer chose to fix it (2026-09-07).
- **`scan_and_register_headless` itself.** It keeps its second caller — the
  defensive fallback at `boot.py:1452` when no cached provider was wired.
  Whether *that* should filter is a separate question.
- **`scan_and_register`** (the CLI-wiring sibling): no production caller.
- **Exposing `lazy` to the CLI or config.** It stays programmatic.
- **Child-project providers being built without filters** (`boot.py:1084`).
  Deliberate per ADR-011 and unchanged here.
