# ADR-033: A stdin stream that carries nothing resolves the default; `""` is only ever explicit

**Status**: accepted
**Date**: 2026-10-13
**Deciders**: maintainer (rule shape), implementer (mechanism)

## Context

A job with an optional `Stdin` parameter — `data: Annotated[str, Stdin()] =
"nothing was piped"` — hung forever on `sleep 30 | func s`. Stdin resolution
asked one question, `sys.stdin.isatty()`, and a pipe that is never written
answers "piped": the read that followed waited on an upstream that had no
intention of writing. The same verdict also carried only one bit: a
never-written pipe looked exactly like one carrying data, and the only witness
was the read itself, which never returned for the former. The other shape of
"nothing there" fell through the same hole the opposite way: an empty stream
(`func s < /dev/null`, a pipe closed without writing) did return, and the `""`
it carried landed on the parameter over its default — "nothing was piped"
arriving as an empty document, an accident of the read rather than a named
rule. Two facts were undocumented; one of them was a hang.

Two doors re-derived stdin's state independently: the `Stdin`-parameter
resolution (`_engine/stdin_reader.py`) and the prompt door
(`_engine/capabilities/stdin_collector.py`). Nothing forced them to agree.

## Decision

A stream that carries nothing is not a value. Every shape of "nothing there" —
a terminal, a pipe that is never written, and an empty stream — resolves
nothing, and the parameter's own default stands. An empty string reaches a
parameter only through an explicit flag (`--data ""`), which Rule 1 already
ranks above the implicit read: `""` is a value a user gives, never one a
stream's emptiness assumes.

The mechanism is one readiness gate, `is_stdin_available()` — stdin is a pipe
*and* already carries content or has reached end-of-stream — over a zero-width
`select` probe (`_stdin_data_ready`; a test double answers through
`data_ready()`). The parameter door projects the rule as:

- A pipe that already carries content (or has reached end-of-stream) is read:
  content deposits the content, and a stream read and found empty resolves
  nothing — the default stands, exactly as for the pipe never read. The two
  "nothing there" shapes stay distinguishable in the reader's own accounting
  (never read vs read and found empty) while the rule gives both one answer.
- A terminal or a pipe that carries nothing yet is never read: the parameter's
  own default stands, and a required parameter with no default fails the
  ordinary missing-argument way. This keeps the maintainer's 2026-09-10 rule-4
  decision for the terminal case and gives the pipe that carries nothing the
  same answer.
- An iterator-typed parameter is the documented opt-in to waiting: it gets the
  lazy NDJSON stream on any non-TTY (waiting for that producer is the type's
  contract) and nothing on a terminal.

The prompt door keeps its own check (`StdinCollector.is_available()`: both
streams TTY) and states the same rule from the other side: a run blocks on a
human or on data only when the human or the data is actually there.

Unprobeable streams (no usable `fileno()`, a platform whose `select` refuses
pipes) answer `True` to readiness and keep the eager rule this probe refines:
the read itself decides.

## Consequences

### Positive

- `sleep 30 | func s` and `func s < /dev/null` both return promptly with the
  default (wall-clock bounded at one second in
  `tests/cli/test_stdin_integration_unit.py` and
  `tests/engine/test_run_request_stdin.py`).
- "Nothing was piped" has exactly one documented answer in every shape it
  arrives in, and `""` is reachable only by someone who typed it.
- Both doors state one rule: no prompt and no read when nothing is there.

### Negative

- The probe is `select.select` with a zero timeout, and `select` carries a hard
  FD_SETSIZE ceiling (and is sockets-only on Windows): a stream it cannot
  probe answers `True`, and the silent-pipe hang can return in that corner
  behind the historical read-to-EOF contract. `select.poll` on POSIX and
  `PeekNamedPipe` on Windows are the named follow-ups.

### Neutral

- No user-visible knob: the probe is strictly non-blocking, with no grace
  constant and no timeout flag to configure.
- The rule is scoped to the console door. A surface that runs with
  `owns_stdin=False` (servers, MCP — see the `_request_kwargs` docstring,
  `executor.py`) bypasses stdin resolution entirely and keeps defaults.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Blocking read with a grace timeout | simple | arbitrary constant; needs a user-visible knob; still wrong on EOF-vs-later-write | the rule must be right by construction, not by tuning |
| `fstat` + `S_ISCHR`/`S_ISFIFO` classification | no probe | cannot tell "never written" from "empty but present" — both are FIFOs at EOF or not | readiness is a fact about the fd, not its type |
| Deposit `""` for every non-TTY | one rule | silently overruns the default for `sleep 30 \| func s` and for a required parameter; invents a value nobody typed | `""` must be given, never assumed |
| An empty stream is a document and `""` lands | honors the stream literally | "nothing was piped" arrives as a value and overruns the default; two rules for two shapes of nothing | a stream that carries nothing resolves nothing — one answer for every shape (the rule shape the maintainer chose 2026-10-13) |
