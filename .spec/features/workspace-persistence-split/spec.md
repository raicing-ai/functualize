# FUN-23 — Separate managed workspace persistence, and evaluate AgentFS

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

Runtime truth and workspace bytes stop sharing a store.

## Why

A run record and a 400 MB artifact have different transaction sizes, retention, sharing and streaming semantics. Design 1 reached this conclusion too and it is adopted with credit.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. Runtime rows store an immutable reference and a digest. They never store artifact bytes.
2. The workspace port is separate from RuntimeStore and may have a different backend.
3. Whether one SQLite file holds both is answered explicitly — logical separation is already decided, physical co-location is not.
4. The AgentFS evaluation ends in an ADR with a decision, not a survey.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
