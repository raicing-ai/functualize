# 05 — The design

**Thesis: the engine owns what a transition *means*; storage owns whether it is
*durable*.**

Everything below follows from that, plus one practical constraint discovered in the
code: the engine is constructed before its storage can exist, and that is fixable by
moving the construction rather than by inventing a late-binding mechanism.

---

## 1. Shape

```text
                    ┌──────────────────────────────────────────┐
  plugin authors →  │ functualize.plugin                       │  PUBLIC
                    │   RuntimeStoreFactory, StoreProfile,     │
                    │   StoreSubstrate  (newly exported)       │
                    └───────────────────┬──────────────────────┘
                                        │ registers a factory during plugin load
                                        ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ _app/  — THE ONLY COMPOSITION ROOT                                  │
  │                                                                     │
  │   step 4   load plugins        -> factories registered by scheme    │
  │   step 6   resolve config      -> RuntimeStoreConfig                │
  │   step 6.5 select + prepare    -> ONE RuntimeStore, migrated,       │
  │                                    health-checked, profile known    │
  │   step 6.6 build_engine(app, runtime_store=store)                   │
  └───────────────────┬─────────────────────────────────────────────────┘
                      │ constructor argument — not a handle, not a hook
                      ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ _engine/  — OWNS THE LIFECYCLE, UNCHANGED IN THAT RESPECT           │
  │                                                                     │
  │   JobExecutionEngine._execute_lifecycle    the 20 steps             │
  │   _engine/recording/run_recorder.py        lifecycle -> commands    │
  │   _engine/recording/workflow_recorder.py   walk      -> commands    │
  │        │                                                            │
  │        └── speaks only _types protocols ──────────┐                 │
  └───────────────────────────────────────────────────┼─────────────────┘
                                                      ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ _types/persistence.py  — VOCABULARY ONLY, stdlib imports            │
  │   StoreProfile  RuntimeStore  RuntimeTransaction                    │
  │   RunWriter WorkflowWriter InputWriter EventWriter EffectWriter     │
  │   RunReader WorkflowReader InputReader                              │
  │   ClaimWorkflow CompleteStep SuspendAtGate ResumeWorkflow StateBatch│
  └───────────────────┬─────────────────────────────────────────────────┘
                      │ implemented by
      ┌───────────────┴────────────────┐
      ▼                                ▼
  DocumentRuntimeStore            SqliteRuntimeStore
  (wraps today's five stores)     (normalized tables, migrations)
  profile: weak, honest           profile: strong
```

**No new peer layer.** Ports go in `_types`, which every layer may already import.
Recorders go in `_engine`, which already owns the lifecycle. Wiring goes in `_app`,
which is already the composition root. The seven import-linter contracts need **no**
changes — verify with `uv run lint-imports`.

Compare Design 1, which adds `src/functualize/_persistence/` as a sixth peer and
therefore needs an ADR and contract updates before implementation can begin.

---

## 2. The ports

All of this lives in one new file, `src/functualize/_types/persistence.py`. It imports
only the standard library, as `_types` requires.

### 2.1 The profile — capability as data

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class StoreProfile:
    """What this store can actually promise. Checked at boot, never probed.

    Every field is a statement a maintainer must be able to defend with a test.
    `DocumentRuntimeStore` declares `cross_aggregate_atomicity=False` not as an
    apology but as a fact: there is no code path that commits two documents
    together (see 03-the-four-defects.md, B3).
    """

    name: str
    #: Can two aggregates commit in one transaction that rolls back together?
    cross_aggregate_atomicity: bool
    #: "none"          — writes are not fenced at all
    #: "process-local" — fenced only within the object that holds the generation
    #: "cross-process" — a stale writer cannot commit from any process
    fencing: Literal["none", "process-local", "cross-process"]
    multi_process: bool
    multi_machine: bool
    durable_outbox: bool
    versioned_migrations: bool

    # --- added after the durability-outsourcing research; see the note below
    #: Can a transaction hold statements open across a Python decision?
    #: Cloudflare D1 cannot: no BEGIN/COMMIT, one `batch` per atomic unit.
    interactive_transaction: bool
    #: Does every operation cross a network? Decides whether the engine may
    #: read-modify-write in a loop or must buffer and flush once.
    remote: bool
    #: Largest single document the backend accepts. D1 caps a row at 2 MB.
    max_document_bytes: int | None
    #: Does this store work with no network at all? ADR-015 makes the offline
    #: binary the reason the binary exists, and today nothing states this.
    offline_capable: bool

    #: Free text for an operator: where the data is, what it costs.
    description: str = ""
```

**The last four fields were added by the evaluation in
[`../durability-outsourcing/`](../durability-outsourcing/07-the-design.md) §3**, each
earned by a specific finding rather than invented for symmetry. `offline_capable` is the
important one: ADR-015 states that the standalone binary exists because "the first run
needs no network", and that guarantee is currently enforced by nothing except the fact
that no remote substrate has been written yet.

Today's substrates would declare:

| | `DocumentRuntimeStore` | `SqliteRuntimeStore` | a future network SQL store |
|---|---|---|---|
| `cross_aggregate_atomicity` | `False` | `True` | `True` |
| `fencing` | `"process-local"` | `"cross-process"` | `"cross-process"` |
| `multi_process` | `False` | `True` | `True` |
| `multi_machine` | `False` | `False` | `True` |
| `durable_outbox` | `False` | `True` | `True` |
| `versioned_migrations` | `False` | `True` | `True` |

A feature declares what it needs, and boot refuses rather than degrading:

```python
# _app/, at selection time
require(store.profile, multi_machine=True,
        because="workflow resume across runners was configured")
# -> RuntimeStoreCapabilityError naming the store, the field, and the config key
```

**This is the replacement for Design 1's uniform semantic contract.** It is also where
the "different machines" documentation defect stops being possible: `multi_machine` is
a field with a value, not a sentence in a docstring.

### 2.2 The store and its transaction

```python
from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

@runtime_checkable
class RuntimeStore(Protocol):
    """One selected store. Constructed once, by _app, after config resolves."""

    profile: StoreProfile

    # Reads are question-shaped and always available.
    runs: "RunReader"
    workflows: "WorkflowReader"
    inputs: "InputReader"

    def transaction(self) -> AbstractContextManager["RuntimeTransaction"]: ...
    def close(self) -> None: ...


@runtime_checkable
class RuntimeTransaction(Protocol):
    """Everything written inside one short transition.

    A transaction NEVER wraps a job body, a prompt, an agent call or any
    network effect. See 06-data-model.md §4 for the full catalogue.

    **Writers accumulate; `__exit__` commits once.** Calling a writer appends a
    command to this transaction; it issues no statement. The whole batch is
    applied as one unit when the block exits cleanly, and discarded otherwise.
    See the note below — this is a requirement, not an implementation choice.
    """

    runs: "RunWriter"
    workflows: "WorkflowWriter"
    inputs: "InputWriter"
    events: "EventWriter"
    effects: "EffectWriter"
```

`close()` matters and is missing today: `SQLiteSubstrate` caches one connection per
thread in `threading.local()` and **nothing ever closes them**. The port has no
lifecycle at all.

#### The transaction buffers. It does not stream.

This is a correction to an earlier draft of this document, forced by evidence gathered
in [`../durability-outsourcing/`](../durability-outsourcing/05-cloudflare.md).

The natural reading of the port above is that each writer call issues its statement
immediately, inside an open `BEGIN`. On local SQLite that works. **It is not
implementable on the most plausible network backend.** Cloudflare D1 — managed SQLite,
and the best-fitting remote store evaluated — has no interactive transaction at all: its
alpha migration guide instructs you to strip `BEGIN TRANSACTION` and `COMMIT;` from
imported SQL, and the atomic unit is one `batch` request whose statements "abort or roll
back the entire sequence" on failure
([D1 Database docs](https://developers.cloudflare.com/d1/worker-api/d1-database/)).
A caller cannot read, decide in Python, and write, inside one D1 transaction.

So the contract is:

```python
with store.transaction() as tx:
    tx.workflows.complete_step(cmd)   # appends a command
    tx.events.append(evt)             # appends a command
# __exit__ flushes ONE unit:
#   local SQLite  -> one BEGIN/COMMIT
#   D1            -> one {"batch": [...]} request
#   a store with cross_aggregate_atomicity=False -> a documented refusal,
#                                                   never a partial apply
```

**This is why §2.3's writers take commands rather than issuing calls.** That choice was
argued there on testability grounds; it turns out to be the only shape that admits a
remote backend at all. A command is a value and can sit in a list. A method that issues
SQL cannot.

Two consequences worth stating before the port is frozen:

- A writer **cannot return a value read back from the database**, because nothing has
  been written yet when it is called. `claim()` returning `Claimed | Conflict` (§2.3)
  therefore belongs to a *single-command* transaction that commits on the spot — it is
  a claim, not a batch. Compound transitions return nothing and raise on refusal.
- A store that declares `cross_aggregate_atomicity=False` must **refuse** a transaction
  touching two aggregates. Applying it in parts is defect B3 with a new name.

### 2.3 Writers take commands, not rows

```python
@dataclass(frozen=True)
class ClaimWorkflow:
    scope_id: str
    owner: str
    now: datetime
    lease_seconds: float
    force: bool = False

@dataclass(frozen=True)
class Claimed:
    scope_id: str
    generation: int
    expires_at: datetime

@dataclass(frozen=True)
class Conflict:
    scope_id: str
    held_by: str
    held_generation: int


class WorkflowWriter(Protocol):
    def claim(self, cmd: ClaimWorkflow) -> Claimed | Conflict: ...
    def complete_step(self, cmd: CompleteStep) -> None: ...
    def suspend(self, cmd: SuspendAtGate) -> InputRequest: ...
    def resume(self, cmd: ResumeWorkflow) -> Resumed | Conflict: ...
    def cancel(self, cmd: CancelWorkflow) -> CancelResult: ...
    def write_state(self, cmd: StateBatch) -> None: ...


class RunWriter(Protocol):
    def start_attempt(self, cmd: StartAttempt) -> Attempt: ...
    def finish_attempt(self, cmd: FinishAttempt) -> None: ...
```

Three deliberate properties:

1. **`claim` returns `Claimed | Conflict`, not an exception.** Losing a claim is an
   expected outcome of a concurrent system, not an error. Today it raises
   `LeaseHeldError` and half the call sites swallow it
   (`frontier.py:285`, `app/_workflow_control.py:439`).
2. **Every command that mutates a scope carries the held generation**, and the store
   enforces it in the predicate — which is what B1 and B4 fix structurally rather
   than by remembering.
3. **`start_attempt`, not `start_run`.** An `Attempt` is one execution of a job; a
   `Run` is the logical unit a user asked for. Today's retry loop produces neither
   distinction (`03` cross-reference: `exec_policy.py:112-132` runs inside the run
   record opened at `executor.py:799`). This is adopted from Design 2.

### 2.4 Readers are named for questions

```python
class RunReader(Protocol):
    def run(self, run_id: str) -> RunView | None: ...
    def recent(self, query: RunQuery) -> Sequence[RunView]: ...
    def tree(self, root_run_id: str) -> RunTree: ...

class WorkflowReader(Protocol):
    def workflow(self, scope_id: str) -> WorkflowView | None: ...
    def resumable(self, query: WorkflowQuery) -> Sequence[WorkflowView]: ...
    def events_after(self, scope_id: str, seq: int) -> Sequence[EventView]: ...
```

Not `get`/`list`/`find`. A backend may answer `resumable()` with an index; the caller
never discovers that by `hasattr`. This is the ADR-022 lesson applied to reads, and
Design 1 states it equally well.

---

## 3. Who owns what

| Concern | Owner | Why |
|---|---|---|
| The 20-step lifecycle | `_engine/executor.py` | already does; `tests/engine/test_lifecycle_order.py` makes it a contract |
| Which transition happens next | `_engine/frontier.py`, `workflow_walker.py` | already does |
| Turning a lifecycle moment into a command | **new** `_engine/recording/` | thin; no decisions of its own |
| Whether the command commits atomically | the store implementation | that is what a database is for |
| Selecting and constructing the store | `_app/` | the composition root, per `layer-rules.md` |
| Declaring a factory and a URI scheme | a plugin, via `functualize.plugin` | public API |

**The line to police:** a store implementation must never contain the word "resume" in
a conditional. If it needs to know *why* a transition is legal, the logic is in the
wrong module. Design 1's `_persistence/transitions.py` sits on the wrong side of that
line.

---

## 4. Boot: move the construction, delete the problem

### Today

```python
boot_standard(app, perf_timeline):
    # 1. core infrastructure
    app._execution_engine = build_engine(app)          # boot.py:614
    ...
    # 4. load plugins                                    :718
    # 6. resolve config                                   :754
    # 9. APP_READY -> a plugin calls app.install_substrate :841
```

The engine finds its storage later, lazily, via `getattr(self.host, "substrate_override", None)`.
Three problems: the ordering is implicit, a late install is refused rather than
impossible, and an install failure is swallowed by the hook loop (B2).

### Proposed

```python
boot_standard(app, perf_timeline):
    # 1. core infrastructure  (NO engine here)
    ...
    # 4. load plugins -> app._runtime_store_factories: dict[str, RuntimeStoreFactory]
    # 6. resolve config
    # 6.5 SELECT AND PREPARE  <-- new, ~30 lines
    config = resolve_runtime_store_config(app)
    factory = select_factory(app._runtime_store_factories, config)
    store = factory.prepare(config, namespace_for(app))   # migrate + health-check
    check_required_capabilities(store.profile, config)    # refuse here, loudly
    app._runtime_store = store
    # 6.6 build the engine WITH its storage
    app._execution_engine = build_engine(app, runtime_store=store)
    # 9. APP_READY — plugins observe a fully wired app
```

`prepare()` is allowed to raise, and nothing catches it. That is the whole of the B2
fix, and it does **not** require changing what an `APP_READY` hook means — a telemetry
plugin that throws still must not kill boot.

### Is moving it safe?

`app._execution_engine` is not read anywhere between its assignment and `APP_READY` on
either boot path — the only occurrence in that span is the assignment itself. But a
grep is not a proof, so [`08-delivery-and-tests.md`](08-delivery-and-tests.md) §2
specifies the sabotage test that makes it one.

### What about `boot_static`?

Same move, same place. `boot_static` already runs explicit plugins and fires
`APP_READY` (`boot.py:419-468`), so the selection step slots in identically. Design 1's
Wave 1 gate correctly insists both paths are covered; this design keeps that.

---

## 5. The document store, honestly described

`DocumentRuntimeStore` wraps today's `ScopeStore` / `RunStore` / `ScopeStateStore` and
declares what they actually do:

```python
DOCUMENT_PROFILE = StoreProfile(
    name="documents",
    cross_aggregate_atomicity=False,   # B3: no call site locks two keys
    fencing="process-local",           # B1/B4 — even after the repair wave,
                                       # two documents cannot fence as one
    multi_process=False,               # flock is advisory and gives up
    multi_machine=False,
    durable_outbox=False,
    versioned_migrations=False,
    interactive_transaction=True,      # it is a local lock, not a protocol
    remote=False,
    max_document_bytes=None,
    offline_capable=True,              # the reason it is the default
    description="JSON documents under .functualize/. The default when no "
                "storage plugin is installed.",
)
```

Contrast Design 1, which would run the same semantic suite against this store and mark
the failures `TRANSITIONAL`. Under Design 3 the suite is tiered: a **baseline** tier
every store must pass, and **capability** tiers gated on profile fields. A store that
declares `durable_outbox=False` does not run the outbox suite and does not get to be
selected by a feature that needs one.

---

## 6. What happens to `StoreSubstrate`

It stays, narrowed and **made public**.

- It remains the port for `fresh` (derived fingerprints) and `shell-history`
  (delivery-local recall) — data whose discard rules and locality genuinely differ
  from runtime truth. Design 1 reaches the same conclusion.
- It is exported from `functualize.plugin`, with `Stored`. Today it is public
  nowhere while `docs/guides/workflows.md:386` instructs authors to import
  `functualize._types.protocols.StoreSubstrate` — a private path.
- The four concrete stores currently in `functualize.app.utils.__all__` get an
  explicit decision rather than silent deletion. Recommended: deprecate `ScopeStore`
  and `RunStore` for one minor version, pointing at the reader ports; keep
  `FreshStore` and `ShellHistoryStore`, which remain substrate-backed.

`tests/test_public_api_surface.py` enforces the surface, so this is a decision someone
has to make deliberately. Neither other design mentions it.

---

## 7. Why this is better, restated compactly

1. **It is executable on Monday.** Wave 0 is bug fixes against existing shapes and
   needs no ADR. Design 1 cannot start until a layer ADR lands.
2. **It makes the migration source trustworthy** before migrating it. Neither other
   design does.
3. **It deletes the handle argument** by moving construction, rather than winning or
   losing it.
4. **It replaces an unachievable contract with a typed capability**, so incapability
   is a value and not a footnote.
5. **It adds no layer**, so the seven contracts and the ADR they encode stay as they
   are.
6. **It does not build a two-backend abstraction against one backend** — the mistake
   ADR-022 exists to record.
7. **It costs the public-API break** that both other designs leave uncosted.

And what it gives up, stated plainly: the full provider family, admin surface and
generalized query object of Design 1. Those remain available and additive once FUN-22
chooses a database — see [`09-decisions.md`](09-decisions.md) §4.

---

Next: [`06-data-model.md`](06-data-model.md).
