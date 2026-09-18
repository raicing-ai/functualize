# Research — `declared-plugin-directories`

Source: a field bug report filed against installed `0.2.3`, re-verified by the
reporter against `0.3.0`. Every claim below was **re-run against this branch**
(`feat/plugin-host-protocol`, `e4eb3e5`, `pyproject.toml version = "0.3.0"`)
before it was written. Commands are quoted so each line can be falsified.

---

## 1. The report is accurate, and the defect is live on this branch

### 1.1 The guard still exists, unchanged

`src/functualize/_plugins/loader.py:726`

```python
if hasattr(app, "_resolution_chain"):
    try:
        resolved = app._resolution_chain.resolve(
            "plugins_directories", "tool.functualize"
        )
```

One difference from the report's quotation: a `PluginSources.ambient_directory`
gate was added between the config read and the convention fallback
(`loader.py:743-745`, from `single-file-cwd-isolation`). It does not touch the
config branch — the comment there says so explicitly: *"The config-read above is
unaffected — a declared directory stays declared."* That comment is **false
today**, which is itself part of the finding.

### 1.2 `hasattr` is `False` at plugin-load time — measured, not read

Probe (monkeypatched `_resolve_plugin_directories`, real `FunctualizeApp`):

```
AT PLUGIN-LOAD TIME: {'hasattr_resolution_chain': False, 'type': 'FunctualizeApp', 'result': []}
AFTER BOOT hasattr(_resolution_chain): True
```

The attribute is a **bare annotation** on the class
(`src/functualize/app/core.py:126`), and the surrounding comment states the
intent outright:

> These are bare annotations on purpose: they declare a type without creating a
> class attribute, so runtime behaviour (including `getattr(app, name, default)`
> and `hasattr`) is exactly as before.

So the annotation does not rescue the guard, by design.

### 1.3 Boot ordering is as reported

`src/functualize/_app/boot.py`, `boot_standard`:

| Step | Line | What |
|---|---|---|
| 2 | 700-712 | `ProviderRegistry` + TOML provider (ADR-007) |
| **4** | **719-736** | **`app.plugin_loader.load_all(...)`** — "Load plugins EARLY" |
| 4b | 739-744 | `boot_domain_registry(app)` |
| 6 | 753-805 | `app._resolution_chain = build_resolution_chain(...)` |

The ordering is deliberate and documented in-source at `boot.py:705-707`:

> A plugin is the escape hatch: boot loads plugins before it builds the chain,
> precisely so they can register formats. See ADR-007.

`contributor/adr/007-toml-only-config-formats.md` confirms this is an accepted
decision, not an accident. **The ordering is not the thing to change.**

### 1.4 The config branch is unreachable in production — one call site

```
$ rg -n "\.load_all\(" src/ plugins/ examples/
src/functualize/_app/boot.py:724:    app.plugin_loader.load_all(
count: 1
```

`_discover_from_files` (and therefore `_resolve_plugin_directories`) has exactly
**one** production entry point, and it is the one that runs before the chain
exists. `refresh()` does not re-open it — `_app/impl.py:1256`: *"It does not
re-run plugin boot."* `boot_static` loads only explicit plugin objects
(`boot.py:421`, "no entry-point discovery, no file discovery").

So the branch is not "rarely taken". It is **dead**.

### 1.5 End-to-end reproduction, run on this branch

Fixture (`$SCRATCH/repro/`), a file plugin printing `HELLO_WORLD_PLUGIN_REGISTERED`
from its `__call__`:

```
02_multi/
├── .functualize/plugins/hello_world_plugin.py
└── hello_app/
    ├── pyproject.toml        # [tool.functualize] plugins_directories = ["<abs>/02_multi/.functualize/plugins"]
    └── jobs/sample.py        # job `hello`
```

| Case | Command | cwd | Marker printed? |
|---|---|---|---|
| **A** | `func hello` | `02_multi/hello_app` | **no** (exit 0) |
| **B** | `func --discovery-depth 5 hello` | `02_multi` | **yes** |

Case A is the bug: the declared directory is ignored. Case B is the reporter's
workaround: the convention fallback fires only on an exact-CWD match.

### 1.6 The failure is silent — measured

```
$ func --log-level debug hello        # from 02_multi/hello_app
… Successfully loaded plugin 'flow-viz' (version 0.2.0)
… Successfully loaded plugin 'mcp' (version 0.1.0)
…
$ func --log-level debug hello 2>&1 | grep -c "plugins_directories"
0
```

At `DEBUG`, the *most verbose level the CLI offers*, the string
`plugins_directories` does not appear once. Six entry-point plugins are named;
the configured directory is not. Nothing distinguishes "no plugins found" from
"your configured directory was never consulted".

The `logger.debug("Could not resolve plugins_directories from config")` line at
`loader.py:736` is inside the `hasattr` block, so it cannot fire either.

---

## 2. What the report did not find

### 2.1 The value is already resolved correctly — twice — and then dropped

`src/functualize/app/utils.py` carries a complete, upward-walking resolver for
exactly this key, with the full precedence chain
(`CLI + ENV + File + Convention + Global + Defaults`, `utils.py:628`):

- `resolve_effective_directories()` (`utils.py:617`) — public, exported in
  `__all__` (`utils.py:283`).
- `_collect_convention_directories()` (`utils.py:820`) — docstring: *"Detect
  convention directories at each level of **the upward walk**"*, and it maps
  `.functualize/plugins/ → "plugins_directories"` (`utils.py:829, 846`).
- `auto_discover()` (`utils.py:1236`) — self-described *"Single source of
  truth"*, uses `ResourceLocator().search_upward()`, and computes
  `effective["plugins_directories"]` in **both** its branches (`utils.py:1322`,
  `utils.py:1370`).

Two things follow.

**(a) `auto_discover` computes the value and throws it away.** `DiscoveryResult`
(`utils.py:348-362`) has fields `anchor`, `job_sources`, `import_libs`,
`merged_config`, `jobs_directories` — and **no** `plugins_directories`. The key
is resolved into `effective` and never read out. A second dead path.

**(b) The CLI reports a number the loader does not obey.**
`resolve_effective_directories` has **zero production callers** —
`rg -n "resolve_effective_directories" --type py` outside `app/utils.py` returns
only `tests/`. But it is asserted on by 20 test cases across
`tests/cli/test_effective_directories.py` (11) and `tests/cli/test_convention_dirs.py` (9),
including `test_plugins_directories_with_convention` — a fully green test
describing behaviour no production caller can observe.

So the framework contains a *correct* upward-walking resolver for
`plugins_directories`, and the plugin loader re-derives the same key from a
different source that does not exist yet. That is the shape of the problem —
**duplicated, divergent resolution of one concept**, not a missing feature.

### 2.2 Something *does* walk upward at boot — visibly

In reproduction case A, run from `02_multi/hello_app`, the debug log shows:

```
substrate-sqlite installed a substrate at …/02_multi/.functualize/state.db
```

The anchor `02_multi/.functualize/` was found from a subdirectory. Anchor
resolution already walks up at boot; the plugin loader is the component that
does not use it.

### 2.3 The same defect exists a second time, in `_plugins/domain_registry.py`

`src/functualize/_plugins/domain_registry.py:327`

```python
if not hasattr(app, "_resolution_chain") or app._resolution_chain is None:
    return None
```

`_read_configured_provider` has one caller (`domain_registry.py:282`), reached
from `boot_domain_registry` — **boot step 4b**, still before step 6. Measured on
a live app:

```
boot_domain_registry (step 4b) hasattr(_resolution_chain): {'hasattr_at_4b': False}
_read_configured_provider calls, hasattr each: [False, False]
```

So `[<domain>] provider = "..."` has **never** been read either. Same root
cause, same silence, different key.

Census of the pattern (`rg -n 'hasattr\(app, "_resolution_chain"\)|getattr\(app, "_resolution_chain"' src/`) — **4 sites**:

| Site | When it runs | Verdict |
|---|---|---|
| `_plugins/loader.py:726` | boot step 4 | **broken** — always `False` |
| `_plugins/domain_registry.py:327` | boot step 4b | **broken** — always `False` |
| `_app/boot.py:239` | engine construction, `getattr(..., None) or ResolutionChain([])` | degrades to an empty chain by design; the engine reads config *through the host* later (`boot.py:818-821`) |
| `app/utils.py:2246` | post-boot (`declared_config_values`) | fine |

### 2.4 Prior art: this exact class of bug was found and fixed once already

`plugins/…/functualize-ai/src/functualize_ai/_provider_discovery.py`,
`_ai_config_from`, docstring:

> **This used to be unreachable.** The guard read `hasattr(app, "resolve_model")`,
> and `resolve_model` lives on `app.configuration` — never on the app itself.
> Verified against a live app rather than read off the source … So the branch was
> always False, the `[ai]` section had **never** been read here, and every caller
> passing an `app` silently received `AIConfig()` defaults.

`.spec/STATE.md:527-531` records it as a maintainer-routed finding
(2026-09-17). The repo has already decided how this class is handled: **the
guard is the bug, the fix changes behaviour, and it is verified against a live
app rather than read off the source.** This feature follows that precedent
rather than inventing one.

### 2.5 Three documents assert the broken path as working

```
$ rg -n "plugins_directories\`? if configured|\[tool.functualize\] plugins_directories" docs/ contributor/ examples/ README.md
docs/examples/plugins/file-based-plugin.md:21
examples/plugins/file_based_plugin/README.md:32
contributor/architecture/developer-modes.md:170
```

All three say the loader resolves `[tool.functualize].plugins_directories` *"if
configured, else the convention directory"*. None of them is true.

A fourth document steers *around* the defect without naming it —
`examples/plugins/file_based_plugin/.functualize.toml:11`: *"`plugins_directories`
is deliberately NOT set. Leaving it unset is what makes the loader fall back to
the convention directory."* The one working example avoids the broken option.

### 2.6 The existing unit tests are green because they manufacture the missing attribute

`tests/plugins/test_resolve_plugin_directories.py` — 8 tests. Every test that
exercises the config branch builds the state production never produces:

```python
app = MagicMock()
app._resolution_chain = chain_mock
```

That line appears **6 times** in the file. The three tests covering the
convention path use `MagicMock(spec=[])` — "no `_resolution_chain` attribute" —
which is, accurately, the real boot condition. So the suite already encodes the
truth in one half and contradicts it in the other, and passes either way.

This is why the bug survived two releases with full coverage: no test boots an
app.

---

## 3. Constraints any fix must respect

### 3.1 The boot ordering is fixed by ADR-007

Plugins load before the chain so they can register config **format providers**.
Moving `load_all` after step 6 would revoke the documented escape hatch. The fix
must therefore bring the *value* earlier, not push the *load* later.

### 3.2 The layer contract forbids the obvious shortcut

`src/functualize/_plugins/loader.py:11` — *"Only imports from `_types/`,
`_primitives/`, `_events/`, and Python stdlib."*

`pyproject.toml` contract **"Peer layers are independent"** (line 244) lists
`_discovery`, `_config`, `_engine`, `_plugins`, `_gate`. And **"Internal never
imports public"** (line 303) forbids `_plugins → functualize.app`.

So the loader may **not** import `_config/` and may **not** import
`app/utils.py`, where the working resolver lives. Legal ground for a shared
resolver is `_primitives/` — which already hosts `ResourceLocator`
(`_primitives/locator.py:74`), the upward-walk primitive `auto_discover`
itself uses, and which "imports nothing internal" (contract, line 274).

### 3.3 `PluginSources.ambient_directory` must keep working

`single-file-cwd-isolation` set `PluginSources(ambient_directory=False)` for
`func <file>.py <job>` (`_cli/main.py:1730`) so a neighbour's
`./.functualize/plugins/` cannot hijack a named file. Its stated line is *"a
**declared** `plugins_directories` is untouched"* — which this feature is what
finally makes true. Widening the convention fallback to an upward walk without
respecting that switch would re-open the hijack this test guards
(`tests/cli/test_single_file_cwd_isolation.py:204-250`).

---

## 4. The reporter's second observation (`app.before_job`) — verified, and separable

Measured on a live app built from this branch:

```
has app.before_job: False
has app.hooks: True
has app.hooks.before_job: True
type(app.hooks): HooksFacade
```

- `HooksFacade` is `src/functualize/_app/hooks_facade.py:33`; `before_job` is a
  property at line 65 returning the decorator.
- The move was **intentional and marked breaking**: `d8f0809 refactor(app)!: six
  facades take FunctualizeApp from 71 public members to 37 (T9)`.
- A plugin whose `__call__` raises is caught and logged as a per-plugin
  `logger.warning` (`_plugins/loader.py:620-623`), so boot continues without
  it — the reporter's "silently-ish" is accurate.
- **`CHANGELOG.md` does not document it.** `grep -n -i "facade\|public members"
  CHANGELOG.md` → 0 hits; `grep -n -i "app.hooks\|HooksFacade"` → 0 hits. A
  breaking rename of a public registration API shipped in `0.3.0` with no
  changelog entry and no migration note.

This shares *nothing* mechanically with the directory bug — different module,
different cause, different fix. It is written up here so the finding is not
lost, and is put to the maintainer as a scope question rather than folded in.

---

## 5. The discovery walks — measured map

Added 2026-09-18 after the maintainer asked how `.functualize/` and config files
are actually found. This section is the reason §6 re-cuts the approach.

**There are four independent upward walks, with three different stop rules.**

| | What it finds | Starts at | Stops at | Honours `root = true`? |
|---|---|---|---|---|
| **A. Project config** | `.functualize.toml` / `pyproject.toml` | cwd | filesystem root | ✅ |
| **B. Chain config files** | `config.<env>.<ext>` | cwd | **`$HOME`** | ❌ |
| **C. `.functualize/` runtime anchor** | the `.functualize/` *directory* | cwd | filesystem root | ❌ |
| **D. Plugin directories** | `.functualize/plugins/` | — | **does not walk** | — |

### 5.1 Walk A — project config

`app/utils.py:1291` — `ResourceLocator().search_upward(start=cwd)`, no `stop`,
no `marker`, so it climbs to `/`. Per directory it tries three candidates
(`utils.py:635-639`), first hit wins at that level:

1. `pyproject.toml` → `[tool.functualize]` (via `_extract_functualize_section`)
2. `.functualize.toml` — keys at the root, no wrapper
3. `.functualize/.functualize.toml`

Every level that hits becomes a layer; `merge_config_layers` deep-merges them
nearest-first. The **anchor** is the nearest hitting directory, and relative
paths resolve against it.

### 5.2 Walk B — the resolution chain

`_app/boot.py:888`, `discover_config_path`. Separate machinery, and it looks for
different files: the default pattern is

```python
file_pattern: str = r"^config\.(\w+)\.(\w+)$"     # config.dev.toml
```

So **walk B never looks at `.functualize.toml` or `pyproject.toml`.** It stops
at `$HOME` and falls back to `~/.config/<app_name>`. Since ADR-007 a candidate
must also carry an extension a registered format provider handles; rejects are
collected into `unreadable` and warned about at boot.

This is why `builtin info` printed `No config files found.` in the reproduction
while `[tool.functualize]` was populated and being read: walk A found it, walk B
was not looking for it.

### 5.3 Walk C — the `.functualize/` runtime anchor

`find_functualize_dir` — walks up for a `.functualize/` **directory**, no
`$HOME` stop, no `root` key. Decides project-vs-standalone mode and where
`fresh.json`, `scopes.json` and `cache.json` live; standalone falls back to
`~/.cache/functualize/<project_id>/`.

**Implemented twice, byte-identical**: `_primitives/cache_format.py:289` and
`_primitives/fresh_format.py:108`. Noted, not this feature's to fix.

### 5.4 `root = true`

`_config/merge.py:33-105`, explicitly modelled on EditorConfig
(`merge.py:44`). The key is stripped from the merged output.

Measured on `walk/top/mid/leaf`, config at `top` and `mid`, starting from `leaf`:

| `mid/.functualize.toml` | merged result |
|---|---|
| without `root = true` | `{'jobs_directories': ['mid_jobs'], 'import_libs': ['top_lib']}` |
| with `root = true` | `{'jobs_directories': ['mid_jobs']}` |

**It affects walk A only.** Walks B and C never consult it.

### 5.5 XDG is a source, not a rung of the ladder

XDG is appended *after* the walk, and the two mechanisms disagree about which
XDG directory that is:

| Call | Location | Used by |
|---|---|---|
| `search_platform_user()` (`locator.py:167`) | `~/.local/share/functualize/` — XDG **data** | walk A's locator, walk B's chain |
| `resolve_user_config_dir()` (`utils.py:1033`) | `~/.config/functualize/config.toml` — XDG **config** | `resolve_effective_directories`'s *Global* layer |

Precedence for list keys is `CLI + ENV + File + Convention + Global + Defaults`
(`utils.py:631`), where *Global* is the `~/.config` one.

**`root = true` stops the directory walk but does not block the XDG layer.**
Measured, with `root = true` set in `mid/` and
`~/.config/functualize/config.toml` declaring `plugins_directories`:

```
merged file layers            -> {'jobs_directories': ['mid_jobs']}
effective plugins_directories -> ['/opt/org-wide-plugins']
```

An org-wide plugin directory therefore resolves correctly today, all the way
through the precedence chain — and is then discarded, because nothing hands it
to the loader.

---

## 6. Reusing walk A — what it gives, and the gap it does not close

**Maintainer decision, 2026-09-18: reuse walk A rather than give the loader a
fifth stop rule.** This section measures exactly what that buys.

### 6.1 The declared half: walk A already answers it

Run against the reproduction fixture, from `02_multi/hello_app`:

```
anchor        -> …/02_multi/hello_app
merged keys   -> ['plugins_directories', 'jobs_directories']
declared dirs -> ['…/02_multi/.functualize/plugins']
effective     -> ['…/02_multi/.functualize/plugins']
```

`resolve_effective_directories` returns the declared directory **correctly**,
with the anchor, the merge, `root = true` and the XDG layer all applied. Nothing
needs inventing. The only missing step is handing the value to the loader.

### 6.2 The convention half: walk A does **not** reach a config-less level

`auto_discover` does not feed `_collect_convention_directories` the walk. It
feeds it only the levels that produced a **config hit** (`utils.py:1311-1316`):

```python
walk_directories = [directory for (directory, _config) in results]
if cwd not in [d.resolve() for d in walk_directories]:
    walk_directories.insert(0, cwd)
convention_dirs = _collect_convention_directories(walk_directories)
```

Measured on the fixture, where `02_multi/` holds `.functualize/plugins/` but no
config file:

```
levels with a config hit  -> ['…/02_multi/hello_app']
convention dirs collected -> []
```

and yet, handed the directory directly, the collector finds it:

```
_collect_convention_directories([Path('…/02_multi')])["plugins_directories"]
  -> ['…/02_multi/.functualize/plugins']
```

So walk A and walk C hold **two different definitions of "this level belongs to
the project"** — walk A says *a config file lives here*, walk C says *a
`.functualize/` directory lives here*. In the reproduction they disagree, and the
plugin loader is downstream of the one that says no.

### 6.3 Consequence: the convention directory should anchor on walk C

The convention directory is by definition `<project root>/.functualize/plugins/`,
and walk C already computes `<project root>` — it is what `builtin info` prints:

```
Mode:  project (.functualize/ found at …/02_multi/.functualize)
```

Resolving the convention directory from `find_functualize_dir` rather than from
`Path.cwd()` fixes the reproduction, keeps one definition of the project root,
and **bounds the search at the first `.functualize/` found** — which answers the
trust-model concern in `spec.md` §E: the walk cannot climb past the project root
into arbitrary ancestors.

### 6.4 The second gap: `boot_standard` never runs walk A

```
$ rg -n "auto_discover" src/functualize/_app/
(no matches)
```

Walk A runs in `_cli/main.py` (3 sites) and `_cli/self_cmd.py` (1), not in boot.
A programmatic `FunctualizeApp(name="x")` — no CLI — never runs it at all. So
"reuse walk A" cannot mean "the loader calls `auto_discover`":

- `_plugins/` may not import `functualize.app.utils` (import-linter *"Internal
  never imports public"*), and
- the CLI's result does not currently reach boot.

Both are Plan's to resolve. The shape the spec fixes is: **one resolver, walk A's
semantics, reachable from boot without a layer violation** — most likely by
extracting walk A's directory resolution into `_primitives/` (where
`ResourceLocator` and `find_functualize_dir` already live and where `_plugins/`
may legally reach) and having both `app/utils.py` and the loader call it.
