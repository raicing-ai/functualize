# Standalone Examples

Jobs run with the `func` CLI, no project scaffolding required. Seven
directories cover everything — each is self-contained, and each README is a
step-by-step verification checklist you can walk top to bottom.

| Directory | What it covers | Why it's separate |
|-----------|----------------|-------------------|
| [`showcase/`](showcase/) | **The main example.** All three CLI modes, the inline TUI (SmartBar flows, autocomplete, value completions, pre-flight ring, config inspector, settings, ambient displays), every rendering surface (panel, live zone, scrollback, full-screen TTY, adaptive), unix-style args + stdin, environment overlays, and AI in both directions (key-free via `MockAI`) | The one directory to `cd` into for "does the whole thing work?" |
| [`discovery_lab/`](discovery_lab/) | All six discovery filters + `extra_directories` + exclude patterns, flipped per-run via `FUNCTUALIZE_DISCOVERY_*` env vars and CLI flags over a single crafted jobs tree | Filters must start from a *no-filter* project config, which would fight the showcase's job set |
| [`config_lab/`](config_lab/) | The settings precedence chain: CLI > env > `pyproject.toml` > global config > defaults, with a simulated global config activated via `XDG_CONFIG_HOME` | Needs its own `pyproject.toml` filter and global-config pair where *which job gets listed* proves which layer won |
| [`secrets_lab/`](secrets_lab/) | Declaring a credential with `Secret[str]`, discovering what a job needs with `func builtin env`, and the set / unset / empty / required-missing distinction across every surface that renders config | Credentials need a decoy field beside them (`sort_key`, which every name-based heuristic masks and which is not a secret) — that only reads clearly in a project built around the point |
| [`group_options_lab/`](group_options_lab/) | **Flags that belong to a group, not a job.** `class DeployOptions(GroupOptions, group="deploy")` declares `--env` once and every job beneath it inherits it, typed *mid-path*: `deploy --env prod web --region eu-west-1 run v1.2`. Two levels of inheritance, an ungrouped control job, a required positional, and a `Secret[str]` group option | Mid-path flags need a group tree at least two deep with a job under *both* levels — `deploy_tool` is the settings-identity demo and only one deep, so it cannot show inheritance or the deeper group's own flags at all |
| [`composition_lab/`](composition_lab/) | **Capabilities used *together*.** One job per combination — `Fingerprint`×`Sources`, `Deps`×`Guards(status)`, `FromJob` with a config parameter and a pydantic return in one signature, `Invoke.parallel`×`State`, `GroupOptions`, a glob `generates`, a second group, and a `@workflow` with a `Gate` that pauses and resumes. Ships **both** entry points (`func` and `main.py`), and `demo.sh` walks the lot | Every other directory demonstrates one feature. The defects this lab exists for lived *between* features, where no single-feature test looks — and the two command builders (`func`'s live signature, an app's cached descriptors) only disagree when you run both |
| [`deploy_tool/`](deploy_tool/) | **An app that is not `func`.** Its own command name, pyproject table, config file and `DEPLOY_TOOL_*` env prefix; a root flag generated from a setting's `cli_flag`; a `phase="early"` flag read pre-boot; and a bare invocation that opens the interactive shell (`inline_tui = false` to opt out) | The other three configure functualize itself — this one is a *different tool built on it*, which is the only way to show the settings identity and generated flags |

## How `func` works for standalone code

```bash
# Mode A — run a file directly (no discovery)
func my-script.py job_name        # name optional if the file has one job

# Mode B — run a discovered job by name
func deploy --target production

# Mode C — bare func lists jobs; in a terminal it opens the inline TUI
func
```

A "job" is any public top-level function; parameters are injected by type
annotation (a Pydantic config model becomes CLI flags, `RunContext` provides
logging/invoke/state).

## Quick start

```bash
pip install "functualize[cli]"     # inside this repo: uv sync --all-extras && uv run func

cd examples/standalone/showcase
func scripts/hello.py greet --name World   # Mode A
func healthcheck                           # Mode B
func                                       # Mode C / inline TUI
```

Then follow each README's checklist:

1. [`showcase/README.md`](showcase/README.md) — CLI, TUI, surfaces, config inspector, AI
2. [`discovery_lab/README.md`](discovery_lab/README.md) — the filter matrix, one env var at a time
3. [`config_lab/README.md`](config_lab/README.md) — the precedence chain, one layer at a time
4. [`secrets_lab/README.md`](secrets_lab/README.md) — declare, discover, verify a credential
5. [`group_options_lab/README.md`](group_options_lab/README.md) — every mid-path invocation, and the two it must refuse
6. [`composition_lab/README.md`](composition_lab/README.md) — the seams between features, on both surfaces (`./demo.sh`)

## Tests

Every directory ships a `test_*.py` proving the job bodies work (TUI/discovery
behavior is covered by the manual checklists here and the Pilot/integration
tests under `tests/`):

```bash
uv run pytest examples/standalone/ -v
```
