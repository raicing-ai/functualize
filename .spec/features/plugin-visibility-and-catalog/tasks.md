# Tasks — plugin visibility and catalog

Wave ordering is binding: never start a task in wave N+1 while wave N has
unchecked tasks. Each task names its acceptance gate; a task is `[x]` only when
that gate is green against the code as it actually stands.

---

## Wave 1 — pin the invariant, then make plugin commands safe to expose

- [x] **T1.1 — Pin `func --help`**
  Freeze the current top-level `--help` output as a test fixture. Byte-identical
  comparison. Lands before anything else moves, so every later task is measured
  against it.
  *Files:* `tests/cli/test_help_surface_pinned.py`
  *Gate:* AC-A10. Test passes now; mutating `register_builtin_commands` to mount
  a second command makes it fail.

- [x] **T1.2 — `PluginCommand.needs_terminal`**
  Add `needs_terminal: bool = False` to the frozen dataclass; accept it in
  `FunctualizeApp.register_plugin_command()`. Additive with a default — no
  existing caller changes.
  *Files:* `_app/models.py`, `_app/impl.py`, `app/core.py`
  *Note:* `PluginCommand` existed **twice** — byte-identical copies in
  `_app/models.py` (live) and `_types/descriptors.py` (no consumers). The
  dead twin and its `_types/__init__` export were deleted rather than
  updated in parallel; two definitions where one gains a field is the
  drift this repo already shipped once.
  *Gate:* Existing plugin registration still works unchanged; a command
  registered with `needs_terminal=True` round-trips.
  *Why first:* Part A makes plugin commands runnable from the TUI. `func mcp
  serve` calls `server.start_stdio()` and owns stdin/stdout. Exposing it without
  this field hands users a way to hang their shell.

- [x] **T1.3 — `functualize-mcp` declares `serve` as terminal-owning**
  *Files:* `plugins/functualize-mcp/src/functualize_mcp/_plugin.py`
  *Gate:* `uv run pytest plugins/functualize-mcp/tests/ -q`; `serve` reports
  `needs_terminal=True` and the other five (`start`, `stop`, `list`, `tools`,
  `schema`) report `False`.

  **`serve` is `True` for both transports, not only stdio.** MCP runs three
  ways: stdio (default, `start_stdio()`), HTTP+SSE via `--http` or `[mcp]
  transport = "http"` (`start_http()`), and a background HTTP subprocess via
  `func mcp start`. Both `serve` transports call `_mcp.run(...)` and **block in
  the foreground** (`_server.py:136,151`), so the shell must step aside for
  either; stdio merely adds the extra hazard that stdout *is* the protocol
  channel. `start` spawns a subprocess and returns, so it is `False`.

  This is why `needs_terminal` can stay the plain bool `_types/commands.py`
  decided on. The static form is only unsafe if a single node's answer varies
  with its flags — and here it does not, because the flag selects the transport,
  not whether the command blocks.

- [x] **T1.4 — Classification helper**
  `_primitives/plugin_kinds.py`: `PluginKind` str-enum + `classify_group()`
  mapping `functualize.plugins`→adapter, `functualize.domains`→domain,
  `functualize.*_providers`→implementation, else unknown. Re-export via
  `app/utils.py`.
  *Files:* `_primitives/plugin_kinds.py`, `app/utils.py`
  *Gate:* AC-B4 — a synthetic `functualize.zzz_providers` classifies as
  `implementation` with no code change. `uv run lint-imports` = 0 violations.

## Wave 2 — the command tree (the original bug)

- [x] **T2.1 — `PluginCommandProvider`**
  Namespace node (navigable) + leaf node (runnable) satisfying `CommandNode`.
  `needs_terminal` from T1.2. `params()` from the callback signature.
  `execute()` invokes the callback, returns an exit code. Compose into
  `build_command_tree` as jobs → plugins → builtin.
  *Files:* `app/commands.py`
  *Gate:* AC-A1, AC-A2, AC-A4, AC-A6, AC-A7 against a fake plugin — never
  against `functualize-mcp` being installed.

- [x] **T2.2 — Precedence in the tree**
  Job wins on exact path conflict; the shadowed plugin command is **absent**,
  not skipped at lookup. Extract the predicate `_dispatch_group`
  (`_cli/main.py:936-939`) already applies so both read one rule.
  *Files:* `app/commands.py`, `_cli/main.py`
  *Gate:* AC-A3 — tree and `_dispatch_group` resolve the same conflict
  identically, asserted in one test over both.

- [x] **T2.3 — Kind-aware `source_label`**
  `command_tree_rows` hardcodes `source_label="builtin"` for descriptor-less
  nodes; ask the node instead.
  *Files:* `_cli/tui/job_listing.py`
  *Gate:* AC-A5 — plugin node labels as a plugin, reserved subtree still
  `builtin`.

- [x] **T2.4 — `info schema` kind**
  `_cli/info.py:244` derives `"builtin" if path[0] == BUILTIN_ROOT_SEGMENT else
  "job"`, which mislabels plugin commands as `job`. Add the third value and
  extend the `--kind` filter.
  *Files:* `_cli/info.py`
  *Gate:* AC-C1. `command_schemas` already walks `build_command_tree`, so
  traversal is unchanged — verify by asserting the plugin command appears with
  the right kind, and that `--kind job` excludes it.

- [x] **T2.5 — Live TUI verification**
  `observe-tui` against `examples/standalone/showcase` with `functualize-mcp`
  installed: `mcp` in the Jobs browser, SmartBar completes it, `mcp serve`
  renders a preflight instead of the current silence.
  *Gate:* AC-A8, AC-A9. Manual/agent verification only — never wired into CI.

## Wave 3 — the remaining surfaces

- [x] **T3.1 — Shell completion**
  Pass `get_plugin_commands()` rows as `build_group_trie`'s second positional,
  currently defaulted (`_cli/completions/data.py:130-133`).
  *Files:* `_cli/completions/data.py`
  *Gate:* AC-C2, AC-C3 — emitted payload carries the namespace and its
  subcommands; no discovery-cache change.

- [x] **T3.2 — `app.cli_command` precedence**
  Filter plugin commands against job names inside `register_plugin_commands`
  before `add_command`, so click never overwrites a job
  (`adapters/cli.py:802-803` registers jobs then plugins). Reuse T2.2's
  predicate.
  *Files:* `app/adapters/cli.py`
  *Gate:* AC-D1, AC-D4 — the `collide` reproduction in `research.md` now
  resolves to the job on all three paths.

- [x] **T3.3 — Conflict check: namespaced + reachable**
  `check_name_conflicts` inspects only `namespace is None` and is reached only
  from `run()`. Extend to `f"{namespace}.{name}"` (matching `_cli/main.py:934`)
  and reach it from the `cli_command` property. Replace `_dispatch_group`'s
  `logger.debug` shadow notice with a user-visible diagnostic.
  *Files:* `app/adapters/cli.py`, `_cli/main.py`
  *Gate:* AC-D3, AC-D5.

- [x] **T3.4 — F6 + F7 polish**
  `prog_name` on the ad-hoc plugin command so `func mcp serve --help` prints
  `Usage: func mcp serve`; pad the group listing to a column as
  `render_extensions` does.
  *Files:* `_cli/main.py`
  *Gate:* AC-A11, AC-A12.

- [x] **T3.5 — Command-inventory parity test**
  One app with a job, a namespaced plugin command and a builtin; assert the same
  command set from `build_command_tree`, `command_schemas`,
  `extract_completion_data`, `_dispatch_group`'s trie, and `app.cli_command`.
  *Files:* `tests/cli/test_command_inventory_parity.py`
  *Gate:* AC-P1. Sabotage check: reverting any of T2.1/T3.1/T3.2 makes it fail.
  `tests/cli/test_schema_surface_parity.py` compares *field rendering*, which is
  why F2/F3/F4 all passed CI; this compares *inventory*.

## Wave 4 — `functualize.jobs` (Part E)

Largest part. Bumps `CACHE_VERSION`; AC-C3's no-cache-change constraint binds
waves 2–3, not this one.

- [x] **T4.1 — Lazy `EntryPointProvider`**
  Build descriptors from `EntryPoint.name` / `.value` without `ep.load()`;
  defer the import to materialization via `LazyJobFunction` /
  `engine.materialize_job`, as directory jobs already do.
  *Files:* `_discovery/providers.py`
  *Gate:* `tests/discovery/test_warm_boot_zero_imports_property.py` stays green
  with a job-publishing distribution installed. The naive `ep.load()` version
  fails it — confirm that first, so the test is known non-vacuous.

- [x] **T4.2 — ~~Cache entry-point descriptors~~ → no cache needed**
  **PLAN DEVIATION, deliberate.** The plan called for persisting entry-point
  descriptors fingerprinted by the installed `(distribution, version)` set, and
  a `CACHE_VERSION` 19 → 20 bump. That is not needed and was not done.

  `EntryPoint.name`/`.value` are *metadata*, so enumeration costs a metadata
  read rather than an import. Re-reading the table each boot therefore keeps
  warm-boot-zero-imports **and** buys AC-E2 and AC-E3 by construction instead
  of by invalidation logic: there is no second source of truth to drift, and an
  uninstalled distribution cannot leave a ghost job because nothing persisted
  it. Verified against a real installed distribution — `func backup` ran, then
  after `uv pip uninstall` it was neither listed nor runnable, on a warm cache.

  Consequence: `CACHE_VERSION` stays at 19 and **the whole feature is one
  mergeable increment**, with AC-C3's no-cache-change constraint holding for
  wave 4 as well.

  The fidelity gap this was meant to close is handled instead by
  `JobNode._resolved_descriptor()`, which materializes a `<entry_point>`
  descriptor when something asks it to *describe* itself — permitted explicitly
  by `CommandNode.params()` ("can force materialization"). Narrowed to
  entry-point sources so the directory warm path is untouched.

- [x] **T4.3 — Wire it into boot**
  *Files:* `_app/boot.py`
  *Gate:* AC-E1 — an entry-point job runs via `func <job>` and lists in bare
  `func` (TTY + piped), the TUI browser, `info schema`, and completion.
  **AC-E4 reachability:** name the boot call path and prove it by breaking *that
  call* and watching a test fail. This capability has been unreachable since it
  was written; a test that constructs the provider directly leaves it exactly as
  unreachable. Commit before sabotaging.

- [x] **T4.4 — Document the mechanism**
  `functualize.jobs` appears in no user-facing doc today.
  *Files:* `contributor/guides/plugin-development.md`, `docs/`
  *Gate:* AC-E6. A doc example that actually runs.

## Wave 5 — catalog (Part B)

- [x] **T5.1 — Manifest + loader**
  `_cli/data/plugin_catalog.toml` carrying name, distribution, kind,
  description, recommended flag; typed loader; `recommended_distributions()` as
  the single source the CLI and the drift test both read.
  *Files:* `_cli/data/plugin_catalog.toml`, `_cli/plugin_cmd.py`
  *Gate:* AC-B7 — parses `pyproject.toml`'s `[all]` extra and fails on drift.
  AC-B8 — `functualize-bitwarden` absent, with the musl reason recorded beside
  the assertion. AC-B12 — every distribution named exists under `plugins/`.

- [x] **T5.2 — `plugin available`**
  Grouped by kind, installed markers, `--format json`. Installed plugins
  classify from their live entry-point group (authoritative); the manifest
  supplies the kind only for the not-installed.
  *Files:* `_cli/plugin_cmd.py`
  *Gate:* AC-B1, AC-B2, AC-B5, AC-B6, plus spec behaviour 19 — the
  `importlib.metadata` snapshot is read once and never re-read after an install
  (`_cli/plugin_cmd.py:22-27`).

- [x] **T5.3 — Offline guarantee**
  *Gate:* AC-B3 — without `--remote`, no socket is opened. Test fails if one is.

- [x] **T5.4 — `--remote`**
  PyPI query for `functualize-*`, merged and marked uncurated; network failure
  degrades to the shipped catalog with a warning and exit 0.
  *Files:* `_cli/plugin_cmd.py`
  *Gate:* AC-B11.

- [x] **T5.5 — `install --recommended`**
  Mutually exclusive with a positional `PACKAGE`. Reuses the existing planning,
  confirmation and `manifest.record_addition` path.
  *Files:* `_cli/plugin_cmd.py`
  *Gate:* AC-B9, AC-B10 — already-installed package is not an error; every
  installed name is recorded so `self update` restores it.

## Wave 6 — close

- [x] **T6.1 — Full gates**
  *Gate:* `ruff check` / `ruff format --check` / `mypy src/` / `lint-imports`
  (0 violations) / `pytest tests/skills/ tests/tui_audit/` (15/15) / full suite.
  AC-X1–X4.

- [x] **T6.2 — Docs sync + STATUS migration**
  Run `/sync-docs`. Migrate the durable half to `.spec/STATUS.md` — including
  the deferred item: plugin namespaces are absent from the discovery cache, so
  `func <namespace>` still detours through `Mode.UNKNOWN`
  (`_cli/main.py:779-782`). Then `git rm -r .spec/features/plugin-visibility-and-catalog`
  before merge (`spec-artifacts-cleared`).

---

## Landing note

Waves 1-3 are the fix originally asked for plus its cross-surface siblings, and
are self-contained: they touch no cache format and pin `func --help`. They can
merge without waves 4-5. Wave 4 (`functualize.jobs`) bumps `CACHE_VERSION` and
is the largest single piece; wave 5 (catalog) is independent of it and depends
only on T1.4.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 1,
      "tasks": [
        "T1.1",
        "T1.2",
        "T1.3",
        "T1.4"
      ],
      "depends_on": []
    },
    {
      "id": 2,
      "tasks": [
        "T2.1",
        "T2.2",
        "T2.3",
        "T2.4",
        "T2.5"
      ],
      "depends_on": [
        "T1.1",
        "T1.2",
        "T1.3"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "T3.1",
        "T3.2",
        "T3.3",
        "T3.4",
        "T3.5"
      ],
      "depends_on": [
        "T2.1",
        "T2.2",
        "T2.4"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "T4.1",
        "T4.2",
        "T4.3",
        "T4.4"
      ],
      "depends_on": [
        "T2.1"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "T5.1",
        "T5.2",
        "T5.3",
        "T5.4",
        "T5.5"
      ],
      "depends_on": [
        "T1.4"
      ]
    },
    {
      "id": 6,
      "tasks": [
        "T6.1",
        "T6.2"
      ],
      "depends_on": [
        "T3.5",
        "T4.3",
        "T5.5"
      ]
    }
  ]
}
```
