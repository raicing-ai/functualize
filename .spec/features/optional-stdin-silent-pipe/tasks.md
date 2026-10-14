# Tasks — optional-stdin-silent-pipe

Each task is checked only when its own acceptance gate is green against the code
as it stands. See `spec.md` for the numbered behavior (R1–R7) and `contracts.md`
for the interface matrix.

## T1 — Readiness seam + Rule 3 rewrite (`src/functualize/_engine/stdin_reader.py`)

Add `_stdin_data_ready(timeout=0.0)` (test-double `data_ready()` first, then a
zero-width `select` poll; `True` when polling is impossible), redefine
`is_stdin_available()` as `not isatty() and _stdin_data_ready()` with exception
behavior preserved, and restructure Rule 3: streaming hand-over first (unchanged),
then eager `read_stdin()` only when data is ready, skipping a falsy read so an
empty stream resolves nothing. Docstrings state the rules and the streaming
opt-in.

- [x] Acceptance: T3/T4 pins green; `uv run mypy src/` clean.

## T2 — Shared-rule docstrings (`stdin_collector.py`, `_types/cli_markers.py`)

`StdinCollector.is_available()` states the shared rule with the reader (a run
blocks on a human or on data only when the human or the data is actually there);
behavior unchanged. The public `Stdin` docstring says the parameter is filled
from piped **content** and that a streaming annotation is the explicit opt-in to
waiting.

- [x] Acceptance: no behavior change — collector and protocol tests untouched and green.

## T3 — Test seam (`tests/_support/stdin_fakes.py`)

One fake stdin (answers `isatty`, `read`, `data_ready`) shared by both suites so
resolution tests never leave the runner's real `sys.stdin` in the probe path.

- [x] Acceptance: used by T4/T5; no test patches methods on the real `sys.stdin` object.

## T4 — CLI-level pins (`tests/cli/test_stdin_integration_unit.py`)

Wall-clock silent-pipe test (real `os.pipe()`, write end held open, daemon
thread + `join(timeout)`, resolves `{}` promptly and never reads); empty-stream
pin (`read()` → `""` resolves `{}`, while an explicit `""` still wins — the two
shapes distinguishable); real multi-line + non-default `encoding` data arriving
intact through a real pipe; existing R1/R2/R4 pins updated to the seam and
unchanged in assertion.

- [x] Acceptance: all green; the wall-clock test fails (join timeout) on a blocking-read regression.

## T5 — Engine-level parity (`tests/engine/test_run_request_stdin.py`)

Mirrors through `engine.run` on `func.job`: a silent pipe leaves `"the default"`;
an empty stream leaves `"the default"`; a required `Stdin` parameter with an
empty stream fails as an ordinary missing argument; existing pins (explicit
value beats pipe, TTY keeps the default, non-console surfaces, name collision)
updated to the seam and unchanged in assertion.

- [x] Acceptance: all green; outcomes agree with T4 — both suites say the default survives when nothing arrives.

## T6 — Validation and records

`uv sync --all-extras`, `uv run ruff check`, `uv run ruff format --check`,
`uv run mypy src/`, `uv run lint-imports`, step tier via
`.agents/skills/test-tiers/scripts/tests-for-diff` (mapper alone first; no call
past 600 s), `uv run python .github/scripts/dead_code_delta.py 4e816a0f <head>`,
`CHANGELOG.md` `[Unreleased]` `### Fixed` entry.

- [x] Acceptance: every command green; dead-code delta output pasted into the delivery record.

## T7 — Probe silent pipes above FD_SETSIZE

Use `select.poll` for the zero-timeout readiness check so a silent pipe with
read fd >= 1024 resolves nothing. Treat EOF as ready, preserving the empty
stream decision in ADR-033. If `poll` is unavailable, raise instead of
claiming that the stream is ready. Update ADR-033 and `.spec/STATUS.md` to
state the new invariant, and add a bounded engine-level regression using a
real high-fd pipe.

- [x] Acceptance: the high-fd test fails on the original committed probe and
  passes after the fix; existing silent-pipe, EOF, and content tests pass;
  `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, and the selected
  pytest tier pass; dead-code delta reports `NEW_DEAD: 0`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 1, "tasks": ["T1 — readiness seam + Rule 3 rewrite", "T2 — shared-rule docstrings", "T3 — test seam"] },
    { "id": 2, "tasks": ["T4 — CLI-level pins", "T5 — engine-level parity"] },
    { "id": 3, "tasks": ["T6 — validation and records"] },
    { "id": 4, "tasks": ["T7 — probe silent pipes above FD_SETSIZE"] }
  ]
}
```
