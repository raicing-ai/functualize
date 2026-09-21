# FUN-25 — Measure StoreProfile empirically across six backends

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

Turn StoreProfile from a hypothesis into measurements.

## Why

StoreProfile's ten fields were asserted from vendor documentation. ADR-022's failure mode is building a two-backend abstraction against one backend; the antidote is knowing what real backends do BEFORE the port is frozen. The payoff is already proven: Stored.revision: int is a latent defect only a remote backend exposes, found by reading S3's docs.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. A results table: ten questions x seven backends. Every cell is a measured value or an explicit NOT MEASURED with a reason.
2. Every cell carries an evidence level: measured (real service) | measured (emulator) | measured (fake) | NOT MEASURED.
3. Every StoreProfile field on any backend proposed for shipping is backed by at least one `measured (real service)` row.
4. Tier A passes with no network, no Docker and no credentials.
5. Tier B and C SKIP, never fail, when credentials are absent. A contributor with no AWS account runs the suite green.
6. The three open questions are answered or explicitly retired: R2 conditional-PUT atomicity; D1 absolute REST latency; whether anything depends on Stored.revision being an int.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
