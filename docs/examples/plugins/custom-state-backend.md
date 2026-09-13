# Custom Substrate — Plugin Example

Bring your own storage. Implement `StoreSubstrate` — the one seam that decides
where functualize keeps its own bookkeeping — and install it at boot. Every
store follows, because there is one place that decides and one object handed to
all of them.

This example's implementation is a dict. The shape is what transfers: it is the
same shape `functualize-state-sqlite` fills with a database.

## Source

[`examples/plugins/custom_state_backend/`](https://github.com/raicing-ai/functualize/tree/master/examples/plugins/custom_state_backend)

## The Protocol

Six members. A substrate is asked for a **document** by key; it is never asked
what a scope is or which document refuses an unreadable read — those are
decisions about meaning and they stay on the stores.

```python
from functualize._types.protocols import Stored, StoreSubstrate

class MySubstrate:
    def read(self, key: str) -> Stored | None: ...
    def write(self, key: str, payload: dict, *, expect: int | None = None) -> bool: ...
    def lock(self, *keys: str): ...                 # a context manager
    def clear(self, key: str) -> str | None: ...    # `func builtin data clear`
    def delete(self, key: str) -> bool: ...         # the scope purge
    def describe(self, key: str) -> str: ...        # `func builtin data show`

assert isinstance(MySubstrate(), StoreSubstrate)
```

Two distinctions the stores depend on:

- **Nothing stored is not an empty document.** A missing `scopes` reads as "no
  scopes"; an empty one reads as "a scope file that happens to be empty". Return
  `None` for the first and a `Stored` for the second.
- **`clear` is not `delete`.** `clear` is the documented way out of a document
  that cannot be read and may keep a copy aside; `delete` is the scope purge and
  must not.

**Two ways to be safe, because backends differ.** A filesystem gets mutual
exclusion from `flock`; a remote store often cannot offer it and needs
compare-and-swap instead, so `write(..., expect=)` is in the port from the start
and reports refusal rather than assuming a lock was held.

## Plugin Boot Class

```python
class MyPlugin:
    name = "state-my-substrate"

    def __call__(self, app):
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app):
        app.substrate = MySubstrate()
```

`APP_READY` and not later: the engine resolves its substrate lazily, on the
first store access, and installing after that is **refused** rather than
half-applied. Some of a run's documents in one backend and some in another is
the state this seam exists to make unreachable.

## Why this is not a `StateBackend`

It used to be. [ADR-022](https://github.com/raicing-ai/functualize/blob/master/contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md)
records why the key-value domain was retired: a backend-agnostic key-value
protocol can only offer the **intersection of every backend**, which is worth
least exactly where having a real database is worth most. The MCP history tools
were the proof — `get_job_history` could not ask for "recent executions", so it
probed four method names and took whichever the installed backend had.

Durable state for a *job* is a different question, answered by `rc.state` and by
the workflow scope — not by a storage plugin.

## Key Concepts

- **Protocol compliance** — `isinstance(substrate, StoreSubstrate)` validates the shape
- **One decision** — the substrate is chosen once; fingerprints, scopes and the
  run log all follow it
- **Entry points** — auto-discovery without manual configuration

## Related

- [Custom Adapter Example](custom-adapter.md)
- [Plugins Guide](../../guides/plugins.md)
- [Scaffold CLI](../../cli/scaffold.md)
