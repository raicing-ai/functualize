Execute phase for: $ARGUMENTS

Prerequisite: verify `.spec/features/<name>/tasks.md` exists.

Context anchor — read ONLY these files, nothing else:
- `AGENTS.md`
- `.spec/CONSTITUTION.md`
- `.spec/ARCHITECTURE.md`
- `.spec/TESTING.md`
- `.spec/STATE.md` — if absent, treat as: no work in flight
- `.spec/features/<name>/tasks.md`
- **this feature's own confirmed artifacts:** `.spec/features/<name>/spec.md`, `plan.md`,
  `schema.md` (if present), `contracts.md`, and `matrix/**` (if present: the measurement kit and
  its recorded evidence)

Still forbidden:
- **any other feature's** `spec.md`, `plan.md`, `schema.md` or `contracts.md`;
- this feature's `research.md`, which is findings, never a gate, and which no task may name as an
  input;
- chat history;
- unrelated files.

**Why the feature's own artifacts are in.** The six-file anchor forbade them, yet tasks are
written against them, and Verify mandates reading two of them (`spec.md` and `contracts.md`,
`agentic-verify.md` steps 2 and 2b). An executor could then neither read a task's named inputs nor
re-derive them without re-deciding design mid-implementation.

**The anchor restricts spec documents, not the codebase.** Reading source and
running retrieval — `rg`, serena, graphify, zvec-grep — is expected: you cannot
implement a task, derive a gate's hit set, or run step 5's reachability check
without it.

1. Read context anchor (above only)
2. Read the `## Task Dependency Graph` at the bottom of `tasks.md`. Find the lowest-numbered wave with unchecked `[ ]` tasks — that is the current wave. If no graph exists, fall back to sequential order.
3. Pick any unchecked `[ ]` task within the current wave
4. Implement
5. **Reachability check — before marking the task done.** Name the production
   call path that reaches the code you just added (e.g. `execute() →
   _preflight_check → Preflight.check`). If the only caller is a test, the task
   is not done: wire it, or say plainly in your report that it is unwired and
   which task will wire it.

   **Commit the finished change first.** Then break that path once — comment
   out the call, `if False:` the branch — confirm a test fails, restore with
   `git checkout -- <file>`, and amend the commit with the result. Commit
   first because that restore reverts *everything* uncommitted in the file:
   done out of order it has silently discarded completed work. If the change
   is not yet coherent enough to commit, copy the file to the scratchpad and
   restore with `cp -f` (plain `cp` prompts and will hang a non-interactive
   shell, leaving sabotaged source in the tree).

   If nothing fails, the integration is untested no matter how well the
   component is covered. Sabotage also catches a *vacuous test* — one that
   passes under the very regression it claims to cover — which running it
   cannot.

   This exists because three capabilities shipped built, unit-tested, and
   unreachable while every gate stayed green. See
   `contributor/guides/wiring-discipline.md` §3.
6. Mark task [x] in `tasks.md`
7. Update `STATE.md` with current in-flight task
8. If the current wave is now fully `[x]`, advance to the next wave and note the transition in `STATE.md`
9. Repeat until all tasks are [x]
