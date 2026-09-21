# FUN-18 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Write the four state machines and their legal-transition tables
      *Files:* `schema.md`
- [ ] **1.2** Encode the transition table as data in _types/persistence.py
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **2.1** IllegalTransition, raised on any unlisted transition
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **3.1** The relational schema: attempts, runs, scopes, steps, events, gates, outbox
      *Files:* `schema.md`
- [ ] **3.2** Define the JSON boundary — what stays a blob and what becomes a column
      *Files:* `schema.md`
- [ ] **4.1** The versioned migration runner and its contract
      *Files:* `src/functualize/_primitives/migrations/`
- [ ] **5.1** Retention policy replacing the write-time 500-record eviction
      *Files:* `src/functualize/_primitives/migrations/`

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "1.1"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "1.2",
        "2.1"
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
    },
    {
      "id": 4,
      "tasks": [
        "5.1"
      ]
    }
  ]
}
```
