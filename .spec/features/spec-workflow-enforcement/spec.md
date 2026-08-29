# Spec: Unconditional Spec-Driven Workflow Enforcement

**Feature:** `spec-workflow-enforcement`
**Source:** [`.spec/shape-intents/spec-workflow-enforcement.md`](../../shape-intents/spec-workflow-enforcement.md) — 57 assertions, all decisions resolved 2026-08-29
**Status:** specified

> Per `X.3` (one source of truth) this spec does **not** restate the shape
> intent's assertions. The intent is the normative assertion set; this document
> states the *behavior* those assertions add up to, and the acceptance criteria
> that decide whether it was achieved. Where an acceptance names an assertion
> ID, the intent is authoritative on the detail.

---

## Problem

`CLAUDE.md` tells a model that "for non-trivial work, use the
`spec-driven-developer` subagent." That is advisory prose addressed to a model,
so every session re-litigates whether the spec workflow applies — and a session
that never reads it, or reasons its way past it, is indistinguishable from one
that complied.

Three things make the advisory layer structurally unable to carry the
requirement:

- Subagent selection cannot be forced (`F.1`).
- The built-in `Plan` agent, which plan mode uses for research, does not load
  `CLAUDE.md` at all (`F.2`).
- The repo is driven from the VS Code extension, where `defaultMode: "plan"` in
  project settings is ignored outright (`F.11`).

Separately, the workflow it points at is **not executable as written**. The
Execute context anchor names `.spec/PROJECT.md`, which does not exist and is
gitignored; Phase 0 branches on a gitignored marker so "run Init" misfires in
every worktree; Phase 5 writes to a `ROADMAP.md` that was never created; and
the agent's own `tools:` list omits `Edit`, `Skill`, and `Agent`, so three of
its own instructions cannot run.

## Goal

**Any coding agent that modifies shipped code in this repository has an
atomized task list on disk, or has declared and logged an exemption — without
the user asking for either.**

The guarantee is mechanical: it fires from the harness on a tool call, at a
fixed point in the lifecycle, and it reads artifacts on disk rather than the
model's claims about them.

## Non-goals

- Changing anything the package ships. No file under `src/functualize/`,
  `plugins/*/src/`, `tests/`, or any `pyproject.toml` is modified (`X.5`).
- Preventing a determined operator from bypassing the workflow. The exemption
  path is deliberate; the requirement is that using it leaves a record.
- Closing the four SpecKit gaps (`SK.1`–`SK.4`). Audited, explicitly deferred.
- Making plan mode load-bearing. The enforcement works identically whether a
  session ever enters plan mode or not.

---

## User stories

**As the maintainer**, when an agent starts editing `src/functualize/` without
a task list, it is stopped and told which command produces one — so I never
discover mid-review that a change was made ad hoc.

**As the maintainer**, when an agent decides a change is too small to spec, I
find out. The bypass appears in my next diff rather than in nobody's.

**As an agent working in any of the five worktrees**, the workflow I am told to
follow references files that actually exist in the tree I am standing in, so
Phase 0 does not tell me to initialize an initialized project and Phase 4 does
not tell me to read a file that was never committed.

**As a reviewer on a pull request**, the feature's spec, plan, contracts, and
task ledger are in the branch — I can see the wave graph and the acceptance
gates that the diff claims to satisfy.

**As someone reading master a year later**, `.spec/features/` is empty and
`STATUS.md` carries what survived, so no document in the tree contradicts the
code. The full reasoning is still recoverable from the pull request.

**As a contributor cloning fresh**, the harness behaves the same for me as for
the maintainer: the skills resolve, the hooks are registered under Project
Settings, and the validator runs without the project venv.

---

## Behavior

### B1 — The write gate

An attempt to create or modify a file under `src/functualize/**` or
`plugins/*/src/**` is denied unless one of two conditions holds on disk:

- some `.spec/features/*/tasks.md` exists and contains a
  `## Task Dependency Graph` section with a parseable wave block; or
- `.spec/EXEMPT` exists, is fresh, and declares a reason of at least 20
  characters.

Writes anywhere else — `tests/`, `plugins/*/tests/`, `plugins/conftest.py`,
every `pyproject.toml`, `docs/`, `contributor/`, `.spec/`, `.claude/` — are not
examined.

**Boundary, stated honestly.** This covers the `Edit`, `Write`, and
`NotebookEdit` tools. A write issued through the **shell** — `echo >`, `sed -i`,
`tee`, a heredoc, a script — raises none of those events and is not blocked.
The gate therefore stops *ad-hoc editing*, not a determined bypass, which is
already `spec.md`'s stated non-goal. `B10` covers what happens instead.

The denial message is addressed to the model and names both the artifact that
is missing and the command that produces it, because `deny` is the only
decision channel Claude reads.

### B2 — The exemption is recorded, not merely permitted

Passing via `.spec/EXEMPT` appends a record to `.spec/exemptions.log`, which is
tracked in git and is not cleared when the feature's artifacts are. Bypassing
the workflow is allowed; bypassing it invisibly is not.

### B3 — The gate degrades to today's behavior when broken

Any internal failure — malformed input, missing interpreter, unreadable
`.spec/` — results in the write proceeding. A validator that cannot decide does
not block. The repository is never bricked by its own harness.

### B4 — The gate follows the agent, not the session origin

With five live worktrees, the gate validates the tree the agent is actually
working in, resolved from the hook input rather than from a placeholder pinned
to where the session started.

### B5 — Approving a plan delivers the execution contract

At the moment a plan is approved, the Phase 4 discipline — wave ordering is
binding, acceptance gates run against real code, reachability precedes marking
`[x]`, `STATE.md` is updated per task — arrives as context without the user
asking. This layer never blocks.

### B6 — Delegated planning is not a blind spot

A delegation to the built-in `Plan` agent carries the workflow contract in its
prompt, since that agent loads none of the repository's instruction files.
`Explore`, `spec-driven-developer`, and the default agent are untouched.

### B7 — The workflow the agent is told to follow is executable

Every file the Execute anchor names exists and is committed. Phase 0's
initialization check keys on a committed file. Phase 5 updates a document that
exists. The agent holds the tools its own instructions require.

### B8 — Feature artifacts live on the branch and never reach master

`.spec/features/` is tracked, so a feature's spec, contracts, plan, schema,
research, and task ledger travel with the branch and are visible in review. A
required check prevents merging while any of it remains, so master carries
none. What survives is migrated to `STATUS.md` or an ADR before the clearing
commit; the rest stays recoverable through the pull request's retained refs.

### B10 — A shell bypass is recorded rather than blocked

A shell command that modifies shipped code while no task list and no exemption
exist does not fail. It is noticed: the same ledger that records declared
exemptions gains a record naming the changed path and marking it as a shell
write.

Blocking the shell would mean recognising redirection, `sed -i`, `tee`, `cp`,
heredocs, and every script that wraps them — an enumeration that is fragile,
easy to fool, and prone to false positives on read-only commands. Recording is
achievable and is the same trade already accepted for `.spec/EXEMPT`: the
bypass stays possible, and stops being invisible.

### B9 — The contract exists in exactly one place

The routing contract lives in one rule file loaded at launch. `CLAUDE.md`, the
phase commands, and the hook payloads reference it; none restate it.

---

## Acceptance criteria

Behavioral, ordered by the wave that satisfies them. Each is decided by
observation, not by inspection of the implementation.

| ID | Criterion |
|---|---|
| `A1` | From a fresh worktree with no `.spec/features/` present, an attempt to edit a file under `src/functualize/` is denied, and the denial text names `/agentic-specify` and the `.spec/EXEMPT` path |
| `A2` | In the same state, edits to `tests/`, `plugins/*/tests/`, `plugins/conftest.py`, a `pyproject.toml`, and `docs/` all proceed without a prompt |
| `A3` | With a `tasks.md` containing a valid `## Task Dependency Graph` present, the same `src/functualize/` edit proceeds without a prompt |
| `A4` | Writing `.spec/EXEMPT` with a ≥20-character reason permits the edit, and a record naming that reason appears in `.spec/exemptions.log` |
| `A5` | An `.spec/EXEMPT` older than the freshness window does not permit the edit |
| `A6` | With the validator deliberately broken (malformed output, non-zero non-2 exit), editing `src/functualize/` still proceeds |
| `A7` | `A1`, `A3`, `A4`, and `A6` produce identical results when repeated from a second worktree |
| `A8` | Approving a plan results in the execution contract appearing in context, phrased as statements about the repository rather than as instructions, and never blocks the approval |
| `A9` | A delegation with `subagent_type: "Plan"` reaches the subagent with the contract prepended; delegations to `Explore`, `spec-driven-developer`, and the default agent are unmodified |
| `A10` | Every file named in the Execute context anchor exists and is tracked by git, and the anchor list is byte-identical between the agent definition and `agentic-execute.md` |
| `A11` | In a fresh worktree, Phase 0 does not report the project as uninitialized, and Phases 2–3 do not stall on a missing `STATE.md` |
| `A12` | `spec-driven-developer` can invoke a skill, make a targeted edit, and dispatch a subagent — the three operations its own instructions require and its `tools:` list currently forbids |
| `A13` | `.spec/features/` is tracked: a newly created feature directory appears in `git status` |
| `A14` | A pull request retaining any `.spec/features/` content fails the required check; the same branch passes once the clearing commit is pushed |
| `A15` | `git ls-files .spec/features/` on master returns empty |
| `A16` | `.spec/plans/` and `.spec/STATE.md` remain untracked |
| `A17` | `/hooks` lists all three hooks under Project Settings with their matchers |
| `A18` | The validator runs correctly when invoked outside the project virtualenv, with no third-party imports and no `functualize` import |
| `A19` | The routing contract appears in exactly one file; `CLAUDE.md` §"Spec-driven workflow" contains a pointer and no contract text |
| `A20` | `uv run pytest`, `uv run ruff check`, `uv run mypy`, and `uv run lint-imports` produce the same results before and after the change |
| `A21` | A shell write to `src/functualize/` with no task list and no exemption present appends a record to `.spec/exemptions.log` marked as a shell write, and does **not** block the command |
| `A22` | The same shell write, when a valid `tasks.md` or a fresh `.spec/EXEMPT` exists, appends nothing — the workflow was followed, so there is nothing to record |

---

## Open verification, not open decision

`MODE.6` is the one behavior that cannot be settled from the documentation:
`plansDirectory` resolves against project root (`F.18`), and project root does
not follow into a worktree (`F.13`). If a plan written from a worktree lands in
the master checkout, `MODE.3` is reverted to the default and that single
assertion is dropped. This is a measurement, not a decision to re-open.
