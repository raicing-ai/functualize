# .spec/ — Design Documents

Architectural reference documents and shape intents for the Functualize project.

The files committed here are the canonical design reference. The [spec-driven-developer](../.claude/agents/spec-driven-developer.md) workflow tracks feature specs and task lists on the working branch for review, archives them, and clears them before merge. Session state is gitignored.

## Committed Reference

- **`ARCHITECTURE.md`** — Implementation-level architecture: runtime storage and its discard rules, the event log, capability duality, the AdapterPlugin protocol, presets as factory functions, monorepo plugin packaging.
- **`CONSTITUTION.md`** — Non-negotiable rules: layer dependencies, forbidden patterns, naming conventions, quality gates, pre-release stance, transitional change policy.
- **`TESTING.md`** — Test strategy: tiers (unit, property-based, CLI integration, TUI Pilot, E2E), fixtures (`cli_run`, `xdg_dirs`, `project_tree`), TUI testing approaches.
- **`STATUS.md`** — Current project status: active work, open features, shape intents, potential follow-ups, recently completed features, and contribution entry points.

## Shape Intents

`shape-intents/` describes design documents that are "specified, not yet implemented" —
behavior changes written up at the assertion level, with per-assertion PASS/GAP verification
against the current codebase. **The directory itself is kept empty in this repository.**
Once such a document is written, it is published to Confluence (raicing-ai's *Software
Development* space → *Functualize & FuncCloud — Product Design Workspace* → *10 — Shape
Intents*) rather than committed here, so an open design question doesn't sit as a stale,
unlinked file on the branch that specified it. This repo's own contributor docs (this README
included) reference `.spec/` and `contributor/` paths, never Confluence URLs, because a
Confluence link is not reachable by anyone without access to that instance; ask a maintainer
for the Confluence link if you need to read a shape intent.

When a shape intent graduates to implementation, it is atomized into a task list under
`.spec/features/<name>/` and executed via the spec-driven-developer workflow. Before the
branch merges, both are cleared: the durable half moves to `STATUS.md` and an ADR. Standalone
Distribution & Self-Management shipped that way on 2026-09-04 — see
[ADR-015](../contributor/adr/015-standalone-distribution-and-self-management.md).

## Workflow

New features follow the spec-driven-development phases described in `.claude/agents/spec-driven-developer.md`:

| Phase | Trigger | Output |
|-------|---------|--------|
| 0: Init | First session | Creates `.spec/PROJECT.md`, `.spec/REQUIREMENTS.md`, `.spec/STATE.md`, `.spec/ROADMAP.md` |
| 1: Discuss | Scope unclear | Refined requirements |
| 2: Specify | Feature request | `.spec/features/<name>/spec.md` |
| 3: Plan | Spec confirmed | `.spec/features/<name>/plan.md` + `tasks.md` |
| 4: Execute | Tasks ready | Implementation + `[x]` checkmarks |
| 5: Verify | All `[x]` | Gate passes, ROADMAP.md updated |

Session-local files (`STATE.md`, `proposals/`, `scrutiny-reports/`) are gitignored. `features/` is tracked on the working branch so its acceptance gates can be reviewed, then cleared in a deletion-only final commit after validation and archive. That final push skips redundant validation only when the previous PR run's validation jobs were green; `spec-artifacts-cleared` still runs. Master keeps only permanent design decisions; shape intents live in Confluence, not on any branch.

## Session documents vs. the committed record

**Proposals and scrutiny/review reports are session documents. They live under `.spec/` and are never committed.**

| Kind | Where | Committed? |
|---|---|---|
| A proposal / plan for a change | `.spec/proposals/` | **No** — gitignored |
| A scrutiny, audit, or review report | `.spec/scrutiny-reports/` | **No** — gitignored |
| The decision a proposal argued for | `contributor/adr/NNN-*.md` | **Yes** |
| A behaviour rule the review produced | `contributor/guides/*.md` | **Yes** |
| A design "specified, not yet implemented" | Confluence (`10 — Shape Intents`) | **No** — repo-committed only via `.spec/features/` once it graduates |

The reason is that a proposal is an *argument at a moment* — it cites line numbers, it is superseded by its own implementation, and it goes stale the day it lands. An ADR is a *decision*, and stays true. Committing the argument means the repository accumulates documents that contradict the code and each other, and a reader cannot tell which one is current.

**When a proposal or report lands, migrate what survives before deleting it:**

1. The decision, and the reasoning a future reader needs to not re-litigate it → the relevant **ADR** (add an Addendum section if the ADR is already accepted).
2. Any rule about *how to work* that came out of it → the relevant **`contributor/guides/`** document.
3. Anything still open → **`STATUS.md`**, self-contained, with no reference to the gitignored file.

Nothing in a committed file may link to `.spec/proposals/` or `.spec/scrutiny-reports/` — those paths do not exist for anyone who clones the repository. `contributor/` had a `proposals/` and a `reports/` directory until 2026-08-28 for this reason; both are gone.

*Precedent: the secrets/config work (ADR-007, ADR-008) shipped its proposal and two review reports into `contributor/`. The durable half is now ADR-008's Addendum and `wiring-discipline.md` §8–§10; the arguments went back to `.spec/`.*

`STATUS.md` is the public-facing complement: it lists active work, open features, follow-ups, recently completed milestones, and contribution entry points — all self-contained without references to gitignored files.
