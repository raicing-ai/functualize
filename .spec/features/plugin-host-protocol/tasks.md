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

## T6 · Migrate the four APP_READY registrations

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

- **Gate** `rg -c "hook_registry.register_global" plugins/` — `now: 4` · `after: 0`
- **Gate** the hooks still fire at boot: each plugin's own suite
- **Reachability** break `make_on_ready_decorator`'s registration and watch all
  four plugin suites fail.

## T7 · Write the port and the five views

`[F]` `src/functualize/_types/host.py`

`PluginHost` (11 members) plus `DependencyView`, `ExtensionsView`,
`ConfigurationView`, `GatesView`, `HooksView` — signatures copied from the live
facades, exactly as listed in `contracts.md` §2, including the two documented
deviations (`resolver: Any`; `get_plugin_commands` absent).

- **Gate** `uv run lint-imports` — `now: 7 kept, 0 broken` · `after: 7 kept, 0 broken`
- **Gate** an unmodified app satisfies it, **both ways** (AC-3):
  `isinstance(app, PluginHost)` → `True`, **and** a mypy-checked assignment to a
  `PluginHost` parameter. Runtime alone proves member presence, never signatures.
- **Gate** `rg -c "_app" src/functualize/_types/host.py` — `after: 0` (no `_app`
  import, in a `TYPE_CHECKING` block or otherwise — AC-1b)
- **Gate** `wc -l src/functualize/_types/protocols.py` — `now: 882` · `after: 882`
  (the port did **not** go there; smell #3 in `plan.md` §2)

## T8 · Re-export and cover the public surface

`[F]` `src/functualize/plugin/__init__.py`, `tests/test_public_api_surface.py`

`from functualize._types.host import PluginHost`, add to `__all__`, and add
`"PluginHost"` to the surface test's expected set.

- **Gate** `python -c "from functualize.plugin import PluginHost; print(PluginHost)"` — `now: ImportError` · `after: prints`
- **Gate** `uv run pytest tests/test_public_api_surface.py` — `now: green` · `after: green with PluginHost listed`

## T9 · Retype the lifecycle protocols, with the door that makes it bite

`[F]` `src/functualize/_types/protocols.py`,
`tests/spec/test_adapters_conform_to_the_port.py`

`AdapterPlugin.__call__(app: PluginHost)` at :103 and
`PluginWithShutdown.on_shutdown(app: PluginHost)` at :124 — **and** the static
conformance assertions, in the same task. The retype alone is provably inert:
nothing statically accepts `AdapterPlugin` today (`validate_adapter(obj: Any)`,
tests-only), so mypy reports nothing (`contracts.md` §3).

- **Gate** `rg -n ': AdapterPlugin' src plugins tests` — `now: 0` · `after: ≥1` (the door exists)
- **Gate** the new test file type-checks and **fails before T10**: the four
  concrete adapters become `[arg-type]` errors naming Expected `PluginHost` vs
  Got `FunctualizeApp`. A green result here means the door is not wired.
- **Reachability** `app/adapters/_validation.py:30`'s runtime `isinstance` is
  unaffected (`__call__` presence unchanged) — `tests/test_adapter_protocol.py`.

## T10 · Widen the four concrete adapters

`[F]` `src/functualize/app/adapters/tui.py`, `src/functualize/app/adapters/cli.py`,
`plugins/functualize-http/src/functualize_http/__init__.py`,
`plugins/functualize-lambda/src/functualize_lambda/__init__.py`

`app: FunctualizeApp` → `app: PluginHost` at `tui.py:39`, `cli.py:823`,
`http:371,443`, `lambda:136`.

- **Measure first, then decide.** `cli.py:823`'s body is large. If it reaches an
  app member the 11-member port lacks, **the port does not grow**: `CliAdapter`
  is core, not a plugin, and may keep `FunctualizeApp` with T9's assertion
  scoped to the plugin adapters. Record the measurement and the decision either
  way (`plan.md` §6).
- **Gate** T9's conformance test — `now (post-T9): 4 errors` · `after: 0`
- **Gate** `rg -c "app: FunctualizeApp" src/functualize/app/adapters plugins/*/src` — `now: 5` · `after: 0 or the recorded exception`

## T11 · Annotate the forty `Any` sites

`[F]` the hit set of `.spec/features/plugin-host-protocol/count_app_annots.py`
(40 `Any` params across `plugins/*/src`)

- **Gate** `uv run python .spec/features/plugin-host-protocol/count_app_annots.py`
  — `now: TOTAL 44 / Any-typed 40 / FunctualizeApp 4 / 91%` ·
  `after: TOTAL 44 / Any-typed 0 / PluginHost 44 / 0%`
- **Gate** the plugin type-check is **package-local or focused**, never the
  aggregate: `uv run mypy plugins/*/src` is `now: Found 120 errors in 22 files`
  on an untouched tree, so no all-green claim over it is possible (AC-20).
  Record each package's own baseline before and after.

## T12 · Make the rule executable

`[F]` `tests/spec/test_the_port_is_not_leaked.py`

A static negative test: a misspelled `PluginHost` member is a mypy error, and a
`PluginHost`-typed parameter cannot reach `_di_registry`.

- **Gate** the file fails when the misspelling is corrected to a real member —
  a negative test that cannot fail is prose
- **Gate** documents the second pass: `FUNCTUALIZE_TEST_SUBSTRATE=sqlite`

## T13 · Documentation, ADR and the counts

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

- **Gate** `rg -c "app: Any" contributor/guides/plugin-development.md` — `now: 1` · `after: 0`
- **Gate** `rg -c "hook_registry" docs/ contributor/guides/` — `now: ≥3` · `after: 0`
- **Gate** `grep -c '^\[\[tool.importlinter.contracts\]\]' pyproject.toml` = the number the prose claims — `now: 7 vs "six"` · `after: 7 vs "seven"`

## T14 · Scaffold templates — both of them

`[F]` `src/functualize/_cli/scaffold/templates/plugin.py.j2`,
`src/functualize/_cli/scaffold/templates/domain-plugin/_plugin.py.j2`

- **Gate** `rg -n 'app: (Any|FunctualizeApp)' src/functualize/_cli/scaffold/templates/`
  — `now: 2` · `after: 0`. The pattern must be the alternation: a locator for
  `app: FunctualizeApp` alone silently misses `domain-plugin/_plugin.py.j2:20`.
- **Gate** a scaffolded plugin type-checks against the port out of the box

## T15 · The example (AC-22)

`[F]` `examples/standalone/<topic>/plugin_host/` (+ its `test_*.py`)

The first public symbol subject to
`contributor/reference/public-api-example-coverage.md`. The example must **call**
the port — import `PluginHost`, annotate a plugin function with it, register and
run — not merely name it.

- **Gate** `uv run pytest examples/` — `now: green` · `after: green, one test more`
- **Gate** the coverage census: `PluginHost` is not in the uncovered set
- **Note** this AC does not reduce the 108-symbol backlog; it declines to add
  to it.

## T16 · Verify

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
