# Gate interactions, evidence, and the transactional outbox — plan

## Alignment

Shape Intent *Gate Interactions, Evidence, and the Transactional Outbox* (Confluence `SD`
page 20086800, v2, `Authority: Approved`). In scope, in the shape's words: "a gate request
and its candidate set persisted with first-class identities"; "an answer and its
evaluation accepted with resolver class and channel, schema identity and version, payload
hash, validation result, supersession, and causal run/workflow/step/attempt identity";
"the policy identity and version that selected the candidate set, by exact candidate
ids"; "evidence retrievable by reference plus digest, without reading `scopes.json`";
"one commit carries the state transition and the effect to dispatch, and redelivery is
at-least-once with consumer dedup"; "the answer surfaces running on the selected
`RuntimeStore`". Out of scope, in its words: "Slack screens, AG-UI events, a network SQL
provider, artifact byte storage, or FUN-20/FUN-23 migration", and "the existing input
recorder and gate deposit ownership established by earlier work".

## Retrieval passes run

- **zvec-grep** (index built for this worktree, 912 files / 14 412 entities, 1 m 23 s):
  outbox delivery, answer-surface migration, evidence by digest, receiver registration,
  at-most-once wording. Found: the data-model reference's transaction catalogue (dispatch
  and acknowledge rows unbuilt); ADR-029 *Negative* naming this slice's obligations;
  ADR-033's operator-slice precedent (`selected_workflow_store`); `Notify` and
  `contributor/architecture/run-model/10-graph-semantics.md:115` calling an at-most-once
  rule "the outbox" — a direct conflict with AC-2.
- **serena** `find_referencing_symbols(EffectWriter)`: two implementations
  (`_DocumentEffectWriter`, `SqlEffectWriter`) and the port; zero callers of `append`
  outside tests and conformance.
- **graphify** `get_neighbors(answer_gate)`: callers `resume_scope`, MCP `_answer_gate`,
  `workflow_flags._record`, CLI `workflow_answer`.
- **rg** for every count: two `InputWriter` implementations plus the frontier's
  delegate; `RuntimeStore.transaction` implemented by the two stores and
  `tests/substrate_probe/fakes.py`.

## BEFORE

```
 _cli/builtins.py ─────────── answer / resume ──────────┐
 functualize_mcp/_workflow_tools.py ── answer_gate ─────┤ legacy ScopeStore(app.substrate)
 app/adapters/workflow_flags.py ── --wf-input ──┐       │      (always, even on SQLite)
                                                │       ▼
 [app]  app/_workflow_answer.py ── answer_gate ─┼──► [_primitives] gate_requests ─► scopes.json
        app/_workflow_control.py               │
          resume_scope ── answer_gate ──────────┘ (document only)
          _record_port_input ──────────────────────► RuntimeStore.transaction().inputs.append
                                                        (relational only; no provenance)
 [_engine] gate_service ─► frontier ─► RuntimeStore.transaction()
                                         ├ workflows.suspend(SuspendAtGate)
                                         └ inputs.append(ladder candidates)

 [_types] persistence: InputWriter{append,consume}  EffectWriter{append}
          RuntimeStore{profile,runs,workflows,inputs,transaction,close}
 [plugin] sqlite: SqlEffectWriter ──► outbox table ──► (nothing claims a row)
 [_primitives] document_store: _DocumentEffectWriter ─► NotImplementedError (durable_outbox=False)
 [_app] boot step 6.5: _required_capabilities() == {}  (no feature declares a need)
```

Smells already present, by catalogue name:

- **Divergent change** — `app/_workflow_answer.answer_gate` and
  `_workflow_control._record_port_input` are two implementations of "record an answer",
  one per store kind, differing in validation messages and capabilities.
- **Speculative generality** — `EffectWriter` and the `outbox` table exist with no
  appender and no consumer.
- **Primitive obsession** — a candidate's provenance is one free-text `source` string.
- **Middle man** — `DocumentRuntimeStore` (declared, `TRANSITIONAL(FUN-17/T7)`; untouched).

## AFTER

```
 _cli answer/resume ─┐
 mcp gate tools ─────┼─► selected_workflow_store(app) ─┬─ documents ─► ScopeStore (scopes.json)
 --wf-input ─────────┘                                 └─ relational ─► RuntimeStore port
                         │
                         ▼
 [app] _workflow_answer.answer_gate / gate_draft / resolve_gate     (one implementation,
       _workflow_control.resume_scope                                 two record seams)
         │ builds values with ─► [_engine] recording.InputRecorder
         │                           submitted · decided · accepted_effect · superseding
         ├─ document seam: gate_requests (candidate + decision on the gate record)
         └─ port seam:     store.transaction(): inputs.append + inputs.decide
                                              + effects.append  (durable_outbox only)
         └─ after commit ─► [_app] effects.drain(app) ─► [_primitives] outbox.OutboxDispatcher

 [_engine] gate_service ─► frontier ─► transaction(): inputs.append(rungs)
                                        + inputs.decide + effects.append (durable_outbox only)

 [_primitives] outbox.OutboxDispatcher(queue: EffectQueue, receivers) ── _types only
       claim ─► receiver.receive(effect) ─► published | failed(retry_at)
 [plugin] sqlite: SqlEffectQueue(outbox) ── implements EffectQueue; store is an OutboxStore
 [_app] impl.register_effect_receiver ─► app._effect_receivers
        boot 6.5: _required_capabilities ─► durable_outbox=True when receivers exist
        boot end: build OutboxDispatcher iff profile.durable_outbox and receivers; drain once
```

Dependency directions and layer crossings: `_primitives/outbox.py` → `_types` only;
`_app` → `_primitives.outbox` (composition root); `app/` → `_app.effects` and
`_engine.recording` (both already permitted — `app/` imports `_engine.recording` today);
the SQLite plugin → `functualize.plugin` and `_types`. No peer layer imports another;
no import-linter contract changes.

### Candidate AFTERs rejected

- **A background dispatcher thread started at boot.** A second thing that runs work
  beside `JobExecutionEngine`; needs a join on shutdown and a policy for daemon death.
  Introduces *temporal coupling* between boot and shutdown with nothing measured to pay
  for it. Rejected for the synchronous drains above.
- **`effects: EffectQueue` on `RuntimeStore` itself.** Forces the document store and
  every fake to grow a member that can only refuse — *refused bequest*. A typed
  `OutboxStore` sub-protocol keeps the capability where the profile says it is.
- **Receivers on the EventBus.** The bus is fire-and-forget and must not control
  lifecycle (AGENTS.md *Event model*); an at-least-once consumer needs a failure signal.

## Design skills consulted

- `python-design-patterns` (in-repo) — separation of concerns, KISS.
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue) — smell names
  above; *Strategy* for the two record seams behind one `answer_gate`.

## Files expected to change

Measured with `wc -l` on `91947bb4`.

| File | Lines | Change |
|---|---|---|
| `src/functualize/_types/gate_resolution.py` | 156 | `EvidenceRef`, `GateDecision`, candidate provenance, topic |
| `src/functualize/_types/persistence.py` | 1028 | request causal ids, `SupersedeRequest`, `EffectIntent`, writer/reader members, `EffectView`, `EffectQueue`, `OutboxStore`, `EffectReceiver` |
| `src/functualize/_types/lifecycle.py` | 244 | D-4 edge; `OUTBOX` machine |
| `src/functualize/_engine/recording/input_recorder.py` | 160 | provenance, evidence validation, decision, intent, supersede |
| `src/functualize/_primitives/gate_requests.py` | 381 | provenance and decision on the gate record |
| `src/functualize/_primitives/document_store.py` | 1376 | `decide`, `supersede`, `decision`; run id on suspend |
| `plugins/.../_schema/0003_gate_interactions.sql` | new | additive revision |
| `plugins/.../_run_sql.py`, `_readers.py`, `_workflow_sql.py` | 343 / 330 / 525 | columns, decisions, evidence rows, supersede |
| `plugins/.../_outbox_sql.py` | new | `SqlEffectQueue` |
| `plugins/.../_runtime_store.py` | 100 | `effects` |
| `src/functualize/_engine/gate_service.py`, `frontier.py` | 192 / 758 | run id, ladder decision + intent |
| `src/functualize/_primitives/outbox.py` | new | `OutboxDispatcher` |
| `src/functualize/_app/effects.py` | new | receiver registry, required capability, dispatcher build, `drain` |
| `src/functualize/_app/impl.py`, `extensions_facade.py`, `boot.py`, `_types/host.py`, `plugin/__init__.py` | — | registration door, both boot paths |
| `src/functualize/app/_workflow_answer.py`, `_workflow_resume.py`, `_workflow_control.py`, `adapters/workflow_flags.py` | 466 / 207 / 899 / 459 | one answer path, two seams |
| `src/functualize/_cli/builtins.py`, `functualize_mcp/_workflow_tools.py` | — | the selected store |

## Risks

- **Two `ScopeStore` objects on the document path.** Unchanged: the document seam keeps
  writing through the same `gate_requests` functions it uses today.
- **`builtins.py` is 3038 lines.** Only the two store look-ups change.
- **Facade line budget** (`tests/test_facade_loc_limits.py`): the registration door is one
  delegating method on `extensions_facade`, the logic in `_app/effects.py`.

## Surviving smells

1. **Divergent change, reduced but not removed** — `answer_gate` keeps one flow with two
   record seams (document gate record vs port). Accepted: the document backend stores the
   draft beside the request and the port does not; one seam per storage shape is the
   *Strategy* answer, and forcing documents through the port would move draft storage in
   a slice that is not about drafts. **Does not need maintainer review** — the shape's §6
   diagram already draws document and SQLite as different shapes.
2. **Middle man** — `DocumentRuntimeStore`, as declared by FUN-17/T7. Untouched here.
3. **Refused capability on relational stores** — `--no-commit` and `--retry-epilogue` are
   refused with named errors instead of being implemented. Accepted: both need storage
   (drafts, step deletion) the port does not have, and a named refusal is the honest
   state; recorded so a later slice can lift it. **Needs maintainer review: no** — it is
   strictly better than today, where both verbs addressed an empty document.

None of the *Forbidden Patterns* is present: no god object grows past its budget (the new
logic lands in new modules), no peer-layer import, no module-level mutable state (the
receiver registry hangs off the app instance), no ABC, no hard-coded path.
