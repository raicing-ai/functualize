# Tasks — `_events` layer independence

## Wave 0 — move the wiring

### 1.1 Create `_app/event_wiring.py`

Files: `src/functualize/_app/event_wiring.py`

Add `install_config_event_sink(event_bus)` carrying the body of the old
`_events.adapter.install_adapter`, plus module-level `_sink_installed: bool`.
Import `EventBusAdapter` from `functualize._events.adapter`; import
`set_event_sink` from `functualize._config._emit` inside the function, still
guarded by `try/except (ImportError, ModuleNotFoundError)`.

Acceptance: `uv run python -c "from functualize._app.event_wiring import install_config_event_sink"`
succeeds.

### 1.2 Strip the peer import out of `_events/adapter.py`

Files: `src/functualize/_events/adapter.py`

Delete `install_adapter` and `_adapter_installed`. Keep `EventBusAdapter`
unchanged. Update the module docstring — it currently opens "bridges
config._emit → EventBus", which stops being true of this module.

Acceptance: no peer *import* remains —
`grep -rnE "^\s*(from|import)\s+functualize\.(_config|_discovery|_engine|_plugins|_gate|_app|_cli)" src/functualize/_events/`
prints nothing. A bare `grep functualize._config` is the wrong check:
`_events/_catalog_entries.py` stores peer module names as string literals in
the event catalog, which are data rather than imports.

## Wave 1 — repoint the caller

### 2.1 Update `_app/boot.py`

Files: `src/functualize/_app/boot.py`

Replace the `install_adapter` import and call with
`install_config_event_sink`. No other change in this file.

Acceptance: no *call site* remains — `grep -rn "install_adapter" src/ tests/`
returns only the historical mention in `_app/event_wiring.py`'s module
docstring, which explains where the wiring moved from.

### 2.2 Retarget the idempotency test

Files: `tests/observability/test_adapter_properties.py`

Import `install_config_event_sink` from `functualize._app.event_wiring`; reset
`event_wiring._sink_installed` where the test currently resets
`adapter_module._adapter_installed`. Leave the `EventBusAdapter` tests alone.

Acceptance: `uv run pytest tests/observability/ -q` passes.

## Wave 2 — enforce it

### 3.1 Add the import-linter contract

Files: `pyproject.toml`

Add the "Events depends on foundation only" forbidden contract from
`contracts.md`, including `functualize._config` in `forbidden_modules`.

Acceptance: `uv run lint-imports` reports all contracts kept, and the new one
is listed by name.

### 3.2 Prove reachability, then regress

Files: none (verification only)

Break `install_config_event_sink` so it raises, run a booted-app test, and
confirm failure — this proves `_app/boot.py` really reaches it. Restore, then
run `uv run pytest tests/observability/ tests/core/ tests/config/ -q`.

Acceptance: the sabotage fails a test before restoring; the full run is green
after.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] }
  ]
}
```
