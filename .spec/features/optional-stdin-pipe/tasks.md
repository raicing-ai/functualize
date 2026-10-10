# Tasks: optional-stdin-pipe

## Wave 0

- [ ] **1.1 — the reader classifies stdin without waiting** (AC1, AC2, AC3, AC5)
  - Files: `src/functualize/_engine/stdin_reader.py`,
    `tests/engine/test_stdin_states.py`,
    `tests/cli/test_stdin_integration_unit.py`,
    `tests/cli/test_stdin_resolution_properties.py`,
    `tests/engine/test_run_request_stdin.py`
  - `StdinState` + `stdin_state()` classify stdin as `TTY` / `NO_INPUT` /
    `READY` with a non-blocking `select.poll` probe; unprobeable streams keep
    today's eager rule. `is_stdin_available()` derives from the state;
    resolution follows contracts.md (streaming hoist included), so a
    never-written pipe resolves the signature default promptly and an
    empty-but-present stream deposits `""`.
  - New tests drive real `os.pipe()`s and `/dev/null`: the never-written case
    carries a wall-clock bound; the empty case pins `""` over the default;
    data cases keep multi-line and multibyte intact; a required no-default
    parameter fails ordinarily. The three existing test files move their patch
    seam to `is_stdin_available` / `read_stdin` with assertions unchanged.
  - Gate: `uv run pytest tests/engine/test_stdin_states.py tests/cli/test_stdin_integration_unit.py tests/cli/test_stdin_resolution_properties.py tests/engine/test_run_request_stdin.py -q --run-slow`
    passes; the multi-line case already in the files still passes.
  - Reachability: `func <job>` → `app/adapters/cli.py` →
    `JobExecutionEngine.run` → `executor.py::_request_kwargs:1158` →
    `resolve_stdin_params`; proven by reverting that call and watching the
    engine stdin tests fail.

## Wave 1

- [ ] **2.1 — the prompt door reads the same classifier** (AC4)
  - Files: `src/functualize/_engine/capabilities/stdin_collector.py`,
    `tests/engine/test_stdin_states.py`
  - `StdinCollector.is_available` derives its stdin half from `stdin_state()`
    (peer-layer import) and keeps the stdout half and its verdicts. One parity
    test pins both doors' projections per state (TTY / never-written / empty /
    data) so the two agree rather than contradict.
  - Gate: `uv run pytest tests/engine/test_stdin_states.py -q` passes,
    including the parity table.
  - Reachability: `RunContext.prompt_*` → `get_stdin_collector`
    (`tests/context/test_runcontext_prompt.py:179` pins that hop) →
    `StdinCollector.is_available`; proven by breaking `is_available` and
    watching the parity test fail.

## Wave 2

- [ ] **3.1 — the decision outlives the feature tree** (AC2, AC4)
  - Files: `contributor/adr/032-optional-stdin-empty-stream.md`,
    `contributor/architecture/interactivity-model.md`, `CHANGELOG.md`
  - The empty-document-wins rule, the two-door projection split and the
    platform boundary are recorded durably (ADR), the interactivity model names
    the split side by side, and the changelog narrates the behaviour change.
    This task lands no code and runs no test.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"], "depends_on": [0]},
    {"id": 2, "tasks": ["3.1"], "depends_on": [1]}
  ]
}
```
