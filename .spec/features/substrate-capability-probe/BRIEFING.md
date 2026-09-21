# START HERE — FUN-25: Measure StoreProfile empirically across six backends

You are picking up one ticket of a nine-ticket initiative. **You have no prior context and
that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Jira** | FUN-25 — https://raicing-ai.atlassian.net/browse/FUN-25 |
| **Branch** | `spike/substrate-capability-probe` |
| **Wave** | 0 of 7 |
| **Blocks** | informs FUN-17 (profile fields), FUN-18 (schema limits), FUN-19 and FUN-22 (which backends are worth building) |
| **Runs in parallel with** | FUN-24 |
| **Base** | `docs/runtime-persistence-research`, itself off `origin/master` @ `8c06198` |

## The one-line goal

Turn StoreProfile from a hypothesis into measurements.

## Why this ticket exists

StoreProfile's ten fields were asserted from vendor documentation. ADR-022's failure mode is building a two-backend abstraction against one backend; the antidote is knowing what real backends do BEFORE the port is frozen. The payoff is already proven: Stored.revision: int is a latent defect only a remote backend exposes, found by reading S3's docs.

## Read these first, in this order

The research is **already on this branch** at
`contributor/architecture/research/`. It was written for someone who has never seen this
codebase. Budget an hour.

1. ../durability-outsourcing/07-the-design.md §3 — the ten fields and what each means
2. ../durability-outsourcing/05-cloudflare.md, 06-s3.md — the documented answers this ticket must verify
3. ../durability-outsourcing/09-verdict.md §4 — the three open questions

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
cd /home/ubuntu/orca/workspaces/functualize/rp-25-capability-probe
uv sync
uv run pytest -q                   # confirm green before you change anything
cat .spec/features/substrate-capability-probe/tasks.md
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
`.spec/STATUS.md` or `contributor/adr/` and `git rm -r .spec/features/substrate-capability-probe`.
Make that the **last** commit and make it deletion-only. The sequence is in
`.claude/rules/spec-workflow.md` → *Version control lifecycle*.
