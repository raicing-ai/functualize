# Scope-targeted walk-log append

## Problem

A superseded workflow walker can append a late observational event to the scope log after a new walker has force-claimed that scope. The log then attributes an action to the current holder that it did not perform. The existing subscriber uses an empty state write at generation 0 to choose the scope, and that write cannot fence the event append.

## Authority

Shape Intent SD/23560193 v2, `Status: Approved`, `Authority: Approved` (read 2026-10-30). Owner decisions D-1 = B and D-2 = (a) are fixed. The scope event append names its scope and held generation directly; generation 0 fences nothing. The expected refusal matches the live FOSS-131 report (`updated` 2026-10-13 13:27:53 UTC).

## Behavior

- A caller may append an event directly to a named scope with a lease generation. A stale positive generation lands no event. The substrate may raise or silently match zero rows at commit.
- A current holder's scope-targeted append lands. A caller omitting `generation` passes 0 and is unfenced.
- A caller may name a run or a scope, never both. An append naming neither retains the unit's existing single-written-scope routing.
- Every `workflow.*` event emitted by the walker carries its held generation on the bus. The walk-log subscriber uses that value for the append, stores neither `scope_id` nor `generation` in the event payload, and performs no routing state write. An observation refusal does not disturb the walk.
- Watch and MCP scope-log response shapes remain unchanged. A superseded walk's late line is absent. Run records and outbox behavior remain unchanged.

## Acceptance criteria

1. The supplied matrix prints `MATRIX_PASS`: late = REFUSED, holder = landed, race = REFUSED on both SQLite and document stores.
2. The supplied generation-carrying SQLite and document repros exit 0 with `NO_RESIDUAL`. The generation-free repro is intentionally outside this gate.
3. A new `BASELINE` conformance row proves that a stale scope-targeted append lands nothing and the holder's append lands on both stores. It fails before the implementation and passes after.
4. A SQLite plugin test forces a claim from a second handle between the append and commit and proves the stale row does not land.
5. The requested root and SQLite plugin suites, Ruff, Mypy, and import-linter pass. The docs and changelog describe the contract.

## Boundaries

The run log, cancel semantics, generation-zero convention, watch flags, JSON schema, and lease renewal behavior are outside this change.
