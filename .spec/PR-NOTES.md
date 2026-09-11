# Notes for the PR body

Things a reviewer needs that the commit history does not say clearly.

## `5511bf0` carries more than its message admits

Subject: *"test: migrate the remaining slow suites to the durable State"*.
It also carries **the entire spec-workflow architecture gate** — 4 files,
+396/−19:

```
.claude/agents/spec-driven-developer.md | 100 +++++++++++--
.claude/commands/agentic-plan.md        | 142 ++++++++++++++++--
.claude/commands/agentic-specify.md     |  16 ++
.claude/rules/spec-workflow.md          | 157 +++++++++++++++++++-
```

**How.** That work was done by a separate agent in this same worktree and was
still uncommitted when I ran a broad `git add -A`. Its edits were swept into my
commit, under my message. My fault: `git add -A` in a worktree another session
is writing to cannot distinguish my changes from anyone else's, and I did not
check `git status` against what I had edited before staging.

**Why it was not split.** Splitting a commit eight commits back needs an
interactive rebase, which this environment does not support, and rewriting
history in a shared worktree while another session is active is worse than a
misleading message. The branch squash-merges, so the message never reaches
master — which is exactly why this note exists instead.

**What to review it as.** Two independent changes:

1. *Test migration* (the stated subject) — eight `--run-slow` files ported to
   the durable `State`. See the commit body.
2. *The architecture gate* — Plan now opens with a BEFORE/AFTER architecture
   pass before any approach exists, mapped with all three retrieval tools and
   the codemaps, iterating against `spec.md`, with code smells named at three
   points and a required `## Surviving smells` section in `plan.md`. Forbidden
   Patterns from the Constitution are blockers there, not compromises.
   `7993fea` is a follow-up correcting where the smell catalogue comes from.

## Process rule this produced

**`git add -A` is unsafe in a shared worktree.** Stage the paths you edited.
The concurrent session flagged its own work appearing as unexplained dirt in
`git status` twice before the sweep happened, and I read those as noise.
