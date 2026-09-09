# Feature — run-request-entry

Implements **F1** of `contributor/architecture/run-model/13-roadmap.md`: the audit's steps 1
and 2, the deposit protocol's removal, and the three divergences that fall out of them
(D-1, D-2, D-3) plus the one shipping-class defect (D-13).

**Depends on:** nothing. Runs in parallel with `run-outcome-authority` (F2).
**Blocks:** `engine-sealed-construction` (F3), `surface-request-parity` (F4),
`durable-run-layer` (F5), `agent-step-port` (F6).

Out of scope and why: `contributor/architecture/run-model/11-boundaries.md`.

---

## 1. The problem

**A run has no identity on the way in.** It is assembled by nine doors as thirteen loose
keyword arguments, two of which are the result of a resolution each door performs for itself,
and three of which are not arguments at all but attributes parked on the app object by one
CLI module. Around that centre, five verified defects.

### 1.1 The engine cannot resolve the job it is asked to run

`_engine/executor.py:657` takes `function: Callable` and `config_class: type` — the *results*
of a name→job resolution the caller performed. Eight production sites perform it:

| # | Site | Resolves how |
|---|---|---|
| 1 | `app/core.py:620-621` | `job_registry.get_job(name).function` |
| 2 | `app/adapters/click_params.py:1148` | bound at command-build time |
| 3 | `app/adapters/lazy_command.py:153` | materialized from the descriptor |
| 4 | `app/adapters/cli.py` (`_try_discovered_job`) | `engine.materialize_job` |
| 5 | `_cli/main.py` (`_handle_job`) | builds a click command whose callback re-resolves |
| 6 | `_app/impl.py:861` | `job_registry.get_job(name).function` |
| 7 | `_engine/capabilities/invoke.py:401` | `registered_job.function` |
| 8 | `_engine/capabilities/invoke.py:598` | `registered_job.function` |

Verified: `def execute(` is at `executor.py:657` with **13 parameters excluding `self`**.

The engine already resolves by name for its own children — `executor.py:1216` (workflow
steps) and `:1795` (dependencies) both call `self.get_job(...)` then `self.execute(...)`.
Resolution is an engine capability exposed only on the inside.

Sites 2 and 5 are the same job resolved twice in one process.

### 1.2 Three flags are parked on the app, and only `func` parks them

Verified — `rg 'app\._(prompt_gates|output_format|force) *='` returns **ten** hits, **all in
`_cli/main.py`**:

```
main.py:945   _output_format                       (builtin path)
main.py:1246  _output_format  1247 _prompt_gates  1248 _force   (group path)
main.py:1366  _output_format  1367 _prompt_gates  1368 _force   (job path)
main.py:1666  _output_format  1667 _prompt_gates  1668 _force   (single-file path)
```

A project's own entry point (`app.cli_command()`, `app/adapters/cli.py`) executes none of
these lines. The kernel then reads them back:

- `_prompt_gates` — `_engine/executor.py:1283`, via `getattr(self._app, "_prompt_gates", False)`
- `_output_format` — `_engine/capabilities/stdout.py:151,156`, via `getattr(app, "_output_format", "auto")`
- `_force` — `app/adapters/click_params.py:74` (delivery→delivery, not a layer crossing)

**Every read has a silent default.** A door that never deposits does not fail; it gets
`False`, or `"auto"`. So an app surface has been running every gated workflow with
`prompt_gates=False` for as long as the flag has existed, and nothing reported it.

### 1.3 `--prompt-gates` cannot be reached from an app's own entry point (D-1)

Consequence of 1.2. The app-side root callback (`app/adapters/cli.py`) registers no such flag
and nothing sets `app._prompt_gates`, so a gated walk on an app surface can never be
interactively prompted. This is the same class of defect `--scope-id` was fixed for in 0.3.0.

### 1.4 `--output` is `func`-only, and its env var is read by nothing (D-2)

Consequence of 1.2. Verified live by the coverage audit against a throwaway project:

```
$ python appfail.py boom --output json
Error: No such option '--output'.
```

`FUNCTUALIZE_CLI_OUTPUT` appears only in help text (`_cli/builtins.py:1961, 2072, 2166`) and
is read by no code.

### 1.5 Nothing outside the two click surfaces can force a run (D-3)

`--force` is deposited at `main.py:1370` and `cli.py:996` and consumed at
`click_params.py:74` → `engine.execute(force=…)`. `FunctualizeApp.execute` (`core.py:573-629`)
forwards `scope_id`, `group_option_values` and kwargs — **not `force`**. So a stale job
reached over MCP, HTTP or Lambda cannot be forced to run without a shell.

### 1.6 A workflow started by an event can never be resumed (D-13)

`_app/impl.py:861`, verified at HEAD:

```python
app.execution_engine.execute(
    job_name,
    registered_job.function,
    config_class=registered_job.config_class,
    kwargs=kwargs,
)
```

Four arguments. No `parent_scope`, no `workflow_scope_id`. Two scope objects exist and are
minted in different places — the in-memory `WorkflowScope` trace by `FunctualizeApp.execute`
(`app/core.py:606-628`, skipped by this door), and the **persisted** scope record by the
engine for every `@workflow` (`_engine/workflow_runner.py:97` —
`self._scope_id = scope_id or new_scope_id()`, reached at `executor.py:869-877`).

So the workflow **does** get a persisted scope. What nobody gets is its id: the event handler
returns nothing, creates no in-memory scope, and passes no `workflow_scope_id` in. The scope
exists and is **unaddressable** — it cannot be listed against the run that made it, answered,
or resumed. This is the only door with that property.

### 1.6a Three doors have a resume channel nobody designed

`FunctualizeApp.execute` declares its control inputs as keyword parameters
(`app/core.py:573-580`):

```python
def execute(self, job_name: str, *, scope_id=None, group_option_values=None, **kwargs): ...
```

and three doors splat a **caller-controlled dictionary** into it — HTTP
(`functualize_http/__init__.py:177`, the decoded request body), Lambda (`:159`, `:197`), and
MCP's `run_job` (`_tools.py:287`) and async worker (`_tools.py:450`).

A payload carrying `scope_id` therefore binds to the control parameter rather than to the
job's arguments. These doors are documented as having **no** resume channel; in fact they have
an unvalidated one that appears in no schema. `force` does not leak the same way — it is not
an `app.execute` parameter, so it lands in job kwargs and a `@workflow` refuses unexpected
launch arguments (`executor.py:851-863`).

Same root cause as §1.2 seen from the other side: where deposits made a control input
unreachable on some doors, `**kwargs` splatting makes one reachable by anyone on others.

### 1.7 Parallel batch items never reach history (#5)

`executor.py:705` records history only when `invoke_depth == 0`; `invoke.py:598` runs
`parallel` items at depth+1. The items run and are never recorded. It rides along here
because it is a property of the same wrapper that §1.1 rewrites.

### 1.8 A dead argument at the workflow step seam

`executor.py:1221` passes `config_class=entry.config_class` and `execute()` re-derives it at
`:390` (`entry.config_class or detected_config`). It dies with the parameter.

---

## 2. User stories

- **US-1 · A workflow reached by an event can be finished.** As an application embedding
  functualize, when a job is submitted through `interactivity.job.submit` and it blocks on a
  gate, I get a scope id and can answer and resume it — the same as from any other door.
- **US-2 · My own CLI has the same flags `func` does.** As the author of a project with its
  own `main.py`, `--prompt-gates` and `--output` work on my entry point, because they are
  about the program and not about reaching it.
- **US-3 · An agent can force a stale job.** As an agent driving functualize over MCP, I can
  re-run a job the fingerprint considers fresh, without asking a human to open a terminal.
- **US-4 · A new engine feature reaches every surface for free.** As a maintainer, when I add
  an execution input, I add a `RunRequest` field and a lifecycle step — I do not visit nine
  call sites and decide nine times whether to thread it.
- **US-5 · I can tell which surface a run came from.** As a maintainer debugging a report of
  "it works on the CLI but not over MCP", the run itself records which door built it.
- **US-6 · Parallel work appears in history.** As a user, `func builtin history` shows the
  items a parallel batch ran, not just the batch.

---

## 3. Behaviour

### 3.1 One request object

> Everything a run needs is one frozen value. The engine's signature stops being the
> extension point: a new execution input is a field, not a parameter on nine call sites.

`RunRequest` is stdlib-only and lives in `_types/`, so `_cli`, `app`, `_engine` and plugins
can all import it without a cycle — the same placement logic as `exit_codes.py` and
`naming.py`.

### 3.2 One resolution authority

> The question *"which function is this name?"* has exactly one answer, inside the engine.

`engine.run(request)` resolves via `get_job`/`materialize_job`, splits config-model fields
out of `kwargs`, resolves stdin markers, and enters `_execute_lifecycle` unchanged.
**No production code outside `_engine/` holds a job function in order to execute it.**

`execute(job_name, function, …)` is **deleted**, not deprecated
(`.spec/CONSTITUTION.md` → Pre-Release Stance; *Forbidden Patterns* → no shims).

### 3.3 The deposit protocol becomes fields

| Was | Becomes |
|---|---|
| `app._prompt_gates`, read via `getattr(..., False)` | `request.prompt_gates` |
| `app._output_format`, read via `getattr(..., "auto")` | `request.output_format` |
| `app._force`, read by `click_params.py` | `request.force` |

Each becomes a **required decision at request construction**, so a door that omits it is a
type error rather than a silent `False`. The remaining four private-attribute reach-throughs
(`_app`, `_surface_stack`/`_surfaces`, `_ambient_constructs`, `_event_bus`) are **F3's**, not
this feature's.

### 3.4 The facade is the only way in

`FunctualizeApp.execute(request)` is the single surface-facing entry, **including for the
click family**, which bypasses it today because the facade could not accept parsed kwargs and
a resolved function. Scope creation (`core.py:606-628`) stops being skippable.

> **This is the D-13 fix.** Not a patch at `impl.py:861` — the removal of the alternative.

### 3.5 Provenance is recorded

`RunRequest.surface` names the door that built it. It is required, and its permitted values
are a closed set, so a new door must declare itself.

### 3.6 What must not change

- `_execute_lifecycle`'s 20-step order. `tests/engine/test_lifecycle_order.py` is green at
  **every commit** of this feature.
- Warm/cold behavioural equality. `TestWarmBootParity` is green at every commit.
- Pre-boot routing: still ~3 ms with zero job-module imports. Resolution happens after boot,
  never in the trie.
- `parallel` continues to pass `parent_scope=None` deliberately (`invoke.py:603`).

---

## 4. Acceptance criteria

**The request and the resolution (audit steps 1–2)**

- **AC-1** `RunRequest` exists in `src/functualize/_types/run_request.py`, is a frozen
  dataclass, and imports nothing outside the standard library.
- **AC-2** `JobExecutionEngine.run(request)` exists and resolves the job by name internally.
- **AC-3** `JobExecutionEngine.execute` no longer exists. `rg 'def execute\(' src/functualize/_engine/executor.py` returns nothing.
- **AC-4** No file outside `src/functualize/_engine/` passes a job function for execution.
  Asserted by a test, not by review.
- **AC-5** `_execute_lifecycle`'s step order is unchanged — `tests/engine/test_lifecycle_order.py` passes.
- **AC-6** `TestWarmBootParity` passes: a cold-boot run and a warm-boot run of the same job
  produce the same result and the same recorded history entry.
- **AC-7** The config-field/kwargs split and stdin-marker resolution happen inside
  `engine.run`; `app/adapters/click_params.py` no longer performs either.

**The deposit protocol (D-1, D-2, D-3)**

- **AC-8** `rg 'app\._(prompt_gates|output_format|force) *=' src/` returns **zero** hits.
- **AC-9** `getattr(self._app, "_prompt_gates", …)` and `getattr(app, "_output_format", …)`
  no longer appear in `src/functualize/_engine/`.
- **AC-10** `--prompt-gates` works on a project's own entry point: a gated workflow run
  through an app-defined CLI with `--prompt-gates` prompts, and without it blocks.
- **AC-11** `--output json` works on a project's own entry point and produces the same bytes
  as `func` does for the same job.
- **AC-12** `app.execute(...)`, MCP `run_job`, HTTP and Lambda can all force a run: a job the
  fingerprint reports fresh runs anyway when the request carries `force=True`.
- **AC-13** `FUNCTUALIZE_CLI_OUTPUT` is either read by the code or removed from the help text.
  It is not documented and inert.

**Scope and provenance (D-13)**

- **AC-14** A `@workflow` submitted through `interactivity.job.submit` that blocks on a gate
  reports a scope id, and that scope can be answered and resumed to completion.
- **AC-15** `_app/impl.py` no longer calls `app.execution_engine` directly; it builds a
  request and calls the facade.
- **AC-16** Every door sets `RunRequest.surface`, and the value is drawn from a closed set.
  A request built with an unknown surface is rejected.
- **AC-17** `rc.invoke` still propagates `parent_scope`, and `parallel` still passes `None` —
  neither changes.
- **AC-17a** A job argument named `scope_id` or `group_option_values` no longer binds to a
  control parameter. An HTTP body, a Lambda event and an MCP `run_job` argument dict carrying
  those keys reach the job as job arguments; addressing a scope requires the request field.
- **AC-17b** A workflow submitted through `interactivity.job.submit` reports its scope id to
  the caller — the scope is addressable, not merely created.

**History and dead weight (#5, the `config_class` seam)**

- **AC-18** Items of a parallel batch appear in `func builtin history`.
- **AC-19** `config_class` is no longer passed at the workflow step seam
  (`executor.py:1221`); the engine derives it.

**Performance (T8)**

- **AC-20** `tests/perf/test_startup_budget.py` carries a warm-cache `func <job>` wall-clock
  phase with a budget, and it passes.

---

## 5. Out of scope, deliberately

- The four remaining private-attribute reach-throughs and every post-hoc engine write — F3.
- The `RunStatus` translation sites and the flag vocabulary — F2.
- Giving `Invoke`, HTTP and Lambda a *group-option* channel — F4. This feature gives them a
  request; F4 gives them the syntax to fill it.
- The run *record*. `RunRequest` is the identity on the way in; the durable record is F5.
- Exposing the freshness verdict to the job body — F9.

## 6. Prior art this feature is consistent with

- **ADR-020** — this is its decisions 1 and 2, with the deposit protocol folded in.
- **ADR-012** (`Sources`) — the same move at a smaller scale: stop discarding what one layer
  already computed and the next layer needs.
- **`pitfalls.md` §6** — *a list hardcoded in five places has already drifted*. Ten deposit
  writes in one file is that list.
- **`pitfalls.md` §23** — *two dispatch paths, one result-handling contract*. Eager and lazy
  click already converge on `deliver_job_result`; after this they converge on `run` too.
- **ADR-001, ADR-004** — the same house move, third application: find the single authority,
  collapse the re-derivations, seal the boundary.

## 7. Why the urgent tranche is not a separate feature

`contributor/architecture/run-model/13-roadmap.md` §C. The audit recommends landing D-13,
D-1 and D-2 first and separately because they need no redesign and ship in days. That benefit
is *shipping early*, which the one-branch-one-PR constraint removes — while the cost, writing
each fix twice, remains. They are ordered first **within** this feature instead.
