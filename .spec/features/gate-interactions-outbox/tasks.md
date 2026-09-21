# FUN-21 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** InputRequest state machine wiring and the input recorder
      *Files:* `src/functualize/_engine/recording/input_recorder.py`
- [ ] **2.1** Gate deposit and reopen inside the transaction
      *Files:* `src/functualize/_engine/workflow_walker.py`
- [ ] **2.2** Evidence as reference plus digest
      *Files:* `src/functualize/_engine/recording/input_recorder.py`
- [ ] **3.1** The outbox table writer, committing with the transition
      *Files:* `src/functualize/_primitives/outbox.py`
- [ ] **3.2** The dispatcher, at-least-once, with consumer dedup
      *Files:* `src/functualize/_primitives/outbox.py`
- [ ] **4.1** Sabotage: kill between commit and dispatch; prove redelivery
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
        "2.1",
        "2.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "3.1"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "3.2"
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
