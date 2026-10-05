# START HERE — FUN-19: The SQLite runtime provider, legacy migration, and the tiered conformance suite

You are picking up one ticket of a nine-ticket initiative. **You have no prior context and
that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Jira** | FUN-19 — https://raicing-ai.atlassian.net/browse/FUN-19 |
| **Branch** | `feat/sqlite-runtime-provider` |
| **Wave** | 3 of 7 |
| **Blocks** | FUN-20, FUN-21, FUN-22, FUN-23 |
| **Runs in parallel with** | none |
| **Base** | rebased 2026-10-05 onto `origin/master` @ `e8e3b867` (was `8c06198`) |
| **Shape** | SD/12583004, `Authority: Approved` — `plan.md` → `## Alignment` |
| **Phase** | Plan complete; decisions D-1 a, D-2 a, D-3 refuse answered 2026-10-05; Execute: wave 0 (tasks 1–4) complete at `46704c8a`; wave 1 next (8 waves, each reachability-closed) |

## The one-line goal

The first real RuntimeStore, and the tiered suite every later backend must pass.

## Why this ticket exists

SQLite is the reference implementation: it is the only backend that is both transactional and offline-capable, which makes it the one that can be the default. The conformance suite written here is what makes FUN-22 cheap.

## Read these first, in this order

The research is **already on this branch** at
`contributor/architecture/research/`. It was written for someone who has never seen this
codebase. Budget an hour.

1. `runtime-persistence-engine-owned/06-data-model.md` §4 — the transaction catalogue
2. `runtime-persistence-engine-owned/08-delivery-and-tests.md` — the tiered capability suites
3. plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py — 225 lines; it stays and keeps serving `fresh` and `shell-history`
4. `contributor/reference/runtime-persistence-data-model.md` — the frozen schema, fencing and migration contract this ticket implements

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
cd /home/ubuntu/orca/workspaces/functualize/rp-19-sqlite-provider
uv sync
uv run pytest -q                   # confirm green before you change anything
cat .spec/features/sqlite-runtime-provider/tasks.md
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
`.spec/STATUS.md` or `contributor/adr/` and `git rm -r .spec/features/sqlite-runtime-provider`.
Make that the **last** commit and make it deletion-only. The sequence is in
`.claude/rules/spec-workflow.md` → *Version control lifecycle*.
