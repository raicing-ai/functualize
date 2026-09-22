# FUN-25 — Plan

**Status:** architecture gate **SATISFIED** (Factory Designer, 2026-09-22, branch
`spike/substrate-capability-probe` @ `68fa1a1`, `origin/master` @ `7ba663c`).
The scaffold's `TODO` diagrams are replaced below. 3b (blast radius, tasks) follows in
`tasks.md`.

## 1. Retrieval — the three tools, by absolute path

All three ran against **`/home/ubuntu/orca/workspaces/functualize/rp-25-capability-probe`**,
never a bare project name.

| Tool | How it was reached | Result |
|---|---|---|
| **zvec-grep** | `zg` at `/usr/local/bin/zg`. No index existed on this worktree; built under the standing authorization (`.claude/rules/spec-workflow.md` → *Retrieval discipline*). `zg status` confirms the root is the worktree, not the parent checkout. | 843 files, 13 271 entities, **1 m 01 s**, `.zvec-grep/index.zvec`. Queries in §2. |
| **serena** | MCP transport **failed** in this runtime (`CONNECTION_CLOSED`). The CLI is reachable — `uvx --from git+https://github.com/oraios/serena serena` — so serena was driven over stdio JSON-RPC directly with `--project <abs path>`. *A tool you cannot reach is not a tool that is absent.* | `get_symbols_overview` on both substrate modules; `find_referencing_symbols` on `Stored`. |
| **graphify** | MCP transport **failed** (`EACCES`, `/root/.local/bin/graphify-mcp`). CLI reachable at `/usr/local/bin/graphify`; `graphify-out/graph.json` is committed and warm. | `graphify explain "StoreSubstrate"` → degree 33, every edge direction below. |

**Finding — the committed graph is stale.** `graph.json` (from `d554713`, 2026-09-21)
places `StoreSubstrate` at `protocols.py:L760`; it is at **`:791`** (`rg -n "class
StoreSubstrate"`). It also reports `plugins/functualize-tasks-local/`, which is now
`plugins/domains/functualize-tasks-local/`. Edge *directions* are correct and were used;
its *coordinates* were not trusted and every line number here was re-measured with `rg`.

**Finding — the codemaps do not cover this region.** `contributor/architecture/codemaps/`
mentions a substrate three times, all incidental (`modules.md:153`, `entry-points.md:27`,
`overview.md:73`); none describes the port, the stores above it, or the implementations
beside it. So there is **no codemap for the diagrams below to contradict**. That is a gap
in the codemaps, not a licence — recorded here, and out of scope to fix in a spike.

## 2. The premise the whole ticket rests on, measured

> **`StoreProfile` does not exist in this codebase.**

```console
$ rg -n "StoreProfile" src/ plugins/ tests/ | wc -l
0
$ rg -n "StoreProfile" . -g '!graphify-out' --stats   # 25 matches, 11 files
```

All 25 are research prose under `contributor/architecture/research/` plus one comment in
`.env.example:19`. The type is a **proposal** in
`durability-outsourcing/07-the-design.md:60` and
`runtime-persistence-engine-owned/05-the-design.md:80`, owned by FUN-17.

This is the single most important shape fact in the ticket, and it settles the boundary
question: the probe cannot measure `StoreProfile` fields *through* functualize, because
there is no `StoreProfile` and no remote substrate to measure them through. **It measures
the backends directly and reports what a future `StoreProfile` would have to say.**

The ten fields it must produce a column for are `07-the-design.md:60-104` minus `name`
and `description`: `cross_aggregate_atomicity`, `fencing`, `multi_process`,
`multi_machine`, `durable_outbox`, `versioned_migrations`, `interactive_transaction`,
`remote`, `max_document_bytes`, `offline_capable`. Counted, not assumed — the dataclass
lists twelve attributes, two of which are labels.

## 3. BEFORE

Layers per `.spec/CONSTITUTION.md` → *Layer Dependency Rules*. `↓` = "is imported by".

```
  [_types]      src/functualize/_types/protocols.py
                  :764  Revision = NewType("Revision", str)        <- str since 7ba663c
                  :768  @dataclass(frozen=True, slots=True) Stored
                  :791  @runtime_checkable class StoreSubstrate(Protocol)
                          .read()  :824   .write()  :838   .lock()
                        ... no StoreProfile. Nothing declares a guarantee.
                     │
                     ▼ imports (EXTRACTED, graphify)
  [_primitives] src/functualize/_primitives/substrate.py
                  JsonFileSubstrate      _revision_of() = blake2b of the bytes  :60-68
                  substrate_for_project()                                       :253
                     │
                     ▼ uses (INFERRED, graphify — 5 stores, one floor)
  [_primitives] scope_store.py:124  scope_state_store.py:98  run_store.py:136
                fresh_store.py:81    shell_history.py:71
                     │
                     ▼
  [_engine]     _engine/executor.py · _engine/capabilities/state.py
                     │
                     ▼
  [app/ public] app/core.py:353  install_substrate(substrate: StoreSubstrate)

  ── beside the layer stack, all depending only on [_types] ──────────────────────
  plugins/substrates/functualize-substrate-sqlite/…/substrate.py
        SQLiteSubstrate   revision INTEGER column :58, stringified at the
                          Python boundary :112  Stored(…, revision=Revision(str(row[1])))
  examples/plugins/custom_state_backend/…/_backend.py     MemorySubstrate
  tests/primitives/test_substrate.py                      InMemory, OneLock
  plugins/domains/functualize-tasks-local/tests/…         _NoLockSubstrate

  ── the test-side switch that already exists ────────────────────────────────────
  tests/conftest.py:397-451  _alternate_substrate
        FUNCTUALIZE_TEST_SUBSTRATE=sqlite  --monkeypatch-->  JsonFileSubstrate.for_project
        marker `json_substrate` opts a test out

  ── the emulator idiom that already exists ──────────────────────────────────────
  plugins/credentials/functualize-aws/tests/test_integration_floci.py (242 lines)
        pytest.importorskip("boto3");  _reachable(AWS_ENDPOINT_URL) TCP probe
        -> pytest.skip(allow_module_level=True);  pytestmark = mark.integration
        "It does *not* fall back to a fake: a green run that silently tested
         nothing is worse than a skip that says so."   :17-19
```

### Smells the BEFORE already carries

Named from the **`design-patterns-refactoring`** skill (Refactoring.Guru catalogue,
user-level — see §7).

- **Shotgun surgery** (ch34) — *the substrate double*. Measured:
  `rg -c "def read\(self, key: str\) -> Stored \| None" src/ plugins/ tests/ examples/`
  returns **7** definitions across 6 files: 1 port declaration, 2 shipping
  implementations, and **4 hand-rolled doubles** (`MemorySubstrate`, `InMemory`,
  `OneLock`, `_NoLockSubstrate`). Widening the six-member port means editing six sites.
  *Not this ticket's to fix* — it is FUN-17's, and naming it here is how FUN-17 inherits it.
- **Primitive obsession** (ch32) — **already removed**, by FUN-24. `revision: int`
  (`git show 7ba663c~1:src/functualize/_types/protocols.py`, line 784) became
  `Revision = NewType("Revision", str)`. Recorded because it is the ticket's own
  worked example, and because it retires an acceptance criterion — §5.
- **Speculative generality** (ch35) — *latent, in the spec, not the code*. `StoreProfile`
  is a ten-field abstraction with **zero** implementations. The probe is precisely the
  instrument that stops it shipping speculative; that is the ticket's whole thesis
  (ADR-022's failure mode, `spec.md` → *Why*).

## 4. AFTER

The probe is a **closed leaf**. It adds no layer, no port, no `src/` symbol, and no
import into any `_`-prefixed package.

```
  ┌─ tests/substrate_probe/   [new — not a layer; a measurement instrument] ─────┐
  │                                                                              │
  │  conftest.py     credential + reachability gating; ONE skip idiom, lifted    │
  │                  verbatim from test_integration_floci.py:41-64               │
  │  harness.py      the ten questions as data. Imports NOTHING from functualize.│
  │                     Question(id, field, ask: Callable) -> Answer(value,       │
  │                     evidence: Literal["real","emulator","fake","unmeasured"])│
  │  fakes.py        BatchOnlySqliteDriver · FakeObjectStore · FakeItemStore     │
  │                     instruments, NOT StoreSubstrate implementations          │
  │  _floci_survey.py  does floci implement S3 conditional writes and            │
  │                     DynamoDB TransactWriteItems AT ALL?  (task 1.1)          │
  │                                                                              │
  │  tier_a.py ──────┐  d1.py   dynamodb.py   s3.py (+R2)   tier_c.py            │
  └──────────────────┼──────────────────────────────────────────────────────────┘
                     │                    │
    the ONE permitted│import              │ boto3 / urllib.request only
                     ▼                    ▼
  [_primitives] JsonFileSubstrate      AWS · Cloudflare · Turso · Supabase
  [plugin]      SQLiteSubstrate           (network, credential-gated, SKIP-not-fail)
                     │
                     ▼ (unchanged, untouched)
  [_types] protocols.py   ── no edit, no new symbol, no new member ──

  output ─▶ contributor/reference/substrate-capability-matrix.md   [publishable to master]
```

**The boundary rule, stated so a reviewer can check it in one command:**

> Only `tier_a.py` may import from `functualize`. Every other module in
> `tests/substrate_probe/` imports the backend's own client and nothing of ours.

```console
$ rg -n "^(from|import) functualize" tests/substrate_probe/ | grep -v "^tests/substrate_probe/tier_a.py"
# must be empty
```

**Why the probe does not import `StoreSubstrate`.** A probe that measured through our
adapter would measure *the adapter*, and the entire reason this ticket precedes FUN-17 is
to learn what backends do **before** the port is frozen. Importing the port would make the
spike a de-facto FUN-17 implementation — the "one ticket quietly absorbing the next one's
work" failure `spec.md` → *Out of scope* names. `tier_a.py` is the deliberate exception:
for the filesystem and local SQLite the shipping substrate **is** the backend, and AC3
demands a `measured (real service)` row for every field of a shipping backend.

### Smells this AFTER introduces, and what was done about them

Gate step 4 — checked on each candidate, not only on the settled one.

| Candidate AFTER | Smell it introduced (catalogue) | Verdict |
|---|---|---|
| One `probe.py` parameterised over all backends | **Long method** / **divergent change** (ch32, ch34) — one module changing for eight unrelated vendor reasons | **Rejected.** One module per backend. |
| A `ProbeBackend` ABC that each backend subclasses | **Forbidden pattern** — `.spec/CONSTITUTION.md` → *ABC for ports*. Also re-creates the intersection contract ADR-022 exists to forbid: a shared base can only promise what all eight do. | **Rejected — blocker, not a compromise.** `harness.py` holds plain functions and a frozen dataclass; no inheritance. |
| Probe fakes implementing `StoreSubstrate` so they slot into `_alternate_substrate` | **Speculative generality** (ch35), and it silently converts the spike into FUN-17 | **Rejected.** The fakes model *vendor drivers* (a D1 that has no `BEGIN`, an S3 that has no multi-key atomicity), not our port. |
| Reusing `tests/conftest.py::_alternate_substrate` to route Tier A | **Feature envy** (ch36) — the probe would reach into a fixture whose job is the *root suite's* substrate choice, and would inherit its `json_substrate` skip | **Rejected.** `tests/substrate_probe/conftest.py` is its own, and Tier A constructs substrates directly. |

## 5. Findings that change `spec.md` — the Specify↔Plan iteration

Gate step 4 requires revising `spec.md` where the architecture work shows it wrong,
rather than planning around it. Three did.

### 5.1 Open question 3 is **answered now**, at planning time — it is not a probe task

`spec.md` AC6 and the issue's AC7 ask "whether anything in the tree depends on
`Stored.revision` being an `int`". `09-verdict.md:56` proposes the falsifier; this branch
is rebased onto FUN-24, so it can simply be run.

```console
$ git show 7ba663c~1:src/functualize/_types/protocols.py | rg -n "revision: "
784:    revision: int
$ rg -n "^Revision" src/functualize/_types/protocols.py
764:Revision = NewType("Revision", str)
$ rg -n "revision\s*[+\-*/]|revision\s*[<>]|int\(\s*\w*revision|sorted\(.*revision|max\(.*revision" src/ plugins/ tests/
plugins/substrates/functualize-substrate-sqlite/…/substrate.py:130   "revision = documents.revision + 1",
plugins/substrates/functualize-substrate-sqlite/…/substrate.py:135   "UPDATE documents SET … revision = revision + 1 "
```

**Answer: nothing does.** The two hits are **SQL text** operating on the sqlite plugin's
own `revision INTEGER` column (`:58`); the value crosses into Python as a string at
`:112` — `Stored(data=data, revision=Revision(str(row[1])))`. No Python expression in
`src/`, `plugins/` or `tests/` orders a revision or does arithmetic on one. FUN-24 already
made the type opaque; `07-the-design.md` §6.1's repair is **landed**.

Consequence for this ticket: the question is **retired, with evidence**, not probed. What
remains is worth a guard, so the property cannot silently regress when the first remote
substrate lands — task **3.2**.

### 5.2 The backend roster contradicts itself, and R2 has no task

Three counts disagree, and I am not entitled to pick one silently:

| Source | Says |
|---|---|
| Issue title | "six backends" |
| `spec.md` AC1 / issue AC1 | "ten questions **× seven backends**" |
| `tasks.md` (scaffold) | JSON, SQLite, 3 fakes, D1, DynamoDB, S3, Turso, Supabase = **ten columns** |
| `07-the-design.md` §3 table | filesystem, SQLite, D1, S3, **R2** = five |

Worse: **open question 1 is about R2**, and the scaffold's `tasks.md` has **no R2 task**,
so AC6/AC7 is unreachable as written.

**Recommended resolution**, written into `spec.md` and `tasks.md` so work is not blocked,
and flagged for maintainer review (§8):

- **Seven backend columns** — the AC1 number is the binding gate text: filesystem,
  local SQLite, Cloudflare D1, AWS S3, **Cloudflare R2**, AWS DynamoDB, Turso/libSQL.
- **"Six"** in the title reads as the six non-incumbent candidates — everything but the
  filesystem, which is the incumbent rather than a candidate. The two numbers are then
  consistent rather than contradictory.
- **Supabase Postgres** is an eighth, Tier C, expected `NOT MEASURED`.
- **The three fakes are instruments, not backends.** They populate the *evidence* column
  (`measured (fake)`), never a column of their own. That is what keeps AC2 meaningful.
- **R2 needs no new module.** R2 is S3-API-compatible, so task **4.3** covers both by
  swapping the endpoint — which is exactly how `test_integration_floci.py:12-14` already
  reaches an emulator through `AWS_ENDPOINT_URL`.

### 5.3 AC3 is unsatisfiable on this host, and that is a fact about the host

AC3 — every `StoreProfile` field of a **shipping** backend backed by a `measured (real
service)` row. Measured 2026-09-22: this host has no cloud credentials. But *shipping*
today means exactly two backends, `JsonFileSubstrate` and `SQLiteSubstrate`, and for those
the real service is local and runs with no credentials at all. **AC3 is fully satisfiable
for every backend that ships today.** It is unsatisfiable only for backends that do not
ship yet — which is the correct state for a spike whose output is advice to FUN-17.
`spec.md` now says so, so a reviewer does not read a credential gap as a failed criterion.

## 6. Files expected to change

Sizes measured on this tree, not carried from the scaffold.

| File | Now | Change |
|---|---|---|
| `tests/substrate_probe/__init__.py` | — | new, trivial |
| `tests/substrate_probe/conftest.py` | — | new, ~90 — the one skip/gating idiom |
| `tests/substrate_probe/harness.py` | — | new, ~150 — ten questions as data |
| `tests/substrate_probe/fakes.py` | — | new, ~200 — three instruments |
| `tests/substrate_probe/_floci_survey.py` | — | new, ~150 — task 1.1 |
| `tests/substrate_probe/tier_a.py` | — | new, ~200 |
| `tests/substrate_probe/d1.py` | — | new, ~180 |
| `tests/substrate_probe/dynamodb.py` | — | new, ~180 |
| `tests/substrate_probe/s3.py` | — | new, ~200 — S3 **and** R2 |
| `tests/substrate_probe/tier_c.py` | — | new, ~150 |
| `tests/primitives/test_substrate.py` | 494 (`wc -l`) | **+~25** — revision-opacity guard (task 3.2) |
| `pyproject.toml` | 1 file | **+4** — register the `substrate_probe` marker beside the existing seven |
| `contributor/reference/substrate-capability-matrix.md` | — | new — **the deliverable** |
| `CHANGELOG.md` | hand-written prose | one `### Added` entry |
| `.spec/STATUS.md` | — | the durable half, migrated before the clearing commit |

**Path deviation, recorded as the issue requires.** The scaffold named
`contributor/architecture/research/substrate-capability-matrix.md`. That tree **cannot
reach `master`** under the member rule of 2026-09-22 and, unlike `.spec/features/**`, has
*no* CI guard to catch it. The matrix lands at
**`contributor/reference/substrate-capability-matrix.md`** — the convention for a durable,
citable reference, and reachable from `master` so FUN-17…FUN-22 can cite it.
`tasks.md` 6.1 is amended accordingly.

### Two environment facts the implementer must not rediscover the hard way

- **`boto3` is available in CI's test jobs.** `test-fast`/`test-full` run
  `uv sync --all-extras`, and the `all` extra includes `functualize-aws`, which pins
  `boto3>=1.34.0`. Measured locally: `boto3 1.43.29`. `pytest.importorskip("boto3")`
  stays anyway — it costs one line and covers a bare `uv sync`.
- **`httpx` is NOT declared by any first-party package.** `rg '"httpx' pyproject.toml
  plugins/*/*/pyproject.toml` returns nothing; it is present only transitively
  (`httpx 0.28.1` locally). The D1 REST probe therefore uses **stdlib
  `urllib.request`**, not `httpx`. It is also the better instrument: open question 2 asks
  for *absolute latency*, and stdlib removes a client library from the measurement.
- **`grep -rn boto3 src/functualize/` must stay at 0** (`functualize-aws/pyproject.toml`,
  ADR-016 §5.1). Verified 0 today. The probe lives in `tests/`, so it cannot break this —
  but it is the rule that explains why no probe code may drift into `src/`.

## 7. Design skills consulted

- [x] **`python-design-patterns`** (in-repo, `.claude/skills/python-design-patterns` →
      `.agents/skills/python-design-patterns`). Loaded. Used for: *ABC for ports* refusal,
      composition over inheritance in `harness.py`, KISS on the one-module-per-backend
      call.
- [x] **`design-patterns-refactoring`** (user-level, Refactoring.Guru catalogue + *Dive
      Into Design Patterns*). Loaded. This is the smell vocabulary used above.
- **Verified, not assumed** (`.spec/CONSTITUTION.md` → *a description of a thing is not
  the thing*): the in-repo skill is 2 files, and
  `rg -ic "long method|feature envy|shotgun surgery|divergent change|middle man|primitive obsession" .claude/skills/python-design-patterns/`
  exits **1 — zero matches**. `.claude/rules/spec-workflow.md`'s measured claim still
  holds. The catalogue names in this document come from the user-level skill, which **is**
  present in this session. An executor on a machine without it should keep these names
  (they are written down here) rather than re-derive them.

## Surviving smells

Required section. Each: catalogue name, where, why accepted, review flag.

1. **Duplicated code** (ch35 family) **across the per-backend probe modules** —
   `tests/substrate_probe/{d1,dynamodb,s3,tier_c}.py`.
   *Accepted, and carried forward from the scaffold unchanged.* Each module is a
   standalone measurement whose value is being readable in isolation; sharing the setup
   would hide exactly the differences the probe exists to find, and a shared base would be
   the ADR-022 intersection mistake in test clothing. Rule of Three (ch30) is deliberately
   **not** applied: these three occurrences are evidence, not duplication to be removed.
   **Needs maintainer review: no.** It is the scaffold's own declared position and the
   architecture work did not disturb it.

2. **Speculative generality** (ch35) — `tests/substrate_probe/harness.py`'s ten-question
   structure is shaped by a `StoreProfile` that **does not exist** (§2).
   *Accepted, with a bounded life.* This is the one genuinely uncomfortable entry: the
   instrument is built to the shape of a proposal. It is accepted because the alternative
   — measuring backends against no structure — produces a pile of observations no one can
   diff, and because the spike's output is a markdown table, so a wrong shape costs a
   rewrite of one document rather than a migration. If FUN-17 lands a different
   `StoreProfile`, the matrix is re-keyed; nothing in `src/` depends on the guess.
   **Needs maintainer review: YES** — see §8.

3. **Shotgun surgery** (ch34) — the four hand-rolled substrate doubles (§3).
   *Surviving, untouched, and explicitly not this ticket's.* Named so FUN-17 inherits a
   diagnosis rather than a surprise. **Needs maintainer review: no** (it is a handoff note).

**No forbidden pattern survives.** Checked against `.spec/CONSTITUTION.md` → *Forbidden
Patterns*, one by one: no god object (largest planned module ~200 LOC); no peer-layer
cross-import (the probe imports no `_`-prefixed package except `_primitives.substrate`
from `tier_a.py`, and `tests/` is not a layer); no global mutable state (the harness is
frozen dataclasses; the one module-level value is a read-only env snapshot, the same shape
as `test_integration_floci.py:36`); **no ABC for ports** (rejected in §4's table); no
implicit `Callable` port convention (`Question.ask` is a typed field on a frozen dataclass,
not a bare convention); no hard-coded config paths; no `_cli/` import; no
`DeprecationWarning` shim.

## 8. *Needs maintainer review* — raised by name, not merely recorded

Both are put to
[@m.hakim.adiprasetya](mention://member/1df5f0eb-717d-4e3c-8c1c-9029920bbf39) on the
Multica issue at the same time as the task list, per the gate's final rule.

1. **The backend roster (§5.2).** Six, seven, or ten columns — and R2 currently has no
   task while owning open question 1. Recommendation written into `spec.md`/`tasks.md`:
   seven columns including R2, fakes as evidence not columns, R2 via `s3.py`'s endpoint.
   *Blocking?* No — task 4.3 is written to cover both, so wave 3 proceeds either way.
2. **Surviving smell 2 — building the harness to a `StoreProfile` that does not exist.**
   The honest framing: this spike's instrument is shaped by FUN-17's unshipped proposal.
   Accepting it is accepting that a wrong guess costs one markdown rewrite.
   *Blocking?* No.

Also raised, though it is a credential decision rather than an architecture one: **Tier
B/C access** (issue → *Human-gated items*). Without it those cells are `NOT MEASURED (no
credentials)`. Per §5.3 this does **not** fail AC3 for any backend that ships today.
