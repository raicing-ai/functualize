# FUN-25 — Tasks

Refined against the code by the Factory Designer, 2026-09-22 at `68fa1a1`. Each task is
1–3 files and completable in one context window.

**Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked
tasks.** Waves below map to the JSON graph at the foot of this file, which is what the
`PreToolUse` spec gate parses.

## How to read a task

Every task carries **Files** (the hit set, not a guess), **Gate** (the command that must
be green before the box is ticked), and **Done when**. A box goes `[x]` only when its own
gate is green *against the code as it actually stands* — never on the strength of its
description (`.spec/CONSTITUTION.md` → *Transitional Changes*).

Two rules that govern every task in waves 3–4:

- **Never invent a cell.** A missing credential yields `NOT MEASURED (no credentials)` or
  a skip. Never a failure, never a guess, never a fake standing in for a real service.
- **Gate at module level**, before any client is constructed, so a credential-less
  contributor gets a skip rather than a collection error. The idiom is already in this
  repo: `plugins/credentials/functualize-aws/tests/test_integration_floci.py:41-64`.

---

## Wave 0 — survey and instrument

- [x] **1.1** Point the probe at floci and find out whether it implements S3 conditional
      writes (`PutObject` with `If-None-Match`/`If-Match`) and DynamoDB
      `TransactWriteItems` **at all**. This decides whether floci can back a
      `measured (emulator)` row for the wire-protocol questions or only for the boring
      ones. It is itself a probe run, and its answer is reported even when negative.
      *Files:* `tests/substrate_probe/_floci_survey.py`, `tests/substrate_probe/__init__.py`
      *Prior art — read before writing:* `test_integration_floci.py` (242 lines) already
      carries the emulator idiom, the `docker run -d --name floci -p 4566:4566
      floci/floci:latest` invocation, and the "no fallback to a fake" rule. Reuse it; do
      not reinvent it.
      *Gate:* `uv run pytest -q tests/substrate_probe/_floci_survey.py` → passes or skips
      with a reason naming the missing endpoint; never fails.
      *Done when:* the survey prints, for each of the two capabilities, one of
      *implemented* / *not implemented* / *not reachable*, and that verdict is captured
      for 6.1.
      *(Member's order, Jira comment 10013: this is task 1, before the harness.)*

- [ ] **1.2** The credential/reachability gate and the probe's pytest marker — one idiom,
      one place, used by every module after it.
      *Files:* `tests/substrate_probe/conftest.py`, `pyproject.toml`
      *Gate:* `uv run pytest -q tests/substrate_probe/` with **no** credentials in the
      environment → green, zero failures, zero collection errors; and
      `rg -n "substrate_probe" pyproject.toml` shows the marker registered beside the
      existing seven in `[tool.pytest.ini_options] markers`.
      *Done when:* a helper exists that turns "these env vars are absent" into a
      module-level skip with a reason a reader can act on.

- [ ] **1.3** The ten probe questions as one backend-agnostic harness. Plain functions and
      frozen dataclasses — **no ABC, no shared backend base class**
      (`.spec/CONSTITUTION.md` → *Forbidden Patterns*; `plan.md` §4).
      *Files:* `tests/substrate_probe/harness.py`
      *Gate:* `uv run pytest -q tests/substrate_probe/` green, **and**
      `rg -n "^(from|import) functualize" tests/substrate_probe/harness.py` returns
      nothing — the harness imports none of ours.
      *Done when:* the ten field names of `plan.md` §2 are enumerated in one place, each
      with its question and its evidence level, and a backend module can answer a subset
      without inheriting anything.

## Wave 1 — the three fakes (Tier A instruments)

These model **vendor driver constraints**, not our port. None implements `StoreSubstrate`.

- [ ] **2.1** `BatchOnlySqliteDriver` — refuses interactive transactions, accepts exactly
      one batch. Models D1, which has no `BEGIN`/`COMMIT`
      (`durability-outsourcing/05-cloudflare.md` §A.3).
      *Files:* `tests/substrate_probe/fakes.py`
      *Gate:* `uv run pytest -q tests/substrate_probe/` green with no network and no
      Docker.
      *Done when:* an attempt to hold a transaction open across a Python decision raises,
      and a single batch commits.

- [ ] **2.2** `FakeObjectStore` and `FakeItemStore` — an S3 with no multi-key atomicity
      and conditional-write semantics, and a DynamoDB with `TransactWriteItems`.
      *Files:* `tests/substrate_probe/fakes.py`
      *Gate:* as 2.1.
      *Done when:* each fake answers the harness's questions and every answer it produces
      is stamped `measured (fake)` — never `measured (real service)`.

## Wave 2 — Tier A (no network, no Docker, no credentials)

- [ ] **3.1** Tier A backends: the JSON filesystem, local SQLite, and the three fakes.
      **This is the one module permitted to import from `functualize`** — for these two
      the shipping substrate *is* the backend under test, which is what makes AC3
      satisfiable without any cloud account.
      *Files:* `tests/substrate_probe/tier_a.py`
      *Gate:* `uv run pytest -q tests/substrate_probe/tier_a.py` green with the network
      down; **and** the boundary rule holds —
      `rg -n "^(from|import) functualize" tests/substrate_probe/ | rg -v "tier_a.py"`
      returns nothing.
      *Done when:* every one of the ten fields has a value for the filesystem and for
      local SQLite, each stamped `measured (real service)`.

- [ ] **3.2** Regression guard: a revision is an **opaque token**, not an integer.
      Open question 3 is already answered (`spec.md` → *Findings*; FUN-24 landed
      `Revision = NewType("Revision", str)`), so this task does not probe it — it stops it
      silently regressing when the first remote substrate arrives.
      *Files:* `tests/primitives/test_substrate.py` (currently 494 lines; ~+25)
      *Gate:* `uv run pytest -q tests/primitives/test_substrate.py` green, **and** the
      reachability check — break `_revision_of` (`_primitives/substrate.py:60-68`) to
      return a constant and watch this new test fail. **Commit before sabotaging.**
      *Done when:* a test asserts a revision round-trips as an opaque token and is never
      ordered or arithmetically combined, and the sabotage was observed to turn it red.

## Wave 3 — Tier B (real services; skip, never fail)

- [ ] **4.1** Cloudflare D1 (real). Answers **open question 2 — absolute REST latency from
      a developer laptop**, so record the numbers, not just a verdict.
      *Files:* `tests/substrate_probe/d1.py`
      *Transport:* stdlib `urllib.request`. **Not `httpx`** — no first-party package
      declares it (`rg '"httpx' pyproject.toml plugins/*/*/pyproject.toml` → nothing); it
      is present only transitively, and stdlib keeps a client library out of a latency
      measurement.
      *Gate:* with `CLOUDFLARE_*` unset → `uv run pytest -q tests/substrate_probe/d1.py`
      skips at module level with a reason. With credentials → every cell measured or
      explicitly `NOT MEASURED`.
      *Done when:* `interactive_transaction`, `max_document_bytes` (the documented 2 MB
      row cap — **verify it, do not copy it**) and a latency distribution are recorded.

- [ ] **4.2** AWS DynamoDB — floci first, then real. Two evidence levels from one module:
      whatever floci answers is `measured (emulator)` and may **never** back a shipped
      field; the real service is `measured (real service)`.
      *Files:* `tests/substrate_probe/dynamodb.py`
      *Gate:* `pytest.importorskip("boto3")` then the env gate; no credentials → skip.
      *Done when:* `TransactWriteItems` behaviour under contention is measured, or
      recorded `NOT MEASURED (no credentials)` with task 1.1's floci verdict beside it.

- [ ] **4.3** AWS S3 **and Cloudflare R2** — floci first, then real. R2 is
      S3-API-compatible, so it is the same module against a different endpoint, exactly
      as `test_integration_floci.py:12-14` already reaches an emulator through
      `AWS_ENDPOINT_URL`. **This task owns open question 1 — is R2's conditional
      `PutObject` atomic under concurrent writers?** It is the single most important
      unknown in the research (`09-verdict.md:47-50`) and the scaffold had no task for it.
      *Files:* `tests/substrate_probe/s3.py`, `.env.example` (add `FUNCTUALIZE_PROBE_R2_*`)
      *Gate:* no credentials → module skip. With credentials → a contention test with
      concurrent conditional writers, and the count of winners recorded.
      *Done when:* Q1 is answered with a measurement, or recorded
      `NOT MEASURED (no R2 credentials)` — stated, never omitted.

## Wave 4 — Tier C (cheapest-last)

- [ ] **5.1** Turso/libSQL and Supabase Postgres, if cheap. Turso is the seventh column;
      Supabase is an eighth and is expected to stay `NOT MEASURED`.
      *Files:* `tests/substrate_probe/tier_c.py`
      *Gate:* clients absent or credentials absent → module skip, suite still green.
      *Done when:* each is measured or carries an explicit `NOT MEASURED` reason.

## Wave 5 — publish

- [ ] **6.1** Write the results matrix and settle the three open questions.
      *Files:* `contributor/reference/substrate-capability-matrix.md`
      **Path amended** from the scaffold's
      `contributor/architecture/research/substrate-capability-matrix.md`: that tree cannot
      reach `master` under the member rule of 2026-09-22 and has **no** CI guard to catch
      it, so publishing there would leave the initiative's only measured artifact
      unmergeable. `contributor/reference/` is the convention for a durable, citable
      reference and FUN-17…FUN-22 must cite this from `master`. *(Issue → Deliverable
      placement; supersedable by the member.)*
      *Gate:* the table has ten question rows × seven backend columns; **every** cell
      carries one of the four evidence levels;
      `rg -c "NOT MEASURED" contributor/reference/substrate-capability-matrix.md` matches
      the number of cells left unmeasured, each with a reason; Q1/Q2/Q3 each have a
      heading and a verdict. Q3's verdict is already written — `spec.md` → *Findings*.
      *Done when:* a reader who has never seen this initiative can tell, per cell, what
      was measured, against what, and what was not.

- [ ] **6.2** Migrate the durable half and record the change.
      *Files:* `CHANGELOG.md`, `.spec/STATUS.md`
      *Gate:* `CHANGELOG.md` carries a hand-written `### Added` entry under
      `[Unreleased]` (prose, never generated — `functualize-repo-ops`); `.spec/STATUS.md`
      carries the probe's durable findings, because `.spec/features/**` is deleted before
      merge and must not take the knowledge with it.
      *Done when:* both land in the **same push** as 6.1, before the leader's
      deletion-only clearing commit.

---

**Not in any wave — the leader's, after Code Review and QA** (issue → *Execution
contract* step 5): the `spec-artifacts-cleared` sequence, as a **deletion-only last
commit** removing `.spec/features/substrate-capability-probe` *and*
`contributor/architecture/research/**`, verified with
`git diff --name-status origin/master..HEAD`. Not an implementer task; listed so nobody
does it early and deletes the reviewer's own evidence.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "1.1",
        "1.2",
        "1.3"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "2.1",
        "2.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "3.1",
        "3.2"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "4.1",
        "4.2",
        "4.3"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "5.1"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "6.1",
        "6.2"
      ]
    }
  ]
}
```
