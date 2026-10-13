# effecting-step-recovery — research

Findings from the Specify retrieval pass that change the shape of the feature.
Facts that are simply true go straight into `spec.md`. Baseline: `origin/master`
at `c75a476e`. The engine files (`_engine/frontier.py`, `_engine/workflow_walker.py`,
`_types/workflow.py`, `app/_workflow_answer.py`) are unchanged since `4e816a0f`.

## R1 — An undeclared gate cannot be answered (this decided D2 = 2a′)

The store would accept one. `FrontierWalk.open_request` takes the gate's name and
schema as data, and `answer_gate` validates against the schema recorded with the
request (`app/_workflow_answer.py:337`).

The answer path, however, reads the **declared** workflow at two points:

- `_resolve_gate_model` materialises the gate's model through
  `declaration.node(gate)`. For a name that is not declared it returns
  `gate_unresolvable` ("Workflow '…' no longer declares gate '…'")
  (`app/_workflow_resume.py:92-123`).
- `_walk_has_passed` / `_downstream_of` answer "has the walk passed this gate?" from
  the declared graph's edges (`app/_workflow_answer.py:348`, `:389`).

So the recovery gate must be a node that `WorkflowDeclaration.node(name)` returns.
A name the walker merely knows about is not enough.

## R2 — Gate names are canonicalised, and `.` is the group separator

`Gate.__post_init__` normalises a gate's name through `_job_ref_name`
(`_types/workflow.py:330`). Measured on this checkout:

```
refund.in_doubt  -> refund.in-doubt
refund__in_doubt -> refund--in-doubt
refund-in-doubt  -> refund-in-doubt
refund_in_doubt  -> refund-in-doubt
```

Name resolution treats `.` as the group separator. A bare name matches the last
dotted segment (`_types/naming.py:138-158`). The shape's example, `refund.in_doubt`,
would therefore read as a job `in-doubt` in a group `refund`, and a bare answer to
`in-doubt` would be ambiguous as soon as two steps were effecting. **The spec uses
`<step>-in-doubt`** (spec Q-1). This refines the shape's illustrative name. It does
not change the decision.

## R3 — The gate ladder can answer from the config chain

`_gate_strategy_list` (`_engine/gate_service.py:46-65`) gives an undeclared-strategy
gate the ladder `["prompt", "resolve"]` when prompt-gates is on, and `None`
(block) otherwise. `resolve` is the **config chain** (`Gate` docstring,
`_types/workflow.py:303-304`).

A configured or environment value for the recovery gate's field would become a
standing answer to *every* future doubt. That is a silent decision, which criterion
3 forbids. The recovery gate's ladder must exclude `resolve`, `ai_inbound`,
`ai_outbound` and `decision` (spec AC-9). D3's later reconciler becomes its own rung.

## R4 — Gate answers are not keyed by loop pass

`rg -n iteration src/functualize/_engine/gate_service.py` returns 0 lines. A gate's
recorded answer is keyed by gate name alone. A recovery gate inside a `Loop` would
therefore replay pass 1's answer for a doubt on pass 3. The spec requires one
answer per pass (AC-13). The plan has to choose the mechanism, because the existing
gate path does not provide one.

## R5 — `Deps` and `inv()` run inside the step's window

A workflow step runs as a full job through `engine.run`
(`_engine/workflow_orchestrator.py:150-185`). A job's `Deps` run inside that call
(`_engine/dependency_runner.py:129`), and so does anything the body invokes. An
attempt committed before `run_step` therefore covers all of it (AC-16).

## R6 — A nested workflow can only be detected at boot

A `Step` names its job by string or callable. Whether that job is itself a workflow
is known only once the registry is resolved. Declaration-time checks
(`workflow/_validation.py`, raising `ValueError` / `TypeError`) cannot see it.
Boot-time checks (`_engine/workflow_validation.py:113`,
`validate_workflow_declarations`, raising `WorkflowDeclarationError`) can. The
E×W×W refusal therefore belongs at boot (AC-12). The name-collision refusal
belongs at declaration time, next to "Duplicate workflow node name"
(`workflow/_validation.py:77`) (AC-11).

## R7 — The shape is cached and digested, and both have a byte-for-byte precedent

`graph_digest` hashes `WorkflowShape.to_dict()` (`_engine/workflow_validation.py:211-237`).
The walk refuses a resume whose recorded digest differs, raising
`WorkflowGraphChangedError` (`_engine/workflow_walker.py:431-441`). A scope with no
recorded digest records the current one and proceeds.

`to_dict()` already adds a key "only when declared, so every gate without one
projects — and digests — byte-for-byte as it did before the field"
(`_types/workflow.py:780-783`, the `decision` key). The same rule gives AC-7 and
AC-10. The cached shape lives in the discovery cache (`CACHE_VERSION = 21`,
`_primitives/cache_format.py:156`), so changing the cache entry's schema bumps it.

## R8 — The flag's intent and its prior specification

`contributor/architecture/run-model/08-durable-runs.md` §B row 2 and §E define the
flag as "a declared distinction between a replayable step and an effecting one".
The integration test cites "`durable-run-layer`/T9. Spec AC-14, AC-15. Risk R-f"
(`tests/integration/test_crash_and_resume.py:1-16`). That feature's artifacts were
cleared, and `rg -n "effecting" .spec/STATUS.md` finds one unrelated line (`:680`),
so no migrated decision about the in-flight window exists to contradict.

The existing kill-point tests pass for both values of the flag, because the kill
lands after the record commits (`test_crash_and_resume.py:61-62`, `:104-133`).

## R9 — Prior art: two outboxes, and neither is this

- `EffectWriter` (`_types/persistence.py:638-656`) is the port for engine-delivered
  effects, with an optional `idempotency_key`. The document backend declares
  `durable_outbox=False` and refuses to append
  (`contributor/reference/runtime-persistence-data-model.md` §2.4). A step's effect
  is run by user code, not delivered by the engine, so it is not an outbox row. The
  attempt record is a step-record state.
- FUN-21's in-flight spec (branch `feat/gate-interactions-outbox`) requires
  "AT-LEAST-ONCE with consumer dedup … no at-most-once claim anywhere". The approved
  shape therefore words this guarantee "never re-run without a decision" (AC-15).

## R10 — The notification gap is real and out of scope

`_notify` skips a `Notify` key that this scope has already recorded as sent
(`_engine/workflow_walker.py:916-919`). An in-doubt stop after an earlier block in
the same scope notifies nobody. This is owned by FUN-21 (Northstar M-1 (a)) per the
approved shape. The spec records it as a known limitation, not an acceptance
criterion.
