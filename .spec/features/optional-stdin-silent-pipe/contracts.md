# Contracts — optional-stdin-silent-pipe

No public signature changes. The whole change refines what existing entry points
resolve to; `Stdin`'s fields, the CLI, and the config surface are untouched.

## `functualize._engine.stdin_reader`

Internal module (underscore layer); the signatures below are stable because
`tests/engine/test_run_request_stdin.py` and `tests/cli/test_stdin_integration_unit.py`
drive them directly.

### `resolve_stdin_params(markers, values, streaming) -> dict[str, Any]`

Signature unchanged. Return matrix after this change (single marked parameter,
`values[name] is None`):

| stdin state | eager parameter | streaming parameter |
|---|---|---|
| terminal | `{}` (Rule 4, unchanged) | `{}` (Rule 4, unchanged) |
| non-TTY, no byte has arrived, writers still open | `{}` **(new — returns promptly)** | `{name: iter_stdin_ndjson(...)}` (unchanged; iteration waits) |
| non-TTY, stream closed empty (`< /dev/null`, `printf '' \|`) | `{}` **(new — default survives)** | `{name: iter_stdin_ndjson(...)}` (unchanged; yields nothing) |
| non-TTY, content present (writer closed after writing) | `{name: content}` — read to EOF, `encoding` applied (unchanged) | `{name: iter_stdin_ndjson(...)}` (unchanged) |
| unprobeable stream (no `fileno`, `select` refuses pipes) | historical behavior: read to EOF | unchanged |

An explicit non-None value (including `""`) short-circuits to `{name: value}`
for every row (Rule 1). Multiple unresolved `Stdin` parameters still raise
`ValueError` listing their names (Rule 2). `{}` means "drop the parameter and let
the signature default win"; a parameter without a default then fails as an
ordinary missing argument (`executor.py` drop loop, unchanged).

### `is_stdin_available() -> bool`

Signature unchanged; semantics refined and documented: `True` iff stdin is not a
terminal **and** content is already waiting or the stream has reached EOF. `False`
for a terminal, for an open-but-unwritten pipe, and whenever the check cannot be
performed (historical exception behavior preserved).

### `_stdin_data_ready(timeout: float = 0.0) -> bool` (new, module-private)

The single readiness probe. Zero-width `select` poll: `True` when the stream is
readable (data waiting or EOF). A stream that cannot be polled — `AttributeError`
(no `fileno`/not a stream), `OSError`, `TypeError`, `ValueError`, or a platform
whose `select` refuses pipes (Windows) — answers `True`, which keeps the
historical read-to-EOF contract there. A test double may answer through a
`data_ready()` attribute when it has no pollable descriptor.

### Unchanged

`read_stdin(encoding)`, `iter_stdin_ndjson(encoding)`, `streaming_stdin_params`,
`stdin_markers_for` — signatures and behavior untouched.

## `functualize._engine.capabilities.stdin_collector`

`StdinCollector.is_available()` stays `bool(sys.stdin.isatty() and sys.stdout.isatty())`.
Its docstring now states the shared rule with the reader: a run blocks on a human
or on data only when the human or the data is actually there.

## `functualize._types.cli_markers.Stdin`

Public marker (re-exported as `functualize.job.Stdin`): fields
`flag`/`help`/`encoding` unchanged. The docstring is corrected to say the
parameter is filled from piped **content** — an empty stream leaves the default —
and that a streaming annotation is the explicit opt-in to waiting.

## Surfaces

`SURFACE_POLICY` / `owns_stdin` unchanged: `func.job`, `func.group`,
`func.single-file`, `app.cli` own stdin; agent-run, MCP, HTTP, Lambda, TUI, and
engine paths do not and never receive resolved stdin values.
