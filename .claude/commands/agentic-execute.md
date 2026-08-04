Execute phase for: $ARGUMENTS

Prerequisite: verify `.spec/features/<name>/tasks.md` exists.

Context anchor — read ONLY these four files, nothing else:
- `.spec/PROJECT.md`
- `.spec/CONSTITUTION.md`
- `.spec/STATE.md`
- `.spec/features/<name>/tasks.md`

No chat history. No other specs. No unrelated files.

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
