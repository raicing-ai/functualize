# Research: Workflow Launch Validation

Findings that decided the plan. Each carries the probe that produced it.

---

## R1 — Python already implements the exact rule. Do not write one.

The spec needs "reject an argument the function cannot accept, but do **not**
require the arguments DI will fill" (B1 + B3). That is precisely
`inspect.Signature.bind_partial`:

```
def f(log, version: str = 'x')     f(zzz=1)      -> TypeError: got an unexpected keyword argument 'zzz'
def g(log, **kw)                   g(zzz=1)      -> OK
def h(log)                         h()           -> OK          # missing DI arg tolerated
def f(log, version: str = 'x')     f(version=1)  -> OK
```

All four rows are the spec's behaviors — B1, B5, B3, B6 in order. `bind_partial`
gets every one right with no branching of ours.

**The one gap is wording.** `bind_partial` omits the function name that a real
call includes:

```
bind_partial ->            got an unexpected keyword argument 'zzz'
real call    ->  h() got an unexpected keyword argument 'zzz'
```

So the implementation is: let `bind_partial` decide, catch its `TypeError`, and
re-raise with `f"{function.__name__}() {exc}"`. **Python owns the rule; we own
only the timing and the wording.** That is what makes A2 (parity with a plain
job) an equality rather than an approximation.

## R2 — No DI classifier is needed, and building one would be wrong

The spec's note asked how to exclude DI parameters. The answer is that we must
**not** exclude them.

DI parameters are ordinary declared parameters, and the engine already lets a
caller supply one — `_resolve_di_parameters`' merge loop injects only names
"not already provided by caller" (`executor.py:826`). So `execute(job, log=X)`
is legal today for a plain job, and the launch check must keep it legal for a
workflow job. Membership in the signature is the whole question; where a
parameter's value *would have come from* is irrelevant to it.

This also removes the coupling the spec worried about. There is an existing
classifier — `ResolutionPlan` / `ParamBinding.source`
(`_engine/resolution.py:22-55`, one of `"di" | "runcontext" | "config" |
"skip"`) — and the check does not touch it. Nothing to reuse, nothing to
duplicate, nothing for the follow-on `Param` work to inherit badly.

## R3 — A plain job's bad-kwarg failure *does* fire `AFTER_FAILURE`

Relevant because A2 claims parity and a plugin can observe hooks.

The `TypeError` from a plain job is raised at the actual call, inside
`_execute_with_lifecycle`, whose `except BaseException` fires `AFTER_FAILURE`
before returning the `FAILURE` result (`executor.py:2397-2400`). `PRE_EXECUTE`
has already fired by then.

So a launch refusal that fires no hooks at all would be observably different
from the plain-job case it claims to match.

## R4 — The codebase already has a shape for "refused before running"

The config-validation handler (`executor.py:872-930`) does exactly this: on
`ValidationError` / `MissingValueError` it fires `AFTER_FAILURE`, deliberately
skips `PRE_EXECUTE` ("without invoking PRE_EXECUTE hooks or executing the
function"), emits `job.execute.end` with `status="failure"`, and returns a
`FAILURE` `JobResult` carrying the exception.

The launch check should return through that same shape rather than invent a
third failure path. Its comment also records *why* the shape exists: a config
failure that escaped as a raised exception meant "the most common user error was
the one that printed a raw traceback."

## R5 — Ordering: the hook needs a context the prelude runs before

```
executor.py:789-800   workflow prelude  (walks the graph; may return early)
executor.py:808       ExecutionContext constructed
executor.py:815+      DI resolution
executor.py:872+      config resolution + ArgValidator
```

The check must precede line 789. The `AFTER_FAILURE` hook wants a
`RunContext`, or the `ExecutionContext` as the documented fallback
(`context.capabilities.get(_RunContext, context)`).

Every argument `ExecutionContext(...)` takes — `job_name`, `function`,
`kwargs`, `invoke_depth`, `cwd`, `job_directory`, `start_time`, `config_class`,
`parent_scope` — is already in scope at line 789. Constructing it above the
prelude instead of below is therefore mechanical, and the prelude does not read
it, so the move is inert for the existing path.

**That inertness is a claim to prove, not assume** — it is the plan's main risk
and gets its own sabotage check.

## R6 — What "the graph did not run" is observable as

Reproduced against `42d6bc5` from `examples/standalone/composition_lab/`:

```python
>>> app.execute('lab.release', scope_id='spec-probe-1', zzz_nonsense=1)
RunStatus.BLOCKED
>>> StateStore.for_project(Path.cwd()).get_scope('spec-probe-1')
status:   blocked
steps:    ['lab.bundle::', 'lab.parse::', 'lab.publish::', 'lab.report::']
gates:    ['approval-gate']
position: approval-gate
```

So A1 asserts the post-fix scope has **empty `steps`, empty `gates`, and no
`position`**. Status alone cannot separate the two behaviors — the pre-fix run
returns `BLOCKED` and the post-fix run returns `FAILURE`, but a test asserting
only `status is FAILURE` would also pass against an implementation that ran the
whole graph and failed afterwards.

Incidental: `lab.bundle::` shows `step_key`'s empty `args_hash` in situ. Out of
scope here; it is the follow-on work's problem.

## R7 — Only the programmatic surface is affected

```
$ func lab release --zzz-nonsense 1
Error: No such option '--zzz-nonsense'.
```

click refuses unknown options at parse time, so the CLI never reaches
`execute()` with one. The blast radius is `app.execute`, `rc.invoke` /
`Invoke.__call__`, and the three trigger plugins that forward request data into
kwargs. No CLI test needs changing.
