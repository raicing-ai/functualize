# START HERE — FUN-22: Network providers and distributed resume

You are picking up one ticket of a nine-ticket initiative. **You have no prior context and
that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Jira** | FUN-22 — https://raicing-ai.atlassian.net/browse/FUN-22 |
| **Branch** | `feat/network-sql-provider` |
| **Wave** | 7 of 7 |
| **Blocks** | none — this completes the initiative |
| **Runs in parallel with** | none |
| **Base** | `docs/runtime-persistence-research`, itself off `origin/master` @ `8c06198` |

## The one-line goal

A workflow parks on one machine and resumes on another.

## Why this ticket exists

This is the capability the whole initiative exists to enable, and it is LAST because everything before it is what makes it a 400-line plugin instead of a rewrite. FUN-25 has already measured which backends can actually do it.

## Read these first, in this order

The research is **already on this branch** at
`contributor/architecture/research/`. It was written for someone who has never seen this
codebase. Budget an hour.

1. ../durability-outsourcing/09-verdict.md — D1 first, not S3 and not R2, with reasons
2. ../durability-outsourcing/05-cloudflare.md §A — the D1 mapping, method by method
3. the FUN-25 capability matrix — the measured answers, which outrank the documented ones

If you have never seen this repository at all, start with
`contributor/architecture/research/runtime-persistence-engine-owned/01-orientation.md` —
it assumes nothing.

## Then read the repository's own rules

- `AGENTS.md` — commands, architecture, constraints
- `.claude/rules/spec-workflow.md` — the phase contract. **Writes to `src/functualize/**`
  are blocked by a `PreToolUse` hook unless `.spec/features/*/tasks.md` carries a
  parseable `## Task Dependency Graph`. This branch already has one** (see `tasks.md`
  next to this file), so you are unblocked — but if you restructure the tasks, keep the
  graph valid or you will lock yourself out.
- `.spec/CONSTITUTION.md` — the non-negotiables, including the forbidden patterns

## How to start

```bash
cd /home/ubuntu/orca/workspaces/functualize/rp-22-network-providers
uv sync
uv run pytest -q                   # confirm green before you change anything
cat .spec/features/network-sql-provider/tasks.md
```

Work the waves in order. Wave N+1 does not start while wave N has unchecked tasks.

## Three things that will bite you

1. **Reachability precedes `[x]`.** Name the production call path and verify it by
   breaking the call and watching a test fail. "A test calls it" is not a call path.
2. **Commit before sabotaging.** `git checkout -- <file>` reverts everything uncommitted
   in that file.
3. **Disclose transitional states, never disguise them.** Mark the site
   `# TRANSITIONAL(<step>): …` and describe it as current-behaviour-plus-planned-end-state.

## What "done" looks like

See `spec.md` next to this file for the acceptance criteria. They are gates, not
aspirations — run them at authoring time.

## Before you open a PR

`.spec/features/` is tracked on this branch and **absent from master**. The
`spec-artifacts-cleared` check blocks the merge until you migrate the durable half to
`.spec/STATUS.md` or `contributor/adr/` and `git rm -r .spec/features/network-sql-provider`.
Make that the **last** commit and make it deletion-only. The sequence is in
`.claude/rules/spec-workflow.md` → *Version control lifecycle*.
