# 04 — Three designs compared

Three people have now proposed how Functualize should persist runtime truth. This
page puts them side by side with real quotations, says where they agree, and argues
for the third.

**If you read one page in this folder, read this one.**

| | Name used here | Where it lives |
|---|---|---|
| **Design 1** | *Provider family* | [`../runtime-persistence/`](../runtime-persistence/README.md) — in this repository, mirrored to Confluence 5308716 |
| **Design 2** | *Minimal ports* | `.spec/scrutiny-reports/runtime-persistence-non-c4-review.md` §11, expanded on Confluence 6258689 |
| **Design 3** | *Engine-owned* | this folder |

---

## 1. What all three agree on

This is most of the substance, and it should not be lost in the argument:

- **One storage choice per application.** No per-store backend selection. This is
  ADR-022's invariant and all three keep it.
- **Columns for operational facts, JSON only for genuinely opaque payloads.**
  Status, position, timestamps, sequence numbers, lease fields and parent ids become
  columns; step inputs and gate schemas stay JSON.
- **Short transactions around transitions, never around job code.** A job body can
  block on a prompt for an hour; a database transaction cannot be held across it.
- **EventBus observes after commit.** It is not the durable record.
- **SQLite is local/single-host.** Multi-machine needs a network database.
- **Workspace bytes are a separate capability**, with runtime SQL holding references
  and digests.
- **No indefinite dual-write** during migration.

Design 3 adopts all seven unchanged. The disagreements are about **ownership,
placement, sequencing, and one claim of fact**.

---

## 2. Design 1 — Provider family

### What it proposes

A `RuntimePersistenceProvider` that manufactures a matched family of repositories
behind a Unit of Work, all living in a **new peer layer** called `_persistence`.

```python
# ../runtime-persistence/10-target-architecture.md
@runtime_checkable
class RuntimePersistenceProvider(Protocol):
    name: str
    capabilities: PersistenceCapabilities

    def migrate(self) -> MigrationReport: ...
    def health(self) -> PersistenceHealth: ...
    def unit_of_work(self, namespace: RuntimeNamespace) -> RuntimeUnitOfWork: ...
    def queries(self, namespace: RuntimeNamespace) -> RuntimeQueries: ...
    def admin(self, namespace: RuntimeNamespace) -> RuntimePersistenceAdmin: ...
    def close(self) -> None: ...
```

```text
src/functualize/
├── _types/persistence.py       # stdlib-only DTOs and protocols
├── _persistence/               # new independent peer layer
│   ├── handle.py               # bind-once runtime capability
│   ├── registry.py             # scheme -> provider factory
│   ├── document_adapter.py     # legacy stores behind semantic ports
│   ├── transitions.py          # backend-neutral short UoW operations
│   └── contract.py
```

Boot gains a `runtime_persistence` phase, and the engine receives a **bind-once
handle** rather than a provider:

> Core creates a bind-once `RuntimePersistenceHandle` and injects that stable port
> into the engine during core infrastructure setup. … The handle removes the current
> temporal race without forcing engine creation to move after every plugin.

### What it gets right

The capability record is the right idea. The normalization rule is well drawn, with an
explicit *bad JSON fields* list. The rejected-alternatives section is genuinely
useful — it forecloses "widen `StoreSubstrate` with query methods" with the correct
argument. The migration sequence has real gates rather than "done when tests pass".

### Where it is wrong

**(a) It asserts a capability the code does not have.** Its capability table rates the
document adapter `fencing: yes`. [`03-the-four-defects.md`](03-the-four-defects.md)
B1 and B4 show two independent holes, both reproducible.

**(b) Its Wave 1 contract is unachievable.** Wave 1 delivers
`DocumentRuntimePersistence` — the current stores behind the new semantic ports —
and marks it:

> `TRANSITIONAL`: semantic ports still delegate to document stores; on-disk data and
> transaction limits are unchanged.

while the ports it must satisfy include a Unit of Work whose whole purpose is
committing several aggregates together. B3 shows that atomicity has no implementation
and no call site. You cannot delegate a transaction to a layer that has none.

**(c) It puts transition ownership in the wrong module.** `_persistence/transitions.py`
is described as "backend-neutral short UoW operations" — that is, *lifecycle logic*.
The codebase already has an owner for lifecycle logic, and it is tested as such. See
§3.

**(d) It plans a migration whose source is corrupt.** Wave 3 imports today's JSON and
SQLite documents. Waves 0–2 do not fix B1–B4, so the import inherits them, and the
cutover's verification step cannot detect the difference.

**(e) It costs neither the public-API break nor the ring cap.** Its cleanup step says
"move or delete runtime stores from `_primitives`". Those four stores are public API
(`functualize.app.utils.__all__:259-265`), covered by
`tests/test_public_api_surface.py`. And `scopes` carries a 500-record terminal-only
eviction cap (`scope_format.py:144`) that no retention section mentions.

---

## 3. Design 2 — Minimal ports

### What it proposes

Explicitly the opposite placement decision:

> Do not add `_persistence` initially. Keep domain transition decisions in the engine
> and use a public factory plus `_types` ports for storage.

```python
# .spec/scrutiny-reports/runtime-persistence-non-c4-review.md §11
@runtime_checkable
class RuntimeStore(Protocol):
    profile: RuntimeStoreProfile
    runs: "RunReader"
    workflows: "WorkflowReader"
    inputs: "InputReader"

    def transaction(self) -> AbstractContextManager["RuntimeTransaction"]: ...
    def close(self) -> None: ...


class WorkflowWriter(Protocol):
    def claim(self, command: ClaimWorkflow) -> ClaimedWorkflow | Conflict: ...
    def suspend(self, command: SuspendWorkflow) -> InputRequest: ...
    def resume(self, command: ResumeWorkflow) -> ResumeStarted | Conflict: ...
    def complete_step(self, command: CompleteStep) -> None: ...
    def cancel(self, command: CancelWorkflow) -> CancelResult: ...
    def write_state(self, command: StateBatch) -> None: ...
```

> These are commands, not table CRUD. The engine-owned recorder builds commands from
> lifecycle context and emits `EventBus` notifications only after the transaction
> context exits successfully. **The provider implements atomicity; it does not decide
> what "resume" means.**

Its Confluence expansion adds explicit state machines (`Execution`: CREATED → RUNNING
→ SUSPENDED → READY → RUNNING → SUCCEEDED/FAILED/CANCELLED; `Input request`: OPEN →
ACCEPTED/CANCELLED/EXPIRED), an explicit `Attempt` aggregate separate from
`Execution`, a concrete SQLite policy list, and a decision register. It rejects
at-most-once outbox delivery outright:

> "Outbox delivery: at-least-once. Consumers must deduplicate by stable event ID. An
> 'at-most-once' claim is not compatible with crash-safe publication."

### What it gets right

Almost all of the structural judgement. Commands rather than CRUD. Engine keeps
lifecycle. No new peer layer. `Attempt` modelled separately from `Execution` — which
Design 1 omits and which the code demands, because retry loops *inside* one run
record (`exec_policy.py:112-132` sits at `executor.py:1472`, while the run record
opened at `:799`). Honest delivery semantics.

### Where it is incomplete

**(a) It does not schedule the repair.** It says "add the missing production
activation and no-lock race tests" as step 1, which characterises two of the four
defects but fixes none, and does not mention B1 (`rc.state` unfenced) at all.

**(b) It rejects late binding without solving construction order.** Its decision
register rejects "mutable backend selection after first store access" — correct — but
a store constructed from resolved config cannot reach an engine that was built at boot
step 1. It does not say how the store gets there. Design 1's handle is an answer to
that question; Design 2 declines the answer without replacing it.

**(c) One of its supporting arguments is factually wrong.** Its case against the
bind-once handle is that "the repository already states that the engine is complete at
construction". The code says otherwise, and this is checkable:

```python
# src/functualize/_app/boot.py:236-243  — already a late-binding closure
def _config_view_factory(*, section_prefix: str) -> Any:
    chain = getattr(app, "_resolution_chain", None) or ResolutionChain([])
```

`_resolution_chain` does not exist when `build_engine` runs at step 1. The engine
already late-binds config, and already late-binds the substrate through a lazy
property. The handle is not a novel violation; it is the third instance of an existing
pattern.

**(d) It misses the public-API break** (H4 in the assessment) — as does Design 1.

---

## 4. Design 3 — Engine-owned

### The thesis in one sentence

**The engine owns what a transition *means*; storage owns whether it is *durable*.**
Everything else follows from taking that seriously, including where the code lives.

Design 3 is Design 2's shape with four additions, each of which exists because
something in the code demanded it:

| Addition | Because |
|---|---|
| A **repair wave** before anything else | B1–B4 are writing the migration's source data |
| **Move engine construction after config resolution** | resolves Design 2's gap (b) and Design 1's handle in one move |
| A **`StoreProfile`** with per-capability declarations and boot-time refusal | replaces Design 1's unachievable uniform contract |
| **Export the port publicly**; decide the fate of the four public stores | neither other design costs this |

### Why "move construction" is the right answer to the handle argument

Design 1 introduces a bind-once handle because the engine is built before the provider
can exist. Design 2 rejects the handle but inherits the problem. Both treat engine
construction time as fixed. It is not:

```
boot_standard()                              _app/boot.py:485
  1. core infrastructure ... build_engine()   :614   <-- today
  ...
  6. RESOLVE CONFIG                           :754-798
  ...
  9. APP_READY                                :841
```

**Nothing reads `app._execution_engine` between line 614 and line 841.** Grep the
span; the only reference is the assignment. So:

```diff
- step 1: app._execution_engine = build_engine(app)
+ step 6.6: store = select_runtime_store(app)        # config is resolved by now
+ step 6.7: app._execution_engine = build_engine(app, runtime_store=store)
```

and the engine receives its storage as an ordinary constructor argument. No handle, no
lazy property, no `APP_READY` race, no new layer — and the "one composition root"
rule is strengthened rather than bent, because `_app` now does the wiring instead of a
plugin reaching in at hook time.

This is the single highest-leverage change in the folder and it is roughly thirty
lines.

### Why the profile beats the uniform contract

Design 1 says every provider passes one semantic suite, and the document adapter is
marked `TRANSITIONAL` where it cannot. That collapses two different things — "this
backend is slower" and "this backend cannot make you this promise" — into one word.

Design 3 makes incapability a typed value the caller can branch on:

```python
@dataclass(frozen=True)
class StoreProfile:
    name: str
    cross_aggregate_atomicity: bool
    fencing: Literal["none", "process-local", "cross-process"]
    multi_process: bool
    multi_machine: bool
    durable_outbox: bool
    versioned_migrations: bool
```

so the document adapter can say `cross_aggregate_atomicity=False,
fencing="process-local"` — which is **true today and provable** — and a feature that
needs more refuses at boot with a message naming the store and the missing capability.
This is also the honest home for the two documentation defects in
[`02-what-exists-today.md`](02-what-exists-today.md) §9: `multi_machine=False` is a
field, not a paragraph someone forgets to update.

### Why transitions stay in the engine

Design 1's placement is **legal**. That is worth stating plainly, because the earlier
adversarial review called it a blocker and overstated the case: a peer layer importing
`_types`, `_primitives` and `_events`, with `_app` wiring it and the engine consuming
protocols, is exactly what the independence contract permits
(`pyproject.toml:263-272`), and all seven contracts pass today.

The objection is **cohesion**, and it has a name. A transition service in
`_persistence` and the lifecycle in `_engine` would change together for one reason —
*shotgun surgery* — and the second authority arrives with no equivalent of:

```
tests/engine/test_lifecycle_order.py
```

which is what makes the engine's twenty-step order a contract rather than a comment
(`contributor/reference/execution-lifecycle.md:1-14`). Splitting lifecycle across two
modules where only one has an ordering test is how the order quietly stops being true.

### Why one backend does not earn a provider family

ADR-022 retired the previous abstraction — `StateBackend` / `ExecutionStore` — and
recorded exactly why, in terms that apply to Design 1:

> a backend-agnostic protocol … can only promise the **intersection** of every
> possible backend, so anything sharper has to be discovered by feeling around for it
> at runtime.

Design 1 proposes a provider that owns lifecycle, writes, queries, migrations, admin,
close **and** a repository family — and the only backend that will exist when it ships
is SQLite. FUN-22's network database is explicitly unchosen; its own ticket text says
"such as PostgreSQL or libSQL/Turso". Building a two-implementation abstraction
against one implementation is the shape ADR-022 warns about.

Design 3 therefore ships narrow ports now and leaves the provider-family move
available once FUN-22 picks a database. Nothing in Design 3 forecloses Design 1; it
sequences it.

---

## 5. Side-by-side

| Dimension | Design 1 · Provider family | Design 2 · Minimal ports | **Design 3 · Engine-owned** |
|---|---|---|---|
| Where persistence code lives | new `_persistence` peer layer | `_types` + `_app` | `_types` ports, `_engine/recording/` recorders, `_app` wiring |
| Who decides what "resume" means | `_persistence/transitions.py` | engine | engine |
| How the engine gets its store | bind-once handle, filled at a new boot phase | unspecified | **constructor argument; engine construction moves to after config** |
| Document adapter's promise | same semantic contract, marked TRANSITIONAL | "legacy/best-effort" prose | **typed `StoreProfile`; unmet capabilities refuse at boot** |
| Attempt identity | absent | explicit `Attempt` aggregate | explicit `Attempt` aggregate (adopted from 2) |
| State machines | after the schema | before the schema | **before the schema, and before the ports** |
| Outbox delivery | at-least-once *or* at-most-once | at-least-once only | at-least-once only (adopted from 2) |
| B1–B4 repair | not scheduled | partially characterised | **Wave 0, blocking everything** |
| Public-API break costed | no | no | **yes** |
| 500-record ring cap costed | no | no | **yes** |
| Backends when the abstraction ships | 1 (provider family) | 1 (narrow ports) | 1 (narrow ports) |

## 6. Honest accounting — what Design 3 takes from the others

This design is not independent invention and should not be read as such.

**From Design 1:** the capability record as a concept; the normalization rule and the
bad-JSON-fields list; the transaction catalogue's shape; the outbox pattern; the
workspace/artifact separation; the offline-cutover-with-backup migration; most of the
rejected-alternatives reasoning. `06-data-model.md` is closer to Design 1 than to
anything else in this folder.

**From Design 2:** commands over CRUD; engine-owned transitions; no new peer layer;
`Attempt` as a first-class aggregate; at-least-once only; the SQLite policy list
(`PRAGMA foreign_keys=ON`, `BEGIN IMMEDIATE` on claim paths, bounded busy timeout
surfaced as retryable).

**Original to Design 3:** the repair wave and its four reproductions; the
construction-order move; the typed `StoreProfile` replacing the uniform contract; the
public-port export and the public-store decision; the ring-cap accounting; the
correction of Design 2's "complete at construction" argument.

## 7. Where Design 3 could be wrong

Stated so a reviewer can attack it:

- **If FUN-22 picks a database soon**, Design 1's provider family stops being
  premature and the incremental route costs a refactor. The mitigation is that
  Design 3's ports are a strict subset of Design 1's; widening is additive.
- **Moving engine construction** is a real behavioural change to boot. The claim that
  nothing depends on the current position rests on a grep over one span in two
  functions. It needs a test, not a grep — [`08-delivery-and-tests.md`](08-delivery-and-tests.md)
  §2 specifies it.
- **The repair wave delays the feature** by two to four weeks. If the maintainer
  judges the four defects acceptable in the interim, the sequencing argument
  weakens — but the migration argument does not, because a corrupt source stays
  corrupt.

---

Next: [`05-the-design.md`](05-the-design.md).
