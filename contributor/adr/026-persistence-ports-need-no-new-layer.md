# ADR-026: Persistence Ports Need No New Layer — `_types`, `_engine`, `_app`

**Status**: accepted
**Date**: 2026-09-23
**Deciders**: maintainer, during `runtime-persistence-ports` (FUN-17)

## Context

[ADR-025](025-engine-owns-transition-meaning.md) settles *who owns what*. This
one settles *where the code goes*, which is a separate question with its own
wrong answer.

The runtime is gaining a set of persistence ports: a capability record, a store
protocol, a buffering transaction, five writers, three readers, and a family of
command and view types. The reflex is to give them a home of their own —
`src/functualize/_persistence/` — and that reflex was proposed.

### The package structure is a dependency order, not a filing scheme

`.spec/CONSTITUTION.md` fixes the internal layering:

```
_types (shared vocabulary, zero logic)
  → _primitives (zero-dep utilities)
    → _events (cross-cutting concerns)
      → _discovery / _config / _engine / _plugins / _gate (peer layers)
        → _app (composition root — sole cross-layer wiring point)
          → _cli (delivery — public API only)
```

Seven `[tool.importlinter]` contracts in `pyproject.toml` enforce it. Adding
`_persistence/` as a sixth peer is therefore not a directory decision: it is a
contract change, it needs its own ADR, and it makes the peer-independence rule
harder to state — because the new peer would be the one every other peer wants
to talk to.

### The layers these ports want already exist and already permit this

Nothing about the ports needs a new layer, once you ask which layer each piece
belongs to by its dependency shape rather than by its subject matter:

- The ports are **vocabulary with zero logic** — protocols, frozen dataclasses,
  a capability record. `_types` is defined as exactly that, and every layer may
  already import it. A port in `_types` is reachable from `_engine`, from
  `_primitives` and from `_app` with no contract touched.
- The recorders **translate lifecycle moments**, and the lifecycle lives in
  `_engine`. They are not storage; per ADR-025 they hold no decisions.
- The **wiring** — choosing an implementation, constructing it, handing it to
  the engine — is cross-layer composition, which `_app` exists to be the sole
  site of.

Subject-matter filing ("everything about persistence lives together") would put
all three in one package and cut across the dependency order to do it. That is
the trade this ADR declines.

### One implementation does not earn an abstraction package

There is one runtime store at ship time: an adapter over the document stores
already in `_primitives`. A second is planned and not written. ADR-022 records
what the project paid last time for building a two-implementation abstraction
against one implementation, and the shape chosen here is a strict subset of the
larger one — so widening later is additive rather than a rewrite.

### `lint-imports` alone cannot police this

Worth recording, because it changes what "the contracts still pass" is worth as
evidence. `exclude_type_checking_imports = true` is set, so imports inside
`if TYPE_CHECKING:` blocks are not evaluated by the contracts. A deferred
`_types → _app` import leaves `uv run lint-imports` reporting *7 kept, 0 broken*
while the violation sits in the tree — measured by adding one, and recorded in
`contributor/architecture/codemaps/dependencies.md`. The same blind spot already
required a dedicated import-line test at
`tests/types/test_plugin_host_port.py`.

## Decision

**No new peer layer. Ports in `_types`, recorders in `_engine`, wiring in
`_app`. The seven import-linter contracts are unchanged.**

### Placement

| Piece | Home | Why that layer |
|---|---|---|
| Capability record, store and transaction protocols, writers, readers, commands, views | `src/functualize/_types/persistence.py` | vocabulary with zero logic; every layer may import `_types` |
| Lifecycle-moment translation | `src/functualize/_engine/recording/` | the lifecycle it translates already lives in `_engine` |
| Store selection, construction, capability check | `src/functualize/_app/` | the sole cross-layer wiring point |
| The document-store adapter | `src/functualize/_primitives/` | it wraps the three document stores that already live there |

### One file, and why it is not three

The whole contract goes in `_types/persistence.py` rather than splitting into
`profile.py` / `commands.py` / `protocols.py`. Two reasons, one principled and
one concrete: it is read as a unit — a reviewer checking whether a writer can
return a value needs the transaction semantics in view — and `_types/commands.py`
is **already taken** by the shell's runtime command tree. A second module of that
name would collide two unrelated meanings of "command" inside one package.

The module is projected at roughly 340 lines of declarations. That is a large
file and a deliberate one; the ~500-line threshold in `.spec/CONSTITUTION.md`
governs **classes**, and no class here exceeds about fifteen lines.

### The adapter goes in `_primitives`, not `_engine`

It wraps the scope store, the run store and the scope-state store, all of which
are in `_primitives`. Placing it in `_engine` would be legal by the contracts and
wrong by ADR-025: it puts storage adaptation inside the layer that owns
lifecycle meaning, which is the boundary that ADR exists to hold.

### The layer claim is proved twice

`uv run lint-imports` must report seven contracts kept and zero broken, **and**
an import-line test must read the actual import lines of
`_types/persistence.py`. The first is necessary and, for the reason in the
Context, not sufficient. Both are required before the work closes.

## Consequences

### Positive

- **No contract edit, so no second approval gate.** The work can proceed on the
  strength of this ADR rather than waiting on a layering change.
- **The ports are reachable from everywhere that needs them** — `_engine`,
  `_primitives` and `_app` — without any layer importing sideways.
- **The peer-independence rule stays simple.** No peer acquires a dependency on
  a new peer.
- **A future provider family remains available.** This shape is a subset of it,
  so growing into one is additive.

### Negative

- **Persistence is spread across four packages**, so "show me the persistence
  code" is four paths rather than one. Accepted: the dependency order is the
  more valuable invariant, and the alternative buys tidiness with a contract
  change.
- **`_types/persistence.py` is a big file** and will grow as commands are added.
  Re-examine if it passes 500 lines.

### Neutral

- Nothing moves. Every existing module stays where it is; this is additive
  placement, not a reorganisation.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| `src/functualize/_persistence/` as a sixth peer layer | One home for the subject; matches how people talk about it | Needs a contract edit and its own approval; the new peer is the one every peer wants to import; built for one implementation | Cost is real and immediate, benefit is filing convenience |
| Ports in `_primitives` instead of `_types` | Next to the stores they adapt | `_primitives` is not the vocabulary layer; `_types` is the one layer everything may import | Would force peers to import `_primitives` for a protocol |
| Recorders in `_app` with the wiring | Keeps `_engine` untouched | The lifecycle moments they translate are `_engine`'s; `_app` would have to reach into engine internals to observe them | Inverts the dependency for no gain |
| Split the ports across three `_types` modules | Smaller files | Read as a unit in practice; `_types/commands.py` name is already taken | Collides with an existing module and separates what reviewers read together |

## What would reopen this

A **second** runtime store whose implementation cannot live in `_primitives` —
one carrying a driver, a connection pool and a migration runner, say. At that
point the two implementations plus their shared machinery may genuinely
outgrow the current homes, and a peer layer becomes a proposal with evidence
behind it rather than a reflex. The port definitions would stay in `_types`
regardless; it is the *implementations* that would be asking for a home.
