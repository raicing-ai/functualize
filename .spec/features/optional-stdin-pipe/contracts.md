# contracts.md — external interfaces

No new user-visible surface: no flag, no timeout, no knob, no schema change.

## Observable behaviour

- An optional `Stdin` parameter receives its own default when nothing was piped
  (a TTY, or a pipe that is never written) and `""` when an empty stream was
  piped; piped data arrives as itself. Before: a never-written pipe hung the
  process.
- A required `Stdin` parameter with no default fails as the ordinary
  required-argument error when nothing was piped. It never hangs.

## Module signatures (`functualize._engine.stdin_reader`)

| symbol | contract |
|---|---|
| `resolve_stdin_params(stdin_markers, cli_values, streaming=None) -> dict[str, Any]` | signature unchanged; rules below |
| `StdinState` (enum) | `TTY` \| `NO_INPUT` \| `READY`, **new**. `READY` = "a read returns promptly: input or end-of-stream is already there" |
| `stdin_state(stream=None) -> StdinState` | **new**, internal: the non-consuming classification both doors read |
| `is_stdin_available(stream=None) -> bool` | `stdin_state(...) is READY`: `True` for an empty-but-present stream (end-of-stream is there), `False` for a TTY and for a pipe that is never written |
| `read_stdin(encoding="utf-8") -> str` | unchanged: consumes stdin whole; `""` means an empty stream |
| `iter_stdin_ndjson`, `stdin_markers_for`, `streaming_stdin_params` | unchanged |

A stream whose readiness cannot be probed (no fileno — `io.StringIO`, exotic
test doubles — or a platform without `select.poll`, i.e. Windows) keeps today's
rule exactly: treated as carrying a read, and the read decides.

## `resolve_stdin_params` resolution rules

1. An explicit CLI value wins (unchanged).
2. More than one unresolved `Stdin` parameter raises `ValueError` (unchanged).
3. An iterator/iterable-typed parameter (`streaming`) receives the lazy NDJSON
   stream on any non-TTY stdin; waiting for its producer is that type's
   contract. On a TTY it is not deposited (rule 5).
4. `stdin_state() is READY` → `read_stdin()` is deposited: the data, or `""`
   when the stream was empty but present.
5. Otherwise (TTY, or a pipe that is never written) → `{}`: the parameter is
   not deposited and the signature default wins. A parameter with no default
   fails as the ordinary required argument.

## `StdinCollector.is_available` (prompt door)

Verdict unchanged: `stdin_state() is StdinState.TTY and sys.stdout.isatty()`.
Non-TTY stdin keeps returning `False` — the `default` / `InputNotAvailable`
behaviour — never blocking. Both doors now read one classifier instead of two
copies of the TTY idiom.
