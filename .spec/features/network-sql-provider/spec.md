# FUN-22 — Network providers and distributed resume

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

A workflow parks on one machine and resumes on another.

## Why

This is the capability the whole initiative exists to enable, and it is LAST because everything before it is what makes it a 400-line plugin instead of a rewrite. FUN-25 has already measured which backends can actually do it.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. D1 FIRST. It is the only evaluated backend with atomic multi-document commit via batch, and it needs no port change.
2. The provider is a PLUGIN. `grep -rn 'cloudflare\|boto3' src/functualize/` stays at 0.
3. A workflow parked by process A on machine 1 resumes on machine 2, with the fence holding across both.
4. Declared profile values match FUN-25's MEASURED values, not the vendor documentation.
5. R2 is NOT implemented unless FUN-25 established that its conditional PutObject is atomic under concurrent writers.
6. The default store is unchanged and still offline-capable. ADR-015 holds.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
