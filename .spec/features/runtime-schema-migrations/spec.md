# Runtime schema — state machines, relational schema, migration contract

**Status:** refined against `origin/master` @ `03fbb64` (the merged persistence ports).
Premises re-based 2026-09-25; the three decisions in *Open decisions* gate waves 2 and 4 of
`tasks.md`, and nothing else.

## Goal

Make the four runtime state machines executable — a transition outside the table is refused
with `IllegalTransition` at the point it would be written — and specify the relational schema
and the forward-only migration contract that the SQLite store builds on.

## Why

Scope status is written from **13 production call sites across 5 modules**, and nothing checks
the move (measured below). The ports merged in `03fbb64` carry status as a bare `str` on every
command and view, so the port did not close this; it moved it. Specifying the machine before the
schema is what stops the schema encoding an accident.

## Re-based premises (what changed since the scaffold)

Every row was re-measured on this branch at `03fbb64`; the command is the evidence.

| # | Scaffold said | Measured at `03fbb64` | Command |
|---|---|---|---|
| P1 | Evidence baseline `8c06198` | Baseline is `03fbb64`; branch rebased onto it | `git merge-base HEAD origin/master` |
| P2 | Write the four state machines (new) | Already on `master`, as target: `contributor/reference/runtime-persistence-data-model.md` §1 — a full transition table for Scope only; Attempt, Run and InputRequest are diagrams | read §1.1–1.4 |
| P3 | `_types/persistence.py` is ~340 lines, +90 goes there | **700** lines; ADR-026 *What would reopen this*: "re-examine if a later feature adds to this module, or if any executable logic appears in it" | `wc -l src/functualize/_types/persistence.py` |
| P4 | Status vocabulary is implicit | **Five** scope-status vocabularies: `WalkState` (`_engine/frontier.py:96`), `TERMINAL_SCOPE_STATUSES` (`_primitives/scope_format.py:133`), `LIVE_STATUSES`/`TERMINAL_STATES` (`app/_workflow_view.py:47,50`), `_SCOPE_STATUS_FOR` (`_engine/workflow_walker.py:1153`), literals in `_primitives/document_store.py:848,875,887` | `rg -n 'set_scope_status\(' src plugins` |
| P5 | The master table is the truth | **Live paths the master table forbids:** a resumed walk stays `blocked` and ends `completed` (`frontier.py:411`, docstring `app/_workflow_control.py:218-220`) → BLOCKED→COMPLETED; `resume_scope` refuses only `cancelled` (`app/_workflow_control.py:306`), so a `failed` scope is resumed and walked to `completed` → FAILED→COMPLETED | read the cited lines |
| P6 | One writer to guard | One **choke point**: all 13 writers reach `ScopeStore.set_scope_status` (`_primitives/scope_store.py:415`) — 4 via `DocumentRuntimeStore`, 9 directly | same `rg`; serena `find_referencing_symbols` misses the 2 duck-typed ones (`executor.py:1065`, `_workflow_control.py:444`) |
| P7 | Run machine is RUNNING → SUCCEEDED/FAILED/CANCELLED | The live run record stores `RunStatus` values — 9 members; **prior art:** `RunStatus.terminal` (`_types/enums.py:46-76`) already defines the run machine's terminal set (5: SUCCESS, FAILURE, CANCELLED, TIMEOUT, REFUSED) and says it is "the state machine's question". The run machine adopts it rather than a second vocabulary | read |
| P8 | InputRequest status is written | Document backend **derives** it (`_primitives/document_store.py:399-414`); no production writer stores it | read |
| P9 | The migration runner is this wave's | Master reference §7: "The runner arrives with FUN-19's tables"; no relational store exists at `03fbb64` | `rg -n 'CREATE TABLE' src/functualize` → `_config/vault.py` only |
| P10 | `ScopeStore` can absorb the check | `ScopeStore` is a **930-line class** — past the Constitution's ~500 LOC god-object line; growth is a Forbidden Pattern | AST walk (plan.md) |

## Acceptance criteria

Gates run at authoring time; each task's file scope is the gate's hit set.

1. **Tables.** Scope, Run, Attempt and InputRequest each have a legal-transition table held as
   data, with a named terminal set. Gate: a test enumerates every `(from, to)` pair of each
   machine's state set and asserts the check accepts exactly the table.
2. **Refusal.** A scope-status write or a run close outside its table raises `IllegalTransition`
   naming the machine, the current state and the target state, and **nothing is written**.
   Gate: for each machine with a live writer (Scope, Run), a test drives an illegal move through
   the production writer and asserts the exception and the unchanged record; sabotage (remove
   the check) makes that test fail.
3. **No live path regresses.** Every transition the live engine performs today is either in the
   table or recorded as a decision in *Open decisions*. Gate: `tests/workflow`,
   `tests/integration`, `tests/primitives`, `tests/types` and `tests/test_scope_store.py` pass
   unchanged except for tests that assert a now-illegal move, each listed in `tasks.md`.
4. **One row per step.** `schema.md` specifies the relational schema at one row per step (never
   one row per document) with the JSON boundary rule, and every column the reference model names.
5. **Forward-only migrations, recorded version.** Migrations are ordered, checksummed and
   forward-only; the applied version is recorded in `schema_migrations`; a checksum mismatch or a
   partially applied revision refuses rather than continues. *(Executable placement: decision D3.)*
6. **Retention is a policy.** The 500-record caps become one explicit `RetentionPolicy` value
   (count, terminal-only, age), consumed by every place that applies a cap. *(Whether the
   document backend stops evicting on write: decision D3.)*

## Open decisions (member confirmation required)

| ID | Question | Recommendation | Blocks |
|---|---|---|---|
| D1 | Is `failed` terminal? Today a failed scope is resumable (P5). | Add FAILED→RUNNING as the **retry** edge (guard: `resume`, not cancelled). Keeps today's behaviour; "terminal" then means `completed` and `cancelled`. The alternative — retry mints a new scope — is a behaviour change owned by the atomic-workflow wave. | task 3.1 |
| D2 | A resumed walk reports `blocked` until it ends (P5). | Admit BLOCKED→COMPLETED and BLOCKED→FAILED as `# TRANSITIONAL` edges, closed when resume goes through `ResumeWorkflow` (the atomic-workflow wave, which moves the scope to RUNNING in one unit). Forcing RUNNING now changes `advanceable_scopes` and `list_scopes` output. | task 3.1 |
| D3 | The migration runner and the relational retention statement have **no production caller** until the SQLite store lands (P9), and *Reachability precedes `[x]`* forbids ticking them here. | Keep them in this wave as tasks 5.2/5.3 **only if** the SQLite provider wave's first task wires them; otherwise move both to that wave and let this wave satisfy AC5 in `schema.md` + the contract. The document backend keeps its write-time cap (no maintenance scheduler exists); the policy value makes it explicit. | tasks 5.2, 5.3 |

## Out of scope

- The SQLite store, its connection handling and boot-step wiring (`sqlite-runtime-provider`).
- Moving the walk's resume through the port; the fence moving into the predicate
  (`workflow-persistence-atomic`).
- `input_candidates` append-only writes and the outbox (`gate-interactions-outbox`).
- Any change to a public `__all__`.

Needing one of these is a finding to raise, not work to absorb.

## Evidence baseline

`origin/master` @ `03fbb64`. Baseline suite on this branch, before any change:
`tests/types tests/primitives tests/workflow tests/test_scope_store.py
tests/integration/test_crash_and_resume.py` → **884 passed, 32 skipped** (201 s);
`lint-imports` → **7 kept, 0 broken**.
