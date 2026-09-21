# FUN-22 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** functualize-store-d1 skeleton and plugin registration
      *Files:* `plugins/functualize-store-d1/`
- [ ] **1.2** The D1 batch driver — one request per transaction
      *Files:* `plugins/functualize-store-d1/`
- [ ] **2.1** Reuse the SQLite schema and SQL against D1
      *Files:* `plugins/functualize-store-d1/`
- [ ] **2.2** Declare the profile from FUN-25's measured values
      *Files:* `plugins/functualize-store-d1/`
- [ ] **3.1** Run the full conformance suite against D1
      *Files:* `tests/conformance/`
- [ ] **4.1** The multi-machine tier: park on one host, resume on another
      *Files:* `tests/conformance/`
- [ ] **5.1** DynamoDB provider, only if FUN-25 confirmed TransactWriteItems fits
      *Files:* `plugins/functualize-store-dynamodb/`

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
    },
    {
      "id": 5,
      "tasks": [
        "5.1"
      ]
    }
  ]
}
```
