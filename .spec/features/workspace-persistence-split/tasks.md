# FUN-23 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Define the workspace port
      *Files:* `src/functualize/_types/persistence.py`
- [ ] **2.1** Reference-and-digest storage for artifacts in runtime rows
      *Files:* `src/functualize/_primitives/`
- [ ] **3.1** Decide physical co-location; record it
      *Files:* `contributor/adr/`
- [ ] **4.1** Evaluate AgentFS against the workspace port and write the ADR
      *Files:* `contributor/adr/`

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
        "2.1"
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
        "4.1"
      ]
    }
  ]
}
```
