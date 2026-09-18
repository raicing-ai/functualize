# substrate-conformance — research / handoff

**Written 2026-09-18, from `feat/plugin-host-protocol` while executing
`plugin-taxonomy`. Branch base: `origin/master` @ `7f86d94`.**

This is a **handoff, not a spec.** Nothing here has been built. It exists so the
next session can run `/agentic-specify` with the measurements already taken and
the false starts already ruled out.

Every number below was produced by running the command shown, in this worktree,
against `7f86d94`. Where a count differs on `feat/plugin-host-protocol`, that is
said explicitly — three of the couplings described here were already removed
there, which is how the problem was found.

---

## 1 · Why this exists

`plugin-taxonomy` made `functualize-state-sqlite` load for the first time. Until
then it declared itself in an entry-point group nothing read, so
`pip install functualize-state-sqlite` installed a package that did nothing, and
**the alternative substrate was never exercised by an ordinary run.**

The moment it loaded, 60 tests failed. Fifty-seven were one latent bug in the
plugin; the rest were tests asserting a JSON filename where the subject was not
the file format. None of that was visible while the plugin was inert.

That is the shape of the problem. `StoreSubstrate` is a real port with two real
implementations, and the second one was effectively untested in situ.

---

## 2 · What `SQLiteSubstrate` actually is

Worth stating plainly, because "SQLite backend" suggests a relational model and
it is not one.

```
$ grep -A5 'CREATE TABLE' plugins/functualize-state-sqlite/src/functualize_state_sqlite/substrate.py
CREATE TABLE IF NOT EXISTS documents (
  key TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL
)
```

One table. `payload` is a JSON string. Every substrate document — `fresh`,
`scopes`, `scope-state/<id>`, `runs`, `shell-history` — is one row keyed by its
document name. 225 LOC.

**It is not "JSON with extra steps", and the difference is the point of the
port.** It uses SQLite for exactly the guarantees a file cannot give:

| Mechanism | What it buys |
|---|---|
| `revision INTEGER`, `UPDATE … SET revision = revision + 1` | real compare-and-swap in one statement — what `write(expect=)` promises |
| `INSERT … ON CONFLICT DO UPDATE` | atomic upsert, no read-then-write window |
| `BEGIN IMMEDIATE` | **one lock over every document**. `.spec/ARCHITECTURE.md` records the lock-order inversion as a *known open limitation* of `JsonFileSubstrate` and says this backend is the one that closes it |
| WAL journal mode | concurrent readers during a write |
| `SELECT COUNT(*), SUM(LENGTH(payload))` | `describe()` without loading payloads |

**And the blob shape is decided, not accidental.** ADR-022 chose a document port
over a key-value domain and names what would reopen it: *"A backend whose value
is in queries the framework cannot express — full-text search over gate
payloads, say… The answer then is still not a KV protocol. It is a port for that
capability, named for the question it answers, with the substrate underneath."*

**The honest cost, for whoever specs this:** you cannot ask SQL "which scopes are
blocked". The stores load a whole document and filter in Python. That is fine at
the documented caps — 500 scopes, 500 runs (`.spec/ARCHITECTURE.md` → *Bounds*)
— and it is not what you would want behind a shared server. **Changing that is
out of scope here**; this feature is about *testing* the port, not widening it.
It is recorded so the question is not re-asked from scratch.

---

## 3 · The measured problem

### 3.1 · Two hand-written suites that barely overlap

```
$ grep -c 'def test_' tests/primitives/test_substrate.py                              # 32
$ grep -c 'def test_' plugins/functualize-state-sqlite/tests/test_sqlite_substrate.py # 23
```

Comparing the names:

| | count |
|---|---|
| in **both** suites | **5** |
| JSON only | 27 |
| SQLite only | 18 |

The five shared: `test_round_trip`, `test_an_unwritten_key_reads_as_none`,
`test_an_empty_document_is_not_none`, `test_a_matching_revision_writes`,
`test_a_stale_revision_refuses`.

So **45 port behaviours are pinned against exactly one backend.** Which side a
behaviour lands on is an accident of who wrote the file, not a decision:

- **JSON only** — key validation and traversal rejection, "the error names the
  key", "no `expect` overwrites unconditionally", "rewriting identical content
  keeps the revision", "revisions differ between keys", "locking nothing is
  allowed", "write does not take the lock", lock-ordering stability.
- **SQLite only** — `clear()` keeps a copy without reading it, `delete()`
  reports whether there was one, `describe()` aggregates a namespace, a batch is
  all-or-nothing, an exception rolls the block back, the lock is re-entrant,
  concurrent writers do not both win, a second substrate object sees the first
  one's writes.

Several of those are *port promises*. `clear()` "not reading is the whole point"
and `write(expect=)` returning `False` as "an ordinary outcome, not an error"
are both written into `StoreSubstrate`'s docstring, and each is currently
checked against one implementation.

### 3.2 · Tests reach artifacts by type

```
$ git grep -l -E '(fresh|scopes|runs)\.json' -- tests/      # 26 files
$ git grep -l -E 'state\.db|sqlite3\.connect' -- tests/ plugins/   # 11 files
```

Thirty-seven files are coupled to one backend's storage format. That coupling is
what produced the 60 failures: a test that reads `.functualize/fresh.json` is
not testing freshness, it is testing JSON, and it reports success by finding
nothing when the data is in a database.

**Three were converted on `feat/plugin-host-protocol` as proof the fix works**,
and each got shorter as well as backend-agnostic:

- `tests/pipeline/test_fingerprint_key_agreement.py` — counted keys by parsing
  `fresh.json`; now asks `func builtin data show` for `Fingerprints: N`.
- `tests/cli/test_state_mode_report.py` — asserted the reported path *was*
  `.functualize/fresh.json`; now asserts the **directory** that decided the
  mode, which is the test's actual subject.
- `tests/gate/test_provider_tables.py` — discovered provider tables by regex on
  `*_PROVIDERS` and mistook two string constants for tables; now checks the
  value is a `Mapping`.

The rule that fell out: **where the subject is content, go through the port;
where it is user-visible, go through the product.** A test whose subject
genuinely *is* the file format keeps `@pytest.mark.json_substrate`.

### 3.3 · The cross-backend gate exists and nothing runs it

```
$ grep -rn 'FUNCTUALIZE_TEST_SUBSTRATE' .github/
(no matches)
```

`tests/conftest.py::_alternate_substrate` repoints the one substrate decision, so
`FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest` re-runs the **entire** suite
against SQLite. 55 tests carry `@pytest.mark.json_substrate` and skip themselves
with a reason. The conftest calls that run *"this feature's sabotage step: if the
suite only passes on files, something still reaches through the port, and the
failures name it."*

It is a good mechanism. **No workflow invokes it**, so it runs only when someone
remembers. Verified working on `feat/plugin-host-protocol` after that branch's
changes: a sample of `tests/primitives tests/engine tests/workflow` gave
**706 passed, 32 skipped**.

---

## 4 · The proposal (for Specify to accept, reshape or reject)

### 4.1 · Do NOT add a roundtrip API to production

The port already is one: `read`, `write`, `lock`, `clear`, `delete`, `describe`.
A helper existing to serve tests would be production code with one consumer —
the same *middle man* shape `plugin-taxonomy`/T7 deletes from
`functualize-tasks-local`. **The gap is a shared test, not a shared function.**

Recorded because it was the first idea and it is wrong.

### 4.2 · Ship a conformance suite, publicly, in `functualize.testing`

That package exists for this audience and currently holds eight job-author
doubles and no substrate kit:

```
$ python -c "import functualize.testing as t; print(t.__all__)"
['AutoPrompt', 'CapturingLog', 'FakeShell', 'FakeShellCall', 'FakeStdout',
 'MockInvoke', 'NoopPerf', 'TestRunContext']
```

One parametrized suite taking a factory, which both first-party backends run:

```python
from functualize.testing import SubstrateConformance

class TestSQLite(SubstrateConformance):
    @pytest.fixture
    def substrate(self, tmp_path):
        return SQLiteSubstrate(tmp_path / "s.db")
```

Then the 45 one-sided behaviours become two-sided by construction, and adding a
port promise means adding it once.

**Public, not internal, for a reason that is not convenience.** `docs/examples/
plugins/custom-state-backend.md` ships a "write your own substrate" tutorial.
Today a third-party author has a Protocol and no way to know they satisfy it
beyond `isinstance` — which passes on a class with six correctly-named methods
that do the wrong thing. This is the missing half of that tutorial.

Note the cost: `contributor/reference/public-api-example-coverage.md` requires
every public symbol to have a caller in `examples/`. The custom-substrate
example is the natural one and would satisfy it.

### 4.3 · Run the SQLite variant in CI

Otherwise 4.2 only proves what someone remembers to run. Small: one job setting
`FUNCTUALIZE_TEST_SUBSTRATE=sqlite`. Needs a decision on whether it blocks merge
or reports only.

### 4.4 · Decouple the 37 artifact-reading test files

Largest and least urgent. Worth splitting from 4.2 — a conformance suite is
useful immediately, and this is a long tail.

---

## 5 · Open questions for Specify

**Q1 — class-based, fixture-based, or a pytest plugin?** The sketch above uses
inheritance, which is the shape most likely to be *used* by a third party but
sits oddly beside this repo's preference for composition. A parametrized
`substrate_factory` fixture is the alternative.

**Q2 — does the conformance suite cover `lock()` semantics?** `lock()` "may be a
no-op for a backend that offers no mutual exclusion", so a conformance test
cannot require exclusion. It *can* require that `write(expect=)` refuses a stale
revision, which is the guarantee that survives a no-op lock. Deciding what a
no-op-lock backend must still promise is the substantive design question here —
and it is the one that matters for a future S3 substrate.

**Q3 — should the conformance suite be run against a deliberately broken
substrate as its own gate?** The repo's discipline is that a test proves nothing
until it has failed on purpose. A stub that violates one promise per subclass
would prove the suite bites.

**Q4 — does 4.4 include the plugin suites, or only `tests/`?**

**Q5 — is `FUNCTUALIZE_TEST_SUBSTRATE` still the right mechanism** once a
conformance suite exists, or does it become redundant? They answer different
questions — the variant run exercises the *whole system* on another backend,
the conformance suite exercises the *port* — so probably both, but say so.

---

## 6 · Prior art to read before deciding

| Source | Why |
|---|---|
| `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md` | why the port is documents, and what would reopen it |
| `.spec/ARCHITECTURE.md` → *Runtime storage*, *Locking*, *Bounds* | the five documents, the two discard rules, the lock-order limitation `SQLiteSubstrate` closes |
| `src/functualize/_types/protocols.py` → `StoreSubstrate`, `Stored` | the six members, and the docstrings that state the promises a conformance suite would assert |
| `tests/conftest.py` → `_alternate_substrate` | the existing cross-backend mechanism and the `json_substrate` opt-out |
| `contributor/reference/public-api-example-coverage.md` | what publishing into `functualize.testing` costs |
| `tests/primitives/test_one_substrate_choice.py` | the existing "one decision, not five" tests — a model for how this repo writes a structural gate |
