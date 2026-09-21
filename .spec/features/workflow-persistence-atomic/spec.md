# FUN-20 — Workflow state, resume, and leases committed atomically

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

One transition, one commit, one fence.

## Why

Defect B3: no code path commits two documents together, so scopes and scope-state can diverge. This is where that is structurally fixed rather than patched — the fence moves into the transaction predicate instead of being remembered at each call site.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. A step record, its state change and its event commit as ONE unit or none of them do.
2. The fence is in the transaction predicate. A stale generation cannot commit from ANY process, and no call site has to remember to check.
3. A resumed walk in a fresh process sees its steps AND its variables. The split brain is unreachable by construction.
4. The B1 and B4 reproductions from FUN-24 still pass, now for a structural reason rather than a patched one.
5. A transaction NEVER wraps a job body, a prompt, an agent call or any network effect.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
