# deps-inherit-group-options

## The defect

A group-option flag typed mid-path on the command line (`func demo --target b
report`) reaches only the job the user named. Each `Deps` dependency that job
declares is run through a rebuilt request whose `group_option_values` was reset
to `None` (`_types/run_request.py`, `nested_request`), so the dependency
resolves its `GroupOptions` from default < config file < environment and the
one run silently mixes two values: the invoked job reads `target="b"`, its
dependency reads `target="a"` (or the default) — with no diagnostic, because
`--log-level DEBUG`'s `Group options consumed mid-path: {...}` line is printed
once, at the top, and describes only what the invoked job received.

Verified against `master` at `4e816a0f`:

- `_cli/main.py:1004` — the walk's options are collected into
  `group_option_values` and handed to the top-level run only.
- `_engine/dependency_runner.py:146` — every dependency request is built by
  `nested_request(context.request, surface="engine.dependency", ...)`.
- `_types/run_request.py:366` — `nested_request` resets
  `"group_option_values": None`.
- `_engine/executor.py:875-879, 1380` — `engine.run()` forwards
  `request.group_option_values` into `_resolve_group_options`, which is where
  the value would have landed had it survived the hop.

## The behavior after

A group-option flag given on the command line for a command group resolves to
the same `GroupOptions` value in **every `Deps` dependency the run reaches**,
whatever the nesting depth, and that value is the one the invoked job sees.

The distinction this feature draws — why a dependency inherits when a workflow
step and an `rc.invoke` child do not (`docs/guides/group-options.md`, "Steering
a whole run from code") — is that a `Deps` upstream is not a job reached by
code that might mean another path. It is part of *fulfilling* the request that
carried the flag: the engine schedules it before the dependent's pre-flight,
in the same program invocation, under the same command line. A step or an
`rc.invoke` child starts from a job author's decision; a dependency starts
from the request itself.

Precedence is unchanged everywhere: default < config file < vault <
environment < group-CLI, per group. A dependency reached by a run that gave no
CLI flag keeps today's resolution (its own vault, file, environment and
default layers), and `nested_request`'s default reset stays — the dependency
seam *states* the field, the same way `rc.invoke(..., group_option_values=...)`
does, keeping the guide's rule that anything passed is passed on purpose.

Out of scope, per the dispatch: `--force` re-running a dependency, any change
to how environment variables reach a dependency, and the freshness-key half of
the same report family.

## Acceptance criteria

Every criterion below is a gate; each was run at authoring time against the
code as it stands after the change.

- **AC-1 — the exact repro, through the engine.** A group `demo` declaring
  `DemoOptions(GroupOptions, group="demo")` with a `target` field, a `report`
  job with `deps=Deps("build")`, and a `build` dependency that injects
  `DemoOptions`: run `report` with `group_option_values={"target": "b"}` and
  both the invoked job and the dependency resolve `target="b"`.
  Gate: `uv run pytest tests/group_options/test_group_options_deps.py -q`
  (exit 0, the file's dependency-inheritance tests green).
- **AC-2 — nesting depth.** A dependency-of-dependency in the same declared
  graph resolves the same CLI value; the scheduler builds every node's request
  from the invoked job's request, so the map reaches the whole graph.
  Gate: same command as AC-1 (the transitive-chain test).
- **AC-3 — precedence unchanged at the hop.** With `DEMO__TARGET=a` exported
  and `--target b` typed, the dependency resolves `b`; with no CLI layer, the
  dependency resolves `a` — today's behavior.
  Gate: same command as AC-1 (the ladder test at the dependency).
- **AC-4 — the repro through the CLI door.** `func demo --target b report`
  through the real group-dispatch path (in-process `_handle_group`: boot,
  discovery, mid-path walk, engine) runs the dependency under `target="b"`.
  Gate: same command as AC-1 (the `_handle_group` test in the same file).
- **AC-5 — the other boundaries hold, unmodified.** The workflow-step and
  `rc.invoke` boundaries keep their documented behavior and the tests that pin
  them keep passing without edits.
  Gate: `uv run pytest tests/group_options/test_combination_matrix.py tests/execution/test_invoke_group_options.py tests/engine/test_nested_delivery_inputs.py -q`
  (exit 0, no test in those files modified by this feature).
