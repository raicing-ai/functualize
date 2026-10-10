# ADR-032: An empty stdin stream is a document; a pipe that carries nothing is not

**Status**: accepted
**Date**: 2026-10-10
**Deciders**: maintainer (rule shape), implementer (mechanism)

## Context

A job with an optional `Stdin` parameter — `data: Annotated[str, Stdin()] =
"nothing was piped"` — hung forever on `sleep 30 | func s`. Stdin resolution
asked one question, `sys.stdin.isatty()`, and a pipe that is never written
answers "piped": the read that followed waited on an upstream that had no
intention of writing. The same verdict also carried only one bit. A never-written pipe looked
exactly like one carrying data — both `isatty() == False` — and the only
witness was the read itself, which never returned for the former. An
empty-but-present stream (`< /dev/null`, a pipe closed without writing) did
deposit `""`, but as an accident of that read rather than a named rule, so
"nothing was piped" and "an empty stream was piped" were never two
documented facts — one of them was a hang.

Two doors re-derived stdin's state independently: the `Stdin`-parameter
resolution (`_engine/stdin_reader.py`) and the prompt door
(`_engine/capabilities/stdin_collector.py`, the issue-named
`stdin_collector.py:55`). Nothing forced them to agree.

## Decision

One non-blocking classifier, `StdinState` — `TTY` / `NO_INPUT` / `READY` —
backed by a `select.poll` probe with a zero timeout (the "poll(), not
select()" lesson of `_engine/capabilities/shell.py`: `select()` carries a hard
FD_SETSIZE ceiling that wide test sessions reach). The probe never waits: a
pipe that is never written is `NO_INPUT` in constant time.

The parameter door projects the state as:

- `TTY` or `NO_INPUT` → deposit nothing (rule 5). "Nothing was piped" — the
  job's own default stands, and a required parameter with no default fails the
  ordinary missing-argument way. This keeps the maintainer's 2026-09-10 rule-4
  decision for the terminal case and extends the same answer to the pipe that
  carries nothing.
- `READY` → deposit what the stream carries: the content, or `""` when the
  stream is empty but present. **`""` is what the user actually piped** — an
  empty document is still a document — so it lands like any other piped
  content instead of the parameter's default silently standing in for it.
- An iterator-typed parameter is the documented opt-in to waiting: it gets the
  lazy NDJSON stream on any non-TTY (waiting for that producer is the type's
  contract) and nothing on a terminal.

The prompt door derives its verdict from the same classifier — prompts happen
at a TTY; anything else keeps the `default` / `InputNotAvailable` behaviour —
so the two doors agree by construction rather than by coincidence.

Unprobeable streams (no `fileno()`, no `select.poll` — Windows, test doubles)
keep the eager rule this probe refines: the read itself decides.

## Consequences

### Positive

- `sleep 30 | func s` returns promptly (wall-clock bounded in
  `tests/engine/test_stdin_states.py`).
- "Nothing piped" and "empty stream piped" are distinguishable facts, and each
  has exactly one documented answer.
- One classifier, two doors: prompt availability and parameter resolution can
  no longer contradict each other.

### Negative

- Windows ships without `select.poll`, and its `select()` is sockets-only:
  a never-written pipe can still hang there. The fallback preserves today's
  behaviour exactly; `PeekNamedPipe` is the named follow-up if Windows needs
  the probe.

### Neutral

- No user-visible knob: the probe is strictly non-blocking, with no grace
  constant and no timeout flag to configure.
- The `""` pin is scoped to the console door. A surface that runs with
  `owns_stdin=False` (servers, MCP — see the `_request_kwargs` docstring,
  `executor.py`) bypasses stdin resolution entirely and keeps defaults.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Blocking read with a grace timeout | simple | arbitrary constant; needs a user-visible knob; still wrong on EOF-vs-later-write | the rule must be right by construction, not by tuning |
| `fstat` + `S_ISCHR`/`S_ISFIFO` classification | no probe | cannot tell "never written" from "empty but present" — both are FIFOs at EOF or not | the states are facts about the fd's readiness, not its type |
| Deposit `""` for every non-TTY | one rule | silently overwrites the default for `sleep 30 \| func s` and for a required parameter | "nothing was piped" must keep the default (rule 5) |
| Classifier consumes into a module stash | one read | stateful across calls; leaks between tests and between resolutions | the classifier never consumes; `read_stdin` reads once, unchanged |
