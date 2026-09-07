# Spec: A job that is missing says why, where the user is looking

Upstream ask 5, re-scoped against what PR #29 already shipped.

## Problem

A job module that cannot be imported — a missing dependency, a syntax error, a
typo at module level — is skipped. Its jobs never exist.

```python
# needs_dep.py
import totally_missing_pkg          # not installed

def fetch() -> None:
    """Fetch a thing."""
```

```
$ func fetch
WARNING:functualize._discovery.cached_provider:Failed to import and extract from
'/tmp/.../needs_dep.py': No module named 'totally_missing_pkg'
Error: Unknown command 'fetch'.
Run 'func' to see all available commands.
```

The user's model says *my job is broken*; the CLI says *it never existed*. The
one line that explains it is a raw Python logger dump — logger name, module
path and all — printed above the error, on every command.

**PR #29 shipped most of the machinery.** `discovery_failures` is a real,
structured report, and it survives a warm boot (a module that fails to import
is retried every boot rather than cached as absent — verified). Three gaps are
left, and this feature closes them. Two more report kinds have since joined the
same list — job-name collisions and unsatisfiable parameters — so each gap now
hides three classes of finding rather than one.

### Gap 1 — the default rendering does not show it

There are three renderings. Two report failures; the one everybody gets by
default does not.

```
$ func builtin info                        # rich — the default
   Discovered Jobs
  ┃ Command ┃ Group ┃ Module Path ┃
  │ hello   │ ...   │ greet       │        <- that is all. No mention of needs_dep.py.

$ FUNCTUALIZE_CLI_OUTPUT=plain func builtin info
  discovery failures (1):
    .../needs_dep.py
      ModuleNotFoundError: No module named 'totally_missing_pkg'
  jobs (1):
    hello  Say hi.
```

The plain renderer even carries the comment explaining *why* failures print
above the job list — "an explanation printed below the thing it explains gets
scrolled past". That reasoning reached two renderers and not the default one.

### Gap 2 — the health check reports a confident wrong number

`builtin self doctor` exists to answer "what is wrong here", and says:

```
  ok  boot                    the CLI starts
      job-discovery           1 discovered from /tmp/.../badimport
```

One discovered. Two files. No hint that one of them failed.

### Gap 3 — the error message does not connect the two

`func fetch` does not know that `fetch` is defined in the file that failed.

## Behavior

### The default rendering reports failures, above the job list

Same content and same position as the plain renderer, rendered as a panel.
Absent when there are none — no empty section.

### `self doctor` counts what it could not read

The `job-discovery` check reports the failures alongside the count, with the
same `!!` marker every other unhealthy check uses, and the report's overall
status reflects it.

### An unknown command explains itself when it can

When a typed name is not a command **and** a discovery failure exists, the
error says so. Where the name can be attributed to a specific failed file, it
names that file and the reason:

```
$ func fetch
Error: Unknown command 'fetch'.
  'fetch' is defined in needs_dep.py, which failed to import:
    No module named 'totally_missing_pkg'
```

Attribution reads the failed file's **source**, without importing it — the
same technique discovery already uses to decide what to import — and only on
the error path, where a command is already failing. When the name cannot be
attributed, the hint is generic:

```
$ func typoo
Error: Unknown command 'typoo'.
  (1 module failed to import — run 'func builtin info' for details)
```

### One clean warning line, not a logger dump

A module that fails to load still warns on stderr, so a user running an
unrelated job learns something is broken. It is one formatted line, with no
logger name and no internal module path:

```
⚠ needs_dep.py not loaded — No module named 'totally_missing_pkg'
```

## Acceptance criteria

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | The default `builtin info` shows discovery failures | shows nothing |
| A2 | They appear **above** the job list | n/a |
| A3 | A clean project shows no failures section | n/a |
| A4 | All three kinds render — import failure, name collision, unsatisfiable parameter | only two renderers show any |
| A5 | `self doctor` reports the failed file with a `!!` marker | says "1 discovered" and stops |
| A6 | `self doctor`'s overall status is not `ok` when a module failed | reports ok |
| A7 | `func fetch` names the file and the reason | "Unknown command", no hint |
| A8 | Attribution does not import the failed module | n/a |
| A9 | An unattributable name gets the generic hint | no hint |
| A10 | With no failures, unknown-command output is unchanged | — |
| A11 | The stderr warning is one formatted line, no logger name or internal path | raw `WARNING:functualize._discovery...` |
| A12 | Everything above holds on a warm boot | the report already does |
| A13 | Full gates green | — |

## Out of scope

- **Making a failed import fatal.** It stays non-fatal; that is the design.
- **Retrying the import.** Already happens every boot, which is why the report
  survives a warm boot.
- **Attribution for a name defined in a file that parses but fails at import
  time deeper than its own body** — the AST read sees top-level definitions,
  which is the case that matters.
