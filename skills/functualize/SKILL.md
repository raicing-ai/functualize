---
name: functualize
description: >
  Write, run, and debug functualize jobs — job functions, RunContext
  capabilities (Log, Invoke, Prompt, State, Stdout, Shell, Live), layered
  config, secrets, and discovery rules. Use when editing jobs.py or any file
  defining functualize jobs, when a job is not being discovered, when wiring
  job config or credentials, when listing or inspecting the jobs an app
  exposes — a machine-readable catalogue of every job and the arguments it
  takes, as JSON Schema — or when the user mentions functualize, `func run`,
  `func builtin`, `builtin info`, RunContext, or @job. Not for installing,
  upgrading, or configuring the `func` tool itself — use functualize-cli.
license: MIT
metadata:
  version: "0.1.0"
  project: functualize
---

# Functualize

A Python CLI framework. Users write plain functions; functualize discovers
them, injects capabilities, resolves layered config, and exposes them as CLI
commands, a TUI, and MCP tools.

**Never guess.** A functualize app describes itself at runtime. Every question
below has a command that answers it exactly, against the version actually
installed. Prefer running the command over recalling the API.

> **Are you changing functualize itself?** This skill — and its siblings
> `functualize-cli`, `functualize-app`, `functualize-skill` — describe how to
> *use* the framework, not how it is built. Adding a capability type, changing
> discovery, editing `src/functualize/`: none of that is covered here, and the
> answers here will be confidently wrong about internals. Say so, and point the
> user at the functualize repository's own `AGENTS.md` and `contributor/`
> guides, whose skills and steering docs cover the layering rules this skill
> deliberately hides.

---

## 0. Resolve how to invoke functualize — before anything else

`func` may not be on PATH. It depends on how the project manages its
environment, and guessing wrong ends in `command not found` followed by a
`pip install` into the wrong interpreter. Establish the prefix first, then
reuse it for the rest of the session.

Detect from the project root, innermost dependency manager wins:

| Marker in the repo | Invocation prefix |
| --- | --- |
| `uv.lock`, or `[tool.uv]` in `pyproject.toml` | `uv run func` |
| `poetry.lock` | `poetry run func` |
| `Pipfile.lock` | `pipenv run func` |
| `.venv/` and nothing above | `.venv/bin/func` |
| `mise.toml` / `.tool-versions` | may already put `.venv/bin` on PATH — try bare `func` first |

Version managers and dependency managers **compose**; this is not an if/elif
chain. `mise` decides which Python and which `uv`; `uv` decides which
packages. A repo with both takes its prefix from `uv`, running under the
interpreter mise selected. Bare `func` works only when a shell activation has
already put the venv on PATH.

Confirm reachability and identity with one command:

```bash
<prefix> func builtin version
```

If that fails, functualize is not reachable from this environment. **Do not
install it silently.** Report what you found, propose installing into the
detected context — `uv add "functualize[cli]"`, `poetry add "functualize[cli]"`
— and let the human decide. The `[cli]` extra is not optional in practice:
`click`, `rich` and `textual` live there, so a bare `functualize` installs a
`func` that cannot run. Never `pip install` bare, never `--user`, never system
Python — it appears to succeed, fixes nothing, and leaves the machine dirtier.

Long tail (conda, pipx, pyenv without a venv, Docker, mise+poetry):
[references/environment.md](references/environment.md). Installing, upgrading and
configuring `func` itself is the **`functualize-cli`** skill.

---

## 1. Orient

```bash
<prefix> func builtin info          # discovered jobs, config sources, settings
<prefix> func builtin info schema   # EVERY job and its arguments, as JSON
<prefix> func builtin info jobs     # the catalogue; add --json for structure
<prefix> func builtin why <job>     # why a job would or would not run
<prefix> func <job> --help          # a job's real flags, from its signature
```

**`info schema` is the one to reach for first.** One call returns every
command's input contract as JSON Schema — name, description, parameter types,
defaults, which are required — so there is no need to walk each group's
`--help` one command at a time. It covers **jobs and builtins alike**, because
both are nodes in one command tree. It is the same renderer that builds the MCP
tool definitions, so what you read is exactly what a tool call would accept.

```bash
<prefix> func builtin info schema --kind job      # the project's jobs only
<prefix> func builtin info schema --kind builtin  # func's own commands only
<prefix> func builtin info schema <name>          # one command, by dotted path
<prefix> func builtin info jobs <job>             # one job in detail, human-readable
<prefix> func builtin info all --json             # jobs + config + environment
```

Each entry carries `kind` (`job` or `builtin`) and `path` — the segments to
type, as an array, so there is nothing to re-split:

```json
{"name": "audit.report", "kind": "job", "path": ["audit", "report"],
 "description": "Emit the audit report.",
 "inputSchema": {"type": "object",
                 "properties": {"rows": {"type": "integer", "default": 3}}}}
```

`func --help` names these at the bottom, so a bare `--help` is a safe first
call when you have forgotten the exact spelling — it also names
`FUNCTUALIZE_CLI_OUTPUT`, which makes JSON the default and saves passing a flag
on every subsequent call.

Never invent a job name, a config key, or a flag. `builtin info` is the
authority, and it reflects the installed version rather than any
documentation — including this file.

---

## 2. Four things that are wrong by default

These are invisible from the file you are editing. An untutored guess produces
code that reads correctly and does not work.

### 2.1 Capabilities are injected by parameter type — never constructed

Declare what you need in the signature and it arrives. Do not instantiate a
capability, do not import `logging`, do not thread anything through by hand.

```python
# WRONG
def deploy(rc: RunContext):
    log = Log()                      # capabilities are not constructed
    logging.getLogger(__name__).info("...")   # not stdlib logging
```

```python
# RIGHT
from functualize.job import RunContext, Log, Shell

def deploy(rc: RunContext, log: Log, sh: Shell) -> None:
    log("Starting deployment")       # Log is callable
    log.warning("disk almost full")  # and has .info/.warning/.error/.debug
```

The full set is exported from `functualize.job`: `Log`, `Invoke`, `Prompt`,
`Perf`, `Shell`, `State`, `Stdout`, `TTY`, `Live`, `JobContext`,
`JobConfigView`. One per concern; see
[references/capabilities.md](references/capabilities.md).

### 2.2 A job is a plain function — the decorator is optional

```python
# This is a complete, runnable job. No decorator required.
def deploy(rc: RunContext) -> None:
    """Deploy the application to production."""
```

`@job` from `functualize.job` exists to *declare* things — dependencies,
retries, guards, fingerprints — not to register the function. Reach for it
when you need those, not by reflex.

### 2.3 Returning a value does not print it

Output goes through the `Stdout` capability. A returned value is for
programmatic callers (`Invoke`, `FromJob`) and is not written to the terminal.

```python
# WRONG — prints nothing
def report(rc: RunContext) -> dict:
    return {"status": "ok"}
```

```python
# RIGHT
from functualize.job import RunContext, Stdout

def report(rc: RunContext, out: Stdout) -> None:
    out.emit({"status": "ok"})       # serialized per --output
```

`out.emit()` respects `--output` (`auto` — the default, dispatching on the
emitted value's type — plus `json`, `ndjson`, `raw`, `none`), so the same job is
human-readable and machine-parseable without branching.
`out.write()` is raw passthrough — no serialization, no newline.

### 2.4 Discovery is convention plus filters — valid code can still be invisible

A correct function may not appear, because discovery is narrowed by file and
job filters (`require_file_import`, `require_job_prefix`,
`require_job_decorators`, `exclude`, scan depth) from config or flags. Job and
group names are canonical: lowercase, hyphenated, normalized on resolution.

When a job does not show up, do not edit the function hoping to fix it:

```bash
<prefix> func builtin why <job>
```

See [references/discovery.md](references/discovery.md).

---

## 3. Config and secrets

Job config resolves through a layered chain (defaults → user XDG → project →
env → CLI). Credentials come from the **environment or `.env`**, never from a
config file.

**A credential is a field on a config model, not a job parameter.** The shape:

```python
class NotifyConfig(BaseModel):
    api_key: str = Field(default="", json_schema_extra={"secret": True})

def notify(config: NotifyConfig, log: Log) -> None:
    key = Secret(config.api_key)     # wrap at the boundary; renders •••
    log(f"using {key}")
```

Set it with `<JOB>_<FIELD>` or bare `<FIELD>` in the environment —
`NOTIFY_API_KEY=… func notify`.

Do **not** write `api_key: Secret[str]` as a job *parameter*: no CLI flag is
generated for it and no environment variable populates it, so the job cannot be
invoked at all — while `builtin info schema` still advertises it as a required
input. `Secret[str]` is a value wrapper for use inside the job, not a way to
receive one.

This matters more than usual here: everything a coding agent runs lands in a
transcript. Declaring a field secret makes that transcript safe by
construction.

Full rules, the XDG layout, and the hazards:
[references/config-and-secrets.md](references/config-and-secrets.md).

---

## 4. References

Load on demand; do not read them all. If you know what the code must do but
not which of the framework's names to reach for, start with **idiomatic.md** —
it is indexed by intent rather than by feature.

| File | Read when |
| --- | --- |
| [idiomatic.md](references/idiomatic.md) | Choosing *which* declaration to reach for; composing two or more; branching on exit codes |
| [environment.md](references/environment.md) | `func` is not found, or the environment is unusual |
| [capabilities.md](references/capabilities.md) | Choosing or using a capability |
| [config-and-secrets.md](references/config-and-secrets.md) | Wiring config, credentials, or the XDG directory |
| [discovery.md](references/discovery.md) | A job is missing, or naming and filters are in play |
| [workflows.md](references/workflows.md) | Composing multi-step jobs |
| [testing.md](references/testing.md) | Writing tests for jobs |

---

## 5. Verify before reporting done

1. `<prefix> func builtin info` — the job appears.
2. `<prefix> func <job> --help` — flags match what you intended.
3. Run it.
4. If it did not appear, `<prefix> func builtin why <job>` — do not guess.
