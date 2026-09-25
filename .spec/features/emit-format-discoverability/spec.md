# emit-format-discoverability

## Problem

Measured on the published 0.4.0 wheel, in a project holding one job
`greet() -> str`:

| Invocation | Today |
|---|---|
| `func --help` | lists fourteen globals; **no `--emit-format`, `--force`, `--prompt-gates`** |
| `func --emit-format bogus greet` | `Error: Unknown command 'bogus'.`, exit 1 |
| `func --emit-format bogus` | `Error: Unknown command 'bogus'.`, exit 1 |
| `func --emit-format=bogus greet` | `Error: --emit-format must be one of {…}, got 'bogus'.`, exit 1 |
| `func greet` | nothing on stdout, exit 0 — and help never says why |

The emit surface works and is documented in the guides. The defect is that the
keyboard never offers it, so a first-time author writes the silent version and
cannot tell success from a no-op.

Why the three are missing: `func --help` is rendered by the pre-boot `cli_app`
group (`_cli/main.py`), which deliberately does **not** declare the three
run-scoped globals — BUILTIN mode rejects them by design (ADR-020, and the
comment above `register_builtin_commands(cli_app)`). Declaring them as click
options there would change what `func builtin …` accepts.

Why the bad value reads as a command: `--emit-format` takes an *optional*
value. The pre-boot lookahead (`_cli/dispatch.py`) consumes the next token only
if it is in the valid set, so `func --emit-format greet` means "default format,
run greet". `bogus` is therefore left as the first positional and reported as
an unknown command. The lookahead is correct; the diagnosis is not.

## Behaviour

- **B1.** `func --help` shows a `Run options` section listing `--emit-format`
  with its valid set (read from the flag grammar, not restated), `--force` and
  `--prompt-gates`, and says they go before the job name.
- **B2.** `func --help` tells an author how a job's output reaches stdout: a
  return value is never printed; use `out.emit()` (`Stdout`) or `print()`.
- **B3.** When the token an optional-value global refused turns out to name
  nothing (no job, group or plugin command, after full boot), `func` reports
  the flag's invalid value — the same sentence and exit code (1) as the
  `--flag=value` spelling — instead of `Unknown command`.
- **B4.** An app's own entry point (`./main.py --help`) carries the same B2
  sentence on its `--emit-format` row. That surface already declares the flag
  with a `click.Choice`, so B1 and B3 already hold there.

## Acceptance criteria

- **AC1.** `func --help` stdout contains `--emit-format [auto|json|ndjson|none|raw]`,
  `--force`, `--prompt-gates`, and `before the job name`.
- **AC2.** `func --help` stdout and an app's `--help` stdout both contain
  `out.emit()` and `print()`.
- **AC3.** `func --emit-format bogus greet` and `func --emit-format bogus`
  exit 1 with stderr containing `--emit-format must be one of` and `'bogus'`,
  and **not** `Unknown command`. Same for `--perf-report bogus greet`.
- **AC4.** `func --emit-format greet` still runs `greet` (lookahead unchanged);
  `func nosuchjob` still reports `Unknown command 'nosuchjob'`.
- **AC5.** `func --help` still lists exactly one command (`builtin`), and
  `func --emit-format json builtin version` is still rejected (BUILTIN
  boundary unchanged).

## Out of scope

- `func greet --emit-format json` → `No such option`. Globals-before-command is
  correct parsing; B1's "before the job name" is the discoverability fix. A
  targeted hint would live in the shared job-command parser used by both
  surfaces and is a separate change. Prior art for the hint exists on the
  group-walk path (`_dispatch_group`, `is_known_global_flag`: "global option
  '…' must come before the group name").
- Printing a job's return value. Deliberate design (`_types/stdout.py`).
