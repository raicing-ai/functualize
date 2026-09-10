# F3 · engine-sealed-construction — waves 0–4 (T1–T5)

Worktree: `/home/viltohmyst/.herdr/worktrees/functualize/agent-f3-engine-seal`
Branch: `agent/f3-engine-seal`
Scope: T1, T2, T3, T4, T5 — the critical path four other features wait on.

## Retrieval — verified before starting

```
$ ls graphify-out/graph.json .serena/project.yml && du -sh .zvec-grep
.serena/project.yml
graphify-out/graph.json
74M	.zvec-grep
```

- **graphify** — `graphify-out/graph.json` present and committed (warm on arrival). Not queried: every
  "who reaches this" question in this feature is a literal-name question (`engine._app`,
  `add_registry_mirror`, `Path.cwd()`), which ripgrep answers exactly and exhaustively, and the
  feature's own audit documents (`05-engine-seal.md`, `audit-engine-encapsulation.md`) had already
  produced the dependency picture. No graphify claim appears in this report that was not checked
  with `rg` or a test.
- **serena** — `.serena/project.yml` present. Not used: the symbols involved (`JobExecutionEngine`,
  `FunctualizeApp`, `RunContext`) have unique names, so `rg` is exact here, and the two questions
  it could not answer — "does anything construct an engine expecting the old signature" and "does
  anything pass `resolution_chain=`" — needed a parse of every call site, which I did (all 37
  `JobExecutionEngine(` calls in `src/`, `tests/`, `plugins/` are keyword-only).
- **zvec-grep** — `.zvec-grep/` (74 MB) present, but **the `zg` CLI is NOT on PATH** and is not
  installed under `$HOME/.local/bin`: it lives at
  `$HOME/.local/share/mise/installs/node/24.14.1/bin/zg` (per `bootstrap-retrieval.sh`). With that
  directory prepended, `zg server on` reports *Server: ready*, so the index is intact — I simply
  did not need a prose query, since the design was already written down in
  `contributor/architecture/run-model/05-engine-seal.md`. Recorded because the brief asks to report
  a missing tool rather than work blind.

Environment note: the worktree had no venv on arrival. `uv run` created one from the root project only; **`plugins/*` are workspace members installed by `uv sync --all-extras`**, without which 48 test modules cannot import (`functualize_mcp`, `functualize_ai`, …). I ran `uv sync --all-extras` before any verification. Every number below is from that environment.

---

## T1 · `EngineHost`

### What changed

`src/functualize/_types/protocols.py` — added `EngineHost`, a `@runtime_checkable Protocol`
(126 lines with its docstrings), plus its entry in the module docstring's protocol list and in `__all__`, and
`RegisteredJob` to the `TYPE_CHECKING` import.

The members are the ones waves 0–4 actually consume:

| Member | Consumed by |
|---|---|
| `get_descriptor(name)` | `runcontext.get_job_schema` (kills `runcontext.py:698`'s three-hop chain), `invoke.schema` |
| `registered_jobs()` | `runcontext.list_jobs` |
| `replace_job(current, replacement)` | `executor._ensure_materialized` (replaces the shared dict) |
| `resolution_chain()` | `executor._live_resolution_chain` |
| `state_root` | `executor._state_store`, `Preflight`'s root, `RunContext.cwd` |
| `max_invoke_depth` | `executor` ×2, `invoke` ×1 |
| `event_bus` | `runcontext._resolve_event_bus` |
| `live_zone()` | `capabilities/live.py` |
| `collector()` | `runcontext._get_input_provider`, `executor._resolve_prompt_capability` |
| `push_surface` / `pop_surface` | `capabilities/tty.py` |

**Deliberate deviations from `contracts.md` §1**, each with its reason:

- `get_job`, `surface_stack` and `resolve_gate` are **not** declared. Nothing in waves 0–4 calls
  them: the engine keeps its own registry (so it does not need `get_job`), `live_zone()` and
  `collector()` answer the surface questions by name instead of exposing a stack to interpret,
  and `_gate_registry` is a constructor argument that nothing writes post-hoc. A protocol member
  with no caller is the "mechanism nothing calls" this repo removes on sight
  (`_primitives/state_store.py` says so about `batch()`); T6–T8 may add them when they have a
  caller.
- `resolution_chain` is a **method**, not the property §1 sketches. `FunctualizeApp.resolution_chain()`
  has been a method since the TUI provenance panels started calling it, and `_cli/tui/chain_resolution.py`
  calls it as one — a property would have broken the TUI. A port that does not fit its implementation
  is the wrong port.
- Added: `replace_job`, `collector`, `push_surface`, `pop_surface` — see T3/T4 for where each is used.

Sabotage (this task declares no behaviour, so the falsifier is the declaration itself): removing
`@runtime_checkable` turns the conformance assertion red —
`TypeError: Instance and class checks can only be used with @runtime_checkable protocols` in
`tests/engine/test_engine_is_sealed.py::TestTheHostIsReal`. Restored.

### Gate

```
$ rg -c 'class EngineHost' src/functualize/_types/protocols.py
before: 0
after:  1

$ rg -n 'class EngineHost' -B2 src/functualize/_types/protocols.py | rg -c 'runtime_checkable'
before: n/a
after:  1
```

A different spelling of the same question — the falsifier the task did not choose:

```
$ grep -c 'EngineHost(Protocol)' src/functualize/_types/protocols.py
1
$ grep -rn 'EngineHost' src/ tests/ plugins/ | grep -v '^src/functualize/_types/protocols.py' | wc -l
0        # T1: a declaration nothing uses yet, asserted rather than assumed
```

Runtime proof that it is a protocol and not a class-shaped alias:

```
empty  -> False          # isinstance(Empty(), EngineHost)
full   -> True           # an object implementing all 11 members
issubclass raises TypeError as documented: Protocols with non-method members don't support issubclass().
Non-method members: 'event_bus', 'max_invoke_depth', 'state_root'.
```

`uv run pytest tests/types -q` → **168 passed** (the package the port lives in).

---

## T2 · `build_engine(host)`, called by both boot paths

### What changed

`src/functualize/_app/boot.py`:

- **added `build_engine(host: EngineHost) -> JobExecutionEngine`** (43 lines, before `boot_static`).
  It carries the one `JobExecutionEngine(...)` construction and the one `_config_view_factory`
  closure. The two blocks it replaced were byte-identical apart from the local aliases
  `ResolutionChain`/`ResolutionChain2` and `_config_view_factory`/`_config_view_factory2`.
- `boot_static` and `boot_standard` each collapse their 19-line block to
  `app._execution_engine = build_engine(app)`.
- Removed the two now-unused local `from functualize._engine.executor import JobExecutionEngine`
  imports inside those functions, and added `EngineHost` to the `TYPE_CHECKING` block.

T2 is deliberately **transitional**: the post-hoc writes are still inside `build_engine`, marked

```
# TRANSITIONAL(engine-sealed-construction/T3): the engine is still finished
# *after* it is constructed …
```

T3 deletes them, which is exactly what happened (§ Wave 2).

`tests/app/test_engine_construction.py` (new, 85 lines) — a spy on `boot.build_engine`, run on
both paths, asserting the builder is called once with the app and that the resulting engine can
resolve a discovered job (so the builder was handed a *working* host, not merely called).

Sabotage: `boot_static` constructing the engine directly instead of calling the builder.
`tests/app/test_engine_construction.py::test_the_static_path_builds_its_engine_through_the_one_builder`
fails — `assert [] == [<FunctualizeApp object>]` (the spy recorded no call). Restored.

### Gate

```
$ rg -c 'def build_engine' src/functualize/_app/boot.py
before: 0 · after: 1

$ rg -c 'JobExecutionEngine\(' src/functualize/_app/boot.py
before: 2 · after: 1
```

Falsifier the task did not choose (same question, looser spelling — would also catch a call
spelled `JobExecutionEngine (`):

```
$ grep -cE 'JobExecutionEngine\s*\(' src/functualize/_app/boot.py
1
```

`uv run pytest tests/app tests/engine tests/execution -q` → **356 passed** after the collapse.

---

## T3 · Every post-hoc write and the shared dict die

### What changed

`src/functualize/_engine/executor.py`:

- `JobExecutionEngine.__init__` takes `host: EngineHost | None = None` in place of
  `resolution_chain: Any = None` (all callers are keyword — verified by parsing every
  `JobExecutionEngine(` call in `src/`, `tests/`, `plugins/`). `self._host = host`.
- `add_registry_mirror()` and `self._registry_mirrors` **deleted** (executor.py:232 and :201).
- `_ensure_materialized` now reports the swap instead of writing into the registry's private dict:
  `self._host.replace_job(entry, new_entry)`.
- New read-only accessors: `host` (the port) and `max_invoke_depth` (the host's answer, falling
  back to the constructor value only when there is no host).
- `_make_empty_chain` **deleted** — it was dead (no caller in `src/`, `tests/` or `plugins/`) and
  its only body read `self._resolution_chain`. Replaced by `_live_resolution_chain()`, which asks
  the host every time; `_resolve_shell_setting` uses it.
- The two `RunContext` constructions pass `_max_invoke_depth=self.max_invoke_depth`.

`src/functualize/_app/boot.py`: `build_engine` passes `host=host` and the two transitional writes
(`engine._app = host`, `engine.add_registry_mirror(...)`) are gone; step 7a's
`app._execution_engine._resolution_chain = app._resolution_chain` is gone, replaced by a comment
saying why nothing needs wiring; `_resolve_max_invoke_depth` records the resolved value **on the
app** (`app._resolved_max_invoke_depth`).

`src/functualize/app/core.py`:

- `refresh()` no longer writes `engine._resolution_chain`.
- New `EngineHost` members: `get_descriptor`, `registered_jobs` (`MappingProxyType` over the
  registry's map — a view, no copy, measured: see below), `replace_job`, `state_root`,
  `max_invoke_depth`, `live_zone`, `collector` (+~90 lines). `resolution_chain()`, `event_bus`,
  `push_surface`/`pop_surface` already existed.
- `__init__` records `self._state_root = Path.cwd()` once, at the delivery boundary.

**Measurement the plan asked for (R-g):** `registered_jobs()` returns
`types.MappingProxyType(registry._registered_jobs)` — one proxy object per call over a mapping
already in memory; no copy. Mutation raises
`TypeError: 'mappingproxy' object does not support item assignment` (asserted in the test).

`src/functualize/_engine/capabilities/invoke.py`: `max_invoke_depth=ctx.engine.max_invoke_depth`
(one line). **File outside T3's list, disclosed:** without it `Invoke` would have kept the
constructor's depth while the engine read the host's, turning the deleted write into a silent
behaviour regression. invoke.py is in this assignment's T4 list; the line moved in T3 because
T3 is what makes the value live.

Tests updated (they failed because of this change, so they are in scope):

- `tests/execution/test_lazy_materialization.py` — the mirror test becomes a host test
  (`_RecordingHost`); docstring line updated.
- `tests/config/test_unified_config_integration.py` (3 helper sites) — `resolution_chain=chain`
  → `host=mock_app` with `mock_app.resolution_chain.return_value = chain`.
- `tests/test_shell_capability.py`, `tests/test_shell_interactive.py` — inline `_Host` stubs
  answering `resolution_chain()`.
- `tests/core/test_app_persistent_consumer_api.py` — `test_propagates_new_chain_to_execution_engine`
  **pinned the deleted write** (`assert engine._resolution_chain is app.resolution_chain()`).
  Rewritten as `test_the_engine_reads_the_chain_the_app_currently_holds`, which asserts the
  behaviour that mattered: after a refresh the engine resolves against the app's current chain.

Sabotage (restore one write):

```
boot.py:209: _state_root        ← `engine._state_root = app.state_root` re-added
AssertionError: The engine is finished by its owners after it is built. …
FAILED tests/engine/test_engine_is_sealed.py::TestNothingWritesIntoTheEngine
```

Restored by editing the file back (`grep -c SABOTAGE src/functualize/_app/boot.py` → 0).

### Gates

```
$ rg -n 'engine\._[a-z_]+ *=|execution_engine\._[a-z_]+ *=' src/ plugins/ | grep -v '^src/functualize/_engine/'
before: 5  (boot.py:286,498,701,1586; core.py:514)
after:  0

$ rg -c 'add_registry_mirror' src/functualize/
before: 3  (boot.py:288, :500, executor.py:232)
after:  no matches  (rg exit 1; .pyc files are skipped as binary)
```

`tests/engine/test_engine_is_sealed.py` (new, 233 lines) carries the absence assertion as a test —
an **AST** scan of `src/` and `plugins/` for any assignment whose target is a private attribute of
something named `engine`/`_engine`/`execution_engine`, outside `_engine/`. AST rather than a
regex, because a regex also matches the comment explaining the removed write and cannot tell
`engine._x = y` from `engine._x == y`. The same file asserts host conformance
(`isinstance(app, EngineHost)`, `app.execution_engine.host is app`) on **both** boot paths,
read-only `registered_jobs()`, materialization propagating to the app registry, the live chain
read, and the config-resolved `max_invoke_depth` reaching the engine.

`uv run pytest tests/context -q --run-slow` → **736 passed**; `tests/engine tests/execution
tests/app tests/core tests/config tests/gate tests/cli` → **3185 passed, 490 skipped**.

---

## T4 · Every `_app` reach-through becomes a host call — one commit

### What changed

All eleven reads, in one pass (no file was migrated on its own — a half-migrated read set is the
failure mode the plan names R-a):

| File | Was | Now |
|---|---|---|
| `capabilities/runcontext.py` `_resolve_event_bus` | `getattr(engine, "_app")` then `_event_bus`/`event_bus` | `host.event_bus` |
| `capabilities/runcontext.py` `_emit_event` | same, for `_dispatch_to_surfaces` | `host` (the app is the host) |
| `capabilities/runcontext.py` `get_job_schema` | `engine._app.job_registry.get_descriptor` | `host.get_descriptor`, `JobNotFoundError` when `None` |
| `capabilities/runcontext.py` `list_jobs` | `app.get_jobs()` | `host.registered_jobs()` + `host.get_descriptor` per name |
| `capabilities/runcontext.py` `_get_input_provider` | `active_collector(app)` | `host.collector()` |
| `capabilities/invoke.py` `schema` | `app.job_registry.get_descriptor` | `host.get_descriptor`, else the existing fallback |
| `capabilities/live.py` | `active_live_zone(getattr(ctx.engine, "_app", None))` | `ctx.engine.host.live_zone()` |
| `capabilities/tty.py` | `funcapp=getattr(ctx.engine, "_app", None)` | `funcapp=ctx.engine.host` |
| `executor.py` `_resolve_prompt_capability` | `active_collector(getattr(self, "_app", None))` | `host.collector()` |
| `executor.py` `_resolve_shell_sinks` | `getattr(app, "shell_surface_writer", None)` | `getattr(self._host, "shell_surface_writer", None)` |
| `executor.py:1401` (a comment) | spelled `engine._app` | describes the chain without spelling it |

The transitional `_app` property added at T3 (marked `TRANSITIONAL(.../T4)`) is **deleted** here;
the engine now has exactly one way out, `host`.

`_resolve_shell_sinks` keeps a `getattr`: `shell_surface_writer` is defined **nowhere in `src/`**
— it is a hook a plugin installs on the app — so the port cannot declare it without making every
plain app fail conformance. It is the documented extension case, not a missing member.

Tests updated: `tests/context/test_runcontext_prompt.py`, `test_runcontext_emit.py`,
`test_invoke_parallel_and_schema.py` (mock apps now answer the port: `engine.host = app`, and the
prompt stub delegates to `active_collector` so the stack ordering stays under test),
`tests/context/test_prompt_properties.py`, `test_emit_properties.py`,
`test_runcontext_delegation_properties.py` (the same three helpers, found only by `--run-slow` —
they are skipped in a normal run, which is the trap the rules warn about).

**Coverage gap found and closed.** The task's sabotage is "point `host.live_zone()` at `None`; a
`tests/tui_audit/` test must fail." With that sabotage applied, `tests/tui_audit/` stayed **green
(15 passed)**: that suite is fifteen narrow historical proofs (key aliasing, modal key leak,
blocking workers) and exercises no `Live` capability. The live-zone path *is* covered — by
`tests/_cli/test_panel_live_zone.py`, which drives the real TUI with pilot — and adding the
missing end-to-end proof for the capability itself (`tests/execution/test_tty_live_capabilities.py`,
new class `TestLiveBindsToTheHostsZone`): a job declaring `live: Live` pushes a construct, and the
app's pushed live zone receives it.

Sabotage, with that coverage in place (`live_zone()` → `None`):

```
FAILED tests/execution/test_tty_live_capabilities.py::TestLiveBindsToTheHostsZone::test_a_construct_reaches_the_hosts_live_zone
       - assert [] == [<tests.execution.test_tty_live_capabilities._Construct object …>]
FAILED tests/_cli/test_panel_live_zone.py::test_live_zone_is_resolved_and_rendered_during_panel_run
       - AssertionError: the construct's content should render into #live-zone, got '\n'
FAILED tests/_cli/test_panel_live_zone.py::test_events_forward_to_hosted_constructs
       - AssertionError: the zone should forward structured events to hosted constructs
3 failed, 30 passed
```

Restored; `tests/tui_audit tests/execution/test_tty_live_capabilities.py
tests/_cli/test_panel_live_zone.py` → **33 passed**.

### Gate

```
$ rg -n 'getattr\([^,]*, "_app"|\._app\b' src/functualize/_engine/ | wc -l
before: 11    (task says 12 — F1/F2 removed one read since e57f0c9)
after:  0
```

The broader `rg '_app' src/functualize/_engine/` returns **9**, and every one must survive: six
docstring lines across four files naming `_app/boot.py` / `_app/impl.py` (`__init__.py:8`,
`executor.py:486`, `job_graph.py:20-21`, `workflow_validation.py:3,11`) and three `_apply_prefix`
lines in `capabilities/shell.py`, where `_app` is an unrelated substring. `surface_routing.py`
holds no `_app` read, and was not touched (it is out of this task's file scope).

Verification: `uv run pytest tests/tui_audit/ -q` → **15 passed**; fast suite green (§ Verify).

---

## T5 · `Path.cwd()` leaves `_engine/`

### What changed

`src/functualize/_engine/executor.py`:

- `JobExecutionEngine.state_root` (new property): the **host's** answer; an explicit
  `state_root=` constructor argument is honoured only when there is no host; with neither, it
  **raises** with a message naming `build_engine`. Nothing plausible is invented — a kernel that
  can still reach for the process working directory is the defect being removed, and `Path(".")`
  or `os.getcwd()` would be the same sin spelled to satisfy a grep.
- `_state_store()` → `StateStore.for_project(self.state_root)`.
- `_preflight()` → `Preflight(self._state_store(), root=self.state_root)`.

`src/functualize/_engine/preflight.py`: `root` is now **required** (keyword-only). Its docstring
says why: a default would be the kernel asking the operating system, which is how a pre-flight
could resolve `Fingerprint.sources` against a directory the run never named.

`src/functualize/_engine/capabilities/runcontext.py`: `RunContext.cwd` returns the run's own
`cwd` when the request carried one, else the engine's `state_root`; with no engine at all it
raises, because a `RunContext` built by hand has no project to name.

`src/functualize/app/core.py`: the `func why` pre-flight path
(`explain_verdicts`) uses `self.state_root` for both the store and the root, instead of
`Path.cwd()`.

`tests/app/test_state_root_from_host.py` (new, 85 lines): both halves of AC-6, each with the
**process moved away from the project** between construction and the run — a kernel that still
asked the OS would follow it:

- a run writes `.functualize/state.json` under the app's root and nothing under the new cwd;
- a run whose request named no directory reports the project root from `rc.cwd`.

Sabotage (re-point `Path.cwd()` back into the kernel: `StateStore.for_project(Path.cwd())`):

```
FAILED tests/app/test_state_root_from_host.py::test_a_run_writes_its_state_under_the_projects_root
E  assert (PosixPath('/tmp/…/project') / '.functualize' / 'state.json').exists()
```

Restored by editing the file back; `rg 'SABOTAGE' src/functualize/_engine/executor.py` → 0.

### Gate

```
$ rg -n 'Path\.cwd\(\)' src/functualize/_engine/ | grep -v '^\S*:[0-9]*: *#' | grep -v 'defaults to'
before: 3  (executor.py:1212, preflight.py:116, runcontext.py:291)
after:  0   (the only remaining mention is executor.py:944's docstring, "defaults to Path.cwd()")
```

Falsifier the task did not choose — the same question asked of every file in the package, without
the two filters:

```
$ grep -rn 'Path.cwd()' src/functualize/_engine/ --include='*.py'
src/functualize/_engine/executor.py:944:            cwd: Working directory (defaults to Path.cwd()).
```

One hit, a docstring, and it is true: `ExecutionContext.cwd` *does* default to the process
directory — the engine supplies it from the request, and the state root no longer goes near it.

---

## Verify — the commands the rules require, once, at the end

All five below were run in this worktree with `uv sync --all-extras` installed. Plugin suites are
run separately afterwards (they cannot be collected with `tests/`).

```
$ uv run ruff check src/ tests/ plugins/ && uv run ruff format --check src/ tests/
All checks passed!
1114 files already formatted

$ uv run mypy src/
Success: no issues found in 335 source files

$ uv run lint-imports
Contracts: 6 kept, 0 broken.
   (Peer layers are independent / Events depends on foundation only / Primitives import nothing
    internal / Types import nothing internal / Internal never imports public / _cli uses public
    API only — all KEPT)

$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
<pasted below>

$ uv run pytest examples/ -q
194 passed in 125.81s (0:02:05)
```

The first `--run-slow` pass was **17 failed, 11203 passed, 139 skipped** — and it earned its keep,
because none of the sixteen real ones are visible in the fast suite:

- 3 × `tests/context/test_prompt_properties.py`, 9 × `tests/context/test_emit_properties.py`,
  3 × `tests/context/test_runcontext_delegation_properties.py` — these files **skip** without
  `--run-slow`, so the mock-app fixes made for `test_runcontext_prompt.py`/`test_runcontext_emit.py`
  had not reached their three sibling helpers. Fixed the same way; `tests/context --run-slow` →
  **736 passed**.
- 1 × `tests/_cli/test_display_refresh_thread_worker.py::test_slow_refresh_does_not_freeze_the_loop`
  — a responsiveness measurement (`got 1 polls … against an idle ceiling of 17`) taken while the
  machine was running this suite on all cores with four sibling agents' worktrees active. Re-run
  alone: **6 passed in 4.01s**. Parallelism artifact, not this change (nothing here touches the
  display refresh worker).

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q     # re-run, after the fixes
11220 passed, 139 skipped, 3087 warnings in 650.04s (0:10:50)

$ uv run pytest plugins/<name>/tests -q     # one package at a time, all 13
plugins/functualize-ai-pydantic  9 passed
plugins/functualize-ai           17 passed
plugins/functualize-aws          72 passed, 1 skipped
plugins/functualize-bitwarden    66 passed
plugins/functualize-flow-viz     25 passed
plugins/functualize-http         48 passed
plugins/functualize-inline       50 passed
plugins/functualize-lambda       44 passed
plugins/functualize-mcp          16 passed
plugins/functualize-state-sqlite 80 passed
plugins/functualize-state        6 passed
plugins/functualize-tasks-local  7 passed
plugins/functualize-tasks        15 passed
```

The re-run is the one that counts: **11220 passed, 139 skipped, 0 failed** — including the four
files that only execute under `--run-slow`.

Also run, because this change is exactly what they exist for:

```
$ uv run pytest tests/tui_audit/ -q                              # AC-12's suite
15 passed in 10.02s

$ uv run pytest tests/tui_audit tests/execution/test_tty_live_capabilities.py tests/_cli/test_panel_live_zone.py -q
33 passed in 16.54s
```

A final residue check, because five sabotages were applied and reverted by hand:

```
$ grep -rn 'SABOTAGE' src/ tests/ plugins/ --include='*.py' | wc -l
0
```

---

## Files touched (line counts)

New:

| File | Lines |
|---|---|
| `tests/app/test_engine_construction.py` | 85 |
| `tests/engine/test_engine_is_sealed.py` | 233 |
| `tests/app/test_state_root_from_host.py` | 85 |

Modified (source): `_types/protocols.py` (the `EngineHost` block is 126 lines, docstrings
included), `_app/boot.py` (`build_engine` is 43 lines; the two 19-line construction blocks
`spec.md` §1.1 names — `boot.py:270-288` and `:482-500` — become one line each),
`_engine/executor.py` (two fields and one method deleted, two accessors and `state_root` added),
`app/core.py` (the host members are 84 lines, comment block included; `refresh()` loses its write),
`_engine/capabilities/runcontext.py`, `_engine/preflight.py` (one signature line made required),
`_engine/capabilities/live.py`, `tty.py`, `invoke.py` (one to two lines each).

Exact add/delete deltas per file are not available: the brief forbids every `git` command, so
there is no diff to count against. The numbers above are measured from the files as they stand
(and from `spec.md`'s own line ranges for the deleted blocks) rather than estimated.

Modified (tests): `test_lazy_materialization.py`, `test_unified_config_integration.py`,
`test_shell_capability.py`, `test_shell_interactive.py`, `test_app_persistent_consumer_api.py`,
`test_runcontext_prompt.py`, `test_runcontext_emit.py`, `test_invoke_parallel_and_schema.py`,
`test_prompt_properties.py`, `test_emit_properties.py`, `test_runcontext_delegation_properties.py`,
`test_tty_live_capabilities.py` (one new test class).

Doc: `contributor/architecture/developer-modes.md:161` — the materialization step named the
deleted `add_registry_mirror` as the current mechanism. Rewritten to the host call.
(`contributor/architecture/{audit-engine-encapsulation.md, run-model/05-engine-seal.md, adr/020}`
describe the defect as it was; they are analysis, not a description of current behaviour, and are
left as written.)

`CHANGELOG.md` — no entry. `[Unreleased]` is empty and the feature's job-author-visible half
(the `RunContext` diet, T8/T9) is later waves; the release note for this feature belongs with
those. Flagging it rather than silently deciding.

---

## Could not do / open questions (not blocking)

1. **`zg` is not on PATH.** Present at
   `$HOME/.local/share/mise/installs/node/24.14.1/bin/zg`; `.zvec-grep/` (74 MB) exists for this
   worktree. No prose query was needed, so this cost nothing — but a brief that says "run
   `zg query`" will fail in a clean shell.
2. **`surface_stack` was dropped from the port.** §1 lists it, but every consumer of the surface
   stack in `_engine/` reaches it through `active_live_zone`/`active_collector`, and
   `surface_routing.py` — which owns those two rules — is out of T4's file scope. Exposing the raw
   stack and re-implementing the ordering in the engine would put a second copy of the routing
   rule in the kernel. If T6–T8 need it, adding it then is one property.
3. **`tests/tui_audit/` does not exercise `Live`.** T4 asks for a tui_audit failure under the
   `live_zone()` sabotage; it stays green. Proof was added where the capability lives, and the
   real-TUI half is already covered by `tests/_cli/test_panel_live_zone.py` — see T4.
4. **`.spec/STATE.md` does not exist** in this worktree ("no work in flight" by the workflow's own
   rule), so nothing was recorded there. T1–T5 are marked `[x]` in `tasks.md`.
5. **No commit was made.** The brief forbids every `git` command, so the four sabotage
   demonstrations above were restored by editing the files back and each restore is confirmed by
   the `grep -c SABOTAGE` output and the green re-run quoted beside it, rather than by a commit.

## Task table

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T1 · `EngineHost` | yes | `class EngineHost` → 0 | 1 (and `runtime_checkable` → 1) |
| T2 · `build_engine(host)` | yes | `def build_engine` → 0; `JobExecutionEngine(` → 2 | 1; 1 |
| T3 · the seal | yes | writes outside `_engine/` → 5; `add_registry_mirror` → 3 | 0; 0 |
| T4 · `_app` reach-throughs | yes | 11 reads | 0 |
| T5 · `Path.cwd()` | yes | 3 | 0 |
