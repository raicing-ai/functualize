# Plan — plugin visibility and catalog

Read `spec.md` for behaviour, `research.md` for the reproduced evidence.

## Resolved open questions

### Q1 — where the classification helper lives → `_primitives/`, re-exported via `app/utils.py`

Implementation in `_primitives/plugin_kinds.py`: pure string logic over a group
name, zero dependencies, which is exactly what `_primitives` is for. `_cli`
reaches it through `app/utils.py`.

This is the established seam, not a new one. `app/utils.py` already re-exports
from `_primitives/agent_epilog`, `_primitives/cache_format`,
`_primitives/job_schema`, `_primitives/locator`, `_primitives/state_store` and
`_types/naming` (lines 24-56), and `_cli` consumes them from there precisely
because it may not import internals.

**Not an ADR.** The constitution requires one for a new layer, public API
surface, or dependency-rule change. This adds a function to an existing public
module through an existing pattern — no new layer, no new package, no rule
change. If `lint-imports` disagrees, that is the signal to stop and write one.

### Q2 — does `PluginCommand` need a terminal declaration → **YES**. Reversed.

The spec draft pinned `needs_terminal = False` for plugin nodes. That is unsafe,
and this feature is what makes it unsafe.

`func mcp serve` calls `server.start_stdio()`
(`plugins/functualize-mcp/src/functualize_mcp/_plugin.py:205`) — stdin and
stdout *are* the MCP protocol channel. Today the TUI cannot reach that command,
so nothing happens. The moment Part A puts `mcp` in the command tree, a user can
launch an stdio server from inside the inline TUI, where output is captured on a
worker thread. That corrupts the protocol and hangs the shell.

So: add `needs_terminal: bool = False` to `PluginCommand`, accept it in
`register_plugin_command()`, surface it on the plugin `CommandNode`, and have
`functualize-mcp` declare it for `serve`. Additive with a default — no existing
plugin changes.

**The bool survives; no predicate needed.** MCP runs three ways — stdio
(default), HTTP+SSE via `--http` or `[mcp] transport = "http"`, and a background
HTTP subprocess via `func mcp start`. That looked like the args-dependence
`_types/commands.py` ruled out ("a plain bool, not a predicate over args",
justified because the tree splits *families* into nodes, which does not cover a
*flag* on one node). It is not: both `serve` transports call `_mcp.run(...)` and
**block in the foreground** (`_server.py:136,151`), so the shell steps aside
either way. The flag picks the transport, not whether the command blocks. `start`
returns promptly and is `False`.

**This is a blocking dependency of Part A, not a follow-up.** Making the command
visible and making it safe to run must land together.

### Q3 — manifest format → TOML data file under `_cli/data/`

`_cli/data/` holds behaviour modules, not assets, so the file sits beside them
as `plugin_catalog.toml` with a small typed loader. Inert, diffable, reviewable
in a PR without reading Python. AC-B12 (every distribution named in it exists)
is what keeps a data file from drifting.

---

## Design

### Part A — one provider, and the consequences that fall out

`PluginCommandProvider` in `app/commands.py`, satisfying the existing
`CommandProvider` protocol. Two node classes: a namespace node (navigable,
children = its commands) and a leaf (runnable). `build_command_tree` composes
jobs → plugins → builtin.

**The tree is the fix for more than the TUI.** `command_schemas`
(`_cli/info.py:236`) already walks `build_command_tree`, so `info schema` gains
plugin commands with no change to its traversal — only the `kind` derivation at
`_cli/info.py:244` (`"builtin" if path[0] == BUILTIN_ROOT_SEGMENT else "job"`)
needs a third value, or it will label them `job`. That is the whole of F3.

This is the "one command tree" design working as intended: surfaces that read it
inherit the fix. The surfaces that broke — completion, `app.cli_command` — are
the ones that built their own inventory.

Also in A: `command_tree_rows` (`_cli/tui/job_listing.py:44`) hardcodes
`source_label="builtin"` for any descriptor-less node; it must ask the node what
it is. Plus F6 (`prog_name`) and F7 (column alignment).

### Part C — completion

`extract_completion_data` (`_cli/completions/data.py:112`) calls
`build_group_trie` with job rows only, leaving `plugin_namespaces` — the second
positional — defaulted. It runs post-boot with `func_app` in hand, so the fix is
to pass `get_plugin_commands()` rows, exactly as `_dispatch_group` does at
`_cli/main.py:986`. No cache change (AC-C3).

### Part D — one precedence rule

Keep the CLI's D3 outcome: job wins, shadowed plugin absent. Make the other two
agree.

- `register_plugin_commands` (`adapters/cli.py:562`) filters against job names
  *before* `add_command`, so click never overwrites. This is where the silent
  plugin win dies.
- `check_name_conflicts` gains the namespaced case (key on
  `f"{namespace}.{name}"`, matching `_cli/main.py:934`) and is reached from the
  `cli_command` property, not only `run()`.
- One shared predicate feeds `_dispatch_group`, the tree provider, and the
  adapter, so the three cannot drift. That predicate is the natural companion to
  the AC-P1 parity test.
- A shadowed plugin command gets a real diagnostic, not `logger.debug`
  (AC-D5).

### Part E — `functualize.jobs`, and the lazy-boot constraint

**The naive wiring breaks warm-boot-zero-imports.**
`EntryPointProvider._discover()` calls `ep.load()` for every entry point, which
imports the plugin module. Adding it to the pipeline as written would import
every job-publishing plugin on every boot. That guarantee is guarded by
`tests/discovery/test_warm_boot_zero_imports_property.py`,
`tests/integration/test_warm_cold_boot.py` and
`tests/cli/test_lazy_dispatch_single_import.py`, so the naive change fails CI —
which is the good outcome, but it means E is not a small task.

`importlib.metadata.EntryPoint` exposes `.name`, `.value` (`module:attr`) and
`.group` **without loading**. So entry-point jobs need the treatment directory
jobs already got: a cheap descriptor now, `ep.load()` deferred to
materialization, reusing `LazyJobFunction` / `engine.materialize_job`.

Cache interaction (AC-E2, AC-E3): entry-point descriptors are cached like
directory ones, fingerprinted by the `(distribution, version)` set publishing
under `functualize.jobs`. Uninstalling changes the fingerprint, which
invalidates — no ghost job. This **does** bump `CACHE_VERSION` (currently 19);
AC-C3's no-cache-change constraint binds Parts C and D, not E.

### Part B — catalog

`func builtin plugin available` and `install --recommended` in
`_cli/plugin_cmd.py`, reusing `discover_extensions()` for the installed half and
the TOML manifest for the rest. `recommended_distributions()` is the single
source the CLI and the AC-B7 drift test both read.

---

## Files to change

| File | Part |
|---|---|
| `_types/descriptors.py` | Q2 — `PluginCommand.needs_terminal` |
| `app/core.py` | Q2 — `register_plugin_command` signature |
| `app/commands.py` | A — `PluginCommandProvider`, composition |
| `_cli/tui/job_listing.py` | A — kind-aware `source_label` |
| `_cli/main.py` | A — F6 `prog_name`, F7 alignment; D — shared predicate |
| `_cli/info.py` | A/C — third `kind` value |
| `_cli/completions/data.py` | C — pass plugin rows |
| `app/adapters/cli.py` | D — precedence, conflict check reachability |
| `_primitives/plugin_kinds.py` *(new)* | Q1 — classification |
| `app/utils.py` | Q1 — re-export |
| `_discovery/providers.py` | E — lazy `EntryPointProvider` |
| `_app/boot.py` | E — wiring |
| `_primitives/cache_format.py` | E — version bump, fingerprint |
| `_cli/data/plugin_catalog.toml` *(new)* | B |
| `_cli/plugin_cmd.py` | B — `available`, `--recommended` |
| `plugins/functualize-mcp/src/functualize_mcp/_plugin.py` | Q2 — declare `serve` |

## Risks

1. **Q2 is a safety regression if missed.** Part A without the terminal
   declaration hands users a way to hang their shell. They land together.
2. **Part E vs lazy boot.** Highest-effort item. If the lazy descriptor proves
   impractical, the fallback is to gate `EntryPointProvider` behind opt-in
   config rather than regress warm boot — but that weakens AC-E1, so raise it
   rather than deciding silently.
3. **Cache version bump (E)** invalidates every existing cache once. Expected,
   but it means E cannot be a quiet change.
4. **AC-A10.** Any touch near `register_builtin_commands` or the epilog risks
   `func --help`. The pinning test lands in wave 1, before anything else moves.
5. **`lint-imports`.** Q1 is the load-bearing placement; run it per task, not at
   the end.
6. **Reachability (AC-E4).** `EntryPointProvider` has been unreachable since it
   was written. A test that constructs it directly leaves it exactly as
   unreachable — the proof must break the *boot* call path.
