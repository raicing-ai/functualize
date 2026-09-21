# FUN-17 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Write _types/persistence.py: StoreProfile with all ten fields
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **1.2** Write the command and view dataclasses
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **2.1** Write the RuntimeStore and buffering RuntimeTransaction protocols
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **2.2** Write the writer and reader protocols
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **3.1** DocumentRuntimeStore adapter over today's stores, declaring an honest profile
      *Files:* `src/functualize/_primitives/document_store.py`
- [ ] **4.1** run_recorder.py — lifecycle moments to StartAttempt/FinishAttempt
      *Files:* `src/functualize/_engine/recording/run_recorder.py`
- [ ] **4.2** workflow_recorder.py — walk moments to Claim/CompleteStep/Suspend/Resume
      *Files:* `src/functualize/_engine/recording/workflow_recorder.py`
- [ ] **5.1** Move construction to _app/boot.py; engine accepts runtime_store
      *Files:* `src/functualize/_app/boot.py, src/functualize/_engine/executor.py`
- [ ] **5.2** Delete the lazy substrate property and add the tripwire test
      *Files:* `src/functualize/_engine/executor.py, tests/`
- [ ] **6.1** require() capability check with a refusal naming store, field and config key
      *Files:* `src/functualize/_app/`

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
        "3.1"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "4.1",
        "4.2"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "5.1"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "5.2"
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
