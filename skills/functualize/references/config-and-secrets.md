# Config, `.env`, and secrets

## Two axes, not one ladder

Config resolution has two independent dimensions. Confusing them is the most
common source of "my value isn't being picked up".

**Axis 1 — whose config (directory ladder).** Project directory, then each
parent, then the global XDG directory. **Nearest directory wins overall.**

**Axis 2 — which environment (overlay within one directory).** Each directory
can hold `config.base.toml` plus `config.{env}.toml`. The overlay is
deep-merged on top of the base: overlay keys win, base-only keys survive.

These do not interleave. A project's `config.base.toml` **outranks** a global
`config.prod.toml` — the ladder is about *whose* config it is, not which
environment it names.

## The environment name

The overlay is selected by the first of these set to a valid name, defaulting
to `DEV`:

1. `FUNCTUALIZE_ENV`
2. `ENVIRONMENT`
3. `ENV`

Blank values, or values that are not a valid filename segment
(`[A-Za-z0-9_-]+`), are **skipped rather than erroring**, and the next variable
is tried. This exists specifically because POSIX `sh`/`ksh` set `ENV` to the
path of a startup file, which is not an environment name.

Matching is case-insensitive against the file's slot, so `config.Prod.toml` is
selectable. A file naming any *other* environment is discovered but never
merged — `func`'s inline TUI lists it as `○ inactive`, so a config file that
plainly exists and is not taking effect is visible rather than mysterious.

| `ENVIRONMENT` | Overlay merged |
| --- | --- |
| *(unset)* | `config.dev.toml` |
| `DEV` | `config.dev.toml` |
| `PROD` | `config.prod.toml` |
| `STAGING` | `config.staging.toml` |

## How `.env` correlates with the config files

`.env` is loaded into `os.environ` **before boot builds the resolution chain**.
That gives it two distinct jobs, and the second one is the one people miss:

1. **It supplies values** — `SECTION_KEY` convention (`[server] api_url` →
   `SERVER_API_URL`; empty section means the bare uppercased key).
2. **It selects which config files load** — because `ENVIRONMENT` is read from
   `os.environ` during boot, a single line in `.env` changes which whole
   overlay merges.

```bash
# .env
ENVIRONMENT=prod
DATA_SYNC_API_URL=https://api.prod.example.com
```

This loads `.env`, which sets `ENVIRONMENT=prod`, which makes boot merge
`config.base.toml + config.prod.toml`. The `.env` file is therefore not just a
peer source — it is the **selector** for the file layer.

## Full precedence

Highest to lowest:

| Source | Example |
| --- | --- |
| CLI flags | `--batch-size 2000` |
| Shell environment | `export DATA_SYNC_BATCH_SIZE=500` |
| `.env` values | `DATA_SYNC_BATCH_SIZE=100` |
| Config files (nearest dir; overlay over base) | `batch_size = 50` |
| Pydantic field defaults | `Field(default=25)` |

**python-dotenv does not override existing shell variables.** A shell
`export DATA_SYNC_BATCH_SIZE=500` beats a `.env` saying `100`. This applies to
`ENVIRONMENT` itself: shell `ENVIRONMENT=staging` plus `.env`
`ENVIRONMENT=prod` loads the **staging** overlay.

That single rule explains most "I edited `.env` and nothing changed" reports.
Check the shell first.

## `.env` loading is opt-in for the CLI

- The `func` CLI defaults to **`dotenv = false`**. Opt in per project via
  `[tool.functualize]` in `pyproject.toml`, `FUNCTUALIZE_DOTENV` /
  `FUNCTUALIZE_DOTENV_PATH`, or `--dotenv-file` / `--no-dotenv`.
- Library boot (`ConfigSources`) defaults to `dotenv=True`, loading `./.env`
  from the **current working directory only**. A missing file is not an error.
- There is **no upward directory scan** — a `.env` forgotten in a parent
  directory is never silently picked up. Deliberate.

So "I added `.env` and `func` ignored it" is expected behavior, not a bug.

## Dev vs prod

**Development** — `.env` carries both the environment selector and local
credentials:

```bash
# .env  (gitignored)
ENVIRONMENT=dev
DATA_SYNC_API_KEY=dev-secret-123
```
```bash
func --dotenv-file .env data-sync run
```

**Production / CI** — do not use `.env`. The orchestrator sets real
environment variables, and dotenv is disabled so the run is reproducible:

```bash
export ENVIRONMENT=prod
export DATA_SYNC_API_KEY="$VAULT_SECRET"
func --no-dotenv data-sync run
```

For an embedded app, the equivalent is the `twelve_factor()` preset
(`CLI → Env → Defaults`, no file discovery, `dotenv=False`) rather than the
default `classic()`.

## What to commit

The intended split:

| File | Committed | Holds |
| --- | --- | --- |
| `config.base.toml` | **yes** | What is true in every environment |
| `config.dev.toml`, `config.staging.toml`, `config.prod.toml` | **no** | Per-environment values, including local credentials |
| `.env` | no | Environment population, especially secrets |

Because overlays are not committed, a token in `config.dev.toml` never reaches
git, which makes it a legitimate place for a local development credential.
Confirm the project's `.gitignore` actually enforces this before relying on it —
functualize does not create one:

```gitignore
config.*.toml
!config.base.toml
.env
.env.*
!.env.example
```

Two consequences of that split worth planning for:

- **Dev then exercises a different resolution path than production.** A dev
  credential read from `config.dev.toml` comes through the file source; the
  production one comes through the environment. Putting the dev credential in a
  gitignored `.env` instead keeps both environments on the same mechanism, at
  the cost of losing TOML's typing and sections. Either is defensible; pick
  deliberately.
- **A fresh clone has only `config.base.toml`**, and nothing states what an
  overlay should contain. Commit a `config.dev.toml.example` alongside it, or
  the first thing every new contributor hits is a config they cannot
  reconstruct.

The shape to aim for: **`config.base.toml` holds what is true everywhere and is
the only committed layer, uncommitted overlays hold what differs per
environment, and production secrets live only in the environment.**

## Secrets

Credentials come from the environment or `.env`. **Never from a config file at
any level**, including the XDG directory — those are plain TOML written at
default umask, typically world-readable. There is no encryption, no keyring,
and no restrictive-permission write path anywhere in functualize.

Declare the field secret. **Two markers exist and they are not equivalent** —
verify which one you need:

```python
from pydantic import BaseModel, ConfigDict, Field
from functualize.types import Secret

class SyncConfig(BaseModel):
    # (a) Declaration marker. Settable from ANY source, including a config
    #     file. Recognised by is_secret_field, so `func builtin env`, the CLI
    #     adapter, and prompt masking treat it as secret.
    #     The value stays a plain `str`, so it is NOT masked in log lines,
    #     f-strings, tracebacks, or emitted output.
    api_key: str = Field(default="", json_schema_extra={"secret": True})

    # (b) Value wrapper. Masks everywhere, including f-strings and tracebacks.
    #     Requires arbitrary_types_allowed, and REJECTS a plain string — it
    #     only accepts an actual Secret(...) instance, so a config file or a
    #     bare environment variable cannot populate it today.
    model_config = ConfigDict(arbitrary_types_allowed=True)
    token: Secret
```

`Secret.__str__` and `__repr__` return `•••`; the real value is reachable only
via `.get_secret_value()`. `Stdout.emit()` redacts known secret values from
serialized output — but "known" means values that are actually `Secret`
instances, gathered by `collect_secret_values`. A field marked only with
`json_schema_extra` contributes nothing to that set.

**Practical consequence:** `is_secret_field()` returning `True` does not by
itself mean the value is masked in output. For a credential that must never
appear in a log line, the value has to be a `Secret` instance, which today
means constructing it in job code rather than receiving it from config:

```python
def sync(cfg: SyncConfig, log: Log) -> None:
    token = Secret(cfg.api_key)   # wrap at the boundary
    log(f"using {token}")         # renders ••• 
```

Do not write `api_key: Secret[str]` on a plain `BaseModel`: pydantic raises
`PydanticSchemaGenerationError` at class-definition time because `Secret`
implements no `__get_pydantic_core_schema__`.

`func builtin env` masks secrets by default, and **omits** them entirely from a
child process's environment unless `--include-secrets` is passed. Omission is
deliberate: a tool receiving `•••` fails confusingly, while a tool receiving
nothing fails loudly on the missing credential.

This matters more than usual under a coding agent, because every command and
its output lands in a transcript that gets resumed, uploaded, and pasted into
issues. Declaring a field secret makes that transcript safe by construction.

## The XDG directories

Three, not one:

| Variable | Holds | Fallback |
| --- | --- | --- |
| `XDG_CONFIG_HOME` | `config.toml`, `config.base.toml`, `jobs.d/`, `jobs/` | `~/.config/functualize` |
| `XDG_DATA_HOME` | argument history, config snapshots | platform default |
| `XDG_CACHE_HOME` | state store, discovery cache | platform default |

Layout under the config directory:

```
~/.config/functualize/
├── config.toml          # CLI tool settings: [discovery], [cli], [aliases]
├── config.base.toml     # global job-config defaults, per-job sections
├── jobs.d/<job>.toml    # per-job overrides; group jobs use <group>.<fn>.toml
└── jobs/*.py            # user-global job definitions (needs extra_directories)
```

### Hazard: this directory is shared by every project on the machine

Writing here mutates global state affecting the user's unrelated functualize
projects. `config.toml` in particular carries `[discovery]` and `[aliases]`,
where a careless write can change which jobs *any* project finds.

Rules when writing here at all:

- Only under the job-name prefix you own — `jobs.d/<your-job>.toml`.
- Never edit `config.toml`.
- Never write credentials.
- Say so explicitly; do not modify it as a side effect of another task.

Prefer project-local config. Reach for the XDG directory only when the user has
asked for something to apply across all their projects.

## Debugging

```bash
func builtin info            # which config sources loaded, and from where
func builtin why <job>       # whether a job runs, and why
func builtin env <job>       # resolved config as env vars, secrets masked
```

Work from those three rather than reasoning about the ladder in your head.
