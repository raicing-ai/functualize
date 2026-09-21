# FUN-25 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** Point the probe at floci and find out whether it implements S3 conditional writes and DynamoDB TransactWriteItems at all
      *Files:* `tests/substrate_probe/_floci_survey.py`
- [ ] **1.2** Write the ten probe questions as one backend-agnostic harness
      *Files:* `tests/substrate_probe/harness.py`
- [ ] **2.1** BatchOnlySqliteDriver — refuses interactive transactions, accepts one batch
      *Files:* `tests/substrate_probe/fakes.py`
- [ ] **2.2** FakeObjectStore and FakeItemStore
      *Files:* `tests/substrate_probe/fakes.py`
- [ ] **3.1** Tier A backends: JSON files, local SQLite, and the three fakes
      *Files:* `tests/substrate_probe/tier_a.py`
- [ ] **4.1** Tier B: Cloudflare D1 (real)
      *Files:* `tests/substrate_probe/d1.py`
- [ ] **4.2** Tier B: AWS DynamoDB (floci then real)
      *Files:* `tests/substrate_probe/dynamodb.py`
- [ ] **4.3** Tier B: AWS S3 (floci then real)
      *Files:* `tests/substrate_probe/s3.py`
- [ ] **5.1** Tier C: Turso/libSQL and Supabase Postgres, if cheap
      *Files:* `tests/substrate_probe/tier_c.py`
- [ ] **6.1** Write the results matrix and answer the three open questions
      *Files:* `contributor/architecture/research/substrate-capability-matrix.md`

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
        "4.2",
        "4.3"
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
        "6.1"
      ]
    }
  ]
}
```
