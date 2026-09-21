# FUN-17 — Ports, StoreProfile, recorders, and the construction move

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

Define the persistence ports and move engine construction to after config resolves.

## Why

The engine does not receive its storage — it goes and finds it, lazily, on first access (executor.py:1509-1527). That temporal coupling is what every defect downstream rests on. Moving construction to _app deletes the argument rather than winning it.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. RuntimeTransaction ACCUMULATES commands and commits once on __exit__. It must be implementable over Cloudflare D1, which has no BEGIN.
2. A store declaring cross_aggregate_atomicity=False REFUSES a transaction spanning two aggregates. It never applies it in parts.
3. StoreProfile carries all ten fields including offline_capable, and boot REFUSES rather than degrading when a required capability is absent.
4. The lazy substrate property is gone. A tripwire test proves the engine receives its store and never discovers one.
5. The seven import-linter contracts still pass unchanged. No new layer.
6. claim() returns Claimed | Conflict. Losing a claim is an outcome, not an exception.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
