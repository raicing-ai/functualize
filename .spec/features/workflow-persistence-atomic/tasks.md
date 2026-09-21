# FUN-20 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Route FrontierWalk.claim through the workflow recorder; return Claimed | Conflict
      *Files:* `src/functualize/_engine/frontier.py`
- [ ] **1.2** Route renew and release the same way
      *Files:* `src/functualize/_engine/frontier.py`
- [ ] **2.1** Route step records and branch pins through the recorder
      *Files:* `src/functualize/_engine/workflow_walker.py`
- [ ] **2.2** Route gate suspend and resume through the recorder
      *Files:* `src/functualize/_engine/workflow_walker.py`
- [ ] **3.1** Nested workflow scope claims
      *Files:* `src/functualize/_engine/workflow_orchestrator.py`
- [ ] **4.1** Sabotage: break the fence predicate and watch the two-process test fail
      *Files:* `tests/`

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
        "1.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "2.1",
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
        "4.1"
      ]
    }
  ]
}
```
