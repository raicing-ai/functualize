# Spec — `_events` layer independence

## Problem

`.spec/CONSTITUTION.md` states that `_events/` must not import `_discovery`,
`_config`, `_engine`, `_plugins`, `_app` or `_cli`. It does:

```
src/functualize/_events/adapter.py:88   from functualize._config._emit import set_event_sink
src/functualize/_events/adapter.py:102  import functualize._config._emit as emit_module
```

Both are real runtime imports inside `install_adapter()`, not `TYPE_CHECKING`.

No import-linter contract catches it. `_events` never appears as a
`source_module` in a contract forbidding a peer layer, so `lint-imports`
reports 5 kept / 0 broken. The violation is invisible to CI.

The coupling is bidirectional in intent: `_config/chain.py:22` and
`_config/sources.py:35` import `EventBus` back from `_events`, but only under
`if TYPE_CHECKING:`, and `exclude_type_checking_imports = true` hides that from
the linter too.

## Why it exists

`_config/_emit.py` exposes no-op emit points called on every config operation.
`_events.adapter.install_adapter()` replaces the sink with an `EventBusAdapter`
so config events route through the EventBus, then monkey-patches
`set_event_sink` to a raising stub so nothing can re-point it afterwards.

The design is sound — `_config` never imports `_events` at runtime. Only the
*location* of the wiring is wrong: `_events` reaches sideways into a peer.
`_app/` is the composition root and "sole cross-layer wiring point" per the
constitution, and it already drives the call (`_app/boot.py:100`).

## Behaviour required

1. `_events/` contains no runtime import of any peer layer. `EventBusAdapter`
   stays in `_events` — it depends only on `EventBus`.
2. The wiring — obtain `set_event_sink`, install an `EventBusAdapter`, block
   further `set_event_sink` calls — moves to `_app/`.
3. Behaviour at runtime is unchanged:
   - idempotent; installing twice does not double-route events
   - a missing `_config._emit` is tolerated, logged at debug, and marks the
     install done rather than raising
   - after install, `set_event_sink()` raises `RuntimeError` naming
     `app.event_bus.subscribe()` as the alternative
4. `lint-imports` gains a contract that would fail if `_events` imported a peer
   layer again, and passes.

## Acceptance criteria

- `uv run lint-imports` reports all contracts kept, including a new one naming
  `functualize._events` as a source module forbidden from `_discovery`,
  `_config`, `_engine`, `_plugins`, `_gate`, `_app`, `_cli`.
- No peer *import* remains in `_events`:
  `grep -rnE "^\s*(from|import)\s+functualize\.(_config|_discovery|_engine|_plugins|_gate|_app|_cli)" src/functualize/_events/`
  returns nothing. (A bare `grep functualize._config` is the wrong check —
  `_events/_catalog_entries.py` carries peer module names as string literals in
  the event catalog, which are data, not imports.)
- `uv run pytest tests/observability/ -q` passes.
- A booted app still routes config events through the EventBus: the existing
  idempotency property test passes against the relocated wiring.
- Calling `set_event_sink()` after boot still raises `RuntimeError`.

## Out of scope

- `exclude_type_checking_imports = true`. Flipping it would surface
  `_config → _events` and probably many more; it needs measuring on its own.
- The `_gate` and `workflow/` omissions in `.spec/CONSTITUTION.md`'s tables.
  Documentation-only, tracked separately.
