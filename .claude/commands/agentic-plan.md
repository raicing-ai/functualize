Plan phase for: $ARGUMENTS

Prerequisite: verify `.spec/features/<name>/spec.md` exists and is user-confirmed.

1. Read `.spec/STATE.md` — if absent, treat as: no work in flight
2. **Retrieval pass — call sites and blast radius.** Not optional, and not the
   same pass Specify ran. For every symbol the approach touches:
   - *What references this?* — **serena** `find_referencing_symbols`. LSP-accurate,
     so it is the only safe basis for a signature change. It also tells you which
     existing tests change meaning.
   - *What breaks if I change it?* — **graphify** `get_neighbors` for typed,
     directional dependents.
   - *Where is the seam, and is there a name collision?* — read the code the
     answers point at.

   **The task file lists in `tasks.md` are the hit sets of these queries**, not a
   list composed from memory. Anything that reshapes the approach goes in
   `research.md`. Pass an absolute worktree path — without one zvec-grep silently
   answers about the parent checkout.
   (Routing table: `.claude/skills/code-intel/SKILL.md`.)
3. Write `plan.md` — technical approach, files to change, dependencies, risks
4. If implementation internals are complex: write `schema.md` — DB tables, internal types, aggregation schemas
5. Write `tasks.md` — atomic tasks, each ≈ 1–3 files, completable in one context window. End with a `## Task Dependency Graph` section grouping tasks into waves (see spec-driven-developer agent for format and rules).
6. Review task list with user before Execute
