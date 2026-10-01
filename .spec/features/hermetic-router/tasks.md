# hermetic-router — Tasks

Authored 2026-10-01 against `ef1939d` (`origin/master`). Eleven tasks in eight
waves. Every `now:` below was produced by running its command on this branch
at authoring time.

**Execute is NOT yet authorised.** `spec.md` awaits the member's confirmation
and `plan.md` → *Decisions* D-1…D-4 and the review-flagged smells S-1, S-4
await answers. When they arrive, record them here (one line each) and only
then start wave 0. A changed answer sends `spec.md`/`plan.md` back for
revision and the affected gates are re-authored before any `src/**` write.

**The implementation lands on this branch, in this pull request.** The spec is
created, executed and completed within the same PR and removed before merging
(T11). Never open a second PR for the implementation, and never merge.

**The Execute phase reads only this file from the feature directory.** Each
task therefore restates the behaviour, the exact files, the commands and the
observable result that closes it. Ids `B-n`/`AC-n` are `spec.md` §4–§5, `C-n`
are `contracts.md`; you do not need to open either.

## How to read a gate

A fenced `bash` block holding one **count** (`rg -c …`), followed on the next
line by `now:` (measured at authoring) and `after:` (what the task must
produce). `tests/spec/test_task_gates_still_hold.py` re-runs every gate of
every `[x]` task against `HEAD` for the life of the branch, so each gate was
chosen to stay true through every later task. `invariant` marks a count that
must not change. **Comments and docstrings in a counted file count too — do
not mention a counted pattern in prose inside that file.** Run gates from the
repository root.

## Standing rules for every task

- Worktree `/home/ubuntu/orca/workspaces/functualize/sdd-hermetic-router`,
  branch `sdd/hermetic-router`. If `.venv` is missing or stale:
  `uv sync --frozen --all-extras --all-packages`.
- Checks, from the repository root, output redirected:
  `uv run ruff check --fix src/ tests/ plugins/ examples/ > /tmp/functualize-ruff.log 2>&1`,
  `uv run ruff format src/ tests/ plugins/ examples/ > /tmp/functualize-format.log 2>&1`,
  `uv run mypy src/ > /tmp/functualize-mypy.log 2>&1`,
  `uv run lint-imports > /tmp/functualize-lint-imports.log 2>&1`, and the
  task's own pytest command (at most two pytest invocations per verification;
  never pipe pytest through `head`/`tail`).
- One commit per task, conventional subject, single scope token, ≤72 chars,
  lowercase, imperative. **No tracker key, issue URL, agent, model or run
  identity in any commit message.** No `Co-authored-by:` naming an agent.
- **Reachability precedes `[x]`.** T2 and T3 add code whose producer arrives in
  T4; each marks the site `# TRANSITIONAL(hermetic-router/T4): evidence has no
  producer until the decision rung records it`, closes on its own gates, and T4
  removes every marker. From T4 on, name the production call path in the
  commit body. T10 proves each path by sabotage: **commit first**, break the
  call, watch the named test fail, `git checkout -- <file>`.
- Peer independence: `_engine` never imports `_gate` at runtime, `_gate` never
  imports `_engine`; `_types` imports nothing internal but `_types`; core never
  imports `functualize_decision_jev`.
- No test makes a network request. No test sleeps: patch `time.sleep` to raise
  where a provider failure is exercised.
- Wave ordering is binding: never start wave N+1 while wave N has an unchecked
  task.

## Decisions recorded (fill in on approval)

- D-1 (default route): _pending_
- D-2 (evidence location): _pending_
- D-3 (cost): _pending_
- D-4 (`decision_record`): _pending_
- S-1 (rung sink), S-4 (`source` mapping): _pending_

## Wave 0 — foundation

### [ ] T1 — the declared fallback, and the decision's projection moved to its owner

*Files:* `src/functualize/_types/decision.py`, `src/functualize/_types/workflow.py`,
`tests/types/test_decision_values.py`, `tests/workflow/test_gate_decide_declaration.py`,
`tests/workflow/test_decision_policy_digest.py`

Behaviour (B-1, B-2, B-5; C-1):

1. In `src/functualize/_types/decision.py`, add the last field of
   `ChoiceDecision`: `fallback: str | None = None  # one of options; taken when no proposal is accepted`.
   In `ChoiceDecision.__post_init__`, after the options are frozen: if
   `fallback is not None and fallback not in self.options` raise
   `ValueError(f"ChoiceDecision fallback {fallback!r} is not one of the options {sorted(self.options)}")`.
2. **Move** `_decision_shape` from `src/functualize/_types/workflow.py` (it sits
   just above `_node_kind`) to `src/functualize/_types/decision.py` as public-in-package
   `decision_shape(decide: ChoiceDecision) -> dict[str, Any]`, same body, plus:
   `if decide.fallback is not None: shape["fallback"] = decide.fallback`
   (the key is **absent** when `None`, so every existing digest is unchanged).
   In `workflow.py`, replace the one call site (inside the `WorkflowShape`
   projection, `decision=(... if isinstance(node, Gate) and node.decide is not None else None)`)
   with `decision_shape(node.decide)`, imported from `functualize._types.decision`.
3. Add to `decision.py`:
   ```python
   def decision_digest(decide: ChoiceDecision) -> str:
       canonical = json.dumps(decision_shape(decide), sort_keys=True, separators=(",", ":"))
       return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
   ```
   Add `"decision_digest"` and `"decision_shape"` to `__all__`. Update the
   module docstring's "Values and one Protocol, nothing else" sentence to say it
   also holds the declaration's JSON projection and its digest (pure functions).
4. In `Gate._check_decision` (`workflow.py`), **after** the existing
   `_allowed_values(...)` call and the options-equality check (order matters:
   `tests/workflow/test_gate_decide_declaration.py` expects the annotation
   message for `Loose.maybe`/`Loose.numbered`, which have defaults), add:
   - if `not self.awaits.model_fields[decide.field].is_required()`: raise
     `ValueError(f"Gate '{self.name}' decides {self.awaits.__name__}.{decide.field}, which has a default; a default would bypass the decision — declare it as ChoiceDecision(fallback=...)")`;
   - if `decide.fallback is not None`: the other required fields
     `[n for n, f in self.awaits.model_fields.items() if n != decide.field and f.is_required()]`
     must be empty, else `ValueError` naming them and saying the fallback alone
     must complete the answer.

Tests to add (AC-1, AC-12):
- `tests/types/test_decision_values.py`: fallback outside options → `ValueError`;
  fallback `None` default; `decision_digest` starts with `sha256:` and has 71
  chars; two decisions differing only in `fallback` have different digests;
  a decision with `fallback=None` has no `"fallback"` key in `decision_shape`.
- `tests/workflow/test_gate_decide_declaration.py`: a decided field with a
  default raises with `match="fallback="`; a fallback beside another required
  field raises naming that field; a fallback with every other field defaulted
  is accepted.
- `tests/workflow/test_decision_policy_digest.py`: two `@workflow` declarations
  differing only in `fallback` have different `graph_digest`
  (`functualize._engine.workflow_validation.graph_digest`), and a gate without
  `fallback` digests exactly as the existing tests already pin.

Commands: `uv run pytest tests/types/test_decision_values.py tests/workflow/test_gate_decide_declaration.py tests/workflow/test_decision_policy_digest.py -q --no-header > /tmp/functualize-t1.log 2>&1` → all pass.

Gates:

```bash
rg -c "^    fallback: str \| None = None" src/functualize/_types/decision.py
```
now: `0` · after: `1`

```bash
rg -c "^def decision_shape\(|^def decision_digest\(" src/functualize/_types/decision.py
```
now: `0` · after: `2`

```bash
rg -c "_decision_shape" src/functualize/_types/workflow.py
```
now: `2` · after: `0`

Closed when: the three gates read as `after:`, the pytest command passes, and
the five checks are clean. Commit: `feat(workflow): let a decision declare its fallback option`.

### [ ] T2 — candidates carry evidence, stored and projected only when present

*Files:* `src/functualize/_types/gate_resolution.py`,
`src/functualize/_primitives/gate_requests.py`,
`src/functualize/app/_workflow_resume.py`,
`tests/primitives/test_gate_requests.py`, `tests/workflow/test_gate_drafts.py`

Behaviour (B-6; C-2 first half, C-4):

1. `src/functualize/_types/gate_resolution.py`: add the last field of the
   frozen `CandidateEvaluation`:
   `evidence: Mapping[str, Any] | None = None` (import `Mapping` from
   `collections.abc` under `TYPE_CHECKING` or at runtime — the module already
   imports `Any`). Extend its docstring: evidence is JSON-safe, written by a
   strategy rung, never by an answer surface; `None` for every other candidate.
2. `src/functualize/_primitives/gate_requests.py`, in `append_candidate`: build
   the entry dict as today, then on one line
   `if candidate.evaluation.evidence is not None: entry["evidence"] = dict(candidate.evaluation.evidence)`
   — the key is **omitted** when there is none. In `candidates_for`, pass
   `evidence=entry.get("evidence")` to `CandidateEvaluation(...)`. Exactly two
   lines in this file contain the string `"evidence"`.
   Mark the write line `# TRANSITIONAL(hermetic-router/T4): evidence has no producer until the decision rung records it`.
3. `src/functualize/app/_workflow_resume.py`, `_resolution_view`: build each
   candidate's dict as today (seven keys), and add `"evidence"` only when
   `candidate.evaluation.evidence is not None` (`dict(...)` of it). One line
   contains the string `"evidence"`.

Tests to add:
- `tests/primitives/test_gate_requests.py`: appending a candidate whose
  evaluation carries `{"schema": "decision-evidence/1", "x": 1}` stores it under
  `"evidence"` and `candidates_for` returns it equal; one without evidence
  stores no `"evidence"` key and reads back `None`.
- `tests/workflow/test_gate_drafts.py`: the existing exact-dict assertion
  (`result["resolution"]["candidates"] == [ {...seven keys...} ]`) is left
  **unchanged** and still passes; add a test where a candidate with evidence
  projects an eighth key `"evidence"`.

Commands: `uv run pytest tests/primitives/test_gate_requests.py tests/workflow/test_gate_drafts.py tests/types/test_gate_resolution_values.py -q --no-header > /tmp/functualize-t2.log 2>&1` → all pass.

Gates:

```bash
rg -c "^    evidence: Mapping\[str, Any\] \| None = None" src/functualize/_types/gate_resolution.py
```
now: `0` · after: `1`

```bash
rg -c "\"evidence\"" src/functualize/_primitives/gate_requests.py
```
now: `0` · after: `2`

```bash
rg -c "\"evidence\"" src/functualize/app/_workflow_resume.py
```
now: `0` · after: `1`

Closed when: gates as `after:`, pytest passes, five checks clean. Commit:
`feat(gate): record structured evidence beside a candidate's verdict`.

## Wave 1 — the ladder

### [ ] T3 — each rung gets its own evidence sink; a declared fallback is resolved and forced

*Files:* `src/functualize/_gate/_context.py`, `src/functualize/_gate/_registry.py`,
`tests/gate/test_registry_evidence.py` (new)

Depends on T1 (`ChoiceDecision.fallback`) and T2 (`CandidateEvaluation.evidence`).

Behaviour (B-3, B-6; C-2):

1. `src/functualize/_gate/_context.py`: add
   ```python
   class RungEvidence:
       """Write-once collector one ladder rung fills while it runs."""
       def __init__(self) -> None:
           self._value: Mapping[str, Any] | None = None
       def record(self, evidence: Mapping[str, Any]) -> None:
           if self._value is not None:
               raise RuntimeError("a rung records its evidence once")
           self._value = dict(evidence)
       @property
       def value(self) -> Mapping[str, Any] | None:
           return self._value
   ```
   and the **last** field of the frozen `GateContext`:
   `evidence: RungEvidence | None = None` (document it in the class docstring's
   `Attributes:`). Export `RungEvidence` from `functualize._gate.__init__`'s
   `__all__` only if that module re-exports `GateContext` (it does — keep them
   together).
2. `src/functualize/_gate/_registry.py`, `GateRegistry.evaluate`:
   - **Fallback (before Step 1's classification):** when
     `decision is not None and decision.fallback is not None`, set
     `resolved_fields = {**(resolved_fields or {}), decision.field: decision.fallback}`
     and `force_gate = True`. (This is what makes the `resolve` rung take the
     fallback and what stops Step 2's short-circuit from skipping the decision.)
   - **Per-rung sink:** inside the rung loop, for a registered resolver, create
     `sink = RungEvidence()` and call `resolver.resolve(dataclasses.replace(ctx, evidence=sink))`.
     On success record `CandidateEvaluation(EvaluationOutcome.ACCEPTED, evidence=sink.value)`;
     on exception `CandidateEvaluation(EvaluationOutcome.FAILED, detail=str(exc), evidence=sink.value)`.
     `unavailable` and `not_reached` rungs are unchanged (no evidence).
   - Mark the sink creation line `# TRANSITIONAL(hermetic-router/T4): evidence has no producer until the decision rung records it`.
   - Update the `evaluate` docstring's `decision:` arg text to state the
     fallback rule.

Tests to add — `tests/gate/test_registry_evidence.py` (AC-6 groundwork, B-3):
- a resolver that calls `ctx.evidence.record({"k": 1})` then returns a model →
  the accepted rung's evaluation carries `{"k": 1}`; one that records then
  raises → the failed rung carries it; a resolver that records twice → the rung
  is `failed` with `"records its evidence once"` in its detail;
- with `decision=ChoiceDecision(..., fallback="b")` over a one-field
  `Literal["a","b"]` model and ladder `["decision", "resolve"]`, a `decision`
  resolver that raises leaves rungs `[("decision","failed"), ("resolve","accepted")]`
  and `model.<field> == "b"`; a counting `decision` resolver is called exactly
  once (the forced dispatch; F-1 closed for fallback gates);
- with `fallback=None` the Phase 1 behaviour holds (no seeding, no force).

Commands: `uv run pytest tests/gate/ tests/test_gate_resolution.py tests/test_gate_resolution_algorithm.py -q --no-header > /tmp/functualize-t3.log 2>&1` → all pass.

Gates:

```bash
rg -c "^class RungEvidence" src/functualize/_gate/_context.py
```
now: `0` · after: `1`

```bash
rg -c "^    evidence: RungEvidence \| None = None" src/functualize/_gate/_context.py
```
now: `0` · after: `1`

```bash
rg -c "RungEvidence\(\)" src/functualize/_gate/_registry.py
```
now: `0` · after: `1`

Closed when: gates as `after:`, pytest passes, five checks clean. Commit:
`feat(gate): give each ladder rung an evidence sink and honour fallbacks`.

### [ ] T5 — a gate with a fallback is walked `decision → resolve`

*Files:* `src/functualize/_engine/gate_service.py`, `tests/engine/test_gate_service.py`

Depends on T1. Disjoint from T3 (same wave).

Behaviour (B-3, B-4; C-6): in `_gate_strategy_list`, the `declared == "decision"`
branch returns `["decision", "resolve"]` when
`gate.decide is not None and gate.decide.fallback is not None` (comment: a
declared fallback means the router never blocks; `resolve` takes it), and
`["decision", "prompt", "resolve"]` otherwise — unchanged. Nothing else in the
module changes; `_engine` still imports nothing from `_gate`.

Tests to add — `tests/engine/test_gate_service.py`: the strategy list for a
decision gate with a fallback is `["decision", "resolve"]`; without one it is
`["decision", "prompt", "resolve"]` (AC-11, ladder half).

Commands: `uv run pytest tests/engine/test_gate_service.py -q --no-header > /tmp/functualize-t5.log 2>&1` → passes.

Gates:

```bash
rg -c "\"decision\", \"resolve\"" src/functualize/_engine/gate_service.py
```
now: `0` · after: `1`

Closed when: gate as `after:`, pytest passes, five checks clean. Commit:
`feat(engine): walk a decision gate with a fallback as decision then resolve`.

## Wave 2 — the decision rung records evidence

### [ ] T4 — the decision rung builds and records its evidence

*Files:* `src/functualize/_gate/decision_evidence.py` (new),
`src/functualize/_gate/decision_strategy.py`,
`src/functualize/_primitives/gate_requests.py` (marker removal only),
`src/functualize/_gate/_registry.py` (marker removal only),
`tests/gate/test_decision_strategy.py`, `tests/gate/test_decision_evidence.py` (new)

Depends on T1, T2, T3.

Behaviour (B-6, B-7, B-8; C-3). **The resolver module must never contain the
word `confidence`** (ADR-030 point 3, gated below); the builder lives in its own
module for exactly that reason.

1. New `src/functualize/_gate/decision_evidence.py` (module docstring: why it
   exists separately — the rule module never names the provider's own scalar):
   ```python
   SCHEMA = "decision-evidence/1"

   def build_decision_evidence(
       decide: ChoiceDecision,
       *,
       state: str,
       latency_seconds: float,
       result: DecisionResult[str] | None = None,
       error: DecisionUnavailableError | None = None,
       probability: float | None = None,
       margin: float | None = None,
       verdict: str,               # "accepted" | "below_threshold" | "no_distribution" | "provider_failed"
   ) -> dict[str, Any]: ...
   ```
   returning exactly these keys (C-3):
   `schema` (= `SCHEMA`); `field` (= `decide.field`); `state` =
   `{"step": decide.state.name, "sha256": hashlib.sha256(state.encode("utf-8")).hexdigest(), "chars": len(state)}`;
   `rule` = `{"digest": decision_digest(decide), "accept_at": float(decide.accept_at), "min_margin": float(decide.min_margin), "fallback": decide.fallback}`;
   `provider` (= `result.provider`, else `error.provider`); `model` (=
   `result.model` or `None`); `requested_model` (= `result.provenance.requested_model`,
   else `decide.model`); `proposal` (= `result.value` or `None`);
   `distribution` (= `dict(result.distribution)` or `None`); `confidence` (=
   `result.confidence` or `None`); `probability`; `margin`; `verdict`;
   `failure` (= `None`, or `{"kind": error.kind.value, "status": error.status, "retry_after": error.retry_after}`);
   `latency_seconds`; `input_tokens`/`output_tokens` (from
   `result.provenance`, else `None`). Imports: stdlib, `functualize._types.decision`
   (`decision_digest`, types), `functualize._types.errors` (types). `__all__ = ["SCHEMA", "build_decision_evidence"]`.
2. `src/functualize/_gate/decision_strategy.py`, `DecisionGateResolver.resolve`:
   keep the rule exactly as it is. Around `self._provider.choose(...)` take
   `started = time.monotonic()`; on `DecisionUnavailableError` record
   `build_decision_evidence(..., error=exc, verdict="provider_failed", latency_seconds=time.monotonic() - started)`
   through `ctx.evidence.record(...)` (when `ctx.evidence is not None`) and
   re-raise; with no distribution record `verdict="no_distribution"` then raise
   as today; otherwise compute `p`/`margin` as today and record
   `verdict="accepted"` or `"below_threshold"` (with `probability=p`,
   `margin=margin`) **before** returning or raising
   `DecisionBelowThresholdError` (message unchanged). The missing-state-step
   `ValueError` stays first and records nothing.
3. Remove both `TRANSITIONAL(hermetic-router/T4)` markers (in
   `_primitives/gate_requests.py` and `_gate/_registry.py`).

Production call path (name it in the commit body): walk →
`GateService.service` → `GateRegistry.evaluate` → `DecisionGateResolver.resolve`
→ `RungEvidence.record` → rung `CandidateEvaluation(evidence=…)` →
`InputRecorder.ladder_candidates` → `FrontierWalk.record_candidates` →
`gate_requests.append_candidate` → `gate_draft(...)["resolution"]`.

Tests:
- `tests/gate/test_decision_evidence.py`: the key set equals the C-3 list
  exactly (17 keys: `schema field state rule provider model requested_model
  proposal distribution confidence probability margin verdict failure
  latency_seconds input_tokens output_tokens`); `state.sha256` equals
  `hashlib.sha256(text.encode()).hexdigest()`; a failure carries kind/status/
  retry_after and `None` model/proposal/distribution.
- `tests/gate/test_decision_strategy.py`: through `GateRegistry.evaluate`
  with a fake `DecisionProvider` — accepted proposal → rung evidence verdict
  `accepted`, `distribution` equals the returned mapping, tokens as reported;
  below threshold → `below_threshold` on the failed rung; `confidence` 1.0 below
  threshold falls through and `confidence` 0.0 above is accepted (AC-7);
  provider raising `DecisionUnavailableError(kind=RATE_LIMITED, status=429, retry_after=19014.0, …)`
  → evidence `failure == {"kind": "rate_limited", "status": 429, "retry_after": 19014.0}`
  and `latency_seconds >= 0`.

Commands: `uv run pytest tests/gate/ tests/integration/test_decision_gate_e2e.py -q --no-header > /tmp/functualize-t4.log 2>&1` → all pass (the Phase 1 e2e suite unchanged).

Gates:

```bash
rg -c "confidence" src/functualize/_gate/decision_strategy.py
```
now: `0` · after: `0` (invariant — ADR-030 point 3)

```bash
rg -c "^def build_decision_evidence\(" src/functualize/_gate/decision_evidence.py
```
now: `0` · after: `1`

```bash
rg -c "TRANSITIONAL\(hermetic-router/T4\)" src
```
now at T4 entry: `2` · after: `0`

Closed when: gates as `after:`, pytest passes, five checks clean. Commit:
`feat(gate): record the decision's evidence on its ladder rung`.

## Wave 3 — the reader

### [ ] T6 — `decision_record`: one record per routed run

*Files:* `src/functualize/app/_decision_record.py` (new), `src/functualize/app/utils.py`,
`tests/workflow/test_decision_record.py` (new)

Depends on T2 (projection), T4 (evidence shape).

Behaviour (B-9; C-5). New module `src/functualize/app/_decision_record.py`:

```python
def decision_record(store: Any, scope_id: str, gate: str) -> dict[str, Any] | None:
```

- `record = store.get_gate(scope_id, gate)`; `None` → return `None`.
- `candidates = gate_requests.candidates_for(record)` (ordered by ordinal);
  `request = gate_requests.request_for(scope_id, gate, record, lease.generation if lease else 0)`
  with `lease = store.get_lease(scope_id)` — the same call `_resolution_view`
  makes in `app/_workflow_resume.py`.
- `decision` = the last candidate whose `source == "strategy:decision"` (or `None`).
- `accepted` = the candidate whose `evaluation.outcome` is `ACCEPTED` (at most one).
- `decided_by`: `None` if no accepted; `"decision"` if its source is
  `strategy:decision`; `"fallback"` if `strategy:resolve`; else `"person"`.
- `evidence` = `decision.evaluation.evidence` if any, else `None`.
- `route`: if `accepted` is `None` → `None`; elif `evidence` has `"field"` →
  `accepted.payload.get(evidence["field"])`; elif the payload is a dict with
  exactly one key → that value; else `None`.
- `reason`: when `decided_by == "fallback"` and `decision` exists →
  `f"decision: {decision.evaluation.detail}"`; else `None`.
- Return `{"gate", "request_id", "route", "decided_by", "fallback_used", "reason", "evidence"}`
  with `fallback_used = decided_by == "fallback"` and `evidence` as a plain dict
  or `None`.
- Module docstring: a projection of recorded candidates; nothing re-evaluated;
  reads `source` as the reader `GateCandidate` documents; `TRANSITIONAL(FUN-21)`
  storage is read through `gate_requests`, as `_resolution_view` does.

`src/functualize/app/utils.py`: `from functualize.app._decision_record import decision_record`
next to the other workflow imports, and `"decision_record"` in `__all__` beside
`"gate_draft"`. Docstring of the function says **provisional**.

Tests — `tests/workflow/test_decision_record.py`, against a `ScopeStore` in a
`tmp_path` with candidates appended through `gate_requests.append_candidate`:
accepted-by-decision, fallback-after-below-threshold (reason starts with
`decision: `), fallback-after-unavailable (reason contains `install functualize-decision-jev`),
answered-by-person (`decided_by == "person"`, no evidence), unanswered
(`route is None`, `decided_by is None`), missing gate → `None`.

Commands: `uv run pytest tests/workflow/test_decision_record.py tests/workflow/test_gate_drafts.py -q --no-header > /tmp/functualize-t6.log 2>&1` → passes.

Gates:

```bash
rg -c "^def decision_record\(" src/functualize/app/_decision_record.py
```
now: `0` · after: `1`

```bash
rg -c "\"decision_record\"" src/functualize/app/utils.py
```
now: `0` · after: `1`

Closed when: gates as `after:`, pytest passes, five checks clean. Commit:
`feat(app): read a gate's routing decision as one record`.

## Wave 4 — the reference workflow, and the guards

### [ ] T7 — the hermetic router reference workflow

*Files (all new unless marked):* `examples/standalone/hermetic_router/README.md`,
`examples/standalone/hermetic_router/router.py`,
`examples/standalone/hermetic_router/conftest.py`,
`examples/standalone/hermetic_router/tests/test_router.py`,
`examples/standalone/README.md` (edit), `examples/README.md` (edit)

Depends on T1–T6.

Behaviour (B-12…B-15; C-7). **Public API only**: `functualize.app`,
`functualize.app.utils`, `functualize.workflow`, `functualize.plugin`,
`functualize.types`, `pydantic`. No model client, no provider package.

`router.py`:

```python
Route = Literal["deterministic", "cheap_model", "frontier_agent", "human_review"]

class RouteChoice(BaseModel):
    route: Route                      # required — no default

class Review(BaseModel):
    handled: bool

ROUTER = ChoiceDecision(
    field="route",
    instructions="Choose how this request should be handled.",
    options={
        "deterministic": "a fixed rule or lookup answers it; no model needed",
        "cheap_model": "a short, low-risk text task a small model can do",
        "frontier_agent": "multi-step reasoning or tool use is required",
        "human_review": "risky, ambiguous, or needs a person's judgement",
    },
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
    fallback="human_review",
)

def build_router(app: FunctualizeApp, text: str) -> list[str]:
    """Register workflow `router` and its jobs on `app`; return the list stubs append to."""
```

Graph: steps `intake` (returns `text`), `Gate(name="route", awaits=RouteChoice, decide=ROUTER)`,
stub steps `deterministic`, `cheap_model`, `frontier_agent`,
`Gate(name="review", awaits=Review)`, stub step `handle_by_person`; edges
`intake → route`; `ConditionalEdge(source="route", condition=lambda a: a["route"], targets={"deterministic": "deterministic", "cheap_model": "cheap-model", "frontier_agent": "frontier-agent", "human_review": "review"})`
(node addresses canonicalise `_` to `-`; `ConditionalEdge` targets and
`Edge` endpoints accept the declared form, as Phase 1's e2e test writes
`"approve_refund"`, while the **answer path** takes the canonical form —
`answer_gate(..., "review", ...)` is unaffected, `handle_by_person` is
addressed as `handle-by-person`);
`review → handle-by-person`; every stub → `END`. Jobs are registered with
`app.register_dynamic_job(name, fn)` as `tests/integration/test_decision_gate_e2e.py`
does; each stub appends its route name to the returned list and returns it.
**No step is `effecting=True`.**

`conftest.py`: put this directory on `sys.path` (copy
`examples/standalone/plugin_host/conftest.py`).

`tests/test_router.py` (copy the autouse fixtures of
`tests/integration/test_decision_gate_e2e.py`: a `tmp_path` project with a
`.functualize/` directory, `monkeypatch.chdir` into it, `AppState.reset()`
before and after — `AppState` is internal, and resetting process state between
tests is the one internal touch this example's *tests* may make; `router.py`
itself uses public API only — and `time.sleep` patched to raise). A `FakeProvider` implementing the public
`DecisionProvider` protocol returns a canned `DecisionResult` (or raises
`DecisionUnavailableError`); register it with
`app.gates.register_gate_strategy("decision", DecisionGateResolver(FakeProvider(...)))`.
Run with `app.execute(RunRequest(job_name="router", surface="app.execute", workflow_scope_id=<scope>))`;
read with `decision_record(ScopeStore.for_project(Path.cwd()), <scope>, "route")`
(`ScopeStore` from `functualize.app.utils`). One test per criterion:

- AC-2: `cheap_model` 0.82 vs 0.10 → stubs ran `["cheap_model"]`; record
  `route == "cheap_model"`, `decided_by == "decision"`, `fallback_used is False`.
- AC-3: `deterministic` 0.55 vs 0.35 → `"deterministic"` not run; route
  `human_review`, `fallback_used is True`, `"proposed 'deterministic' at 0.55"`
  in `reason`; the run is blocked on `review`.
- AC-4: provider raises rate limited (`status=429, retry_after=19014.0`) →
  route `human_review` in under 1 s; `evidence["failure"]["kind"] == "rate_limited"`.
- AC-6: for AC-2's run, `evidence` has the 17 C-3 keys; `state.sha256` is the
  SHA-256 of the text; `rule.digest` starts `sha256:`; `distribution` equals
  the fake's mapping; tokens equal the fake's provenance.
- AC-7: below threshold with `confidence=1.0` → fallback; above with
  `confidence=0.0` → accepted.
- AC-8: two scopes, same text, distributions differ → equal `state.sha256` and
  `rule.digest`, unequal `distribution`, both records present.
- AC-9: resume the AC-2 scope (`app.execute` again with the same scope id) →
  the fake's call count stays 1 and `decision_record` is unchanged.
- AC-10: in AC-3's run, answer `review` through `answer_gate(app, store, scope, "review", {"handled": True, "evidence": {"forged": 1}})`
  → that candidate has no `"evidence"` in `gate_draft(...)["resolution"]["candidates"]`,
  and `handle_by_person` runs.
- AC-14: walk the declared graph from `route`: every node reachable without
  passing a `Gate` is a `Step` with `effecting=False`.
- Installed-but-unconfigured provider (no fake registered, `OPENCODE_API_KEY`
  removed with `monkeypatch.delenv(..., raising=False)`): route
  `human_review`; `reason` contains `not_configured` when the Jev plugin is
  installed, or `install functualize-decision-jev` when it is not — assert
  one of the two.

`README.md`: what the router shows (routing, not model calls), the four
routes, the thresholds and fallback, how to read `decision_record`, and that
it runs without any provider. `examples/standalone/README.md`: add a table row
for `hermetic_router/` and change "Ten directories … nine ship a step-by-step
README" to "Eleven … ten". `examples/README.md`: "eight self-contained
directories" → the number of directories `ls -d examples/standalone/*/ | wc -l`
prints after this task (11), written as a word.

Commands: `uv run pytest examples/standalone/hermetic_router -q --no-header > /tmp/functualize-t7.log 2>&1` → all pass; `uv run ruff check examples/ && uv run ruff format --check examples/`.

Gates:

```bash
rg -c "fallback=\"human_review\"" examples/standalone/hermetic_router/router.py
```
now: `0` · after: `1`

```bash
rg -c "effecting=True" examples/standalone/hermetic_router
```
now: `0` · after: `0` (invariant — AC-14)

```bash
rg -c "^(import|from) (httpx|openai|anthropic|urllib|functualize_ai|functualize_decision_jev)" examples/standalone/hermetic_router
```
now: `0` · after: `0` (invariant — AC-15)

Closed when: gates hold, the example's tests pass, five checks clean. Commit:
`docs(examples): add the hermetic router reference workflow`.

### [ ] T8 — guards: no provider, Phase 1 unchanged, no new primitive

*Files:* `tests/integration/test_decision_fallback_e2e.py` (new)

Depends on T1–T6. Disjoint from T7 (same wave).

Tests (AC-5, AC-11, AC-12, AC-13, AC-16):
- **AC-5**: with the Jev plugin hidden exactly as
  `tests/integration/test_decision_gate_e2e.py::test_without_the_plugin_the_gate_blocks_and_core_never_loads_it`
  hides it (monkeypatching `functualize._primitives.entry_points.entry_points`
  and the loader's), a workflow whose router declares `fallback="human_review"`
  walks to the `human_review` branch; `decision_record` reads
  `decided_by == "fallback"` and a `reason` containing `install functualize-decision-jev`;
  rungs are `[("strategy:decision", "unavailable"), ("strategy:resolve", "accepted")]`.
- **AC-11**: a decision gate **without** fallback, weak proposal (`returns`
  0.54 vs 0.46) → `RunStatus.BLOCKED`, `blocked_reason` contains
  `decision: jev/jev-1.13-free proposed 'returns' at 0.54 (margin 0.08); workflow requires >= 0.70, margin >= 0.10`
  exactly as Phase 1's `test_a_weak_proposal_blocks_for_a_person_and_says_why`
  asserts, and the first candidate's source is `strategy:decision` with
  outcome `failed`; that candidate now carries evidence with
  `verdict == "below_threshold"` (Phase 1 gates gain evidence, nothing else).
  Reuse that file's `FakeTransport`/`_proposes` shape (copy it; do not import
  from another test module).
- **AC-12**: `graph_digest` differs for two declarations differing only in
  `fallback`.
- **AC-13**: `set(EvaluationOutcome)` has the five members `accepted invalid
  failed unavailable not_reached`; `_VALID_GATE_STRATEGIES ==
  {"resolve","prompt","ai_inbound","ai_outbound","decision"}`;
  `set(STRATEGY_PROVIDERS) == _VALID_GATE_STRATEGIES`; `CORE_STRATEGIES ==
  {"resolve","prompt"}`; `WalkOutcome`'s members equal those at `ef1939d`
  (read them once at authoring of the test and pin the list literally).
- **AC-16**: no file under `plugins/domains/functualize-decision-jev/src` differs
  from `ef1939d` — assert with
  `subprocess.run(["git", "diff", "--quiet", "ef1939d", "--", "plugins/domains/functualize-decision-jev/src"])`
  returning 0 (skip if `git` is unavailable).

Commands: `uv run pytest tests/integration/test_decision_fallback_e2e.py tests/integration/test_decision_gate_e2e.py tests/plugins/test_jev_wire.py tests/plugins/test_jev_decision_provider.py -q --no-header > /tmp/functualize-t8.log 2>&1` → all pass.

Gates:

```bash
rg -c "functualize_decision_jev" src
```
now: `0` · after: `0` (invariant — core never imports the provider)

Closed when: gate holds, pytest passes, five checks clean. Commit:
`test(integration): guard the router's fallback and the unchanged primitives`.

## Wave 5 — the durable record

### [ ] T9 — documentation and the durable half

*Files:* `docs/guides/workflows.md`, `contributor/adr/030-decisions-are-candidates-not-authority.md`,
`contributor/reference/runtime-persistence-data-model.md`,
`contributor/architecture/codemaps/modules.md`,
`contributor/architecture/codemaps/data-flow.md`, `CHANGELOG.md`, `.spec/STATUS.md`

Depends on T1–T8 (documents what exists).

- `docs/guides/workflows.md` → *Decision gates*: a subsection **Fallback and
  the decision record** — `ChoiceDecision(fallback=...)`, why a field default
  is refused (it would bypass the decision), the `decision → resolve` ladder,
  evidence on the decision rung (list the C-3 keys in one sentence), and
  `decision_record(store, scope_id, gate)` with a short example; link to
  `examples/standalone/hermetic_router/`. Say plainly: two runs on the same
  input can route differently; the records make that visible, they do not
  prevent it.
- ADR-030: add `## Addendum — fallback and evidence (2026-10)` recording D-1…D-4
  as answered, the rejected alternatives A/B/C from `plan.md`, and that the
  fallback is taken by the existing `resolve` rung (no new primitive).
- `runtime-persistence-data-model.md` §2.4: `input_candidates` row gains
  `evidence JSON` (nullable; opaque, so JSON per §3).
- `codemaps/modules.md` `_gate/` paragraph: "Eight modules" → "Nine modules",
  add `decision_evidence.py` (the C-3 builder; never consulted by the rule) and
  `RungEvidence` in `_context.py`. `codemaps/data-flow.md` §5: add the
  `DECISION` rung, the fallback ladder, and that every rung is recorded as a
  candidate (with evidence for `decision`).
- `CHANGELOG.md` `[Unreleased]`: `### Added — hermetic router: a declared
  fallback and the decision as evidence` (hand-written prose, not generated).
- `.spec/STATUS.md` → *Decision gates*: a **Hermetic router — delivered**
  paragraph (fallback, evidence, `decision_record`, the example) and the open
  items that remain (monetary cost → Phase 3; evidence's SQL home → FUN-18/21;
  exact margin comparison unchanged). Self-contained — no reference to
  `.spec/features/`.

Commands: `uv run pytest tests/test_contributor_docs.py -q --no-header > /tmp/functualize-t9.log 2>&1` → passes.

Gates:

```bash
rg -c "fallback=" docs/guides/workflows.md
```
now: `0` · after: `2`

```bash
rg -c "evidence JSON" contributor/reference/runtime-persistence-data-model.md
```
now: `0` · after: `1`

```bash
rg -c "^## Addendum" contributor/adr/030-decisions-are-candidates-not-authority.md
```
now: `0` · after: `1`

```bash
rg -c "decision_evidence.py" contributor/architecture/codemaps/modules.md
```
now: `0` · after: `1`

(The first gate's `2`: one in the code example, one in the prose naming the
keyword. Write it so.)

Closed when: gates as `after:`, the doc test passes. Commit:
`docs(workflow): document decision fallbacks and the decision record`.

## Wave 6 — verification checkpoint

### [ ] T10 — prove reachability, run every check, push the feature-bearing branch

*Files:* none changed except `tasks.md` ticks (and fixes, each in its own commit, if a check fails).

1. Five checks over the whole tree: `uv run ruff check src/ tests/ plugins/ examples/`,
   `uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`,
   `uv run lint-imports`, and the **wave tier**:
   `uv run pytest -n auto -q --no-header tests/gate tests/engine tests/workflow tests/primitives tests/types tests/integration tests/plugins tests/spec examples/standalone/hermetic_router > /tmp/functualize-t10.log 2>&1`
   (bounded with `timeout 570`; if it exceeds that, split it per directory).
2. **Sabotage, one at a time** (all work committed first; after each, `git checkout -- <file>`):
   - `_gate/_registry.py`: pass `evidence=None` instead of `sink.value` on the
     accepted rung → `examples/standalone/hermetic_router/tests/test_router.py`
     AC-6 test fails.
   - `_gate/_registry.py`: delete the fallback seeding → AC-3 test fails.
   - `_primitives/gate_requests.py`: drop the `"evidence"` write → AC-6 fails.
   - `_engine/gate_service.py`: return the Phase 1 ladder for fallback gates →
     AC-3 fails (the walk blocks at the router, not at `review`).
   - `app/_decision_record.py`: map `strategy:resolve` to `"person"` → AC-3/AC-5 fail.
   Record each (file, test that failed) in the commit body of the tick commit.
3. Walk every AC-1…AC-16 in `spec.md` against a named passing test; list them
   in the tick commit body.
4. Push: `git push -u origin sdd/hermetic-router` and dispatch the tip tier
   with the PR's CI (do **not** wait on it in the same turn; read its verdict in
   a later turn). `spec-artifacts-cleared` is expected red until T11.

Closed when: every check is green locally, every sabotage failed its named
test, the AC sweep is complete, and the push succeeded. Commit:
`test(spec): tick the hermetic router verification checkpoint`.

## Wave 7 — clearing

### [ ] T11 — the deletion-only tip (second push)

*Files:* `.spec/features/hermetic-router/` (deleted)

Only after the pull request's CI for T10's head is green, including all three
`test-full` legs. The durable half already migrated in T9.

```
git rm -r .spec/features/hermetic-router
git commit -m "chore(spec): clear the hermetic-router artifacts"
git push
```

The commit must be **deletion-only** under `.spec/features/` (no other path),
so CI skips revalidation and runs the artifact checks. Do not merge — that is
the member's.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1", "T2"] },
    { "id": 1, "tasks": ["T3", "T5"] },
    { "id": 2, "tasks": ["T4"] },
    { "id": 3, "tasks": ["T6"] },
    { "id": 4, "tasks": ["T7", "T8"] },
    { "id": 5, "tasks": ["T9"] },
    { "id": 6, "tasks": ["T10"] },
    { "id": 7, "tasks": ["T11"] }
  ]
}
```

Wave notes:
- **Wave 0.** T1 (`_types/decision.py`, `_types/workflow.py`) and T2
  (`_types/gate_resolution.py`, `_primitives/gate_requests.py`,
  `app/_workflow_resume.py`) touch disjoint files; neither imports the other's
  new symbol.
- **Wave 1.** T3 (`_gate/`) needs T1's `fallback` and T2's `evidence`; T5
  (`_engine/gate_service.py`) needs T1 only. Disjoint files; `_engine` and
  `_gate` never import each other.
- **Wave 2.** T4 consumes T3's sink and removes the markers T2/T3 placed, so it
  follows both. It touches `_registry.py` and `gate_requests.py` only to delete
  a marker comment.
- **Wave 3.** T6 reads the evidence shape T4 writes.
- **Wave 4.** T7 (examples) and T8 (one new test file) are disjoint and both
  need the whole stack.
- **Waves 5–7.** Docs, then the checkpoint, then the deletion-only tip — each
  alone, in that order.
