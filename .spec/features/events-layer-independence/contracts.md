# Contracts — `_events` layer independence

## Removed

### `functualize._events.adapter.install_adapter(event_bus: EventBus) -> None`

Deleted. It was internal (`_events` has no `__init__` re-export of it) and had
exactly one production caller, `_app/boot.py:100`.

Module-level state `functualize._events.adapter._adapter_installed` is deleted
with it.

## Unchanged

### `functualize._events.adapter.EventBusAdapter`

Stays in `_events`. Constructor and `emit()` behaviour untouched. Depends only
on `EventBus`, so it is legal where it sits.

## Added

### `functualize._app.event_wiring.install_config_event_sink(event_bus: EventBus) -> None`

New module `src/functualize/_app/event_wiring.py`.

Installs an `EventBusAdapter` as `_config._emit`'s sink so config resolution
events route through the EventBus, then replaces `set_event_sink` with a stub
that raises `RuntimeError`.

- Idempotent. Repeat calls return immediately; events are never double-routed.
- Tolerates a missing `functualize._config._emit`: logs at debug, marks the
  install complete, returns. Does not raise.
- After a successful install, `functualize._config._emit.set_event_sink(...)`
  raises `RuntimeError` whose message names `app.event_bus.subscribe()`.

Module-level state `_sink_installed: bool` carries the idempotency flag, in
`_app` where the wiring now lives.

## Import-linter contract added

`pyproject.toml`, `[[tool.importlinter.contracts]]`:

```toml
name = "Events depends on foundation only"
type = "forbidden"
source_modules = ["functualize._events"]
forbidden_modules = [
    "functualize._discovery",
    "functualize._config",
    "functualize._engine",
    "functualize._plugins",
    "functualize._gate",
    "functualize._app",
    "functualize._cli",
]
```

`_config` is included — unlike the grandfathering variant considered and
rejected — because this feature removes the only import that needed excusing.

## Test contract change

`tests/observability/test_adapter_properties.py` imports `install_adapter` from
`functualize._events.adapter` and manipulates
`adapter_module._adapter_installed`. Both move: the import becomes
`functualize._app.event_wiring.install_config_event_sink`, and the flag becomes
`event_wiring._sink_installed`. `EventBusAdapter` assertions are unaffected.
