# Standalone scripts — one file, no project

A functualize job does not need a package, a `pyproject.toml`, or a
`FunctualizeApp`. A single `.py` file with a PEP 723 header is a complete,
distributable program: `uv` builds its environment on first run, functualize
generates its `--help` from the signature.

Reach for this when the work is one command that someone else should be able to
run without setting anything up — a skill's bundled script, a repo utility, a
one-off you want to hand to a colleague. Reach for a scaffolded app instead when
there are several jobs, shared config, or anything you will grow.

---

## The shape

```python
#!/usr/bin/env -S func
# /// script
# requires-python = ">=3.11"
# dependencies = ["functualize[cli]", "httpx"]
#
# [tool.functualize]
# job = "fetch"
# ///
"""Fetch a resource and emit it as structured output."""

from functualize.job import Log, Stdout
from functualize.types import Secret


def fetch(log: Log, out: Stdout, url: str, token: Secret[str] | None = None) -> None:
    """Fetch URL and emit the response as JSON."""
    log(f"fetching {url}")
    out.emit({"url": url, "status": "ok"})
```

```bash
chmod +x fetch.py
./fetch.py --url https://example.com
```

Each piece earns its place:

- **`dependencies = [...]`** — `uv` builds an ephemeral environment on first
  run. Nothing needs installing first, and the script cannot drift against
  whatever happens to be on the machine. Note the `[cli]` extra: `click`,
  `rich` and `textual` are optional, and a bare `functualize` dependency
  produces a program that cannot run.
- **`[tool.functualize] job = "fetch"`** — declares that this file *is* that
  job. Without it, `func fetch.py --url x` reads `--url` as a *function name*
  and fails with `Function '--url' not found`, and a bare `./fetch.py` prints a
  listing instead of running anything.
- **`Stdout.emit`** — `--output json` makes the script parseable by whatever
  called it.
- **`Secret[str]`** — credentials render as `•••` in logs, tracebacks and
  emitted payloads. Worth doing from the first commit for anything a script
  might print.

Unknown keys in `[tool.functualize]` warn rather than fail, so a newer
functualize can add fields without breaking your script — but a typo warns
instead of silently doing nothing.

## The shebang must be `func`

```python
#!/usr/bin/env -S func                # ✓ func reads the file and runs the job
#!/usr/bin/env -S uv run --script     # ✗ runs the module body, which runs nothing
```

Only `func` dispatches. It reads the `# /// script` block, delegates to `uv` if
the declared dependencies are missing, and then invokes the job named by
`[tool.functualize] job`.

`uv run --script` does none of that: it hands the file to `python`, which
executes the module body — a few imports and a `def` — and exits **0 having run
nothing**. No output, no error, no `--help`. That silent success is the worst
failure mode in this file, because it looks exactly like a program with nothing
to say.

So the shebang costs a `func` on PATH. When you cannot assume one — which is
what §0 of the `functualize` skill warns about — do not change the shebang;
change the invocation:

```bash
func fetch.py --url https://example.com            # func on PATH
uvx --from 'functualize[cli]' func fetch.py --url https://example.com   # nothing installed
```

The `uvx` form needs only `uv` on the machine and is the one to hand to someone
else. Both read the same header, so the script itself does not change.

## Global flags come *before* the file

This is the one that bites. `--output`, `--log-level` and the discovery flags
are global — they belong to `func`, not to your job — so they must precede the
script path:

```bash
func --output json fetch.py --url https://example.com    # ✓
func fetch.py --url https://example.com --output json    # ✗ No such option '--output'
```

Everything after the script path belongs to the job, which is the whole point of
declaring `job =` in the header.

## Where state goes

A loose script with no `.functualize/` directory anywhere above it runs in
**standalone mode**: fingerprints, history and scopes land in an XDG cache
directory keyed by a hash of the path. That is usually right for a script.

If the script lives in a repository and you want its freshness ledger somewhere
visible, `mkdir .functualize` at the repo root. `func builtin state show` prints
which mode is active.

## Testing a single-file script

The file is importable, so the job is callable directly with fakes — no
subprocess, no CLI:

```python
from functualize.testing import CapturingLog, FakeStdout

def test_fetch_emits_status():
    log, out = CapturingLog(), FakeStdout()
    fetch(log=log, out=out, url="https://example.com")
    assert out.emitted[-1]["status"] == "ok"
```

Put the test beside the script. `pytest` is not in the script's header — the
program should not ship a test runner — so supply it at the point of running,
in an environment that also has functualize:

```bash
uvx --with 'functualize[cli]' pytest test_fetch.py
```

pytest puts the script's directory on `sys.path`, so `from fetch import fetch`
resolves to the file itself.

## When to stop and scaffold

Move to `func builtin scaffold init` when any of these becomes true:

- more than one job, and they share configuration;
- you want layered config files rather than flags;
- the thing has a name and users, and should be `myapp <job>` rather than
  `./script.py`;
- you are writing tests that need fixtures beyond a couple of fakes.

Migration is not disruptive: the job function itself is unchanged. What changes
is where it lives and how the environment is declared.
