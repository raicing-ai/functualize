# FUN-4 — Plan

Baseline `03fbb64` (`origin/master`, FUN-17 merged). Branch `feat/gate-resolution-model`.

## Architecture gate — how the region was mapped

| Pass | Tool | What it answered |
|---|---|---|
| Prose / prior art | **zvec-grep** (`/usr/local/bin/zg`, index built in this worktree: 834 files, 13 265 entities, 1 m 33 s) | The overwrite defect and reopen refusal (`_workflow_answer.py`, `scope_store.reopen_gate`); the ladder's per-rung failure rationale (`_gate/_registry.py:190-222`, `docs/guides/ai.md:273-306`) |
| Real surface | **rg** + **AST class-size walk** (serena was **not** activated in this run; T7 and T8 re-run `find_referencing_symbols` on `_service_gate`, `deposit_gate_payload` and `answer_gate` before editing) | Every call site in `spec.md` §7 |
| Dependency direction | `pyproject.toml` import-linter contracts, `rg "^from functualize\._"`; graphify was checked for staleness (built 9 commits behind HEAD) and **not** used for line facts | `_engine` ⟂ `_gate` (peers), public `app/` → internals allowed, internals → public forbidden |
| Prior decisions | ADR-022, ADR-025, ADR-026, ADR-027; `contributor/reference/runtime-persistence-data-model.md` §1.4, §2.4, §4 | The engine owns transition meaning and storage owns durability. There is one seam, not two. No new layer |

Codemaps (`contributor/architecture/codemaps/`) were **not** re-read line by line in this
run. The diagrams below agree with `AGENTS.md` → *Package structure* and ADR-026's layer
chain. T7's executor reads `codemaps/data-flow.md` before editing, and reports any
contradiction as a finding.

## BEFORE

```
 layer        module (real path)                                   dependency →
 ───────────  ──────────────────────────────────────────────────  ─────────────────────────────
 public app/  app/_workflow_answer.py  answer_gate / gate_draft ──┐
              app/_workflow_resume.py  deposit_gate_input ────────┤ ScopeStore (direct, 3 writers
 public CLI   _cli/builtins.py, app/adapters/workflow_flags.py ──┤  of gates[name]["payload"])
 plugin       functualize_mcp/_workflow_tools.py ────────────────┘
                                                                    │
 _engine      workflow_walker.py  WorkflowWalker (803 LOC class)    │
                ._service_gate ──(injected, duck-typed)──► _gate/_registry.GateRegistry.resolve_gate
                │                                          returns first model; rungs discarded;
                │                                          failures → one joined string
                ├──► frontier.FrontierWalk.block ──────────► ScopeStore.put_gate      (around the port)
                ├──► ScopeStore.deposit_gate_payload ──────► overwrite                (around the port)
                └──► frontier.gate_payload ────────────────► ScopeStore.get_gate      (around the port)
              frontier.FrontierWalk.claim ──► RuntimeStore.transaction()  (the ONLY port use)
 _primitives  document_store.DocumentRuntimeStore  (TRANSITIONAL(FUN-17/T7), middle man)
                _DocumentInputReader: InputRequest without id; id = "scope::gate"
                _DocumentTransaction (442 LOC): _suspend (never issued), _resume writes
                consumed_at (never issued), _append_input partitions "::" (never issued)
              scope_store.ScopeStore (930 LOC) — gates live in scopes.json
 _types       persistence.py  InputRequest(no id) · SuspendAtGate(no model/tools)
              InputWriter.append(request_id, source, payload) — 0 callers
```

### Smells the BEFORE already carries (catalogue names, Refactoring.Guru)

| Smell | Where | Note |
|---|---|---|
| **Primitive obsession** | the request id `f"{scope_id}::{gate_name}"` (`document_store.py:996`); the joined `last_error` string standing in for per-rung results (`_registry.py:228-238`) | The core of AC-1 and AC-2 |
| **Large class** | `WorkflowWalker` 803, `ScopeStore` 930 | Pre-existing. The constitution forbids **growth**, so the AFTER must not add lines to either |
| **Shotgun surgery** | "accept an answer" is written in 3 places with 2 different guards (`answer_gate` refuses an answered gate, `deposit_gate_input` does not) | Found by the 3-writer rg |
| **Dead code** | `ResumeWorkflow` apply, `_append_input`, `SuspendAtGate` — ports built, 0 production callers | FUN-17 disclosed this as "a port existing is not yet a port being reachable" |
| **Middle man** | `DocumentRuntimeStore` | Declared and TRANSITIONAL on master. Not ours to remove |
| **Duplicate knowledge** | "was this answer used?" is answered by graph position (`_walk_has_passed`) *and* by `consumed_at` | Two sources for one fact |

## Candidate AFTERs considered

**A — Model only, in `_types`, unwired.** Rejected. AC-1 and AC-2 cannot reach `[x]`
under *Reachability precedes `[x]`*. It introduces **speculative generality**: types
with no caller.

**B — `GateRegistry` records its own candidates to a store.** Rejected. `_gate` would
need a store, which puts storage decisions in a peer layer. It is also the
`transitions.py` shape ADR-025 rejects, and it duplicates what the engine's recorders
already are.

**C — the walker (`_engine`) records through the port; a pure `_gate` produces
evaluations; one `_primitives` module holds the document representation, shared by the
port backend and the surfaces.** **Chosen.** The smells it introduces are checked below.

## AFTER (C)

```
 layer        module                                         dependency →
 ───────────  ───────────────────────────────────────────── ───────────────────────────────────────
 public app/  app/_workflow_answer.py  answer_gate/gate_draft ─┬─► _gate/_evaluation.evaluate_submission
              app/_workflow_resume.py  deposit_gate_input  ────┤   (validate once → CandidateEvaluation)
                                                               ├─► _engine/recording/input_recorder
                                                               │   (mint ids, build GateCandidate)
                                                               └─► _primitives/gate_requests  ◄─┐
                                                                   TRANSITIONAL(FUN-21): same │
                                                                   lock as ScopeStore.batch() │
 _engine      workflow_walker.WorkflowWalker._service_gate  (3-line delegate; class SHRINKS)   │
                 └─► gate_service.GateService.service(node, walk, registry, recorder)          │
                       ├─► registry.evaluate(...)  (injected; returns _types LadderOutcome)    │
                       ├─► recording.InputRecorder → SuspendAtGate(+request_id,model,tools),   │
                       │                              GateCandidate…, ConsumeInput             │
                       └─► frontier.FrontierWalk.{open_request, record, consume, resolution}   │
                             └─► RuntimeStore.transaction()  (one unit per gate transition) │
                                   ▲ FUN-21 adds tx.effects.append(...) in these same units    │
 _primitives  document_store: _DocumentInputWriter/Reader + _DocumentTransaction dispatch ─────┘
              (delegate to gate_requests; _resume no longer writes consumed_at;
               "::" parse gone; class stays ≤ 500)
              scope_store.ScopeStore — unchanged surface; deposit_gate_payload kept for tests only
 _gate        _registry.GateRegistry.evaluate (pure ladder) ; resolve_gate = evaluate + raise
              _evaluation.evaluate_submission, blocked_reason_from
 _types       gate_resolution.py  EvaluationOutcome, CandidateEvaluation, GateCandidate,
                                  LadderOutcome, GateResolution          (values, stdlib only)
              persistence.py      InputRequest.request_id, SuspendAtGate(+3), ConsumeInput,
                                  InputWriter.append(candidate)/consume, InputReader.request/
                                  candidates_for ; errors.py InputRequestNotOpenError
```

Boundary crossings, checked against the import-linter contracts:
- `_engine` → `_types`: legal.
- `_engine` → `_gate`: **none**. The registry is injected and `LadderOutcome` is a
  `_types` value.
- `_primitives` → `_types`: legal.
- `_gate` → `_types`: legal.
- public `app/` → `_gate`, `_engine.recording`, `_primitives`: legal. Precedent: `app/utils.py` already imports `_engine.notify` and
  `_primitives.*`.
- No internal module imports a public one.

### Smells the AFTER introduces, and how each was handled

| Candidate smell | Verdict |
|---|---|
| **Large class growth** in `WorkflowWalker` or `ScopeStore` | **Removed by construction.** Gate logic moves *out* of `WorkflowWalker` into `GateService`. `ScopeStore` gets **no** new method, because `gate_requests` works over `get_gate`/`put_gate` inside `batch()`. `_DocumentTransaction` only dispatches; its apply bodies live in `gate_requests`. T5's gate keeps it ≤ 500 LOC |
| **Shotgun surgery** — the accept guard in 3 places | **Removed.** R6's guard exists once, in `gate_requests.append_candidate`. Both the port path and the surface path call it |
| **Divergent change** in `gate_requests` (the document format *and* the guard) | Accepted. Both disappear together when FUN-21 replaces the module |
| **Feature envy** — surfaces building candidates | Avoided. Surfaces call `evaluate_submission` and `InputRecorder`; they never construct `GateCandidate` fields by hand |

## Surviving smells

1. **Two write paths to one record: port (walker) and direct (surfaces).** Smell:
   *shotgun surgery*, reduced but not gone.
   - **Where:** `_primitives/gate_requests.py` is called from
     `document_store.py` and from `app/_workflow_answer.py` / `app/_workflow_resume.py`.
   - **Why accepted:** the surfaces hold only a `ScopeStore`, so moving them to the
     selected `RuntimeStore` changes how CLI, MCP and app callers obtain storage. That
     move is AC-3's precondition and FUN-21's slice. Both paths share one implementation
     and one guard, so behaviour cannot drift.
   - **Needs maintainer review: yes** (D-2): confirm FUN-21 owns the surface move.
2. **`ScopeStore.deposit_gate_payload` kept with 0 production callers.** Smell: *dead
   code*, test-only.
   - **Where:** `scope_store.py:721`, with 34 test call sites in 15 files.
   - **Why accepted:** tests use it to plant an answered gate. R9 reads such a record as
     a legacy accepted request, so the fixture stays valid. Migrating 34 sites is churn
     with no behaviour change.
   - **Needs maintainer review: yes** — keep it, or add a wave to migrate the fixtures.
3. **Duplicate knowledge: `consumed` status vs `_walk_has_passed`.**
   - **Where:** `app/_workflow_answer.py` `_reopen`.
   - **Why accepted:** legacy records have no consumed marker, and pitfalls §22's
     graph-based check is correct for them. The graph check can be removed once legacy
     records are imported (offline-import wave).
   - **Needs maintainer review:** no.
4. **Engine-minted identity differs from `StartAttempt`'s store-minted identity.** This
   is an inconsistency, not a catalogue smell.
   - **Why accepted:** it is forced by the accumulating port (contracts §2).
   - **Needs maintainer review:** no. ADR-029 records it (T12).

Nothing on *Forbidden Patterns* survives:
- no class grows past ~500 LOC (gated in T5, T7);
- no peer cross-import (`lint-imports` at every wave);
- no ABC;
- no global state: ids come from `uuid4` in the recorder, with no module-level registry;
- no `_cli/` internals import: `_cli/builtins.py` keeps importing
  `functualize.app.utils` only.

## Design skills consulted

- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — **loaded**.
  The smell names above come from it: *Primitive Obsession*, *Large Class*, *Shotgun
  Surgery*, *Dead Code*, *Middle Man*, *Speculative Generality*, *Divergent Change* and
  *Feature Envy*. *Extract Class* is the refactoring behind `GateService`, and *Replace
  Data Value with Object* is the one behind `request_id` and `GateCandidate`.
- `python-design-patterns` (in-repo) — **not loaded in this run**. It covers KISS, SRP,
  God-class decomposition and composition. The executor of T7 loads it before extracting
  `GateService`.

## Technical approach (per wave; the tasks carry the detail)

- **W0: values and port (T1, T2).** These are pure types. Nothing changes behaviour.
- **W1: pure logic (T3, T4).** `gate_requests` (the document representation plus the R6
  guard, R7 supersede and R9 projection) and `_gate` evaluation. They share no files, so
  they run in parallel.
- **W2: backend and recorder (T5, T6).** The document backend delegates to
  `gate_requests`. `InputRecorder` mints ids and builds the commands.
- **W3: walker (T7).** `GateService` is extracted and gate transitions go through
  `RuntimeStore.transaction()`. This is the first production path for AC-1 and AC-2.
- **W4: surfaces (T8).**
- **W5: attribution (T9).** This is a separate wave because T9's callers depend on T8's
  new keyword.
- **W6: end-to-end gates and sabotage (T10), in parallel with docs (T11).**
- **W7–W8: the pre-merge lifecycle (T12, then T13).**

## Version-control lifecycle (binding for T12–T13)

`.spec/features/` is tracked on this branch and absent from `master`
(`.claude/rules/spec-workflow.md` → *Version control lifecycle*).

1. Before opening the PR, migrate the durable half:
   - add a `.spec/STATUS.md` entry for FUN-4. It states that AC-1 and AC-2 are
     delivered, AC-3 is open pending FUN-18/19/21, and the Jira issue must not close
     yet;
   - add `contributor/adr/029-gate-resolution-is-recorded-not-recomputed.md`. It records
     engine-minted identity, the append-only evaluated candidate, one consumption writer
     and supersede-on-reopen.
2. **Push 1:** the feature commits. Wait for validation, including all three `test-full`
   legs. `spec-artifacts-cleared` is expected to fail at this point.
3. **Push 2:** the **last** commit is deletion-only:
   `git rm -r .spec/features/gate-resolution-model`. Also confirm
   `git ls-files contributor/architecture/research/` is empty. It is empty on this base,
   because this branch is cut from `master`, not from `docs/runtime-persistence-research`.
4. Hygiene: no Jira or Multica key, no agent identity and no `Co-authored-by:` agent
   trailer in any commit subject, body, PR title or PR body. Read back
   `git log --format='%B' origin/master..HEAD` before each push. `master` refuses
   non-fast-forward pushes, so a leak cannot be undone.
5. `tests/spec/test_task_gates_still_hold.py` is red from the first commit of `tasks.md`
   until ≥ 12 counting gates belong to `[x]` tasks. `tasks.md` → *Why the gate suite is
   red* carries the running count. The final deletion commit makes the suite skip
   (`.spec/features/` empty).

## Risks

| Risk | Mitigation |
|---|---|
| FUN-18 (in flight on `feat/runtime-schema-migrations`) edits `_types/persistence.py` at the same time | T2 is small and lands in wave 0. Whichever merges second rebases. Contracts §7 lists what FUN-18's schema must carry |
| `ScopeStore.batch()` reads may not see the in-batch envelope, which would make the R6 guard racy | T3's gate includes a two-writer test through `batch()`. If the guard cannot be made atomic over the public `ScopeStore` surface, **stop** and raise it: the fix would add a `ScopeStore` method, which the plan has ruled out |
| MCP clients depend on the gate record's `model`/`tools` keys | `SuspendAtGate` carries both (contracts §2). T7 runs the MCP workflow tests |
| `blocked_reason` text drift breaks operators' greps and `docs/guides/ai.md` | R8 byte-identical gate, in T4 |
