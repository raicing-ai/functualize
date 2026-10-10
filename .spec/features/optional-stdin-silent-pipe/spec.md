# Optional Stdin parameters take piped data only, never a silent wait

## Problem

`resolve_stdin_params` reads "stdin is a pipe" as "stdin has data":
`is_stdin_available()` answered `not sys.stdin.isatty()`, and Rule 3 then called
`read_stdin()` — a `sys.stdin.read()` that blocks until every writer closes. Two
field failures follow:

1. **A silent pipe hangs the run.** `sleep 30 | timeout 5 func s ; echo exit=$?`
   prints `exit=124`. The parameter is optional and nothing arrived; the command
   was supposed to return promptly.
2. **An empty stream overwrites the default.** `func s < /dev/null` prints
   `{"note":""}` instead of the parameter's default. The job author wrote
   `Annotated[str, Stdin()] = "the default"`; a stream that carried nothing must
   leave that default standing. This one is worse than the hang: it silently
   fabricates a value nobody sent.

Rule 4 (the signature default wins when stdin resolves nothing) is reachable
today only on a terminal. It must be the rule for a pipe that carries nothing in
any form.

## Behavior

- **R1 — explicit beats implicit (unchanged).** A non-None value supplied by the
  caller or the CLI — including the empty string `""` — resolves the parameter;
  stdin is never consulted.
- **R2 — a terminal resolves nothing (unchanged).** `func s` on a plain TTY hands
  the parameter no value; the signature default wins (Rule 4, maintainer decision
  2026-09-10).
- **R3 — a silent pipe resolves nothing, promptly.** `sleep 30 | func s` returns
  with the default without waiting for the writer. Readiness is probed with a
  zero-width poll; an eager parameter takes the pipe only when content has
  already arrived. Tests bound the whole call by wall clock.
- **R4 — an empty stream resolves nothing.** `func s < /dev/null` and
  `printf '' | func s` hand the parameter no value and the default survives.
  "Nothing piped" (R2/R3) and "empty stream piped" (R4) are distinguishable
  internally — no readable data versus readable EOF — and in tests, and both
  resolve to "no value". An intentionally empty value comes only from the
  explicit flag (R1). A required `Stdin` parameter on an empty stream fails as an
  ordinary missing argument: the job refuses an empty body.
- **R5 — real data arrives intact (unchanged).** Once data is present the reader
  still reads to EOF, so multi-line content and the marker's `encoding` survive
  byte-for-byte.
- **R6 — a streaming parameter is the documented opt-in to waiting.**
  Iterator-typed `Stdin` parameters keep the lazy `iter_stdin_ndjson` hand-over
  whenever stdin is a pipe, with no readiness gate: row-wise pipelines must
  deliver first rows as they arrive however late the upstream starts, and
  iteration blocks on a slow row by design. This is the one remaining blocking
  read, and it is opted into by the annotation shape itself.
- **R7 — both halves of interactivity agree.** Prompting already refuses to
  block a non-interactive run (`StdinCollector.is_available()` requires both
  streams to be terminals). Parameters now say the same thing: a non-interactive
  stdin never blocks a run and never fabricates a value. Non-console surfaces
  (agent-run, MCP, HTTP, Lambda, event, engine) never read stdin at all —
  surface policy unchanged — so an omitted parameter keeps its default there.

## Acceptance criteria

1. **No silent blocking, by wall clock.** `sleep 30 | func s` returns promptly
   with the default. Proven by wall-clock-bounded tests over a real pipe whose
   write end is held open (resolve level and `func`/`app` entry level), not by
   inspection. The only accepted blocking read is the streaming form, which is
   the documented opt-in (R6).
2. **The two no-data shapes are pinned.** "Nothing piped" and "empty stream
   piped" are distinguishable in tests and neither overwrites the parameter
   default; the explicit flag still wins for a deliberately empty value (R1/R4).
3. **Real piped data is intact.** Multi-line content and a non-default
   `encoding` arrive unchanged through the same path (R5).
4. **Agent-run and MCP paths agree with the console path.** The prompt half
   (`StdinCollector.is_available`, no prompting on a non-interactive run) and the
   parameter half (default survives when nothing arrives) state one rule; the
   CLI-level and engine-level suites pin matching outcomes rather than
   contradicting each other (R7).
5. **TTY keeps Rule 4.** `func s` on a plain terminal still resolves nothing and
   the default wins (R2).

## Out of scope

- No new flag, config key, environment variable, or API knob. The only documented
  opt-in to a blocking read is the streaming annotation (R6); a user-visible
  control would be a shape decision.
- Streaming timing semantics unchanged (`tests/pipeline/test_stdin_streaming.py`
  must pass unmodified).
- Surface policy (`SURFACE_POLICY` / `owns_stdin`) unchanged.
- Windows: `select` cannot poll pipes there, so the probe falls back to the
  historical read-to-EOF — same behavior as today, no regression. CI runs the
  suite on Linux only.
