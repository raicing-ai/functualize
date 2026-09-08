# Plan — `_events` layer independence

## Approach

Move the wiring, not the adapter. `EventBusAdapter` is legal in `_events`
(it only touches `EventBus`); only `install_adapter` reaches into `_config`.
So lift that one function into `_app/`, which the constitution already names
the "sole cross-layer wiring point", and which already calls it.

A new module `_app/event_wiring.py` rather than more code in `boot.py`:
`boot.py` is already ~900 lines, and the idempotency flag wants a module of its
own so a test can reset it without touching boot state.

## Files

| File | Change |
|---|---|
| `src/functualize/_app/event_wiring.py` | **new** — `install_config_event_sink()` + `_sink_installed` |
| `src/functualize/_events/adapter.py` | delete `install_adapter` and `_adapter_installed`; drop the `_config` imports; keep `EventBusAdapter`; update module docstring |
| `src/functualize/_app/boot.py` | import and call `install_config_event_sink` instead of `install_adapter` |
| `pyproject.toml` | add the "Events depends on foundation only" contract |
| `tests/observability/test_adapter_properties.py` | retarget the idempotency test at the new location |

## Risks

**The monkey-patch must survive the move.** `install_adapter` rebinds
`emit_module.set_event_sink` to a raising stub. Rebinding a module attribute
from `_app` works identically to rebinding it from `_events` — it is the same
module object either way — but the raising stub's closure must not capture
anything from `_events`. It captures nothing today.

**Idempotency flag relocation is observable.** The existing test reaches for
`adapter_module._adapter_installed` directly and restores it in a `finally`.
Moving the flag means the test must reset the new one or later tests in the
same session see an already-installed sink. Task 2.2 carries that.

**Import-linter contract ordering.** Contracts are independent, so insertion
position is cosmetic; place it next to the other `forbidden` contracts.

**No behaviour change is intended.** If `tests/observability/` needs edits
beyond the two symbol renames, that is a signal the move changed semantics —
stop and re-read rather than adapting the test.

## Verification

Reachability, not just green tests: `_app/boot.py` is the only production call
path. Break it (make `install_config_event_sink` raise) and confirm a booted-app
test fails — that proves the wiring is actually reached rather than merely
imported by a unit test.

Then:

```bash
uv run lint-imports                              # all contracts kept
grep -rn "functualize\._config" src/functualize/_events/   # must be empty
uv run pytest tests/observability/ -q
uv run pytest tests/core/ tests/config/ -q       # boot + config regression
```
