# FUN-24 — Repair the four runtime persistence defects

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

Make the existing document stores safe before anything migrates them.

## Why

A corrupt source stays corrupt. FUN-19 migrates the documents these defects write; repairing after the migration means migrating known-bad records and paying twice. All four defects have runnable reproductions that were executed, not reasoned about.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. A two-process claim race yields TWO DISTINCT generations. Assert it with locking disabled — a test that runs with locking working cannot tell the two designs apart.
2. A stale runner's write to scope-state/<id> is REFUSED, not accepted.
3. Every fenced write passes expect=. The advisory lock becomes defence in depth, not the mechanism.
4. A substrate install failure FAILS BOOT rather than being logged and swallowed.
5. Stored.revision is opaque; `grep -rn '\.revision' src/functualize plugins` shows nothing did arithmetic on it.
6. A TUI write and a CLI read agree — the split brain at shell_mode.py:312 is closed.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
