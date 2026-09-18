# Spec — `declared-plugin-directories`

**Status:** Specify — awaiting maintainer confirmation
**Branch:** `feat/plugin-host-protocol` (base `master`)
**Origin:** field bug report against `0.2.3`, re-verified by the reporter
against `0.3.0`, re-verified here against this branch. Evidence, commands and
measurements: [`research.md`](research.md).

---

## A. Problem

### A.1 What a user does, and what happens

A project declares where its file-based plugins live:

```toml
# hello_app/pyproject.toml
[tool.functualize]
plugins_directories = ["/srv/02_multi/.functualize/plugins"]
```

Nothing loads. No error, no warning, and at `--log-level debug` — the most
verbose level the CLI offers — the string `plugins_directories` does not appear
once in the output. Six entry-point plugins are named by the log; the directory
the user declared is not mentioned at all.

The option is not merely broken. It is **unreachable**: the code that reads it
is guarded by `hasattr(app, "_resolution_chain")`, which is `False` every time
that code runs, on every production path. Measured on a live app:

```
AT PLUGIN-LOAD TIME: {'hasattr_resolution_chain': False, 'result': []}
AFTER BOOT hasattr(_resolution_chain): True
```

The ordering that causes this is deliberate and documented (ADR-007): plugins
load at boot **step 4** so they can register config format providers; the
resolution chain is built at **step 6**. That ordering is correct and is not
what this feature changes.

### A.2 The only mechanism that works does not compose

With the declared option dead, file plugins load from exactly one place:
`Path.cwd() / ".functualize" / "plugins"` — an **exact** match on the current
working directory, with no upward walk. Every other anchored thing in this
framework walks up: config discovery, job discovery, and the state substrate.
In the same reproduction run, `substrate-sqlite` found `02_multi/.functualize/`
from two directories down while the plugin loader, in the same boot, saw
nothing.

So the common multi-app layout fails:

```
02_multi/
├── .functualize/plugins/shared_plugin.py
└── hello_app/               ← where you actually run `func`
    ├── pyproject.toml
    └── jobs/
```

| Case | cwd | Plugin loads? |
|---|---|---|
| A — `plugins_directories` declared | `02_multi/hello_app` | **no** |
| B — nothing declared | `02_multi` | yes |

Case B is the reporter's workaround, and it requires running `func` from a
directory that is not the project, with `--discovery-depth` raised so jobs are
still found. Declaring the directory — the documented, supported thing to do —
is the case that fails.

### A.3 The value is already resolved correctly, elsewhere, and thrown away

`src/functualize/app/utils.py` contains a complete resolver for this exact key,
with an upward walk and the full precedence chain
(`CLI + ENV + File + Convention + Global + Defaults`). It is used by nothing in
production:

- `auto_discover()` — self-described *"Single source of truth"* — computes
  `effective["plugins_directories"]` in both of its branches and never reads it
  out. `DiscoveryResult` has no field for it.
- `resolve_effective_directories()` is exported in `__all__` and has **zero**
  production callers, while 20 green tests assert its behaviour.

So there are two resolvers for one concept. The correct one is orphaned; the
one that runs asks a source that does not exist yet. The user-visible bug is a
symptom of that split, and a fix that only patches the loader leaves the split
in place.

### A.4 The same defect exists a second time

`_plugins/domain_registry.py:327` carries the identical guard, runs at boot step
4b — also before step 6 — and is also always `False`, measured:

```
_read_configured_provider calls, hasattr each: [False, False]
```

`[<domain>] provider = "..."` has therefore never been read either. Same root
cause, same silence, different key. This spec treats the defect as a **class**,
not a single site.

This is the third instance of the pattern in this repository. The first —
`functualize-ai`'s `hasattr(app, "resolve_model")`, always `False`, silently
returning `AIConfig()` defaults — was found, fixed, and recorded as a maintainer
decision (`.spec/STATE.md:527-531`). That precedent governs here.

### A.5 The documentation asserts the broken behaviour

Three documents state that the loader honours
`[tool.functualize].plugins_directories` *"if configured, else the convention
directory"*:

- `docs/examples/plugins/file-based-plugin.md:21`
- `examples/plugins/file_based_plugin/README.md:32`
- `contributor/architecture/developer-modes.md:170`

None is true. A fourth file steers around the defect without naming it:
`examples/plugins/file_based_plugin/.functualize.toml:11` — *"`plugins_directories`
is deliberately NOT set."* The repository's one working example avoids the
option this feature exists to make work.

### A.6 Why full coverage did not catch it

`tests/plugins/test_resolve_plugin_directories.py` has 8 tests. The 6 that
exercise the config branch construct the state production never produces:

```python
app = MagicMock()
app._resolution_chain = chain_mock
```

The 3 covering the convention path use `MagicMock(spec=[])` — "no
`_resolution_chain`" — which is the *real* boot condition. The suite encodes the
truth in one half and contradicts it in the other, and is green either way,
because **no test boots an app**.

---

## B. Scope

### B.1 In scope

1. A declared `plugins_directories` is honoured on the standard boot path.
2. Plugin directory resolution **reuses walk A** — the project-config walk that
   already resolves `jobs_directories` and `import_libs` — rather than keeping a
   fifth stop rule of its own. Maintainer decision, 2026-09-18. It comes with the
   anchor, the layer merge, `root = true` and the XDG *Global* layer already
   built (`research.md` §5-6).
3. The convention directory is anchored on the **project root that walk C
   already computes** (`find_functualize_dir`) — the same one `builtin info`
   prints as `Mode: project (.functualize/ found at …)` — not on `Path.cwd()`.
   This bounds the search at the first `.functualize/` and closes the
   disagreement measured in `research.md` §6.2.
4. When a directory is **declared** but yields nothing, the operator is told at
   `WARNING` — visible on a normal run, no flag required. An absent *convention*
   directory stays silent; it is the ordinary case.
5. `_plugins/domain_registry.py`'s identical guard is fixed in the same change,
   because it is the same defect and leaving it is knowingly shipping a known
   dead branch.
6. The three documents in §A.5 are corrected to describe what the code does.
7. Tests that prove the behaviour **through a booted app**, not through a mock
   carrying an attribute boot never sets.
8. A `CHANGELOG.md` entry for the `0.3.0` facade migration that removed
   `app.before_job` — carried here because it is a one-paragraph documentation
   fix with no code change, and opening a feature for it would cost more than
   writing it (maintainer, 2026-09-18). It is the only part of this spec that
   touches a subject other than plugin-directory resolution, and it is recorded
   as such rather than blended in.

### B.2 Out of scope

- **Changing the boot ordering.** ADR-007 fixes it. The value moves earlier;
  the plugin load does not move later.
- **The full resolution chain at plugin-load time.** Format providers registered
  by plugins must still be able to affect the chain, so the chain cannot be
  built before them.
- **`PluginSources.ambient_directory` semantics.** The `single-file-cwd-isolation`
  switch keeps its current meaning: `func <file>.py <job>` declines the *ambient*
  directory. A *declared* directory is unaffected — which is what its own
  comment already claims and this feature makes true.
- **Retiring `resolve_effective_directories` or reshaping `DiscoveryResult`**
  beyond what §B.1.2 requires.

### B.3 Decisions

**No open questions. Specify is complete.**

- ~~**OQ-1 — `app.before_job` → `app.hooks.before_job`.**~~ **Settled
  2026-09-18: a `CHANGELOG.md` entry, and nothing else.** The rename is intended
  and final; no deprecation shim, no code change. Verified: `app.before_job` is
  gone (`False` on a live app), the move was deliberate and marked breaking
  (`d8f0809 refactor(app)!: six facades take FunctualizeApp from 71 public
  members to 37`), a 0.2.x plugin fails with a per-plugin `logger.warning` and
  boot continues without it, and **`CHANGELOG.md` documents none of it** — 0
  hits for `facade`, `public members`, `app.hooks`, `HooksFacade`, and the
  branch's uncommitted `CHANGELOG.md` additions do not cover it either.

  The harm is not the rename; it is that nobody was told. See §B.1.8.

- ~~**OQ-2 — the diagnostic level.**~~ **Settled 2026-09-18: `logger.warning`
  for both cases** — a declared directory that does not exist, and one that
  exists but yields no loadable plugin. Visible on a normal run, no flag
  required. This follows the precedent already set at `_app/boot.py:775-786`
  for an unreadable config file, and for the stated reason: *"the operator who
  needs this most is the one running a job and getting the model default, who
  has no reason to suspect the config file they wrote is being ignored and no
  reason to go looking for a diagnostic command."*

  Applies to **declared** directories only. A convention directory that is
  absent is the ordinary case for most projects and stays silent.

- ~~**OQ-3 — the bound of the upward walk.**~~ **Settled 2026-09-18: reuse walk
  A, and anchor the convention directory on walk C's project root.** Declared
  directories inherit walk A's bound (filesystem root, `root = true` honoured,
  XDG *Global* appended); the convention directory stops at the first
  `.functualize/` found. Neither is a new rule. Rationale and the measurements
  behind it: `research.md` §5-6.

---

## C. Behaviour

Written as what an operator can observe. Mechanism is Plan's to decide.

### C.1 A declared directory is loaded

Given a project whose config declares `plugins_directories`, when the app boots
by any production path that discovers file plugins, each declared directory is
scanned and its plugins are registered — regardless of which directory the
process was started from.

Declared values resolve through walk A, so they arrive with its semantics
already applied: layers merged nearest-first across the upward walk, `root = true`
stopping that walk where a project declares itself self-contained, and the XDG
*Global* layer (`~/.config/functualize/config.toml`) as the lowest precedence
rung. An org-wide plugin directory declared there reaches a project that declares
none of its own.

Declared paths are honoured as written: absolute, relative to the config
anchor, and `..`-relative alike. (Consistent with ADR-013, which removed the
containment rule from declared `sources`/`generates` for the same reason: *"the
declaration a unit actually needs is expressible."*)

### C.2 Declared and convention compose

A declared directory does not *replace* the convention directory; both are
scanned, declared first. Today the config branch returns early, so a project
that declares one extra directory silently loses its own
`.functualize/plugins/`. That is a second, latent bug in the same function and
this spec closes it.

Order is declared-then-convention, and the existing duplicate-name rule is
unchanged: the first plugin loaded under a given name wins, later ones are
skipped with a warning.

### C.3 The convention directory is found at the project root

Absent any declaration, the convention directory is `<project root>/.functualize/plugins/`,
where `<project root>` is the directory walk C already anchors on — the first
ancestor holding a `.functualize/` directory. Running `func` from
`02_multi/hello_app` finds `02_multi/.functualize/plugins/`, the same directory
the app already reports in `builtin info` and already writes `fresh.json` into.

The search stops there. It does not continue past the project root, so a
`.functualize/plugins/` in a grandparent outside the project is not reached, and
a project with no `.functualize/` anywhere above it has no convention directory
rather than an arbitrary one.

### C.4 `ambient_directory=False` still declines the ambient directory

`func <file>.py <job>` continues to skip the convention directory — at every
level of the walk, not only the literal cwd. A *declared* `plugins_directories`
still loads.

### C.5 A declared directory that yields nothing is reported

When a directory is **declared** and it does not exist, or exists and contains
no loadable plugin, the operator is warned, naming the path — on a normal run,
without raising the log level. "No plugins found" and "the directory you named
was never consulted" become distinguishable without a diagnostic command.

A declaration is a statement of intent, so a declaration that produces nothing
is worth a line. The *convention* directory is a fallback nobody asked for, so
its absence is silent.

### C.6 A domain's configured provider is read

`[<domain>] provider = "..."` selects that provider at boot, as its
documentation already claims.

---

## D. Acceptance criteria

Each is a gate: a command that fails before the change and passes after.

| # | Criterion |
|---|---|
| **AC-1** | Reproduction case A passes. A project declaring `plugins_directories` in `pyproject.toml`, `func` run from a subdirectory, loads the plugin and its registration side effect is observed. Run end-to-end through the CLI, not through `_resolve_plugin_directories`. |
| **AC-2** | Reproduction case B still passes. No config, cwd = the directory containing `.functualize/plugins/` — the plugin still loads. No regression. |
| **AC-3** | `func` run from `02_multi/hello_app` with **no** `plugins_directories` declared loads `02_multi/.functualize/plugins/` — the directory `builtin info` already names as the project root in the same boot. |
| **AC-3b** | The convention search **stops at the project root**. A `.functualize/plugins/` placed in the *parent* of the directory holding the project's own `.functualize/` is **not** loaded. Falsifier for an unbounded walk, and the guard on the trust-model concern in §E. |
| **AC-3c** | A declared directory resolves through walk A's semantics, proven on each rung rather than asserted: (i) a value declared two levels up is inherited; (ii) `root = true` at an intermediate level stops that inheritance; (iii) `~/.config/functualize/config.toml` supplies the value when no project file declares one. Measured today as resolving correctly and then being discarded (`research.md` §6.1, §5.5). |
| **AC-4** | Declared and convention compose: a project declaring one extra directory loads plugins from **both** it and its own `.functualize/plugins/`. Falsifier for the current early-return. |
| **AC-5** | `PluginSources(ambient_directory=False)` declines the convention directory **at every level of the walk**. `tests/cli/test_single_file_cwd_isolation.py` passes unchanged, plus a new case placing the hijacking module one level up. |
| **AC-6** | A **declared** directory that does not exist produces a `logger.warning` naming the path, on a default-level run with no flags. Asserted on captured log output from a booted app. |
| **AC-6b** | A **declared** directory that exists but yields no loadable plugin produces a `logger.warning` naming the path, likewise at default level. |
| **AC-6c** | An **absent convention** directory stays silent. The ordinary case for a project that has no `.functualize/plugins/` must not gain a warning on every run. Falsifier for over-applying AC-6. |
| **AC-7** | `[<domain>] provider = "..."` is read at boot. A test boots an app with a domain config section and observes the configured provider selected, not the default. |
| **AC-8** | **Zero** `hasattr(app, "_resolution_chain")` guards remain in `_plugins/`. `rg -n 'hasattr\(app, "_resolution_chain"\)' src/functualize/_plugins/` returns nothing. (`_app/boot.py:239` and `app/utils.py:2246` are out of scope — §A.4 and `research.md` §2.3 record why.) |
| **AC-9** | One resolver, not two. The path that answers "where do plugin directories live" is reachable from a single definition, and it is walk A's. `app/utils.py` and the plugin loader agree by *calling the same code*, not by two implementations that happen to match. Exact form is Plan's; the count is not. |
| **AC-9b** | Walk A is reachable from `boot_standard` without a layer violation. Today `rg -n "auto_discover" src/functualize/_app/` returns **nothing** — walk A runs only in `_cli/`, so a programmatic `FunctualizeApp(name="x")` never runs it. After the change, an app booted with no CLI involved honours a declared `plugins_directories`. Asserted by a test that constructs `FunctualizeApp` directly. |
| **AC-9c** | `_collect_convention_directories` is fed a directory set consistent with the project root. The measured disagreement — walk A collecting `[]` where walk C anchors (`research.md` §6.2) — is closed, in whichever direction Plan settles. |
| **AC-10** | No test asserts plugin-directory resolution by assigning `_resolution_chain` to a mock. `grep -c "_resolution_chain = chain_mock" tests/plugins/test_resolve_plugin_directories.py` → `0`. Behaviour is proven through a booted app. |
| **AC-11** | The three documents in §A.5 describe the shipped behaviour. Verified by re-reading each line, not by grep alone. |
| **AC-12** | `examples/plugins/file_based_plugin/` still works unchanged, and its `.functualize.toml:11` comment is revisited — if `plugins_directories` now works, "deliberately NOT set" needs a reason that is about the example, not about the bug. |
| **AC-13** | `uv run lint-imports` passes. No new peer-layer or internal→public edge. `_plugins/` still imports only `_types/`, `_primitives/`, `_events/` and stdlib. |
| **AC-14** | Full suite green. The 20 tests asserting `resolve_effective_directories` either still pass or are deliberately changed with the change recorded. |
| **AC-15** | `CHANGELOG.md` carries an entry for **this** change. The option was documented and dead across `0.2.3` and `0.3.0`; a user who worked around it needs to know it now works, and that the convention directory now resolves at the project root. |
| **AC-16** | `CHANGELOG.md` carries a separate `0.3.0` entry for the facade migration, showing the before/after for `app.before_job` → `app.hooks.before_job` and stating that an un-migrated plugin is skipped with a warning rather than failing the app (§B.1.8). Verified by `grep -n -i "app.hooks" CHANGELOG.md` returning a hit, which it does not today. |

---

## E. Non-goals

- Making the resolution chain available at boot step 4.
- Sandboxing or verifying file plugins. The security note at
  `_plugins/loader.py:6-10` stands: file plugins execute arbitrary local Python
  at the trust level of any local `.py` file.

  An upward search widens the set of directories from which code is executed,
  which is why §C.3 bounds it at the project root rather than at the filesystem
  root: the widening is from *one* directory to *the project*, not to every
  ancestor up to `/`. AC-3b is the falsifier. `ambient_directory=False` still
  declines the whole convention path (AC-5). Within that bound this feature does
  not change the trust model.
- Any change to entry-point plugin discovery.
