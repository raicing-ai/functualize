# START HERE — FUN-23: Separate managed workspace persistence, and evaluate AgentFS

You are picking up one ticket of a nine-ticket initiative. **You have no prior context and
that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Jira** | FUN-23 — https://raicing-ai.atlassian.net/browse/FUN-23 |
| **Branch** | `feat/workspace-persistence-split` |
| **Wave** | 6 of 7 |
| **Blocks** | none |
| **Runs in parallel with** | FUN-21 |
| **Base** | `docs/runtime-persistence-research`, itself off `origin/master` @ `8c06198` |

## The one-line goal

Runtime truth and workspace bytes stop sharing a store.

## Why this ticket exists

A run record and a 400 MB artifact have different transaction sizes, retention, sharing and streaming semantics. Design 1 reached this conclusion too and it is adopted with credit.

## Read these first, in this order

The research is **already on this branch** at
`contributor/architecture/research/`. It was written for someone who has never seen this
codebase. Budget an hour.

1. 06-data-model.md §2.4 — logical separation is decided; physical co-location is not
2. 09-decisions.md §3 'Store artifact bytes in runtime rows' — rejected
3. the Confluence page 'Agent Sandbox and State — OpenShell, AgentFS, and AEnv'

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
cd /home/ubuntu/orca/workspaces/functualize/rp-23-workspace-split
uv sync
uv run pytest -q                   # confirm green before you change anything
cat .spec/features/workspace-persistence-split/tasks.md
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
`.spec/STATUS.md` or `contributor/adr/` and `git rm -r .spec/features/workspace-persistence-split`.
Make that the **last** commit and make it deletion-only. The sequence is in
`.claude/rules/spec-workflow.md` → *Version control lifecycle*.
