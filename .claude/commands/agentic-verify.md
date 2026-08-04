Verify phase for: $ARGUMENTS

Prerequisite: all tasks in `.spec/features/<name>/tasks.md` are [x].

1. Run project tests, lint, and type-check
2. Verify each acceptance criterion in `spec.md` is met
2b. **Walk the declared surface.** Go through this feature's section of
   `contracts.md` line by line. For each declared item, name the test that
   exercises it *through the public entry point*. A green suite is necessary,
   not sufficient — components tested only in isolation pass every gate while
   being unreachable in production.

   Items with no such test are the feature's real remaining work. Report them
   as such rather than closing over them. (`func why` was listed as an S3
   deliverable, was committed at the S3 gate, and did not exist as a command;
   this step is what would have caught it.)
2c. **Orphan scan.** List symbols defined in `src/` that only tests reference.
   Treat each hit as a question to answer, not a failure — public API meant for
   users, plugin extension points, and symbols called from within their own
   defining module are legitimate. A hit that is none of those is unwired code.
   See `contributor/guides/wiring-discipline.md`.

2d. **Spot-check the tests that carry the most weight.** Pick the assertions a
   reviewer would rely on — the ones pinning a precedence, an ordering, or a
   guard — and sabotage the source they cover. A test that passes under the
   regression it names is worse than no test, because it is read as coverage.
   **Commit before sabotaging**; the restore reverts everything uncommitted in
   the file (`contributor/guides/wiring-discipline.md` §3).
3. Run verification skills (each determines its own tier via blast-radius analysis):
   - Invoke `verify-e2e` against `.spec/features/<name>/spec.md` — the skill will determine whether FULL, TARGETED, SMOKE, or SKIP is appropriate based on what files the feature touched. If it reports failures, investigate and fix before proceeding.
4. Update `STATE.md`: mark feature complete with date
5. Update `ROADMAP.md`: move feature to done
