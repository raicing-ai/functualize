# Contracts: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Phase**: Specify — **external interfaces only.**

What belongs here: surfaces someone outside this feature depends on — the commands a user
types, the files another tool reads, the environment variables CI sets, the JSON a script
parses, the build inputs a release pipeline supplies.

What is deliberately absent: module layout, internal types, the detection function's
signature, the manifest's in-memory representation. Those are Plan-phase decisions.

---

## 1. Command surface

Every command is a child of the single reserved top-level segment `builtin`. **No top-level
name is added by this feature**, and no deprecation alias is created.

```
func builtin self doctor   [--format json]
func builtin self update   [--yes]
func builtin self install  <package> [--yes]
func builtin self python  [-- <args>...]
func builtin self uv      [-- <args>...]

func builtin plugin list                [--format json]
func builtin plugin install    <package> [--yes]
func builtin plugin uninstall  <package> [--yes]
```

In a consumer application the same commands appear under that application's own script name
(`myapp builtin self update`), and act on **that application's** distribution.

### Conventions these commands inherit

| Convention | Rule | Precedent |
|---|---|---|
| Structured output | Command-owned `--format json`. **Not** `--json`, and not the global `--output` | `builtin workflow list` |
| Confirmation | Every mutating command prints the exact command it will run, then prompts. `--yes` skips the prompt, never the printing | new, but required by AC14/AC18 |
| Terminal ownership | `plugin install` / `plugin uninstall` are terminal-owning and are declared as such **after P1 lands** | `config edit` |

> `builtin info` already uses `--json` (a boolean flag resolved through `resolve_renderer`).
> Fields added to `info` by this feature ride that existing flag; they do **not** introduce a
> second spelling on that command.

**Why two spellings exist across the tree** — audited 2026-09-03, full inventory in
`research.md` §1. Six shipped commands answer "text or JSON?" two ways: `--json` (bool,
honours `[cli] output` / `FUNCTUALIZE_CLI_OUTPUT`) on `why`, `info`, `info jobs`, `info all`;
`--format` (choice, ignores it) on `workflow list`, `workflow state`. This feature adopts
`--format` for **new** commands and rides `--json` where it extends an existing one, so it
adds no new inconsistency and normalizes none. Normalizing is a separate breaking change.

**`--output` is a different axis and is not used here.** The global `--output`
(`auto`/`json`/`ndjson`/`raw`/`none`) governs job emission via `out.emit()`; `builtin
parallel --output` (`interleaved`/`grouped`/`prefixed`) governs layout. Neither is a renderer
selector. No command in this feature accepts `--output`.

### `self python` / `self uv` — two modes on one subcommand

**With `--` and arguments, it runs them** against the owned environment, replacing the
process or proxying its exit code:

```bash
func builtin self python -- -m pip debug
func builtin self uv     -- pip install requests
```

**Bare, it prints the path** — exactly one absolute path, a newline, nothing else; no label,
no decoration:

```bash
func builtin self python          # /home/u/.local/share/pyapp/functualize/0.2.0/bin/python
EDITOR_INTERPRETER=$(func builtin self python)
```

The passthrough is the primary form. `$(…)` is not portable to PowerShell or `cmd`, breaks on
paths containing spaces, and cannot be shown in `--help` — and the binary's audience is the
user with no Python, who is least likely to have a POSIX shell habit. The bare form exists
for the case that genuinely wants a path rather than an execution: configuring an editor or
an external tool.

Everything after `--` is passed through untouched. Diagnostics go to stderr, so the bare
form's stdout stays clean for capture.

**Both forms are terminal-owning.** `CommandNode.needs_terminal` is a plain bool and cannot
vary per invocation (`_types/commands.py:52-70`), so one answer must cover both — and the
passthrough is the one that matters: running `uv pip install` on a TUI worker with captured
stdout is precisely the `skills install` defect P2 fixes. The cost is that bare `self python`
also hands off inside the inline shell to print one line. That is cosmetic; the inverse is a
corrupted interface.

**This does not affect shell capture.** A builtin's `needs_terminal` is read only by the TUI
(`_cli/tui/app.py:2665`, `job_execution.py:425`); the direct CLI path never consults it, so
`$(func builtin self python)` from a shell works regardless.

In a mode with no functualize-owned environment, both forms refuse with exit code `3` and
print nothing to stdout.

### `self install` vs `plugin install`

Same mechanism, different bookkeeping, deliberately not merged:

| | `plugin install` | `self install` |
|---|---|---|
| Intent | extend functualize | satisfy a job's imports |
| Appears in `plugin list` | yes | no |
| Manifest key | `plugins` | `packages` |
| Restored by `self update` | yes | yes |

**Deliberately not merged into one command with a flag** (decided 2026-09-03). The two are
mechanically identical today, and a `--package` flag would be a smaller surface. They stay
separate because **`plugin install` is a seam**: plugin-specific behavior — verifying that a
distribution actually registers a `functualize.*` entry point, warning on framework version
skew, a plugin-aware uninstall that checks nothing still depends on it — has an obvious home
without contorting a general package installer. `self install` stays a plain installer and
does not grow plugin concerns.

The naming is also honest in both directions: `plugin install requests` would misdescribe its
argument, and `self install functualize-mcp` does not claim `functualize-mcp` is *not* a
plugin — it claims only that the user asked for a package.

### Removed from the original design

`func builtin self paths` and `func builtin self config-info` are **not part of this
contract**. Their content is delivered through §3 below.

---

## 2. Exit codes

Drawn from the committed `ExitCode` table; this feature introduces no new code.

| Code | Name | Used when |
|---|---|---|
| `0` | `OK` | The command completed, including a doctor run that reported problems |
| `2` | `USAGE` | The invocation was malformed, or a required external tool is absent |
| `3` | `REFUSED` | **The mode-refusal contract**: a degraded or unknown installation. Guidance is printed, nothing is executed |

`REFUSED` is the load-bearing one: a user or script can distinguish "functualize declined to
act because it does not own this installation" from "the action ran and failed".

---

## 3. Fields added to `builtin info`

Additive only. No existing field changes name, type, or meaning.

**Human-readable form** — `builtin info` gains install mode and owning distribution.
`builtin info all` additionally gains a manifest summary.

**The label is `Install mode:`, not `Mode:`.** `builtin info` already prints a `Mode:` line
under *Runtime State* describing state storage, and its value there is already `standalone`
(meaning "no project directory"). The install mode's `standalone` means "the pre-baked
binary". Both appear in one screen, so the labels must disambiguate them and the JSON keys
must not collide — hence the nesting below.

**JSON form** — `builtin info --json` and `builtin info all --json` gain one object under a
new top-level key:

```json
{
  "install": {
    "mode": "tool_uv",
    "owning_distribution": "functualize",
    "manifest": {
      "path": "/home/user/.config/functualize/install.json",
      "installations": 2,
      "stale": 1
    }
  }
}
```

`manifest` is present in the `info all` payload; the bare `info` payload carries `mode` and
`owning_distribution` only.

---

## 4. Runtime mode values

These strings are a **public vocabulary**: they appear in JSON output, in doctor's report,
and are accepted by the override environment variable. They are stable identifiers, not
display text.

| Value | Meaning | Degraded |
|---|---|---|
| `standalone` | The pre-baked single binary | no |
| `tool_uv` | Installed with `uv tool install` | no |
| `tool_pipx` | Installed with `pipx install` | no |
| `project` | A project checkout whose environment declares functualize | no |
| `tool_pip` | Bare pip into a non-virtual environment | **yes** |
| `unknown` | Unrecognised | **yes** |

Degraded modes refuse every mutating command with exit code `3`.

---

## 5. Environment variables

### Consumed at runtime

| Variable | Contract |
|---|---|
| `FUNCTUALIZE_RUNTIME` | Overrides detection with one of the §4 values, verbatim. Intended for CI and tests. An unrecognised value is a usage error, not a silent fallback |

The test suite strips all `FUNCTUALIZE_*` and `XDG_*` variables automatically, so any test
depending on this must pass it explicitly.

### Read as detection signals, never written

`PYAPP`, `PYAPP_COMMAND_NAME` — injected by the binary's own runtime. Functualize treats
them as read-only evidence.

---

## 6. Install manifest file

A file other tools may read. Its location follows the same user-config directory resolution
as the rest of the CLI (honouring `XDG_CONFIG_HOME`), and is reported by `info all`.

```json
{
  "schema_version": 1,
  "installations": [
    {
      "binary_path": "/usr/local/bin/func",
      "runtime_mode": "standalone",
      "owning_distribution": "functualize",
      "python_version": "3.12.4",
      "functualize_version": "0.1.2",
      "plugins": ["functualize-state-sqlite"],
      "packages": ["requests"],
      "first_run_at": "2026-06-20T10:30:00Z"
    }
  ]
}
```

**Guarantees:**

- `schema_version` is present and integral. A reader encountering a higher version must not
  assume it can parse the file.
- `installations` is **append-only**. Entries are never removed by any command in this
  feature, including when `binary_path` no longer exists.
- `runtime_mode` is one of the §4 values.
- `owning_distribution` distinguishes a functualize-owned install from a consumer
  application's.
- `plugins` records only what was added through `plugin install` — it is not an inventory of
  everything installed.
- `packages` records only what was added through `self install`. The two lists are disjoint
  by construction and are restored together by `self update`.
- `first_run_at` is UTC, ISO 8601.

**Not guaranteed:** ordering, uniqueness of `binary_path` across entries (two installs at
one path over time is a real history), or that any entry still resolves.

---

## 7. Build inputs for the binary

The release pipeline's contract with the binary builder. Recipe **B** (pre-baked, offline)
per decision O1; payload `all` per decision O2.

| Variable | Value |
|---|---|
| `PYAPP_PROJECT_NAME` | `functualize` |
| `PYAPP_PROJECT_VERSION` | the release version |
| `PYAPP_PROJECT_FEATURES` | `all` |
| `PYAPP_EXEC_SPEC` | the console-script entry point declared in `pyproject.toml` |
| `PYAPP_DISTRIBUTION_EMBED` | `1` |
| `PYAPP_DISTRIBUTION_PATH` | the baked distribution artifact — see below |
| `PYAPP_SKIP_INSTALL` | `1` |
| `PYAPP_UV_ENABLED` | `1` |
| `PYAPP_SELF_COMMAND` | `pyapp` |

**No variable is left to an implicit default** (AC25).

### The baked distribution artifact

New CI output with no existing analog in this repository. Per platform and architecture:

- **Input**: a python-build-standalone distribution, plus `functualize[all]`
- **Output**: one archive in which functualize and every first-party plugin are **already
  installed**
- **Consumed as**: `PYAPP_DISTRIBUTION_PATH`

This artifact — not the wheel — is what makes the first run offline-capable. The wheel
continues to be built and published to PyPI unchanged.

### `PYAPP_SELF_COMMAND=pyapp`

The builder's own management group is renamed from its default. Left at the default it would
expose a working `self` command in standalone mode that does not exist in any other mode.
Renaming keeps the surface uniform across installations and keeps the internal updater
reachable at `func pyapp …`.

**`func pyapp …` is internal.** It is not documented to users and carries no stability
guarantee.

---

## 8. Distribution channels

| Channel | Contract |
|---|---|
| GitHub Releases | One binary per supported platform/architecture, attached to the release tag |
| `install.sh` | Detects platform, downloads the matching binary, places it on `PATH` |
| Homebrew formula | Installs the same binary |
| PyPI | Unchanged — the wheel and its extras continue to publish as today |

---

## 9. Interfaces explicitly *not* changed

Stated so the Plan phase treats them as fixed:

- **`builtin config path`** — unchanged. It remains the single answer to "where are my config
  files".
- **The reserved-name rule** — `builtin` stays the one reserved top-level segment. This
  feature adds no top-level name and no alias.
- **`CommandNode`** — the shell's node contract is untouched. **P1 changes only how a
  first-party command *family* resolves terminal ownership internally**; the node's
  terminal-ownership value stays a plain boolean resolved once, as documented today.
- **The subprocess invocation in `skills install`** — correct as written, and not the defect.
  P2 changes only whether the inline shell hands over the terminal. Behavior from a real
  terminal is unchanged (AC29).
- **The global `--output` option** — untouched; this feature uses command-owned `--format`.
