# Tasks — run-request-entry

Every gate below is an executable command that was **run at authoring time** against
`e57f0c9`; the `now:` line is what it returned then. A task is done when the gate returns its
`after:` value. Run gates from the worktree root.

Two gates were narrowed during authoring, because the first spelling over-matched — recorded
here rather than silently fixed, per the acceptance-gate rule:

- *"a function passed for execution"* first matched `rg -n 'function=[a-z_]+'` over
  `app/`, `_app/`, `_cli/` → **12 hits**, of which **9 are job registration**, not execution.
  Narrowed to the engine-call spelling → **6 hits in 5 files**.
- The history gate `invoke_depth == 0` matches **4** lines, two of which are perf marks
  (`:1042`, `:1059`) and one a docstring (`:683`). The real gate is `:705`.

---

## Wave 0 — the value object

### [x] T1 · `RunRequest` exists, and nothing depends on it yet

**Files:** `src/functualize/_types/run_request.py`, `src/functualize/_types/__init__.py`,
`src/functualize/app/utils.py`, `tests/types/test_run_request.py`

Frozen dataclass with `slots=True`, stdlib-only imports, `surface` required and typed as the
closed `Literal` in `contracts.md` §1. Re-export from `functualize.types` and from
`functualize.app.utils` (the only route `_cli` may import by).

Spec AC-1.

**Gate**
```bash
test -f src/functualize/_types/run_request.py && rg -c 'class RunRequest' src/functualize/_types/run_request.py
```
now: `file absent` · after: `1`

**Gate — stdlib only**
```bash
rg -n '^from functualize|^import functualize' src/functualize/_types/run_request.py | wc -l
```
now: `n/a` · after: `0`

**Test:** constructing without `surface` is a `TypeError`; with an unknown surface, a
`ValueError`; the instance is immutable and hashable.

---

## Wave 1 — the engine gains an entry

### [x] T2 · `engine.run(request)` beside `execute()`, labelled transitional

**Files:** `src/functualize/_engine/executor.py`, `tests/engine/test_engine_run_entry.py`

`run()` unpacks the request and calls the existing `execute()`. It resolves nothing yet — T11
does that. Carry `# TRANSITIONAL(run-request/T11): run() delegates to execute(); resolution
moves in at T11` per `CONSTITUTION.md` → *Transitional Changes*.

Spec AC-2.

**Gate**
```bash
rg -c 'def run\(self, request' src/functualize/_engine/executor.py
```
now: `0` · after: `1`

**Gate — the label exists**
```bash
rg -c 'TRANSITIONAL\(run-request' src/functualize/_engine/executor.py
```
now: `0` · after: `1`

**Test:** `engine.run(request)` and the equivalent `engine.execute(...)` produce equal
`JobResult`s for the same job — the property that makes wave 3 safe.

---

## Wave 2 — the facade takes a request

### [x] T3 · `FunctualizeApp.execute(request)`

**Files:** `src/functualize/app/core.py`, `tests/app/test_facade_request.py`

Signature becomes `execute(self, request: RunRequest) -> JobResult`. Scope creation
(`core.py:606-628`) is unchanged and now unavoidable. Add `request_for(...)` for the
programmatic case (`contracts.md` §3).

**Gate** *(narrowed during execution: `ruff format` wraps the signature across lines, so
the single-line spelling can never match — the gate now reads the signature multi-line)*
```bash
rg -U -c 'def execute\(\n\s+self,\n\s+request' src/functualize/app/core.py
```
now: `0` · after: `1`

> **The legacy form survives to T15.** T3 lands a facade that accepts *either* a
> `RunRequest` or the old `(job_name, *, scope_id, group_option_values, **kwargs)`,
> labelled `TRANSITIONAL(run-request/T15)`. Wave 3 migrates the seven doors one at a time,
> which is only green if the un-migrated ones still work. T15's own gate confirms this was
> the intent: it records `now: 1` for the legacy signature at wave 5 entry.

**Sabotage:** remove the scope creation; the D-13 test at T8 must fail.

---

## Wave 3 — every door builds a request

Seven tasks, file-disjoint by owning package. Each keeps the suite green on its own.

### [ ] T4 · `func`'s four entry paths build requests

**Files:** `src/functualize/_cli/main.py`

The job, group, single-file and builtin paths construct a `RunRequest` and call the facade.
Deposits stay in place for now — T12 removes them.
Surfaces: `func.job`, `func.group`, `func.single-file`, `func.builtin`.

**Gate**
```bash
rg -c 'RunRequest\(' src/functualize/_cli/main.py
```
now: `0` · after: `4`

### [ ] T5 · Both click constructors build requests through one helper

**Files:** `src/functualize/app/adapters/click_params.py`,
`src/functualize/app/adapters/lazy_command.py`,
`src/functualize/app/adapters/_request_builder.py` (new)

`pitfalls.md` §23 — two dispatch paths, one contract. Both callbacks call the same builder.

**Gate**
```bash
rg -c 'build_request\(' src/functualize/app/adapters/click_params.py src/functualize/app/adapters/lazy_command.py
```
now: `click_params.py:0`, `lazy_command.py:0` · after: `click_params.py:1`, `lazy_command.py:1`

**Test:** for one argv, the eager and lazy paths produce **equal** requests (risk R-b).

### [ ] T6 · An app's own CLI builds requests

**Files:** `src/functualize/app/adapters/cli.py`, `src/functualize/app/commands.py`

Surface `app.cli`. Registration paths (`function=` at `cli.py:353`, `commands.py:134`) are
**not** touched — they register a job, they do not execute one.

**Gate**
```bash
rg -c 'RunRequest\(|build_request\(' src/functualize/app/adapters/cli.py
```
now: `0` · after: `≥1`

### [x] T7 · The three plugins build requests

**Files:** `plugins/functualize-http/src/functualize_http/__init__.py`,
`plugins/functualize-lambda/src/functualize_lambda/__init__.py`,
`plugins/functualize-mcp/src/functualize_mcp/_tools.py`,
`plugins/functualize-mcp/src/functualize_mcp/_server.py`

Surfaces `http`, `lambda`, `mcp.tool`, `mcp.run-job`, `mcp.async`. The `**kwargs` splat into
`app.execute` stops here — T15 pins that it cannot come back.

**Gate**
```bash
rg -c 'app\.execute\([a-z_]*name, \*\*' plugins/*/src/*/__init__.py plugins/functualize-mcp/src/functualize_mcp/_tools.py
```
now: `functualize_http:1`, `functualize_lambda:2`, `_tools.py:2` · after: `0` in all four

### [x] T8 · The event door goes through the facade — **D-13**

**Files:** `src/functualize/_app/impl.py`, `tests/app/test_event_submit_scope.py`

Surface `event.job-submit`. The scope stops being unaddressable because the facade returns it.

Spec AC-14, AC-15, AC-17b.

**Gate**
```bash
rg -c 'execution_engine\.execute\(' src/functualize/_app/impl.py
```
now: `1` · after: `0`

**Test:** submit a `@workflow` through `interactivity.job.submit`; it blocks; the scope id is
reported; `workflow answer` + `workflow resume` drive it to completion.
**Sabotage:** restore the direct engine call; this test must fail.

### [x] T9 · Both TUI doors build requests

**Files:** `src/functualize/_cli/tui/job_execution.py`, `src/functualize/_cli/inline_tui.py`

Surfaces `tui.inline`, `tui.shell`. Note `_execute_command` no longer exists; the executing
body is `inline_tui.py::_run_handoff:143`.

**Gate**
```bash
rg -c 'RunRequest\(|build_request\(' src/functualize/_cli/tui/job_execution.py src/functualize/_cli/inline_tui.py
```
now: `0`, `0` · after: `≥1`, `≥1`

### [ ] T10 · `rc.invoke` and `invoke_parallel` build requests

**Files:** `src/functualize/_engine/capabilities/invoke.py`

Surfaces `invoke`, `invoke.parallel`. `parent_scope=self._workflow_scope` at `:398` and
`parent_scope=None` at `:603` are **preserved exactly** — spec AC-17.

**Gate**
```bash
rg -c 'parent_scope=None' src/functualize/_engine/capabilities/invoke.py
```
now: `1` · after: `1` *(unchanged — this gate asserts the deliberate behaviour survives)*

---

## Wave 4 — the cutover

### [ ] T11 · Delete `execute()`; resolution, kwargs-split and stdin move into `run()`

**Files:** `src/functualize/_engine/executor.py`,
`src/functualize/app/adapters/click_params.py`, `src/functualize/app/adapters/lazy_command.py`

**The riskiest commit in the feature** (risk R-a). One commit: `run()` resolves via
`get_job`/`materialize_job`, the config-model/kwargs split moves in from
`click_params.py:1099-1104`, stdin-marker resolution from `:1108-1124`, and
`execute(job_name, function, …)` is deleted. Remove the T2 transitional label.

Spec AC-3, AC-4, AC-7.

**Gate — the old entry is gone**
```bash
rg -c 'def execute\(' src/functualize/_engine/executor.py
```
now: `1` · after: `0`

**Gate — nothing calls it (narrowed, see header)**
```bash
rg -n 'engine\.execute\(|execution_engine\.execute\(' src/functualize/ plugins/*/src/ | wc -l
```
now: `6` *(`_app/impl.py:861`, `invoke.py:401`, `invoke.py:598`, `click_params.py:1148`,
`lazy_command.py:153`, `core.py:621`)* · after: `0`

**Gate — the engine's own recursions moved too**
```bash
rg -n 'self\.execute\(' src/functualize/_engine/executor.py | wc -l
```
now: `2` *(`:1216`, `:1795`)* · after: `0`

**Verification:** `tests/group_options/` with `--run-slow` (both surfaces),
`TestWarmBootParity`, `tests/engine/test_lifecycle_order.py`.
**Sabotage:** break the config-model/kwargs split; `tests/group_options/` must go red.
**Sabotage:** make materialization raise on the lazy path only; the warm-parity pair must fail.

---

## Wave 5 — the deposits die and the flags appear

### [ ] T12 · The ten deposit writes are removed

**Files:** `src/functualize/_cli/main.py`

`prompt_gates`, `output_format` and `force` are request fields as of T4; the writes are now
dead. Spec AC-8, AC-9.

**Gate**
```bash
rg -c 'app\._(prompt_gates|output_format|force) *=' src/functualize/_cli/main.py
```
now: `10` · after: `0`

**Gate — the kernel stops reading them**
```bash
rg -c '_prompt_gates|_output_format' src/functualize/_engine/executor.py src/functualize/_engine/capabilities/stdout.py
```
now: `executor.py:1`, `stdout.py:1` · after: `0`, `0`

### [ ] T13 · `--prompt-gates` and `--output` on an app's own entry point — **D-1, D-2**

**Files:** `src/functualize/app/adapters/cli.py`,
`tests/cli/test_app_surface_prompt_gates.py`, `tests/cli/test_app_surface_output_format.py`

Spec AC-10, AC-11.

**Gate**
```bash
rg -c 'prompt-gates|--output' src/functualize/app/adapters/cli.py
```
now: `0` · after: `≥2`

**Test:** via the dual-surface `cli_run` fixture — the same test body passes on `func` and on
an app entry point. This test **cannot exist today**; that is the defect.

### [ ] T14 · `FUNCTUALIZE_CLI_OUTPUT` is read or removed

**Files:** `src/functualize/_cli/builtins.py`

Spec AC-13. It is documented in help text at three sites and read nowhere.

**Gate**
```bash
rg -c 'FUNCTUALIZE_CLI_OUTPUT' src/functualize/_cli/builtins.py src/functualize/
```
now: `builtins.py:3`, tree-wide: `3` · after: help-text count `3` **and** a read site, **or**
tree-wide `0`

### [ ] T15 · Control inputs cannot arrive as job arguments

**Files:** `src/functualize/app/core.py`,
`tests/app/test_control_inputs_are_not_kwargs.py`

Closes the accidental channel (spec §1.6a, AC-17a). After T7 no door splats; this task makes
it *unrepresentable* — `request_for(**kwargs)` treats `scope_id` and `group_option_values` as
job arguments, never as control inputs.

**Gate**
```bash
rg -n 'def execute\(self, job_name.*scope_id' src/functualize/app/core.py | wc -l
```
now: `1` · after: `0`

**Test:** an HTTP body `{"scope_id": "x"}` reaches the job as an argument named `scope_id`,
and does **not** address scope `x`.

---

## Wave 6 — history

### [ ] T16 · Parallel batch items reach history — **#5**

**Files:** `src/functualize/_engine/executor.py`,
`src/functualize/_engine/capabilities/invoke.py`

Spec AC-18. The `invoke_depth == 0` rule stays for workflow steps and dependencies — the
rationale at `executor.py:683-688` is sound and a deep workflow must not evict the 200-entry
ring. Parallel *items* are top-level work a user asked for, and are the exception.

**Gate**
```bash
rg -n 'invoke_depth == 0' src/functualize/_engine/executor.py | wc -l
```
now: `4` *(`:683` docstring, `:705` the history gate, `:1042` and `:1059` perf marks)* ·
after: `4`, with `:705`'s condition widened — **the count is not the gate here**; the test is.

**Test:** `func builtin parallel a b` then `func builtin history` lists `a` and `b`.

---

## Wave 7 — the dead argument

### [ ] T17 · `config_class` leaves the step and dependency seams

**Files:** `src/functualize/_engine/executor.py`

Spec AC-19. `execute()` re-derived it at `:390` (`entry.config_class or detected_config`), so
passing it at `:1221` and `:1800` was always redundant.

**Gate**
```bash
rg -n 'config_class=entry\.config_class' src/functualize/_engine/executor.py | wc -l
```
now: `3` *(`:390` the derivation, `:1221` step seam, `:1800` dependency seam)* · after: `1`
*(`:390` only)*

---

## Wave 8 — measurement and documentation

### [ ] T18 · A warm-cache `func <job>` phase in the budget suite — **T8**

**Files:** `tests/perf/test_startup_budget.py`

Spec AC-20. Author it by running it: measure the phase, record the number in a comment, set
the budget from the measurement (risk R-g).

**Gate**
```bash
rg -c 'warm' tests/perf/test_startup_budget.py
```
now: `0` · after: `≥1`

**Sabotage:** insert a 200 ms sleep on the warm path; the phase must fail.

### [ ] T19 · Docs follow the surface

**Files:** `docs/guides/`, `contributor/architecture/surface-boundary.md`

`--prompt-gates` and `--output` are no longer `func`-only. `surface-boundary.md`'s §4 table
changes from aspiration to description.

**Gate**
```bash
uv run python -m functualize._cli.main builtin doc-verify --list >/dev/null && echo ok
```
now: `ok` · after: `ok` *(doc-verify stays green)*

---

## Wave 9 — checkpoint

### [ ] T20 · Feature gate

Checkpoints get their own wave — they depend on all prior work.

- `uv run ruff check src/ tests/ plugins/` and `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — 6 contracts kept
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- every AC-1…AC-20 named to a test
- orphan scan over every symbol added by this feature; an `app/utils.py` re-export with no
  `_cli` consumer is removed
- the four sabotage checks above, each run once, **committing before each**
  (`CONSTITUTION.md` → *Commit before sabotaging*)

---

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3"]},
    {"id": 3, "tasks": ["T4", "T5", "T6", "T7", "T8", "T9", "T10"]},
    {"id": 4, "tasks": ["T11"]},
    {"id": 5, "tasks": ["T12", "T13", "T14", "T15"]},
    {"id": 6, "tasks": ["T16"]},
    {"id": 7, "tasks": ["T17"]},
    {"id": 8, "tasks": ["T18", "T19"]},
    {"id": 9, "tasks": ["T20"]}
  ]
}
```

**Why these boundaries**

- **W0 → W1 → W2 is a producer chain.** `run()` cannot exist before `RunRequest`; the facade
  cannot take one before `run()` accepts one.
- **W3 is wide because it is mechanical.** Seven doors, seven disjoint file sets, and the
  T2 equality property means each can land alone with the suite green.
- **W4 is alone, and it is the risk.** Deleting `execute()` and moving the kwargs-split must
  be one commit — a wave-mate would make the parity suites ambiguous about what broke.
- **W5 after W4, not before.** Removing the deposits before the fields are wired would run
  every gated workflow with `prompt_gates=False` — the live defect, deliberately caused.
- **W6 and W7 are separate waves only because both edit `executor.py`.** Neither depends on
  the other.
- **W9 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness within each wave**

| Wave | Tasks | Files |
|---|---|---|
| 3 | T4 / T5 / T6 / T7 / T8 / T9 / T10 | `_cli/main.py` / `adapters/click_params.py`+`lazy_command.py`+`_request_builder.py` / `adapters/cli.py`+`app/commands.py` / 4 plugin files / `_app/impl.py` / `tui/job_execution.py`+`inline_tui.py` / `capabilities/invoke.py` |
| 5 | T12 / T13 / T14 / T15 | `_cli/main.py` / `adapters/cli.py` / `_cli/builtins.py` / `app/core.py` |
| 8 | T18 / T19 | `tests/perf/` / `docs/` + `contributor/` |

No two tasks in a wave share a file. `_engine/executor.py` is touched by T2, T11, T16 and
T17 — all four are alone in their waves. `app/adapters/click_params.py` is touched by T5 and
T11, in waves 3 and 4.
