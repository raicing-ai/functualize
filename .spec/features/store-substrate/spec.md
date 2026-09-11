# Store substrate — one swappable floor under functualize's own bookkeeping

**Depends on:** `durable-run-layer` T5–T8 (the lease and its fencing token).
That work builds the compare-and-swap primitive a non-filesystem substrate
needs; building this first would mean inventing it twice.

## A · The correctness case, not the tidiness case

`lambda` is a declared surface (`_types/run_request.py:36`). Functualize keeps
its own bookkeeping in exactly two places — a project `.functualize/` directory
or `$XDG_CACHE_HOME` (`state_format.resolve_state_location`) — and **both are a
local hard disk**.

On Lambda the only writable path is `/tmp`: wiped between cold starts, not
shared between concurrent invocations. So:

```
1. workflow runs, hits a gate, stops      → writes /tmp/scopes.json
2. the container freezes                  → /tmp is gone
3. a human approves the gate
4. resume → new container → empty /tmp    → "scope not found"
```

**A gate that cannot be resumed is a gate that does not work.** This is a
broken feature on a supported surface, not an abstraction preference. The same
applies to two machines sharing a workflow and to any read-only container.

Confirmed undocumented: nothing in `docs/` warns that gates require a durable
local filesystem (G6, `now: 0`).

## B · What is *not* in scope, and why

**`functualize-state` is retired, not expanded.** Maintainer's own framing
(2026-09-11): it was built as a Dapr-style common interface for state and
database operations, and that is outside this framework's domain.

The argument, recorded because it will be re-proposed: a backend-agnostic
key-value protocol can only offer the *intersection* of every backend —
get/set/delete/keys. Anyone who chose Postgres chose it for transactions,
joins, schema and indexes, none of which survive that intersection. So the
abstraction is worth least exactly where the database is worth most. A job that
needs Postgres should import `psycopg`. Dapr can justify the building block as
a polyglot sidecar; a Python job framework cannot.

It is also already dead: core imports `functualize_state` **zero** times (G4),
and its `StateBackend.keys(prefix)` has drifted from core's glob-matching
`State.keys(pattern)`.

**This feature is about the other thing that wore the same word**: the four
files functualize writes for itself — `scopes.json`, `state.json`,
`runs.json`, and whatever `state.json` becomes after `durable-run-layer`/T3b.
A user never sees them, and losing them loses a run.

## C · Why the port is three methods, not eighty-nine

Measured, and it is the finding that makes this cheap:

```
_primitives/state_store.py   direct filesystem calls: 0
_primitives/scope_store.py   direct filesystem calls: 0
_primitives/run_store.py     direct filesystem calls: 0
```

The store classes never touch a file. All 45 filesystem references live in the
three `_format` modules (G5), and those three have an **identical** shape:

```
empty_X   resolve_X_path   X_lock   load_X   save_X   update_X   clear_X
```

So the seam exists structurally and is merely unnamed. The 89 typed methods —
`record_step`, `put_gate`, `get_fingerprint` — do not move. They become pure
logic over a swappable floor.

Consumers already help: `executor`, `frontier`, `preflight`, `workflow_walker`,
`workflow_runner`, `app/core` and `app/utils` all take a store by
**constructor injection**. Only 17 sites construct one (G3).

## D · The three stores become peers, and the facade is deleted

**Maintainer's question, 2026-09-11: "you will extract ScopeStore to be outside
StateStore — they will be peers consuming the same substrate?" Yes.** The
measurement makes it easy:

`StateStore` has **36 methods, 25 of which are pure pass-through** to the
`ScopeStore` it holds (`self._scopes.…`). Only ~11 concern `state.json` itself.
Meanwhile `RunStore` is **already** a peer, constructed directly by the engine
and never behind the facade — so today's arrangement is not a design, it is two
halves of one.

```
TODAY                                  AFTER

StateStore  (36)                       StoreSubstrate
  ├ 11 own                              ├── FreshStore   ~8
  └ 25 ─ pass-through ─┐                ├── ScopeStore    32
                       ▼                └── RunStore      13
                 ScopeStore (32)
RunStore (13) ← peer already
```

The 25 delegating methods are **deleted, not moved**: callers reach `ScopeStore`
directly rather than asking `StateStore` to forward. Five modules change the
type they accept — `app/_workflow_answer.py`, `app/_workflow_control.py`,
`app/adapters/workflow_flags.py`, `_cli/builtins.py`, and the MCP plugin's
`_workflow_tools.py` — and all five already take the store by injection, so
this is a type change rather than a rewiring.

`beside_state` disappears with the facade. Sibling-file resolution is a
filesystem idea and means nothing to a substrate that is not a directory; the
substrate names collections (`"scopes"`, `"runs"`, `"fresh"`) instead.

**This is the same decision as `durable-run-layer`/T3b arriving twice.** Once
`history` moves to the run log, `state.json` holds only freshness verdicts —
which is why it becomes `fresh.json`, and why the class becomes `FreshStore`.
Do T3b first or the split leaves a `history` section in a store named for
freshness.

## E · The live defect this also fixes

`capability-duality` put `rc.state` *inside* the scope record. Swapping the KV
store to SQLite today therefore splits one fact across two stores:

```
rc.state.set("k", 1)      → SQLite        (the value)
scope steps, gates        → scopes.json   (what gives it meaning)
```

Two files, two locks, no transaction across them; a crash between them leaves
them disagreeing. `functualize-state-sqlite` produces this **today**. The
substrate fixes it by construction, because all four stores move together or
none do.

### E.2 · The same defect, arrived at twice more (2026-09-11)

`scope-record-lifecycle`/T3 moved job state **out** of the scope record and into
a per-scope file, which fixed a 116× cost. It did not fix the split above — it
relocated it, and made one consequence sharper.

**A lock-order inversion, found by external review**
(`.spec/reviews/scope-state-review.md` Q2.3):

```
T1: with state.batch():        # holds the STATE lock
        rc.track_phase(...)    # -> a record write -> wants the SCOPES lock
T2: with store.batch():        # holds the SCOPES lock
        store.set_state(...)   # -> wants the STATE lock
```

Both orderings are reachable from ordinary user code. Neither lock can be
dropped without losing the guarantee it exists for, and **no global ordering
can be imposed from inside the stores**, because the caller decides which batch
to open first. It is mitigated today — the record is ensured before the state
lock is taken, and both locks time out audibly after 10 s — but mitigation is
all it is.

`scope-record-lifecycle/plan.md` reached the same destination independently, as
its surviving smell #1: two files now describe one run, so a crash between the
two writes leaves a record with no state or state with no record.

**What this changes for the design, concretely.** The port's `lock` is
load-bearing rather than incidental. A substrate that hands out a lock *per
collection* reproduces the inversion in a new place and this feature would then
have moved the bug rather than removed it. "One lock for everything this
substrate holds" has to be expressible in the port, and T7's no-shared-disk
implementation has to satisfy it.

## F · Acceptance criteria

- **AC-1** A `StoreSubstrate` protocol exists with three members — `read`,
  `write` (compare-and-swap via `expect`), `lock` — and the three `_format`
  modules are its default implementation.
- **AC-2** The store classes keep every typed method and still touch the
  filesystem **zero** times. (G1 is an invariant, not a target.)
- **AC-3** A workflow that blocks at a gate under a non-filesystem substrate is
  resumable **from a different process with no shared disk**. This is the
  criterion the whole feature exists for; a test that only swaps the substrate
  in-process does not meet it.
- **AC-4** Choosing a substrate moves **all four** stores or none — the
  split-brain in §D is unreachable by construction.
- **AC-5** `WorkflowScope.replace_state_store` and `StateStoreProtocol` are
  **deleted**, not kept alongside. One seam, at the substrate; a second seam at
  the KV level is what produced §D (*Pre-Release Stance*: delete rather than
  shim).
- **AC-6** `functualize-state` is removed from the repository, and the reason
  in §B is recorded in an ADR so it is not rebuilt.
- **AC-7** Until a durable substrate is configured, the filesystem default is
  unchanged and behaves exactly as today — no user on a laptop notices this
  feature happened.
- **AC-8** `docs/` states plainly that gates need a durable store, and names
  how to configure one.
- **AC-9** `StateStore` no longer forwards a single scope method. The facade is
  gone and the three stores are peers (§D); `rg -c "self\._scopes\." ` over
  the store modules returns 0.

## G · Deliberately out of scope

- A generic user-facing database API (§B).
- Migrating existing `.functualize/*.json` into another substrate. The files
  are per-project and cheap to rebuild except for scopes; a migration command
  is its own change if anyone wants one.
