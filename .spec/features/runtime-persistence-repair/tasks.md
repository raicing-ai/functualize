# FUN-24 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Add the generation fence to ScopeStateStore._mutate
      *Files:* `src/functualize/_primitives/scope_state_store.py`
- [ ] **1.2** Make Stored.revision an opaque token; update the SQLite substrate to match
      *Files:* `src/functualize/_types/protocols.py, plugins/functualize-state-sqlite/.../substrate.py`
- [ ] **2.1** Pass expect= on ScopeStore._mutate's write; keep lock() as defence in depth
      *Files:* `src/functualize/_primitives/scope_store.py`
- [ ] **2.2** Delete the dead "state": {} field and its now-wrong docstring
      *Files:* `src/functualize/_primitives/scope_store.py`
- [ ] **3.1** Install the substrate in a boot step that may raise, before APP_READY
      *Files:* `src/functualize/_app/boot.py`
- [ ] **3.2** Route TUI shell history through the installed substrate
      *Files:* `src/functualize/_cli/tui/shell_mode.py`
- [ ] **4.1** Sabotage tests: two-process claim race, stale-runner state write, boot-failure, TUI/CLI agreement
      *Files:* `tests/`

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "1.1",
        "1.2"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "2.1",
        "2.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "3.1",
        "3.2"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "4.1"
      ]
    }
  ]
}
```
