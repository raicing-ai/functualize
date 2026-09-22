# FUN-25 — Measure StoreProfile empirically across six backends

**Status:** refined against the code by the Factory Designer, 2026-09-22, at `68fa1a1`
(`origin/master` @ `7ba663c`). The scaffold's text is superseded where the architecture
pass falsified it; every change is recorded in `plan.md` §5.

## Goal

Turn `StoreProfile` from a hypothesis into measurements.

## Why

`StoreProfile`'s ten fields were asserted from vendor documentation. ADR-022's failure
mode is building a two-backend abstraction against one backend; the antidote is knowing
what real backends do **before** the port is frozen. The payoff is already proven:
`Stored.revision: int` was a latent defect only a remote backend exposes, found by reading
S3's docs — and repaired by FUN-24 (§Findings below).

## The premise, measured

> **`StoreProfile` does not exist in this codebase.**
> `rg -n "StoreProfile" src/ plugins/ tests/ | wc -l` → **0**.

All 25 occurrences in the tree are research prose plus one comment in `.env.example:19`.
The type is a proposal in `durability-outsourcing/07-the-design.md:60`, owned by FUN-17.

So the probe does **not** measure backends through functualize. There is no remote
substrate to measure through. It measures the backends directly and reports what a future
`StoreProfile` would have to say about each. The ten fields it must produce a column for
are that dataclass's twelve attributes minus the two labels (`name`, `description`):
`cross_aggregate_atomicity`, `fencing`, `multi_process`, `multi_machine`, `durable_outbox`,
`versioned_migrations`, `interactive_transaction`, `remote`, `max_document_bytes`,
`offline_capable`.

## Acceptance criteria

Gates, run at authoring time, each task's file scope equal to the gate's hit set.

1. **A results table: ten questions × seven backends.** Every cell is a measured value or
   an explicit `NOT MEASURED` with its reason. The seven columns are the filesystem,
   local SQLite, Cloudflare D1, AWS S3, **Cloudflare R2**, AWS DynamoDB and Turso/libSQL;
   Supabase Postgres is an eighth, Tier C, expected `NOT MEASURED`. *(Roster reconciled in
   `plan.md` §5.2 and flagged for maintainer review — the scaffold's "six", "seven" and
   "ten" disagreed, and R2 owned an open question with no task to answer it.)*
2. **Every cell carries an evidence level:** `measured (real service)` |
   `measured (emulator)` | `measured (fake)` | `NOT MEASURED`. **The three fakes are
   instruments, not columns** — they populate this column, never a column of their own.
3. **Every `StoreProfile` field on any backend proposed for shipping is backed by at least
   one `measured (real service)` row.** Today exactly two backends ship —
   `JsonFileSubstrate` and `SQLiteSubstrate` — and for both the real service is local and
   needs no credentials. **This criterion is fully satisfiable on a host with no cloud
   access.** It bites only for a backend someone proposes to ship, which is FUN-17's
   decision, not this ticket's. (`plan.md` §5.3.)
4. **Tier A passes with no network, no Docker and no credentials.**
5. **Tier B and C skip, never fail, when credentials are absent.** A contributor with no
   AWS account runs `uv run pytest` green. Gating happens at *module* level, before any
   client is constructed, so collection cannot error either.
6. **Every `StoreProfile` field for every backend is traceable to a probe result, never to
   a vendor doc.** A vendor claim may appear beside a measurement as context; it may never
   stand in for one.
7. **The three open questions are answered or explicitly retired:**
   - **Q1 — R2 conditional-`PutObject` atomicity under concurrent writers.** Probed by
     task 4.3 against R2's S3-compatible endpoint. `NOT MEASURED (no credentials)` is an
     acceptable outcome; silence is not.
   - **Q2 — D1 absolute REST latency from a developer laptop.** Probed by task 4.1 with
     stdlib `urllib.request`, so no client library sits inside the measurement.
   - **Q3 — does anything depend on `Stored.revision` being an `int`?` — **ANSWERED AND
     RETIRED at planning time; not a probe task.** See *Findings* below.
8. **Task 1 is the floci survey.** Point the probe at floci and find out whether it
   implements S3 conditional writes and DynamoDB `TransactWriteItems` at all — that
   decides whether floci is usable for the wire-protocol job or only for the boring parts.
   It is itself a probe run. *(Member's order, Jira comment 10013; unchanged.)*

## Findings that changed this spec

**Q3 is answered.** This branch is rebased onto FUN-24, so `09-verdict.md:56`'s falsifier
can simply be run:

- Before `7ba663c`: `revision: int` (`git show 7ba663c~1:…/protocols.py`, line 784).
- Now: `Revision = NewType("Revision", str)` (`_types/protocols.py:764`).
- Arithmetic/ordering census over `src/`, `plugins/`, `tests/`: the **only** two hits are
  SQL text against the sqlite plugin's own `revision INTEGER` column, stringified at the
  Python boundary (`…/functualize_substrate_sqlite/substrate.py:112`).

**Nothing in Python orders a revision or does arithmetic on one.**
`07-the-design.md` §6.1's repair is landed. What remains is a regression guard so the
property cannot silently un-land when the first remote substrate arrives — task **3.2**.

## Deliverable placement

The matrix lands at **`contributor/reference/substrate-capability-matrix.md`**, not the
scaffold's `contributor/architecture/research/` path: that tree cannot reach `master`
under the member rule of 2026-09-22 and, unlike `.spec/features/**`, has no CI guard to
catch the mistake. FUN-17…FUN-22 must be able to cite the matrix from `master`. The probe
harness stays under `tests/substrate_probe/`.

## Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket
quietly absorbing the next one's work — if you find yourself needing a later wave's
deliverable, say so rather than building it here.

Named explicitly, because the architecture pass found each one tempting:

- **Defining `StoreProfile`** anywhere under `src/` or `plugins/`. FUN-17.
- **Implementing any remote substrate.** FUN-17…FUN-23.
- **Exporting `StoreSubstrate`/`Stored` from `functualize.plugin`**, or deprecating
  `ScopeStore`/`RunStore`. `07-what-changes.md:63` — FUN-17.
- **Making the probe's fakes implement `StoreSubstrate`** so they slot into
  `tests/conftest.py::_alternate_substrate`. They model vendor drivers, not our port.
- **Unifying the four hand-rolled substrate doubles** already in the tree (`plan.md` §3).
  A real smell, diagnosed and handed to FUN-17.
- **Any `src/` or `plugins/**/src/` change at all.** `contracts.md`'s first command.

## Evidence baseline

`origin/master` @ **`7ba663c`** (not the scaffold's `8c06198` — the branch was rebased
onto FUN-24's merge). Targeted baseline re-measured on `68fa1a1`, 2026-09-22:

```console
$ uv run pytest -q --no-header tests/test_public_api_surface.py
43 passed in 0.29s
```

Every claim in the research carries a `path:line` citation that was checked when written.
**Re-check before relying on one** — `master` moves, and FUN-24 already invalidated the
`revision: int` citation that seeded this ticket.
