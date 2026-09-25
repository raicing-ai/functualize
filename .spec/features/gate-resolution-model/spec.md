# FUN-4 — Gate resolution requests, candidates and evaluations

**Status:** Specify + Plan drafted 2026-09-25 against `origin/master` @ `03fbb64`.
**Awaiting member confirmation** (`/agentic-specify` step 6, `/agentic-plan` step 11).
Execute is not authorised until the decisions in §8 are answered.

## 1. Problem

Gate resolution produces an answer, but the answer is not a record: it is a field inside
the legacy scopes document. Every fact below was checked by running a command at `03fbb64`.

- **The legacy scopes document** is `.functualize/scopes.json`, written only through
  `ScopeStore` (`src/functualize/_primitives/scope_store.py`, class 930 lines by AST). A
  gate lives at `envelope["scopes"][<scope_id>]["gates"][<gate_name>]` as a dict of
  `model`, `input_schema`, `tools`, `payload`, `blocked_at` and optionally `draft`,
  `source` and `consumed_at` (`frontier.py:445` `put_gate`, `scope_store.py:721-731`,
  `document_store.py:835-870, 988-1004`).
- **A request has no identity.** It is a dictionary key. The FUN-17 port value
  `InputRequest` (`_types/persistence.py:387`) has no id field, and the document backend
  makes one up as `f"{scope_id}::{gate_name}"`. It parses that string back with
  `partition("::")` (`document_store.py:996`). So a second question at the same gate
  cannot be told apart from the first one.
- **Candidates are not modelled.** `GateRegistry.resolve_gate` (`_gate/_registry.py:97-239`)
  walks a strategy ladder and returns the first model that succeeds. Every other rung
  is discarded. The rungs that failed survive only as one joined string
  (`GateResolutionError.last_error`), which the walker copies into
  `WalkReport.blocked_reason` (`workflow_walker.py:759-768`). Nothing records which rung
  answered.
- **The answer is overwritten, not appended.** `ScopeStore.deposit_gate_payload`
  replaces `payload`. It has **3** production call sites (`rg -n "deposit_gate_payload\("
  src plugins`): `workflow_walker.py:758`, `app/_workflow_answer.py:228` and
  `app/_workflow_resume.py:101`.
  - Every production *answer* goes through `answer_gate`, and `answer_gate` refuses an
    already-answered gate. Its callers are CLI `workflow answer` (`_cli/builtins.py:1455`),
    `resume --input` via `resume_scope` (`app/_workflow_control.py:328`), the
    `--wf-answer` flags (`app/adapters/workflow_flags.py:428`) and MCP `answer_gate`
    (`_workflow_tools.py:287`).
  - The public `functualize.app.utils.deposit_gate_input` does **not** refuse, so a
    second call silently replaces the first. It has **0** production callers; only
    tests call it. The comment at `_cli/builtins.py:1095` still says the CLI and MCP
    `resume_gate` use it, and that is stale.
  - `contributor/reference/runtime-persistence-data-model.md` §2.4 names the overwrite
    defect.
- **Consumption is recorded on a path nobody calls.** Only `ResumeWorkflow` writes
  `consumed_at` (`document_store.py:850-870`). `ResumeWorkflow` has **0** production
  callers (`rg -n "ResumeWorkflow|\.resumed\(" src` hits only the recorder, the port and
  the document store). The walker reads `payload` and marks nothing
  (`frontier.py:457-460`).
- **The walker writes gates around the port.** Since FUN-17 the walk *claims* through
  `RuntimeStore.transaction()` (`frontier.py:213`). Blocking at a gate and depositing an
  answer still go straight to `ScopeStore` (`frontier.py:445`, `workflow_walker.py:758`).
  `SuspendAtGate` exists but nothing issues it. It also has no `model` or `tools` field,
  so issuing it as it stands would lose data MCP depends on.

## 2. Users

- **A workflow author.** Declares `Gate(awaits=Model, strategy=…)`. Needs a blocked walk
  to say why it blocked, and each rung's reason to stay attached to the right rung.
- **An operator or agent answering a gate** through the CLI (`func builtin workflow answer`,
  `workflow resume --input`, `--wf-answer`), MCP (`answer_gate`, `resume_workflow`) or the
  app API (`answer_gate`, `deposit_gate_input`). Needs their answer
  kept, attributed to them, and not silently replaced.
- **Stage 3 consumers.** FUN-6 (the Jev experiment) and the interactive Slack gate
  resolver need a stable **request identity** to put in a message and to answer against
  later, plus a readable history of who proposed what and how it was judged.

## 3. Vocabulary

| Term | Meaning |
|---|---|
| **Resolution request** | A gate's question to the outside world. It carries its own minted identity. It is the FUN-17 `InputRequest` given an id, not a new parallel type. |
| **Candidate** | One complete proposed answer to one request, from one source. It is either a strategy rung (`strategy:<name>`) or a submission from a surface (`cli`, `mcp`, `api`, or `<surface>:<actor>`). A **draft** is not a candidate: it is partial input that has not been submitted. |
| **Evaluation** | The judgement made on one candidate at the moment it is recorded: its outcome, plus its detail or validation errors. It is written once and never rewritten. |
| **Resolution** | A request together with its candidates in order, and which one (if any) was accepted. |
| **Interaction evidence** | The resolution record together with each candidate's provenance (source, time submitted). Attachments stored by reference and digest are **not** part of this ticket (FUN-21 AC4). |

Name collision to avoid: `app/_workflow_answer.resolve_gate` already returns an
`ambiguous_gate` envelope with a `candidates` key. That key means *(scope, gate)
addresses*. New read output nests under `resolution` so the two never share a key
(§6).

## 4. Behaviour

### 4.1 Request lifecycle (statuses as declared on `master`; FUN-18 owns the transition table)

The five statuses are the ones `InputRequest.status` already declares: `open`,
`accepted`, `consumed`, `cancelled`, `expired`. This ticket adds none. It uses these
transitions:

| From | To | Trigger (owner) |
|---|---|---|
| absent | `open` | the walk reaches a gate with no live request for (scope, gate) — **R1** |
| `open` | `accepted` | a candidate evaluated `accepted` is recorded — **R3/R4** |
| `accepted` | `consumed` | the walk walks past the gate on that answer — **R5** |
| `accepted` | `cancelled` | `answer --reopen` supersedes the request — **R7** |
| `open` | `cancelled` / `expired` | *no producer in this ticket* (scope cancel cascade and timeouts are FUN-18 / later) |

`accepted → cancelled` is **not** in the diagram FUN-18 inherited
(`runtime-persistence-data-model.md` §1.4). It is a coordination item (§8, D-4).

### 4.2 Rules

- **R1 — One live request per gate.** A request is *live* while it is `open` or `accepted`.
  There is at most one live request per (scope, gate). The walk opens a new request only
  when no live or consumed one exists. So a resume re-reaching an unanswered gate
  **reuses** the request, and its `request_id` and `created_at` stay stable across
  claims and generations. This is stricter than "one OPEN per (scope, gate,
  generation)", and it implies that one. `blocked_at` no longer resets on re-block.
- **R2 — Replay.** When the walk reaches a gate whose live or consumed request has an
  accepted candidate, the walk feeds that candidate's payload to the node and evaluates
  nothing. A gate inside a loop keeps today's behaviour: it replays the same answer on
  every iteration. Per-iteration gate identity is out of scope.
- **R3 — The ladder enumerates.** When the walk reaches an `open` request with no
  accepted candidate and the gate has a strategy list (`_gate_strategy_list`, unchanged),
  every rung in the expanded list becomes one candidate, in ladder order:
  - `accepted` — the first rung whose resolver returns a model. Its payload is
    `model.model_dump()`.
  - `failed` — the resolver raised. The detail is the exception text, the same text
    each rung contributes to `blocked_reason` today.
  - `unavailable` — the strategy name is not registered. The detail is the install hint
    from `missing_strategy_hint`.
  - `not_reached` — every rung after the accepted one.

  The two loud wiring errors are unchanged: a preset that names an unregistered
  strategy, and a single explicitly-named unregistered strategy. Both still raise
  `ValueError` and record nothing.
  Each time the ladder runs against the same open request, it **appends** a new block of
  candidates. `ordinal` keeps counting and never restarts. So "failed until
  functualize-ai was installed, then accepted" can be read from the record.
- **R4 — Submissions from surfaces.** A complete submission against an `open` request is
  validated against the gate model once and recorded as one candidate.
  - Valid → `accepted` (payload = the validated `model_dump()`). The request becomes
    `accepted`.
  - Invalid → `invalid`, with the validation errors as `{field, message}` pairs. The
    request stays `open`. The surface's error response is unchanged
    (`validation_error`). Drafts that are not yet complete create no candidate,
    exactly as today.
- **R5 — Consumption has one writer.** The walk records `accepted → consumed` when it
  walks past the gate on the accepted candidate, both for inline ladder success and for
  replay after resume. A replay over an already-consumed request writes nothing.
  `ResumeWorkflow` stops writing `consumed_at` (§1: it has no production caller).
- **R6 — Refusal is not a candidate.** A submission against a request that is not `open`
  is refused and **nothing is recorded**:
  - `accepted` / `consumed` → `gate_already_answered`. This is new on the public
    `deposit_gate_input`, which today overwrites.
  - `cancelled` / `expired` → `gate_not_found`.

  The status check and the append happen under one lock or unit. So of two concurrent
  submissions, exactly one is accepted and the other gets `gate_already_answered`.
- **R7 — Reopen supersedes, never rewrites.** `answer --reopen` on an `accepted`,
  unconsumed request:
  1. moves that request to `cancelled`, recording reason `reopened`;
  2. opens a **new** request, with a new id, for the same gate;
  3. seeds the new request's draft with the old accepted payload (today's `reopen_gate`
     outcome).

  The old request keeps its candidates and their evaluations. The refusal once the walk
  has passed the gate (`gate_already_consumed`) keeps its current graph-based check.
- **R8 — Recorded, not recomputed.** `blocked_reason` and every resolution read are
  built from the recorded evaluations. A read never calls a resolver, never validates a
  payload and never loads the gate model. The `blocked_reason` text for a
  ladder-exhausted gate stays byte-identical to today's (unregistered hints first, then
  `"<rung>: <error>"`, joined by `"; "`).
- **R9 — Legacy records.** A gate record written before this change has no `request_id`.
  It is read as a request with id `"<scope_id>::<gate_name>"` (the FUN-17 convention)
  and **zero** recorded candidates. Its status is derived exactly as
  `document_store._input_request` derives it today. Nothing is synthesised on read. The
  first write to such a record (a submission, a consume or a reopen) stamps a minted
  `request_id`.
- **R10 — Attribution.** Every candidate carries a non-empty `source` of at most 128
  characters. CLI surfaces pass `cli`, MCP passes `mcp`, a direct app-API call without
  one records `api`, and rungs record `strategy:<name>`.

### 4.3 Out of scope (named so nothing absorbs it)

- Durable storage of requests, candidates and evaluations outside the scopes document:
  **FUN-18** (tables, migrations, the `InputRequest` legal-transition table,
  `IllegalTransition`), **FUN-19** (the SQLite provider) and **FUN-21** (the durable
  interaction/evidence slice).
- The outbox for effects triggered by an answer, evidence stored by reference and
  digest, and redelivery: **FUN-21**.
- Moving the answer surfaces (`app/_workflow_answer.py`, `app/_workflow_resume.py`) from
  `ScopeStore` to the selected `RuntimeStore`. The surfaces hold only a `ScopeStore`
  today (`_cli/builtins.py:1127-1142`,
  `plugins/adapters/functualize-mcp/.../_workflow_tools.py:146`). That move is a
  precondition of AC-3 and belongs to FUN-21 (§8, D-2).
- Job-level gates (`Invoke(force_gate=…)`, `_engine/capabilities/invoke.py:415`). These
  have no workflow scope and no request. They keep calling `resolve_gate`, which
  behaves as it does today.
- Cancel/expiry cascades from scope cancellation, per-iteration gates in loops, and new
  public symbols (§8, Q-2).

## 5. Acceptance criteria and what can close on this ticket

| AC (Jira) | Closes here? | Evidence that closes it |
|---|---|---|
| **AC-1** A resolution request is a modelled object with its own identity, not a field | **Yes.** | The walker opens requests through `RuntimeStore.transaction()` with a minted `request_id`. The id is stable across resumes (R1). A test reaches it through `app.execute()`, and sabotage (dropping the id mint) fails that test. |
| **AC-2** Candidates modelled, enumerated, evaluated; evaluation recorded, not recomputed | **Yes on behaviour; its storage location is disclosed as transitional.** | R3, R4, R8 through the public entry points (`app.execute`, `answer_gate`, `deposit_gate_input`, MCP `answer_gate`). The read-without-recompute gate makes the resolver and the model raise on read, and the read must still succeed. The records sit inside `scopes.json` behind `# TRANSITIONAL(FUN-21)`. Jira's persistence clause stops **the ticket** closing while that is true, but the behaviour is complete. |
| **AC-3** Interaction evidence durable and readable independently of the scopes document | **No.** It cannot close on this ticket's work. | It needs FUN-18's tables, FUN-19's provider and FUN-21's slice. FUN-21 must also move the answer surfaces onto the selected store. This ticket hands over the model, the port contract (`contracts.md` §2) and the one module, `_primitives/gate_requests.py`, that FUN-21 replaces. |

**The ticket stays open after this branch merges.** The FUN-4 Jira issue moves to Done only
when FUN-21 closes AC-3 (§8, D-1).

## 6. Observable surface

- `gate_draft(...)` and `answer_gate(...)` results gain a key `resolution`:
  `{"request_id", "request_status", "candidates": [{"candidate_id", "ordinal", "source",
  "submitted_at", "outcome", "detail", "errors"}]}`. Payloads are **not** echoed here,
  because the answer is already in the gate record and MCP output is size-sensitive.
- `deposit_gate_input(...)` gains `gate_already_answered`. A successful result gains
  `request_id`.
- `WalkReport.blocked_reason`: text unchanged (R8), source changed.
- No symbol is added to or removed from any public `__all__`
  (`tests/test_public_api_surface.py` stays unchanged).

## 7. Premises verified (command → result at `03fbb64`)

| Claim | Command | Result |
|---|---|---|
| 3 production call sites of `deposit_gate_payload` | `rg -n "deposit_gate_payload\(" src plugins` | walker:758, answer:228, resume:101 |
| 34 test call sites of `deposit_gate_payload` in 15 files | `rg -c "deposit_gate_payload\(" tests plugins -g '*.py'` | 15 files, sum 34 |
| `deposit_gate_input` has no production caller | `rg -n "deposit_gate_input" src plugins -g '*.py'` | export, definition, one stale comment |
| `ResumeWorkflow` has no production caller | `rg -n "ResumeWorkflow\|\.resumed\(" src` | recorder, port, document store only |
| The engine reaches `ScopeStore` gate methods at 3 sites | `rg -c '_store\.(put_gate\|get_gate\|deposit_gate_payload)\(' src/functualize/_engine/` | walker 1, frontier 2 |
| Class sizes | AST walk | `WorkflowWalker` 803, `ScopeStore` 930, `_DocumentTransaction` 442, `FrontierWalk` 358, `GateRegistry` 248 |
| `_engine` and `_gate` are independent peers | `pyproject.toml` contract "Peer layers are independent" | both listed |

## 8. Decisions and open questions for the member

These need an answer before Execute. The designer's recommendation is given for each.

| # | Question | Recommendation |
|---|---|---|
| **D-1** | May this branch **merge** while AC-3 is open, with the FUN-4 Jira issue kept open until FUN-21 lands? | **Yes.** Merge the parallel part once it is green, and record AC-3 as open in `.spec/STATUS.md`. The alternative is to hold the branch open across two more waves, which makes rebasing against FUN-18 worse |
| **D-2** | Boundary with FUN-21: this ticket takes FUN-21's scaffold task 1.1 (input recorder plus wiring requests and candidates into the walker) and the *deposit* half of 2.1. FUN-21 keeps the outbox, evidence stored by reference and digest, redelivery, the durable implementation, **and** moving the answer surfaces onto the selected `RuntimeStore`. | **Accept.** Without the wiring, AC-1 and AC-2 cannot reach `[x]` under *Reachability precedes `[x]`*. FUN-21's `tasks.md` needs refining to match (contracts §7) |
| **D-3** | Keep `ScopeStore.deposit_gate_payload` with 0 production callers for its 34 test call sites, or add a wave that migrates them? | **Keep it.** It is declared in `plan.md` → *Surviving smells* #2 |
| **D-4** | FUN-18's `InputRequest` transition table must admit `accepted → cancelled` (reopen supersedes, R7) | **Accept.** The alternative, `accepted → open`, rewrites a request's history in place |
| **D-5** | Record `invalid` submissions as candidates (R4), which the audit trail needs, rather than dropping them as today | **Record them.** Payloads are already stored for valid answers, so recording invalid ones changes no data-class decision |
| **Q-2** | Export `GateCandidate` and friends publicly now, or when the Slack resolver arrives? | **Later.** A public symbol needs an `examples/` caller and a consumer |
