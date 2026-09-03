# Shape Intent: Workflow Run Parameters — A Launch Value That Reaches Every Step

**Status: specified, not yet implemented**
**Date: 2026-08-31**
**Scope: the parameter surface of `app.execute()` for a `@workflow` job, the
layer a `Step` resolves from, and what survives a `Gate`. Touches
`_engine/executor.py`, `_engine/workflow_walker.py`,
`_primitives/state_store.py`, and the three trigger plugins
(`functualize-http`, `functualize-lambda`, `functualize-mcp`).**

Every claim below carries the command that demonstrates it. A claim with no
command is not a finding. Commands were run against `2af8a07` from
`examples/standalone/composition_lab/`, whose `lab release` walk is
`parse → report → publish → bundle → [approval-gate] → check.signoff`, and
whose `LabOptions(GroupOptions, group="lab")` declares one field, `strict`.

---

## Core Principle

**A workflow definition is a template; a run is an instance of it.** The value
that distinguishes one run from another has to arrive at launch and be legible
to every node the run reaches — including the nodes reached after a pause.

This is not an argument for a new layer by analogy. It is the property that
makes `@workflow` reusable at all: without it, the only way to run the same
topology two ways is to declare it twice.

**What this intent does not propose.** The *mid-path CLI flag* boundary —
`func lab --strict release` not reaching the walk's steps — is deliberate,
documented (`docs/guides/group-options.md:174-175`, `:192`) and pinned by
`tests/group_options/test_combination_matrix.py:441`. A flag belongs to the
path it was typed at. Nothing below asks to change that. The finding is that
there is no run-scoped channel *of any kind*, so the flag boundary is currently
the only boundary there is, and the layers that do cross are all process-global.

---

## The state of the code

### Assertion 1 — A group option reaches a walk's steps through the env layer. **PASS**

```
$ LAB__STRICT=true func lab release
BUNDLED lab-0.1.0.tar.gz strict=True
Blocked: gate 'approval-gate' in scope '8d8a745b4c914464' awaits input.
```

The env layer is re-read per job execution, so it crosses into steps where the
CLI layer does not. This is the mechanism `docs/guides/group-options.md:198`
("Steering a whole run from code") documents as the way to parameterize a walk.

### Assertion 2 — That value survives the gate. **GAP**

Same run, resumed after depositing the gate's input:

```
$ func builtin workflow resume 8d8a745b4c914464 approval-gate --input '{"note":"ok","author":"ai"}'
$ func lab release --scope-id 8d8a745b4c914464
SIGNOFF verdicts=1 strict=False
```

and the counterfactual, an identical cycle with the variable re-exported:

```
$ LAB__STRICT=true func lab release --scope-id <sid>
SIGNOFF verdicts=2 strict=True
```

**One run, one `scope_id`, two answers, selected by the operator's shell.**
`check.signoff` is the step whose entire purpose is to apply strict mode, and it
is on the far side of the gate — so the parameter is lost at exactly the node
that consumes it. A resumed walk re-resolves every not-yet-recorded step against
whatever environment the *resuming* process happens to have, which is a
different process, possibly a different machine, and in the `ai_outbound` case
possibly a different operator.

This is a correctness defect independent of any position on the design question
below: the documented recipe for parameterizing a walk is unsound across the
feature the walk exists to demonstrate.

### Assertion 3 — A workflow job validates its launch arguments. **GAP**

```python
>>> app.execute('lab.release', strict=True)
RunStatus.BLOCKED          # walk ran with strict=False; the argument vanished
>>> app.execute('lab.release', zzz_nonsense=1)
RunStatus.BLOCKED          # unknown argument accepted in silence
```

No error, no warning. The walk runs to the gate as though nothing was passed.

The argument is not discarded — it is *deferred*, and lands at the worst
possible moment. Bound to a scope and driven to completion:

```python
>>> app.execute('lab.release', scope_id='probe-late', zzz_nonsense=1)
RunStatus.BLOCKED
>>> store.deposit_gate_payload('probe-late', 'approval-gate', {...})
>>> app.execute('lab.release', scope_id='probe-late', zzz_nonsense=1)
RunStatus.FAILURE
```

A misspelled parameter runs the entire graph, blocks, waits for a human to
approve the gate, and only then fails — at the epilogue, where the kwarg is
finally bound to the decorated function's signature. The approval is spent on a
run that was never going to succeed.

The mechanism is visible in the ordering: `_run_workflow_prelude`
(`_engine/executor.py:1092`, called at `:797`) walks the graph *before* DI
resolution and argument binding, so a bad kwarg cannot be detected until the
prelude finishes and the epilogue is entered.

### Assertion 4 — A plain job validates its launch arguments. **PASS**

```python
>>> app.execute('lab.bundle', zzz_nonsense=1)
RunStatus.FAILURE
```

The same nonsense argument, same entry point, rejected immediately. This
contrast is what makes Assertion 3 a defect rather than a design: the parameter
surface of `execute()` is strict for one kind of job and silent for the other,
and nothing at the call site says which kind it is holding.

### Assertion 5 — There is a per-run channel that is not process-global. **GAP**

The two layers that cross into steps are the environment and the config file.
Both are process- or filesystem-global; neither is scoped to a run. The one
in-process override layer is not shared:

```
$ grep -n "def _make_config_view" src/functualize/_engine/executor.py
407:    def _make_config_view(self, section_prefix: str) -> Any:
```

It constructs a **fresh view per job**, and `set()` writes to that view's
`_overrides` dict (`_config/job_config.py:141-160`). So `rc.config.set()` dies
with the job that called it and reaches no step, no `Deps` upstream, and no
`rc.invoke` child.

That leaves `os.environ` mutation as the only working answer, which is a data
race under any concurrent host — two in-flight runs with different values write
the same global and read each other's.

### Assertion 6 — The shipped trigger surfaces can parameterize a walk. **GAP**

```
$ grep -n "app.execute" plugins/functualize-http/src/functualize_http/__init__.py
175:  result = await asyncio.to_thread(self._app.execute, job_name, **kwargs)
$ grep -n "app.execute" plugins/functualize-lambda/src/functualize_lambda/__init__.py
126:  result = app.execute(job_name, **job_kwargs)
```

Both turn a request body / event payload directly into `execute()` kwargs — the
call shape Assertion 3 shows to be silently ignored for a workflow. Neither
passes `group_option_values` at all:

```
$ grep -rln "group_option_values" plugins/*/src
plugins/functualize-mcp/src/functualize_mcp/_server.py
```

MCP is the only trigger surface that plumbs group options
(`_server.py:268-274`), and it routes them into precisely the layer that does
not cross into steps. So an agent starting a gated walk over MCP has its
arguments accepted, schema-validated, and then ignored by every node.

These three plugins exist to turn an external event into a run. An event carries
data. Today they can parameterize a single job and cannot parameterize a walk.

### Assertion 7 — Step replay identity accounts for the values a step ran under. **GAP**

```
$ sed -n 438,445p src/functualize/_engine/workflow_walker.py
def _key(name: str) -> str:
    """Step-record key for a node.

    The args hash is empty because a `Step` takes no arguments — it names a
    registered job and that job's own declaration supplies everything else
    (§A.7). Matrix instances differ by *name*, not by args.
    """
    return step_key(name, "")
```

Resume is replay plus memoization, and the memo key is the node name alone. The
docstring is accurate *today* — a `Step` genuinely takes no arguments. It stops
being accurate the moment a run can carry parameters, and a step recorded under
one parameter set would be replayed for a run launched with another.

**This is the real cost of the work, and the reason it is not a small patch.**
It is recorded as an assertion because any option below has to answer it.

---

## Why this was not caught

The group-options combination matrix is thorough about *layers* and silent about
*runs*. `test_a_workflow_step_does_not_inherit_the_group_cli_layer`
(`tests/group_options/test_combination_matrix.py:441`) pins the CLI-layer
boundary, and its own docstring is careful to say the finding was "observed, not
predicted". The suite even guards against vacuous workflow cells (`:435-438`).

What no cell covers is a **second invocation of the same scope**. Every
workflow assertion in the matrix runs a walk once, start to finish. The gate is
what introduces a second process into a single run, and the gate lives in a
different test area from the group options — so the layer tests never resume,
and the resume tests never vary a layer.

The working rule: **a memoized, resumable run needs its assertions written
across the pause, not up to it.** A layer that is correct on the first
invocation of a scope is not thereby correct on the second, and for gated
workflows the second invocation is where the interesting steps live.

---

## Prior art

Three orchestrators with materially different philosophies — a scheduler, a
Python-native runtime, and an asset graph — converged on the same primitive.

| | Parameter primitive | Supplied at | Persisted on |
|---|---|---|---|
| Airflow | `conf` (JSON) + typed `Params` | `POST /api/v2/dags/{id}/dagRuns` | a column on the DagRun row |
| Prefect | flow `parameters` (pydantic) | `run_deployment()`, REST create-run | the FlowRun record |
| Dagster | `run_config` (pydantic, nested per op) | `RunRequest`, launch API, partitions | the run record |

Two details of that convergence matter here more than the convergence itself.

**They persist on the run, not in the process.** Airflow needs this because
tasks execute on different workers; Prefect and Dagster because runs retry.
Functualize needs it for the same reasons plus one of its own — a gate can hold
a run open across days and processes. Assertion 2 is that requirement failing.

**Dagster addresses Assertion 7 head-on** by making the partition key part of
asset identity, and Prefect by folding parameters into the default cache key.
Neither treats "parameters vary per run" and "results are memoized" as
independent features. Whichever option is taken below inherits that constraint.

Prefect is also the useful contrast for *why* this repository has the gap: in
Prefect the flow body **is** the orchestrator, so parameters reach tasks by
ordinary Python scope. A functualize `@workflow` body is an epilogue that runs
after `END` (`contributor/reference/workflow-walker.md`), so it is structurally
incapable of handing values to the steps it precedes on the page. The gap is a
consequence of the epilogue design, not an oversight in it.

---

## The shape of the work

Two coherent end states. This intent does not pick one — that is a product
question about how seriously the trigger plugins are meant.

**Option A — a run-scoped parameter layer.** Parameters supplied at launch,
validated against a declared model, persisted with the scope, and resolved by
every node in the run as a layer above env. Two pieces already exist and would
be the seams: `_blank_scope()` (`_primitives/state_store.py:45-56`) already
persists per-scope state alongside `gates` and `position`, which is where the
values must live for Assertion 2; and `_events/tracing.py:56` already
propagates `baggage` through a `ContextVar`, which is the in-process half. The
work is the ladder integration, the declaration surface, and Assertion 7.

**Option B — declare walks unparameterizable, and enforce it.** Keep the config
ladder as the only channel, and make the surfaces say so: `execute()` rejects
unknown kwargs for a workflow job at launch, the HTTP and Lambda plugins refuse
a body for one, and the docs stop recommending an `os.environ` recipe that
Assertion 2 shows to be unsound across a resume. This is a legitimate end state
for a local task runner — a build's inputs *should* be a file under version
control — but it is only honest if the plugins stop advertising the shape.

**Not an option: leaving Assertion 3 as it stands.** Silent argument-dropping
followed by a late failure after an approval is spent is a defect under either
option, and its fix is the same under both: bind and validate a workflow job's
arguments at launch, before the prelude walks. It is separable and can land
first.

## Acceptance

Under either option:

- [x] `app.execute('<workflow>', nonsense=1)` fails at launch, before the
      prelude walks. Demonstrated by a test that asserts the graph did **not**
      run — an assertion on status alone passes vacuously here.
      **Done 2026-09-03** (`feat/workflow-run-params`); see `STATUS.md` →
      *Workflow launch validation*. `tests/workflow/test_launch_validation.py`
      asserts the state store is untouched — no step records, no gate, no
      position — because a status assertion would pass against an
      implementation that walked the whole graph and failed afterwards.
- [ ] The gap in `docs/guides/group-options.md:198` is closed: either the
      section documents a channel that survives a resume, or it states in the
      text that the recipe does not, with the gated case named.
- [ ] A test resumes a gated walk in a **second** invocation with a different
      ambient environment and asserts what the post-gate step observes. This is
      the cell `test_combination_matrix.py` has no equivalent of.

Under Option A additionally:

- [ ] A launch parameter set once is observed by a step *after* a gate, in a
      process that does not carry the value in its environment.
- [ ] `_key` (`_engine/workflow_walker.py:438`) accounts for the parameters a
      step ran under, or a documented rule states why replay is safe without it.
      The docstring's "a `Step` takes no arguments" must be re-derived, not
      inherited.
- [ ] Two concurrent runs with different parameter values, in one process, each
      observe their own. `os.environ` cannot satisfy this, which is the point.
- [ ] `functualize-http` and `functualize-lambda` deliver a request body into a
      walk, end to end, through the public entry point (`CONSTITUTION.md`
      §Quality Gates, capability coverage).
