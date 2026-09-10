# Entry-point coverage audit — every way a job starts, and every place behaviour can diverge

Audit of `origin/master` @ `c0c921f`, 2026-09-08. Analysis only — no `src/`,
`plugins/*/src/`, or `tests/` files were modified.

**Tools and what they produced.** Behaviour claims below were proven by running
the shipped binary (`uv run func …`, throwaway fixtures under
`/tmp/fz-audit-probe/`) unless marked `[CODE]` (read-only code evidence) or
`[INFERENCE]`. Symbol-level "who calls X" questions were answered with
**serena** (`activate_project` on the worktree root, then
`find_referencing_symbols`); dependency-edge evidence ("what depends on X")
with **graphify** (`graphify explain "<symbol>"` against the committed
`graphify-out/graph.json`); exact-string sweeps with ripgrep. **zvec-grep was
not needed**: every "why" question this audit asks is answered by prose already
read in `contributor/`, `.spec/STATUS.md`, and the ADR catalogue.

---

## Headline findings

1. **The 9-entry map in `surface-boundary.md` under-counts.** Counting from
   code, there are **17** distinct ways a job execution starts (§A): the nine
   documented, plus `python -m functualize`, the inline-TUI job runner, the
   full-screen TUI's `app.execute` path, MCP's *three* job-executing call
   sites (per-job tools, generic `run_job`, async worker), `func builtin
   parallel`, the `interactivity.job.submit` event handler, and the engine's
   own two internal recursions (workflow steps, dependency runs).
2. **`interactivity.job.submit` bypasses `FunctualizeApp.execute` and runs a
   job with no `WorkflowScope`** — the only surface that does
   (`_app/impl.py:861`, direct `app.execution_engine.execute(...)` with no
   `parent_scope`, no `workflow_scope_id`). A `@workflow` reached this way
   cannot be resumed.
3. **`--prompt-gates` and `--emit-format` are `func`-only, but neither is "about
   reaching the program".** `--prompt-gates` is never settable from a
   project's own entry point (no flag, nothing sets `app._prompt_gates`), so
   a gated walk on an app surface can never be interactively prompted — the
   exact class of defect `--scope-id` was fixed for. `--emit-format` is similarly
   absent from the app-side click group (verified: `Error: No such option
   '--emit-format'`).
4. **`Invoke`/`rc.invoke()` cannot pass group options; `app.execute` can**
   (STATUS #17 — still open). Verified signatures: `Invoke.__call__`,
   `RunContext.invoke` have no `group_option_values` parameter.
5. **MCP is internally split on group options**: the per-job tool path
   (`_server.py:272`) passes `group_option_values`; the generic `run_job` tool
   (`_tools.py:254`) and the async worker (`_tools.py:408`) do not.
6. **`RunContext` is 781 lines against a 500-LOC constraint;
   `FunctualizeApp` is 1265 against 300; `JobExecutionEngine` is 2401.**
   The facade budget in AGENTS.md is broken by 1.6×, 4.2×, and unbounded
   respectively.
7. **The single `RunStatus → ExitCode` table now has seven consumers, not
   six**: `deliver_job_result` (click surfaces), the TUI
   (`job_execution.py:271-285` — which re-derives and treats `BLOCKED` as
   success), MCP (string status), HTTP, Lambda (one shared
   `http_status_for_status`), `func builtin parallel` (`builtins.py:604`),
   and `Invoke` (raw `JobResult`).
8. **The negative-flag rule is one function, seven consumers** (graphify:
   `click_params` ×4, `tui/bar.py`, `tui/sync.py`, `cli/dispatch.py`) — the
   "five sites" of STATUS's boolean-negation work have grown to seven, all
   sharing `negative_flag_for` (`_types/naming.py:100`). The rule is shared;
   the site count is not pinned by any test.
9. **Verified live:** X1–X4 (warm-cache filters) are closed; parse failures
   still vanish on run two (#27); enum parameters still arrive as `str`
   (#38); unknown-command explanation still does not reach a project's own
   `main.py` (#37).
10. **New observation:** a `GroupOptionsConflictError` escapes boot as a raw
    traceback (exit 1) rather than a rendered failure — and in one fixture
    transition it persisted across `func builtin cache clear` and mtime
    bumps. Unattributed; see handoff note H6.

---

## A. Invocation surface inventory

Every distinct way a job execution can start, verified against code. "Entry
symbol" is where the *job run* is initiated; boot path is what the
constructing `FunctualizeApp` took.

| # | Surface | Entry symbol (file:line) | Who builds the app | Boot path | Pre-boot processing |
|---|---|---|---|---|---|
| 1 | `func <job>` | `_cli/main.py::_handle_job` (1263) → `FunctualizeApp` (1356) | `_cli` | `boot_standard`, `JobSources(lazy=True)` (1342-1345) | `_extract_global_options`, `auto_discover`, cache-first routing names, `_extract_aliases`, `detect_mode` |
| 2 | `func <group> <job>` | `_handle_group` (1164) → `_dispatch_group` (900) → `create_job_click_command` (1067) | `_handle_group` boots app (1235) | `boot_standard`, lazy | as #1; mid-path group flags consumed by `walk_group_path` (`dispatch.py:770`) **before click sees the line** |
| 3 | `func <file>.py [fn]` | `_handle_single_file` (1555) | `_handle_single_file` (1645), via a **second** `auto_discover` | `boot_standard`, lazy | PEP 723 `maybe_delegate_to_uv` (`pep723.py:216`), `import_job`, `_register_single_file_peers` (1527) |
| 4 | bare `func` | `_handle_bare` (470) | `_handle_bare` (535) | `boot_standard`, lazy | TTY → `launch_inline_tui` (`inline_tui.py:30`); non-TTY → listing |
| 5 | `func builtin …` | `register_builtin_commands` (`builtins.py:668`) | the `cli_app` callback boots one app for the whole subtree | `boot_standard` | none of `func`'s job routing; `builtin parallel` runs jobs via `app.execute_parallel` (996); `builtin workflow resume` only *deposits* gate input (927) |
| 6 | `python -m functualize` | `__main__.py` → `_cli.main:main` | same as #1–#5 | — | identical |
| 7 | a user's `main.py` + `app.cli_command()`/`app.run()` | `CliAdapter.__call__` (`adapters/cli.py:808`), `run` (875) | the user | `boot_static` if fully explicit else `boot_standard` | none — `register_callback` defaults **False** when a `cli_group` is supplied (850), so composable apps have **no pre-command globals at all** |
| 7a | — job commands in 7 | `_build_job_command` (`cli.py:326`): eager `create_job_click_command` or lazy `make_lazy_command` (`lazy_command.py:63`) | — | — | group flags ride **click params** on group nodes (`_group_option_params`, `cli.py:371`), deposited only when `parameter_source == COMMANDLINE` (400-408) |
| 8 | `app.execute(job, **kw)` programmatic | `FunctualizeApp.execute` (`core.py:573`) → `engine.execute` (621) | the user | either | none; **always** creates a `WorkflowScope` (608-618) |
| 9 | HTTP plugin | `functualize_http/__init__.py::_execute` (178) | the plugin | app-owned | JSON body → kwargs; result → `http_status_for_status` (193) |
| 10 | Lambda plugin | `functualize_lambda/__init__.py::_response` (63); fat handler (159), thin handler (197) | the plugin | `boot_static` (documented cold-start pattern) | event → kwargs; result → `http_status_for_status` (65) |
| 11 | MCP per-job tools | `_server.py::_execute_job` (272) | the plugin (server owns app) | app-owned | **passes `group_option_values`** (273) |
| 11a | MCP generic `run_job` | `_tools.py::_run_job` (254) | — | — | **does not** pass `group_option_values` |
| 11b | MCP async worker | `_tools.py::_run_async_worker` (408) | — | — | **does not** pass `group_option_values` |
| 11c | MCP gate deposit | `_workflow_tools.py::_deposit` (631) | — | — | deposits input only; the caller still invokes the job |
| 12 | `Invoke` / `rc.invoke()` | `invoke.py::_do_execute` (401); `parallel` `_run` (598) | already booted | — | `invoke_depth+1`, `parent_scope`; no `group_option_values`; parallel items get `parent_scope=None` (603) |
| 13 | Inline-TUI job execution | `_cli/tui/job_execution.py::_run_job` → `app._func_app.execute` (242) | TUI holds the app | app-owned | parses SmartBar tokens; builtins detour through click `run_builtin` (408) |
| 14 | Full-screen TUI (`FunctualizeInlineTUI`) | `inline_tui.py::_execute_command` → `app.execute` (239) | TUI holds the app | app-owned | same |
| 15 | `interactivity.job.submit` event | `_app/impl.py::on_job_submit_event` (845) → `app.execution_engine.execute` (861) | already booted | — | **no scope created** — see D-13 |
| 16 | workflow step / dependency recursion | `executor.py::_run_workflow_prelude` (1216), `_run_dependencies` (1795) | the engine itself | — | `invoke_depth+1`, `run_dependencies=False` in deps |
| 17 | `func builtin self doctor` probe | `self_cmd.py::_BOOT_PROBE` (231) | probe subprocess | app-owned | `auto_discover` + `app.refresh()` — boots, never runs a job |

Notes:

- **`boot_static` vs `boot_standard`** is decided once at
  `app/core.py:181` (`_is_fully_explicit` → `_app/impl.py::is_fully_explicit`)
  and dispatched at `core.py:186/188`. Static skips filesystem discovery,
  plugin loading, and the `ResolutionChain` (`boot.py:163-173`). Surfaces 9–11
  document `boot_static` as their cold-start path; a feature living only in
  `boot_standard` does not exist for them.
- **Two click construction paths exist per job** (`cli.py:350-365`): eager
  (`create_job_click_command`, live signature) and lazy (`make_lazy_command`,
  cached descriptor). Both converge on `deliver_job_result` — the pitfall-23
  fix. This remains the second-order split most likely to regrow a divergence.
- **The pre-boot layer belongs to surfaces 1–6 only.** Every other surface
  enters at `FunctualizeApp(...)`; anything parsed or expanded pre-boot
  (aliases, `--exclude`, `--emit-format`, `--prompt-gates`, `--scope-id` global
  form) is absent there by construction.

---

## B. Divergence matrix

Feature × surface. `✓` = honours the feature, same semantics; `✗` = does not
honour or differs; `—` = not applicable to the surface. Each divergence is a
numbered D-item below. Cells marked `[CODE]` were verified by reading the
call path end-to-end; everything else was run.

| Feature | `func <job>` / group / file / bare | app CLI (`cli_command`) | `app.execute` (programmatic) | MCP tools | HTTP / Lambda | TUI job runner | `Invoke` / `rc.invoke` | `builtin parallel` |
|---|---|---|---|---|---|---|---|---|
| `@job` `Deps` | ✓ (engine) | ✓ (engine) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Fingerprint` / freshness | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `Guards` (refusal exit 3) | ✓ verified (exit 3) | ✓ | ✓ (status only) | ✓ (status string) | ✓ (table) | ✓ | ✓ (JobResult) | ✓ |
| `Exec` (retry/run-skip) | ✓ (engine) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GroupOptions` flags | ✓ (walk_group_path) | ✓ (click params) | ✓ (`group_option_values=`) | **split: ✓ per-job, ✗ run_job** (D-5) | ✗ (D-6) | ✓ | **✗** (D-4) | ✗ (D-6) |
| `@workflow` + Gate | ✓ | ✓ | ✓ (scope) | ✓ (deposit + re-invoke) | ✓ (BLOCKED → table) | ✓ | ✓ | ✓ |
| Gate resume | ✓ `--scope-id` (3 forms) | ✓ `--scope-id` | ✓ (`scope_id=`) | ✓ (`resume_gate` + invoke) | ✓ (re-invoke w/ scope? — no channel, D-6) | ✓ | ✓ (`_propagate_scope`) | ✓ (scope per item) |
| `--prompt-gates` | ✓ | **✗** (D-1) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Capability injection (`Log`, `TTY`, `Sources`, `Live`…) | ✓ | ✓ | ✓ | ✓ (minus TTY, refused) | ✓ (minus TTY) | ✓ | ✓ | ✓ |
| Config precedence ladder | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `--force` | ✓ (deposit `app._force`) | ✓ (root callback) | **✗ no channel** (D-3) | ✗ (D-3) | ✗ (D-3) | ✓ (`force` deposit) | ✗ | ✗ |
| `--emit-format` json/ndjson/raw | ✓ | **✗** (D-2) | ✗ | — | — | — | — | — |
| Exit-code contract | ✓ (single table) | ✓ (single table) | — | ✗ string status (by design) | ✓ shared table | **~** (D-7: BLOCKED→success) | — raw JobResult | ✓ table, first failure (D-8) |
| aliases | ✓ pre-boot | ✗ (func-only by design) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| discovery filters (`--exclude`, `--require-*`) | ✓ pre-boot | ✗ (func-only by design) | ✗ (app declares `JobSources`) | ✗ | ✗ | ✗ | ✗ | ✗ |
| unknown-command explanation | ✓ | **✗** (D-9) | — | — | — | — | — | — |
| `interactivity.job.submit` scope identity | — | — | — | — | — | — | **✗ no scope** (D-13) | — |

### D-list of concrete divergences

- **D-1 `--prompt-gates` is `func`-only.** Set only by `_cli/main.py`
  (`:1369`, `:1655`, `:1248`) on `app._prompt_gates`; read by the engine at
  `executor.py:1283` via `getattr(self._app, "_prompt_gates", False)`. The
  app-side root callback (`cli.py:1024-1074`) registers no such flag, nothing
  else sets the attribute, so a project's own entry point always walks with
  `prompt_gates=False`. Per `surface-boundary.md` §4 this is *about the
  program* (gate prompting is a job-author feature) — it must align. Verified
  `[CODE]`; contrast with `--scope-id`, which exists in all three forms
  (`cli.py:1067-1071`, `click_params.py:1095-1097`).

- **D-2 `--emit-format` is `func`-only.** The engine's `Stdout` capability reads
  `getattr(app, "_output_format", "auto")` (`_engine/capabilities/stdout.py:156`),
  but the app-side click group accepts no `--emit-format` option and nothing sets
  the attribute. Verified live: `python appfail.py boom --emit-format json` →
  `Error: No such option '--emit-format'.` (probe in `/tmp/fz-audit-probe/proj`).
  An app author's only lever is `FUNCTUALIZE_CLI_OUTPUT`… which appears
  **only in help text** (`builtins.py:1961,2072,2166`) and is read by nothing
  — pitfall #1 ("resolves and displays but is wired to nothing"), instance
  `[CODE]`.

- **D-3 `--force` has no channel outside the two click surfaces.** Both CLIs
  deposit `app._force` (`main.py:1370`, `cli.py:996`) consumed at
  `click_params.py:82` (`_force_requested`) → `engine.execute(force=…)`.
  `app.execute` (`core.py:573-629`) forwards `scope_id`,
  `group_option_values`, and `kwargs` — no `force`. MCP, HTTP, and Lambda all
  call `app.execute`, so none of them can force a run. A stale job reached
  over MCP is unreachable without a CLI. `[CODE]`.

- **D-4 `Invoke`/`rc.invoke()` cannot pass group options.** Verified
  signatures: `Invoke.__call__` (`invoke.py:86-97`) has
  `config/awaits_input/available_tools/force_gate/gate_strategy/timeout`;
  `RunContext.invoke` (`runcontext.py:365-374`) has
  `_propagate_scope/timeout`. STATUS #17 — open, and the combination-matrix
  doc (`docs/guides/group-options.md`) pins the boundary as deliberate. A job
  invoking one grouped job twice with different `env` cannot.

- **D-5 MCP is split on group options.** Per-job tools:
  `_server.py:272-274` `app.execute(job_name, group_option_values=group_values
  or None, **job_kwargs)` ✓. Generic `run_job`: `_tools.py:254`
  `self._app.execute(name, **kwargs)` ✗. Async worker: `_tools.py:408`
  `self._app.execute(job_name, **kwargs)` ✗. Same adapter, three answers.
  `[CODE]`.

- **D-6 HTTP/Lambda have no group-option or scope-resume channel.** Both
  build kwargs from the request/event body only; `functualize-http`
  `__init__.py:178-193` and `functualize-lambda` `__init__.py:159/197` call
  `app.execute(job_name, **job_kwargs)`. A gated workflow reached through
  Lambda cannot be resumed through Lambda (STATUS #21's fix mapped statuses;
  the resume channel was never the question). `[CODE]`.

- **D-7 The TUI re-derives the exit table and disagrees on `BLOCKED`.**
  `_cli/tui/job_execution.py:271-285`: success set is
  `(SUCCESS, SKIPPED, BLOCKED)`; a blocked walk is rendered as an outcome of
  `"success"` with return code 0, while the process table says `BLOCKED → 5`
  (`_types/exit_codes.py:56`). Justified by the TUI being a shell (the user
  stays in it), but it is a second, hand-written translation site — the doc's
  "six sites, two of which share a table" is now seven sites, one of which
  disagrees.

- **D-8 `builtin parallel` is a seventh translation site.** `builtins.py:604`
  exits with `exit_code_for_status(failed[0].status)` — an 8th consumer of
  the table beside the TUI's hand-rolled one. And its items never reach
  history: `execute()` records only `invoke_depth == 0` (`executor.py:705`),
  while `execute_parallel`'s items run at `invoke_depth+1`
  (`invoke.py:598`) — STATUS #5, still open. `[CODE]`.

- **D-9 Unknown-command explanation is `func`-only in practice.** Both
  reporters call `explain_missing_job` (`main.py:1449-1451`,
  `cli.py:741-743`), but a project's own entry point invokes click in
  standalone mode and click's `UsageError` fires before either runs.
  Verified live: `python appmain.py nosuchcmd` → click's
  `No such command 'nosuchcmd'.` (exit 2); `func nosuchcmd` → explanation +
  fuzzy suggestions (exit 1). STATUS #37 — open.

- **D-10 Enum parameters arrive as `str` on the CLI.** Verified live:
  `def paint(color: Color)` with `Color(RED="red")`; `func paint.py paint red`
  prints `type: str value: red`; programmatic `app.execute("paint",
  color=Color.RED)` passes the member through untouched. `_click_type_for`
  renders a `click.Choice` of member values and nothing converts back.
  STATUS #38 — open.

- **D-11 Single-file mode is hostage to CWD module side effects.** Verified
  live, twice: `_handle_single_file` boots a second app whose discovery
  imports CWD `*.py` files, so a stray CWD script with a module-level
  `app.cli_command()` hijacked the run and surfaced as
  `Error: No such command '<target>.py'` (exit 2) — the target file was never
  reached. This is the documented "import-time side effects" escape hatch
  (`developer-modes.md:48`) turned into a routing failure; the misleading
  error is the part worth recording.

- **D-12 `GroupOptionsConflictError` escapes as a raw traceback.** A project
  with two `GroupOptions` classes bound to one group dies during
  `boot_standard` (`cached_provider.py:916`) with a full traceback and exit 1
  — the discovery-failure-is-not-fatal surface of ADR-018 applies to module
  *reads*, not to group-option conflicts. Verified live (exit 1).

- **D-13 `interactivity.job.submit` runs jobs without a scope.**
  `_app/impl.py:845-866` calls `app.execution_engine.execute(...)` directly —
  the only non-engine caller that skips `FunctualizeApp.execute`, whose whole
  job is scope creation (`core.py:606-628`). A `@workflow` invoked through
  this event walks with no `parent_scope`/`workflow_scope_id`; gates that
  pause for input have nothing to resume by. `[CODE]`.

### Feature-counted sites (the "count ALL of them" rows)

- **Flag rendering / negative-flag spelling**: one rule,
  `negative_flag_for` (`_types/naming.py:100`), **seven consumers** (graphify
  `explain "negative_flag_for"`, EXTRACTED): `build_click_params_from_fields`
  (`click_params.py:266`), `_config_option_params` (`:552`),
  `_option_from_marker` (`:619`), `build_click_params` (`:820`),
  `SmartBar.evaluate` (`tui/bar.py:295`), `_group_flag_tokens`
  (`tui/sync.py:134`), `_negative_aliases` (`dispatch.py:736`). STATUS's
  boolean-negation work recorded five sites; two more exist today, all on the
  shared rule. Group-flag *rendering* additionally happens in
  `_render_group_option_rows` (`main.py:876`, from the same click params) and
  the MCP translator merges group fields via `job_input_schema`
  (`_translator.py:237`) — the ADR-010 single-schema renderer holds.
- **RunStatus → output translation**: seven sites, listed in D-7/D-8 and the
  matrix; two share the exit table, two share `http_status_for_status`, MCP
  and the TUI each re-derive.
- **Dependency resolution**: one `JobGraph` over
  `RegisteredJob.dependencies` (`executor.py:1681-1692`, `job_graph.py:130-136`),
  fed by `declared_dependency_names` at registration
  (`_app/boot.py:1479`, `impl.py:721`, `providers.py:680`, `registry.py:435`,
  `sync.py:304`). The "three disagreeing resolvers" of STATUS are closed;
  five registration sites write one field into one graph.
- **Log format**: both pre-exec surfaces set `format="%(message)s"`
  (`main.py:1995`, `cli.py:967`) — the two-surface fix holds `[CODE]`.

---

## C. Encapsulation leakage scoreboard

One row per leak: who reaches in, what they touch, why (if discoverable).
Pure observation — no redesign here.

| # | Who reaches in | What they touch | Evidence | Smell label |
|---|---|---|---|---|
| C-1 | `FunctualizeApp` (app layer) | `engine._registered_jobs.pop(name)` on refresh | `core.py:495` | Law of Demeter / Message Chain — the app re-implements registry eviction inside the engine's map |
| C-2 | `FunctualizeApp.refresh` | writes `engine._resolution_chain = …` | `core.py:514` (and `boot.py:701`) | the engine's config dependency is a public write-back field, not a setter |
| C-3 | `_app/boot.py` (both paths) | sets `engine._app = app`; `engine.add_registry_mirror(app.job_registry._registered_jobs)` | `boot.py:286-288`, `498-500` | composition root back-reference into the engine, plus a mirror of the registry's private map |
| C-4 | `_engine.executor` (kernel) | reads **delivery-layer deposits** off the app: `getattr(self._app, "_prompt_gates", False)` (`:1283`), `getattr(self._app, "_output_format", "auto")` (`stdout.py:156`) | — | the deposit contract (`_output_format`, `_prompt_gates`, `_force`, `_workflow_scope_id`) is an untyped, undocumented cross-layer protocol; a kernel reading `_cli`-style attributes is delivery state leaking in |
| C-5 | `_app/impl.py::on_job_submit_event` | calls `app.execution_engine.execute` directly, skipping `app.execute` | `impl.py:861-866` | Feature Envy + invariant bypass (scope creation lives in `core.py:606-628`) — see D-13 |
| C-6 | `app/adapters/click_params.py` | imports `JobExecutionEngine` for an `isinstance` guard; imports `_engine.missing_value.MissingValueError` | `click_params.py:1068-1090`, `1192` | delivery layer reaching into kernel internals (serena: `click_params.py` imports `executor.py` EXTRACTED) |
| C-7 | `app/adapters/lazy_command.py` | imports `_engine.capabilities.tty.terminal_available` | `lazy_command.py:80` | same; duplicated with C-6's TTY pre-flight (`click_params.py:1072-1083`) — the TTY question is answered in two files |
| C-8 | `app/adapters/surface_gate.py` | imports `_engine.ambient.has_eligible_ambient` | `surface_gate.py:37` | delivery layer importing engine policy |
| C-9 | `app/core.py` (explain path) | imports `_engine.explain`, `_engine.guards`, `_engine.preflight`, `_primitives.state_store`; calls `engine.materialize_job`, `engine._declared_dep_names` | `core.py:711-822`, `808` | a second "would this job run" implementation (for `func why`) beside the engine's own preflight — Divergent Change on the freshness rule |
| C-10 | `app/core.py::execute_parallel` | constructs `WiredInvoke` directly from `_engine.capabilities.invoke` | `core.py:663-682` | public facade instantiate kernel capability |
| C-11 | `_cli/tui/job_execution.py` | holds `app._func_app`; pokes `app._pending`, `app._snapshot_store` | `job_execution.py:84-85, 253-255` | TUI reaches through the inline-TUI facade into the app's private state |
| C-12 | `app/utils.py` | the sanctioned funnel: re-exports ~30 internal names from `_primitives`, `_types`, `_config.merge` | `utils.py:23-77` | sanctioned dogfooding bridge (the only way `_cli` may touch internals) — but it means `app` is a public facade whose `utils` module is an internal dumping ground; every internal name here is now public API by accident |
| C-13 | `_cli/` runtime imports of `_`-packages | **zero** — AST-checked across all of `src/functualize/_cli`; four hits are `TYPE_CHECKING`-only | `live_panel_widget.py:41`, `panel_live_zone.py:43-44`, `job_browser.py:19` | clean — the `_cli uses public API only` contract holds at runtime |
| C-14 | Size drift | `RunContext` **781 lines** (117–898) vs the 500-LOC facade cap in AGENTS.md; `FunctualizeApp` **1265 lines** (64–1328) vs 300; `JobExecutionEngine` **2401 lines** (157–2557), 60+ methods | measured | Large Class on all three; `RunContext` grew beyond "thin facade delegating to capabilities" — it now owns log-level validation, the capability map, history metadata, and the invoke delegation |

`RunContext`'s 781 lines are the sharpest finding: the constraint exists
precisely because a facade that outgrows its budget stops being a facade, and
the engine has no owner left to keep it honest.

---

## D. Recurring-issue ledger

Cross-reference of `.spec/STATUS.md` + ADR catalogue against the tree at
`c0c921f`. RESOLVED = closed and verified in code or by running; REGROWN =
closed then re-opened; UNTOUCHED = still open with evidence.

| Issue (source) | Verdict | Evidence |
|---|---|---|
| Discovery cache not filter-aware — X1–X4 (STATUS Next-Cut) | **RESOLVED** | Reproduced the full X1–X4 matrix live at HEAD: cold `--exclude` correct; warm `--exclude` excludes; config filter added after warm takes effect; filtered-then-unfiltered restores the job. `discovery_hash` wired at `boot.py:518` (computed **every** boot, so dropping a filter invalidates). |
| F2: `cache rebuild` writes `discovery_hash: null` (ADR-011) | **RESOLVED** | `builtins.py:689-696` — `_build_provider_for_cwd` now builds from `resolve_cli_config(...).discovery` and its docstring records the old null-fingerprint failure mode. |
| F3: child writes parent's cache (ADR-011) | **RESOLVED** | `boot.py:1146-1157` — child provider gets `ancestor_search=False`; the comment records both halves of the old clobber. |
| Child providers get no discovery config / `read_group_options_from_cache` cannot honour the fingerprint (STATUS follow-ups) | **UNTOUCHED** | Child provider still receives `discovery_hash_from_config(None)` (`boot.py:1157`); `read_group_options_from_cache` (`utils.py:1589`) takes `(cache_path)` only — no fingerprint argument, no call site can supply one. |
| Parse failure disappears on run two — #27 | **UNTOUCHED** | Verified live: run 1 reports `SyntaxError: invalid syntax`; run 2 (warm) reports nothing; a `ModuleNotFoundError` in the same tree repeats on every run. |
| `rc.invoke` cannot pass group options — #17 | **UNTOUCHED** | Verified signatures (D-4). |
| Enum parameter arrives as `str` — #38 | **UNTOUCHED** | Verified live (D-10). |
| Unknown-command explanation misses app entry points — #37 | **UNTOUCHED** | Verified live (D-9). |
| Parallel items missing from history — #5 | **UNTOUCHED** | `executor.py:705` (`invoke_depth == 0` gate) vs `invoke.py:598` (items at depth+1). `[CODE]` |
| `get_missing_required_args` has no production caller — #13 | **UNTOUCHED** | Only references: `_cli/tui/__init__.py:27,72` (import + `__all__`) and its own module. The live answer comes from `SmartBar.evaluate` (`bar.py`). |
| `omit_defaults` has no caller — #14 | **UNTOUCHED** | `build_command_line` keyword exists; no production `True` caller found. `[CODE]` |
| `remote_first()` resolves nothing remotely — #16 | **RESOLVED** | ADR-016 wired it: vault seam + `func builtin vault` subtree exist (`builtins.py:202-215`); preset raises when no remote provider is registered. |
| Lambda reports every failure as HTTP 200 — #21 | **RESOLVED** | Both trigger plugins consume `functualize.types.http_status_for_status` (`functualize-http/__init__.py:30`, `functualize-lambda/__init__.py:39`); lambda `_response` maps status at `:65`. |
| `tui.default_surface` inert until shell import — #22 | **UNTOUCHED** (test discipline RESOLVED) | `register_settings(*tui_settings())` still runs as an import side effect (`_cli/tui/__init__.py:88`); `test_the_setting_is_inert_until_the_shell_registers_it` (`tests/adapters/test_surface_gate.py:154`) pins the gap so closing it fails the test. The product gap itself is open. |
| Boolean-flag negation: "five flag-rendering sites" | **RESOLVED, count moved** | One rule (`naming.py:100`), **seven** consumers today (graphify list in §B). The parity guarantee (one rule, many sites) holds; the site count is unpinned. |
| Three disagreeing dependency resolvers | **RESOLVED** | One `JobGraph` over one `dependencies` field (§B feature-count). |
| `test_env_override_opens_the_gate` sharding flake — #22 original | **RESOLVED** | The amended test asserts against `_BASE_SETTINGS`; present at `test_surface_gate.py:154`. |
| Job-name collisions silent on lazy path — #32 / eager-boot-provider — #30 | **RESOLVED** | `register_descriptors` (`boot.py:1218`) is called by both boot paths; `CACHE_VERSION` 20 (entry key `source_file::python_name`). Not re-run here; STATUS records the gates. |
| Matrix declaration surface (`@job(matrix=…)`) | **RESOLVED** | STATUS records `TypeError` + `CACHE_VERSION` 18; no `matrix=` surface found in a sweep of `job/decorators.py`. |
| ADR-001 interactivity collapse / ADR-004 shell convergence | **RESOLVED** | No `InputProvider`/`OutputRenderer` remains; Typer absent (`test_typer_isolation.py` asserts absence); `builtin` subtree only. Plugin namespaces still absent from the discovery cache (`main.py:779-782`) — recorded as deferred in STATUS, **UNTOUCHED** for pre-boot visibility. |
| Dead `config_class` argument at the workflow `run_step` seam (0.1.1 review #13) | **UNTOUCHED** | `executor.py:1221` passes `config_class=entry.config_class`; `execute()` re-derives at `:390` (`entry.config_class or detected_config`). Line numbers moved; the dead argument is still there. |
| Shell completion model unification — #4 | **UNTOUCHED** | `shell-init` (`builtins.py:1115-1116`) and `SmartBar` completion consume the same trie but compute partitions independently; no `_cli/completions/shared.py` exists. `[CODE]` |
| `GroupOptionsConflictError` raw traceback at boot | **NEW** (not in STATUS) | Verified live, exit 1, full traceback from `cached_provider.py:916`. ADR-018's "reported, not fatal" surface does not cover it. |
| Stale group-options binding surviving cache repairs | **NEW, unattributed** | During fixture transitions, a `GroupOptionsConflictError` naming two files persisted across `func builtin cache clear` and `touch`+mtime bumps. Final state self-healed. Exact mechanism not pinned — handoff H6. |

---

## Handoff notes for the depth audit

The ten most promising evidence trails, each with file:line and one sentence.

1. **`interactivity.job.submit` scope bypass** — `_app/impl.py:861` calls
   `app.execution_engine.execute` without the scope creation that
   `core.py:606-628` exists to guarantee; this is the one surface where
   "every run has a WorkflowScope" is false, and it is an engine-invariant
   leak the encapsulation redesign must own (D-13, C-5).
2. **The deposit protocol** — `executor.py:1283` (`_prompt_gates`) and
   `_engine/capabilities/stdout.py:156` (`_output_format`) are the kernel
   reading delivery attributes; `--prompt-gates`/`--emit-format`/`--force` being
   deposit-only is why app.execute/MCP/HTTP/Lambda cannot force, prompt, or
   serialize (D-1, D-2, D-3).
3. **MCP's three app.execute call sites** — `_server.py:272`,
   `_tools.py:254`, `_tools.py:408`: two of three drop `group_option_values`;
   the translator merges group fields into tool schemas, so an agent sees
   flags it cannot pass through `run_job` (D-5).
4. **The TUI's hand-rolled status table** — `_cli/tui/job_execution.py:271-285`
   treats `BLOCKED` as success; `_types/exit_codes.py:56` says 5. Seven
   translation sites now exist; the depth audit's encapsulation boundary must
   decide which sites may re-derive and which must call the table.
5. **`RunContext` at 781 lines** — `runcontext.py:117-898`; the facade budget
   violation is the concrete symptom that capabilities outgrew their boundary
   (log-level validation and the capability map now live in the facade).
6. **`GroupOptionsConflictError` cache residue** — `cached_provider.py:895-921`
   drops bindings only per-file and only on re-import; reproduce the
   transition "file A declares group G, file B also declares G after A stops"
   against a warm cache — the observed persistence across `cache clear`
   suggests a second invalidation gap in the group-options section, which is
   the one cache section with no fingerprint at all (see `utils.py:1589`).
7. **`func why`'s second verdict engine** — `core.py:725-822` walks
   `engine.materialize_job`, `_declared_dep_names`, and the fingerprint store
   itself; any engine redesign that moves preflight must not orphan this
   public explain surface (C-9).
8. **Seven `negative_flag_for` consumers** — `naming.py:100` + the graphify
   list in §B; the rule is shared but the count is untested, so an eighth
   site can appear silently — the exact class `test_secret_surface_parity.py`
   was written to prevent elsewhere.
9. **The `_registered_commands` key contract** — `core.py:496-501` filters
   `"<group>::<name>"` strings and `boot.py:1314-1315` documents the
   Python-name-vs-canonical-name drift; the registry key format is a
   cross-layer string protocol worth owning in one place.
10. **Single-file mode's second boot** — `_handle_single_file` runs
    `auto_discover` + a second `FunctualizeApp` (`main.py:1643-1653`) whose
    CWD import executes arbitrary module top-level code (D-11); the depth
    audit's "how does a run start" model should decide whether that second
    boot is a surface or an accident.
