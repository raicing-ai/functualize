# FUN-19 — The SQLite runtime provider, legacy migration, and the tiered conformance suite

**Status:** pre-loaded scaffold. Refine before executing; do not execute it as written
without checking it against the code.

## Goal

The first real RuntimeStore, and the tiered suite every later backend must pass.

## Why

SQLite is the reference implementation: it is the only backend that is both transactional and offline-capable, which makes it the one that can be the default. The conformance suite written here is what makes FUN-22 cheap.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the
gate's hit set.

1. SqliteRuntimeStore declares cross_aggregate_atomicity=True, fencing='cross-process', offline_capable=True, and passes the tier each field gates.
2. The BASELINE conformance tier passes for every store including DocumentRuntimeStore. A store that declares a capability False does not run that capability's tier and cannot be selected by a feature needing it.
3. Legacy migration is OFFLINE with backup and verification. No indefinite dual write (rejected as RP-7).
4. Migration REFUSES illegal records rather than importing them — which is why FUN-24 comes first.
5. BatchOnlySqliteDriver from FUN-25 runs against this store in Tier A and passes, proving the transaction buffers.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

## Evidence baseline

`origin/master` @ `8c06198`. Every claim in the research carries a `path:line` citation
that was checked against the working tree. **Re-check before relying on one** — master
moves.
