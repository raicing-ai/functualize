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

### [x] T4 · `func`'s four entry paths build requests

**Files:** `src/functualize/_cli/main.py`

The job, group, single-file and builtin paths construct a `RunRequest` and call the facade.
Deposits stay in place for now — T12 removes them.
Surfaces: `func.job`, `func.group`, `func.single-file`, `func.builtin`.

**Gate**
```bash
rg -c 'RunRequest\(' src/functualize/_cli/main.py
```
now: `0` · after: `4`

### [x] T5 · Both click constructors build requests through one helper

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

### [x] T6 · An app's own CLI builds requests

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

### [x] T10 · `rc.invoke` and `invoke_parallel` build requests

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

### [x] T11 · Delete `execute()`; resolution, kwargs-split and stdin move into `run()`

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
now at wave 4 entry: `3` *(`lazy_command.py:142` and `:177`, `click_params.py:1162`)* ·
after: `0`

*(The `6` this gate was authored against — `_app/impl.py:861`, `invoke.py:401`, `:598`,
`core.py:621` and the two click paths — is the wave-0 number. Waves 1–3 took four of them
through the facade, and `lazy_command.py` grew a second call, so wave 4 opened at 3. The
falsifying command is unchanged; only the starting count is.)*

**Gate — T4's transitional bridges are gone** *(added during execution)*
```bash
rg -n '_run_request|_builtin_delivery_inputs' src/functualize/ \
  --glob '!**/run_request.py' | wc -l
```
now: `13` · after: `0`

*(Widened twice during execution. First: T6 mirrored T4's deposit into
`app/adapters/cli.py` and `app/commands.py`, so a gate scoped to `_cli/main.py` would have
missed two thirds of it. Second, and worse: the anchor was `\bapp\._run_request`, and `\b`
**cannot match `self._app._run_request`** — the character before `app` is `_`, which is a
word character — so `app/commands.py:140` was invisible to a gate written specifically to
find it, and the count read 12 where the truth was 13. The `\b` anchor was there to keep
`_types/run_request.py`'s own docstring out of the count; a `--glob` exclusion does that
without blinding the pattern.)*

> **Why this gate exists.** T4 could not call the facade directly: the four `func` paths
> execute *through* click commands, and the callback that runs the job belongs to T5/T11.
> It therefore built each `RunRequest` and **deposited it** as `app._run_request`, plus a
> module-level `_builtin_delivery_inputs` dict for `func.builtin`, whose callback boots its
> own app in a scope `_run_cli` cannot reach (the audit's pre-boot cause, C-V).
>
> That is an eleventh deposit and a process-global, added by the feature whose purpose is to
> kill the deposit protocol. It is legitimate *only* as a bridge across two waves. **T12's
> gate does not catch it** — that gate names `_prompt_gates|_output_format|_force` — so
> without this gate the bridge would outlive the thing it was bridging to.

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

### [x] T12 · The ten deposit writes are removed

**Files:** `src/functualize/_cli/main.py`

`prompt_gates`, `output_format` and `force` are request fields as of T4; the writes are now
dead. Spec AC-8, AC-9.

**Gate**
```bash
rg -c 'app\._(prompt_gates|output_format|force) *=' src/functualize/_cli/main.py
```
now: `10` · after: `0`

*(Eleven writes, not ten: `app/adapters/cli.py:1001` wrote `_force` too, and this gate is
scoped to `main.py` so it could never see it. Counted and removed.)*

**Gate — the kernel stops reading them**
```bash
rg -c '_prompt_gates|_output_format' src/functualize/_engine/executor.py src/functualize/_engine/capabilities/stdout.py
```
now: `executor.py:1`, `stdout.py:1` · after: `0`, `0`

### [x] T13 · `--prompt-gates` and `--output` on an app's own entry point — **D-1, D-2**

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

### [x] T14 · `FUNCTUALIZE_CLI_OUTPUT` is read or removed

**Files:** `src/functualize/_cli/builtins.py`

Spec AC-13. It is documented in help text at three sites and read nowhere.

**Gate**
```bash
rg -c 'FUNCTUALIZE_CLI_OUTPUT' src/functualize/_cli/builtins.py src/functualize/
```
now: `builtins.py:3`, tree-wide: `3` · after: help-text count `3` **and** a read site, **or**
tree-wide `0`

**Outcome: already satisfied when the wave opened — by prior work, not by this task.**
The audit's premise ("documented in help text at three sites and read nowhere") was true at
`c0c921f` and became false before execution began. `_cli/info.py:63` reads it:

```python
from_env = os.environ.get("FUNCTUALIZE_CLI_OUTPUT")
return from_env if from_env in RENDERERS else "rich"
```

`resolve_renderer`'s own docstring records why it was added — on `func` the settings store had
already folded the variable into `cli_config`, but "a project's own `main.py` builds no store,
so `cli_config` is `None` on that surface and the documented env var silently did nothing".
All three `builtins.py` help sites (`:2510`, `:2624`, `:2718`) route through it
(`:2529`, `:2641`, `:2740`).

Verified by behaviour, not by reading:

```
$ func builtin info jobs                          -> hello  A job to list.
$ FUNCTUALIZE_CLI_OUTPUT=json func builtin info jobs -> [ { "name": "hello", ...
```

Already pinned against regression by `tests/cli/test_info_subcommands.py` (69 passed), so no
new test is owed. The tree-wide count is **7**, not 3 — the gate's `now:` was stale in the
same way its premise was.

*(`contributor/architecture/run-model/01-current-state.md:151` and
`appendix-a-audit-synthesis.md:82` still assert "read by nothing"; corrected with this task.)*

### [x] T15 · Control inputs cannot arrive as job arguments

**Files:** `src/functualize/app/core.py`,
`tests/app/test_control_inputs_are_not_kwargs.py`

Closes the accidental channel (spec §1.6a, AC-17a). After T7 no door splats; this task makes
it *unrepresentable* — `request_for(**kwargs)` treats `scope_id` and `group_option_values` as
job arguments, never as control inputs.

**Gate — the signature, read by introspection rather than by regex**
```bash
uv run python -c "import inspect; from functualize.app.core import FunctualizeApp as A; \
p = inspect.signature(A.execute).parameters; \
print(sorted(p), any(x.kind is inspect.Parameter.VAR_KEYWORD for x in p.values()))"
```
now: `['group_option_values', 'kwargs', 'request', 'scope_id', 'self'] True` ·
after: `['request', 'self'] False`

*(The authored gate was `rg -n 'def execute\(self, job_name.*scope_id' …` and it read `0`
**before the task ran** — `ruff format` wraps a five-parameter signature across lines, so a
single-line pattern matches nothing whether or not the parameters exist. It is the fourth gate
on this branch that could not fail. Introspection cannot be fooled by formatting, and
`tests/app/test_control_inputs_are_not_kwargs.py` asserts the same thing so it cannot rot.)*

**Also closed, and not named by the spec:** `request_for`'s `surface` was keyword-only, which
left one square inch of the same channel open — a caller splatting a payload
(`request_for(name, **body)`) whose body had a key literally called `surface` would have
**relabelled the door the run came through**, and a door's identity is not the caller's to
choose. Both parameters are positional-only now; no caller used the keyword form.

**Blast radius:** 336 failures and 64 errors across 38 test files, none of which the `Files:`
line named. Migrated by two agents; `app/_workflow_control.py:180` — `guarded_execute`, the
ninth execution door — was the one `src/` caller still on the legacy form and is migrated here.
Verified afterwards that no control input degraded into a job argument:
`rg -n 'request_for\([^)]*scope_id' tests/` and `rg -n 'kwargs=\{[^}]*"scope_id"' tests/` are
both empty, which is the failure mode that would have left a green suite testing nothing.

**Test:** an HTTP body `{"scope_id": "x"}` reaches the job as an argument named `scope_id`,
and does **not** address scope `x`.

---

## Wave 6 — history

### [x] T16 · Parallel batch items reach history — **#5**

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
after: `4` — **the count is not the gate here**; the test is.

**Test:** `func builtin parallel a b` then `func builtin history` lists `a` and `b`. Verified
end to end:

```
$ func builtin parallel alpha beta   -> Success alpha / Success beta
$ func builtin history               -> job success beta … / job success alpha …
```

**The rule turned out to be about the door, not the depth**, and the spec's framing ("parallel
*items* are top-level work… and are the exception") does not by itself say how to detect one.
Two wrong attempts, both instructive:

1. `surface == "invoke.parallel" and invoke_depth == 1` — recorded **every** fan-out,
   including `rc.invoke_parallel` from inside a job, which is exactly the eviction the depth
   rule exists to prevent. Depth cannot make this distinction: a top-level job's `RunContext`
   and the standalone `WiredInvoke` that `app.execute_parallel` builds **both sit at depth 0**,
   so both put their items at depth 1.
2. The counter-case test that should have caught (1) **passed vacuously** — it called
   `rc.invoke_parallel(["ok", "ok"])` where the API takes `(job, kwargs)` pairs, so the items
   never ran and "no history records" meant "nothing happened". It now asserts the items
   returned `Success` before asserting what history holds.

The landed rule: `app.execute_parallel` — documented as the seam for callers that are *not
themselves jobs* — stamps its items with a new surface **`app.parallel`**, and
`rc.invoke_parallel` keeps `invoke.parallel`. Each door names itself, which is the field's
whole purpose. `RunSurface` gains one value (20, was 19).

**Sabotage, both directions:** widen to `("app.parallel", "invoke.parallel")` and the nested
counter-case fails; narrow to `False` and the top-level case fails.

---

## Wave 7 — the dead argument

### [x] T17 · `config_class` leaves the step and dependency seams

**Files:** `src/functualize/_engine/executor.py`

Spec AC-19. `execute()` re-derived it at `:390` (`entry.config_class or detected_config`), so
passing it at `:1221` and `:1800` was always redundant.

**Gate**
```bash
rg -n 'config_class=entry\.config_class' src/functualize/_engine/executor.py | wc -l
```
now: `3` *(`:390` the derivation, `:1221` step seam, `:1800` dependency seam)* · after: `1`
*(`:390` only)*

**Outcome: satisfied by T11, not by separate work.** Converting the engine's two internal
recursions to `self.run(RunRequest(...))` removed both seam passes as a side effect — a request
carries no `config_class`, so `run()` derives it from `get_job` like every other caller.

Verified as *consolidation* rather than a lost derivation: the one surviving site (`:391`) is
inside `_ensure_materialized`, which `get_job` calls, and it applies
`entry.config_class or detected_config` — so the step and dependency seams now inherit exactly
the same answer instead of being handed a second copy of it. That is what AC-19 asked for.
`tests/workflow/`, `tests/engine/` and `tests/integration/` all green (510 passed).

---

## Wave 8 — measurement and documentation

### [x] T18 · A warm-cache `func <job>` phase in the budget suite — **T8**

**Files:** `tests/perf/test_startup_budget.py`

Spec AC-20. Author it by running it: measure the phase, record the number in a comment, set
the budget from the measurement (risk R-g).

**Gate**
```bash
rg -c 'warm' tests/perf/test_startup_budget.py
```
now: `0` · after: `13`

**Authored by measuring**, nine warm runs after one cold priming run, on this machine
2026-09-10:

| | |
|---|---|
| cold | 825 ms |
| warm | min 739 · median 751 · max 850 |

Budget set to **1800 ms** — ~2x the observed max, the same headroom
`BUDGET_CONFIG_RESOLUTION_MS` takes against its own measurement (300 against a 158 max). CI is
slower and noisier, and a perf test that flakes gets muted, which is worse than one that is
loose.

**The finding worth more than the budget: the warm/cold gap is ~9%.** A `func <job>`
invocation does not spend its time on the discovery cache — interpreter start plus imports are
the cost, and they run to roughly what `boot.total`'s entire 500 ms budget allows *before*
`FunctualizeApp.__init__` is called. Anyone optimising the cache again should know that first.
Recorded in the constant's comment, where the next person to touch it will read it.

Every other test in this file times a phase inside one process; this is the only one that can
see the part of startup that happens before the app exists. It asserts `returncode == 0` on
every run, because a command that exits non-zero is fast for the wrong reason.

**Sabotage:** a 1.2 s sleep in `main()` → median 1966 ms, phase fails; removed → 12 passed.
(The task suggested 200 ms, which would not have crossed a budget set from a real measurement —
the sleep has to exceed the headroom, not merely be noticeable.)

### [x] T19 · Docs follow the surface

**Files:** `docs/guides/`, `contributor/architecture/surface-boundary.md`

`--prompt-gates` and `--output` are no longer `func`-only. `surface-boundary.md`'s §4 table
changes from aspiration to description.

**Gate**
```bash
uv run python -m functualize._cli.main builtin doc-verify --list >/dev/null && echo ok
```
now: `ok` · after: `ok` *(doc-verify stays green)*

**What actually needed changing was not the §4 table.** `--prompt-gates` and `--output` were
never listed as `func`-only, so that table was not the lie. The lie was **item 3 of "How to add
a feature that must align"**, which instructed future authors to do the thing this feature
exists to remove:

> ~~Deposit-and-read for anything genuinely pre-command … a global must land on the app
> (`app._force`, `app._workflow_scope_id`) and be read at call time.~~

Rewritten to the two honest routes, in preference order: pass it to the builder when the
parsing happens first (`func`'s handlers), else put it in the per-invocation `ctx.obj` (an
app's root callback, which parses after its subcommands are built). With the reason stated —
ambient *scope* is sometimes unavoidable, ambient *lifetime* is what breaks — and
`app._workflow_scope_id` explicitly kept as the programmatic seam with no CLI spelling.

The three delivery inputs are added to "must work on both surfaces" as **description**, citing
the two dual-surface test files, so the next reader can check the claim rather than trust it.

Also corrected `run-model/04-request-and-entry.md` §B: it enumerated "all ten, all in
`_cli/main.py`" and there were **eleven**, one of them in `app/adapters/cli.py` — which is why
an app had `--force` but not the other two. Its conclusion held; its premise did not, and the
premise is the half worth getting right. A census scoped to the file you suspect will confirm
whatever you suspected.

---

## Wave 9 — checkpoint

### [x] T20 · Feature gate

Checkpoints get their own wave — they depend on all prior work.

## AC → test, all twenty

Every criterion named to the thing that would catch its regression. A criterion
with no test is a criterion nobody is keeping.

| AC | Kept by |
|---|---|
| AC-1 `RunRequest` frozen, stdlib-only | `tests/types/test_run_request.py` — including an AST scan for internal imports |
| AC-2 `engine.run(request)` resolves by name | `tests/engine/test_engine_run_entry.py::test_run_resolves_the_name_the_caller_did_not` |
| AC-3 `execute` is gone | `rg -c 'def execute\(' src/functualize/_engine/executor.py` → 0; and `tests/app/test_facade_request.py::test_the_legacy_job_name_form_is_gone` for the facade half |
| AC-4 nothing outside `_engine/` passes a function | `rg -n 'engine\.execute\(\|execution_engine\.execute\(' src/ plugins/*/src/` → 0 |
| AC-5 lifecycle order unchanged | `tests/engine/test_lifecycle_order.py` |
| AC-6 warm/cold parity | `tests/integration/test_lazy_true_engine_materialization.py` — the pair that fails when `run()` skips materialization |
| AC-7 split + stdin inside `run()` | `tests/engine/test_run_request_stdin.py` (8 tests) — **written for T10 because nothing covered the wiring**: all 27 existing `test_stdin_*` stayed green with `stdin_markers_for` disabled |
| AC-8 no deposit writes | `rg -c 'app\._(prompt_gates\|output_format\|force) *=' src/functualize/` → 0 |
| AC-9 kernel reads none of them | `rg -c '_prompt_gates\|_output_format' src/functualize/_engine/executor.py src/functualize/_engine/capabilities/stdout.py` → 0, 0 |
| AC-10 `--prompt-gates` on an app | `tests/cli/test_app_surface_prompt_gates.py` — runs on both `cli_run` surfaces |
| AC-11 `--output` on an app | `tests/cli/test_app_surface_output_format.py` — parametrized over whatever the grammar declares |
| AC-12 every door can force | `tests/cli/test_app_surface_output_format.py` + `_request_builder`'s `force` path; the app door's value now travels in `ctx.obj` |
| AC-13 `FUNCTUALIZE_CLI_OUTPUT` read or removed | `tests/cli/test_info_subcommands.py` — read at `_cli/info.py:63`, verified by behaviour |
| AC-14 gated `job.submit` is resumable | `tests/app/test_event_submit_scope.py` |
| AC-15 `_app/impl.py` builds a request | `tests/app/test_event_submit_scope.py`, same pair |
| AC-16 every door names a closed-set surface | `RunRequest.__post_init__` raises on an unknown surface; `tests/types/test_run_request.py::test_unknown_surface_is_rejected` |
| AC-17 `invoke` propagates scope, `parallel` does not | `tests/context/test_parallel_and_log_properties.py` |
| AC-17a control inputs are not job arguments | `tests/app/test_control_inputs_are_not_kwargs.py` (20 tests) — including `inspect`-based signature checks, because the authored gate could not fail |
| AC-17b submitted workflow reports its scope | `tests/app/test_event_submit_scope.py` |
| AC-18 parallel items reach history | `tests/pipeline/test_history_producer.py` — both the top-level case and the nested counter-case |
| AC-19 `config_class` left the seams | `rg -c 'config_class=entry\.config_class' src/functualize/_engine/executor.py` → 1 (the derivation only) |
| AC-20 warm-cache budget | `tests/perf/test_startup_budget.py::TestWarmCommandBudget` |

## What the gate caught that no task's `Files:` line named

The point of a checkpoint is to run the commands nobody ran during the waves.
These were all found here, and all of them were invisible to a normal
`pytest tests/`:

- **`examples/` was outside every migration scope.** T15's blast radius reached
  `examples/quickstart/step7_workflow` (7 tests) and `step3_invoke` (2), which
  are neither `tests/` nor `plugins/`, so neither migration agent could see them.
- **Four test files are `--run-slow`-gated**, so the migration agents (running
  the normal suite) never saw them fail: `tests/test_auto_scope.py` (6),
  `tests/adapters/test_property_lambda_adapter.py` (4, a stale `FakeApp`),
  `tests/plugins/test_mcp_visibility_properties.py` (2 stale fakes),
  `tests/discovery/test_registry_properties.py` (a job never registered).
- **An agent's edit dropped a Hypothesis strategy** and I committed it:
  `test_dispatch_preservation.py`'s two `--output` `@given`s lost
  `job_name=_job_name` while the neighbouring `--perf-report` ones kept theirs.
  Under a normal run all 22 tests in that file **skip**, so my verification saw
  `22 skipped` and read it as fine. It errors only under `--run-slow`.

**Orphan scan:** `RunSurface` and `RUN_SURFACES` were re-exported from the
`app/utils.py` corridor with zero `_cli` consumers. Removed — the corridor is
what `11-boundaries.md` names as the problem, and a re-export nobody imports only
makes it bigger. Both stay public via `functualize.types`.

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

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | `RunRequest` exists, is immutable, refuses an unknown surface, and imports nothing from functualize. | `python3 -c "import ast,sys;t=ast.parse(open('src/functualize/_types/run_request.py').read());print([n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('functualize')])"` — a non-empty list falsifies it. Also construct one with `surface='nope'`: no `ValueError` falsifies it. | Delete the `__post_init__` surface check; `tests/types/test_run_request.py::test_unknown_surface_is_rejected` must fail. |
| 1 | `engine.run(request)` and `engine.execute(...)` are the same execution. | Compare more fields than the test does — `metadata`, `duration_ms` shape — for one job through both entries. A divergence beyond timing falsifies it. | Replace `kwargs=dict(request.kwargs)` with `kwargs={}` in `run()`; 2 tests in `tests/engine/test_engine_run_entry.py` must fail. |
| 2 | The facade takes a request, creates the scope, and calls `engine.run`. | `rg -n 'execution_engine\.execute' src/functualize/app/core.py` — any hit falsifies it. Then check the legacy form still works: `app.execute('job', k=1)`. | Delete the scope creation; `tests/app/test_facade_request.py::test_a_request_creates_an_addressable_scope` must fail. |
| 3 | All seven doors build a request naming their own surface, and no door splats a caller dict into the facade. | `rg -n 'app\.execute\([a-z_]*name, \*\*' src/ plugins/` — any hit falsifies it (this is the accidental control channel). Then `rg -o 'surface="[a-z.-]+"' src/ plugins/ | sort -u` and check every surface against `RUN_SURFACES`: a door naming another door's surface falsifies it. | Restore the direct engine call in `_app/impl.py::on_job_submit_event`; 2 tests in `tests/app/test_event_submit_scope.py` must fail. **This wave's known debt:** `app._run_request` and `_builtin_delivery_inputs` are transitional bridges; confirm T11's gate still names both. |
| 4 | The engine has exactly one entry. `execute(job_name, function, …)` is gone with no shim, every caller — the two click paths and the engine's own two recursions — arrives through `run(request)`, and T4/T6's deposit bridges are gone with the doors still naming their surfaces. | `rg -n 'def execute\(|self\.execute\(' src/functualize/_engine/executor.py` and `rg -n 'engine\.execute\(|execution_engine\.execute\(' src/functualize/ plugins/*/src/` — any hit falsifies it. Then ask it a way the task did not: `python3 -c "from functualize._engine.executor import JobExecutionEngine as E; print(hasattr(E,'execute'))"` must print `False` (`rg` cannot see an inherited or dynamically added method). For the bridges, run the gate **without** its `\b` anchor — `rg -n '_run_request' src/functualize/ --glob '!**/run_request.py'` — because the authored anchor could not match `self._app._run_request` and hid one site. For the surfaces, `rg -o 'surface="[a-z.-]+"' src/functualize/ plugins/*/src/ | sort -u`: `func.job`, `func.group` and `func.single-file` must each appear; `app.cli` is `_request_builder._DEFAULT_SURFACE`. **Two of the nineteen declared surfaces — `func.builtin` and `func.bare` — are produced by nothing.** That is recorded (OPEN-QUESTIONS 11), not an oversight; a claim that all nineteen are reachable would be false. | Break the config-model/kwargs split in `_request_kwargs` (drop the `config_fields` exclusion); `tests/group_options/` must go red. Then make `stdin_markers_for` return `{}` unconditionally; `tests/cli/test_stdin_integration_unit.py` must go red — that pair proves the two blocks that moved out of `click_params.py` are both still on the production path. |
| 5 | *(fill from the wave's task headings: T12, T13, T14, T15)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 6 | *(fill from the wave's task headings: T16)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 7 | *(fill from the wave's task headings: T17)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 8 | *(fill from the wave's task headings: T18, T19)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 9 | *(fill from the wave's task headings: T20)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


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
