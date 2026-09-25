# START HERE — FUN-4: Gate resolution requests, candidates and evaluations

You have no prior context, and that is expected. This file gets you to the point where
you can start.

## What this branch is

| | |
|---|---|
| **Branch** | `feat/gate-resolution-model` |
| **Worktree** | `/home/ubuntu/orca/workspaces/functualize/rp-04-gate-resolution` |
| **Base** | `origin/master` @ `03fbb64` (FUN-17's runtime-persistence ports, merged) |
| **Phase** | Specify + Plan drafted. **Execute is blocked on member answers** to `spec.md` §8 |
| **Blocks** | FUN-6 (the Jev experiment) and the interactive Slack gate resolver |
| **Neighbours** | FUN-18 `feat/runtime-schema-migrations` (schema, migrations, `InputRequest` transition table; in flight) · FUN-21 `feat/gate-interactions-outbox` (durable interaction/evidence slice and outbox; not started) |

## The one-line goal

A gate's question gets its own identity, every proposed answer is kept with the
judgement made on it, and nothing is recomputed on read.

## What closes here, and what cannot

- **AC-1 (request identity): closes here.**
- **AC-2 (candidates enumerated and evaluated, evaluation recorded): closes here on
  behaviour.** The records live inside `scopes.json` behind `TRANSITIONAL(FUN-21)`.
- **AC-3 (evidence durable and readable independently of the scopes document): does
  not close on this ticket.** It needs FUN-18, FUN-19 and FUN-21, including moving the
  answer surfaces onto the selected `RuntimeStore`.

The Jira issue stays open after this branch merges (`spec.md` §5, §8 D-1).

## Read in this order

1. `spec.md` §1 (what is wrong today, with the commands that prove it), §4.2 (rules
   R1–R10) and §8 (decisions awaiting the member).
2. `plan.md` — the BEFORE/AFTER diagrams and `## Surviving smells`. Two of those smells
   need maintainer review.
3. `contracts.md` — the port amendment (§2) and what FUN-18 and FUN-21 inherit (§7).
4. `tasks.md` — the only feature file the Execute phase reads. Every task restates what
   it needs.

If the codebase is new to you: the research at `docs/runtime-persistence-research` @
`92d6f05` (`contributor/architecture/research/runtime-persistence-engine-owned/01-orientation.md`)
assumes nothing. It is **not** on this branch and must never be added: the
`research-artifacts-cleared` rule.

## Then the repository's own rules

- `AGENTS.md`, `.claude/rules/spec-workflow.md` and `.spec/CONSTITUTION.md`.
- Writes to `src/functualize/**` need a parseable `## Task Dependency Graph` in some
  `.spec/features/*/tasks.md`. **This branch has one.** Keep it valid if you restructure
  tasks. The hook is a Claude Code project setting, so a Multica run does not load it.
  Obey it anyway.

## How to start

```bash
cd /home/ubuntu/orca/workspaces/functualize/rp-04-gate-resolution
uv sync --frozen --all-extras --all-packages
uv run pytest -x -q --no-header > /tmp/functualize-test.log 2>&1   # the baseline
```

`tests/spec/test_task_gates_still_hold.py` is **expected red** until T6 is ticked, as
`tasks.md` explains. Every other test should be green at the baseline.

## Three things that will bite you

1. **Reachability precedes `[x]`.** Name the production call path, break it, and watch a
   test fail.
2. **Commit before sabotaging.** `git checkout -- <file>` reverts everything uncommitted.
3. **Two classes are already over the limit:** `WorkflowWalker` (803 lines) and
   `ScopeStore` (930). The constitution forbids *growth*. T7 shrinks the walker, and
   nothing may add a method to `ScopeStore`.

## Before you open a PR

`.spec/features/` is tracked here and absent from `master`. Tasks T12 and T13 carry the
sequence:
1. migrate to `.spec/STATUS.md` and ADR-029;
2. push 1 and wait for validation;
3. push 2, whose last commit is the deletion-only `git rm -r .spec/features/gate-resolution-model`.

No Jira or Multica key, no agent identity and no agent `Co-authored-by:` may appear in
any commit, PR title or PR body.
