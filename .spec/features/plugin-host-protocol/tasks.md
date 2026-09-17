# Tasks — plugin-host-protocol

**16 tasks / 11 waves.** Revised 2026-09-17 against the scrutiny report and the
two maintainer decisions (`plan.md` §0). Every gate below carries its measured
`now:` value, taken on `79545ef`; a gate whose `now:` does not reproduce is a
signal to re-measure before editing, not to proceed.

Wave ordering is binding. Reachability precedes `[x]` — name the production
path and break it once (`contributor/guides/wiring-discipline.md`).

---

## T1 · Delete the MCP dead probe

`[F]` `plugins/functualize-mcp/src/functualize_mcp/_task_tools.py`

Delete lines 66-76 — the `hasattr(app, 'resolve')` / `app._tasks` probe inside a
bare `except`. Both attributes are absent, so the in-memory `Tasks` fallback is
the only path that has ever run. Leave a one-line comment recording that the
block was dead, so the deletion is not read later as a removed feature.

- **Gate** `python -c "from functualize.app import FunctualizeApp as A; a=A(); print(hasattr(a,'resolve'), hasattr(a,'_tasks'))"`
  — `now: False False` · `after: False False` (unchanged; the point is that the
  probe could never succeed)
- **Gate** `rg -c "hasattr\(app, ?'resolve'\)|app\._tasks" plugins/` — `now: 2` · `after: 0`
- **Reachability** the MCP task tools still return the in-memory `Tasks`: break
  the fallback constructor and watch `plugins/functualize-mcp/tests/` fail
  (AC-7b).

## T2 · Delete the ai-pydantic dead state guard

`[F]` `plugins/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py`

Delete lines 139-148 — the `from functualize_state import StateBackend` guard
and the `app._di_registry.resolve(StateBackend)` behind it. That import raises
`ImportError` (ADR-022 retired the domain; no `plugins/functualize-state`
exists), so the line was never reached. Call `resolve_ai_state_backend(None)`
directly, which is what the `except` already did.

- **Gate** `python -c "import functualize_state"` — `now: ImportError` · `after: ImportError`
- **Gate** `rg -c "_di_registry" plugins/` — `now: 1` · `after: 0`
- **Reachability** ai-pydantic still resolves its ephemeral backend: break
  `resolve_ai_state_backend` and watch `plugins/functualize-ai-pydantic/tests/` fail.

## T3 · Rename the substrate trio

`[F]` `src/functualize/app/core.py`, `src/functualize/_types/protocols.py`,
`src/functualize/_engine/executor.py`

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
- **Reachability** `_engine/executor.py:1526`'s `chosen or substrate_for_project(...)`
  still honours an installed override: `tests/primitives/test_one_substrate_choice.py`.

## T4 · Collapse the ten chain sites

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

Also migrate the two writers to `install_substrate`:
`plugins/functualize-state-sqlite/.../_plugin.py:78` and
`tests/integration/test_substrate_durability.py:102`.

- **Gate** `rg -c "execution_engine\.substrate" src plugins tests` — `now: 10` · `after: 0`
- **Gate** `rg -c "app\.substrate *=" src plugins tests` — `now: 2` · `after: 0`
- **Do not fix** `functualize-tasks-local`'s hook-ordering bug at
  `_plugin.py:66`. That is `plugin-taxonomy`'s F4/AC-8 (`spec.md` §I). This task
  changes the **spelling only**; the bug must survive intact.
- **Reachability** `FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest tests/integration/test_substrate_durability.py`.

## T5 · Retype `HooksFacade.on_ready`

`[F]` `src/functualize/_app/hooks_facade.py`, `src/functualize/_types/host.py`

Introduce `OnReadyHandler = Callable[[PluginHost], None]` and type the property
`Callable[[OnReadyHandler], OnReadyHandler]` (`contracts.md` §5). Returning the
handler matches `_app/decorators.py:98-100`, which registers and returns `fn`.

`_types/host.py` is created here with only the alias and a forward reference;
T7 fills in the protocols. Split this way because T6 needs the type and T7
needs T3's rename.

- **Gate** the eight-case probe in `contracts.md` §5, as a focused mypy fixture
  — `now: 3 of 8 behave` · `after: 8 of 8`
- **Gate** existing `app: Any` handlers still pass — all four real handlers are
  `def _on_app_ready(self, app: Any) -> None`, verified compatible
- **Reachability** `tests/core/test_app_ready_and_shutdown.py`.

## T6 · Migrate the four APP_READY registrations

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
