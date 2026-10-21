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
- [x] **3.2** Surfaces: `resume_scope` on a `RuntimeStore`; `--wf-input`, CLI
      `answer`/`resume` and MCP gate tools through `selected_workflow_store`;
      `_record_port_input` removed.
      *Files:* `src/functualize/app/_workflow_control.py`, `src/functualize/app/adapters/workflow_flags.py`, `src/functualize/_cli/builtins.py`, `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`, `tests/cli/test_workflow_answer_relational.py`
      *Gate:* with SQLite selected, `func builtin workflow answer … --input … --format
      json` records an accepted candidate and its decision on the port and `resume`
      completes the walk and consumes the request; a partial `--set` is a recorded
      candidate `--show` reads back as the draft; a fused `resume --input` answers and
      advances; `--no-commit` and `--retry-epilogue` exit 2 with
      `draft_requires_commit` / `epilogue_retry_unsupported`, changing nothing;
      `--wf-input` answers through `resolve_gate → answer_gate` (valid → accepted with a
      decision; invalid → recorded and exit 2; unknown gate → exit 1); the MCP
      `get_gate_draft`/`answer_gate`/`resume_workflow` tools answer and advance on the
      port with an `mcp`/`agent` candidate; the legacy scope document never holds the
      scope. `tests/cli/test_workflow_answer_relational.py` 9 passed. Sabotage after
      the code commit, each restored: CLI `answer` on the legacy helper fails 3, CLI
      `resume` on it fails 3, MCP `answer_gate` on it fails 1, `resume_scope` reading
      `get_scope` fails 4, `--wf-input` skipping `answer_gate` fails 2.
      `resume_scope` keeps serving the document store too: `selected_workflow_store`
      hands document projects the scope document, so refusing it would break `resume`
      on the default store (spec §3.5 covers both). `resume --format json` renders the
      run metadata's enums and start time as text — a walk that completed made it raise
      on either store before. Not changed: MCP `watch_workflow`, `purge_workflows` and
      `call_gate_tool`, which still read the legacy helper and are no answer surface.

## Wave 4 — proof and record

- [x] **4.1** Process kill between commit and dispatch; redelivery deduplicated.
      *Files:* `tests/workflow/test_gate_outbox_recovery.py`
      *Gate:* real crashes, by `os._exit` in a child process at production seams.
      A child answers the gate through `answer_gate` with a receiver registered and
      dies inside the post-commit `_app.effects.drain` (exit 17): read cold, the
      request is `accepted` with one candidate, its evidence reference and its
      decision, and the outbox row is `pending`, attempts 0; the next start's boot
      drain delivers it once (deliveries 1, applied 1, row `published`, attempts 1)
      without a second candidate, and a further start delivers nothing. A child
      whose boot drain delivers and then dies inside `SqlEffectQueue.published`
      (exit 23) leaves the row `claimed`, attempts 1, with the receiver's key
      applied once; a restart inside the claim lease delivers nothing; a drain past
      the lease redelivers (deliveries 2) and the receiver's key keeps applied at 1,
      row `published`, attempts 2; a later drain delivers nothing. The document
      store is pinned as having no outbox (`durable_outbox=False`, not an
      `OutboxStore`, a receiver refuses boot), since it has no queue to recover.
      3 passed; 3/3 repeat runs under `-n auto`. Sabotage after the code commit,
      each restored: the answer unit dropping its intent fails 2; acknowledging
      before delivering fails 1; never retaking an expired claim fails 1; no drain at
      the end of boot fails 2; a receiver declaring no capability fails 1.
- [x] **4.2** Documentation, decision and example: at-least-once wording, `Notify` stops
      being called the outbox, ADR-034, data-model reference, `STATUS.md`, `CHANGELOG.md`,
      an `examples/` receiver.
      *Files:* `docs/guides/workflows.md`, `docs/api/workflow.md`, `src/functualize/_types/workflow.py`, `src/functualize/_engine/workflow_walker.py`, `contributor/architecture/run-model/10-graph-semantics.md`, `contributor/adr/034-gate-effects-are-delivered-at-least-once.md`, `contributor/reference/runtime-persistence-data-model.md`, `.spec/STATUS.md`, `CHANGELOG.md`, `examples/plugins/effect_receiver/`
      *Gate:* AC-2's grep is green — `rg -i "at-most-once"` over
      `docs/ contributor/ src/` matches only `Notify`'s record-first rule and
      ADR-034's rejected alternative, and no matched line names the outbox;
      `mkdocs build --strict` passes; the `h-workflow` doc scenario passes
      and `--audit` accepts both edited doc pages; `uv run pytest examples/`
      → 253 passed, including the receiver example's 3 (protocol shape,
      key-dedup on redelivery, a real gate answered through `answer_gate`
      delivered after the commit); statics clean (ruff, format, mypy 397
      files, lint-imports 7 kept) and the docstring-adjacent suites green
      (`tests/types` 339 passed; recovery + notify + answer + receiver 27
      passed, 3 skipped). The source edits are docstrings only — no behaviour
      change, no new production code.

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
