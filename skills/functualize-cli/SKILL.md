---
name: functualize-cli
description: >
  Install, upgrade, inspect and configure the `func` command-line tool itself —
  which environment it lives in, the XDG config and data directories, settings
  precedence, the interactive TUI, the discovery cache and runtime state store,
  shell completions, and where the bundled AI agent skills are installed from.
  Use when `func: command not found`, when `func` is not on PATH or you are
  unsure which environment it lives in, when the wrong version runs, when
  installing or upgrading functualize, when configuring `func` or its TUI,
  when clearing or inspecting the cache or state, when wiring shell
  completions, or when asked where functualize keeps its files. Not for
  inspecting or authoring the jobs in a project — that is the functualize
  skill.
license: MIT
metadata:
  version: "0.2.3"
  project: functualize
---

# Operating the `func` CLI

This skill is about the **tool**, not the jobs you write with it. For authoring
jobs load **`functualize`**; for building a program on it load
**`functualize-app`**.

Everything below is answerable at runtime. Where a command exists, run it rather
than trusting this file — the framework describes the version actually
installed.

---

## 1. Install

`click`, `rich` and `textual` are **optional dependencies**. Installing bare
`functualize` gives you the library and a `func` entry point that cannot run.
Always install the `cli` extra:

| Context | Command |
| --- | --- |
| A project using uv | `uv add "functualize[cli]"` |
| A project using poetry | `poetry add "functualize[cli]"` |
| A standalone tool, isolated | `uv tool install "functualize[cli]"` |
| A PEP 723 single-file script | `dependencies = ["functualize[cli]"]` in the header |
| Everything, including first-party plugins | `functualize[all]` |
| **A machine with no Python at all** | the standalone binary — see below |

**The standalone binary** is one executable with Python and every first-party
plugin already inside it; its first run needs no network. Reach for it only when
installing Python is not an option — a locked-down server, a container, a CI
image. If Python is available, `uv tool install` is smaller and updates faster.

```bash
curl -LsSf https://raw.githubusercontent.com/raicing-ai/functualize/master/install.sh | sh
# Windows:
irm https://raw.githubusercontent.com/raicing-ai/functualize/master/install.ps1 | iex
```

The script reads which dynamic loader is present — not the distribution name —
so it picks the musl archive on Alpine and distroless images, and verifies the
download against the release checksums before installing it.

Two console scripts are installed and they are the same program: `func` and
`functualize`.

**Never install with bare `pip install` into whatever interpreter is on PATH,
and never `--user`.** It appears to succeed, fixes nothing, and leaves a second
functualize on the machine that the project will not use.

## 2. Find out which `func` is running

`func` frequently is not on PATH, and the failure looks like the tool being
absent when it is merely elsewhere. Detect from the project root — innermost
dependency manager wins:

| Marker in the repo | Prefix |
| --- | --- |
| `uv.lock`, or `[tool.uv]` in `pyproject.toml` | `uv run func` |
| `poetry.lock` | `poetry run func` |
| `Pipfile.lock` | `pipenv run func` |
| `.venv/` and nothing above | `.venv/bin/func` |
| `mise.toml` / `.tool-versions` | may already put the venv on PATH — try bare `func` |

Version managers and dependency managers **compose**: `mise` chooses the Python
and the `uv`, `uv` chooses the packages. A repo with both takes its prefix from
`uv`. Confirm with one command:

```bash
<prefix> func builtin version
```

`--version` also works and answers before anything boots, which makes it the
cheapest reachability check. The long tail — conda, pipx, pyenv without a venv,
Docker, mise+poetry — is in the `functualize` skill's
[environment reference](../functualize/references/environment.md).

**Ask the tool rather than deducing it.** `func builtin self doctor` reports how
this `func` was installed, which distribution owns it, whether the CLI can
actually boot here, and every other `func` that has run on the machine:

```bash
func builtin self doctor              # a report, human-readable
func builtin self doctor --format json
```

It runs **before the app boots**, so it still answers when `func` itself is
broken — which is the one moment the question matters most. `func builtin info`
carries the same install mode and owner in its overview.

## 3. Upgrade and uninstall

**Prefer `func builtin self update`.** It works out which of the commands below
applies to *this* installation, prints the exact command before running it, and
afterwards restores anything you had added to the environment — including
packages the upgrade removed that were never recorded anywhere.

```bash
func builtin self update          # prints the command, asks, then runs it
func builtin self update --yes    # for scripts; still prints what it ran
```

It manages the standalone binary, a `uv tool` install, a `pipx` install and a
project checkout. A bare `pip install` into a system interpreter is **not**
self-managing: the command prints guidance, changes nothing, and exits `3`. That
refusal is deliberate — see §1 on why that install shape is a trap.

The manual equivalents, for when you want to drive it yourself:

```bash
uv add "functualize[cli]" --upgrade      # in a project
uv tool upgrade functualize              # a uv-managed tool install
uv tool uninstall functualize
```

Adding to the installation, rather than upgrading it:

```bash
func builtin self install <package>     # a dependency your jobs import
func builtin plugin list                # what extends this installation
func builtin plugin install <package>   # an extension
func builtin plugin uninstall <package>
```

Both record what they added, so `self update` puts it back after an upgrade.
`self install` stays out of `plugin list`; a plain dependency is not an
extension. For anything these decline to do, drive the tools directly:

```bash
func builtin self uv -- pip install --index-url ... some-package
func builtin self python -- -m pip debug
```

Two things do **not** move with the package and are worth knowing about after an
upgrade:

- The **discovery cache** is versioned and rebuilt when its format changes, but
  `func builtin cache clear` is the reliable way to force it after an upgrade
  that changed job metadata.
- **Materialized agent skills** are stamped with the version that wrote them
  (§7). An upgrade does not rewrite them; re-run `func builtin skills
  materialize`.

---

## 4. Where functualize keeps files

Four locations, three roles. Knowing which is which is most of the debugging.

| What | Where | Delete it? |
| --- | --- | --- |
| User config | `$XDG_CONFIG_HOME/functualize/config.toml` (else `~/.config/…`) | Yours — deleting resets your preferences |
| Materialized agent skills | `$XDG_DATA_HOME/functualize/skills/func-<version>/` | Safe — regenerate with `skills materialize` |
| Discovery cache | project `.functualize/`, else `$XDG_CACHE_HOME/functualize/<project-id>/` | Safe — rebuilt on next run |
| Runtime state (fingerprints, history, scopes) | same two modes as the cache | Safe, but you lose freshness records and history |

```bash
func builtin config path     # every config file, found or missing, in order
func builtin state show      # runtime state stats and the path in use
func builtin cache show      # entry count, stale count, cache path
func builtin skills path     # the skills shipped with this version
```

### The two project modes

Cache and state resolve the same way, and which mode you are in changes where
they land:

- **Project mode** — a `.functualize/` directory is found by walking upward.
  Everything lands there.
- **Standalone mode** — none found. Everything lands in an XDG cache directory
  keyed by a hash of the path.

For anything with a repository, run `mkdir .functualize`. Then `rm -rf
.functualize` is a complete reset and your freshness ledger is somewhere you can
see it. `func builtin state show` prints which mode is active — check it before
concluding a fingerprint is broken.

---

## 5. Configure

### Precedence

Lowest to highest: **defaults → user XDG config → project config → environment
→ CLI flags**. `func builtin config show` prints each resolved value *with the
source that won*, which is the fastest way to settle "why is this not taking
effect".

Project config is read from `.functualize.toml`, or `[tool.functualize]` in
`pyproject.toml`.

### Settings

Addressed by dotted name; every one has an environment variable, formed as
`FUNCTUALIZE_<SECTION>_<KEY>`.

| Section | Settings |
| --- | --- |
| `cli` | `output` (`rich`/`plain`/`json`), `show_timing`, `inline_tui` |
| `discovery` | `scan_depth`, `extra_directories`, `exclude_patterns`, `require_file_prefix`/`_postfix`/`_import`/`_marker`, `require_job_prefix`/`_postfix`/`_decorators` |
| `plugins` | `strict` |
| `shell` | `program`, `sudo_password` |
| `tui` | `theme`, `default_surface`, `display_auto_switch`, `show_session_stamp`, `history_retention`, `signature_enabled`, `sensitive_keywords`, `default_override_target` |

```bash
func builtin config show                 # resolved values + sources
func builtin config path                 # which files are consulted
func builtin config edit                 # open the user config in $EDITOR
FUNCTUALIZE_CLI_OUTPUT=json func …       # override for one run
```

> **Three unrelated things are called "output".** They share a word and nothing
> else, so read which one a message is about before changing anything:
>
> | Spelling | Chooses | Values |
> | --- | --- | --- |
> | `[cli] output` setting | how **builtin commands** render | `rich`, `plain`, `json` |
> | `--output` global flag | how `Stdout.emit()` *serializes* a job's output | `auto`, `json`, `ndjson`, `raw`, `none` |
> | `builtin parallel --output` | how concurrent jobs' streams are *arranged* | `interleaved`, `grouped`, `prefixed` |

`[cli] output` is what an agent should set once instead of passing a flag on
every call:

```bash
export FUNCTUALIZE_CLI_OUTPUT=json     # builtin info / info jobs / info all emit JSON
export FUNCTUALIZE_CLI_OUTPUT=plain    # same facts, no box-drawing characters
```

An explicit `--json` overrides the setting, so a project pinned to `plain` can
still be asked for structure.

Both `func --help` and `func builtin info --help` name this variable, so it is
discoverable without reading this file — which is the point. Setting it once at
the start of a session is worth more than remembering a flag.

### Secrets are not config

The XDG config file is plain TOML at default umask, shared by every project on
the machine. Credentials belong in the environment or a `.env`, declared
`Secret[str]` so they render as `•••` everywhere. `func builtin env <job>`
exports a job's resolved config as environment variables and **masks secrets by
default** — `--include-secrets` is opt-in and should never be piped into a
transcript.

---

## 6. Day-to-day operator commands

```bash
func                          # at a TTY: the interactive TUI
                              # piped: a parseable job list, one per line
func builtin info             # config resolution, state path, skills
func builtin info schema --kind builtin   # func's own commands, as JSON Schema
func builtin history          # recent job and shell runs
func builtin cache clear      # force the cold discovery path
func builtin state clear      # reset fingerprints, history, scopes
func builtin parallel a b c   # run several jobs concurrently
func builtin env <job>        # resolved config as env vars (secrets masked)
func builtin domains list     # installed domain SDKs and their providers
func builtin workflow list    # active workflow scopes
```

**Inspecting the project's own jobs belongs to the `functualize` skill**, not
here. `func builtin info jobs`, `info schema --kind job`, `why <job>` and the
machine-readable job catalogue are all about the app you are working on rather
than about the tool; that skill's §1 owns them.

**Bare `func` behaves differently piped.** At a TTY it launches the TUI; through
a pipe it prints job names, one per line, which is what to script against. Set
`cli.inline_tui = false` to stop the TTY case from launching the shell.

**Cold and warm are different programs.** A warm run builds commands from the
discovery cache and may never import your job file. When behaviour differs
between two runs of the same command, `func builtin cache clear` and compare.

Shell completions:

```bash
func builtin shell-init bash              # or zsh, fish — prints the script
func builtin shell-init bash --install    # write it under the cache dir instead
```

---

## 7. The AI agent skills shipped with functualize

Functualize ships the skills that teach an agent to use it, inside the
distribution. They are always the version you have installed.

```bash
func builtin skills list          # what ships, with descriptions
func builtin skills path          # the directory, for composing
func builtin skills install       # install into this project via the skills CLI
func builtin skills materialize   # copy to $XDG_DATA_HOME, version-stamped
```

`install` shells out to `npx skills add <local path>`, which handles the
per-agent destination matrix. Because the source is the local directory, what
lands is pinned to the installed functualize rather than whatever the project's
main branch says today.

Without Node, point your agent at the directory yourself:

```bash
cp -R "$(func builtin skills path)"/* .claude/skills/
```

`materialize` is for when the environment holding the wheel is disposable
(`uvx`, a PEP 723 script env, a rebuilt venv) or when a project that does not
depend on functualize still needs a stable path. It writes
`$XDG_DATA_HOME/functualize/skills/func-<version>/`, replacing that version's
tree wholesale; `--prune` also removes other versions' trees.

---

## 8. When something is wrong

| Symptom | First command | Usual cause |
| --- | --- | --- |
| "What can I even run here?" | `func builtin info schema` | Nothing wrong — this is the one-call answer for jobs *and* builtins, no `--help` walking |
| "What does this builtin take?" | `func builtin info schema builtin.skills.materialize` | Address any command by its dotted path |
| `func: command not found` | `<prefix> func --version` | Not on PATH; §2 |
| A job does not appear | `func builtin why <job>` | Discovery filters, or a stale cache |
| Behaviour differs between runs | `func builtin cache clear` | Warm path never imported the file |
| A config value has no effect | `func builtin config show` | A higher layer wins; read the source column |
| "It will not re-run" | `func builtin why <job>`, then `func builtin state show` | Fingerprint fresh, or standalone mode pointing at a different ledger |
| A credential leaked into output | check for `Secret[str]` on the field | Marker-only declaration does not mask |
| Wrong functualize version runs | `func builtin self doctor` — it lists every `func` that has run on this machine, with its version and install mode | A second install, usually from a bare `pip install` |
