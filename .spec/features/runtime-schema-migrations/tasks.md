# Runtime schema — Tasks

Refined against `03fbb64` on 2026-09-25. The scaffold's 3.1 (relational schema) and 3.2 (JSON
boundary) were specification, not code, and are **done in `schema.md` §2–§3** by the refinement;
they are not re-listed. Wave ordering is binding. Each task names its `after:` set explicitly;
the JSON graph at the end is derived from those edges. A task marked **held** does not start until
the named decision in `spec.md` is answered.

Every task closes only with: the five checks green (`ruff check`, `ruff format --check`, `mypy
src/`, `lint-imports`, targeted `pytest`), its production call path named, and — for any task
that wires a check — the sabotage proof (commit, remove the check, watch the gate fail, restore).

- [ ] **1.1** The four machines as data
      *after:* none
      *Files:* `src/functualize/_types/lifecycle.py` (new), `tests/types/test_lifecycle_tables.py` (new)
      *Gate:* each machine's `transitions ⊆ (states ∪ {None}) × states`, `terminal ⊆ states`, no
      edge leaves a terminal state; `RUN.terminal == {s.value.lower() for s in RunStatus if s.terminal}`;
      an import-line test shows the module imports stdlib and `functualize._types.enums` only.
      D1/D2 rows go in marked `# TRANSITIONAL(<closing wave>)`; if D1/D2 are still open, write
      them as proposed in `schema.md` §1.1 — 3.1 is where they bite.
- [ ] **1.2** `IllegalTransition`
      *after:* none
      *Files:* `src/functualize/_types/errors.py`, `tests/types/test_illegal_transition.py` (new)
      *Gate:* the message names machine, current and target; attributes are readable; pickles.
- [ ] **2.1** `require_transition`
      *after:* 1.1, 1.2
      *Files:* `src/functualize/_primitives/transitions.py` (new), `tests/primitives/test_transitions.py` (new)
      *Gate:* for every machine, the full product `(states ∪ {None}) × states` is enumerated and
      the function accepts exactly `machine.transitions`, raising `IllegalTransition` otherwise;
      an unknown target raises. AC1.
- [ ] **3.1** Scope enforcement at the choke point — **held on D1, D2**
      *after:* 2.1
      *Files:* `src/functualize/_primitives/scope_store.py`, `tests/primitives/test_scope_transitions.py` (new),
      plus the hit set of `rg -n 'set_scope_status\(' tests plugins` that asserts a now-illegal move
      (today 38 sites / 18 files; `tests/test_state_store.py:112-116` is in-table and stays)
      *Gate:* (a) record mode first: run `tests/workflow tests/integration tests/primitives
      tests/test_scope_store.py tests/test_state_store.py` and
      `plugins/substrates/functualize-substrate-sqlite/tests` with the check logging every pair;
      zero pairs outside `SCOPE.transitions`; (b) refuse mode: completed→running through
      `ScopeStore.set_scope_status` raises and leaves the envelope byte-identical; (c) AST line
      count of `class ScopeStore` ≤ 930; (d) sabotage. AC2, AC3.
      *Call path:* `FrontierWalk.complete` → `ScopeStore.set_scope_status` (and the other 12).
- [ ] **3.2** Run enforcement at `close_run`
      *after:* 2.1
      *Files:* `src/functualize/_primitives/run_store.py`, `tests/primitives/test_run_transitions.py` (new)
      *Gate:* closing an already-terminal run raises and leaves the record unchanged; closing a
      `running` run with each of the 9 lower-cased `RunStatus` values behaves per `schema.md` §1.2;
      sabotage. AC2.
      *Call path:* `Executor._close_run_record` → `RunStore.close_run` (`executor.py:1108`).
- [ ] **4.1** One retention policy
      *after:* none
      *Files:* `src/functualize/_types/retention.py` (new), `src/functualize/_primitives/scope_format.py`,
      `src/functualize/_primitives/run_format.py`, `tests/primitives/test_scope_cap.py`
      *Gate:* `rg -n '= 500' src/functualize/_primitives/{scope,run}_format.py` → 0 hits; the
      existing cap tests pass unchanged; a test constructs a smaller policy and sees both trims
      honour it. AC6 (document half).
      *Call path:* `ScopeStore._mutate` → `normalize/_trim` on every write.
- [ ] **5.1** Migration runner and `0001` — **held on D3**
      *after:* 2.1 (the `CHECK (status IN …)` lists are generated from the machines)
      *Files:* `src/functualize/_primitives/migrations/__init__.py`, `src/functualize/_primitives/migrations/runner.py`,
      `src/functualize/_primitives/migrations/0001_runtime_schema.sql`, `tests/primitives/test_migrations.py`
      *Gate:* against stdlib `sqlite3` in-memory: empty → v1 records one ledger row; re-run is a
      no-op; edited `0001` checksum → `MigrationRefused`; ledger ahead of shipped → refused; gap →
      refused; every table and index in `schema.md` §2 exists (`sqlite_master`). AC4, AC5.
- [ ] **5.2** Relational retention statement — **held on D3**
      *after:* 4.1, 5.1
      *Files:* `src/functualize/_primitives/migrations/retention.py`, `tests/primitives/test_migrations.py`
      *Gate:* on a v1 database with 600 terminal and 10 blocked scopes, the statement leaves 500
      terminal + 10 blocked and cascades their children. AC6 (relational half).
- [ ] **6.1** Durable half
      *after:* 3.1, 3.2, 4.1, and 5.1–5.2 unless D3 moved them out
      *Files:* `contributor/reference/runtime-persistence-data-model.md` (§1 Δ rows, §6, §7 status),
      `contributor/architecture/dependency-graph.md` (two new `_types` modules, one `_primitives`),
      `.spec/STATUS.md`, `CHANGELOG.md`
      *Gate:* every **Δ** in `schema.md` appears in the reference doc; `tasks.md` boxes match the
      commits; the message-hygiene key pattern `\b[A-Z]{2,10}-[0-9]{1,6}\b` over the changed prose finds permitted prefixes only.
- [ ] **7.1** Clearing commit (second push, deletion-only, last)
      *after:* 6.1 and a green validation run on the pushed 6.1 tip
      *Files:* `git rm -r .spec/features/runtime-schema-migrations contributor/architecture/research`
      *Gate:* `git show --stat HEAD` lists deletions only; `git ls-files .spec/features
      contributor/architecture/research` → empty. The research tree rides on this branch from its
      first commit and is refused by `research-artifacts-cleared`; its durable half is already on
      master (`runtime-persistence-data-model.md`).

## Task Dependency Graph

Edges (`task ← after`): 1.1 ← ∅ · 1.2 ← ∅ · 4.1 ← ∅ · 2.1 ← {1.1, 1.2} · 3.1 ← {2.1} ·
3.2 ← {2.1} · 5.1 ← {2.1} · 5.2 ← {4.1, 5.1} · 6.1 ← {3.1, 3.2, 4.1, 5.2} · 7.1 ← {6.1}.
`after:` counts: 1.1=0, 1.2=0, 4.1=0, 2.1=2, 3.1=1, 3.2=1, 5.1=1, 5.2=2, 6.1=4, 7.1=1.

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1", "1.2", "4.1"]},
    {"id": 1, "tasks": ["2.1"]},
    {"id": 2, "tasks": ["3.1", "3.2", "5.1"]},
    {"id": 3, "tasks": ["5.2"]},
    {"id": 4, "tasks": ["6.1"]},
    {"id": 5, "tasks": ["7.1"]}
  ],
  "after": {
    "1.1": [], "1.2": [], "4.1": [],
    "2.1": ["1.1", "1.2"],
    "3.1": ["2.1"], "3.2": ["2.1"], "5.1": ["2.1"],
    "5.2": ["4.1", "5.1"],
    "6.1": ["3.1", "3.2", "4.1", "5.2"],
    "7.1": ["6.1"]
  },
  "held": {"3.1": ["D1", "D2"], "5.1": ["D3"], "5.2": ["D3"]}
}
```
