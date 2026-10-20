# Gate interactions, evidence, and the transactional outbox

**Status:** refined against `origin/master` @ `91947bb4` (2026-10-20). Supersedes the
pre-loaded scaffold.

**Authority.** Shape Intent *Gate Interactions, Evidence, and the Transactional Outbox*,
Confluence `SD` page 20086800 **v2**, `Authority: Approved` (owner approval 2026-10-19).
Its §7 *binding* names are used verbatim below; every §7 *provisional* item is settled in
§5 of this file. Dependency: Shape Intent *Store Substrate and Relational SQLite Runtime
Provider*, page 12583004 v3 (`durable_outbox` is a profile fact: SQLite `True`, documents
`False`).

## 1. Goal

A human's answer and the effect it triggers cannot be separated by a crash, and the
answer's history — who answered, through which channel, against which schema, with what
evidence, and which candidates the decision considered — is recoverable from the selected
`RuntimeStore` by request id.

## 2. Why

A gate resolution that commits without its side effect, or a side effect that fires without
its commit, are the two halves of the same bug. The outbox makes them one commit: the
transition and the *intent* to deliver commit together, and delivery happens afterwards,
at least once, with the receiver deduplicating on a stable key.

Today (master `91947bb4`):

- `func builtin workflow answer` and `resume`, and the MCP `answer_gate`,
  `get_gate_draft` and `resume_workflow` tools, always address the legacy `ScopeStore`
  over `scopes.json` (`_cli/builtins.py:1128-1132`, `functualize_mcp/_workflow_tools.py:168-174`)
  — even when `runtime_store.url` selects SQLite, whose walk never reads that document.
  Only `--wf-input` reaches the relational store (`_workflow_control._record_port_input`).
- A candidate records `source`, its evaluation and its payload. Resolver class, channel,
  schema identity/version, payload hash, supersession, causal run identity, evidence
  references and the decision's policy and observed candidate ids are not recorded.
- `EffectWriter` records an outbox row on SQLite (`_run_sql.py:299-343`); nothing
  claims, delivers or acknowledges it, and nothing appends one.

## 3. Behaviour

### 3.1 First-class requests and candidates (binding: `InputRequest`, `GateCandidate`)

- An `InputRequest` additionally carries the causal identity of the walk that opened it:
  `run_id` (the workflow run executing when the gate opened, `None` when no run was
  recorded), `scope_id` (the workflow), `position` (the step — the gate node) and
  `generation` (the walk attempt: each resume claims a new generation).
- A `GateCandidate` additionally carries `resolver_class`, `channel`, `schema_id`,
  `schema_version`, `payload_hash`, `supersedes_candidate_id` and `evidence_refs`.
  Candidates stay append-only; an invalid submission is a candidate (D-5).
- `resolver_class` is one of `human`, `agent`, `program`, `policy`:
  surfaces map `cli`/`tui` → `human`, `mcp` → `agent`, anything else → `program`;
  ladder rungs map `prompt` → `human`, `decision`/`ai_inbound` → `agent`, anything else →
  `policy`. `channel` is the surface name, or the strategy name for a rung.
- `schema_id` is the gate model's `module.QualName`; `schema_version` is
  `sha256:<hex>` of its canonical JSON schema. `payload_hash` is `sha256:<hex>` of the
  canonical JSON payload.
- A surface submission on a request that already holds a non-accepted candidate
  supersedes the newest such candidate (`supersedes_candidate_id`). Nothing is rewritten.

### 3.2 Decisions (binding: `GateResolution`, policy identity/version, observed ids)

- Every acceptance records one `GateDecision` in the same unit as the accepted candidate:
  `request_id`, `accepted_id`, `policy_id`, `policy_version`, `observed_candidate_ids`
  (every candidate on the request at that moment, accepted one included, in ordinal
  order) and `decided_at`.
- Policies: a surface answer is decided by `gate.validate`, versioned by the gate's
  `schema_version`; a ladder answer by `gate.ladder`, versioned by `sha256:<hex>` of the
  ladder's strategy list.
- `GateResolution.decision` carries the recorded decision; it is read, never recomputed.

### 3.3 Evidence by reference and digest (AC-4)

- A submission may carry `EvidenceRef(ref, digest, media_type=None, size=None)` values.
  `ref` is a URI-like string naming bytes stored elsewhere; `digest` is
  `sha256:<64 hex>`. The recorder refuses a missing digest, a malformed digest, an empty
  ref, and a `data:` ref (inline bytes) with `ValueError`.
- SQLite stores each reference as an `artifact_refs` row (`kind='gate-evidence'`) linked
  to its candidate; no evidence byte is written to any runtime row. The document backend
  stores the `{ref, digest}` pairs on the candidate entry.
- A strategy rung's own `CandidateEvaluation.evidence` mapping (the decision rung's
  `decision-evidence/1`) is not attached evidence and is unchanged.

### 3.4 The transactional outbox (AC-1, AC-2, AC-3)

- On a store whose profile declares `durable_outbox=True`, every acceptance appends one
  effect intent — topic `gate.accepted`, idempotency key `gate.accepted:<request_id>`,
  payload `{request_id, scope_id, gate, accepted_id, policy_id, policy_version}` — in the
  **same** transaction unit as the accepted candidate and its decision.
- A store declaring `durable_outbox=False` is never asked to record an intent and runs no
  dispatcher.
- Delivery is **at-least-once with consumer dedup**. A dispatcher claims due intents for
  the topics it has receivers for, hands each to its receiver, then acknowledges it
  (`published`) or records the failure and a retry time (`pending`, `last_error`,
  `available_at`). A receiver that raises is retried; a claim that is never acknowledged
  (the process died) becomes claimable again once its claim lease expires. The receiver
  deduplicates on `idempotency_key`; the framework never promises a single delivery.
- An intent committed by a process that dies before delivering it is delivered by the
  next process that starts with a receiver for its topic.

### 3.5 Answer surfaces on the selected `RuntimeStore` (AC-6)

- `func builtin workflow answer` / `resume`, the MCP `answer_gate` / `get_gate_draft` /
  `resume_workflow` tools and `--wf-input` address the **selected** store through
  `selected_workflow_store(app)` — the same door `list`/`show`/`cancel`/`reclaim` already
  use. On the document store that is the scope document; on a relational store it is the
  `RuntimeStore` port, and nothing reads `scopes.json`.
- `answer` records; `resume` advances. Existing names, `--input`, `--format json`, and
  exit codes are unchanged.
- On a relational store the draft *is* the newest non-accepted candidate's payload:
  `--set`/`--input` merge into it (or `--replace`/`--clear` start fresh) and the
  submission is recorded as the next candidate, superseding it. `--no-commit` is refused
  with `draft_requires_commit` because a relational store records drafts only as
  submissions. `--reopen` supersedes the accepted request (`accepted → cancelled`, D-4)
  and opens a new one at the same generation, refused once the walk has passed the gate,
  exactly as on the document store.
- `--retry-epilogue` on a relational store is refused with `epilogue_retry_unsupported`
  (the port has no step deletion); it is unchanged on the document store.

### 3.6 Capability refusal (AC-5)

- Registering an `EffectReceiver` declares that this configuration needs
  `durable_outbox=True`. Boot step 6.5 refuses a selected store whose profile lacks it,
  with `RuntimeStoreCapabilityError` naming the store, `durable_outbox`, the
  `runtime_store.url` setting and the receivers' topics. Nothing is degraded.
- A receiver may only be registered before boot selects the store; later registration
  is refused, as for runtime store factories.

## 4. Acceptance criteria

Gates, run at authoring time; each task's file scope is the gate's hit set.

1. **AC-1** — A gate resolution and its outbox row commit in ONE transaction: on SQLite
   the accepted candidate, its decision and the `gate.accepted` intent are one batch; a
   unit that raises before commit leaves none of the three.
2. **AC-2** — Delivery is AT-LEAST-ONCE with consumer dedup. The documentation says so in
   those words — no at-most-once claim about the outbox anywhere (`rg -i "at-most-once"`
   over `docs/ contributor/ src/` names no outbox).
3. **AC-3** — An undelivered effect survives a process kill and is delivered on the next
   start: a child process answers a gate and dies (`os._exit`) after commit and before
   dispatch; a fresh app on the same SQLite file delivers the intent once to its receiver,
   and a forced redelivery is deduplicated by the receiver's key.
4. **AC-4** — Evidence attached to a gate answer is stored by reference and digest, never
   as bytes in a runtime row; a `data:` ref and a missing digest are refused.
5. **AC-5** — A store declaring `durable_outbox=False` does not run the outbox tier and
   cannot be selected by a feature needing one: documents + no receiver builds no
   dispatcher; documents + a registered receiver refuses boot naming `durable_outbox`.
6. **AC-6** — With SQLite selected, `func builtin workflow answer … --input … --format
   json` followed by `resume` answers and advances a blocked walk, and the legacy scope
   document (`ScopeStore` over the app's substrate) holds no record of that scope.
7. **AC-7** — For a request id, the selected store returns the request with its causal
   identity, its append-only candidates with resolver class/channel, schema
   identity/version, payload hash, validation outcome, supersession and evidence refs,
   and the decision with policy identity/version and exact observed candidate ids — on
   SQLite through `InputReader` alone, without opening `scopes.json`.

## 5. Settled provisional items (shape §7)

| Item | Settled as |
|---|---|
| CLI JSON keys | `resolution` gains `accepted_id`, `causal{run_id,workflow_id,step,generation}`, `decision{policy_id,policy_version,observed_candidate_ids,accepted_id,decided_at}`; each candidate gains `resolver_class`, `channel`, `schema{id,version}`, `payload_hash`, `supersedes_candidate_id`, `evidence[{ref,digest}]` |
| Dispatcher deployment mode | In-process and synchronous, owned by `_app`: one drain at the end of boot, one after each answer-surface commit, one after `resume`. No thread, no separate worker — so shutdown has nothing to join and a kill loses only an unacknowledged claim, which the claim lease returns |
| Retry interval | 5 s × 2^(attempts−1), capped at 15 min; claim lease 60 s; at most 50 intents per drain round |
| Config key | None new. The requirement is declared by registering a receiver; the refusal names `runtime_store.url` as the setting to change |
| Exact error text | The existing `RuntimeStoreCapabilityError` sentence, `because` naming the receiver topics |
| Public inspection façade | None. The read seam stays `InputReader.request` / `candidates_for` / `decision`; `answer --show --format json` renders it |
| Decision storage | A separate append-only `input_decisions` table on SQLite; the gate record's `decision` entry on documents |

## 6. Out of scope

- Slack screens, AG-UI events, a network SQL provider, artifact byte storage, migration
  of the document backend's storage layout (shape §8).
- The input recorder and gate deposit ownership (D-2; shipped on master via the
  gate-resolution branch). Scaffold task 1.1 is dropped for that reason.
- `Notify` delivery semantics: `Notify` keeps its record-first, at-most-once rule. Its
  documentation stops calling that rule "the outbox" (AC-2).
- Moving `deposited_answer` off the port (ruling R-1) — unchanged.
