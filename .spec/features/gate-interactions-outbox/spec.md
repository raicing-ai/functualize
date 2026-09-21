# FUN-21 — Gate interactions, evidence, and the transactional outbox

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

A human's answer and the effect it triggers cannot be separated by a crash.

## Why

A gate resolution that commits without its side effect, or a side effect that fires without its commit, are the two halves of the same bug. The outbox makes them one commit — the shape DBOS independently arrived at, cited as evidence in 09-decisions.md.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. A gate resolution and its outbox row commit in ONE transaction.
2. Delivery is AT-LEAST-ONCE with consumer dedup. The documentation says so in those words — no at-most-once claim anywhere.
3. An undelivered effect survives a process kill and is delivered on the next start.
4. Evidence attached to a gate answer is stored by reference and digest, never as bytes in a runtime row.
5. A store declaring durable_outbox=False does not run the outbox tier and cannot be selected by a feature needing one.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
