# 12 · Performance — what this design costs, and one claim withdrawn

This codebase enforces boot budgets in CI (`tests/perf/test_startup_budget.py`, all
`perf_budget`-marked, run serially in `test-fast`). A design that moves work into the boot
path fails the suite. This one does not move work into the boot path — but that has to be
argued, not asserted.

---

## A. The budgets, as enforced at `e57f0c9`

| Phase | Constant | Budget |
|---|---|---|
| `boot.total` | `BUDGET_TOTAL_BOOT_MS` (`:35`) | 500.0 ms |
| `boot.core_infra` | `:36` | 50.0 ms |
| `boot.provider_registry` | `:37` | 10.0 ms |
| `boot.observability` | `:38` | 50.0 ms |
| `boot.plugins` | `:39` | 200.0 ms |
| `boot.config_entry_points` | `:40` | 50.0 ms |
| `boot.config_resolution` | `:60` | 300.0 ms |
| `boot.job_registration` | `:61` | 50.0 ms |
| `boot.children` | `:62` | 50.0 ms |
| `boot.tui` | — | asserts the phase **is not recorded** |

Two more live elsewhere: `boot_static` cold start < 5 ms
(`test_static_wiring_fast_path.py:314`), and pre-boot routing at ~3 ms with **zero job-module
imports** (`test_group_trie_ingestion.py:9`, `test_warm_boot_zero_imports_property.py`).

## B. Boot-time neutral, phase by phase

This design changes what happens **after** `FunctualizeApp(...)` is constructed, not during it.

| Phase | Effect | Why |
|---|---|---|
| Pre-boot routing (~3 ms, zero imports) | **None** | Parsers keep their syntax. Aliases, cache-first routing names and `detect_mode` stay pre-boot; resolution happens after boot. The zero-imports property test fires if pre-boot is ever routed through the facade — which is the real guard here, not a promise |
| Config resolution (300 ms) | **None** | Untouched |
| Job registration (50 ms) | **None** | Registry, trie and cache reads unchanged |
| `boot_static` (< 5 ms) | **None, possibly less** | `build_engine(host)` collapses `boot.py:270-288` and `:482-500` into one builder. No new boot work; one fewer duplicated block |
| Import weight | **Zero** | `run_request.py`, the outcome module and `flag_grammar.py` are stdlib-only `_types` residents. The kernel/delivery split is preserved |

**The resolution move's runtime cost is already paid.** `execute()` itself looks the job up by
name and materializes (`_ensure_materialized` imports once, then no-ops). Consolidating
resolution into `run()` *removes* a duplicate: `func`'s dispatch materializes to build the
click command and the callback then re-resolves ([04 §A](04-request-and-entry.md), sites 2
and 5). What it adds is a call-time dict lookup on the eager click path in place of a
build-time binding — noise against a ~100–300 ms process start, and amortized to nothing on
long-running surfaces (TUI, HTTP, MCP).

`RunRequest` is one frozen dataclass per run. With `slots=True` it is smaller than the
13-argument frame it replaces.

## C. The measurement this design owes — T8

Everything above is an argument. One phase must become a number:

> **After F1's resolution move, add a warm-cache `func <job>` wall-clock phase to
> `tests/perf/test_startup_budget.py`.**

It is part of F1's completion criteria, not a follow-up. The reasoning is the codebase's own:
a budget that is not measured is a comment, and §D is what happens to comments.

## D. Withdrawn — the "largest available boot win" was already shipped

Both the audit synthesis and the perf-budget file recommend memoizing
`importlib.metadata.entry_points()`, described as seven scans per boot costing ~53 ms of the
~65 ms `FunctualizeApp()` construction, and named as *"the largest boot win available today"*.

**It shipped on 2026-08-27** as `84ed555`, *"perf(boot): scan entry points once per process,
not once per group (#4)"*. `src/functualize/_primitives/entry_points.py` exists, holds a
process-wide `_snapshot` under a lock, and its docstring carries the real numbers:

> *"Measured on a 215-distribution environment: 114.7 ms across the seven calls out of 191 ms
> total construction. Collapsing them to one scan removes ~98 ms of the ~115 ms, and every
> surface pays this cost — CLI, TUI, MCP, and the direct-run path alike."*

Six consumers use it: `_plugins/loader.py`, `_plugins/domain_registry.py`,
`_config/registry.py`, `_app/boot.py`, `_cli/plugin_cmd.py`, `_discovery/providers.py`. It
lives in `_primitives/` deliberately, because `_config`, `_discovery` and `_plugins` are
peer-independent and a cache in any one of them would be a forbidden import edge.

### How a shipped optimisation became a live recommendation in an architecture document

The comment that recommends the work is at `tests/perf/test_startup_budget.py:44-60`. It was
written on **2026-08-20** (`b5495c6`, PR #3). The fix landed on **2026-08-27** (`84ed555`,
PR #4) — **the next PR** — and nobody deleted the comment. The audit, written 2026-09-08, read
it and repeated its recommendation as current fact.

Three weeks of a file saying *"one concrete lead: a single boot calls
`importlib.metadata.entry_points()` seven times (measured)"* next to code that calls it once.

This is exactly the failure `.spec/CONSTITUTION.md` → *Retrieval Before Assertion* exists to
prevent, and it is worth recording because the audit did nothing careless: it cited a source,
in-repo, written by a maintainer, with measured numbers. **A stale comment is
indistinguishable from a fresh one, and the only defence is running the command.** The claim
here is checked by `rg 'importlib\.metadata\.entry_points\(' src/`.

Correcting that comment is a task in **F8**.

## E. What is actually left on the table

The memoization is complete on the boot path. **Three sites still bypass it**, found while
withdrawing §D:

| Site | Shape |
|---|---|
| `plugins/functualize-ai/src/functualize_ai/_provider_discovery.py:53` | `importlib.metadata.entry_points(group=…)` — a plugin, outside the cache |
| `src/functualize/_cli/skills.py:156` | lazy import inside a function |
| `src/functualize/_cli/tui/display_provider_discovery.py:77` | lazy import inside a function |

None is on the measured boot path — two are lazy CLI/TUI paths and one is a plugin — so this
is not a boot win and is **not** presented as one. It is a consistency gap: three callers of
a superseded API, which is the same shape as every other finding in this set, at a much
smaller scale. F8 re-points them and adds the absence test that pins the count, so a fourth
cannot appear silently.

## F. Regression risks, and what already catches them

| Risk | Caught by |
|---|---|
| Pre-boot re-routed through the facade | the ~3 ms zero-import property test |
| Eager materialization on the lazy path | `TestWarmBootParity` (`tests/integration/test_declared_capabilities_e2e.py:540`) |
| F8's `TYPE_CHECKING` flag flip | import-time only; zero runtime effect |
| The resolution move itself | **nothing today** — which is why T8 is a completion criterion of F1 rather than a nice-to-have |
