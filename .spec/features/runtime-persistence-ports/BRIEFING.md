# START HERE — FUN-17: Ports, StoreProfile, recorders, and the construction move

You are picking up one ticket of a nine-ticket initiative. **You have no prior context and
that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Jira** | FUN-17 — https://raicing-ai.atlassian.net/browse/FUN-17 |
| **Branch** | `feat/runtime-persistence-ports` |
| **Wave** | 1 of 7 |
| **Blocks** | FUN-18, FUN-19, FUN-20, FUN-21, FUN-22, FUN-23 |
| **Runs in parallel with** | none — this is the wave everything else builds on |
| **Base** | `docs/runtime-persistence-research`, itself off `origin/master` @ `8c06198` |

## The one-line goal

Define the persistence ports and move engine construction to after config resolves.

## Why this ticket exists

The engine does not receive its storage — it goes and finds it, lazily, on first access (executor.py:1509-1527). That temporal coupling is what every defect downstream rests on. Moving construction to _app deletes the argument rather than winning it.

## Read these first, in this order

The research is **already on this branch** at
`contributor/architecture/research/`. It was written for someone who has never seen this
codebase. Budget an hour.

1. 05-the-design.md — the whole document; §2 is the ports, §4 is the construction move
2. ../durability-outsourcing/07-the-design.md §4 — why the transaction BUFFERS and does not stream
3. 09-decisions.md D-2, D-3, D-4, D-5, D-13, D-14

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
cd /home/ubuntu/orca/workspaces/functualize/rp-17-ports
uv sync
uv run pytest -q                   # confirm green before you change anything
cat .spec/features/runtime-persistence-ports/tasks.md
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
`.spec/STATUS.md` or `contributor/adr/` and `git rm -r .spec/features/runtime-persistence-ports`.
Make that the **last** commit and make it deletion-only. The sequence is in
`.claude/rules/spec-workflow.md` → *Version control lifecycle*.
