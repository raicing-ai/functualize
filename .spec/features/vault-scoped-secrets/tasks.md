# Scoped vault secrets tasks

The executable steps, exact files, interfaces, tests, and commit points are in [plan.md](plan.md). Complete each task's test cycle before marking it done.

- [ ] T1 — Add the typed identity codec and refuse legacy stores without migration.
- [ ] T2 — Validate scoped secret fields through the public app API, including cached and dynamic groups.
- [ ] T3 — Carry scope through the common resolution chain and establish vault-over-environment precedence.
- [ ] T4 — Parse and sync explicit `[[vault_secret]]` declarations; reject legacy inline provider syntax.
- [ ] T5 — Replace the positional vault CLI with scoped flags and metadata-only reports.
- [ ] T6 — Prove end-to-end behavior, replace docs, and amend the durable ADRs.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": "wave-1", "tasks": ["T1", "T2"]},
    {"id": "wave-2", "tasks": ["T3", "T4"]},
    {"id": "wave-3", "tasks": ["T5"]},
    {"id": "wave-4", "tasks": ["T6"]}
  ]
}
```
