Plan phase for: $ARGUMENTS

Prerequisite: verify `.spec/features/<name>/spec.md` exists and is user-confirmed.

1. Read `.spec/STATE.md` — if absent, treat as: no work in flight
2. If exploration needed: write `research.md` first
3. Write `plan.md` — technical approach, files to change, dependencies, risks
4. If implementation internals are complex: write `schema.md` — DB tables, internal types, aggregation schemas
5. Write `tasks.md` — atomic tasks, each ≈ 1–3 files, completable in one context window. End with a `## Task Dependency Graph` section grouping tasks into waves (see spec-driven-developer agent for format and rules).
6. Review task list with user before Execute
