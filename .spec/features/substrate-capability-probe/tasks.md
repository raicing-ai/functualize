# FUN-25 — Tasks

Refined against the code by the Factory Designer, 2026-09-22. Each task is 1–3 files and
completable in one context window.

**Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked
tasks.** Waves map to the JSON graph at the foot of this file, which is what
`.claude/hooks/spec_gate.py` parses to unblock writes under `src/`.

## How to read a task

Each task is `### [ ] T<n> · <number> — <title>`, and carries **Files** (the hit set, not a
guess), at least one **Gate**, and **Done when**. A box goes `[x]` only when its own gate
is green *against the code as it actually stands* — never on the strength of its
description (`.spec/CONSTITUTION.md` → *Transitional Changes*).

A gate is a fenced `bash` block followed, on the very next line, by the values it was
authored against:

    now: `0` · after: `2`

`tests/spec/test_task_gates_still_hold.py` re-runs every counting gate of every **ticked**
task at HEAD and asserts it still returns `after:`. Consequences worth knowing before
writing one:

- **Counting commands only** — `rg -c` or `| wc -l`. A bare `rg -n` returns line numbers,
  and recording those as a count is a defect that test exists to catch.
- **One line, no `&&`, and not `uv run`.** A `uv run pytest …` block is still welcome
  beside a counted gate; it is skipped for a reason the test can name.
- **`now:` must differ from `after:`.** A gate satisfied before its task runs proves
  nothing by passing. If a count genuinely must not move, write the word `invariant`
  beside the values; if a later task legitimately invalidated the record, write
  `superseded`. Neither is used in this file.
- **An unticked task's `after:` is a prediction.** Replace it with the value you actually
  measured when you tick the box, and say so if it differs — that is what T11 of
  `run-request-entry` did when its wave-0 count had moved by wave 4.

### When `test_task_gates_still_hold.py` goes green

That test also asserts **at least twelve** gates parse, and it counts only the gates of
**ticked** tasks — so it is red until enough of this feature is done, by design. Measured
against this file, by ticking every box in a scratch copy and re-parsing:

| after | collected gates |
|---|---|
| wave 0 | 6 |
| wave 1 | 8 |
| wave 2 | 10 |
| **wave 3** | **13 — green from here** |
| wave 4 | 14 |
| wave 5 | 16 (plus 2 exempt) |

So `test-fast` is red on this branch until wave 3's boxes are ticked, and that is the
convention's own shape rather than a defect in the probe. Sixteen at completion against a
bar of twelve leaves four gates of slack, so dropping one later does not silently re-break
it.

Two rules that govern every task in waves 3–4:

- **Never invent a cell.** A missing credential yields `NOT MEASURED (no credentials)` or
  a skip. Never a failure, never a guess, never a fake standing in for a real service.
- **Gate at module level**, before any client is constructed, so a credential-less
  contributor gets a skip rather than a collection error. The idiom is already in this
  repo: `plugins/credentials/functualize-aws/tests/test_integration_floci.py:41-64`.

---

## Wave 0 — survey and instrument

### [x] T1 · 1.1 — Survey floci for conditional writes and transactions

**Files:** `tests/substrate_probe/_floci_survey.py`, `tests/substrate_probe/__init__.py`

Point the probe at floci and find out whether it implements S3 conditional writes
(`PutObject` with `If-None-Match`/`If-Match`) and DynamoDB `TransactWriteItems` **at all**.
This decides whether floci can back a `measured (emulator)` row for the wire-protocol
questions or only for the boring ones. It is itself a probe run, and its answer is
reported even when negative.

*(Member's order, Jira comment 10013, and acceptance criterion 8: this is task 1, before
the harness.)*

**Prior art — read before writing:** `test_integration_floci.py` (242 lines) already
carries the emulator idiom, the `docker run -d --name floci -p 4566:4566
floci/floci:latest` invocation, and the "no fallback to a fake" rule. Reuse it; do not
reinvent it.

**Gate — both capabilities are surveyed, each by forcing its condition to fail**
```bash
rg -c '^def _survey_' tests/substrate_probe/_floci_survey.py
```
now: `0` · after: `2`

*(`now` measured at `69ffee2` with `git grep -c '^def _survey_' 69ffee2 --
tests/substrate_probe/_floci_survey.py`, which returns nothing because the file did not
exist. Two functions, one per capability. Each probes by making the condition **fail**,
which is what catches the dangerous middle case: an endpoint that accepts a conditional
header and then ignores it, indistinguishable from success at the call site.)*

**Gate — it passes with the emulator, and skips without it; never fails**
```bash
uv run pytest -q tests/substrate_probe/_floci_survey.py
```
after: exit `0` with the endpoint set, and a named skip without it.

*(Not a counting command, so the gate test skips it for that stated reason. Measured both
ways: `1 passed in 0.71s` with `AWS_ENDPOINT_URL=http://localhost:4566`; `1 skipped`
naming the missing endpoint with the variable unset. Exit 5 there is
`NO_TESTS_COLLECTED` — every collected item skipped — not a failure.)*

**Gate — it gates on both the client and the endpoint, at module level**
```bash
rg -c 'importorskip|allow_module_level=True' tests/substrate_probe/_floci_survey.py
```
now: `0` · after: `2`

*(One for `boto3`, one for the endpoint. Both at import time, which is what makes "skips,
never fails" a property of the module rather than of each test in it.)*

**Done when:** the survey prints, for each of the two capabilities, one of *implemented* /
*not implemented* / *not reachable*, and that verdict is captured for T12.

**Verdict, recorded for T12** — floci 2.1.0 (`floci/floci:latest`, digest
`sha256:f5aa8c18…102db`), endpoint `http://localhost:4566`: S3 conditional writes
**implemented and enforced** (create-if-absent refused `PreconditionFailed 412` on a
present key; CAS against a stale ETag refused, against the current ETag accepted);
DynamoDB `TransactWriteItems` **implemented and atomic** (a transaction with one violated
condition cancelled with `TransactionCanceledException`, and neither wrote its sibling nor
modified the existing item). So floci may back `measured (emulator)` rows for the
wire-protocol questions — never a shipped field (AC3).

### [x] T2 · 1.2 — The credential/reachability gate and the probe's pytest marker

**Files:** `tests/substrate_probe/conftest.py`, `pyproject.toml`

One idiom, one place, used by every module after it: absent environment variables become a
*module-level* skip with a reason a reader can act on.

**Gate — the marker is registered, so the probe is a named tier rather than loose tests**
```bash
rg -c 'substrate_probe' pyproject.toml
```
now: `0` · after: `1`

*(`now` measured at `69ffee2` with `git grep -c 'substrate_probe' 69ffee2 --
pyproject.toml` — no matches. **Correction to this task as originally written:** it said
"beside the existing seven". There were **six** registered markers — `slow`,
`integration`, `perf_budget`, `real_state_root`, `installed_plugins`, `json_substrate` —
and the probe's is the seventh. The artifact was wrong; the code is right.)*

**Gate — a contributor with no cloud account runs the directory green (AC4, AC5)**
```bash
uv run pytest -q tests/substrate_probe/
```
after: exit `0`, zero failures, zero collection errors.

*(Not a counting command. Measured on a bare environment — `env | grep -Ei
'^(AWS|CLOUDFLARE|TURSO|SUPABASE|FUNCTUALIZE_PROBE)'` returns nothing — as `15 passed,
1 skipped` at this task, the skip being `_floci_survey.py` gating at module level.)*

**Gate — the skip is module-level, not per-test (AC5 depends on the difference)**
```bash
rg -c 'allow_module_level=True' tests/substrate_probe/conftest.py
```
now: `0` · after: `3`

*(`now` measured at `69ffee2`; the file did not exist. Three helpers — missing env vars, an
unreachable endpoint, an absent client — and each raises at *import* time, before any
client is constructed, so a credential-less contributor sees a skip rather than a
collection error.)*

**Done when:** a helper exists that turns "these env vars are absent" into a module-level
skip with a reason a reader can act on.

### [x] T3 · 1.3 — The ten probe questions as one backend-agnostic harness

**Files:** `tests/substrate_probe/harness.py`

Plain functions and frozen dataclasses — **no ABC, no shared backend base class**
(`.spec/CONSTITUTION.md` → *Forbidden Patterns*; `plan.md` §4).

**Gate — the ten `StoreProfile` fields are enumerated in one place**
```bash
rg -c 'field="' tests/substrate_probe/harness.py
```
now: `0` · after: `10`

*(`now` measured at `69ffee2` with `git grep -c 'field="' 69ffee2 --
tests/substrate_probe/harness.py` — the file did not exist. Ten is the count that matters:
`plan.md` §2's ten fields, transcribed from `07-the-design.md:60-104` rather than
invented. If this gate ever returns nine or eleven, the matrix has lost or grown a column.)*

**Gate — the harness imports nothing of ours**
```bash
rg -c '^(from|import) functualize' tests/substrate_probe/harness.py
```
now: `0` · after: `0` — **invariant**: the harness measures backends directly, so this
count must never move off zero. It is zero today and the gate exists to keep it there.

*(Explicitly exempt, and the only exemption in this file. `plan.md` §4's boundary rule:
only `tier_a.py` may import from `functualize`, because a probe that measures through our
adapter measures the adapter.)*

**Gate — composition, not inheritance: three frozen dataclasses and no base class**
```bash
rg -c 'class Question|class Answer|class Reading' tests/substrate_probe/harness.py
```
now: `0` · after: `3`

*(`.spec/CONSTITUTION.md` → *Forbidden Patterns* rules out ABC for ports, and `plan.md` §4
rejected a `ProbeBackend` base class because a shared base can only promise what every
backend does — the ADR-022 intersection mistake in test clothing. This counts the shape
that replaced it.)*

**Done when:** the ten field names of `plan.md` §2 are enumerated in one place, each with
its question and the evidence level of the answer it yields, and a backend module can
answer a subset without inheriting anything.

*(Reading recorded at execution: the evidence level is a property of an **answer**, not of
a question — the same question yields `measured (real service)` from AWS and
`measured (emulator)` from floci — so `harness.py` defines the four levels as a
first-class type carried by every `Answer`, while each `Question` carries its prose and
`answered_by`. That satisfies the done-when's meaning, not its literal wording.)*

## Wave 1 — the three fakes (Tier A instruments)

These model **vendor driver constraints**, not our port. None implements `StoreSubstrate`.

### [ ] T4 · 2.1 — `BatchOnlySqliteDriver`

**Files:** `tests/substrate_probe/fakes.py`

Refuses interactive transactions, accepts exactly one batch. Models D1, which has no
`BEGIN`/`COMMIT` (`durability-outsourcing/05-cloudflare.md` §A.3).

**Gate — the instrument exists**
```bash
rg -c 'class BatchOnlySqliteDriver' tests/substrate_probe/fakes.py
```
now: `0` · after: `1`

**Done when:** an attempt to hold a transaction open across a Python decision raises, and a
single batch commits — both with no network and no Docker.

### [ ] T5 · 2.2 — `FakeObjectStore` and `FakeItemStore`

**Files:** `tests/substrate_probe/fakes.py`

An S3 with no multi-key atomicity and conditional-write semantics; a DynamoDB with
`TransactWriteItems`.

**Gate — both instruments exist**
```bash
rg -c 'class FakeObjectStore|class FakeItemStore' tests/substrate_probe/fakes.py
```
now: `0` · after: `2`

**Done when:** each fake answers the harness's questions and every answer it produces is
stamped `measured (fake)` — never `measured (real service)`.

## Wave 2 — Tier A (no network, no Docker, no credentials)

### [ ] T6 · 3.1 — Tier A backends: JSON filesystem, local SQLite, the three fakes

**Files:** `tests/substrate_probe/tier_a.py`

**This is the one module permitted to import from `functualize`** — for these two the
shipping substrate *is* the backend under test, which is what makes AC3 satisfiable
without any cloud account.

**Gate — five backends produce a reading**
```bash
rg -c 'reading\(' tests/substrate_probe/tier_a.py
```
now: `0` · after: `5`

*(Predicted. Measure it and correct the number when ticking.)*

**Gate — the boundary rule still holds directory-wide**
```bash
rg -c '^(from|import) functualize' tests/substrate_probe/d1.py tests/substrate_probe/dynamodb.py tests/substrate_probe/s3.py tests/substrate_probe/tier_c.py tests/substrate_probe/harness.py
```
now: `0` · after: `0` — **invariant**: every probe module except `tier_a.py` must stay at
zero. This is `contracts.md`'s directory-wide rule written as a count.

**Done when:** every one of the ten fields has a value for the filesystem and for local
SQLite, each stamped `measured (real service)`.

### [ ] T7 · 3.2 — Regression guard: a revision is an opaque token

**Files:** `tests/primitives/test_substrate.py` (494 lines at `69ffee2`; ~+25)

Open question 3 is already answered (`spec.md` → *Findings*; FUN-24 landed
`Revision = NewType("Revision", str)`), so this task does **not** probe it — it stops the
property silently regressing when the first remote substrate arrives.

**Gate — the guard exists**
```bash
rg -c 'def test_a_revision_is_an_opaque_token' tests/primitives/test_substrate.py
```
now: `0` · after: `1`

**Gate — and it can fail**
```bash
uv run pytest -q tests/primitives/test_substrate.py
```
after: green — then break `_revision_of` (`_primitives/substrate.py:60-68`) to return a
constant and watch this new test go red. **Commit before sabotaging**
(`.spec/CONSTITUTION.md`; `git checkout -- <file>` reverts everything uncommitted in it).

**Done when:** a test asserts a revision round-trips as an opaque token and is never
ordered or arithmetically combined, and the sabotage was observed to turn it red.

## Wave 3 — Tier B (real services; skip, never fail)

### [ ] T8 · 4.1 — Cloudflare D1

**Files:** `tests/substrate_probe/d1.py`

Answers **open question 2 — absolute REST latency from a developer laptop**, so record the
numbers, not just a verdict.

**Transport:** stdlib `urllib.request`. **Not `httpx`** — no first-party package declares
it (`rg '"httpx' pyproject.toml plugins/*/*/pyproject.toml` → nothing); it is present only
transitively, and stdlib keeps a client library out of a latency measurement.

**Gate — the transport is stdlib, not an undeclared transitive dependency**
```bash
rg -c 'urllib' tests/substrate_probe/d1.py
```
now: `0` · after: `1`

*(Predicted. Measure and correct when ticking.)*

**Done when:** `interactive_transaction`, `max_document_bytes` (the documented 2 MB row
cap — **verify it, do not copy it**) and a latency distribution are recorded; or each is
`NOT MEASURED (no credentials)` with its reason. With `CLOUDFLARE_*` unset the module
skips at module level.

### [ ] T9 · 4.2 — AWS DynamoDB (floci first, then real)

**Files:** `tests/substrate_probe/dynamodb.py`

Two evidence levels from one module: whatever floci answers is `measured (emulator)` and
may **never** back a shipped field; the real service is `measured (real service)`.

**Gate — the module answers**
```bash
rg -c 'reading\(' tests/substrate_probe/dynamodb.py
```
now: `0` · after: `1`

*(Predicted. Measure and correct when ticking.)*

**Done when:** `TransactWriteItems` behaviour under contention is measured, or recorded
`NOT MEASURED (no credentials)` with T1's floci verdict beside it.

### [ ] T10 · 4.3 — AWS S3 **and Cloudflare R2**

**Files:** `tests/substrate_probe/s3.py`, `.env.example` (add `FUNCTUALIZE_PROBE_R2_*`)

R2 is S3-API-compatible, so it is the same module against a different endpoint, exactly as
`test_integration_floci.py:12-14` already reaches an emulator through `AWS_ENDPOINT_URL`.
**This task owns open question 1 — is R2's conditional `PutObject` atomic under concurrent
writers?** It is the single most important unknown in the research
(`09-verdict.md:47-50`), and the pre-loaded scaffold had no task for it.

**Gate — two endpoints, two readings**
```bash
rg -c 'reading\(' tests/substrate_probe/s3.py
```
now: `0` · after: `2`

*(Predicted — one for S3, one for R2. Measure and correct when ticking.)*

**Done when:** open question 1 is answered with a contention measurement naming the number
of winning writers, or recorded `NOT MEASURED (no R2 credentials)` — stated, never omitted.

## Wave 4 — Tier C (cheapest-last)

### [ ] T11 · 5.1 — Turso/libSQL and Supabase Postgres, if cheap

**Files:** `tests/substrate_probe/tier_c.py`

Turso is the seventh column; Supabase is an eighth and is expected to stay `NOT MEASURED`.

**Gate — both are attempted**
```bash
rg -c 'reading\(' tests/substrate_probe/tier_c.py
```
now: `0` · after: `2`

*(Predicted. Measure and correct when ticking.)*

**Done when:** each is measured or carries an explicit `NOT MEASURED` reason; clients or
credentials absent ⇒ module skip, suite still green.

## Wave 5 — publish

### [ ] T12 · 6.1 — The results matrix, and the three open questions settled

**Files:** `contributor/reference/substrate-capability-matrix.md`

**Path amended** from the pre-loaded scaffold's
`contributor/architecture/research/substrate-capability-matrix.md`. That tree **cannot
reach `master`** under the member rule of 2026-09-22 and, unlike `.spec/features/**`, has
**no** CI guard to catch the mistake, so publishing there would leave the initiative's only
measured artifact unmergeable. `contributor/reference/` is the convention for a durable,
citable reference, and FUN-17…FUN-22 must be able to cite this from `master`. *(Issue →
Deliverable placement; supersedable by the member.)*

**Gate — every one of the ten fields has a row**
```bash
rg -c 'cross_aggregate_atomicity|fencing|multi_process|multi_machine|durable_outbox|versioned_migrations|interactive_transaction|max_document_bytes|offline_capable|^\| .remote.' contributor/reference/substrate-capability-matrix.md
```
now: `0` · after: `10`

*(Predicted — one matching row per field. Measure and correct when ticking. `remote` is
anchored to a row start because it is a substring of other words.)*

**Done when:** ten question rows × seven backend columns; **every** cell carries one of
the four evidence levels or an explicit `NOT MEASURED` with a reason; open questions 1, 2
and 3 each have a heading and a verdict. Q3's verdict is already written — `spec.md` →
*Findings* — and is transcribed, not re-derived.

### [ ] T13 · 6.2 — Migrate the durable half and record the change

**Files:** `CHANGELOG.md`, `.spec/STATUS.md`

**Gate — the change is recorded in hand-written prose**
```bash
rg -c 'substrate capability probe|FUN-25' CHANGELOG.md
```
now: `0` · after: `1`

*(Predicted. `CHANGELOG.md` is hand-written, never generated.)*

**Done when:** `CHANGELOG.md` carries an `### Added` entry under `[Unreleased]`, and
`.spec/STATUS.md` carries the probe's durable findings — because `.spec/features/**` is
deleted before merge and must not take the knowledge with it. Both land in the **same
push** as T12, before the leader's deletion-only clearing commit.

---

## Recorded deviations

The issue requires every deviation from the pre-loaded scaffold to be recorded here with
its reason. Four, in the order they were decided.

1. **The matrix path** — `contributor/architecture/research/` → `contributor/reference/`.
   Reason in T12. Decided by the Factory Designer, ratified by the issue's *Deliverable
   placement* section.

2. **R2 given a task, and the roster reconciled to seven columns.** The scaffold's title
   said six backends, AC1 said seven, `tasks.md` enumerated ten, and the research table
   listed five — while **open question 1 is about R2**, which had no task at all. T10 now
   owns it. Flagged for maintainer review (`plan.md` §8); not blocking.

3. **`tests/substrate_probe/test_gating.py` and `test_harness.py`** — one extra file each,
   beyond T2's and T3's declared scopes. *Accepted by the leader, 2026-09-22T18:02Z.*
   Without a runnable file the directory run exits `5` (`NO_TESTS_COLLECTED`), so neither
   task's own gate could be run as written; and wave 0 *is* the instrument, so an
   instrument with no test of its own is how a wrong measurement reaches the matrix
   silently. Each was shown capable of failing by sabotage before the box was ticked.

4. **`pytest_collect_file` in `tests/substrate_probe/conftest.py`.** *Accepted by the
   leader, 2026-09-22T18:02Z.* This file fixes the measurement modules' names —
   `_floci_survey.py`, `tier_a.py`, `d1.py`, `s3.py`, `tier_c.py` — and **none matches
   pytest's default `python_files` patterns**, so without the hook a plain `uv run pytest`
   collects nothing from the directory. `contracts.md` asserts the opposite as a property
   CI relies on, and AC4/AC5 rest on it. Measured before the hook: the directory run
   exited `5`. The hook makes the artifact's claim true rather than vacuous, and leaves
   `test_*.py` to the built-in collector so nothing is collected twice.

5. **This file's format.** Converted from `- [ ] **1.1**` bullets with italic `*Gate:*`
   prose to the repo-native `### [x] T<n>` headings with fenced `bash` gates and recorded
   `now:`/`after:` values, on the leader's instruction of 2026-09-22T18:02Z.
   `tests/spec/test_task_gates_still_hold.py` parses `.spec/features/*/tasks.md` for
   exactly that shape and asserts at least twelve gates parse; the prose form parsed to
   **zero**, so `test-fast` could never be green while these artifacts are on the branch —
   and the pre-merge sequence requires exactly that state to be green. The fix is the
   artifact conforming; `tests/spec/**` was not touched. Task numbering (`1.1`…`6.2`), the
   wave boundaries, the tick state and the dependency graph are unchanged — `T<n>` is an
   additional label the parser requires, carried beside the original number, not a
   renumbering.

**Not in any wave — the leader's, after Code Review and QA** (issue → *Execution contract*
step 5): the `spec-artifacts-cleared` sequence, as a **deletion-only last commit** removing
`.spec/features/substrate-capability-probe` *and* `contributor/architecture/research/**`,
verified with `git diff --name-status origin/master..HEAD`. Not an implementer task; listed
so nobody does it early and deletes the reviewer's own evidence.

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
