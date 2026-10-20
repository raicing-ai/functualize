# Gate interactions, evidence, and the transactional outbox — tasks

Refined against `origin/master` @ `91947bb4`. Wave ordering is binding: never start a task
in wave N+1 while wave N has unchecked tasks. Each task's acceptance gate is run at
authoring time; `[x]` needs the gate green **and** the named production call path.

Scaffold corrections applied: task 1.1 (*InputRequest wiring and the input recorder*) is
dropped — `_engine/recording/input_recorder.py` ships on master. Scaffold task 2.1 keeps
only the walker's request/candidate wiring (now 2.1 below); deposit behaviour belongs to
the gate-resolution branch (D-2).

## Wave 0 — vocabulary

- [ ] **0.1** Values and ports: `EvidenceRef`, `GateDecision`, candidate provenance,
      `GateResolution.decision`, request causal ids, `SupersedeRequest`, `EffectIntent`,
      `InputWriter.decide/supersede`, `InputReader.decision`, `EffectView`, `EffectQueue`,
      `OutboxStore`, `EffectReceiver`; `INPUT_REQUEST` gains `accepted→cancelled`; `OUTBOX`
      machine.
      *Files:* `src/functualize/_types/gate_resolution.py`, `src/functualize/_types/persistence.py`, `src/functualize/_types/lifecycle.py`
      *Gate:* `uv run mypy src/` · `uv run lint-imports` · `uv run pytest tests/types tests/primitives -q`

## Wave 1 — recording and storage

- [ ] **1.1** The recorder: provenance on `submitted` and `ladder_candidates`, evidence
      validation, `decided`, `accepted_effect`, `superseding`.
      *Files:* `src/functualize/_engine/recording/input_recorder.py`, `tests/engine/test_input_recorder_provenance.py`
- [ ] **1.2** Document backend: provenance, evidence refs and the decision on the gate
      record; `decide`, `supersede`, `decision` through the port; run id on suspend.
      *Files:* `src/functualize/_primitives/gate_requests.py`, `src/functualize/_primitives/document_store.py`, `tests/primitives/test_document_gate_provenance.py`
- [ ] **1.3** SQLite inputs: revision `0003`, provenance columns, `input_decisions`,
      evidence as `artifact_refs` rows, `supersede`, readers.
      *Files:* `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0003_gate_interactions.sql`, `_run_sql.py`, `_readers.py`, `_workflow_sql.py`, `plugins/substrates/functualize-substrate-sqlite/tests/test_gate_interactions_sql.py`
- [ ] **1.4** SQLite outbox queue: `SqlEffectQueue` (claim, published, failed, effect);
      the store satisfies `OutboxStore`.
      *Files:* `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_outbox_sql.py`, `_runtime_store.py`, `plugins/substrates/functualize-substrate-sqlite/tests/test_outbox_queue.py`

## Wave 2 — the outbox tier

- [ ] **2.1** Walker request/candidate wiring: the run id on the request; a ladder
      acceptance records its decision and, on a durable-outbox store, its intent in the
      candidates' unit.
      *Files:* `src/functualize/_engine/gate_service.py`, `src/functualize/_engine/frontier.py`, `tests/engine/test_gate_ladder_decision.py`
- [ ] **2.2** The dispatcher: claim, deliver, acknowledge or reschedule; at-least-once.
      *Files:* `src/functualize/_primitives/outbox.py`, `tests/primitives/test_outbox_dispatcher.py`
- [ ] **2.3** Receivers and boot: `register_effect_receiver`, the required capability at
      step 6.5, the `OutboxStore` agreement check, the dispatcher built and drained at the
      end of boot on both paths.
      *Files:* `src/functualize/_app/effects.py`, `src/functualize/_app/impl.py`, `src/functualize/_app/extensions_facade.py`, `src/functualize/_app/boot.py`, `src/functualize/_app/store_selection.py`, `src/functualize/_types/host.py`, `src/functualize/plugin/__init__.py`, `tests/app/test_effect_receivers.py`

## Wave 3 — answer surfaces on the selected store

- [ ] **3.1** One answer path, two record seams: `answer_gate`, `gate_draft`,
      `resolve_gate`, reopen and the resolution view over a `RuntimeStore`; provenance,
      decision and intent on both; drain after commit.
      *Files:* `src/functualize/app/_workflow_answer.py`, `src/functualize/app/_workflow_resume.py`, `tests/app/test_answer_on_selected_store.py`
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
