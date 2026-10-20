# Gate interactions, evidence, and the transactional outbox — tasks

Refined against `origin/master` @ `91947bb4`. Wave ordering is binding: never start a task
in wave N+1 while wave N has unchecked tasks. Each task's acceptance gate is run at
authoring time; `[x]` needs the gate green **and** the named production call path.

Scaffold corrections applied: task 1.1 (*InputRequest wiring and the input recorder*) is
dropped — `_engine/recording/input_recorder.py` ships on master. Scaffold task 2.1 keeps
only the walker's request/candidate wiring (now 2.1 below); deposit behaviour belongs to
the gate-resolution branch (D-2).

## Wave 0 — vocabulary

*Waves 0–1 land values, ports and storage ahead of their production callers,
as FUN-17's ports did: the call paths are 2.1 (the walk), 2.3 (boot) and 3.1
(the answer surfaces), and wave 4 proves each by sabotage. Gate evidence for
0.1–1.4: `ruff check`, `ruff format --check`, `mypy src/` and the plugin's
`mypy` clean; `tests/types tests/primitives tests/engine tests/conformance
tests/gate tests/test_public_api_surface.py` 1066 passed, 1 failed — the
lease-timing test `test_a_slow_claim_does_not_leave_the_first_step_claimable`
under `-n auto` load, which passes 3/3 alone and touches no changed module;
the SQLite plugin suite 198 passed.*

- [x] **0.1** Values and ports: `EvidenceRef`, `GateDecision`, candidate provenance,
      `GateResolution.decision`, request causal ids, `SupersedeRequest`, `EffectIntent`,
      `InputWriter.decide/supersede`, `InputReader.decision`, `EffectView`, `EffectQueue`,
      `OutboxStore`, `EffectReceiver`; `INPUT_REQUEST` gains `accepted→cancelled`; `OUTBOX`
      machine.
      *Files:* `src/functualize/_types/gate_resolution.py`, `src/functualize/_types/persistence.py`, `src/functualize/_types/lifecycle.py`
      *Gate:* `uv run mypy src/` · `uv run lint-imports` · `uv run pytest tests/types tests/primitives -q`

## Wave 1 — recording and storage

- [x] **1.1** The recorder: provenance on `submitted` and `ladder_candidates`, evidence
      validation, `decided`, `accepted_effect`, `superseding`.
      *Files:* `src/functualize/_engine/recording/input_recorder.py`, `tests/engine/test_input_recorder_provenance.py`
- [x] **1.2** Document backend: provenance, evidence refs and the decision on the gate
      record; `decide`, `supersede`, `decision` through the port; run id on suspend.
      *Files:* `src/functualize/_primitives/gate_requests.py`, `src/functualize/_primitives/document_store.py`, `tests/primitives/test_document_gate_provenance.py`
- [x] **1.3** SQLite inputs: revision `0003`, provenance columns, `input_decisions`,
      evidence as `artifact_refs` rows, `supersede`, readers.
      *Files:* `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0003_gate_interactions.sql`, `_run_sql.py`, `_readers.py`, `_workflow_sql.py`, `plugins/substrates/functualize-substrate-sqlite/tests/test_gate_interactions_sql.py`
      *Repair:* `supersede` now gives a successor a strictly later creation time,
      so `for_gate` remains deterministic when the clock has not advanced;
      the port regression fixes the successor ID's lexical order.
- [x] **1.4** SQLite outbox queue: `SqlEffectQueue` (claim, published, failed, effect);
      the store satisfies `OutboxStore`.
      *Files:* `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_outbox_sql.py`, `_runtime_store.py`, `plugins/substrates/functualize-substrate-sqlite/tests/test_outbox_queue.py`

## Wave 2 — the outbox tier

- [x] **2.1** Walker request/candidate wiring: the run id on the request; a ladder
      acceptance records its decision and, on a durable-outbox store, its intent in the
      candidates' unit.
      *Files:* `src/functualize/_engine/gate_service.py`, `src/functualize/_engine/frontier.py`, `tests/engine/test_gate_ladder_decision.py`
      *Gate:* both stores pass the accepted and blocked ladder cases; removing
      `GateService.service → GateService._record` after the code commit fails the
      accepted case on both stores, and the committed call was restored.
- [x] **2.2** The dispatcher: claim, deliver, acknowledge or reschedule; at-least-once.
      *Files:* `src/functualize/_primitives/outbox.py`, `tests/primitives/test_outbox_dispatcher.py`
      *Gate:* the real SQLite queue and `OutboxDispatcher.drain` deliver outside
      a transaction, exclude a competing claim, read back a published or
      rescheduled effect, and redeliver after a lost ack while a receiver
      deduplicates by key. Four targeted cases pass; removing the dispatcher's
      `_deliver` call after commit fails the delivery case. Production boot
      composition and draining remain task 2.3.
- [x] **2.3** Receivers and boot: `register_effect_receiver`, the required capability at
      step 6.5, the `OutboxStore` agreement check, the dispatcher built and drained at the
      end of boot on both paths.
      *Files:* `src/functualize/_app/effects.py`, `src/functualize/_app/impl.py`, `src/functualize/_app/extensions_facade.py`, `src/functualize/_app/boot.py`, `src/functualize/_app/store_selection.py`, `src/functualize/_types/host.py`, `src/functualize/plugin/__init__.py`, `tests/app/test_effect_receivers.py`
      *Gate:* a receiver registered through the plugin door is delivered a
      committed SQLite intent by the drain at the end of boot on both the
      static and the standard path, and a second boot on the same file
      delivers nothing new; documents with no receiver builds no dispatcher,
      and documents with a registered receiver refuse boot naming the store,
      `durable_outbox`, `runtime_store.url` and the topic; a store whose
      profile and type disagree is refused at selection in both directions;
      a late registration, a duplicate topic, an empty topic and a
      non-receiver are refused at the door; a queue the drain cannot read is
      logged and the app still starts. `tests/app/test_effect_receivers.py`
      16 passed; removing boot's `_drain_outbox` call after the commit fails
      the delivery case on both paths (`2 failed`), and the committed call
      was restored. `host.py` and `plugin/__init__.py` needed no change: the
      public values shipped with 0.1, and the door stays off
      `PluginHost`'s census-sized `ExtensionsView` until a shipped plugin
      calls it (`contracts.md` §4).

## Wave 3 — answer surfaces on the selected store

- [x] **3.1** One answer path, two record seams: `answer_gate`, `gate_draft`,
      `resolve_gate`, reopen and the resolution view over a `RuntimeStore`; provenance,
      decision and intent on both; drain after commit.
      *Files:* `src/functualize/app/_workflow_answer.py`, `src/functualize/app/_workflow_resume.py`, `tests/app/test_answer_on_selected_store.py`
      *Gate:* a real workflow blocked on the selected store is answered through the public doors on both seams: over SQLite the submission, its decision and its `gate.accepted` intent commit as one unit and the dispatcher runs only after it — the receiver holds the intent keyed by the request and the row reads back `published`; a partial answer is a recorded candidate the next one supersedes; `--no-commit` is refused with `draft_requires_commit`; reopen supersedes over the port, keeps the withdrawn request's own decision, and is refused with `gate_already_consumed` once the walk passed; over documents the decision lands beside the accepted candidate in one batch and the resolution gains `accepted_id`, causal identity and the decision. `tests/app/test_answer_on_selected_store.py` 8 passed, with `tests/workflow/test_gate_drafts.py` and `tests/workflow/test_gate_resolution_model.py` green beside it (50 passed together); removing the post-commit drain after the commit fails the delivery case, and the committed call was restored.
- [ ] **3.2** Surfaces: `resume_scope` on a `RuntimeStore`; `--wf-input`, CLI
      `answer`/`resume` and MCP gate tools through `selected_workflow_store`;
      `_record_port_input` removed.
      *Files:* `src/functualize/app/_workflow_control.py`, `src/functualize/app/adapters/workflow_flags.py`, `src/functualize/_cli/builtins.py`, `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`, `tests/cli/test_workflow_answer_relational.py`

## Wave 4 — proof and record

- [ ] **4.1** Process kill between commit and dispatch; redelivery deduplicated.
      *Files:* `tests/workflow/test_gate_outbox_recovery.py`
- [ ] **4.2** Documentation, decision and example: at-least-once wording, `Notify` stops
      being called the outbox, ADR-034, data-model reference, `STATUS.md`, `CHANGELOG.md`,
      an `examples/` receiver.
      *Files:* `docs/guides/workflows.md`, `docs/api/workflow.md`, `src/functualize/_types/workflow.py`, `src/functualize/_engine/workflow_walker.py`, `contributor/architecture/run-model/10-graph-semantics.md`, `contributor/adr/034-gate-effects-are-delivered-at-least-once.md`, `contributor/reference/runtime-persistence-data-model.md`, `.spec/STATUS.md`, `CHANGELOG.md`, `examples/plugins/effect_receiver/`

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["0.1"]},
    {"id": 1, "tasks": ["1.1", "1.2", "1.3", "1.4"]},
    {"id": 2, "tasks": ["2.1", "2.2", "2.3"]},
    {"id": 3, "tasks": ["3.1", "3.2"]},
    {"id": 4, "tasks": ["4.1", "4.2"]}
  ]
}
```
