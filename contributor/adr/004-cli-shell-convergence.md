# ADR-004: CLI/Shell Convergence — Trie-based Namespace, Typer Removal, and Generalized Command Surface

**Status**: accepted
**Date**: 2026-07-24
**Deciders**: Core team

## Context

Functualize had a grouped job namespace consumed by four surfaces (kernel, CLI dispatch, TUI, MCP)
at four different depths. The namespace shape was re-derived independently in ~7 places:
a flat set of dotted prefix strings plus greedy string-matching in dispatch, plus a re-implemented
ancestor walk in the TUI. `_is_valid_job_group()` was duplicated across registry and sync modules.
Builtins (`cache`, `config`, `scaffold`, `version`, etc.) were hardcoded at dispatch priority 2 —
before groups and jobs — permanently reserving top-level names with no warning.

Separately, Typer sat between functualize and click as a pure adapter layer: functualize synthesized
fake `inspect.Signature` objects with `typer.Argument`/`typer.Option` defaults from its own
`FieldDescriptor` schema, purely so Typer would convert them back into click commands. This added
~22ms import time and one more version-drift surface for functionality functualize was already computing.

Four separate lines of work intersected on the same namespace: a group trie, typer removal, a
generalized shell for project apps, and dynamic input-bar/prompt routing. Left unaligned, these would
build three tree models for one namespace, register groups twice, and answer the builtin problem two ways.

## Decision

One convergence effort resolved all four into a unified design across four phases:

### Phase A — Kernel Namespace Foundation

1. **`GroupTrie` in `_types/naming.py`** — the single namespace authority, placed at the top of the layer
   order. Two populations: pre-boot trie (cache rows + `builtin`, no plugin namespaces — import-free,
   same invariant as the discovery cache) and post-boot trie (adds plugin namespaces from
   `app.get_plugin_commands()`). Resolution delegates per-segment; duality nodes (a name that is both
   a job and a group) are first-class. Dotted-token all-or-nothing split.

2. **`PluginCommand.group` → `namespace`** — renamed to eliminate the collision with `JobDescriptor.group`
   (different concept). Plugin commands are in-memory only (never in the discovery cache), so no cache
   version bump was needed.

3. **`builtin` as a reserved subtree** — the `builtin` name is reserved at boot. All builtin commands
   (`cache`, `state`, `why`, `config`, `domains`, `scaffold`, `version`, `show-info`) moved under
   the `builtin` subtree. Sigils `!` and `?` are also reserved for future `InputMode` dispatch.

### Phase B — Typer Removal + Registration on the Trie

1. **Typer removed entirely** — `build_click_params` (in `app/adapters/click_params.py`) builds
   `click.Parameter` objects directly from `FieldDescriptor` metadata. Registration uses recursive
   `click.Group` nesting from trie segments. `functualize[cli]` no longer declares `typer` or `trogon`.
   `FunctualizeApp.typer_app` → `cli_command`; `_plugin_sub_typers` → `_plugin_sub_groups`.

2. **Help-panel parity** — custom `format_help` on `NormalizingGroup` replaces typer's help rendering.

3. **Isolation enforced** — `test_typer_isolation.py` now asserts typer is **absent**, not just isolated
   from the kernel.

### Phase C — Generalized Shell

1. **`CommandNode` protocol** — `name`, `help`, `provenance`, `children`, `params`, `needs_terminal`, `execute`.
   `CommandProvider` protocol: `root_nodes()`, provider composition.

2. **`JobCommandProvider`** — nodes over job/group trie nodes, `params()` from cache (no materialization).

3. **`ClickCommandProvider`** — wraps click groups (builtins), introspects params.

4. **`InputMode` + `InputModeRegistry`** — sigil-dispatched modes (`!` for shell, `?` reserved),
   `resolve()` fallback, default command mode wraps `CursorContext` sub-modes.

5. **`DynamicInputBar`** — mode widget mounting, `!` shell mode, `?` reserved. Shell mode reuses
   `_job_worker_running` and writes through `StateStore.append_history`.

6. **Settings generalization** — `AppSettingsSchema` / `SettingsStore(spec, app_name=)` / registration API.
   `tui.*` as a shell-contributed section. Killed five hardcoded builtin seams in the TUI.

### Phase D — Periphery + Docs

Group navigation, `--version` fast path, duality nodes, reserved names documented.
Prompt-routing table in `Surface`/`PromptCollector` vocabulary.

## Consequences

### Positive

- One namespace model across all four surfaces (kernel/CLI/TUI/MCP)
- ~22ms less import time (typer removed)
- No more version-drift from typer pass-through dependency
- Project apps can reuse the shell with their own settings schema
- `PluginCommand.group` collision resolved permanently
- Five hardcoded builtin seams deleted from the TUI
- Builtin subtree frees top-level names (`cache`, `state`, etc.) for user jobs

### Negative

- Warm-cache boot MUST build a trie; cache format must include group-path rows
- `builtin` is a forever-reserved name (one collision surface)
- `DynamicInputBar` replaces `SmartBar` as the input widget — any plugin that
  white-box accessed the old bar's internals breaks

### Neutral

- MCP group awareness (parsing the group annotation) remains a separate concern;
  the MCP plugin still stores the group as an opaque annotation string
- Typer was already removed prior to this convergence (Phase B was leftovers);
  the convergence feature closed the registration gap

## Status

Shipped and closed 2026-07-24. Group-model consistency and typer removal are fully
resolved. Two areas were only partly addressed and remain open:

- **Inline TUI for project apps** — the command-surface contracts landed; app-owned
  settings, early flags, and `CommandProvider`-driven autocomplete did not.
- **Dynamic input bar / prompt routing** — the input-mode portion landed and the
  prompt-routing table was rewritten in Surface/PromptCollector vocabulary.
