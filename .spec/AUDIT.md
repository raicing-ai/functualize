# Auditing a wave

Every `tasks.md` in `.spec/features/` carries a **`## Wave Audit`** section. This page says
what that section is for and how to use it. It is written for an agent that has *not* seen
the work being audited and must not be told what to conclude.

## Why this exists

Execution here is done by several agents in parallel, each holding one task's file scope, and
by an orchestrator that commits. Three failure modes recur, and none of them is caught by a
green suite:

1. **A gate that cannot fail.** Three gates in this branch matched their own explanatory
   prose, or matched docstrings and unrelated substrings. One had an `after: 0` that was
   unreachable because reaching it meant deleting the docstring stating the rule the task
   enforced. A gate is not a test until someone has watched it be red.
2. **A test that pins the defect.** `tests/integration/test_cli_workflow_parity.py` asserted
   `code == 0` for a resume that left a gate waiting — contradicting the docstring of the very
   function it tested. The suite was green the whole time.
3. **A task done by widening its own scope.** The wave graph guarantees *source*
   disjointness. It says nothing about the tests pinned to those sources, so a task can go
   green by editing files no task owns.

## What the auditor does

Work through the wave's `## Wave Audit` section. It names, per wave:

- **The claim** — what the wave asserts is now true, in one sentence.
- **Falsify it** — the command that would show the claim is false, and the output that would
  mean it *is* false. Run it. Do not run the task's own gate and stop there: the gate was
  written by the same person as the code.
- **The sabotage** — the specific edit that must turn a named test red. Apply it, run the
  test, restore. **Commit first**: `git checkout -- <file>` reverts everything uncommitted in
  that file, and doing this out of order has already destroyed finished work once in this
  branch.
- **Scope** — the files the wave was allowed to touch. Compare against
  `git show --stat <commit>`. Anything outside the list must be named in the commit message
  with a reason. Silent widening is a finding.
- **The answers that changed** — a wave that claims to be behaviour-free must have changed
  none; a wave that changes one must say which, and a test must assert the *new* answer with
  the reason beside it.

## Rules for the auditor

- **Report a count, never content.** Scope records hold gate payloads.
- Every finding cites `file:line` and the command that reproduces it. A finding without a
  reproduction command is not a finding.
- Rank: **Blocking** (the wave is wrong, or its gate cannot fail) / **Serious** (a reader
  would mis-execute) / **Minor** / **Nit**.
- Say plainly when a check turns up nothing. A short honest report beats a padded one.
- You are auditing, not fixing. Do not edit source. Do not mark tasks done.
- Judge the work against `spec.md`'s acceptance criteria and `contracts.md`, not against what
  the code happens to do. Where they disagree, that disagreement is the finding.
