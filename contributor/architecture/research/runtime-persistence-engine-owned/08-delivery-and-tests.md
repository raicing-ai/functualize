# 08 — Delivery and tests

**The rule this chapter exists to enforce:** a stage is not done because its unit
tests pass. It is done when a named production path reaches it and a **sabotage test**
— one that breaks the wire and watches something fail — proves the path is real.

That rule is not invented here. It is the repository's own execution discipline
(`.claude/rules/spec-workflow.md` → *Reachability precedes `[x]`*: "Name the
production call path, verify it by breaking the call and watching a test fail. 'A test
calls it' is not a call path.") Design 1 states the same principle well; this chapter
applies it to a different wave order.

---

## Wave order, and the one that is new

| Wave | Name | Jira | Blocks | New here? |
|---|---|---|---|---|
| **0** | **Repair** | new ticket under FUN-16 | everything | **yes — no other design has it** |
| 1 | Ports, recorders, construction move | FUN-17 | 2–6 | reshaped |
| 2 | State machines enforced | FUN-18 (first half) | 3–6 | **reordered before the schema** |
| 3 | Relational SQLite + migrations | FUN-18 (second half), FUN-19 | 4–6 | |
| 4 | Attempts, workflow/state/resume | FUN-20 | 5–6 | |
| 5 | Interactions, evidence, outbox | FUN-21 | 6 | |
| 6 | Offline import and cutover | FUN-19 | — | **moved to last** |
| 7 | Network SQL | FUN-22 | — | blocked on a database choice |
| 8 | Workspace / artifacts | FUN-23 | — | spec only |

Two deliberate differences from Design 1's order:

**Wave 0 exists.** Design 1's Wave 0 is "architecture and characterization" —
recording current behaviour as fixtures. That is the right instinct applied to the
wrong data: [`03-the-four-defects.md`](03-the-four-defects.md) shows the behaviour
being characterised is partly corruption, and a fixture that pins it makes the
corruption a requirement.

**Import moved from Wave 3 to Wave 6.** Design 1 imports legacy data immediately after
the relational schema lands. Import last, after the state machines and attempts exist,
so the importer knows what a legal record looks like and can reject an illegal one
instead of faithfully copying it.

---

## Wave 0 — Repair

**Gate:** every one of the four reproductions in
[`03-the-four-defects.md`](03-the-four-defects.md) turns from a demonstration of the
bug into a passing regression test, and each new test fails if its fix is reverted.

| Test | Must assert |
|---|---|
| `tests/primitives/test_claim_is_atomic.py` | two forked processes claiming one scope obtain **two distinct generations**, with the advisory lock neutered |
| `tests/primitives/test_state_is_fenced.py` | a stale generation's `set_state` raises, and the live holder's value survives |
| `tests/primitives/test_fence_checks_owner.py` | a co-generation writer with a different owner is refused |
| `tests/app/test_substrate_install_fails_closed.py` | a substrate whose construction raises **fails boot**; the app does not come up on `JsonFileSubstrate` |
| `tests/cli/test_shell_history_agrees.py` | a command recorded through the TUI is visible to `func builtin history` with a substrate installed |
| `tests/plugins/test_sqlite_multiprocess.py` | the **first** multi-process test the SQLite plugin has ever had |

**Sabotage:** revert the fence in `ScopeStateStore._mutate` → `test_state_is_fenced`
must fail. Revert `expect=` on the claim → `test_claim_is_atomic` must fail. If either
still passes, the test is testing itself.

**Docs in the same wave**, because they are wrong today and cost nothing:
`docs/guides/workflows.md:366-372`, `docs/guides/hosting.md:214-225`,
`substrate.py:20-22`, `_engine/capabilities/state.py:1-33`.

---

## Wave 1 — Ports, recorders, and the construction move

**Gate:** removing the `runtime_store=` argument from `build_engine` fails to
construct, at import time — not at first use. That is the whole point of the move: the
failure mode becomes a `TypeError` at boot instead of a wrong backend at run time.

### The test that makes "nothing reads the engine early" a proof

[`05-the-design.md`](05-the-design.md) §4 claims nothing touches
`app._execution_engine` between boot step 1 and `APP_READY`. That claim currently
rests on a grep. Make it a test:

```python
# tests/app/test_engine_is_not_read_before_wiring.py
def test_nothing_reads_the_engine_before_it_is_wired(monkeypatch):
    """A sentinel in the engine slot must never be dereferenced during boot.

    If some future step reaches for app._execution_engine before step 6.6,
    this explodes with a named error instead of silently reintroducing the
    lazy-substrate race that B2 came from.
    """
    class Tripwire:
        def __getattr__(self, name):
            raise AssertionError(
                f"boot read app._execution_engine.{name} before the engine "
                f"was wired; move that step after 6.6 or inject what it needs"
            )
    ...
```

### Surface parity, both boot paths

The same runtime facts must be asserted through every door, because the
[surface boundary](../../surface-boundary.md) is exactly where divergence has hidden
before:

- `func` cold cache and warm cache
- an embedded `FunctualizeApp` (`boot_static`)
- `Invoke` parent and child
- MCP workflow and history tools
- `func builtin data` / `run` / `history`

**Sabotage:** break the selection step on *one* boot path only. The parity test must
fail. `boot_static` is the path that gets forgotten — it does not load entry-point
plugins at all (`boot.py:419-431` handles only explicit ones).

---

## Wave 2 — State machines

**Gate:** the transition table in [`06-data-model.md`](06-data-model.md) §1.3 is
enforced by the store, and an illegal transition raises rather than being written.

| Test | Must assert |
|---|---|
| `test_a_terminal_scope_refuses.py` | `completed` → `running` is refused (today it silently succeeds) |
| `test_cancel_requires_the_generation.py` | cancel without a claim and without `force` is refused (today `_workflow_control.py:439` proceeds) |
| `test_every_status_write_goes_through_a_command.py` | a grep-style architecture test: no `set_scope_status` call sites remain outside the recorder |

That last one is the kind of test this repository already writes —
`tests/spec/` is full of them — and it is what stops the twelve scattered write sites
from quietly regrowing.

---

## Wave 3 — Relational SQLite

**Gate:** fault injection between every write in a transition proves rollback leaves
no partial state, and a stale generation cannot update state or outcome from a second
process.

Capability suites are **tiered by profile**, which is the practical payoff of
[`05-the-design.md`](05-the-design.md) §2.1:

```
baseline suite          every store must pass
  run tree and recent history
  workflow transition and replay determinism
  state batch and rollback
  corrupt-data policy
  event sequence monotonicity
  close / reopen durability

capability: cross_aggregate_atomicity   -> partial-transition fault injection
capability: fencing == "cross-process"  -> two-process stale-writer refusal
capability: durable_outbox              -> crash-before/after-commit dispatch
capability: versioned_migrations        -> every historical schema, and a failed revision
```

A store that declares `durable_outbox=False` does not run the outbox suite **and
cannot be selected by a feature that needs one**. Under Design 1 the same store would
run the suite and be marked `TRANSITIONAL` — a word that does not stop anyone.

SQLite-specific, adopted from Design 2's policy list: `PRAGMA foreign_keys=ON` on
every connection, WAL only for file-backed databases, a bounded busy timeout surfaced
as a **retryable** error rather than a raw `sqlite3.OperationalError`
([`02-what-exists-today.md`](02-what-exists-today.md) §8.2 — nothing handles it
today), `BEGIN IMMEDIATE` on claim and CAS paths, and no independent `:memory:`
connections in tests.

---

## Wave 6 — Import and cutover

Procedure, adopted from Design 1 nearly unchanged because it is careful:

1. acquire an exclusive project migration lock;
2. snapshot and back up the source documents or database;
3. import into a new schema in one transaction;
4. verify counts, identities, terminal/live status, state keys, sequence order and
   payload digests;
5. atomically persist the selection and cutover marker;
6. reopen through the target read ports and run semantic verification;
7. retain the backup until an explicit cleanup.

**No dual write, ever.** A failed import leaves the source authoritative.

Two additions Design 1 does not have:

- **The importer rejects illegal records** rather than copying them, using the Wave-2
  transition table. A scope that is `completed` with a live lease is a symptom of B4
  and must be reported, not migrated.
- **The report states what the cap already ate.** `scopes` evicts terminal records at
  500 (`scope_format.py:144`), so "verify counts" can only verify against what is
  currently on disk. The report must say so rather than implying completeness.

**Gate:** imports from every legacy fixture are repeatable, and interrupting at each
phase either resumes or rolls back — never producing two authorities.

---

## The test architecture, summarised

```
tests/
  primitives/     the fence, the claim, the cap          <- Wave 0 lands here
  app/            boot ordering, selection, capability refusal
  spec/           architecture tests: "no status write outside a recorder"
  plugins/        the tiered store contract suite, per profile
  integration/    surface parity: func / embedded / MCP / Invoke, cold and warm
  perf/           the startup budget, which the construction move must not break
```

`tests/perf/test_startup_budget.py` deserves a note: moving engine construction later
changes the boot profile. It should not change the total, since the same work happens,
but the budget test is the thing that will tell you if it does.

---

Next: [`09-decisions.md`](09-decisions.md).
