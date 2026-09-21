# FUN-19 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** SqliteRuntimeStore: connection lifecycle and close(), which the current substrate lacks
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **1.2** Schema creation and migration runner wiring
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **2.1** The buffering transaction: accumulate commands, commit once
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **2.2** The writers, with the generation predicate in the WHERE clause
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **3.1** The question-shaped readers
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **4.1** The baseline conformance tier
      *Files:* `tests/conformance/test_baseline.py`
- [ ] **4.2** Capability tiers gated on profile fields
      *Files:* `tests/conformance/test_capabilities.py`
- [ ] **5.1** Offline legacy migration with backup, verification and refusal
      *Files:* `src/functualize/_primitives/migrate_legacy.py`
- [ ] **6.1** Run BatchOnlySqliteDriver against the store; prove the transaction buffers
      *Files:* `tests/conformance/`

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
        "2.1"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "2.2"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "3.1"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "4.1",
        "4.2"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "5.1"
      ]
    },
    {
      "id": 6,
      "tasks": [
        "6.1"
      ]
    }
  ]
}
```
