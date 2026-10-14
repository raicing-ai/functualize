# contracts.md — lazy-import-path-race

## External interfaces

**None change.** This feature alters no public signature, payload, CLI
surface, or protocol. `LazyJobFunction` keeps its constructor signature,
`materialize() -> tuple[Callable[..., Any], type | None]`,
`__functualize_lazy__`, and its `JobMaterializationError` chaining
contract. `_import_real_function` keeps its signature and its
`ImportError`/`AttributeError` raising contract.

## The internal seam the fix owns

```
_import_real_function(descriptor)   # _discovery/lazy_wrapper.py
  real-source branch:
    _IMPORT_LOCK (module-level, re-entrant)      # NEW — the only addition
      insert module_dir into sys.path if absent
      resolve the module (sys.modules hit / import / collision re-exec)
      remove module_dir iff this call inserted it   # finally, inside the lock
```

Contract of the new primitive, for every caller in the process
(`LazyJobFunction.materialize`, `EntryPointProvider._materialize` via the
synthetic-source branch, tests):

1. At most one thread executes the region at a time; re-entry from the
   same thread is permitted (a job module whose import nests another lazy
   materialisation cannot self-deadlock).
2. No removal happens while any importer holds the region, and no import
   starts while a removal is in flight.
3. `sys.path` on exit equals `sys.path` on entry, success or exception.
4. The synthetic-source branch (`<entry_point>` / `<dynamic>`) never takes
   the primitive — it does not touch `sys.path` and keeps loading in
   parallel.

## Invariants asserted by tests

- Concurrent first materialisation of same-module jobs yields zero
  `JobMaterializationError` (deterministic interleaving, AC-2) and zero
  across a many-batch stress run (AC-3).
- One module-body execution per module per process (import-count marker),
  before and after the fix.
- `sys.path` identity across success, import-time exception, and missing
  module (AC-5).
