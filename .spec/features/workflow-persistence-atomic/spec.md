# workflow-persistence-atomic — a parked workflow resumes on the selected store

**Status:** specified 2026-10-11 against SD/12583004 v3 (S-9). **One decision open** (§6, D-W1)
gates wave 5 only. The second spec feature on `feat/sqlite-runtime-provider` (owner decision B,
MCH-149, 2026-10-10); the first, `sqlite-runtime-provider`, is delivered and its directory was
cleared by `5cdd2e12`.

## Goal

Every read and write a workflow walk makes on its scope goes through the selected `RuntimeStore`
port — never the legacy `ScopeStore` — so a workflow blocked at a gate on one process is claimed,
released and resumed by another.

## Why

Only the walk's **claim** travels the port today (`_engine/frontier.py:224`). Its renew
(`frontier.py:321`), release (`:336`), start, step records, branches, position and status still
write the legacy `ScopeStore` (`self._store.*`: 46 call sites across `frontier.py`,
`workflow_walker.py`, `workflow_runner.py`, counted with `rg -o "self\._store\.\w+"` at
`0ede988b`). On SQLite the claim lands in `workflow_scopes` while the release looks in the legacy
`documents` scope, finds generation 0 / owner `nobody`, raises `StaleGenerationError`, and the
walk stops `SUPERSEDED` instead of blocking at its gate. `tests/integration/test_substrate_durability.py`
records exactly that as a strict xfail marked `TRANSITIONAL(workflow-persistence-atomic)`
(`:47-57`) — this feature's own name.

## Acceptance criteria

Gates run at authoring time; each task's file scope is the gate's hit set.

1. **W-AC-1 — the walk never touches the legacy scope store.** `rg -n "self\._store\."
   src/functualize/_engine/frontier.py src/functualize/_engine/workflow_walker.py
   src/functualize/_engine/workflow_runner.py` returns nothing (it is 46 at `0ede988b`); none of the three imports `ScopeStore`; and a new architecture test, `tests/spec/test_the_walk_writes_only_through_the_port.py`,
   holds it with an `ast` walk (imports and attribute calls), not a regex: docstrings name
   `ScopeStore` and must not count.
2. **W-AC-2 — the durability test passes and stops being an xfail.** `tests/integration/test_substrate_durability.py`
   passes on `runtime_store.url = "sqlite:///…"` with the module-level strict xfail and its
   `TRANSITIONAL(workflow-persistence-atomic)` marker **removed**; its positive-records assertions
   read the relational tables (`workflow_scopes`, `workflow_steps`, `scope_state`,
   `input_requests`/`input_candidates`) with ordinary SQL, never a `documents` key.
3. **W-AC-3 — release, renew and status are fenced by the port.** A walk that lost its claim to a
   second process cannot renew, release, record a step, move the scope or write state: each such
   command from the stale generation lands nothing (zero rows on SQLite; the document store's
   compare-and-swap refusal), and the live holder's values survive. Two-process test on SQLite.
4. **W-AC-4 — the document store is unchanged in behaviour.** With nothing configured, every
   existing workflow test passes unmodified except where it constructed a `ScopeStore` for the
   walk by hand (those switch to the port, by the same rule as W-AC-1), and the conformance
   BASELINE passes for both stores including the new commands (§2).
5. **W-AC-5 — schema revision `0002` upgrades a version-1 database.** A file at version 1 (what
   `sqlite-runtime-provider` shipped) migrates to 2 at boot; the `versioned_migrations` tier's
   `historical` set gains `"version-1"`; no `0001` text changes.

## 1. Behaviour

| # | Situation | Behaviour |
|---|---|---|
| B-1 | Worker A walks to a gate on `sqlite:` and exits | the scope is `blocked` at the gate in `workflow_scopes`, its lease released (owner cleared, generation kept), the step records in `workflow_steps`, the request in `input_requests` |
| B-2 | Worker B, another directory sharing only the store, resumes it | B claims at generation N+1, replays the recorded steps without re-running them, feeds the accepted answer, walks to the end; the scope is `completed` |
| B-3 | A walk loses its lease mid-step to another process | its next renew is refused quietly (best-effort, as today), and its next authoritative write is refused by the store's fence; nothing it writes lands |
| B-4 | A step job calls `State.set` inside a walk | the write is a `StateBatch` under the walk's generation into `scope_state`; the resumed walk reads it back through the port |
| B-5 | The walk emits walk-log events | they are appended through `EventWriter` into `scope_events`, not into a legacy scope document |
| B-6 | Nothing configured | identical to today: the document store implements every new command over the same `ScopeStore` methods the walk used to call directly |

## 2. What the port gains (detail in `contracts.md`)

Commands `StartWalk`, `RenewLease`, `ReleaseLease`, `RecordStep`, `RecordBranch`, `MoveScope`;
`CompleteStep` gains the step-record fields the walk already writes; readers `step`, `steps`,
`branch`, `state` and `WorkflowView.graph_digest`. Every one is added to BASELINE so a third-party
store is held to it (S-8).

## 3. Reading of S-9 recorded here

S-9 says *"Its scope reads and writes (claim, renew, release, status) go through the runtime
store port"*. This spec reads **"its"** as the walk's scope — so job `State` written during a walk
(B-4) and the walk log's events (B-5) are in, because both are reads and writes of that scope, and
leaving them on `documents` would keep two authorities for one scope, which the shape rejects
(*"Indefinite dual write; shadow reads"*). **Out**, as the narrowed non-goal says (*"engine-side
workflow state and lease fencing outside the walk's scope reads and writes"*): `State` in a job
run that is not inside a walk, and `executor.py:1059-1068`'s close of such a run's scope. The
operator surfaces are D-W1.

## 4. Out of scope

The rest of FUN-20 (shape non-goal, verbatim: *"The rest of FUN-20's suspension/resume rewiring,
beyond S-9: engine-side workflow state and lease fencing outside the walk's scope reads and
writes"*); gate interactions, evidence and the outbox dispatcher (FUN-21); network providers
(FUN-22); workspace persistence (FUN-23); removing `ScopeStore` or its public export from
`functualize.app.utils` (it still backs the document store and non-walk state).

## 5. Evidence baseline

`feat/sqlite-runtime-provider` @ `0ede988b`, worktree clean, `.spec/features/` absent before this
package. `path:line` citations re-read there.

## 6. Decision open — D-W1, put to the maintainer on MCH-149

**Operator surfaces go blind on SQLite once the walk stops writing `documents`.** `app/_workflow_control.py:120`,
`app/adapters/workflow_flags.py:236-238`, `_cli/builtins.py:1141` and the MCP plugin's
`_workflow_tools.py:43,160-168` read and write scopes through `ScopeStore(app.substrate)`. On
`sqlite:` that substrate is the `documents` table, which this feature stops filling. Options:
(a) move their scope reads and their cancel/reclaim onto the port (wave 5); (b) refuse those
operator commands loudly on a store other than documents until FUN-20; (c) ship them blind.
Recommendation (a). Waves 0–4 proceed regardless.
