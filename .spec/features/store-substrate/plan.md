# Plan — store substrate

## R-a · The port

```python
class StoreSubstrate(Protocol):
    """Where functualize keeps its own bookkeeping."""

    def read(self, collection: str) -> dict[str, Any]:
        """The whole envelope, or an empty one."""

    def write(
        self, collection: str, envelope: dict[str, Any], *, expect: int | None
    ) -> bool:
        """Replace it. False when `expect` did not match the stored version.

        `expect` is the whole reason this is not just `save()`. A filesystem
        gets mutual exclusion from `flock`; a remote store cannot, and needs
        compare-and-swap instead. Carrying it in the port from the start means
        the JSON implementation ignores it and a remote one does not have to
        invent a second method later.
        """

    def lock(self, collection: str) -> AbstractContextManager[None]:
        """Exclusive access, where the substrate can offer it.

        A no-op for a CAS-only backend, which is why `write` returns a bool
        rather than assuming the lock held.
        """
```

Three collections: `"scopes"`, `"runs"`, `"fresh"`. Names, not paths —
`beside_state` is a filesystem idea and goes away with the facade.

## R-b · What moves and what does not

**Does not move:** every typed method on the three stores. `record_step`,
`put_gate`, `get_fingerprint`, `open_run`, `append_event` are already pure
logic — the store classes touch a file **zero** times today (spec §C). They
gain a substrate in `__init__` instead of a `Path`.

**Moves:** the three `_format` modules become `JsonFileSubstrate`, one class.
Their 45 filesystem references collapse into it. The per-file discard rules
(`scopes.json` refuses, `state.json` discards) stay with the **store**, not the
substrate — they are decisions about meaning, not about storage, and flattening
them into the substrate would be the drift this feature exists to prevent.

**Is deleted:** `StateStore`'s 25 pass-through methods, `beside_state`,
`WorkflowScope.replace_state_store`, `StateStoreProtocol`, and the
`functualize-state` package.

## R-c · Order, and why

1. **T3b first** (`durable-run-layer`) — history leaves `state.json`. Without
   it, `FreshStore` is a store named for freshness containing a run log.
2. **The lease** (`durable-run-layer` T5–T8) — it builds the fencing token. A
   CAS-based substrate is the same primitive; building this first invents it
   twice.
3. Then this feature.

## R-d · Risk: the default must be invisible

`JsonFileSubstrate` has to behave exactly as today — same files, same
locking, same discard rules — or every existing project notices a refactor.
The suite is the check: it should pass unchanged against the default
substrate, and the only new tests should be the ones that swap it.

**Sabotage for this feature is the substrate swap itself.** If the test suite
passes with an in-memory substrate wired in, the stores are genuinely
substrate-agnostic; if it only passes on files, something still reaches
through.

## R-e · The proof obligation

AC-3 is the one that matters and the one easiest to fake. A test that swaps the
substrate *in the same process* proves nothing about Lambda — the objects are
still shared. It has to be **two processes with no shared disk**: write from
one, resume from the other, substrate configured to something neither owns.
`tests/integration/test_capability_duality.py::TestStateIsDurable` already does
the two-process trick for files and is the pattern to copy.
