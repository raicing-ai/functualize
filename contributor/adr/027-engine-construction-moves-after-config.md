# ADR-027: Engine Construction Moves to After Config Resolution

**Status**: accepted
**Date**: 2026-09-23
**Deciders**: maintainer, during `runtime-persistence-ports` (FUN-17)

## Context

`JobExecutionEngine` is constructed in boot step 1, before plugins load and
before config resolves. Its storage cannot exist that early — a storage plugin
has not been loaded yet, and the configuration naming a store has not been read.
So the engine does not receive storage. It goes and finds it, lazily, on first
access:

```python
# src/functualize/_engine/executor.py — the property this ADR removes
@property
def substrate(self) -> StoreSubstrate:
    if self._substrate is not None:
        return self._substrate
    from functualize._primitives.substrate import substrate_for_project
    chosen = getattr(self.host, "substrate_override", None)
    self._substrate = chosen or substrate_for_project(self.fresh_root)
    return self._substrate
```

### Three problems, one cause

The cause is ordering: the engine is built before the decision it depends on has
been made. The visible problems are downstream of that.

1. **The ordering is implicit.** Nothing states that a substrate must be
   installed before the first engine access. It is true by accident of when
   things happen to run, and a reader cannot see it.
2. **A late install is refused rather than impossible.** Installing after the
   engine has cached a substrate is a runtime error, when it could have been
   unrepresentable.
3. **An install failure is swallowed.** Storage is installed from an
   `APP_READY` hook, and the hook loop logs and continues
   (`_app/boot.py`, both boot paths). A plugin that fails to install its store
   leaves the app running on the filesystem default, silently.

The property also reaches into the host with
`getattr(self.host, "substrate_override", None)` — a defensive lookup against a
slot this repository declares on its own protocol (`_types/protocols.py`). The
same defensive-lookup pattern has already cost this project a silent break, in
`app/_workflow_control.py`, where a renamed method turned a missing attribute
into `None` and a cancel quietly fenced itself out.

### Engine construction time is not actually fixed

Every proposal to fix this by other means — a bind-once handle, a late-binding
closure, a registration hook — treats step 1 as immovable. It is not, and the
window is measurable rather than assumed.

Measured on this branch, with the first *read* of `app._execution_engine` after
its assignment located by walking the AST rather than by grepping line numbers:

| Path | engine constructed | config resolved | **first engine read** | `APP_READY` |
|---|---|---|---|---|
| `boot_static` | `:403` | `:413` | `register_descriptors` `:457` | `:469` |
| `boot_standard` | `:622` | step 6, ends `:830` | `validate_job_deps` `:860` | `:873` |

So on both paths there is a real, non-empty window **after config resolves and
before job registration** into which construction can move.

**A correction worth recording, because the earlier analysis got it wrong.** The
research this decision came from asserted that nothing reads the engine between
its construction and `APP_READY`. That is false on both paths:
`register_descriptors` and `validate_job_deps` both read it first. The claim
being wrong does not change the decision — it *narrows* it. The move target is
not "anywhere before `APP_READY`"; it is the bounded window above, and job
registration is the wall. Anyone revisiting this should re-measure rather than
trust either number: line numbers move, the shape does not.

## Decision

**Construct the engine in `_app` after config resolution, and pass its storage
in as a constructor argument.**

### The boot sequence gains one step

```
  4.  load plugins           → store factories registered by scheme
  6.  resolve config         → the store configuration is now readable
  6.5 SELECT AND PREPARE     ← new
        select the factory, construct the store,
        migrate and health-check it,
        refuse if a required capability is absent
  6.6 build the engine, with the store
  8.  register jobs          (the first reader of the engine)
  9.  APP_READY              plugins observe a fully wired app
```

Both boot paths take the same move. `boot_static` already runs explicit plugins
and fires `APP_READY`, so the step slots in identically.

### `prepare()` is allowed to raise, and nothing catches it

That is the whole of the swallowed-failure fix, and it does **not** change what
an `APP_READY` hook means. A telemetry plugin that throws still must not kill
boot. Choosing storage is a boot decision with no safe default, so it belongs in
a boot step that is permitted to fail — not in a general extension point whose
contract is to keep going.

### Two arguments, not one

`build_engine` takes **two** keyword-only arguments:

```python
build_engine(host, *, runtime_store, substrate)
```

`substrate` is not redundant. Deleting the lazy property removes the engine's
only source for the `StoreSubstrate` that `FreshStore` and `ScopeStore` still
need, and that port stays alive for derived fingerprints and delivery-local
recall — data whose discard rules and locality genuinely differ from runtime
truth. Folding the two into one argument would merge derived storage with
runtime truth, which is the drift this work exists to prevent. Two lifetimes,
two arguments, both injected.

Keyword-only so a positional call cannot silently bind the wrong one.

### The lazy property is deleted, and the deletion is proved

The property, its cached slot and the local `substrate_for_project` import all
go. A tripwire test must **fail if construction without a store becomes possible
again** — verified by re-adding a defaulted parameter and watching the test go
red, not by observing that the code currently has none. An absent path and an
untested path look identical in a green suite.

## Consequences

### Positive

- **The ordering becomes a signature.** A caller that forgets storage gets a
  `TypeError` at boot. A bind-once handle that was never bound fails at the
  first write — in a run, in production.
- **The swallowed install failure is gone**, without redefining `APP_READY`.
- **The capability refusal has somewhere to live.** Step 6.5 is a boot step that
  may fail, which is what makes "refuse rather than degrade" implementable at
  all.
- **The composition-root rule is strengthened, not bent.** `_app` does the
  wiring instead of a plugin reaching in at hook time.
- **Two smells go with it** — the `getattr` host read, and the chain through
  `self._state_store().substrate` used to build another store.

### Negative

- **A plugin installing a substrate at `APP_READY` now does so after the engine
  is wired**, so it no longer affects that engine. This is a real behaviour
  change for any such plugin and is pinned by a test rather than mentioned in a
  document.
- **Boot gains a step**, and boot is already long.
- **`build_engine`'s signature is breaking** for internal callers. It is
  internal — the only mention in the public folders is a comment — and the
  project carries no backward-compatibility obligation before v1.0.0.

### Neutral

- Roughly thirty lines of boot change. The engine's own responsibilities are
  untouched; it receives two objects it previously fetched.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| A bind-once `RuntimeStoreHandle` | Leaves construction where it is | Unbound handle fails at first write, in production, not at boot; keeps the implicit ordering | The problem is removable, not merely manageable |
| Keep the lazy property, fix the install guard | Smallest diff | Preserves all three problems; the ordering stays invisible | Treats the symptom |
| Re-raise from the `APP_READY` hook loop | Fixes the swallow directly | Changes what a hook means for every plugin; a telemetry plugin that throws would kill boot | Wrong lever — storage choice is not an extension point |
| A late-binding closure, as config already uses | Precedent exists in this file | Works for config because config is read per lookup; a store is a resource with a lifetime, and `close()` has nowhere to hang | Precedent does not transfer |
| Fold `substrate` into `runtime_store` | One argument | Merges derived-fingerprint storage with runtime truth | The exact drift this work exists to prevent |

## What would reopen this

A storage decision that genuinely cannot be made until after job registration —
for instance a store selected from a value only discoverable by inspecting the
registered jobs. That would put the construction site back inside the window
this ADR closes, and the answer would then be to split selection from
construction rather than to restore lazy discovery.
