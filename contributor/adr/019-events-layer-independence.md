# ADR-018: Config event-sink wiring belongs to `_app`, not `_events`

**Status**: accepted
**Date**: 2026-09-08
**Deciders**: Hakim
**Supersedes**: `.spec/features/events-layer-independence/` (cleared on merge)

## Context

`.spec/CONSTITUTION.md` forbids `_events/` from importing any peer layer. It
did anyway:

```
src/functualize/_events/adapter.py:88   from functualize._config._emit import set_event_sink
src/functualize/_events/adapter.py:102  import functualize._config._emit as emit_module
```

Both were real runtime imports inside `install_adapter()`, not `TYPE_CHECKING`.

Nothing caught it. `_events` never appeared as a `source_module` in any
import-linter contract forbidding a peer layer, so `lint-imports` reported
5 kept / 0 broken while the violation sat in the tree. The rule existed in
three documents and in none of the enforcement.

The coupling was there for a good reason. `_config/_emit.py` exposes no-op emit
points called on every config operation; routing them through the EventBus
means replacing that sink with an `EventBusAdapter`. `_config` never imports
`_events` at runtime — the dependency runs the other way, and only at install
time.

## Decision

Move the wiring, not the adapter.

`EventBusAdapter` stays in `_events/adapter.py`. It depends on `EventBus`
alone and was always legal where it sat.

`install_adapter` becomes
`functualize._app.event_wiring.install_config_event_sink`. `_app` is the
composition root and, per the constitution, the "sole cross-layer wiring
point" — and `_app/boot.py` already drove the call.

A sixth import-linter contract, `Events depends on foundation only`, forbids
`_events` from every peer plus `_app` and `_cli`. `_config` is included rather
than excused, because this change removes the import that would have needed
excusing.

## Consequences

Behaviour is unchanged: the install is still idempotent, still tolerates a
missing `_config._emit`, and still replaces `set_event_sink` with a raising
stub afterwards. `install_adapter` was internal with one caller, so nothing
public moved.

The rule is now enforced rather than merely documented. Verified by
re-adding the import and watching the contract flip to BROKEN, and by
reachability: making `install_config_event_sink` raise turns
`tests/core/test_three_layer_caching.py` from 12 passed to 12 failed, proving
`boot.py` genuinely reaches it.

### What this does not fix

`exclude_type_checking_imports = true` hides every `if TYPE_CHECKING:` import
from all six contracts. `_config/chain.py` and `_config/sources.py` import
`EventBus` from `_events` that way, so `_config → _events` remains ungoverned.
Flipping the flag would likely break several contracts at once and has not
been measured; it is deliberately out of scope here.

## Related

- Contract definitions: `[tool.importlinter]` in `pyproject.toml` (six contracts)
- Diagram: `docs/diagrams/layer-dependencies.html`
- Agent-facing summary: `.serena/memories/architecture-layer-contract.md`
