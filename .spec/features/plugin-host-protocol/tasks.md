# Tasks — plugin-host-protocol

**16 tasks / 11 waves.** Revised 2026-09-17 against the scrutiny report and the
two maintainer decisions (`plan.md` §0). Every gate below carries its measured
`now:` value, taken on `79545ef`; a gate whose `now:` does not reproduce is a
signal to re-measure before editing, not to proceed.

Wave ordering is binding. Reachability precedes `[x]` — name the production
path and break it once (`contributor/guides/wiring-discipline.md`).

---

## T1 · Delete the MCP dead probe — [x]

`[F]` `plugins/functualize-mcp/src/functualize_mcp/_task_tools.py`

Delete lines 66-76 — the `hasattr(app, 'resolve')` / `app._tasks` probe inside a
bare `except`. Both attributes are absent, so the in-memory `Tasks` fallback is
the only path that has ever run. Leave a one-line comment recording that the
block was dead, so the deletion is not read later as a removed feature.

- **Gate** `python -c "from functualize.app import FunctualizeApp as A; a=A(); print(hasattr(a,'resolve'), hasattr(a,'_tasks'))"`
  — `now: False False` · `after: False False` (unchanged; the point is that the
  probe could never succeed)
- **Gate** `rg -c "hasattr\(app, ?'resolve'\)|app\._tasks" plugins/` — `now: 2` · `after: 0`
  — **corrected at execute time.** As written the pattern returns **1**, not 2:
  the code spells it `hasattr(self._app, "resolve")` with double quotes, which
  the first alternative never matched, and `app\._tasks` matched
  `self._app._tasks`. The hit set is 2 *lines*; the gate that measures them is
  `rg -c "hasattr\(.*_app, ?[\"']resolve[\"']\)|app\._tasks" plugins/`. Both
  now return zero.
- **Reachability** — **the gate as written was false.** Nothing in
  `plugins/functualize-mcp/tests/` referenced `MCPTaskToolRegistry`, so
  replacing the surviving `Tasks()` constructor with `raise ImportError` left
  all 28 tests green. The production path is real — MCP server boot
  (`_server.py:102` → `register_tools` → `mcp.add_tool(self._add_task)`) and a
  client call enters `_get_tasks` — but no test traversed it. Closed by
  `plugins/functualize-mcp/tests/test_task_tools.py` (4 tests, commit
  `a307ecd`); the same sabotage now fails 2 of them. The first test uses a
  `HostileApp` that raises on any attribute access, which pins the deletion:
  `hasattr` used to swallow exactly that raise.

## T2 · Delete the ai-pydantic dead state guard — [x]

`[F]` `plugins/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py`

Delete lines 139-148 — the `from functualize_state import StateBackend` guard
and the `app._di_registry.resolve(StateBackend)` behind it. That import raises
`ImportError` (ADR-022 retired the domain; no `plugins/functualize-state`
exists), so the line was never reached. Call `resolve_ai_state_backend(None)`
directly, which is what the `except` already did.

- **Gate** `python -c "import functualize_state"` — `now: ImportError` · `after: ImportError`
- **Gate** `rg -c "_di_registry" plugins/` — `now: 1` · `after: 0`
- **Reachability** — **the gate as written was false.** `raise RuntimeError` at
  the top of `resolve_ai_state_backend` left both AI suites green:
  `functualize-ai-pydantic` had one test (an import smoke check) and
  `functualize-ai`'s seventeen never touch `_state_fallback`. `_on_app_ready`
  also wraps its whole body in `except Exception: logger.error(...)`, so a
  failure there is invisible by construction. Closed by two tests appended to
  `plugins/functualize-ai-pydantic/tests/test_plugin.py` (commit `35625a0`);
  the same sabotage now fails both. Production path:
  `_on_app_ready` (`_plugin.py:86`) → `_resolve_state_namespace` →
  `resolve_ai_state_backend(None)`.

## T3 · Rename the substrate trio — [x]

`[F]` `src/functualize/app/core.py`, `src/functualize/_types/protocols.py`,
`src/functualize/_engine/executor.py`, `tests/test_facade_loc_limits.py`

**Writers moved here from T4, at execute time.** Removing the `:334` setter
breaks every `app.substrate = …` in the tree the moment it lands, so the
writers cannot wait a wave without committing a knowingly-red tree. Migrated
with the rename: `plugins/functualize-state-sqlite/…/_plugin.py:76`,
`tests/integration/test_substrate_durability.py:102`, **and a third the plan
missed** — `examples/plugins/custom_state_backend/src/functualize_state_memory/_plugin.py:61`,
plus that example's `README.md:67`. T4's gate `rg -c "app\.substrate *=" src
plugins tests` could not see it: its path list has no `examples/`, and the
example is a working plugin, not a doc snippet.

Per `contracts.md` §4a-4c: `substrate` becomes the storage **in effect**
(`return self.execution_engine.substrate`, never `None`); the `:334` setter
becomes `install_substrate()` delegating to the existing
`_app/impl.py:1546` guard; `EngineHost.substrate` becomes `substrate_override`
and `FunctualizeApp` grows a matching property returning `self._substrate`;
`executor.py:1525` reads the new name.

- **Gate** `uv run pytest tests/test_facade_loc_limits.py` — `now: green at 303/303` ·
  `after: green at 305/305`. Raise the budget **in the same commit**, with the
  argument from `contracts.md` §4d.
- **Gate** late install still refused loudly:
  `app.execution_engine.substrate; app.install_substrate(X)` → `RuntimeError`
  naming the split brain — `now: raises` · `after: raises`
- **Gate** `rg -c "def substrate" src/functualize/_types/protocols.py` — `now: 1` · `after: 1` (renamed, not added)
- **Reachability** — **the named file did not cover it.**
  `tests/primitives/test_one_substrate_choice.py` asserts the engine resolves
  *once* and that its stores share one substrate; it never asserted the engine
  honours the host's override. Setting `chosen = None` — ignoring the override
  entirely — left all 8 of its tests green. The only thing that noticed was
  `tests/integration/test_substrate_durability.py`, and **that gate is also
  mis-written**: without `--run-slow` it reports `4 skipped`, which reads as a
  pass. With `--run-slow` it is 4 passed / 4 failed under sabotage, in 14 s,
  across two spawned worker processes.
  Closed by three fast tests in the same file (commit `546dc54`): the engine
  uses the host's override, the app reports it through the public door, and a
  late install is refused with the first substrate still standing. Both
  sabotages bite — `chosen = None` fails the first two; replacing
  `install_substrate`'s delegation with a bare assignment fails the third.
- **Gate (corrected)** `FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest
  tests/integration/test_substrate_durability.py --run-slow` — `after: 4 passed`
- **Also landed** `tests/_cli/test_self_doctor.py`'s
  `test_there_is_no_plugin_check` searched every report entry for the substring
  `"plugin"`, and the installations check names its entries by absolute binary
  path — so it fails in any checkout whose directory contains `plugin`. It was
  the only failure in 10,644 tests here. Verified pre-existing by restoring the
  three source files from `HEAD` and re-running. Fixed in `c924ce2`, separately,
  because it belongs to no task in this feature.

## T4 · Collapse the ten chain sites — [x]

`[F]` `src/functualize/_app/boot.py`, `src/functualize/_app/impl.py`,
`src/functualize/app/_workflow_control.py`,
`src/functualize/app/adapters/workflow_flags.py`,
`src/functualize/_cli/builtins.py`,
`plugins/functualize-mcp/src/functualize_mcp/_history_tools.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
`plugins/functualize-tasks-local/src/functualize_tasks_local/_plugin.py`

The hit set of `rg -n 'execution_engine\.substrate'` — 10 sites across 8 files,
6 in `src/`. Each becomes `app.substrate`. Behaviour is identical because the
new property returns `self.execution_engine.substrate`.

~~Also migrate the two writers to `install_substrate`~~ — **done in T3**, and
there were three, not two (see T3). T3 removes the setter, so the writers had
to move with it.

- **Gate** `rg -n "execution_engine\.substrate" src plugins tests examples` —
  ~~`now: 10` · `after: 0`~~. **`after: 0` is unreachable, and this was written
  without running it.** The pattern counts *all* matches, and three of them are
  not call sites:
  - `src/functualize/app/core.py:335` — the new property's own body. It *is*
    the delegation; the collapse works because this one match survives.
  - `src/functualize/app/core.py:328` and `tests/test_facade_loc_limits.py:64` —
    prose written in T3, explaining the rename.

  Measured: **13 before** (10 sites + those 3), **4 after** — the property, the
  three prose mentions, minus none, plus one more prose mention this task adds
  at `tests/plugins/test_mcp_history_tools.py:193`. Executable matches: **1**.
- **Gate** `rg -n "app\.substrate *=" src plugins tests examples` — `after: 0`
  writers. Measured **1 match, and it is prose**:
  `examples/plugins/custom_state_backend/tests/test_backend.py:156` narrates the
  old spelling in a docstring. **Add `examples` to the path list**: the original
  gate's three paths miss a real writer, which is how T3 found a fourth file to
  edit.
- **Note** `tests/plugins/test_mcp_history_tools.py:198` builds a fake engine
  and sets `engine.substrate`. Retargeting `_history_tools.py:54` to
  `app.substrate` makes that fake's `_App` need a `substrate` of its own.
  **Happened as predicted** — `AttributeError: '_App' object has no attribute
  'substrate'`. The fake lost its engine entirely and is now one attribute,
  which is what the collapse is for.
- **Do not fix** `functualize-tasks-local`'s hook-ordering bug at
  `_plugin.py:66`. That is `plugin-taxonomy`'s F4/AC-8 (`spec.md` §I). This task
  changes the **spelling only**; the bug must survive intact. **Honoured** —
  `git diff` on that file is one token.
- **Reachability** ~~`FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest tests/integration/test_substrate_durability.py`~~
  — that is T3's gate, and it needs `--run-slow` (see T3). For *this* task the
  question is whether the ten collapsed sites are on production paths, so the
  sabotage is on the property they now all go through:
  `FunctualizeApp.substrate` → `raise RuntimeError`, run with T3's own
  `tests/primitives/test_one_substrate_choice.py` **excluded** so the failures
  are attributable here. **40 failed across 7 files**, naming all six `src/`
  sites:

  | file | n | site |
  |---|---|---|
  | `tests/test_state_cli_scopes.py` | 14 | `_cli/builtins.py:1066`, `adapters/workflow_flags.py:238` |
  | `tests/events/test_run_log.py` | 4 | `_app/boot.py:129`, `:146` |
  | `tests/pipeline/test_fingerprint_key_agreement.py` | 4 | `_app/impl.py:1047` |
  | `tests/test_fingerprint.py` | 2 | `_app/impl.py:1047` (`func why`) |
  | `tests/workflow/test_watch_stream.py` | 2 | `_app/boot.py:129` |
  | `tests/workflow/test_gate_resume_surfaces.py` | 2 | `app/_workflow_control.py:124` |
  | `tests/pipeline/test_generates_globbing.py` | 1 | `_app/impl.py:1047` |

  The four `plugins/` sites go through fake apps, not this property; the rename
  is proven live there by the `AttributeError` above.
- **Done** `1ecd8d9`. Root suite before the sabotage: **10,646 passed, 1 failed**
  — and the failure was **not** this task's.
  `tests/core/test_show_info.py::test_dotenv_loaded_shows_path` asserts `".env"
  in result.output`; under `-n auto` the worker directory makes the tmp path 78
  characters, Rich folds it after `shows_path0/.` inside a 76-column panel, and
  `env` lands on the next line. Proven pre-existing by restoring all nine T4
  files from `HEAD` (scratchpad backup, `cp -f` restore) and re-running: same
  failure. Fixed in `098602a` with the `_packed` helper this test file already
  carries for this exact problem, and verified non-vacuous.

## T5 · Retype `HooksFacade.on_ready` — [x]

`[F]` `src/functualize/_app/hooks_facade.py`, `src/functualize/_types/host.py`

**Third file, added at execute time:** `src/functualize/_app/impl.py`. The
property delegates to `make_on_ready_decorator`, typed `-> Callable[..., Any]`.
Leaving it there makes the property's narrower declaration *asserted* rather
than checked — `Any` satisfies any annotation, in both directions — so the
factory is typed to match. Same reasoning as T3's engine chain.

Introduce `OnReadyHandler = Callable[[PluginHost], None]` and type the property
`Callable[[OnReadyHandler], OnReadyHandler]` (`contracts.md` §5). Returning the
handler matches `_app/decorators.py:98-100`, which registers and returns `fn`.

~~`_types/host.py` is created here with only the alias and a forward
reference~~ — **a bare forward reference does not type-check.**
`OnReadyHandler: TypeAlias = Callable[["PluginHost"], None]` with the name
undefined is `error: Name "PluginHost" is not defined  [name-defined]`, measured
on a one-line fixture. So T5 creates a **placeholder `PluginHost` Protocol with
an empty body**, and says so in its docstring: it constrains the callee (no
member access type-checks against it) but not the caller, since an empty
Protocol is satisfied structurally by everything. T7 fills in the eleven members
and the five views. The placeholder is still strictly better than the obvious
alternative — aliasing to `Any` would make case 7 below pass.

- **Gate** the eight-case probe in `contracts.md` §5, as a focused mypy fixture
  — ~~`now: 3 of 8 behave`~~ · `after: 8 of 8`. **`now` is 4 of 8, measured.**
  Under `Callable[..., Any]` mypy reports *no* error for any of the eight, so
  the four must-pass cases behave and none of the four must-fail cases does.
  `3 of 8` was written without running it.
  Implemented as `tests/types/test_on_ready_signature.py` plus
  `tests/types/fixtures/on_ready_cases.py`, and the fixture calls the
  **shipped** property rather than a local stand-in — otherwise the gate checks
  a copy of the signature. Costs ~1 s on a warm `.mypy_cache`, ~15 s cold;
  deliberately **not** marked slow, because a gate marked slow is a gate that
  skips, which is how T3's durability gate read as a pass.
  `tool.mypy` checks `packages = ["functualize"]`, so the fixture's four
  deliberate errors are invisible to the repo's own mypy run.
- **Gate** existing `app: Any` handlers still pass — ~~all four real handlers~~
  **five**: `plugins/` has four (`tasks-local`, `ai-pydantic`, `mcp`,
  `state-sqlite`) and `examples/plugins/custom_state_backend` has the fifth. All
  five are `def _on_app_ready(self, app: Any) -> None`. Case 3 of the probe is
  this gate, and it passes. **`examples/` missing from a path list is now the
  third count this feature has had to correct** (T3's writers, T6's
  registrations, this).
- **Reachability** ~~`tests/core/test_app_ready_and_shutdown.py`~~ — **that file
  did not mention `on_ready`.** Fourth gate in this feature whose named coverage
  did not exist. And the hole was wider than the file: `rg -l on_ready` over
  `tests/`, `plugins/*/tests`, `examples/` found **no caller of the property at
  all** — the nearest test exercises `_make_global_only_decorator` with a fake
  registry, and all five production plugins call
  `hook_registry.register_global(HookEvent.APP_READY, …)` directly. So the
  property could have been retyped, or deleted, with the suite green.
  Closed with three tests in the named file (registration, identity
  preservation, the non-callable TypeError). **The property is still unwired in
  production — T6 is the task that gives it callers.**
- **Done** `5d76ec4`. Both directions sabotaged, since a type gate can be
  vacuous either way: widening the property back to `Callable[..., Any]` fails
  the new gate at all four marked lines; deleting
  `register_global(HookEvent.APP_READY, fn)` fails
  `test_it_registers_the_handler_for_app_ready` (1 of the 3 — the other two do
  not depend on that line). mypy green on 364 files; lint-imports 7 kept / 0
  broken.

## T6 · Migrate the four APP_READY registrations — [x]

> **There are five, not four.** `rg -n 'register_global\(HookEvent.APP_READY'`
> over `plugins/`, `src/`, `examples/` and `tests/` returns four in `plugins/`
> (`mcp/_plugin.py:70`, `state-sqlite/_plugin.py:58`, `tasks-local/_plugin.py:54`,
> `ai-pydantic/_plugin.py:62`) and a fifth in
> `examples/plugins/custom_state_backend/src/functualize_state_memory/_plugin.py:50`,
> documented again in that example's `README.md:64`. Same omission as T3's
> writers: `examples/` was not in the query's path list. Measured at T5.

`[F]` `plugins/functualize-mcp/src/functualize_mcp/_plugin.py`,
`plugins/functualize-state-sqlite/src/functualize_state_sqlite/_plugin.py`,
`plugins/functualize-tasks-local/src/functualize_tasks_local/_plugin.py`,
`plugins/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py`

`app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)`
becomes `app.hooks.on_ready(self._on_app_ready)` at lines 70/58/54/62.

`[F]` **two more files**, both mirrors of the migrated code:
`plugins/functualize-ai-pydantic/tests/test_pydantic_provider.py` (asserted on
`register_global`) and `examples/plugins/custom_state_backend/tests/test_backend.py`
plus that example's `README.md`.

**The `HookEvent` import goes with the call.** In all five files it was a
function-local `from functualize._events.hooks import HookEvent`, dead once the
event moves into the method name — so after this task **no plugin or example
imports `functualize._events` at all**. That import was the coupling worth
deleting: every plugin reached into an underscore-prefixed internal package to
register a lifecycle hook.

- **Gate** `rg -c "hook_registry.register_global" plugins/` — `now: 4` ·
  `after: 0` ✅ measured. `examples/` shows 1 and it is prose in a test
  docstring explaining what was removed.
- **Gate** the hooks still fire at boot: each plugin's own suite — mcp 32,
  state-sqlite 25, tasks-local 9, ai-pydantic 11, examples 204, root suite
  10,652. All green.
- **Reachability** ~~break `make_on_ready_decorator`'s registration and watch
  all four plugin suites fail~~ — **one fails, not four.** Measured:

  | suite | under sabotage |
  |---|---|
  | `functualize-mcp` | **10 failed** of 32 — its commands stop appearing |
  | `functualize-state-sqlite` | 23 passed |
  | `functualize-tasks-local` | 7 passed |
  | `functualize-ai-pydantic` | 11 passed |
  | `examples/` | 204 passed |
  | root `tests/` (plugin + lifecycle) | **7 failed** — 6 in `tests/cli/test_plugin_command_dispatch.py`, which loads the real MCP plugin |

  Not indirect coverage — **absence of it.** `rg -l SQLiteStatePlugin` over the
  whole tree returns the package, its README, a scaffold `pyproject.toml.j2`
  and the stale graphify dump: **no test anywhere**.
  `functualize-tasks-local/tests/test_plugin.py` held one test, which imported
  the package. The single line T6 changed in each was covered by nothing.

  Closed in two commits, two-sided because the seam has two sides:
  - `1eb1f65` — four tests, two per plugin: it asks for `on_ready` and hands
    over its own handler, and it installs/initialises nothing during
    registration (a backend is chosen at `APP_READY`, ADR-022).
  - `cade950` — the composing test: a plugin loaded through a patched
    `entry_points`, registering via `app.hooks.on_ready`, **is fired at boot**.
    This is the one that fails under the sabotage, with
    `test_it_registers_the_handler_for_app_ready`.

  The plugin-side tests still pass under the app-side sabotage, by design:
  they use a fake hooks object, so they check that the plugin asks the right
  member, not that the member works. `ai-pydantic`'s stays a `MagicMock` for
  the same reason.
- **Done** `deb268a`, `1eb1f65`, `cade950`. **Five sites, not four** —
  `examples/plugins/custom_state_backend` again (see the note above).

## T7 · Write the port and the five views — [x]

`[F]` `src/functualize/_types/host.py`

`PluginHost` (11 members) plus `DependencyView`, `ExtensionsView`,
`ConfigurationView`, `GatesView`, `HooksView` — signatures copied from the live
facades, exactly as listed in `contracts.md` §2, including the two documented
deviations (`resolver: Any`; `get_plugin_commands` absent).

`[F]` **second file, added at execute time:**
`tests/types/test_plugin_host_port.py` + `tests/types/fixtures/plugin_host_conformance.py`.
The conformance gate below has to live somewhere a later wave cannot silently
break, and T9's test file is the *adapter* door, not this one.

- **Gate** `uv run lint-imports` — `now: 7 kept, 0 broken` ·
  `after: 7 kept, 0 broken` ✅
- **Gate** an unmodified app satisfies it, **both ways** (AC-3) ✅ —
  `isinstance` True, and mypy accepts handing a real `FunctualizeApp` to a
  `PluginHost` parameter. The task's reason for wanting both is now
  **demonstrated, not just stated**: sabotaging `get_job` to
  `(name: int, extra: str)` — the right name, the wrong signature — fails the
  mypy half and **passes** the `isinstance` half.
- **Gate** ~~`rg -c "_app" src/functualize/_types/host.py` — `after: 0`~~ —
  **unreachable, fifth mis-written grep gate.** Every view docstring cites the
  facade its signature was copied from (`_app/gates_facade.py:31`,
  `_app/models.py`, `_app/boot.py`, and the two in the module docstring), and
  citing them is the whole basis of "copied from the live facade". Measured: 5
  matches, all prose; **0 imports of `_app`**, which is what the gate meant.
  Asserted now by `TestThePortNamesNoForbiddenLayer`, which reads the import
  lines rather than the file.
  **And the blind spot it guards is real, measured:** with a live
  `if TYPE_CHECKING: from functualize._app.di_facade import DependencyFacade`
  in `host.py`, `uv run lint-imports` reports **"7 kept, 0 broken"**. So
  `layer-contract-blind-spot.md` §7 is not a theoretical worry here, and
  AC-1b cannot be held by `lint-imports` alone.
- **Gate** `wc -l src/functualize/_types/protocols.py` — ~~`now: 882` ·
  `after: 882`~~ → **888 · 888**. The baseline moved because **T3** added six
  lines to `EngineHost.substrate_override`'s docstring, so this is drift from
  our own work rather than a mis-measurement. The gate's point holds unchanged:
  the port did not go into `protocols.py`.
- **Done** `0719a49`. Eleven port members and ten view members, both pinned by
  tests, along with the six members argued off the port. Three sabotages: a
  missing member fails 3 of 12 tests, a wrong signature fails only the mypy
  one, a `TYPE_CHECKING` `_app` import fails only the two import-line ones.

## T8 · Re-export and cover the public surface — [x]

`[F]` `src/functualize/plugin/__init__.py`, `tests/test_public_api_surface.py`

`from functualize._types.host import PluginHost`, add to `__all__`, and add
`"PluginHost"` to the surface test's expected set.

- **Gate** `python -c "from functualize.plugin import PluginHost; print(PluginHost)"`
  — `now: ImportError` ✅ · `after: prints` ✅
- **Gate** `uv run pytest tests/test_public_api_surface.py` — green, 43 tests,
  with `PluginHost` listed ✅. **Non-vacuous**: removing the entry from the
  expected set while leaving the export fails
  `test_no_unexpected_additions[functualize.plugin]`.
- **Decision** `PluginHost` alone is exported, **not** its five views. `app.di`
  is already typed `DependencyView` by the port, so a plugin author never has
  to name a view to write a plugin. That also keeps the example-coverage
  obligation (`contributor/guides/adding-public-api.md` step 8) at **one**
  symbol rather than seven — T15 supplies that caller.
- **Done** `c7cf866`.

## T9 · Retype the lifecycle protocols, with the door that makes it bite — [x]

`[F]` `src/functualize/_types/protocols.py`,
`tests/spec/test_adapters_conform_to_the_port.py`

`AdapterPlugin.__call__(app: PluginHost)` at :103 and
`PluginWithShutdown.on_shutdown(app: PluginHost)` at :124 — **and** the static
conformance assertions, in the same task. The retype alone is provably inert:
nothing statically accepts `AdapterPlugin` today (`validate_adapter(obj: Any)`,
tests-only), so mypy reports nothing (`contracts.md` §3).

`[F]` **the fixture is a third file:**
`tests/spec/fixtures/adapters_against_the_port.py`.

- **Gate** `rg -n ': AdapterPlugin' src plugins tests` — ~~`now: 0`~~ ·
  `after: ≥1`. **`now` is 1, not 0** — and the one hit is
  `tests/test_adapter_protocol.py:408`, *a comment heading*
  (`# Property Tests: AdapterPlugin structural typing`). The gate's point
  survives intact, and is in fact sharper: the only mention of the type in an
  annotation-shaped position was a comment.
- **Gate** the new test file type-checks and **fails before T10** — done as a
  **strict `# want-error` marker set** rather than a red test, so the tree
  stays green while the same truth is stated in both directions. Unlike an
  `xfail` it also fails when the door *stops* biting, which is the direction
  the task cared about.
  **The inert state is reproduced, not assumed:** reverting
  `__call__` to `app: Any` leaves `uv run mypy` **green on all 364 files**, and
  the door test fails with `no error at marked line(s) [54, 55, 56, 57]`.
- **Five marks, not four, and one is not T10's.** `MCPAdapterPlugin` has **no
  `run` and no `shutdown`** — two of `AdapterPlugin`'s three methods — while
  being named `…AdapterPlugin`, setting `adapter_type = "mcp"`, and claiming
  *"Implements the AdapterPlugin protocol"* in its docstring. Nothing checked,
  because it loads as a plain `functualize.plugins` entry point and never
  reaches `validate_adapter` — which `rg` shows is **called from tests only**,
  never from production. → `plugin-taxonomy`.
- **`HttpServerPlugin` is not an adapter** and is outside this door; its own
  docstring says so. T10 still widens its `app` parameter, so T10's count is
  five annotation sites across four files plus this one.
- **Reachability** `app/adapters/_validation.py:30`'s runtime `isinstance` is
  unaffected (`__call__` presence unchanged) ✅ — 74 tests green across
  `tests/test_adapter_protocol.py`, `tests/test_cli_adapter.py`,
  `tests/adapters/test_lambda_adapter.py`.
- **Done** `9aae8ef`. `protocols.py` 888 → 910 lines (the two retypes carry
  their reasoning), so T7's "did not go there" gate is unaffected.

## T10 · Widen the four concrete adapters — [x]

`[F]` `src/functualize/app/adapters/tui.py`, `src/functualize/app/adapters/cli.py`,
`plugins/functualize-http/src/functualize_http/__init__.py`,
`plugins/functualize-lambda/src/functualize_lambda/__init__.py`

`app: FunctualizeApp` → `app: PluginHost` at `tui.py:39`, `cli.py:823`,
`http:371,443`, `lambda:136`.

- **Measured, then decided.** The measurement *is* widening all five and
  reading mypy:

  | site | reaches | outcome |
  |---|---|---|
  | `functualize-http` `HttpAdapter` | `execute`, `get_job`, `get_jobs` | **widened**, 0 errors |
  | `functualize-http` `HttpServerPlugin` | `execute`, `extensions` | **widened**, 0 errors |
  | `functualize-lambda` `LambdaAdapter` | `execute` | **widened**, 0 errors |
  | `app/adapters/cli.py` `CliAdapter` | `app.name`, + `register_discovered_jobs`/`register_plugin_commands` which take the whole app | **keeps `FunctualizeApp`** |
  | `app/adapters/tui.py` `TuiAdapter` | nothing in `__call__`; `run()` hands it to `launch_inline_tui(app: FunctualizeApp)` | **keeps `FunctualizeApp`** |

  `name` is not on the port and must not be: `rg 'app[.]name' plugins/*/src
  examples/*/*/src` → **zero plugin clients**, failing the same client-count
  rule every port member had to pass. The task pre-authorised this for
  `CliAdapter`; the same argument covers `TuiAdapter`, because both live in
  `src/functualize/` and the port is the **plugin** boundary.

  ⚠️ **AC-18 says four adapters; the answer is two.** Deviation recorded here
  rather than absorbed. The two that stay are core, not plugins, and T9's
  conformance marks for them are now permanent decisions rather than pending
  work.

  Bonus, and the clearest evidence the feature does what it claims: **neither
  plugin package imports `FunctualizeApp` any more.** The annotation was its
  last use in both.
- **Gate** T9's conformance test — `now (post-T9): 4 errors` ·
  ~~`after: 0`~~ → **after: 2**, plus MCP's unrelated third. The two removed
  marks are exactly the two adapters widened.
- **Gate** `rg -c "app: FunctualizeApp" src/functualize/app/adapters plugins/*/src`
  — ~~`now: 5` · `after: 0`~~. **`now` was 25, an undercount by 20**: only 5
  were adapter `__call__` sites, the other 20 being module-level core helpers
  in `cli.py` (13) and `click_params.py` (3) plus the `_app` attributes.
  `after: 0` is unreachable. Real result: **18, all core**, and **0 in
  `plugins/*/src`** — which is the half the gate was reaching for.
  Sixth mis-written grep gate.
- **Reachability** the widening is load-bearing: removing `execute` from the
  port fails **3 sites across both plugins** (`functualize_lambda:200,237`,
  `functualize_http:210`); removing `extensions` fails `functualize_http:456`.
  Under `app: Any` neither was reported.
- **Done** `3768d24`. http 59 tests, lambda 55, `tests/spec` 13; mypy green on
  364 core files and on both plugin packages; lint-imports 7 kept / 0 broken.

## T11 · Annotate the forty `Any` sites — [x]

`[F]` the hit set of `.spec/features/plugin-host-protocol/count_app_annots.py`
(40 `Any` params across `plugins/*/src`)

- **Gate** the census ✅ exactly as specified:
  `now: TOTAL 44 / Any-typed 40 / PluginHost 4 / 91%` ·
  `after: TOTAL 44 / Any-typed 0 / PluginHost 44 / 0%`.
  (The `now` line reads `PluginHost 4`, not `FunctualizeApp 4`, because **T10
  already widened those four** — the four in `functualize-http` and
  `functualize-lambda`.)
- **Gate** package-local mypy, never the aggregate (AC-20) ✅. The aggregate is
  **116** errors, not the 120 the task claims — T1, T2, T6 and T10 removed
  four. Baselines before → after:

  | package | before | after | |
  |---|---|---|---|
  | `functualize-ai-pydantic` | 47 | **48** | +1, cause upstream — see below |
  | `functualize-state-sqlite` | 1 | **0** | improved by the port |
  | `functualize-ai` | 4 | 4 | |
  | `functualize-mcp` | 13 | 13 | |
  | `functualize-inline` | 41 | 41 | |
  | `functualize-aws` | 6 | 6 | |
  | `functualize-http` / `-lambda` | 0 | 0 | |
  | bitwarden / flow-viz / tasks-local / tasks | 1 | 1 | each |

  **`state-sqlite` 1 → 0**: `resolved.db_path` was `Any`; the port's
  `resolve_model(...) -> object` forces the caller that named the model class
  to narrow to it, and the `no-any-return` went away. The feature paying for
  itself.

  **`ai-pydantic` 47 → 48**, and the cause is not this task. It hands `AI` and
  `AIConfig` to `di.provide` and `configuration.resolve_model`, and those names
  are **lazy-import variables, not types**: `functualize_ai/__init__.py`
  resolves them through a `__getattr__` table with no `TYPE_CHECKING` block, so
  mypy says `Variable "functualize_ai.AIConfig" is not valid as a type`. That
  is also where most of its 47-error baseline comes from. **Adding that
  `TYPE_CHECKING` block is worth doing and belongs in `functualize-ai`** — not
  in an annotation sweep. → owed elsewhere.
- **Reachability** two sabotages of the port, measured per package:
  removing `di` → **5 errors** (ai-pydantic 2, mcp 2, tasks-local 1); keeping
  `di.provide` but making `qualifier` **required** — the right name with the
  wrong signature, which `isinstance` can never catch → **4 errors**
  (ai-pydantic 2, mcp 1, tasks-local 1). Under `app: Any`, neither sabotage
  produced a single error anywhere.
- **Three sites were secretly optional.** `_gate_strategy.py:60`,
  `_schema_export.py:54`, `_translator.py:20` were `app: Any = None` — a `None`
  default under a non-optional annotation, invisible while the annotation was
  `Any`. Now `PluginHost | None`, which is what they always were.
- 🚩 **A fourth dead probe, and it is a behaviour bug.**
  `functualize-ai/_provider_discovery.py:205` guards on
  `hasattr(app, "resolve_model")`, which is **always False** — measured against
  a live app; `resolve_model` is on `app.configuration`, never on the app. So
  `resolve_ai_provider` has **never** read the `[ai]` config section, and every
  caller passing an `app` has silently received `AIConfig()` defaults. Same
  shape as the two probes AC-7 deleted (T1, T2).
  **Left standing**, and the decision is taken: *"Lets fix pydantic-ai issue
  during plugin taxonomy"* (maintainer, 2026-09-17). So both AI-package
  findings go to `plugin-taxonomy`:
  1. this dead `hasattr(app, "resolve_model")` probe, whose fix changes
     behaviour (an `[ai]` section would start being honoured);
  2. `functualize_ai/__init__.py`'s lazy `__getattr__` table with no
     `TYPE_CHECKING` block, which is why `AI`/`AIConfig` are variables rather
     than types and why `ai-pydantic` sits at 47–48 mypy errors.
  Stated at the site in `_provider_discovery.py` so the next reader is not
  misled by a probe that looks live.
- **The one excluded member is now one visible line.**
  `_workflow_tools.py:449` reaches `execution_engine` for `materialize_job`,
  the single client that did not earn the engine a port seat. A `cast` at that
  line rather than `app: Any` on the constructor, so the class's other five
  methods keep eleven checked members. Behaviour unchanged.
- **Done** `57efc55`. All twelve plugin suites green (436 tests).

## T12 · Make the rule executable — [x]

`[F]` ~~`tests/spec/test_the_port_is_not_leaked.py`~~ →
**`tests/spec/test_the_plugin_host_cannot_be_bypassed.py`** +
`tests/spec/fixtures/the_host_cannot_be_bypassed.py`.

The named file is **`store-substrate`'s**, about the *substrate* port and the
filesystem. Sharing it would give one file two unrelated reasons to change —
the *divergent change* smell that decided this port's own home (`spec.md` §E3).

A static negative test: a misspelled `PluginHost` member is a mypy error, and a
`PluginHost`-typed parameter cannot reach `_di_registry`. **Nine refusals**, not
two — every member argued off the port in `contracts.md` §1 is checked, plus
both of the original reaches and a misspelling one level down inside a view.

**The fixture carries the positive half too**: nine calls a shipped plugin
really makes, which must type-check clean. A port that refused everything would
pass a negatives-only file while being useless.

- **Gate** the file fails when the misspelling is corrected to a real member ✅
  — correcting `app.dii` to `app.di` fails **two** tests: the refusal-case
  inventory (`refusal case(s) removed from the fixture: ['app.dii']`) and the
  marker comparison. Adding `execution_engine` back to the port fails **three**
  across two files, T7's member pin and exclusion pin included.
- **Gate** ~~documents the second pass: `FUNCTUALIZE_TEST_SUBSTRATE=sqlite`~~ —
  **not applicable, and copied from `store-substrate`.** That flag selects a
  second *substrate implementation*; this port has one implementation
  (`FunctualizeApp`), so there is no second pass to document. Nothing was run
  for this gate and nothing could be.

## T13 · Documentation, ADR and the counts — [x]

`[F]` `contributor/guides/plugin-development.md`, `docs/guides/hooks.md`,
`docs/guides/workflows.md`, `docs/examples/plugins/custom-state-backend.md`,
`contributor/adr/020-engine-entrypoint-encapsulation.md`,
`src/functualize/_app/__init__.py` *(if the new module needs an export)*,
`contributor/architecture/dependency-graph.md`, `pyproject.toml`,
`.spec/CONSTITUTION.md`, `contributor/architecture/codemaps/dependencies.md`

- `plugin-development.md:53-70` — teaches `app: Any` **and** names two members
  that do not exist (`app.provide`, `app.register_plugin_command`)
- `hooks.md:257-261` — second surface teaching the raw registry
- `workflows.md:382` — `app.substrate = …` must become `install_substrate(…)`
- `custom-state-backend.md:58,61` — uses **both** the raw registry and the
  removed setter; missed by the previous task list
- **ADR-020** records `EngineHost`, so the `substrate` → `substrate_override`
  rename belongs there (AC-15)
- `dependency-graph.md` gains `_types/host.py`
- **AC-21**: `pyproject.toml:236` and `CONSTITUTION.md` say six contracts,
  `codemaps/dependencies.md:25` says five, there are **seven**

- **Gate** `rg -c "app: Any" contributor/guides/plugin-development.md` —
  `now: 1` · `after: 0` ✅. And the guide taught **two members that do not
  exist**: `app.provide` and `app.register_plugin_command`, both `hasattr`
  False on a live app. All three members it now teaches resolve.
- **Gate** `grep -c '^\[\[tool.importlinter.contracts\]\]' pyproject.toml` = the
  number the prose claims ✅ — **seven**, and three documents disagreed:
  `pyproject.toml:236` "six" *(in the same file as the contracts it
  miscounted)*, `CONSTITUTION.md:11` "six",
  `codemaps/dependencies.md:25` "five" **and a list naming five of seven** — so
  list and prose agreed with each other and both were wrong. All three fixed,
  the list completed, and **made executable** beyond the task's hand-run grep in
  `tests/spec/test_the_contract_count_is_one_number.py`: restoring each old
  number fails that document's case.
- **Also fixed, not in the file list:** `contributor/adr/022-…md:75` told plugin
  authors to install "via `EngineHost.substrate`", the name T3 split in three
  (found during T3, absent from this task's list); ADR-020 gained a note that
  `EngineHost` has since acquired a storage member, had it renamed, and grown a
  peer; `dependency-graph.md` gained *The Two Ports in `_types/`*.
- **Done** `9a089c0`.
- **Gate** `rg -c "hook_registry" docs/ contributor/guides/` — ~~`now: ≥3` ·
  `after: 0`~~. **`after: 0` would delete the documentation of a public
  method.** Measured at T6: **27 matches in `docs/`**, of which
  `docs/guides/hooks.md:114` is the `### register_global` reference section
  *for* `HookRegistry.register_global`, and most of the rest document hook
  events T6 does not touch (`BEFORE_JOB`, `ON_TEARDOWN`, `PRE_EXECUTE`,
  `JOB_REGISTERED`, `INVOKE_START/END`, `ON_SCOPE_CREATED`, `TUI_STARTED`).
  `register_global` remains the supported way to register those; the facade is
  the typed door for `on_ready` only (T5 typed one member of fifteen).
  So the honest target is: **`APP_READY` examples become `app.hooks.on_ready`**
  — `hooks.md:261` and `custom-state-backend.md:58` — and everything else
  stays. Re-derive the count from `rg -n 'register_global\(HookEvent.APP_READY'`
  rather than from `hook_registry`.
- **Note, T6's residue.** `docs/examples/plugins/custom-state-backend.md:58` is
  a **mirror of the example's own README**, which T6 updated. Between T6 and
  T13 that page teaches code the example no longer contains. Disclosed rather
  than silently fixed early, because `docs/` is this task's scope; the example
  itself (`examples/plugins/custom_state_backend/README.md`) is already
  correct.
- **Gate** `grep -c '^\[\[tool.importlinter.contracts\]\]' pyproject.toml` = the number the prose claims — `now: 7 vs "six"` · `after: 7 vs "seven"`

## T14 · Scaffold templates — both of them — [x]

> **"Both" verified at T6.** `find src/functualize/_cli/scaffold/templates
> -name '*plugin*.j2'` returns **six** files, but only two annotate a host:
> `domain-plugin/_plugin.py.j2:20` (`app: Any`) and `plugin.py.j2:18`
> (`app: FunctualizeApp`). The other four take `rc: RunContext`
> (`file_plugin.py.j2:24`, `job-folder/file_plugin.py.j2:26`) or no such
> parameter at all (`domain-plugin/test_plugin.py.j2`,
> `plugin-project/plugin.py.j2`). `plugin.py.j2:34` also carries a
> **commented-out** `app.hook_registry.register_global("before_job", …)` —
> a job hook, not `APP_READY`, so T6 leaves it alone.

`[F]` `src/functualize/_cli/scaffold/templates/plugin.py.j2`,
`src/functualize/_cli/scaffold/templates/domain-plugin/_plugin.py.j2`

- **Gate** `rg -n 'app: (Any|FunctualizeApp)' src/functualize/_cli/scaffold/templates/`
  — `now: 2` · `after: 0` ✅. The alternation mattered exactly as the task
  warned: the two templates were wrong in *different* ways, so a one-spelling
  pattern would have passed one of them.
- **Gate** a scaffolded plugin type-checks against the port out of the box ✅ —
  **actually scaffolded**, through `func builtin scaffold add plugin` in both
  its forms (bare, and `--domain ai --name my-provider`), then `mypy --strict`
  clean, `ruff check` clean, `ruff format --check` clean, and `register(app)`
  called against a live `FunctualizeApp`.
  `ruff check` needed one extra fix to be true: the simple template put **two**
  blank lines between its import and the following comment (`I001`).
  Pre-existing — the old `FunctualizeApp` version produced it too.
- **Beyond scope, added:** `tests/scaffold/test_plugin_templates_annotate_the_port.py`
  makes AC-11 executable rather than a hand-run grep. Four checks, and the grep
  is the weakest: that **exactly two** of the six `*plugin*.j2` templates take a
  host (so a third cannot appear annotated `Any` unnoticed), that neither names
  `Any`/`FunctualizeApp`, that the **rendered AST** annotates `PluginHost` (so a
  docstring mention does not satisfy it), and that the rendered file passes
  `mypy --strict` importing the real port.
  Sabotage: reverting the domain template to `app: Any` fails **three of four**,
  each naming that template — including the mypy one, which also catches that
  `Any` is then unimported.
- **Done** `c85e6b7`. All 261 existing scaffold tests still green.

## T15 · The example (AC-22) — [x]

`[F]` `examples/standalone/<topic>/plugin_host/` (+ its `test_*.py`)

The first public symbol subject to
`contributor/reference/public-api-example-coverage.md`. The example must **call**
the port — import `PluginHost`, annotate a plugin function with it, register and
run — not merely name it.

- **Gate** `uv run pytest examples/` — `now: green` · ~~`after: green, one test
  more`~~ → **green, 204 → 212**. Eight, not one: the port's refusals and the
  budget's own behaviour are separate claims, and the example has to *do*
  something or it demonstrates nothing.
- **Gate** the coverage census: `PluginHost` is not in the uncovered set ✅
- **Note** ~~this AC does not reduce the 108-symbol backlog; it declines to add
  to it.~~ — **it reduces it.** Measured: public `__all__` **161 → 162** symbols
  with uncovered **108 → 105**, and the `FunctualizeApp`-members half moved
  further, **29 → 21** uncovered of 40 distinct. Eight members left that list,
  and they are the ones the rule's own note singled out: *"the six typed facades
  are the headline of the post-#39 plugin surface, and no example touches four
  of them."* This is that example. `public-api-example-coverage.md`'s baseline
  table is updated, which is what it asks for.
- **Design forced by the code, worth recording:** the first draft asserted the
  DI registration by reading it back through `app.di`. That does not work —
  `DependencyFacade` is **write-only**, which is the asymmetry that drove two
  plugins into `app._di_registry` in the first place. The example now checks it
  the way a user observes it: a job run through `app.execute(...)` collecting
  the capability with `rc[JobBudget]`.
- **Reachability** both halves sabotaged in the example: deleting
  `app.hooks.on_ready(...)` fails the two `TestTheReadyHookRan` tests; deleting
  `app.di.provide(...)` fails the two `TestWhatTheJobSees` tests.
- **Done** `b95a94a`.

## T16 · Verify — [x]

`[F]` — (no source files)

- `uv run pytest` (root), `uv run pytest examples/`, and **each**
  `plugins/*/tests` package separately — they cannot be collected together
- `FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest` — the pass that exercises
  the renamed install path. A single green run does not cover T3/T4.
- `uv run lint-imports` → 7 kept, 0 broken
- `uv run mypy src/functualize` → green
- plugin type-checks **package-local**, each against its own recorded baseline;
  never the aggregate `uv run mypy plugins/*/src` (120 errors before this
  feature)
- `uv run ruff check` and `uv run ruff format --check`
- the orphan scan (`/agentic-verify`'s serena pass): nothing this feature added
  is unreachable

### Results

| Check | Result |
|---|---|
| `uv run pytest` (root) | **10,681 passed**, 1,601 skipped, 0 failed |
| `uv run pytest examples/` | **212 passed** (was 204) |
| each `plugins/*/tests` separately | **436 passed**, 1 skipped, 12 packages |
| `uv run lint-imports` | **7 kept, 0 broken** |
| `uv run mypy` | **green, 364 files** |
| `uv run ruff check src/ tests/ plugins/ examples/` | clean (CI's scope) |
| `uv run ruff format --check src/ tests/ plugins/ examples/` | 1,440 formatted |
| plugin mypy, package-local | all at baseline but two: `state-sqlite` **1 → 0**, `ai-pydantic` **47 → 48** (cause upstream, → `plugin-taxonomy`) |
| `FUNCTUALIZE_TEST_SUBSTRATE=sqlite … --run-slow` | 12,035 passed, **4 failed — pre-existing** |

**The four sqlite failures are not this feature's, and that was proved rather
than argued.** `tests/integration/test_crash_and_resume.py` (2) and
`test_notify_exactly_once.py` (2) fail at
`assert scope and scope.get("lease"), "the crashed runner left no lease"`.

Proof: a throwaway worktree at `origin/master` (`11d77f6`), synced and run with
the same command, fails **the same four**. This branch never touched either
file.

Mechanism, for whoever owns `store-substrate`'s second pass:
`tests/conftest.py::_alternate_substrate` is an **in-process `monkeypatch`** of
`JsonFileSubstrate.for_project`. These four tests spawn a real runner and
SIGKILL it. A subprocess does not inherit a monkeypatch, so the child writes
its lease through `JsonFileSubstrate` while the parent reads `SQLiteSubstrate`
and finds nothing. The fixture's docstring anticipated subprocesses — *"a
second process cannot see another's dictionaries"* — and chose SQLite to solve
shared *visibility*; it does not solve patch *inheritance*. → owed elsewhere.

**Bare `uv run ruff check` reports 7, and all 7 are outside CI's scope.** CI
runs `ruff check src/ tests/ plugins/ examples/`. Three are `SIM105` in
`.claude/hooks/*.py`, present on master and untouched by this branch (only
`.claude/**/*.md` changed here). The other four were in this feature's own
`count_app_annots.py`, now fixed — it also gained the docstring explaining why
it is an `ast` walk and not an `rg`.

**Orphan scan.** Every symbol this feature added has a production consumer:

| Symbol | Production files | |
|---|---:|---|
| `PluginHost` | 26 | |
| `install_substrate` | 6 | |
| `OnReadyHandler` | 5 | |
| `substrate_override` | 4 | |
| the five views | 1 each | **see below** |

The five views are named **only** in `host.py` (plus a comment in
`plugin/__init__.py`), which reads like an orphan and is not one: their
consumer is `PluginHost`'s own member annotations, and mypy applies them to
every `app.di.provide(...)` in every plugin. Demonstrated, not asserted —
removing `ConfigurationView.resolve_model` produces an error in **four**
plugin packages (`ai`, `ai-pydantic`, `mcp`, `state-sqlite`), and making
`DependencyView.provide`'s `qualifier` required produces four more. A symbol
whose deletion breaks four packages is reachable.

## Task Dependency Graph

```json
{"waves": [
  {"id": 0,  "tasks": ["T1", "T2"]},
  {"id": 1,  "tasks": ["T3"]},
  {"id": 2,  "tasks": ["T4"]},
  {"id": 3,  "tasks": ["T5"]},
  {"id": 4,  "tasks": ["T6"]},
  {"id": 5,  "tasks": ["T7"]},
  {"id": 6,  "tasks": ["T8", "T9"]},
  {"id": 7,  "tasks": ["T10"]},
  {"id": 8,  "tasks": ["T11"]},
  {"id": 9,  "tasks": ["T12", "T13", "T14", "T15"]},
  {"id": 10, "tasks": ["T16"]}
]}
```

**Why this order**, where it is not obvious:

- **T1/T2 first.** Deletions before anything is shaped around code that cannot
  run — and T2 clears the file T6 then edits.
- **T3 before T7.** The port declares `substrate -> StoreSubstrate` with no
  `None`, which is only true after the rename. Declaring it earlier means
  editing the port twice.
- **T3 and T4 are separate waves** so a failure in either is attributable.
- **T5 before T6.** The migration lands on the safer signature rather than
  widening and then narrowing.
- **T9 before T10.** T9's conformance door is what turns the four concrete
  adapters into errors; T10 fixes them. Running T10 first would leave nothing
  proving the door works.
- **T8 and T9 share a wave** — both need only T7, and neither needs the other.
