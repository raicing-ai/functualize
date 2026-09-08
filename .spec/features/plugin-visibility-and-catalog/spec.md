# Plugin visibility and catalog

**Status:** Specify
**Branch:** `feat/plugin-visibility-and-catalog`

Gaps in how plugins surface to a user. Part A is a defect — an installed
plugin's commands are invisible in the TUI. Part B is a feature — you cannot
find out what plugins *exist* without reading the repository.

**The audit (`research.md`) widened Part A.** The missing provider is not one
bug: the same omission repeats independently on four surfaces (TUI, `info
schema`, shell completion, and the plugin-job entry-point group), and conflict
precedence resolves three different ways depending on how the app is reached.
Parts C, D and E below come from that audit and are in scope; every claim in
them is reproduced in `research.md`, not inferred.

---

## Problem statement

### Part A — plugin commands are absent from the one command tree

`build_command_tree()` (`app/commands.py:368`) is described in its own docstring
as "the shell's **one** command tree", and every TUI surface reads it: the job
browser (`_cli/tui/job_listing.py:36`), command-name completion
(`_cli/tui/app.py:2079`), and preflight/execution resolution
(`_cli/tui/job_execution.py:447`, `_cli/tui/app.py:2636`).

It composes exactly two providers:

```python
nodes: list[CommandNode] = list(JobCommandProvider(app).nodes())
nodes.extend(ClickCommandProvider(app).nodes())   # the reserved `builtin` subtree
return nodes
```

There is no provider for plugin-registered commands, and no file under
`_cli/tui/` calls `app.get_plugin_commands()` at all.

**Verified** in `examples/standalone/showcase` with `functualize-mcp` installed:

```
jobs discovered: 20
plugin commands: [('mcp','serve'), ('mcp','start'), ('mcp','list'),
                  ('mcp','stop'), ('mcp','schema'), ('mcp','tools')]
build_command_tree top-level: ['analyze', 'build', 'builtin', 'deploy',
                               'deploy-rollback', ..., 'transform']
'mcp' in tree? False
```

The plugin loads correctly and registers all six commands. The TUI simply never
asks. Observable consequences, all confirmed against the live TUI via a PTY
probe:

- the header reads `func — functualize (20 jobs)`; `mcp` is not counted
- the Jobs browser panel omits `mcp` entirely
- typing `mcp` in the SmartBar produces no completion

Meanwhile the *other* surfaces over the same data are correct: bare non-TTY
`func` prints `mcp — 6 commands (run 'func mcp' to list)`
(`_cli/main.py:563-590`), and `func mcp serve` executes
(`_cli/main.py:906` `_dispatch_group`).

So this is a single missing provider, not a broken plugin and not a broken
adapter. The asymmetry is the bug: two of the three readers of
`get_plugin_commands()` are in `_cli/main.py`, and the shell's command tree —
the one thing every other surface is supposed to route through — is not one of
them.

**Secondary defect, same area.** `command_tree_rows()`
(`_cli/tui/job_listing.py:24`) builds a fallback row for any node without a job
descriptor and hardcodes `source_label="builtin"`. Once plugin nodes enter the
tree, they would be labelled `builtin` — which is wrong and, per
`_cli/builtins.py:229`, materially misleading: `builtin` means *first-party,
reserved namespace*, and a third-party plugin is neither.

### Part C — the same omission, on two more surfaces (F3, F4)

Both run on a **booted** app, where `get_plugin_commands()` is available. Neither
asks.

**`func builtin info schema`** is advertised in the epilog of every `func --help`
as `all commands, as JSON`. It is not. Against showcase it returns 67 entries —
47 `builtin`, 20 `job`, and zero plugin commands; its `kind` enum admits only
those two values. The agent this surface exists for cannot discover `func mcp
serve`.

**Shell completion** omits them too. `extract_completion_data`
(`_cli/completions/data.py:112`) calls `build_group_trie` with job rows only,
leaving the `plugin_namespaces` parameter — the one `_dispatch_group` passes
`plugin_rows` to — at its default. Empirically `shell-init bash` emits `deploy`
9×, `builtin` 14×, `mcp` 0×, so `func mc<TAB>` completes nothing.

### Part D — job/plugin conflict resolves three different ways (F5)

One app, one collision, three outcomes:

| Path | Outcome |
|---|---|
| `func collide` (`_dispatch_group`) | job wins, plugin dropped, `logger.debug` only |
| `app.cli_command` (`adapters/cli.py:815`) | **plugin wins, silently** |
| `CliAdapter.run()` (`adapters/cli.py:830`) | **ValueError** |

`adapters/cli.py:802-803` registers jobs then plugin commands, and click's
`add_command` overwrites by name, so the plugin displaces the job.
`check_name_conflicts` is reached only from `run()` — never from the
`cli_command` property, which `adapters/cli.py:115` documents as a supported
public access path. It is also narrower than the CLI's rule: it inspects only
`namespace is None`, so namespaced collisions go unchecked, while
`_dispatch_group` checks exactly those.

Per `contributor/architecture/surface-boundary.md`, precedence is about *the
program*, not *how you reach it* — so this is a parity violation, not a
permitted divergence.

### Part E — `functualize.jobs` is a dead entry-point group (F1)

**A distribution publishing jobs under `functualize.jobs` is discovered by
nothing, on every surface.** `EntryPointProvider` (`_discovery/providers.py:750`)
is its only reader; `grep -rn "EntryPointProvider(" src/` returns nothing. It is
not re-exported from any public package either, so a user cannot wire it without
importing an internal package the constitution forbids them.

This is the fourth built-tested-unreachable capability
(`contributor/guides/wiring-discipline.md`).

What makes it a defect rather than dead code: `_cli/plugin_cmd.py:52-57`
deliberately excludes the group from `plugin list`, reasoning that a
distribution publishing there "is supplying work for functualize to run" and
that listing it "would invite a `plugin uninstall` that removes somebody's
jobs". That reasoning is only sound if the group works.

No shipped plugin supplies jobs by any mechanism, which is why this survived.

### Part B — you cannot discover what plugins exist

`func builtin plugin` offers `list`, `install`, `uninstall`. `list` reads
`importlib.metadata` and therefore reports **only what is already installed**.
A user who has never heard of `functualize-mcp` has no way to learn it exists,
what kind of thing it is, or whether they want it.

There is also no way to say "give me the usual set" — the recommended plugins
must be installed one `func builtin plugin install <name>` at a time, and
nothing tells the user which names those are.

Finally, the plugins are not all the same *kind* of thing, and treating them as
one flat list is actively unhelpful. `functualize-mcp` adds commands anyone
might want. `functualize-aws` and `functualize-bitwarden` are backends you
choose because of the infrastructure you already run — installing both makes no
sense. Today `plugin list` groups by raw entry-point group name
(`remote_providers:`, `plugins:`), which encodes the distinction but does not
explain it.

---

## Out of scope — decided, do not change

**`func --help` stays exactly as it is.** It lists only `builtin`, and it must
continue to list only `builtin`. It is a help page for the global flags, not a
command index.

The pre-boot `--help` interception at `_cli/main.py:1978-1988` — which routes
to a plain Click group carrying only what `register_builtin_commands()` mounts
(`_cli/builtins.py:667`) — is deliberate and is not touched by this feature. No
task may add jobs, groups, or plugin commands to the top-level `--help` output.

The command index remains: bare `func` (both TTY and piped),
`func builtin info schema`, and `func <namespace>` for drill-down.

## Out of scope — noted, deferred

Plugin namespaces are registered at `APP_READY` and are therefore invisible to
pre-boot mode detection (`_cli/main.py:779-782`). This is why `func mcp serve`
classifies as `Mode.UNKNOWN`, boots, and only then recovers inside
`_dispatch_group`, whereas jobs and groups are known pre-boot from the
discovery cache.

That detour is a real inefficiency and a plausible future task (caching plugin
namespaces alongside job groups would fix routing *and* let pre-boot surfaces
see plugin commands). **It is not in this feature.** The observable behaviour is
already correct — `func mcp serve` works — so this is a performance and
architecture concern, not a defect, and folding it in would widen the blast
radius from "one provider plus one CLI command family" to "the discovery cache
format". Record it in `STATUS.md` at close.

---

## User stories

**A1.** As someone running the TUI with `functualize-mcp` installed, I see `mcp`
in the Jobs browser alongside my jobs and the `builtin` subtree, so I can
discover that my installation can serve MCP without leaving the shell.

**A2.** As someone typing in the SmartBar, `mcp` completes and drills down to
its six subcommands, the same way `builtin` does.

**A3.** As someone reading the Jobs browser, a plugin command is labelled as
coming from a plugin — not as `builtin`, which would tell me it is first-party
when it is not.

**B1.** As a new user, `func builtin plugin available` tells me what plugins
exist, what each one is for, which kind it is, and whether I already have it —
without a network connection.

**B2.** As a user setting up a project, one command installs the recommended
set, and it does not silently drag in an infrastructure backend I did not ask
for.

**B3.** As a user choosing a secrets backend, the implementation plugins are
presented as a set to *pick from*, visibly distinct from plugins that are
generally useful.

**B4.** As someone who has published a third-party plugin, `--remote` surfaces
it from PyPI, marked as not curated by this project.

---

## Behavior

### A. Plugin commands in the command tree

1. `build_command_tree(app)` returns plugin-registered commands in addition to
   job nodes and the reserved `builtin` node.

2. A plugin command with a namespace (`PluginCommand.namespace == "mcp"`)
   appears as a **navigable** top-level node named `mcp` whose children are its
   commands. A plugin command with `namespace is None` appears as a
   **runnable** top-level node.

3. Ordering: jobs first, then plugin nodes, then `builtin` last. `builtin`
   sorting last is existing behaviour (`app/commands.py:373-374`) and is
   preserved.

4. **Precedence.** A job wins over a plugin command on an exact path conflict.
   The shadowed plugin command is **absent from the tree**, not skipped at
   lookup time. This matches `_dispatch_group`'s existing D3 rule
   (`_cli/main.py:936-939`, `_cli/main.py:967-974`) — the two must not disagree,
   because the TUI resolves execution through the tree and the CLI resolves it
   through `_dispatch_group`, and a command that lists in one and runs in the
   other is worse than one that does neither.

5. `needs_terminal` is `False` for plugin nodes. `PluginCommand` carries no
   terminal declaration, and the conservative answer keeps a TUI front-end from
   suspending itself around a command that does not need it. (A plugin-declared
   terminal hint is a separate future concern; see Open questions.)

6. Executing a plugin node runs its callback and returns a process-style exit
   code, consistent with `CommandNode.execute`.

7. `params()` for a plugin node reports the callback's CLI-facing parameters,
   so the TUI's preflight/missing-argument surfaces work against a plugin
   command as they do against a job.

8. `command_tree_rows()` labels a node by what it actually is. The hardcoded
   `source_label="builtin"` fallback becomes kind-aware: `builtin` for the
   reserved subtree, a plugin label for plugin nodes.

9. The TUI header count reflects the tree, not only `get_jobs()`.

### B. Plugin discovery and classification

10. **Three kinds**, derived from the entry-point group a plugin declares:

    | Kind | Entry-point group | Meaning |
    |---|---|---|
    | adapter | `functualize.plugins` | Adds commands or a delivery surface |
    | domain | `functualize.domains` | A capability protocol / SDK |
    | implementation | `functualize.*_providers` | A concrete backend, chosen per infrastructure |

    The mapping is computed from the group name, **not** a hardcoded list of
    plugin names. `_cli/plugin_cmd.py:16-21` already establishes that groups are
    discovered and never enumerated, because domains declare new provider groups
    at runtime (`_plugins/domain_registry.py:246`). A new `functualize.x_providers`
    group must classify as `implementation` without any code change.

11. `functualize.jobs` remains excluded — it is a job *source*, not an
    extension (`_cli/plugin_cmd.py:52-57`).

12. **`func builtin plugin available`** lists known plugins grouped by kind.
    Each row carries: registered/short name, distribution name, kind,
    one-line description, and whether it is currently installed. Text and
    `--format json` both supported, matching `plugin list`.

13. The catalog is a **manifest shipped inside core**. It works with no network
    access and is the default source. It carries the kind and description for
    plugins that are *not installed*, which cannot be read from metadata
    because there is no metadata to read.

14. **`--remote`** additionally queries PyPI for `functualize-*` distributions
    and merges them in, marked as not curated by this project. Without
    `--remote`, no network call is made. A network failure under `--remote`
    degrades to the shipped catalog with a warning; it is not a fatal error.

15. For an **installed** plugin the kind is derived from its live entry-point
    group, which is authoritative. The shipped manifest supplies the kind only
    for plugins that are not installed. A third-party plugin that is installed
    therefore classifies correctly even though the manifest has never heard of
    it.

16. **`func builtin plugin install --recommended`** installs the recommended
    set in one operation, reusing the existing install mechanism and its
    `--yes` confirmation and manifest recording.

17. The recommended set **must not contradict** the `[all]` extra in
    `pyproject.toml`. That extra names eleven plugins and deliberately excludes
    `functualize-bitwarden`, because `bitwarden-sdk` publishes no musl wheels,
    which would make `functualize[all]` unresolvable and break the
    Alpine/distroless standalone binaries. A test must fail if the two lists
    drift apart.

18. Implementation-kind plugins are **not** part of the recommended set purely
    by virtue of being implementations — they are presented as alternatives to
    choose between. `functualize-aws` is in `[all]` today and that stays true;
    the presentation, not the set, is what distinguishes them.

19. `available` never re-reads `importlib.metadata` after an install in the
    same process. That snapshot is taken once and a freshly installed
    distribution is not in it — reporting its absence as a failure is the
    documented trap at `_cli/plugin_cmd.py:22-27`.

---

## Acceptance criteria

### Part A

- **AC-A1** — With a plugin registering namespaced commands, `build_command_tree(app)`
  contains a top-level node named for the namespace, and its `children()` are the
  registered commands. Test asserts against a fake plugin, not against
  `functualize-mcp` being installed.
- **AC-A2** — A plugin command with `namespace is None` appears as a runnable
  top-level node.
- **AC-A3** — When a job and a plugin command occupy the same path, the tree
  contains the job and does **not** contain the plugin command. Asserted to
  match `_dispatch_group`'s resolution for the same inputs.
- **AC-A4** — Node order is jobs, then plugins, then `builtin` last.
- **AC-A5** — `command_tree_rows()` gives a plugin node a source label that is
  not `builtin`; the reserved subtree still labels `builtin`.
- **AC-A6** — `needs_terminal` is `False` for every plugin node.
- **AC-A7** — Executing a plugin node through `CommandNode.execute` invokes the
  registered callback and returns its exit code.
- **AC-A8** — TUI command-name completion (`_cli/tui/app.py:_command_tree_names`)
  includes the plugin namespace.
- **AC-A9** — Live verification via `observe-tui`: in an example project with
  `functualize-mcp` installed, the Jobs browser shows `mcp` and the SmartBar
  completes it. Manual/agent verification only, never wired into CI.
- **AC-A10** — `func --help` output is **byte-identical** before and after this
  feature. A test pins it.
- **AC-A11** (F6) — `func mcp serve --help` shows `Usage: func mcp serve
  [OPTIONS]`, not `Usage: serve [OPTIONS]`. The ad-hoc command is invoked with a
  `prog_name`, so a copy-pasted usage line is a command that exists.
- **AC-A12** (F7) — The plugin group listing pads descriptions to a column, as
  `render_extensions` (`_cli/plugin_cmd.py:131`) and every click listing do.

### Part B

- **AC-B1** — `func builtin plugin available` lists plugins grouped by the three
  kinds, with an installed/not-installed marker per row.
- **AC-B2** — `func builtin plugin available --format json` emits one object per
  plugin carrying at least `name`, `distribution`, `kind`, `description`,
  `installed`, `source`.
- **AC-B3** — With no network available, `available` (no `--remote`) succeeds and
  makes no outbound request. Asserted by a test that fails if a socket is opened.
- **AC-B4** — Kind classification is derived from the group name: a synthetic
  entry point in group `functualize.zzz_providers` classifies as
  `implementation` with no code change and no manifest entry.
- **AC-B5** — An installed plugin absent from the shipped manifest is still
  listed, classified from its live entry-point group, and marked installed.
- **AC-B6** — `functualize.jobs` entries never appear in `available`.
- **AC-B7** — The recommended set equals the plugin names in the `[all]` extra
  of `pyproject.toml`. The test parses `pyproject.toml` and fails on drift, so
  adding a plugin to `[all]` without updating the catalog is caught.
- **AC-B8** — `functualize-bitwarden` is **not** in the recommended set, and the
  reason is recorded next to the assertion so a future edit does not "fix" it.
- **AC-B9** — `func builtin plugin install --recommended` plans the same install
  commands the existing single-package path produces, honours `--yes`, and
  records every installed name via `manifest.record_addition` so `self update`
  restores them.
- **AC-B10** — `install --recommended` with a package already installed is not an
  error.
- **AC-B11** — `--remote` merges PyPI results marked as uncurated; a simulated
  network failure under `--remote` degrades to the shipped catalog with a
  warning and exit code 0.
- **AC-B12** — Every distribution name in the shipped manifest exists as a
  directory under `plugins/` or is justified in the manifest itself. Prevents
  the manifest naming a package that was never published — the failure mode
  `plugins/PUBLISHING.md` calls out for `functualize-interactivity`.

### Part C — the other two surfaces

- **AC-C1** — `func builtin info schema` includes plugin commands, with a `kind`
  distinguishing them from `job` and `builtin`. Asserted against a fake plugin.
- **AC-C2** — `func builtin shell-init bash` emits the plugin namespace and its
  subcommands, so `func mc<TAB>` completes. Asserted on the emitted payload, not
  by driving a shell.
- **AC-C3** — Both are fixed **without** a discovery-cache format change. Both
  run post-boot; a task that reaches for the cache here is out of scope.

### Part D — one precedence rule

- **AC-D1** — A job and a top-level plugin command with the same name resolve
  **identically** through `func <name>`, `app.cli_command`, and
  `build_command_tree`. One rule, asserted across all three in one test.
- **AC-D2** — The chosen rule is the CLI's existing D3: the job wins and the
  shadowed plugin command is absent. Changing which side wins is not in scope —
  making the three agree is.
- **AC-D3** — A **namespaced** collision (`mcp.serve` vs a job at that path) is
  detected on every surface, not only by `_dispatch_group`.
- **AC-D4** — Reaching the CLI through `app.cli_command` no longer silently lets
  a plugin displace a job. Whether the surviving diagnostic is a raise or a
  documented silent win is a Plan decision, but it must be the same on all three
  paths.
- **AC-D5** — A shadowed plugin command is reported to the user somewhere better
  than `logger.debug`. Silent shadowing is how this went unnoticed.

### Part E — plugin-provided jobs

- **AC-E1** — A distribution publishing under `functualize.jobs` has its jobs
  discovered and runnable via `func <job>`, and listed by `func` (TTY and piped),
  the TUI job browser, `info schema`, and completion — the same surfaces a
  directory-scanned job reaches.
- **AC-E2** — **Cold and warm parity.** The same job set is reported on a cold
  cache and a warm one. Tested by running twice, second run against the cache
  written by the first — the failure mode `contributor/reference/pitfalls.md`
  records four instances of.
- **AC-E3** — Uninstalling the providing distribution does not leave the job
  resolvable from a stale cache.
- **AC-E4** — Reachability per `contributor/guides/wiring-discipline.md`: name
  the production call path that instantiates the provider and prove it by
  breaking the call and watching a test fail. This capability has been
  unreachable since it was written; a test that only calls it directly would
  leave it exactly as unreachable.
- **AC-E5** — **DECIDED 2026-09-08: wire it, do not delete it.** Hakim chose the
  full-support option when offered wire / delete / wire-without-cache. So
  `functualize.jobs` becomes a working, supported way for a plugin to publish
  jobs, and the `_NOT_EXTENSIONS` exclusion in `_cli/plugin_cmd.py:52-57` stays —
  its rationale becomes true rather than aspirational. Plan still decides *how*
  the cache is handled (AC-E2, AC-E3 are the gates either way), but not *whether*
  to support the group.
- **AC-E6** — Document it. `functualize.jobs` currently appears in no
  user-facing doc as a job source; a mechanism that starts working needs a place
  that says so (`docs/`, and the plugin-development guide).

### Prevention

- **AC-P1** — A command-inventory parity test: for one app carrying a job, a
  namespaced plugin command, and a builtin, the same command set is reported by
  `build_command_tree`, `info schema`, `extract_completion_data`,
  `_dispatch_group`'s trie, and `app.cli_command`. A surface that later grows its
  own inventory fails here rather than in a user's shell.
  `tests/cli/test_schema_surface_parity.py` compares *field rendering* and is why
  F2/F3/F4 all passed CI; this compares *inventory*.

### Cross-cutting

- **AC-X1** — `uv run lint-imports` passes with zero violations. `_cli/` must not
  import any `_`-prefixed package; the classification helper must live where both
  `_cli/plugin_cmd.py` and the command tree can legally reach it.
- **AC-X2** — `uv run mypy src/` passes.
- **AC-X3** — `uv run pytest tests/skills/ -q` passes. `skills/` prose names
  `func builtin …` strings and is checked against `BUILTIN_COMMANDS`; a new
  subcommand family may require a skills update.
- **AC-X4** — `uv run pytest tests/tui_audit/ -v` passes 15/15.
- **AC-X5** — Reachability: for the new provider, name the production call path
  and prove it by breaking the call and watching a test fail
  (`contributor/guides/wiring-discipline.md`). "A test calls it" is not a call
  path. Both cold and warm-cache paths.

---

## Open questions

1. **Where does the classification helper live?** `_cli/plugin_cmd.py` needs it
   and may not import internals; `app/commands.py` needs it and lives in the
   public `app/` package. A shared home in `app/` (re-exported where needed) is
   the obvious candidate, but it is a public-surface addition — confirm during
   Plan, and check whether it warrants an ADR under the constitution's
   "new public API surface" rule.

2. **Does `PluginCommand` need a terminal declaration?** Behaviour 5 pins
   `needs_terminal = False` for now. A plugin whose command genuinely takes over
   the terminal (an interactive `mcp` inspector, say) would be mis-driven by the
   TUI. Out of scope here; flag if the Plan finds an existing plugin that needs it.

3. **Manifest format and location.** TOML beside the existing `_cli/data/`
   assets, or a Python module? A data file is inert and diffable; a module is
   typed and cannot drift from its own schema. Decide in Plan.

## Verification commands

```bash
uv run ruff check --fix src/ tests/ plugins/ && uv run ruff format src/ tests/ plugins/
uv run mypy src/
uv run lint-imports
uv run pytest tests/skills/ tests/tui_audit/ -q
uv run pytest -k "plugin_cmd or command_tree or plugin_command" -q
```
