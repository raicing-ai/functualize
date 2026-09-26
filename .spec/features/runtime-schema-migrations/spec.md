# Runtime schema — state machines, relational schema, migration contract

**Status:** refined against `origin/master` @ `03fbb64` (the merged persistence ports).
Premises re-based 2026-09-25; decisions D1–D3 answered by the maintainer 2026-09-26 and recorded
under *Decisions*. No task is held.

## Goal

Make the four runtime state machines executable — a transition outside the table is refused
with `IllegalTransition` at the point it would be written — make a walk in flight say `running`
on every entry, and specify the relational schema and the forward-only migration contract that
the SQLite store builds on.

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
| P11 | (not in the scaffold) | **Probe of every `set_scope_status` write** on `00f58a2` (throwaway, deleted), driving fresh walk to a gate, resume through it, plain resume of a completed scope, resume of a failed scope: `running→running`, `running→blocked`, `blocked→completed`, `completed→completed`, `completed→running`, `running→completed`, `failed→completed`, and nothing else. `completed→running` is reachable by a plain `resume <id>`: completion clears the position, so the next entry takes `FrontierWalk.start`'s first-entry branch. `completed→completed` is the end-of-walk stamp firing twice — not a status change | the decision explanation on the tracking issue, 2026-09-26T00:15Z |

## Acceptance criteria

Gates run at authoring time; each task's file scope is the gate's hit set.

1. **Tables.** Scope, Run, Attempt and InputRequest each have a legal-transition table held as
   data, with a named *absorbing* set (states nothing leaves) and, for Scope, a separately named
   *evictable* set. Gate: a test enumerates every `(from, to)` pair of each machine's state set
   and asserts the check accepts exactly the table.
2. **Refusal.** A scope-status write or a run close outside its table raises `IllegalTransition`
   naming the machine, the current state and the target state, and **nothing is written**.
   Gate: through the production writer, `cancelled → running` (Scope) and closing an
   already-`success` run (Run) raise and leave the record unchanged; `blocked → completed`
   raises too, which is the witness that AC3 landed; sabotage (remove the check) makes each
   test fail.
3. **A walk in flight says `running`.** Every entry into a walk — first entry or resume, from
   `blocked`, `failed` or `completed` — stamps `running` before any step runs. Gate: a resumed
   walk mid-step reads `running` from the store, from `list_scopes` and in `advanceable_scopes`;
   the silent-step detector (`_engine/frontier.py:245`, `status == RUNNING`) diagnoses a silent
   step in a *resumed* walk, which it cannot at `03fbb64`.
4. **No live path regresses.** Every transition the live engine performs after AC3 is in the
   table. Gate: the record-mode sweep in task T6 runs after task T3 lands and finds zero pairs
   outside `SCOPE.transitions`; `tests/workflow`, `tests/integration`, `tests/primitives`,
   `tests/types` and `tests/test_scope_store.py` pass except tests asserting a now-illegal move
   or the old "resumed walk reports `blocked`" behaviour, each listed in `tasks.md`.
5. **One row per step.** `schema.md` specifies the relational schema at one row per step (never
   one row per document) with the JSON boundary rule, and every column the reference model names.
6. **Forward-only migrations, recorded version — as a contract.** `schema.md` §4 fixes the
   migration contract (ordered, checksummed, forward-only, version recorded in
   `schema_migrations`, refusal on mismatch, gap or ahead-of-shipped). The runner, revision
   `0001` and their wiring are implemented and made reachable in `sqlite-runtime-provider` (D3).
7. **Retention is a policy.** The 500-record caps become one explicit `RetentionPolicy` value
   (count, evictable-only, age), consumed by every place in this wave that applies a cap. The
   relational retention statement and its production caller are `sqlite-runtime-provider`'s (D3).

## Decisions (answered by the maintainer, 2026-09-26)

| ID | Question | Answer | Consequence in this package |
|---|---|---|---|
| D1 | Can a finished scope be re-run? | **A — yes.** `resume` keeps accepting `completed` and `failed` scopes (`--retry-epilogue`, retry of a failed step); only `cancelled` is absorbing | Scope table carries `failed → running` and `completed → running` as retry edges, `# TRANSITIONAL` until `workflow-persistence-atomic` decides whether a retry mints a fresh attempt. "Terminal" is split: **absorbing** = `{cancelled}`; **evictable** = `{completed, failed, cancelled}` (`TERMINAL_SCOPE_STATUSES`, whose comment "values a scope can never leave" is corrected in task T5). Documented consequence: a completed scope evicted by the cap can no longer be retried (`resume` → `workflow_not_found`), as today |
| D2 | Should a resumed walk say `running`? | **1 — stamp `running` on every entry** | New task T3 changes `FrontierWalk.start`'s resumed branch (`_engine/frontier.py:341-349`). The edges `blocked → completed`, `blocked → failed`, `failed → completed`, `failed → blocked` leave the table; entry is `{blocked, failed, completed} → running`, exit is `running → {blocked, completed, failed, cancelled}` |
| D3 | Do the runner and the retention statement belong here? | **B — move both to `sqlite-runtime-provider`, plus one task there for the retention caller** | Former tasks 5.1/5.2 moved to that package as 0.1/0.2, with 0.3 the new retention caller. This package keeps `schema.md` (the DDL and migration contract), the machines and the `RetentionPolicy` value |

Smell dispositions are recorded in `plan.md` → *Surviving smells*.

## Out of scope

- The SQLite store, its connection handling, the migration runner and revision `0001`, the
  relational retention statement and its caller, and boot-step wiring (`sqlite-runtime-provider`).
- Moving the walk's resume through the port; whether a retry mints a new attempt; the fence
  moving into the predicate (`workflow-persistence-atomic`).
- Typing the port's `status: str` fields with the lifecycle types (its own ticket, parked until
  this wave's vocabulary lands).
- `input_candidates` append-only writes and the outbox (`gate-interactions-outbox`).
- Any change to a public `__all__`.

Needing one of these is a finding to raise, not work to absorb.

## Evidence baseline

`origin/master` @ `03fbb64`. Baseline suite on this branch, before any change:
`tests/types tests/primitives tests/workflow tests/test_scope_store.py
tests/integration/test_crash_and_resume.py` → **884 passed, 32 skipped** (201 s);
`lint-imports` → **7 kept, 0 broken**.
