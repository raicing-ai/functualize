# Tasks — `declared-plugin-directories`

**11 tasks / 8 waves.** Every gate carries its measured `now:` value, taken on
`63d5b30`. A gate whose `now:` does not reproduce is a signal to re-measure
before editing, not to proceed.

⚠️ **Known pre-existing failure, not caused by this feature.**
`tests/perf/test_startup_budget.py::TestWarmCommandBudget::test_a_warm_func_job_stays_within_budget`
fails at **2270ms against an 1800ms budget**. Proved pre-existing during T1 by
reverting both changed files to HEAD and re-running: **2315ms**, marginally worse
without the change. It spawns real `func` subprocesses and this host is slow at
that. Do not read it as a regression from any task here.

Wave ordering is binding. Reachability precedes `[x]` — name the production path
and break it once (`contributor/guides/wiring-discipline.md`).

**The suite is green at every wave boundary.** T4 (pure refactor) is deliberately
sequenced before T5 (the behaviour change) so a bisect can tell "moved the code"
from "fixed the bug".

⚠️ **`rg` hides dotfiles by default.** The doc gate in T7 needs `--hidden` or it
silently misses `examples/plugins/file_based_plugin/.functualize.toml`. Measured:
`3` without, `4` with.

---

## T0 · Commit the reproduction fixture as a test — [x]

`[F]` `tests/plugins/test_declared_plugin_directories.py`

Write the end-to-end failing test **first**, from the bug report's layout, so
every later task has a falsifier that is red before it and green after.

```
02_multi/
├── .functualize/plugins/marker_plugin.py    # prints a marker from __call__
└── hello_app/
    ├── pyproject.toml     # [tool.functualize] plugins_directories = [<abs>]
    └── jobs/sample.py
```

Three cases, matching `spec.md` §A.2: declared-from-subdirectory (AC-1),
convention-at-exact-cwd (AC-2), convention-from-subdirectory (AC-3).

- **Gate** the new file's declared case fails — `now: FAIL (marker absent)` ·
  `after T5: PASS`
- **Gate** `uv run pytest tests/plugins/test_declared_plugin_directories.py`
  — measured `1 passed, 3 skipped, 2 xfailed` (the 3 skips are the `app`-surface
  variants, restricted by `@surfaces("func")`). AC-2 passes; AC-1 and AC-3 do not.
- **Gate — the xfails fail for the *right* reason**, which a strict xfail alone
  does not prove. Under `--runxfail` both report
  `exit_code=0, stdout='ran\n', stderr='', marker absent`: the job runs and
  exits clean, the plugin is simply never loaded, and **stderr is empty** —
  AC-6's premise measured in passing.
- **Reachability** — n/a, this task adds only tests. It is the reachability
  instrument for T5.

**Marked `# TRANSITIONAL(declared-plugin-directories/T5)`** with `xfail(strict=True)`
on the two red cases, so the suite is green at this wave boundary and the xfail
flips to a failure the moment T5 lands correctly.

---

## T1 · Move `resolve_user_config_dir` down to `_primitives/` — [x]

`[M]` `src/functualize/_primitives/locator.py`
`[M]` `src/functualize/app/utils.py`

`_config/project_dirs.py` (T2) needs the XDG *config* directory, and
`app/utils.py:1033` is in the public package where no internal layer may reach
it. Add `xdg_config_dir()` beside the existing `_xdg_cache_dir` /`_xdg_data_dir`
in `_primitives/locator.py`; leave `resolve_user_config_dir` in `app/utils.py`
as a one-line wrapper so its `__all__` entry and every caller keep working.

Keep the `$XDG_CONFIG_HOME` handling verbatim — empty string falls back to
`~/.config`, which is not the same as `os.environ.get(...)` being `None`.

- **Gate** `rg -n "def xdg_config_dir" src/functualize/_primitives/locator.py`
  — `now: 0` · `after: 1`
- **Gate** `uv run lint-imports` — `now: 7 kept, 0 broken` · `after: unchanged`
- **Reachability** — **the gate as written was false, and sabotage is what
  showed it.** `test_global_config_provides_baseline` passes `global_config=`
  explicitly, so it never calls `resolve_user_config_dir`; under a sabotaged
  `xdg_config_dir` returning `Path("/nonexistent")` it **still passed**.

  The real falsifier reads an actual `$XDG_CONFIG_HOME/functualize/config.toml`:
  `tests/cli/test_auto_discover_properties.py::TestConfigDirsInOutput::test_xdg_global_config_jobs_directories_appear_in_output`
  — `--run-slow`-gated, so it needs that flag or it reports as *skipped* rather
  than as a pass. It **fails** under the same sabotage and passes on restore.
  Production call path: `_cli/main.py → auto_discover → resolve_user_config_dir
  → xdg_config_dir`.

---

## T2 · Extract walk A into `_config/project_dirs.py` — [x]

`[F]` `src/functualize/_config/project_dirs.py`
`[M]` `src/functualize/app/utils.py`
`[M]` `src/functualize/_config/__init__.py`

**Behaviour-neutral move.** The symbol list is `schema.md` §5, and it is the hit
set of the serena reference pass, not a list from memory. `app/utils.py` keeps
`resolve_project_config`, `resolve_effective_directories`,
`_collect_convention_directories` and `_read_toml_file` as thin wrappers with
**unchanged signatures** — that is what keeps AC-14's 21 tests green without
touching them.

`merge_config_layers` does **not** move; it is already in `_config/` and
`app/utils.py:24` already imports it from there.

- **Gate** `uv run pytest tests/cli/test_effective_directories.py tests/cli/test_convention_dirs.py tests/test_auto_discover_bug_condition.py`
  — measured **`now: 28 passed` · `after: 28 passed`**, files unmodified (AC-14).
  The plan said 21; that was `def test_` counted in two files, not the
  collected total across all three.
- **Gate** `wc -l src/functualize/app/utils.py` — `now: 2380` · `after: ≈2160`
- **Gate** `uv run lint-imports` — `now: 7 kept, 0 broken` · `after: unchanged`
- **Reachability** — the wrappers are the production path
  (`_cli/main.py` → `auto_discover` → the moved code). Replace the body of
  `_config/project_dirs.resolve_effective_directories` with `return {}` and the
  21 tests above must fail. If they pass, the wrapper is not delegating.

---

## T3 · `ProjectDirectories` and the composition rule — [x]

`[M]` `src/functualize/_config/project_dirs.py`
`[F]` `tests/config/test_project_dirs.py`

The new logic, unit-tested directly and **not yet wired** — so a failure here is
attributable to the rule rather than to the wiring.

`ProjectDirectories` (`schema.md` §1) and `resolve_plugin_directories()`
(`schema.md` §2), returning `(declared, convention)` as two lists so T5 can warn
about one and stay silent about the other.

The convention directory comes from `find_functualize_dir(cwd)` — walk C — **not**
from walk A's config-hit list. `research.md` §6.2 measured why: walk A collects
`[]` for a directory that holds `.functualize/plugins/` but no config file, which
is exactly the reported layout.

Cover on each rung (AC-3c): inherited two levels up; `root = true` stopping that
inheritance; XDG `~/.config/functualize/config.toml` supplying the value; and
AC-3b — a `.functualize/plugins/` **above** the project root is not returned.

- **Gate** `uv run pytest tests/config/test_project_dirs.py` — `now: n/a (file absent)` · `after: all pass`
- **Gate** AC-3b falsifier: a plugins dir in the parent of the project root is
  absent from both returned lists — `after: PASS`
- **Reachability** — **none yet, and that is disclosed.** T3 adds an unwired
  symbol; T5 is what reaches it. Do not mark `[x]` claiming a production path.
  Mark `# TRANSITIONAL(declared-plugin-directories/T5)` on the new function.

---

## T4 · Extract `FilePluginSource` — [x]

`[F]` `src/functualize/_plugins/file_source.py`
`[M]` `src/functualize/_plugins/loader.py`
`[M]` `tests/plugins/test_file_plugin_edge_cases.py`, `tests/test_file_plugin_discovery.py`, `tests/plugins/test_load_all_file_discovery.py`

**Pure refactor — no behaviour change.** `_discover_from_files`,
`_load_file_plugin` and `_find_plugin_in_module` move to `FilePluginSource`
(`schema.md` §3); `PluginLoader` holds one as `self._file_source` and still calls
`_resolve_plugin_directories` to get the paths. The bug is untouched by this task.

Forced by `.spec/CONSTITUTION.md:95` — *"if a class exceeds ~500 LOC, decompose
it"*. `PluginLoader` is 595; T5's deletion alone leaves 553, still over.

The three test files stop patching a private method on the loader and construct a
`FilePluginSource` with a directory list — they no longer need an `app` mock at
all, which is the point.

- **Gate** `PluginLoader` LOC — `now: 595 (277-871)` · `after: ≈475`
  (T5 takes it to ≈435). Measure with
  `python -c "import ast,sys;t=ast.parse(open('src/functualize/_plugins/loader.py').read());print(next(n.end_lineno-n.lineno+1 for n in ast.walk(t) if isinstance(n,ast.ClassDef) and n.name=='PluginLoader'))"`
  — an AST walk, not `rg`, per the retrieval rules
- **Gate** `rg -c "_discover_from_files" tests/ examples/` — `now: 9+4+7+1 = 21 lines` · `after: 0`
- **Gate** `uv run pytest tests/plugins/ tests/test_file_plugin_discovery.py` — `now: green` · `after: green`
- **Reachability** — `boot_standard → load_all → self._file_source.discover`.
  Make `FilePluginSource.discover` return `[]` unconditionally; the retargeted
  file-discovery tests must fail.

---

## T5 · The fix — boot resolves, the loader receives — [x]

`[M]` `src/functualize/_plugins/loader.py`
`[M]` `src/functualize/_app/boot.py`
`[D]` `tests/plugins/test_resolve_plugin_directories.py`
`[M]` `tests/cli/test_single_file_cwd_isolation.py`
`[M]` `tests/plugins/test_declared_plugin_directories.py` (drop the xfails)

The one arrow reversed (`plan.md` §4.1).

1. `load_all(app, *, directories=None, ...)` — keyword-only, defaulting to
   "scan nothing". Delete `_resolve_plugin_directories` entirely.
2. `_app/boot.py` step 3.5: call `resolve_project_directories(...)` in its **own
   function**, not inline — `boot_standard` is ~400 LOC and adding to it deepens
   a *long method* this plan otherwise reduces (`plan.md` §6.1).
3. Boot applies `PluginSources.ambient_directory` when assembling the list, and
   emits `logger.warning` for a **declared** directory that is missing or yields
   nothing — never for an absent convention one (AC-6/6b/6c).

**Delete `tests/plugins/test_resolve_plugin_directories.py` outright.** All 8
tests assert the behaviour of a method that no longer exists, and 6 of them
manufacture `app._resolution_chain = chain_mock` — the state boot never produces.
T0's file is the replacement.

- **Gate** `rg 'hasattr\(app, "_resolution_chain"\)' src/functualize/_plugins/loader.py`
  — `now: 1` · `after: 0`
- **Gate** `rg -c 'Path\.cwd\(\)' src/functualize/_plugins/loader.py` — `now: 1` · `after: 0`
  (removes the *Forbidden Pattern* at `.spec/CONSTITUTION.md:94`)
- **Gate** `grep -c "_resolution_chain = chain_mock" tests/plugins/test_resolve_plugin_directories.py`
  — `now: 6` · `after: file does not exist` (AC-10)
- **Gate** the reproduction, run through the CLI from the subdirectory —
  `now: 0 markers` · `after: 1 marker` (AC-1)
- **Gate** `uv run pytest tests/plugins/test_declared_plugin_directories.py`
  — `now: 1 passed, 2 xfailed` · `after: 3 passed`
- **Gate** programmatic app, no CLI — `FunctualizeApp(name="x")` in a project
  declaring `plugins_directories` loads the plugin (AC-9b). Measured today:
  `rg -n "auto_discover" src/functualize/_app/` → `now: 0`, i.e. walk A never
  ran on this path at all.
- **Reachability** — `boot_standard` step 3.5 → `load_all(directories=...)`.
  Sabotage: make step 3.5 pass `directories=[]`. T0's AC-1 and AC-3 cases must
  fail. **"A test calls it" is not a call path** — the sabotage must be on the
  boot line, not on the resolver.

---

## T6 · The second dead guard — `[<domain>] provider` — [x]

`[M]` `src/functualize/_plugins/domain_registry.py`
`[M]` `src/functualize/_app/boot.py`
`[M]` `tests/plugins/test_domain_registry.py`

Same defect, same cure (`spec.md` §A.4). `_read_configured_provider(config, metadata)`
becomes a plain mapping lookup; `boot_domain_registry(app, *, config=...)` receives
the `merged` dict step 3.5 already produced.

**Disclosed narrowing** (`plan.md` §6.5): this reads File + Convention + Global,
not CLI or Env — the chain does not exist at step 4b and cannot without breaking
ADR-007. The value is `None` *always* today, so every project gains and none
loses. Mark `# TRANSITIONAL(declared-plugin-directories)` naming the missing rungs.

- **Gate** `rg 'hasattr\(app, "_resolution_chain"\)' src/functualize/_plugins/`
  — `now: 2 lines (loader.py, domain_registry.py)` · `after: 0` (AC-8)
- **Gate** a booted app with `[<section>] provider = "..."` selects that provider
  — `now: always the auto-selected default` (measured: `hasattr` per call
  `[False, False]`) · `after: the configured one` (AC-7)
- **Reachability** — `boot_standard` step 4b → `boot_domain_registry(app, config=...)`
  → `_read_configured_provider`. Pass `config={}` and the new test must fail.

---

## T7 · Documentation truth — [x]

`[M]` `docs/examples/plugins/file-based-plugin.md:21`
`[M]` `examples/plugins/file_based_plugin/README.md:32`
`[M]` `contributor/architecture/developer-modes.md:170`
`[M]` `examples/plugins/file_based_plugin/.functualize.toml:11`
`[M]` `examples/plugins/file_based_plugin/tests/test_file_plugin.py`

Three documents assert the broken path works (`spec.md` §A.5). Correct them to
describe the shipped behaviour: declared **and** convention, composed, with the
convention directory at the project root.

The example's `.functualize.toml:11` says `plugins_directories` is *"deliberately
NOT set"* — once the option works, that comment needs a reason about the
**example** rather than about the bug (AC-12).

The example's own test is three workarounds stacked on one bug: it imports
`functualize._plugins.loader` (an *example* reaching into an internal package),
`chdir`s to make the cwd fallback fire, and mocks
`app._resolution_chain.resolve.side_effect` to step over the dead branch. Replace
with a booted app.

- **Gate** `rg -n --hidden 'plugins_directories' docs/ contributor/ examples/ README.md`
  — `now: 4` (**`--hidden` is required**; without it `3`, silently missing the
  dotfile) · `after: 4, every line describing shipped behaviour` — verified by
  **re-reading each line**, not by the count (AC-11)
- **Gate** `rg -c "functualize\._plugins" examples/` — `now: 1` · `after: 0`
- **Gate** `uv run pytest examples/plugins/file_based_plugin/` — `now: green` · `after: green`
- **Reachability** — n/a (documentation). The example test's reachability is the
  booted app it now uses.

---

## T8 · CHANGELOG — both entries — [x]

`[M]` `CHANGELOG.md`

Two separate entries, and they are separate subjects:

1. **This fix** (AC-15) — `plugins_directories` was documented and dead across
   `0.2.3` and `0.3.0`; anyone who worked around it needs to know it now works,
   that the convention directory now resolves at the project root, and that
   `[<domain>] provider` is now read.
2. **The `0.3.0` facade migration** (AC-16, maintainer decision 2026-09-18) —
   `app.before_job` → `app.hooks.before_job`, with the before/after snippet and
   the fact that an un-migrated plugin is skipped with a warning rather than
   failing the app. Intended and final; **no shim**, per
   `.spec/CONSTITUTION.md:99` (no compat shims pre-1.0).

⚠️ `CHANGELOG.md` has uncommitted changes from a concurrent session on this
branch — rebase before editing rather than assuming the file is as last read.

- **Gate** `grep -c -i 'app\.hooks\|HooksFacade\|facade' CHANGELOG.md` — `now: 0` · `after: ≥1` (AC-16)
- **Gate** `rg -c 'plugins_directories' CHANGELOG.md` — `now: 0` · `after: ≥1` (AC-15)
- **Reachability** — n/a (documentation).

---

## T9 · Verification sweep — [x]

No production files. Run the full gate set and record measured results.

- **Gate** `uv run pytest` (root) — `now: baseline` · `after: ≥ baseline, 0 failed`
- **Gate** `uv run pytest examples/` — `after: green`
- **Gate** each `plugins/*/tests` separately — `after: at baseline`
- **Gate** `uv run lint-imports` — `now: 7 kept, 0 broken` · `after: 7 kept, 0 broken` (AC-13)
- **Gate** `uv run mypy src/` — `after: green`
- **Gate** `uv run ruff check src/ tests/ plugins/ examples/` and `ruff format --check` — `after: clean`
- **Gate** god-object bar (AST walk): `PluginLoader` — `now: 595` · `after: ≤500` (AC-9, `plan.md` §7.3)
- **Gate** orphan scan (serena): every symbol added by T1–T6 has a production
  consumer. `ProjectDirectories`, `resolve_plugin_directories`,
  `FilePluginSource`, `xdg_config_dir` — name the caller of each.
- **Gate** `rg 'hasattr\(app, "_resolution_chain"\)' src/functualize/_plugins/` — `after: 0` (AC-8)
- **Reachability** — this task *is* the reachability audit.

### Results — measured 2026-09-19

| Check | Result |
|---|---|
| `uv run pytest tests/ -n auto` | **10,762 passed**, 1,605 skipped, 0 failed |
| `uv run pytest examples/` | **212 passed** |
| each `plugins/*/tests` separately | **447 passed**, 1 skipped, 12 packages |
| `uv run mypy src/` | green, **360** files (was 358; +2 modules) |
| `uv run lint-imports` | **7 kept, 0 broken** |
| `ruff check` / `format --check` (CI's scope) | clean, 1,454 files |
| `PluginLoader` LOC (AST walk) | **595 → 436**, bar ~500 — PASS |
| guard statements in `_plugins/` | **0** |
| `Path.cwd()` in `_plugins/loader.py` | 1 → **0** |
| `_resolution_chain = chain_mock` in `tests/` | 6 → **0** |
| second resolver for `plugins_directories` | none |

**The perf-budget failure is gone**, and was never this feature's:
`test_a_warm_func_job_stays_within_budget` failed at 2270 ms during T1 and
passes under `-n auto` here. Proved pre-existing at the time by reverting to
HEAD and measuring **2315 ms** — worse without the change.

**Orphan scan — production call path for every symbol T1–T6 added:**

| Symbol | Reached from |
|---|---|
| `resolve_project_directories` | `boot_standard` step 3.5 |
| `resolve_plugin_directories` | `resolve_project_directories` |
| `ProjectDirectories` | `boot.py` — consumed at steps 4 and 4b |
| `FilePluginSource` | `PluginLoader.__init__` → `load_all` Phase 1b |
| `xdg_config_dir` | `project_dirs` (Global rung), `app/utils.resolve_user_config_dir` |
| `find_functualize_dir` | 7 files incl. both `_format` modules and `_app/impl.py` |

### ⚠️ Three of this feature's own gates were false as written

Recorded because the pattern matters more than the individual fixes: **a gate
written as a substring search can match its own documentation, and a gate can
name a test that never touches the code.**

1. **T1's reachability gate** named `test_global_config_provides_baseline`,
   which passes `global_config=` explicitly and never calls
   `resolve_user_config_dir`. It stayed **green under sabotage**. Real
   falsifier: `test_auto_discover_properties.py::TestConfigDirsInOutput::test_xdg_global_config_jobs_directories_appear_in_output`
   (`--run-slow`-gated — without the flag it *skips*, which reads like a pass).
2. **AC-8's gate** `rg 'hasattr\(app, "_resolution_chain"\)' src/functualize/_plugins/`
   returns **1** — matching the docstring that explains the removal. Anchored to
   code, `rg 'if (not )?hasattr\(app, "_resolution_chain"\)'` returns 0.
3. **AC-12's gate** `rg -c "functualize\._plugins" examples/` returns **1** —
   matching the sentence describing what the test used to do. Anchored to
   imports, `rg '^\s*(from|import) functualize\._' examples/` returns 0.

T2's count was also wrong in the plan (21 vs the measured 28 collected), and
T10's premise — "byte-identical" — was false. Five corrections in eleven tasks.

---

## T10 · Collapse the duplicated `find_functualize_dir` — [x]

`[M]` `src/functualize/_primitives/locator.py`
`[M]` `src/functualize/_primitives/cache_format.py`
`[M]` `src/functualize/_primitives/fresh_format.py`
`[M]` `src/functualize/_app/impl.py`, `src/functualize/_app/__init__.py`

**Maintainer decision, 2026-09-18.** In
`_primitives/cache_format.py:289` and `_primitives/fresh_format.py:108`.

⚠️ **They were *not* byte-identical, as this task and `plan.md` §8.3 both
claimed.** `fresh_format` did `Path(start).resolve()` first; `cache_format` did
not. Measured from `<root>/sub/deep` with `.functualize/` at `<root>`:
`cache_format(Path("."))` → `None`, `fresh_format(Path("."))` →
`<root>/.functualize`. They agreed only on absolute input, which every caller
passes today — so the resolving form was adopted: no observable change, and it
closes a latent bug where `resolve_cache_path` answered *standalone* for a
relative argument.

**Single definition goes to `_primitives/locator.py`**, not to either
`*_format.py`. Those modules are named for the formats they read and write;
"walk up until a `.functualize/` directory appears" is a *location* question, and
`locator.py` already owns the others (`ResourceLocator`, `_xdg_cache_dir`,
`_xdg_data_dir`, and `xdg_config_dir` from T1). This also avoids `fresh_format`
importing `cache_format`, which would be a dependency between two unrelated
formats purely to share a helper.

### ⚠️ The trap — read this before editing

`tests/conftest.py:277-288` (`_isolate_state_root`, **autouse**) does:

```python
from functualize._primitives import fresh_format
real_find = fresh_format.find_functualize_dir
...
monkeypatch.setattr(fresh_format, "find_functualize_dir", _scoped)
```

It patches **`fresh_format`'s copy only** — `cache_format`'s is deliberately left
alone, because the fixture sandboxes *runtime state* (`fresh.json`, `scopes.json`)
and not the discovery cache. Verified: `rg -n "setattr\(.*cache_format" tests/`
returns nothing.

So both modules must **bind the name into their own namespace** —
`from functualize._primitives.locator import find_functualize_dir` — and keep
their call sites **unqualified** (`find_functualize_dir(start)`, as both already
are at `cache_format.py:326` and `fresh_format.py:157`). `monkeypatch.setattr`
rebinds a module global, so an imported name stays patchable; a qualified call
such as `locator.find_functualize_dir(start)` does **not**.

**Getting this wrong fails silently and in the worst direction**: the suite stays
green while tests write durable state outside `tmp_path` — the `-n auto` flake
`_isolate_state_root` exists to prevent. The gate below is that fixture, not the
line count.

- **Gate** `rg -c "^def find_functualize_dir" src/functualize/_primitives/`
  — `now: 2 (cache_format.py, fresh_format.py)` · `after: 1 (locator.py)`
- **Gate** the autouse fixture still redirects. Sabotage-style check: in a test
  using `tmp_path` with no `.functualize/`, assert `resolve_fresh_location`
  returns a path under `tmp_path` — `now: PASS` · `after: PASS`. **If this
  passes only because nothing calls the patched name, it is not a gate** —
  confirm by patching `fresh_format.find_functualize_dir` to raise and watching
  it raise.
- **Gate** `uv run pytest -n auto` — `now: baseline` · `after: baseline, no new
  flakes`. Run with `-n auto` specifically: the serial run would not surface a
  broken sandbox.
- **Gate** `uv run pytest tests/test_state_format.py` (the
  `@pytest.mark.real_state_root` opt-out path) — `now: green` · `after: green`
- **Reachability** — `_app/impl.py:81` `build_resource_locator` →
  `find_functualize_dir`, and `_app/impl.py:146`. Break the surviving definition
  to `return None` and `tests/discovery/test_child_project_cache.py` must fail.

---

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["T0", "T1"]},
  {"id": 1, "tasks": ["T2", "T10"]},
  {"id": 2, "tasks": ["T3"]},
  {"id": 3, "tasks": ["T4"]},
  {"id": 4, "tasks": ["T5"]},
  {"id": 5, "tasks": ["T6"]},
  {"id": 6, "tasks": ["T7", "T8"]},
  {"id": 7, "tasks": ["T9"]}
]}
```

**Why this order**, where it is not obvious:

- **T0 and T1 share wave 0.** T0 is tests-only and T1 is a pure move into a
  different package; neither can affect the other.
- **T0 first of all.** The falsifier exists before anything claims to fix
  something. Its two `xfail(strict=True)` cases are what make T5's success
  detectable rather than asserted.
- **T2 before T3.** T3's new function lives in the module T2 creates. Doing them
  together would mix a behaviour-neutral move with new logic in one diff, and
  the move is exactly the kind of change that must be reviewable as a no-op.
- **T4 before T5, in its own wave.** T4 is a pure refactor with the suite green
  throughout; T5 changes behaviour. Separated so a bisect distinguishes "moved
  the code" from "fixed the bug", and so T4's 21 retargeted test sites are not
  entangled with T5's deletions.
- **T5 before T6** even though the two guards are independent. T5 builds the
  step-3.5 function that T6 then reads `merged` from; doing T6 first would mean
  writing that plumbing twice.
- **T7 and T8 share wave 6** — both documentation, neither depends on the other,
  and both need every behaviour change landed so they describe what shipped.
- **T9 last and alone.** A verification sweep that runs before the last change
  verifies nothing.
- **T10 shares wave 1 with T2.** It depends on T1 only because both edit
  `_primitives/locator.py`, and it shares no file with T2. It is independent of
  the whole plugin-directory change — sequenced early so the duplication is gone
  before T9 audits, and kept out of T5's wave so a `-n auto` flake is
  attributable to one of them rather than to either.
