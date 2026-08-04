# deploy_tool — a functualize app that is not `func`

Everything else under `examples/standalone/` configures **functualize itself**.
This one is a *different tool* built on functualize: its own command name,
its own settings file, its own environment prefix, and its own interactive
shell. It exists to demonstrate the four capabilities convergence Phase C
added for project apps.

```bash
cd examples/standalone/deploy_tool
uv sync
uv run deploy-tool --help
```

## 1. Its own settings identity

`deploy-tool` and `func` can be installed on the same machine and configured in
the same `pyproject.toml` without seeing each other's values:

| | `func` | `deploy-tool` |
|---|---|---|
| pyproject table | `[tool.functualize]` | `[tool.deploy-tool]` |
| own config file | `.functualize.toml` | `.deploy-tool.toml` |
| env prefix | `FUNCTUALIZE_*` | `DEPLOY_TOOL_*` |
| global config | `~/.config/functualize/` | `~/.config/deploy-tool/` |

All four come from the `AppSettingsSchema` in `deploy_tool/main.py`
(`settings_schema()`). Note that **`app_name` alone is not enough** — it
namespaces the global config *file*, not the environment variables. The env
prefix comes from `env_prefix` on the schema, and the pyproject table from
`file_section_prefixes`.

## 2. A generated root flag

`--environment` is not written anywhere as a `click.Option`. The setting
declares `cli_flag="--environment"`, and the flag is generated from that:

```bash
uv run deploy-tool --help              # --environment is listed
uv run deploy-tool --environment prod status
```

Resolution order, highest last:

```
default  <  config file  <  DEPLOY_TOOL_DEPLOY_ENVIRONMENT  <  --environment
```

A setting that declares no `cli_flag` stays file/env-only and does **not**
appear in `--help`. That is the whole distinction the field encodes.

## 3. An `phase="early"` flag

`--config-profile` declares `phase="early"`, so it is read from `argv`
*before the app is constructed*:

```bash
uv run deploy-tool --config-profile staging status
```

It has to be early. By the time the click callback runs, discovery has already
happened — a profile that selects *which jobs exist* would be applied too late
to have any effect. Ordinary flags like `--environment` have no such
constraint and resolve at callback time.

Both spellings work (`--config-profile staging` and `--config-profile=staging`).
A trailing `--config-profile` with no value is left for the real parser to
report rather than guessed at.

## 4. Bare invocation opens the shell

```bash
uv run deploy-tool          # at a TTY: the interactive shell
```

The job browser lists `status` and the `deploy` group; Enter on `deploy` drills
into `web` and `api`. `!` runs a shell command; `?` is reserved.

To make a bare invocation print help instead — the conventional CLI behaviour —
set:

```toml
[tool.deploy-tool.cli]
inline_tui = false
```

The opt-out wins even at a TTY (otherwise it would not be an opt-out), and a
non-TTY invocation prints help regardless, since there is no terminal to hand
a shell.

## Jobs

| Job | Group | What it shows |
|---|---|---|
| `status` | — | a top-level job, so the tree is not only groups |
| `web` | `deploy` | nested group; drill-down target in the shell |
| `api` | `deploy` | a second leaf, so `deploy` is navigable |

```bash
uv run deploy-tool status
uv run deploy-tool deploy web --dry-run
uv run deploy-tool deploy api --replicas 3
```

## Tests

```bash
uv run pytest tests/
```

They assert the parts that are load-bearing: the settings identity (including
the `app_name`-is-not-enough trap above), that both flags are generated from
declarations, and that only `--config-profile` is early.
