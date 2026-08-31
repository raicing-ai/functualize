# ADR-010: The Spec-Workflow Gate Fires on Writes, Not on Plan Approval

**Status**: accepted
**Date**: 2026-08-29
**Deciders**: Hakim

## Context

`CLAUDE.md` used to say "for non-trivial work, use the `spec-driven-developer`
subagent." That is advisory prose addressed to a model, so every session
re-litigated whether the workflow applied — and a session that reasoned its way
past it was indistinguishable from one that complied.

Three properties of the harness make the advisory layer structurally unable to
carry the requirement:

- Subagent selection cannot be forced. The docs are explicit: "there is no way
  to force Claude to always use a subagent automatically."
- The built-in `Plan` agent, which plan mode uses for research, **does not load
  `CLAUDE.md`** at all.
- This repo is driven from the VS Code extension, where `defaultMode: "plan"` in
  project settings is ignored outright.

So enforcement had to fire from the harness, on a tool call, at a fixed point in
the lifecycle.

## The obvious choice, and why it fails

The natural enforcement point is `ExitPlanMode` — the plan→execute boundary. It
is hookable, the hook receives the plan text, and `deny` is the one decision
channel whose reason reaches the model.

**It deadlocks.** Plan mode is read-only. `/agentic-specify` and `/agentic-plan`
*write* `spec.md` and `tasks.md`. A gate demanding an existing `tasks.md` at
plan-exit therefore denies the very exit that would let the model create it.
Every new feature would need an exemption on its first plan, which trains the
model to reach for the bypass reflexively — the opposite of the goal.

Probing the live harness later produced a second, independent reason. The docs
state that Claude Code injects the plan into `tool_input.plan` before passing it
to hooks. **Observed `tool_input` was `{}`**; the plan arrived only via
`tool_response`. A gate reading `tool_input.plan` as its sole input would have
found nothing and — because the gate fails open by design — would have permitted
every plan while appearing to work. Silent non-enforcement is the worst
available outcome.

## Decision

**The hard gate is a `PreToolUse` hook on `Edit` / `Write` / `NotebookEdit`,
scoped to `src/functualize/**` and `plugins/*/src/**`.** It denies the write
unless a `.spec/features/*/tasks.md` with a parseable `## Task Dependency Graph`
exists, or `.spec/EXEMPT` declares a reason.

`ExitPlanMode` keeps only a non-blocking `PostToolUse` hook that injects the
execution contract.

This encodes the requirement directly — *no shipped-code change without an
atomized task list* — rather than approximating it via the plan boundary. It has
no chicken-and-egg, fires in every permission mode and every host, and reads
disk rather than prose.

## Consequences

**Good.** Enforcement is independent of plan mode, so the VS Code caveat stops
mattering. The Specify and Plan phases operate freely because `.spec/`,
`tests/`, `docs/` and `contributor/` are ungated. Conformance is decided by
artifacts on disk, never by what a plan claims about itself.

**Cost.** The hook runs on every source edit (~45 ms, mostly interpreter
startup). `/code-review --fix` and `/simplify` trip it and need an exemption.

**The boundary is real and is documented rather than hidden.** The gate sees
three tools; a write through the **shell** — `echo >`, `sed -i`, a heredoc —
raises none of them and is not blocked. Blocking that reliably means parsing
arbitrary shell, which is fragile and easy to fool. It is *recorded* instead: a
`PostToolUse` hook on `Bash` notices that shipped code became dirty with no task
list and no exemption, and appends to the same committed ledger. The gate stops
ad-hoc editing; it does not stop a determined bypass, and does not claim to.

**Self-exemption is permitted and logged.** An agent can write `.spec/EXEMPT`
itself. The mitigation is that doing so appends to `.spec/exemptions.log`, which
is committed — so the bypass appears in the next diff. Bypassing the workflow is
allowed; bypassing it invisibly is not.

## Alternatives rejected

- **`settings.agent: "spec-driven-developer"`** — the strongest mechanism, but it
  applies the agent's *system prompt* to every session, so "what does this
  function do?" gets answered by a workflow executor. It also adds a second
  bypass route (`--agent`), and two overlapping bypasses is how enforcement
  schemes decay.
- **`UserPromptSubmit`** — fails open silently on a 30-second timeout, discarding
  its output without blocking.
- **Hooks in the subagent's frontmatter** — they exist only while that agent runs,
  so they cannot enforce anything when it was never invoked, which is the entire
  problem.
- **`EnterPlanMode`** — not a matchable tool name; absent from the hooks reference.

## Note for anyone extending the `Agent` hook

`updatedInput` replaces the **entire** input object. The documented key list
(`prompt`, `description`, `subagent_type`, `model`) is **wrong in this build**:
`model` is absent unless explicitly passed, and an undocumented
`run_in_background` is present. Build the replacement by shallow-copying what
arrived and mutating only what you mean to change. Enumerating known keys drops
a real field and injects one that was never set.
