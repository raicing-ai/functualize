# Plan — `declared-plugin-directories`

**Phase:** Plan · architecture gate run 2026-09-18 against `63d5b30`
**Spec:** [`spec.md`](spec.md) — 22 acceptance criteria, no open questions
**Evidence:** [`research.md`](research.md) — §5 the four-walk map, §6 what reusing walk A buys

---

## 1. Retrieval — what each tool was asked, and what it answered

All three passes run; none skipped.

| Tool | Question | Answer that changed the plan |
|---|---|---|
| **zvec-grep** (`/usr/local/bin/zg`, index bound to this worktree, refreshed 21 s) | What does the surrounding prose say this region is *for*? | `docs/contributing.md:224` — *"`_app/` is the **only** internal package allowed to import from all peer layers… If two peer layers need to communicate, they don't import each other. Instead, `_app/boot.py` passes the data between them during construction."* That is the AFTER, stated as house style before this feature existed. |
| **serena** (activated by absolute path) | What is actually in these modules? | `PluginLoader` is **595 LOC** (277–871), `load_all` **341 LOC** (309–649). `_resolve_plugin_directories` uses `self.` **zero times** — measured, not estimated. |
| **graphify** (CLI `graphify explain`; MCP `get_neighbors` fails with `'label'`) | Which way do dependencies point? | `PluginLoader` ← `boot_standard`, `boot_static`, `app/core.py`. `auto_discover` ← `_cli/main.py` only. `resolve_effective_directories` ← **nothing** (degree 7, all internal). |

**graphify is 58 commits behind HEAD** (`built_at_commit 78d9ff4`), so its line numbers are stale by ~45 lines and were not used; only relationship *shape* was taken from it, per the routing rules.

### 1.1 Prior art found, and followed rather than contradicted

`contributor/architecture/audit-engine-encapsulation.md` §*Cause 2* already diagnoses this exact smell class one component over:

> The engine also self-wires ambient state: `_state_store()` builds a
> `StateStore.for_project(Path.cwd())` lazily inside the kernel… Construction is
> also duplicated: `boot_static` and `boot_standard` each build the engine with
> near-identical code — a **Divergent Change** trap.

`PluginLoader._resolve_plugin_directories` calling `Path.cwd() / ".functualize" / "plugins"` is the same defect in the same shape: a kernel component reaching for ambient state instead of receiving it. The recorded cure is constructor/parameter injection from the composition root. This plan applies it rather than inventing a new answer.

`contributor/architecture/codemaps/dependencies.md:71-73` names the idiom concretely: *"`_app/boot.py` wires the concrete B instance into A via constructor injection. Example already in the codebase: `_engine/executor.py`'s `JobExecutionEngine` depends on a `JobLookup`-shaped protocol; `_app/boot.py` passes the concrete `_discovery.pipeline.ResolutionPipeline` in."*

### 1.2 Codemaps read

`overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`, `entry-points.md`.

One contradiction found, and it is a finding rather than a drawing error: `data-flow.md:12` describes boot step 4 as *"entry-point + file-based plugins loaded via `PluginLoader`"* with no mention that file-based discovery cannot see configuration. `developer-modes.md:170` goes further and states the config path works. Both are corrected by AC-11.

---

## 2. Skills consulted

| Skill | Source | What it contributed |
|---|---|---|
| `python-design-patterns` | in-repo, `.claude/skills/python-design-patterns` (symlink to `.agents/skills/`) | *"Duplication that diverges in dangerous ways should be abstracted sooner. The rule of three is a heuristic, not a law. If the copies are already diverging incorrectly, extract immediately and add a test that exercises the shared behavior."* — decides §4 against waiting. Also: *inject dependencies*, *delete before abstracting*. |
| `design-patterns-refactoring` | **user-level** (`~/.claude/skills/`), Refactoring.Guru catalogue | The smell vocabulary and the smell→technique routing used throughout §3 and §7. |

The catalogue is **not** in this repository — confirmed. The six names used below (*feature envy*, *duplicate code*, *large class*, *long method*, *divergent change*, *dead code*) come from the user-level skill, per `.claude/rules/spec-workflow.md`.

---

## 3. BEFORE

```
LAYER          MODULE                                    NOTES
─────────────────────────────────────────────────────────────────────────────────

PUBLIC         functualize/app/utils.py  (2380 LOC)      ── walk A lives here ──
               ├── _CANDIDATES, resolve_project_config        anchor + merge
               ├── _collect_convention_directories            upward, per level
               ├── resolve_effective_directories              0 production callers
               ├── _resolve_effective_directories             CLI+ENV+File+Conv+Global
               └── auto_discover                              computes
                        │                                     effective["plugins_
                        │                                     directories"] and
                        │                                     DROPS it
                        │ imported by
                        ▼
INTERNAL       functualize/_cli/main.py                   public API only  ✓
               (3 call sites) + _cli/self_cmd.py

               ─────────── no edge crosses here ───────────
                    _app/ CANNOT import functualize.app.*
                    (import-linter "Internal never imports public")

COMPOSITION    functualize/_app/boot.py  (1963 LOC)
ROOT           boot_standard (486-885, ~400 LOC)
                 step 2  config_registry = ProviderRegistry()      ADR-007
                 step 4  plugin_loader.load_all(app, ...)  ───┐
                 step 4b boot_domain_registry(app)  ─────┐    │
                 step 6  app._resolution_chain = ...     │    │   ← built HERE
                         discover_config_path (walk B)   │    │
                                                         │    │
PEER LAYER     functualize/_plugins/domain_registry.py   │    │
               _read_configured_provider  ◄──────────────┘    │
                 if not hasattr(app,"_resolution_chain")      │
                     return None            ← ALWAYS TRUE     │
                                                              │
PEER LAYER     functualize/_plugins/loader.py                 │
               PluginLoader  (595 LOC — over the ~500 bar)    │
                 load_all (341 LOC)  ◄───────────────────────┘
                   └─ _discover_from_files
                        └─ _resolve_plugin_directories   ← uses self. ZERO times
                             if hasattr(app,"_resolution_chain")   ← ALWAYS FALSE
                             ...
                             Path.cwd()/".functualize"/"plugins"   ← hard-coded,
                                                                     no walk
                        └─ _load_file_plugin
                        └─ _find_plugin_in_module

FOUNDATION     functualize/_primitives/locator.py   ResourceLocator, _xdg_data_dir
               functualize/_primitives/cache_format.py  find_functualize_dir  (walk C)
               functualize/_primitives/fresh_format.py  find_functualize_dir  (DUPLICATE)
               functualize/_config/merge.py         merge_config_layers  (root=true)
```

**Boundary crossings in the BEFORE.** All legal, and that is the problem: nothing
illegal is happening, so no contract catches it. The loader never asks anyone for
the directory — it invents one. Two resolvers exist on opposite sides of a wall
neither may cross, and the wrong one runs.

---

## 4. AFTER

```
LAYER          MODULE
─────────────────────────────────────────────────────────────────────────────────

PUBLIC         functualize/app/utils.py  (≈ -220 LOC)
               ├── resolve_project_config          ─┐
               ├── resolve_effective_directories    │  thin wrappers, signatures
               ├── _collect_convention_directories   │  unchanged → all 21 tests
               ├── resolve_user_config_dir          ─┘  stay green (AC-14)
               └── auto_discover                        unchanged; DiscoveryResult
                        │                               NOT widened (schema.md §4.1)
                        │ imported by
                        ▼
INTERNAL       functualize/_cli/main.py
               (unchanged)

                    the wrappers delegate to
                    ┌───────────────────────
                    ▼
PEER LAYER     functualize/_config/project_dirs.py   ★ NEW — THE ONE RESOLVER
               ├── PROJECT_CONFIG_CANDIDATES
               ├── resolve_project_config()      anchor + merge_config_layers
               ├── collect_convention_directories()
               ├── resolve_effective_directories()   CLI+ENV+File+Conv+Global
               └── resolve_plugin_directories()   ★ declared + convention,
                         ▲         ▲                 convention anchored on walk C
                         │         │
          imports        │         │  imports        (both legal: public→internal,
          (public→       │         │   composition    composition root→peer)
           internal)     │         │   root→peer)
                         │         │
COMPOSITION    functualize/_app/boot.py
ROOT           boot_standard
                 step 2   config_registry = ProviderRegistry()
                 step 3.5 ★ project = resolve_project_dirs(app)   ── ONE read
                 step 4   plugin_loader.load_all(              │
                              app, directories=project.plugin_dirs, ...)
                 step 4b  boot_domain_registry(app, config=project.merged)
                 step 6   app._resolution_chain = ...   (unchanged)
                              │                    │
                              │ list[str]          │ dict
                              ▼                    ▼
PEER LAYER     _plugins/loader.py        _plugins/domain_registry.py
               PluginLoader (≈435 LOC)   _read_configured_provider(config, metadata)
                 load_all(directories=…)   ← no hasattr, no app reach
                   └─ self._file_source.discover(directories)
                                │
               ★ _plugins/file_source.py  (NEW, ≈170 LOC)
                 FilePluginSource
                   ├── discover(directories) -> list[plugin]
                   ├── _load_file_plugin
                   └── _find_plugin_in_module

               ── _plugins/ imports NOTHING from _config/ ──
                  it receives list[str] and dict; peer independence intact

FOUNDATION     functualize/_primitives/locator.py
               ├── ResourceLocator                    (unchanged)
               ├── _xdg_data_dir                      (unchanged)
               └── xdg_config_dir()  ★ moved down from app/utils.py
               functualize/_primitives/cache_format.py  find_functualize_dir (walk C)
               functualize/_config/merge.py             merge_config_layers  (root=true)
```

### 4.1 The edge that makes it work

The loader stops *asking* and starts *receiving*:

```
BEFORE   loader ──reaches for──► app._resolution_chain   (absent)
                 ──reaches for──► app._plugin_sources    (present, but not its business)
                 ──invents──────► Path.cwd()/.functualize/plugins

AFTER    boot ───resolves───────► _config/project_dirs
         boot ───passes list────► loader
```

One arrow reversed. That is the whole architectural change; everything else is
consequence.

### 4.2 Contract check — `uv run lint-imports`

| New edge | Contract | Legal? |
|---|---|---|
| `app/utils.py` → `_config/project_dirs` | *Internal never imports public* — wrong direction, not triggered. `app/utils.py` already imports `_config.merge:24` | ✅ |
| `_app/boot.py` → `_config/project_dirs` | composition root may import any peer; already imports `_config.chain:43` | ✅ |
| `_config/project_dirs` → `_primitives/locator`, `_primitives/cache_format` | foundation, downward | ✅ |
| `_config/project_dirs` → `_config/merge` | same layer | ✅ |
| `_plugins/loader` → `_config/*` | **would violate** *Peer layers are independent* | ❌ — **and is not in the AFTER.** The loader receives `list[str]`. |
| `_plugins/file_source` → stdlib only | — | ✅ |
| `_primitives/locator.xdg_config_dir` | *Primitives import nothing internal* — stdlib `os`/`pathlib` only | ✅ |

Gate: AC-13.

---

## 5. Why not the two alternatives

**Rejected — extract into `_primitives/`.** `_primitives` may import nothing
internal, but the resolver needs `merge_config_layers`, which lives in
`_config/merge.py`. That would force `merge.py` to move too, dragging
`root = true` semantics out of the configuration layer for no reason beyond
placement. `_config/` is where "resolve declared configuration" belongs.

**Rejected — `_app/boot.py` does a minimal raw TOML read of its own.** This is
the bug report's first suggested fix. It manufactures a *third* resolver with a
fourth stop rule, and fails AC-9 by construction. The reason the option is
tempting is the reason it is wrong: it is local, and locality is what produced
two divergent copies in the first place.

**Rejected — pass directories through `PluginSources`.** `contracts.md` freezes
that dataclass, it would not help a programmatic `FunctualizeApp(name="x")`
(which never runs walk A — AC-9b), and it makes the caller responsible for
resolution the framework should do.

---

## 6. Technical approach

### 6.1 The one read, at boot step 3.5

`boot_standard` resolves the project's declared directories **once**, after the
provider registry exists and before plugins load, and hands the result to the two
consumers that need it. Extracted into its own function rather than inlined —
`boot_standard` is already ~400 LOC and a *long method*; adding 25 lines to it
would deepen a smell this plan is otherwise reducing.

### 6.2 Convention directories anchor on walk C

Measured in `research.md` §6.2: walk A collects convention directories only from
levels that produced a **config hit**, so `02_multi/` — which holds
`.functualize/plugins/` but no config file — is skipped. `find_functualize_dir`
(walk C) finds it, and is already what the app reports as `Mode: project`.

`resolve_plugin_directories()` therefore composes two sources:

1. **declared** — `effective["plugins_directories"]` from walk A, in precedence order;
2. **convention** — `find_functualize_dir(cwd) / "plugins"`, appended, unless
   `ambient_directory` is `False`.

Declared first, convention second (`spec.md` §C.2). The existing first-wins
duplicate-name rule then applies across both, unchanged.

### 6.3 `ambient_directory` is applied by boot

The switch stays on `PluginSources` (frozen by `contracts.md`) but is read where
the list is assembled, not inside the loader. This deletes the loader's second
reach into `app` and makes AC-5 a property of one function.

### 6.4 `directories=None` means no file discovery

`load_all(app)` with no `directories` scans nothing. Today the same call reaches
`Path.cwd()`, which makes ~35 unit tests quietly dependent on the working
directory. Making the parameter explicit removes that coupling; it is a
testability improvement, not only a refactor.

### 6.5 The domain registry takes the merged config

`_read_configured_provider(config: dict, metadata)` — a plain dict lookup of
`config[metadata.config_section]["provider"]`, no `app`, no chain, no guard.
`boot_domain_registry` receives the same `project.merged` dict boot already has.

**Disclosed narrowing:** this reads File + Convention + Global, not CLI or Env.
The full chain does not exist at step 4b and cannot without breaking ADR-007.
Today the value is `None` **always**, so every project gains; none loses. Marked
`# TRANSITIONAL` per the constitution if a later feature wants the CLI rung.

### 6.6 `FilePluginSource` — Extract Class

`PluginLoader` is 595 LOC against the constitution's *"if a class exceeds ~500
LOC, decompose it"*. Deleting `_resolve_plugin_directories` alone leaves it at
553 — **still a Forbidden Pattern**, which the gate says may not survive into the
AFTER. Moving the three file-scanning methods out brings it to ≈435.

This is not opportunistic: those are exactly the methods this feature rewrites,
and `_find_plugin_in_module` already uses `self.` zero times while
`_load_file_plugin` uses it once.

---

## 7. Code smells

### 7.1 Named in the BEFORE (gate step 1)

| Smell | Where | Evidence |
|---|---|---|
| **Feature Envy** | `_plugins/loader.py:709-750` `_resolve_plugin_directories` | `self.` used **0 times**; reads `app._resolution_chain`, `app._plugin_sources`, `Path.cwd()`. Routing: *Move Method*. |
| **Feature Envy** | `_plugins/domain_registry.py:315-339` `_read_configured_provider` | Same shape, same fix. |
| **Duplicate Code** (subtle — *"looks different but performs the same job"*) | `app/utils.py` vs `_plugins/loader.py` | Two resolvers for `plugins_directories`, already diverged; the divergence **is** the bug. |
| **Duplicate Code** (obvious) | `_primitives/cache_format.py:289` and `_primitives/fresh_format.py:108` | `find_functualize_dir` byte-identical in two modules. |
| **Large Class** | `_plugins/loader.py` `PluginLoader` | 595 LOC vs the ~500 bar. Routing: *Extract Class*. |
| **Long Method** | `_plugins/loader.py:309-649` `load_all` | 341 LOC. Routing: *Extract Method*. |
| **Long Method** | `_app/boot.py:486-885` `boot_standard` | ~400 LOC. |
| **Divergent Change** | `app/utils.py` | 2380 LOC changing for discovery, config, vault, cache, agent skills and CLI helpers. |
| **Dead Code** | three sites | the `hasattr` branch; `effective["plugins_directories"]` in `auto_discover`; `resolve_effective_directories` with 0 production callers against 21 tests. |
| **Hard-coded config path** (*Forbidden Pattern*, `.spec/CONSTITUTION.md:94`) | `loader.py:747` | `Path.cwd()/".functualize"/"plugins"` — the constitution's stated cure is *"`ResourceLocator` handles discovery; use it"*. |

### 7.2 Introduced by the AFTER (gate step 4)

Checked explicitly, because this is what the loop is for.

| Candidate smell | Verdict |
|---|---|
| **Shotgun Surgery** — does adding a directory key now touch more places? | **No.** Today: two resolvers plus the loader = 3 edit sites. After: `_config/project_dirs.py` = 1. Strictly fewer. |
| **Middle Man** — are `app/utils.py`'s wrappers empty shells? | **Watched, and accepted with a bound.** Four functions become thin delegators. This is deliberate: they are the *public* surface with 21 tests against them, and keeping them is what makes AC-14 achievable without rewriting tests that are not this feature's subject. Not *Remove Middle Man*, because the delegate is in an internal package users may not import. Declared in §8. |
| **Lazy Class** — is `FilePluginSource` too small to earn its keep? | **No.** ≈170 LOC, three methods, its own reason to change (the file-plugin file format), and it takes `PluginLoader` under the god-object bar. |
| **Divergent Change** — does `_config/project_dirs.py` become a new grab-bag? | **No.** One axis: "where do declared project directories resolve to". |
| **Speculative Generality** — an unused `DiscoveryResult.plugins_directories` field | **Caught and removed during the gate.** The first draft added it to close `research.md` §2.1a. With boot calling the resolver directly, nothing consumes it. `schema.md` §4.1 records the reversal. |
| **Long Method** — does `boot_standard` grow? | **No**, by construction — §6.1 puts the new step in its own function, one call line in `boot_standard`. |

### 7.3 Forbidden Patterns — status in the AFTER

| Pattern | BEFORE | AFTER |
|---|---|---|
| God object > ~500 LOC | ❌ `PluginLoader` 595 | ✅ ≈435 |
| Hard-coded config paths | ❌ `loader.py:747` | ✅ removed |
| Peer-layer cross-imports | ✅ none | ✅ none — loader receives data |
| `_cli/` importing internals | ✅ none | ✅ unchanged |
| ABC for ports / implicit `Callable` ports | ✅ none | ✅ none — a `list[str]` is data, not a port |
| Global mutable state | ✅ none | ✅ none |
| `DeprecationWarning` / compat shims | ✅ none | ✅ none |

**No Forbidden Pattern survives into the AFTER.** Two are removed.

---

## 8. Surviving smells

Two survive; a third was fixed instead. All are outside the *Forbidden Patterns*
list and therefore eligible to be accepted. Both review flags were put to the
maintainer on 2026-09-18 and answered — §8.2 accepted, §8.3 fixed.

### 8.1 Middle Man — `app/utils.py`'s four delegating wrappers

`resolve_project_config`, `resolve_effective_directories`,
`_collect_convention_directories` and `resolve_user_config_dir` become thin
forwarders to `_config/project_dirs.py` and `_primitives/locator.py`.

**Why accepted.** They are the public surface. `resolve_effective_directories` is
in `app/utils.__all__` and carries 20 tests; `_cli/` may reach the public API and
nothing else, so deleting the wrapper would either break `_cli/` or force the
resolver back into the public layer where `_app/` cannot see it. The delegation
is the layer boundary doing its job, which the catalogue explicitly excludes from
*Remove Middle Man*.

**Does not need maintainer review.** Bounded at four functions and reversible.

### 8.2 Long Method — `PluginLoader.load_all` stays at ≈341 LOC

`Extract Class` removes file *discovery* from the class but not length from this
method: `load_all` is entry-point loading, merge, topological sort, registration
and instrumentation in one body.

**Why accepted.** Decomposing it is a larger, independent refactor with a
different blast radius (38 `load_all(` test call sites across 6 files,
blast-radius pass §9.3), and doing it inside a bug fix would make the diff
impossible to review against the acceptance criteria. Not a Forbidden Pattern —
the constitution names god *objects*, not long methods.

**✅ Reviewed and accepted — maintainer, 2026-09-18: "let the long method."**
Not carried as a follow-up task. If it is taken later it is a feature of its
own, and this entry is the record that it was seen and left deliberately.

### 8.3 ~~Duplicate Code — `find_functualize_dir`~~ — FIXED, not survived

**Maintainer decision, 2026-09-18: "yes do it, remove one."** Collapsed by
**T10**; it is therefore no longer a surviving smell and is recorded here only
so the decision is traceable.

**One non-obvious constraint, measured before the task was written.** The two
copies are not inert duplication — `tests/conftest.py:277-288`, the autouse
`_isolate_state_root` fixture, monkeypatches **`fresh_format`'s copy only**, to
redirect runtime state into `tmp_path`. `cache_format`'s copy is deliberately
left unpatched.

The collapse survives that fixture **iff `fresh_format.py` binds the name into
its own module namespace** (`from ... import find_functualize_dir`) and keeps its
call site unqualified — `monkeypatch.setattr(fresh_format, "find_functualize_dir", …)`
rebinds a module global, so an imported name is patchable but a qualified call
(`locator.find_functualize_dir(...)`) is not.

Getting that wrong fails in the worst available direction: the suite stays green
while tests write durable state **outside `tmp_path`**, which is the `-n auto`
flake the fixture was written to stop. T10's gate is that fixture, not the
line count.

### 8.4 Not accepted, explicitly

`app/utils.py` at 2380 LOC (*Divergent Change* / god module) is **reduced** by
≈220 LOC here but not resolved. It is not listed above as accepted because this
feature does not make it worse and does not claim to fix it; it is named so the
next reader knows it was seen.

---

## 9. Files to change

Each list is the hit set of the retrieval queries in §1 and the blast-radius
pass, not composed from memory.

### 9.1 Source — new

| File | Why |
|---|---|
| `src/functualize/_config/project_dirs.py` | The one resolver (§4) |
| `src/functualize/_plugins/file_source.py` | `FilePluginSource` (§6.6) |

### 9.2 Source — modified

| File | Change |
|---|---|
| `src/functualize/_plugins/loader.py` | delete `_resolve_plugin_directories`; move 3 methods out; `load_all(directories=…)` |
| `src/functualize/_plugins/domain_registry.py` | `_read_configured_provider(config, metadata)`; `boot_domain_registry(app, config)` |
| `src/functualize/_app/boot.py` | step 3.5 + pass-through to steps 4 and 4b |
| `src/functualize/app/utils.py` | four functions become wrappers. **`DiscoveryResult` is not changed** — see `schema.md` §4.1 |
| `src/functualize/_primitives/locator.py` | `xdg_config_dir()` moved down |
| `src/functualize/_config/__init__.py`, `src/functualize/_plugins/__init__.py` | exports |

### 9.3 Tests — the measured hit set

| File | Sites | Fate |
|---|---|---|
| `tests/plugins/test_resolve_plugin_directories.py` | 8 tests, 6 × `app._resolution_chain = chain_mock` | **deleted** — AC-10 requires zero. Replaced by booted-app tests. |
| `tests/plugins/test_file_plugin_edge_cases.py` | 5 `_resolve_plugin_directories` + 9 `_discover_from_files` | retarget to `FilePluginSource` |
| `tests/test_file_plugin_discovery.py` | 4 + 4 | retarget |
| `tests/plugins/test_load_all_file_discovery.py` | 0 + 7 | retarget |
| `tests/cli/test_single_file_cwd_isolation.py:286` | 1 direct call | rewrite through boot (AC-5) |
| `examples/plugins/file_based_plugin/tests/test_file_plugin.py:38-56` | mocks the dead branch *and* `chdir`s | rewrite (AC-12) |
| `tests/cli/test_effective_directories.py` (11), `tests/cli/test_convention_dirs.py` (9), `tests/test_auto_discover_bug_condition.py` (1) | 21 | **unchanged** — wrappers keep signatures (AC-14) |
| `tests/plugins/test_domain_registry.py` | integration tests | extend for AC-7 |
| `test_loader_props.py` (12), `test_loader.py` (10), `test_plugin_instrumentation.py` (9), `test_protocol_compliance_properties.py` (4), `test_loader_properties.py` (2), `test_file_plugin_discovery.py` (1) | **38 × `load_all(`** | **unchanged** — new param is keyword-only with a default |

**Measured, and a finding of its own:** the example test at
`examples/plugins/file_based_plugin/tests/test_file_plugin.py:40` imports
`functualize._plugins.loader` — an *example* reaching into an internal package,
then `chdir`-ing to make the cwd fallback fire and mocking
`app._resolution_chain.resolve.side_effect` to step over the dead branch. It is
three workarounds stacked on one bug. AC-12 replaces it with a booted app.

### 9.4 Docs

`docs/examples/plugins/file-based-plugin.md:21`,
`examples/plugins/file_based_plugin/README.md:32`,
`contributor/architecture/developer-modes.md:170` (AC-11);
`examples/plugins/file_based_plugin/.functualize.toml:11` (AC-12);
`CHANGELOG.md` (AC-15, AC-16);
`contributor/architecture/codemaps/` — `data-flow.md:12` and `dependencies.md`
via `/sync-docs`.

---

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Behaviour change for projects already declaring `[<domain>] provider`.** They have silently run on defaults; after the fix they get what they asked for. | Same class as the `functualize-ai` precedent, accepted on those terms. AC-7 + a CHANGELOG entry. |
| R2 | **A declared directory now executes code that previously did not run.** File plugins are arbitrary local Python. | Trust model unchanged for *declared* paths — declaring is consent. The *convention* search is bounded at the project root (AC-3b), so the widening is one directory → the project, not → `/`. |
| R3 | **`directories=None` silently disables file discovery** where a test or embedder relied on the cwd fallback. | Grep-able change; ~35 call sites enumerated in §9.3; AC-2 is the regression gate. |
| R4 | **Extract Class churns 17 test sites** while the feature is a bug fix. | Done as its own wave, after the behaviour is green, so a bisect separates "fixed the bug" from "moved the code". |
| R5 | **`app/utils.py` wrappers drift from the resolver.** | The wrappers contain no logic; the 21 existing tests run against the real implementation through them. |
| R6 | **Concurrent commits on this branch.** HEAD moved `e4eb3e5 → 63d5b30` during Specify, and `app/utils.py` line numbers shifted. | Every reference re-verified at `63d5b30`; tasks cite symbols, not line numbers. |

---

## 11. What this plan sends back to Specify

Nothing. The architecture gate confirmed `spec.md`'s decomposition rather than
contradicting it — the one substantive change (convention directories anchor on
walk C, not on walk A's config-hit list) was already folded into `spec.md` §C.3
and AC-3b during Specify, from the same measurement.

The gate did add work the spec did not name: **`FilePluginSource`**, forced by a
Forbidden Pattern (`PluginLoader` > 500 LOC) that survives even after the
feature's own deletions. That is architecture, not scope creep, and §7.3 is the
justification.
