# 04 · Request and entry — `RunRequest`, one resolution, and the death of the deposit protocol

Causes **C-I** (the unresolved entry contract) and **C-IV** (the deposit protocol), and the
one shipping-class defect either audit found.

---

## A. The entry contract as it stands

`src/functualize/_engine/executor.py:657`:

```python
def execute(
    self,
    job_name: str,
    function: Callable[..., Any],       # ← the caller resolved this
    *,
    kwargs: dict[str, Any],
    invoke_depth: int = 0,
    cwd: Path | None = None,
    job_directory: Path | None = None,
    config_class: type | None = None,   # ← and this
    parent_scope: Any | None = None,
    workflow_scope_id: str | None = None,
    run_dependencies: bool = True,
    force_fresh: bool = False,
    force: bool = False,
    group_option_values: dict[str, Any] | None = None,
) -> JobResult:
```

**Thirteen parameters** excluding `self` (the audits say twelve; recounted here). Two of them
— `function` and `config_class` — are the *result of a resolution the caller had to perform*.

The engine already resolves by name for its own children:

| Site | Code |
|---|---|
| `executor.py:1216` | `entry = self.get_job(step_name)` then `self.execute(step_name, entry.function, …)` |
| `executor.py:1795` | `entry = self.get_job(node)` then `self.execute(node, entry.function, …)` |

> Resolution is an engine capability exposed only on the inside. Outside, it is
> re-implemented per door.

### The eight resolution sites

Six external, two engine-internal — unchanged in membership since `c0c921f`:

| # | Site | Resolves how |
|---|---|---|
| 1 | `app/core.py:620-621` (`app.execute`) | `self.job_registry.get_job(job_name)` → `.function` |
| 2 | `app/adapters/click_params.py:1148` (eager click callback) | function bound at command-build time |
| 3 | `app/adapters/lazy_command.py:153` (lazy click callback) | materialized from the descriptor |
| 4 | `app/adapters/cli.py` (`_try_discovered_job`) | `engine.materialize_job` |
| 5 | `_cli/main.py` (`_handle_job` → `_materialize_for_dispatch`) | builds a click command whose callback re-resolves |
| 6 | `_app/impl.py:861` (`on_job_submit_event`) | `app.job_registry.get_job(job_name)` → `.function` |
| 7 | `_engine/capabilities/invoke.py:401` | `registered_job.function` |
| 8 | `_engine/capabilities/invoke.py:598` (`parallel`) | `registered_job.function` |

Sites 2 and 5 are the same job resolved twice in one process: `func`'s dispatch materializes
the job to *build* the click command, and the callback then resolves it again to *run* it.

## B. The deposit protocol — measured, and larger than reported

The audits named three attributes the kernel reads off the app. The full enumeration at
`e57f0c9` is **seven**.

### Writers — all ten, all in `_cli/main.py`

```
main.py:945   app._output_format = output_format      # builtin path
main.py:1246  app._output_format = output_format      # group path
main.py:1247  app._prompt_gates  = prompt_gates
main.py:1248  app._force         = force
main.py:1366  app._output_format = output_format      # job path
main.py:1367  app._prompt_gates  = prompt_gates
main.py:1368  app._force         = force
main.py:1666  app._output_format = output_format      # single-file path
main.py:1667  app._prompt_gates  = prompt_gates
main.py:1668  app._force         = force
```

**Every write is in `_cli/main.py`.** That is the whole of D-1 and D-2 in one observation: a
project's own entry point (`app.cli_command()`, `adapters/cli.py`) never executes any of these
lines, so `--prompt-gates` and `--output` cannot exist there. Verified live by the coverage
audit: `python appfail.py boom --output json` → `Error: No such option '--output'.`

> **Correction, found while executing T12 (2026-09-10): there were eleven writes, not ten, and
> not all of them were in `_cli/main.py`.** `app/adapters/cli.py:1001` wrote `_force` — which
> is why an app entry point *did* have `--force` while lacking the other two. The enumeration
> above missed it because the counting gate was scoped to `_cli/main.py`, so it could not see
> outside the file it was already looking at.
>
> The **conclusion** stands for `--prompt-gates` and `--output`: neither had a writer on the
> app side and neither existed there. The **premise** as stated ("every write is in main.py")
> was false, and it is the more useful half to get right — a census that stops at the file you
> suspect will confirm whatever you suspected.

### Readers

| Attribute | Read at | Direction |
|---|---|---|
| `_prompt_gates` | `_engine/executor.py:1283` | delivery → **kernel** |
| `_output_format` | `_engine/capabilities/stdout.py:151,156` | delivery → **kernel** |
| `_force` | `app/adapters/click_params.py:74` | delivery → delivery |
| `_app` | `runcontext.py:425,479,698,719,764`; `invoke.py:710`; `live.py:135`; `stdout.py:151`; `tty.py:132`; `executor.py:1283,1550,1573` | kernel → app, back-reference |
| `_surface_stack`, `_surfaces` | `_engine/surface_routing.py:46,49,63,64,86,89` | kernel → delivery |
| `_ambient_constructs` | `_engine/ambient.py:125,154` | kernel → delivery |
| `_event_bus` | `runcontext.py:428` | kernel → app |

**New finding.** `_force` is a *delivery-to-delivery* deposit — written in `main.py`, read in
`click_params.py` — while `_prompt_gates` and `_output_format` cross the kernel boundary.
They are three instances of one habit but only two are layer violations, and a fix that treats
them identically will look wrong to `lint-imports` in one case and to nobody in the other.
All three become `RunRequest` fields regardless; the distinction matters only for how the
change is justified in review.

**Also new.** Six of the seven attributes are read through `getattr(app, "_x", default)` — a
silent default. A door that fails to deposit does not fail; it gets `"auto"`, or `False`, or
`[]`. **The deposit protocol has no missing case**, which is exactly why D-1 and D-2 went
unnoticed: the app surface has been silently running every workflow with `prompt_gates=False`
since the flag existed.

## C. D-13 — the one shipping-class defect

`src/functualize/_app/impl.py:861`, verified at `e57f0c9`:

```python
registered_job = app.job_registry.get_job(job_name)
...
app.execution_engine.execute(
    job_name,
    registered_job.function,
    config_class=registered_job.config_class,
    kwargs=kwargs,
)
```

Four arguments. No `parent_scope`. No `workflow_scope_id`. Scope creation lives in
`app/core.py:606-628` — inside `FunctualizeApp.execute`, which this call bypasses.

**Consequence — stated precisely, because the audit's wording is imprecise and this set
inherited the imprecision once.** There are *two* scope objects and they are minted in
different places:

| | Minted by | Where |
|---|---|---|
| The in-memory `WorkflowScope` trace | `FunctualizeApp.execute` | `app/core.py:606-628` — **skipped by this door** |
| The **persisted** scope record | the engine, for every `@workflow` | `_engine/workflow_runner.py:97` — `self._scope_id = scope_id or new_scope_id()`, reached from the prelude at `executor.py:869-877` |

So a workflow submitted through the event **does** get a persisted scope. What it does not get
is a way for anyone to learn the id: the event handler returns nothing, creates no in-memory
scope, and passes no `workflow_scope_id` in. The scope exists and is **unaddressable**.

The practical outcome is the same — the run cannot be answered or resumed, and is unreachable
for the rest of its life — but the fix is different. It is not "create a scope here"; it is
"route through the facade so the id comes back", which is exactly §D.3.

This is the only door with that property, and it is a *workflow* defect found by an
*entrypoint* audit — the clearest single piece of evidence that these two bodies of work are
one ([03 §D](03-the-run-model.md)).

### C.1 The opposite defect: three doors have a channel nobody designed

`FunctualizeApp.execute` declares two control parameters as keywords
(`app/core.py:573-580`):

```python
def execute(self, job_name: str, *, scope_id=None, group_option_values=None, **kwargs): ...
```

and three doors splat a **caller-controlled dictionary** into it. HTTP
(`functualize_http/__init__.py:177`):

```python
result = await asyncio.to_thread(self._app.execute, job_name, **kwargs)
```

where `kwargs` is the decoded request body. Lambda (`:159`, `:197`) and MCP's `run_job`
(`_tools.py:287`) and async worker (`_tools.py:450`) do the same with their event and
argument dicts.

**So a request body carrying `scope_id` binds to the control parameter, not to the job.** A
remote caller can address an existing workflow scope on a door whose documented contract has
no resume channel at all — D-6 says these doors *cannot* resume; in fact they can, by
accident, without validation, and without appearing in any schema.

`force` cannot leak this way: it is not an `app.execute` parameter, so it lands in job kwargs,
and a `@workflow` refuses unexpected launch arguments (`executor.py:851-863`). Per-job MCP
tools are schema-driven and do not leak either.

This is the same root cause as D-1/D-2 seen from the other side. Where the deposit protocol
made a control input **unreachable** on some doors, `**kwargs` splatting makes it
**reachable by anyone** on others. A typed `RunRequest` closes both: control inputs are
fields, job arguments are `kwargs`, and no dictionary crosses between them.

> `rc.invoke` was reported as having the same defect. It does not:
> `_engine/capabilities/invoke.py:398,406` propagates `parent_scope=self._workflow_scope`.
> `invoke.py:603` (`parallel`) passes `parent_scope=None` **deliberately**, with the comment
> *"Independent — no shared scope"*. See [02 §F](02-audit-corrections.md).

## D. The target

### D.1 `RunRequest` — one frozen value object

`src/functualize/_types/run_request.py`, stdlib-only — the same placement logic as
`exit_codes.py` and `naming.py`, so `_cli`, `app`, `_engine` and plugins can all import it
with no cycle.

Fields = today's thirteen, **minus** `function` and `config_class` (the engine resolves
them), **plus** the deposit protocol's three, **plus** provenance:

```python
@dataclass(frozen=True, slots=True)
class RunRequest:
    job_name: str
    kwargs: Mapping[str, Any]
    group_option_values: Mapping[str, Any] | None = None
    parent_scope: Any | None = None
    workflow_scope_id: str | None = None
    invoke_depth: int = 0
    cwd: Path | None = None
    job_directory: Path | None = None
    run_dependencies: bool = True
    force: bool = False
    force_fresh: bool = False
    prompt_gates: bool = False        # was app._prompt_gates
    output_format: str = "auto"       # was app._output_format
    surface: str = "unknown"          # provenance — which door built this
```

`surface` is the field neither audit asked for and both needed: the coverage audit had to
*reconstruct* which door a run came from, by reading code. Once it is a field, the run record
([08](08-durable-runs.md)) records it for free, and "which surface is failing" becomes a
query rather than an investigation.

### D.2 `engine.run(request)` — one resolution authority

`run()` resolves via `get_job`/`materialize_job`, splits config-model fields out of `kwargs`
(knowledge that lives today in `click_params.py:1099-1104`), resolves stdin markers
(`click_params.py:1108-1124`), and enters `_execute_lifecycle` unchanged.

**`execute(job_name, function, …)` is deleted.** Clean cutover, no shim — pre-release stance,
and a shim would preserve exactly the door this feature exists to close.

The invariant, and it is grep-able: *no production code outside `_engine/` holds a job
function for the purpose of executing it.*

### D.3 `FunctualizeApp.execute(request)` — the one Facade

Non-click doors already go through the facade. The click family bypasses it because the
facade could not accept what click has — parsed kwargs and a resolved function.
`RunRequest` fixes precisely that, so the click family converges too, and scope creation
(`core.py:606-628`) stops being skippable. **That is the D-13 fix**: not a patch at
`impl.py:861`, but the removal of the alternative.

## E. Freshness belongs to the job, and today the job never sees it

A decision taken for this set, and it changes one thing in F1.

The framework decides freshness and then **skips the body entirely**:

```python
# _engine/executor.py:1026
if preflight_decision is not None and not preflight_decision.should_run:
    return self._preflight_result(job_name, context, preflight_decision, start_time)
```

So a job cannot implement "am I fresh? then return my cached artifact instead of rebuilding".
The engine has already decided, and the body is never entered. Storing artifacts is the job's
business — it knows the format, the location and the domain — but it cannot act on a verdict
it never receives.

**The precedent is exact and already has an ADR.** `Sources` (ADR-012) was the same shape:

> *"A job declares the files it depends on, the pre-flight expands that glob and records
> `{path: {mtime, size, sha256}}` for each match on **every run**, uses it to decide freshness
> — and then threw it away. The body, about to read exactly those files, had no way to reach
> it, so every job restated the glob its own declaration had just run. Two statements of one
> intent, free to drift."*
> — `_engine/capabilities/sources.py`

The fix was not to build a file-reading service. It was to stop discarding what the pre-flight
already had: `PreflightDecision` "now carries what it used to discard", bound to the body by
`Sources._bind` once the decision is in hand. `PreflightDecision` already carries `verdict`,
`key`, `recorded_value`, `source_map`, `declared_sources`, `declared_generates`
(`_engine/preflight.py:49-64`) — **the verdict is already on the object.**

So the work is two small things, and they are feature **F9** ([13](13-roadmap.md)), not a
caching engine:

1. Expose the verdict to the body, `Sources`-shaped — a capability bound off
   `PreflightDecision` after the pre-flight, before the body.
2. Give a job a way to say *"do not skip me on freshness — let me decide"*, since otherwise
   the body is still never entered when fresh.

Point 2 is the only genuinely new design decision, and it is a declaration-surface change
(job-author facing), which is why F9 is its own feature rather than an acceptance criterion
inside F1.

**What this set will not build** is an artifact store, content addressing, or cache eviction
— see [11 §B](11-boundaries.md).

## F. Blast radius

| # | Claim | Verdict |
|---|---|---|
| RAD.1 | Every production call site of `engine.execute` changes once — the eight in §A plus plugin surfaces | **CONFIRMED** |
| RAD.2 | External plugins reaching past `AdapterPlugin` (direct engine construction, `engine._app` reads) break silently; not enumerable from this repo | **CONFIRMED** — needs a plugin-guide release note |
| RAD.3 | Job authors using `RunContext`'s re-exposures change imports once | **CONFIRMED** — pre-release, one release note |
| RAD.4 | **The kwargs-split / stdin move is the riskiest change in the set.** Identical behaviour must survive across eager click, lazy click, group options and stdin markers, on both surfaces | **CONFIRMED** — defended by `TestWarmBootParity` (`tests/integration/test_declared_capabilities_e2e.py:540`) and the dual-surface `cli_run` harness (`tests/conftest.py:454`), and by nothing else |
| RAD.6 | `func why`'s second verdict engine (`app/core.py:725-823`) must not be orphaned by any pre-flight move | **CONFIRMED** |
| RAD.7 | A warm-cache `func <job>` wall-clock phase must be added to `tests/perf/test_startup_budget.py` after the resolution move, so the change is measured rather than assumed | **CONFIRMED** — see [12](12-performance.md) |

## G. Sabotage checks

Per `contributor/guides/wiring-discipline.md` §3 — **commit before sabotaging**;
`git checkout -- <file>` reverts everything uncommitted in that file.

| Break this | This must fail |
|---|---|
| Drop `group_option_values` from the request builder | `tests/group_options/` (exercises the matrix through both surfaces) |
| Make materialization raise on the lazy path only | the warm/cold parity pair in `TestWarmBootParity` |
| Drop `prompt_gates` from the request | the app-surface gate-prompt test added by F1 (this test cannot exist today — that is D-1) |
| Restore the `impl.py:861` direct-engine call | the D-13 scope test: a workflow submitted via the event blocks with a resumable scope id |
