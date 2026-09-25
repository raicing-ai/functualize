# START HERE — runtime schema: state machines, relational schema, migration contract

You are picking up one wave of the runtime-persistence initiative. **You have no prior context
and that is expected.** This file gets you to the point where you can start.

## What this branch is

| | |
|---|---|
| **Branch** | `feat/runtime-schema-migrations` |
| **Wave** | 2 of 7 |
| **Blocks** | `sqlite-runtime-provider`, and through it the atomic-workflow, gate-outbox, network-provider and workspace-split waves |
| **Runs in parallel with** | none |
| **Base** | `origin/master` @ `03fbb64` (`feat(persistence): runtime persistence ports (#49)`); rebased 2026-09-25 from the research branch's `8c06198` |

The tracker key and link live on the tracking issue, never in this repository's text: the
`message-hygiene` check refuses them in PR titles, bodies and commit messages.

## The one-line goal

Make the four state machines executable — an illegal move raises `IllegalTransition` where it
would be written — and specify the tables and the forward-only migration contract.

## Read these first, in this order

1. `spec.md` → *Re-based premises* and *Open decisions*. Ten premises of the original scaffold
   were re-measured at `03fbb64`; five changed the plan.
2. `contributor/reference/runtime-persistence-data-model.md` (on master) — §1 state machines,
   §2 schema, §6 retention, §7 migration discipline. `schema.md` here is that, corrected (**Δ**).
3. `contributor/adr/025-engine-owns-transition-meaning.md` and
   `026-persistence-ports-need-no-new-layer.md` → *What would reopen this* — why nothing is added
   to `_types/persistence.py`.
4. `plan.md` — BEFORE/AFTER and the surviving smells.

The research studies under `contributor/architecture/research/` are still on this branch as
background; they never reach master and are deleted by task 7.1.

## Then read the repository's own rules

- `AGENTS.md` — commands, architecture, constraints
- `.claude/rules/spec-workflow.md` — the phase contract. Writes to `src/functualize/**` are
  gated on `.spec/features/*/tasks.md` carrying a parseable `## Task Dependency Graph`. This
  branch has one; a Multica run does not load the hook, so obey it by hand.
- `.spec/CONSTITUTION.md` — the non-negotiables, including the forbidden patterns

## How to start

```bash
cd /home/ubuntu/orca/workspaces/functualize/rp-18-schema
uv sync --frozen --all-extras --all-packages
uv run lint-imports                  # 7 kept, 0 broken at 03fbb64
cat .spec/features/runtime-schema-migrations/tasks.md
```

Work the waves in order. Wave N+1 does not start while wave N has unchecked tasks. A task
marked **held** waits for its decision in `spec.md`.

## Three things that will bite you

1. **Reachability precedes `[x]`.** Name the production call path and verify it by breaking the
   call and watching a test fail. "A test calls it" is not a call path.
2. **Commit before sabotaging.** `git checkout -- <file>` reverts everything uncommitted in that
   file.
3. **Disclose transitional states, never disguise them.** Mark the site
   `# TRANSITIONAL(<step>): …` and describe it as current-behaviour-plus-planned-end-state.

## Before you open a PR

- `.spec/features/` and `contributor/architecture/research/` are tracked on this branch and
  **absent from master**. Migrate the durable half (task 6.1), push and wait for validation, then
  make the deletion-only clearing commit (task 7.1) the **last** commit.
- Read back `git log --format='%B' origin/master..HEAD`, the PR title and the PR body for tracker
  keys, internal ids and agent trailers before every push.
