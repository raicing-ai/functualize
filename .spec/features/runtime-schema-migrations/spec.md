# FUN-18 — State machines, relational schema, and the migration contract

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

Specify the legal state transitions, then the tables that hold them.

## Why

02-what-exists-today.md §6 found twelve status writers and no transition table. Specifying the machine before the schema is what stops the schema encoding an accident. Most of this data model is adopted from the archived Design 1, with credit.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. Attempt, Run, Scope and InputRequest each have a written state machine with a legal-transition table.
2. An illegal transition raises IllegalTransition naming both states. It is not silently written.
3. The schema is one row per step, not one row per document — a D1 row caps at 2 MB and the scopes envelope grows without bound.
4. Migrations are versioned and forward-only, with a recorded schema version.
5. The 500-record cap becomes an explicit retention policy, not a write-time eviction.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
