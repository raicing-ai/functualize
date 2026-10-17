# research.md — from-step-walk-reads

Findings from the Specify retrieval pass, against `master` at `c03dfb72`
(the shape page was measured at `c75a476e`; its line numbers are re-anchored
here where they moved). Findings that are simply true went into `spec.md`;
these are the ones that change or bound the feature's shape.

## Retrieval performed

- Prose: zvec-grep index built for this worktree (14 325 entities, 1 m 48 s),
  queries on gate payload reads, `FromStep` meaning, duplicate node names and
  silent annotation failures. Prior art found: `contributor/adr/005-shell-and-task-runner.md:49`
  ("Epilogue body on `END` with `FromStep` injection" — the original design,
  never built), `contributor/reference/workflow-walker.md:44-50` and `:89`,
  `contributor/reference/pitfalls.md` §4 (PEP 563 annotations), and the
  `FromJob(run=False)` default rule in the `FromJob` docstring.
- Counts and negatives: `rg`, below, with the number each returned.
- Behaviour: one throwaway probe (verbatim below), run with the main checkout's
  virtualenv and `PYTHONPATH=src` of this worktree.

## H1 — a gate's answer is already a step record (confirmed, and simpler than the page assumed)

The walker records every node's value the same way: `ledger.results[name] = run.value`
(`src/functualize/_engine/workflow_walker.py:552`), and a gate node's run value
is its accepted answer (`src/functualize/_engine/gate_service.py`, replay path
via `_recorded_payload` → `FrontierWalk.gate_payload`,
`src/functualize/_engine/frontier.py:496-512`). Measured: after the gate is
answered and the walk resumed, the scope holds

```
steps['approve::'] = {'return_value': {'ok': True}, 'return_value_kind': 'json',
                      'return_value_reusable': True, 'return_value_type': 'dict',
                      'status': 'success', ...}
```

So "read a gate's answer" and "read a step's result" are **one read** — the
walk's step records, by node name — not two. The shape page described the gate
read as `gates['approve'].payload`; that slot exists but is the legacy deposit
path (`TRANSITIONAL(FUN-21)` in `frontier.py:509-511` and
`_types/persistence.py:898-899`), and the accepted-candidate model now carries
the answer. Reading the step record avoids depending on either.

Consequence for the existing tool-binding resolver: it already resolves a gate
name (probe P6 below) because it reads step records.

## R1 — fingerprint resurrection (bounded)

`_from_job_value` (`src/functualize/_engine/executor.py:2185-2236`) reads the
walk's step records through the runtime-store port
(`self._runtime_store.workflows.steps(scope_id)`, `:2205`) and, when none
matches, falls through to fingerprint records (`:2229-2235`). A `FromStep`
read routed through that function unchanged would inherit the fallthrough.
Spec B3 forbids it; AC6 pins it.

## R2 — a step and a gate sharing a name (settled: impossible)

`_validate_workflow_graph` refuses duplicate node names across all node kinds
(`src/functualize/workflow/_validation.py:68-78`). Measured:
`workflow(steps=[Step(approve), Gate(name="approve", …)], …)` raises
`ValueError: Duplicate workflow node name 'approve'`. Scope keys drop the
`::<suffix>` (`executor.py:2206`), but within one graph a name identifies one
node, so the read is unambiguous.

## R3 — `ChoiceDecision.state` (not changed; one unverified observation)

The decision resolver reads `ctx.workflow_context[step]`
(`src/functualize/_gate/decision_strategy.py:71-77`), filled from
`dict(ledger.results)` (`gate_service.py:120`). Since `ledger.results` holds
gate answers too (H1), a gate name in `state=` may already resolve today when
that gate ran earlier in the walk; no static check restricts `state` to steps
(`rg -n "decide|\.state\b" src/functualize/_engine/workflow_validation.py src/functualize/workflow/_validation.py` → 0 hits).
**Not probed** (it needs a decision provider). The shape page's claim that a
gate name there "remains a declared error" is therefore unverified; this
feature changes nothing on that path and the spec claims nothing about it.

## Two readers of one record (input to the Plan architecture gate)

The step record is read in three places:

| Reader | Reads via | Location |
|---|---|---|
| `FromJob` injection | runtime-store port `workflows.steps(scope_id)` | `src/functualize/_engine/executor.py:2205` |
| gate-tool binding (core) | raw scope document `scope["steps"]` | `src/functualize/app/_workflow_control.py:836-870` |
| gate-tool binding (MCP) | raw scope document, duplicated function | `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py:440` |

`rg -n "def _resolve_bound" src plugins` → 2 definitions. This is a
duplicate-code / divergent-change candidate for the BEFORE diagram; whether
the AFTER removes it is a Plan decision.

## Counts behind the spec

- `rg -c FromStep tests -g '*.py'` → 13 files; the `None` pin is
  `tests/integration/test_part_i_remaining_cells.py:286` (MCP surface).
- `rg -n -c FromStep -g '*.md'` (docs surfaces) → `docs/guides/workflows.md` 9,
  `contributor/reference/workflow-walker.md` 5, `contributor/adr/005-…` 4,
  `skills/functualize/references/idiomatic.md` 3,
  `skills/functualize/references/workflows.md` 2,
  `examples/standalone/hermetic_router/README.md` 1.
- `from_job_refs` callers: `rg -n "from_job_refs\(" src` →
  `executor.py:2143` (injection), `workflow_validation.py:67` (ordering),
  `dependency_runner.py:59`; plus `from_job.py` internal use.

## Probe (verbatim) and output

```python
import os, tempfile, traceback
from pathlib import Path
from typing import Annotated
os.chdir(tempfile.mkdtemp())
from pydantic import BaseModel
from functualize._primitives.scope_store import ScopeStore
from functualize._types.from_job import FromJob, FromStep
from functualize._types.workflow import END, Edge, Gate, Step, Tool
from functualize.app.core import FunctualizeApp
from functualize.types import RunRequest
from functualize.workflow._decorator import workflow
from functualize.app._workflow_resume import deposit_gate_input
from functualize.app._workflow_control import _resolve_bound

class Approval(BaseModel):
    ok: bool

def run(app, job, sid):
    return app.execute(RunRequest(job_name=job, surface="app.execute", workflow_scope_id=sid))

def plan() -> str: return "PLAN-1"

print("== P1 epilogue reads a step")
for label, meta in [("FromJob", FromJob("plan")), ("FromStep", FromStep("plan"))]:
    @workflow(steps=[Step(plan)], edges=[Edge(source="plan", target=END)])
    def wf(seen: Annotated[str, meta] = "MISSING") -> str: return seen
    app = FunctualizeApp(name="p1"+label)
    app.register_dynamic_job("plan", plan); app.register_dynamic_job("wf", wf)
    r = run(app, "wf", "P1"+label); print(label, r.status, repr(r.return_value))

print("== P2 duplicate step/gate name")
def approve() -> str: return "x"
try:
    workflow(steps=[Step(approve), Gate(name="approve", awaits=Approval)], edges=[Edge(source="approve", target=END)])
    print("accepted")
except Exception as e: print(type(e).__name__, e)

print("== P3 FOSS-82 shape")
seen = {}
def act(ok: Annotated[Approval, FromStep("approve")]) -> str:
    seen["act"] = ok; return "ACTED"
@workflow(steps=[Step(plan), Gate(name="approve", awaits=Approval), Step(act)],
          edges=[Edge(source="plan", target="approve"), Edge(source="approve", target="act"), Edge(source="act", target=END)])
def gwf(ok: Annotated[Approval, FromStep("approve")] = None) -> str: return repr(ok)
app = FunctualizeApp(name="p3")
for n, f in [("plan", plan), ("act", act), ("gwf", gwf)]: app.register_dynamic_job(n, f)
r = run(app, "gwf", "G1"); print("boot:", r.status)
store = ScopeStore.for_project(Path.cwd())
print("deposit:", deposit_gate_input(app, store, "G1", "approve", {"ok": True}).get("status"))
r = run(app, "gwf", "G1"); print("resume:", r.status, r.return_value, "act entered:", "act" in seen)
sc = store.get_scope("G1") or {}
print("steps:", {k: (v.get("status"), v.get("error") or v.get("exception")) for k, v in sc.get("steps", {}).items()})
print("gate keys:", list((sc.get("gates") or {}).get("approve", {}).keys()))
print("== P6 Tool binding naming a gate, today")
print(_resolve_bound(sc, {"x": FromStep("approve")}), _resolve_bound(sc, {"x": FromStep("plan")}))

print("== P4 deposit input at a step name")
try: print(deposit_gate_input(app, store, "G1", "act", {"ok": True}))
except Exception as e: print(type(e).__name__, str(e)[:200])

print("== P5 FromStep param outside a walk")
app5 = FunctualizeApp(name="p5"); app5.register_dynamic_job("act", act)
r = app5.execute(RunRequest(job_name="act", surface="app.execute")); print(r.status, str(getattr(r, "error", ""))[:200])

print("== P7 FromStep naming an unknown node: boot")
def act2(ok: Annotated[str, FromStep("nope")] = "DEF") -> str: return ok
@workflow(steps=[Step(plan), Step(act2)], edges=[Edge(source="plan", target="act2"), Edge(source="act2", target=END)])
def w7() -> None: ...
app7 = FunctualizeApp(name="p7")
for n, f in [("plan", plan), ("act2", act2), ("w7", w7)]: app7.register_dynamic_job(n, f)
r = run(app7, "w7", "S7"); print(r.status, (ScopeStore.for_project(Path.cwd()).get_scope("S7") or {}).get("steps", {}).get("act2::", {}).get("return_value"))
print("== gate step record", sc["steps"]["approve::"])
print("== P5 detail", r.status)
r5 = app5.execute(RunRequest(job_name="act", surface="app.execute"))
print({k: str(v)[:160] for k, v in vars(r5).items() if v not in (None, {}, [], "")})
```

Output at `c03dfb72`:

```
== P1 epilogue reads a step
FromJob RunStatus.SUCCESS 'PLAN-1'
FromStep RunStatus.SUCCESS 'MISSING'
== P2 duplicate step/gate name
ValueError Duplicate workflow node name 'approve'
== P3 FOSS-82 shape
boot: RunStatus.BLOCKED
deposit: input_accepted
resume: RunStatus.FAILURE None act entered: False
steps: {'act::': ('failed', None), 'approve::': ('success', None), 'plan::': ('success', None)}
gate keys: ['blocked_at', 'candidates', 'consumed_at', 'input_schema', 'model', 'payload', 'prompt', 'request_id', 'status', 'tools']
== P6 Tool binding naming a gate, today
{'x': {'ok': True}} {'x': 'PLAN-1'}
== P4 deposit input at a step name
GateNotFoundError Workflow 'G1' has no gate 'act'. Gates: approve. Run `func builtin workflow list` to see what is waiting.
== P5 FromStep param outside a walk
RunStatus.FAILURE 
== P7 FromStep naming an unknown node: boot
RunStatus.SUCCESS DEF
== gate step record {'completed_at': '2026-10-13T20:16:23.315179+00:00', 'effecting': False, 'inputs': {}, 'return_value': {'ok': True}, 'return_value_kind': 'json', 'return_value_reusable': True, 'return_value_type': 'dict', 'status': 'success'}
{'status': 'RunStatus.FAILURE', 'duration_ms': '0.40080701000988483', 'metadata': "{'resolved_inputs': {}, 'run_type': <RunType.JOB: 'job'>, 'run_status': <RunStatus.RUNNING: 'Running'>, 'start_time': datetime.datetime(2026, 10, 13, 20, 16, 24", 'exception': "act() missing 1 required positional argument: 'ok'", 'job_name': 'act'}
```
