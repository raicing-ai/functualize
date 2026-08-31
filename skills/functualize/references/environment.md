# Resolving how to invoke functualize

`func` on PATH is the exception, not the rule. Establish the invocation prefix
once, verify it, then reuse it. Guessing costs a `command not found` and
usually a `pip install` into the wrong interpreter.

## Why this is not a lookup table

Version managers and dependency managers **compose**:

- A **version manager** (mise, pyenv, asdf) decides *which Python* and often
  which `uv`/`poetry` binary.
- A **dependency manager** (uv, poetry, pipenv, plain venv) decides *which
  packages* are importable.

The invocation prefix comes from the **innermost dependency manager**, running
under whatever interpreter the version manager selected. A repo with both
`mise.toml` and `uv.lock` uses `uv run func` — mise's role is invisible at the
call site.

Bare `func` works only when a shell activation has already put the venv's
`bin/` on PATH. That can be true in one terminal and false in the next, so
never conclude from a single successful bare `func` that it is safe to rely on.

## Detection order

Walk up from the working directory. First match wins.

| Evidence | Prefix |
| --- | --- |
| `uv.lock`, or `[tool.uv]` in `pyproject.toml` | `uv run func` |
| `poetry.lock`, or `[tool.poetry]` in `pyproject.toml` | `poetry run func` |
| `Pipfile.lock` | `pipenv run func` |
| `.venv/bin/func` exists | `.venv/bin/func` |
| `venv/bin/func` exists | `venv/bin/func` |
| `environment.yml` / active conda env | `conda run -n <env> func` |
| Nothing above, `func` resolves on PATH | `func` |

Windows equivalents use `.venv\Scripts\func.exe`.

## Cases that mislead

**mise with a path shim.** A `mise.toml` containing

```toml
[env]
_.path = ["./.venv/bin"]
```

puts the venv on PATH *only inside a mise-activated shell*. Non-interactive
tool invocations frequently are not activated. Try bare `func` first, but fall
back to `uv run func` rather than concluding functualize is missing.

**pyenv without a venv.** `.python-version` selects an interpreter but says
nothing about packages. If there is no venv and no lockfile, functualize is
likely installed into that interpreter's site-packages and bare `func` works —
but confirm rather than assume.

**pipx.** `pipx install functualize` puts `func` on PATH in an isolated
environment that **cannot see the project's own packages**. Jobs importing
project modules will fail with `ImportError` even though `func --version`
works. If `func` resolves but imports fail, suspect pipx.

**Docker / devcontainer.** The prefix may need a `docker compose exec <svc>`
wrapper. Ask rather than guessing at the service name.

**Monorepo.** The lockfile may live several directories up while the jobs are
in a subpackage. Resolve the prefix from the lockfile's directory, and mind
that `--discovery-depth` limits how far *down* functualize scans for jobs.

## Verify

One command proves reachability and identity together:

```bash
<prefix> func builtin version
```

Then confirm the project's jobs are actually visible from it:

```bash
<prefix> func builtin info
```

A prefix that reports a version but finds no jobs usually means pipx-style
isolation, or that you are outside the project directory.

## When functualize is genuinely absent

**Do not install it silently.** Installing into the wrong environment appears
to succeed, changes nothing about the failure, and leaves the machine dirtier.

Report what was found, then propose the install that matches the detected
context and let the human confirm:

| Context | Install |
| --- | --- |
| uv project | `uv add functualize` |
| poetry project | `poetry add functualize` |
| pipenv project | `pipenv install functualize` |
| plain venv | `.venv/bin/pip install functualize` |

Never `pip install functualize` bare, never `--user`, never into system Python.

Add the `[cli]` extra when the project needs the CLI/TUI surface rather than
the library alone — check the project's existing dependency spec for which
extras it already uses instead of guessing.
