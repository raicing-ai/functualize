# Audit — plugin namespaces and discovery

Date: 2026-09-08. Method: code reading plus in-process probes and live PTY
observation, against `examples/standalone/showcase` (20 jobs) with
`functualize-mcp` installed editable. Every finding below is reproduced, not
inferred.

**Summary:** the original bug was one missing provider. It is not one bug. The
same omission repeats independently on **four** surfaces, and a fifth defect —
conflict precedence — resolves three different ways depending on how you reach
the app. Separately, the entry-point mechanism for plugin-*provided jobs* is
entirely unwired.

| # | Severity | Finding | Surface |
|---|---|---|---|
| F1 | High | `functualize.jobs` is a dead entry-point group | all |
| F2 | High | Plugin commands absent from `build_command_tree()` | TUI |
| F3 | High | Plugin commands absent from `info schema` | agents |
| F4 | High | Plugin commands absent from shell completion | shell |
| F5 | High | Job/plugin conflict resolves 3 different ways | cross-surface |
| F6 | Minor | Wrong `prog_name` in plugin subcommand help | CLI |
| F7 | Minor | Plugin group listing is not column-aligned | CLI |

---

## F1 — `functualize.jobs` is a dead entry-point group (High)

**A distribution that publishes jobs under `functualize.jobs` has them
discovered by nothing, on every surface.**

`EntryPointProvider` (`_discovery/providers.py:750`) is the only reader of that
group. Evidence:

```
$ grep -rn "EntryPointProvider(" src/
NONE IN src/
```

It is referenced in exactly three non-test places, all of them declarations:
`_discovery/providers.py:750` (the class), and `_discovery/__init__.py:23,41`
(the export). Its only instantiation anywhere in the repository is
`tests/discovery/test_builtin_providers.py`.

It is also **not re-exported from any public package** — not `app/`, `plugin/`,
`types/`, or `job/`. So a user cannot even wire it manually without importing
`functualize._discovery`, which the constitution forbids users from doing.

This is the repo's own documented failure mode — built, unit-tested, and
unreachable (`contributor/guides/wiring-discipline.md`). It is the fourth
instance.

**The contradiction that makes it a defect rather than dead code.**
`_cli/plugin_cmd.py:52-57` deliberately excludes `functualize.jobs` from
`plugin list`, and says why:

> Job *sources*, not extensions. A distribution publishing jobs under this
> group is supplying work for functualize to run […] and listing it under
> `plugin list` would invite a `plugin uninstall` that removes somebody's jobs.

That reasoning is only sound if the group works. It does not. The code reserves
and protects a mechanism that no code path consumes.

**No shipped plugin registers jobs by any mechanism.** `grep` for
`add_job_provider|register_job|job_providers` across `plugins/*/src/` returns
nothing. Two plugins register *commands* (`functualize-http`,
`functualize-mcp`); none supplies jobs. So the whole plugin-provided-job axis is
untested in practice, which is why this survived.

**Decide during Plan:** wire `EntryPointProvider` into the boot path, or delete
it and the `_NOT_EXTENSIONS` exclusion together. Wiring it is what the user
asked for ("plugin jobs properly detected"), but it must then also reach the
discovery cache, or plugin jobs appear cold and vanish warm — see the note on
cache scope at the end.

---

## F2 — Plugin commands absent from the command tree (High)

The original report. `build_command_tree()` (`app/commands.py:368`) composes
`JobCommandProvider` + `ClickCommandProvider` only; no file under `_cli/tui/`
calls `get_plugin_commands()`.

In-process against showcase:

```
jobs discovered: 20
plugin commands: [('mcp','serve'), ('mcp','start'), ('mcp','list'),
                  ('mcp','stop'), ('mcp','schema'), ('mcp','tools')]
build_command_tree top-level: ['analyze', ..., 'transform', 'builtin']
'mcp' in tree? False
```

**Live consequence is worse than "missing from a list".** Typing `mcp serve`
into the SmartBar and pressing Enter is **completely inert** — no preflight, no
error, no `● Ready`, nothing. Control with a real job renders:

```
 status — Show system status (no args needed).
 Ctrl+Enter run  ·  Ctrl+S save as shortcut
```

For `mcp serve` none of those lines appear. `_render_tree_preflight`
(`_cli/tui/app.py:2620`) resolves against the tree, gets `None`, and returns
`False`; the fall-through produces no visible feedback. A user gets silence.

Downstream readers all inherit the gap: `command_tree_rows`
(`_cli/tui/job_listing.py:36`), `_command_tree_names` (`_cli/tui/app.py:2079`),
`_node_needs_terminal` (`_cli/tui/job_execution.py:447`).

**Secondary:** `command_tree_rows` hardcodes `source_label="builtin"` for any
node lacking a job descriptor (`_cli/tui/job_listing.py:44`). Adding plugin
nodes naively would label `mcp` as first-party.

---

## F3 — Plugin commands absent from `info schema` (High)

`func builtin info schema` is advertised in the epilog of **every** `func
--help` as the agent-facing index:

```
func builtin info schema                 all commands, as JSON
```

It is not all commands.

```
$ func builtin info schema > schema.json
entries: 67
kinds: Counter({'builtin': 47, 'job': 20})
mcp present: False
```

The `kind` enum admits only `job` and `builtin`. `func mcp serve` — a working,
installed, executable command — is undiscoverable by the exact consumer this
surface exists for.

This runs on a **booted** app, so `get_plugin_commands()` is available. No cache
change is needed to fix it.

---

## F4 — Plugin commands absent from shell completion (High)

`extract_completion_data` (`_cli/completions/data.py:112`) builds the trie from
jobs only:

```python
jobs = func_app.get_jobs()
trie = build_group_trie(
    [(j.group, j.name, "job") for j in jobs],
    group_options=specs,
)
```

`build_group_trie`'s second positional parameter is `plugin_namespaces`
(`app/utils.py:1517`) — the same one `_dispatch_group` passes `plugin_rows` to
(`_cli/main.py:986`). Here it is omitted. The `builtin` subtree is spliced in
separately from the registry (`data.py:187-191`); plugin commands are spliced in
nowhere.

Empirically:

```
$ func builtin shell-init bash | grep -c ...
deploy:  9
builtin: 14
mcp:     0
```

So `func mc<TAB>` completes nothing. Like F3 this runs post-boot — its own
docstring says "from a **booted** app" — so it is fixable without touching the
cache.

---

## F5 — Job/plugin conflict resolves three different ways (High)

One app, one collision, three outcomes. Reproduced with a job named `collide`
and a top-level plugin command named `collide`:

```
app.cli_command -> 'collide' help: PLUGIN version
  => which one won: PLUGIN
_dispatch_group D3 keeps plugin rows: [...mcp only...]   => JOB wins
check_name_conflicts: RAISED -> Plugin command name 'collide' conflicts...
```

| Path | Outcome |
|---|---|
| `func collide` (`_dispatch_group`, `_cli/main.py:936-939`) | **job wins**, plugin dropped, `logger.debug` only |
| `app.cli_command` (`adapters/cli.py:815`) | **plugin wins**, silently |
| `CliAdapter.run()` (`adapters/cli.py:830`) | **ValueError**, hard failure |

**Why `app.cli_command` lets the plugin win.** `adapters/cli.py:802-803`
registers jobs first, then plugin commands, and click's `add_command` overwrites
by name. `check_name_conflicts` is called only from `run()` — the `cli_command`
property never calls it, and that property is documented at `adapters/cli.py:115`
as a supported public access path.

**And the check is narrower than the CLI's rule.** `check_name_conflicts`
inspects only `cmd.namespace is None`, so a *namespaced* collision is never
checked — while `_dispatch_group` checks exactly that case, keying on
`f"{namespace}.{cmd.name}"` (`_cli/main.py:934`).

Per `contributor/architecture/surface-boundary.md` the test is whether a feature
is about *the program* or *how you reach the program*. Precedence is about the
program, so this is a parity violation, not a permitted divergence.

---

## F6 — Wrong `prog_name` in plugin subcommand help (Minor)

```
$ func mcp serve --help
Usage: serve [OPTIONS]
```

Should be `func mcp serve`. The ad-hoc command is invoked without a `prog_name`,
so click falls back to the callback name. Copy-pasting the usage line gives a
command that does not exist.

## F7 — Plugin group listing is not column-aligned (Minor)

```
Commands:
  list  List running MCP servers
  schema  Export job schemas in multiple formats
  serve  Start MCP server
```

Descriptions do not align, unlike every click-rendered listing and unlike
`render_extensions` (`_cli/plugin_cmd.py:131`), which pads to the widest name.

---

## Confirmed clean

- **Reserved-name enforcement.** `_validate_builtin_reservation`
  (`_app/boot.py:1375`) covers plugin commands *and* namespaces, not just jobs,
  and rejects both `builtin` and shell sigils. Its docstring notes this was
  previously "only claimed by this docstring, not checked" — it is checked now.
- **`func <namespace>` and `func <namespace> <cmd>` dispatch.** Both work.
  `func mcp` lists six subcommands; `func mcp serve --help` renders its options.
- **Bare non-TTY `func`.** Correctly prints
  `mcp — 6 commands (run 'func mcp' to list)` (`_cli/main.py:583-590`).
- **`app.cli_command` command registration.** `register_plugin_commands`
  (`adapters/cli.py:562`) mounts namespaced sub-groups correctly. Its defect is
  precedence (F5), not registration.

---

## Design note — cache scope, and why it bounds the fix

Plugin namespaces are registered at `APP_READY` and are therefore absent from
the discovery cache. `build_group_trie`'s docstring states it plainly:
"`plugin_namespaces`: … Empty pre-boot — plugin commands are not cached."

That is why `func mcp serve` classifies as `Mode.UNKNOWN`, boots, and only then
recovers inside `_dispatch_group` (`_cli/main.py:779-782`).

**This bounds the work usefully.** F2, F3 and F4 all run on a booted app, so all
three are fixable with no cache-format change. Only two things would need the
cache: making `func --help` show plugin commands (explicitly out of scope by
decision) and removing the `Mode.UNKNOWN` detour (a performance concern, not a
defect).

**F1 is the exception.** Wiring `EntryPointProvider` puts plugin-provided *jobs*
into `get_jobs()`, which the cache *does* serve. If those jobs are written to
the cache, uninstalling the plugin leaves stale entries; if they are not, they
appear cold and vanish warm — the exact class of defect
`contributor/reference/pitfalls.md` records four of. Decide the cache
interaction in Plan, explicitly, and test both cold and warm.

## Prevention

`tests/cli/test_schema_surface_parity.py` exists because two renderings of one
contract drifted (`Stdout`/`Shell` shipped as required MCP arguments). It
compares *field rendering* across surfaces, not *command inventory* — which is
why F2/F3/F4 all passed it.

The durable fix is a command-inventory parity test: for one app with a job, a
namespaced plugin command and a builtin, assert the same command set is reported
by `build_command_tree`, `info schema`, `extract_completion_data`,
`_dispatch_group`'s trie, and `app.cli_command`. Any surface that grows its own
inventory later fails there instead of in a user's shell.
