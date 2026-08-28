# Shape Intent: Unconditional Spec-Driven Workflow Enforcement

**Status: specified, not yet implemented**
**Date: 2026-08-29**
**Scope: `.claude/` harness configuration only. No changes to `src/functualize/`, `tests/`, or the package's public surface.**
**Doc basis: Claude Code docs fetched 2026-08-29 from `code.claude.com/docs/en/{hooks,settings-reference,permission-modes,sub-agents,memory}.md`**

## Problem

`CLAUDE.md` currently says:

> For non-trivial work, use the `spec-driven-developer` subagent.

That is advisory prose addressed to a model, so every session re-litigates
whether the spec workflow applies. The requirement is that it never be
re-litigated: **any coding agent that plans or executes in this repository must
be routed through the spec-driven workflow without the user asking for it.**

This intent establishes the layers that make that structural rather than
persuasive, and records the findings that determine which layers can actually
carry the weight.

---

## Open decision D1 — gate strictness (ANSWER BEFORE IMPLEMENTING `GATE.*`)

The user has not yet chosen. The rest of this document assumes **option (b)**;
`GATE.4` is the only assertion that changes if a different option is picked.

| Option | Behavior | Cost |
|---|---|---|
| (a) hard deny | Every non-conforming plan is denied. Absolute. | Blocks one-line typo fixes. Directly contradicts `coding__agentic-coding`'s own rule "Simple 1–2 file change → skip entirely" |
| **(b) deny with declared escape hatch** *(assumed)* | Deny unless the plan carries an explicit `Spec-exempt: <reason>` line. The exemption is written into the plan, so it is visible and reviewable | Model can self-exempt; mitigated because the exemption is recorded in the plan file on disk |
| (c) `permissionDecision: "ask"` | User confirms each bypass interactively | Reintroduces a prompt on every plan; fails in `-p` / non-interactive runs |

---

## Part I — Findings: what the Claude Code docs establish

Each finding is load-bearing for at least one assertion below. Cited so the
implementing agent does not have to re-derive them.

| ID | Finding | Source |
|---|---|---|
| `F.1` | **Subagent selection is advisory and cannot be forced.** "Claude uses each subagent's description to decide when to delegate… There is no way to force Claude to always use a subagent automatically." Escalations are: naming it in the prompt, `@"name"` mention, or session-wide `--agent` / `settings.agent` | sub-agents |
| `F.2` | **The built-in `Plan` and `Explore` agents do not load `CLAUDE.md`.** "A non-fork subagent's initial context contains… CLAUDE.md files: every level of the CLAUDE.md hierarchy… **The built-in Explore and Plan agents skip this.**" Plan mode uses the built-in `Plan` agent for research | sub-agents |
| `F.3` | **`ExitPlanMode` is a hookable tool.** `PreToolUse` "matches on any tool name except `EndConversation`: built-in tools such as `Bash`, … `AskUserQuestion`, and `ExitPlanMode`". `EnterPlanMode` is **not** in the matchable list and appears nowhere in the hooks reference — do not build on it | hooks §PreToolUse |
| `F.4` | **The hook receives the plan text.** "Claude writes the plan to a file on disk before calling the tool, so the literal `tool_input` from the model is typically empty. Claude Code injects the plan content and file path before passing the input to hooks." Fields: `tool_input.plan` (markdown), `tool_input.planFilePath`. `allowedPrompts` is deprecated and ignored | hooks §ExitPlanMode |
| `F.5` | **`deny` is the only decision channel that talks back to the model.** `permissionDecisionReason`: "For `allow` and `ask`, shown to the user but not Claude. For **`deny`, shown to Claude**." Multi-hook precedence is `deny` > `defer` > `ask` > `allow`. Exit code 2 routes identically to `deny`, with stderr as the reason | hooks §PreToolUse decision control |
| `F.6` | **`allow` alone does not work on `ExitPlanMode`.** "`AskUserQuestion` and `ExitPlanMode`… need `updatedInput` paired with it." A conforming plan must therefore be passed by exiting 0 with no JSON, never by returning `allow` | hooks §PreToolUse decision control |
| `F.7` | **`PostToolUse` on `ExitPlanMode` carries the approved plan.** "`tool_response` is an object with `plan` and `filePath` fields holding the approved plan, plus internal status flags. Read `tool_response.plan` for the plan content rather than re-reading the file from disk." The event honors `additionalContext`, delivered "next to the tool result", and top-level `decision: "block"` + `reason` | hooks §ExitPlanMode, §Decision control |
| `F.8` | **Agent delegation is interceptable and rewritable.** `PreToolUse` on `Agent` receives `tool_input` = `{prompt, description, subagent_type, model}`. `updatedInput` "replaces the entire input object, so include unchanged fields alongside modified ones" | hooks §Agent, §PreToolUse decision control |
| `F.9` | **`settings.agent` runs the main thread as a named subagent.** "Run the main thread as a named subagent, so Claude Code applies that subagent's system prompt, tool restrictions, and model to your session." Scope: any settings file. `--agent` overrides it per session | settings-reference §agent |
| `F.10` | **`.claude/rules/*.md` is a first-class instruction surface.** "Rules without `paths` frontmatter are loaded at launch with the same priority as `.claude/CLAUDE.md`." Path-scoped rules load lazily when Claude touches matching files. Project rules are skipped if `project` is excluded from `--setting-sources` | memory §Organize rules |
| `F.11` | **`defaultMode: "plan"` does not apply in VS Code.** "Conversations the VS Code extension starts don't read project settings for the starting permission mode. There, set `claudeCode.initialPermissionMode` to `plan` in your VS Code user settings instead." This repo is driven from the VS Code extension | permission-modes §Set plan mode as the default |
| `F.12` | **`additionalContext` must be phrased as fact, not command.** "Write the text as factual statements rather than imperative system instructions… Text framed as out-of-band system commands can trigger Claude's prompt-injection defenses, which causes Claude to surface the text to you instead of treating it as context." Values over 10,000 chars are spilled to a file and replaced with a path plus preview | hooks §Add context for Claude |
| `F.13` | **`${CLAUDE_PROJECT_DIR}` does not follow into a worktree.** "`${CLAUDE_PROJECT_DIR}` stays put: it still points at the project root where the session started… `cwd` follows Claude: the `cwd` field in the hook's input JSON is the worktree root after Claude enters a worktree." This repository is worked on from **five** live worktrees | hooks §Reference scripts by path |
| `F.14` | **Hooks can live in skill and subagent frontmatter.** Skill hooks stay registered for the rest of the session (unless `once: true`); subagent hooks are removed when the agent finishes, and a `Stop` hook there is converted to `SubagentStop`. Project subagent frontmatter hooks require the workspace-trust dialog; a `-p` session does not count as accepting it | hooks §Hooks in skills and agents |
| `F.15` | **`InstructionsLoaded` cannot enforce anything.** It fires when `CLAUDE.md` or `.claude/rules/*.md` load, "runs asynchronously for observability purposes", and has no decision control — output fields are discarded. Usable for audit only | hooks §InstructionsLoaded |
| `F.16` | **`UserPromptSubmit` is cheap but has a short leash.** Can inject `additionalContext` and can `decision: "block"`. Default timeout is **30s**, not the 600s of most events, and "a hook that reaches its timeout is canceled and its output, including any `additionalContext`, is discarded" — it fails open and silently | hooks §UserPromptSubmit |
| `F.17` | **`SessionStart` can seed context and rename the session.** Fields: `additionalContext`, `initialUserMessage` (headless `-p` only), `sessionTitle`, `watchPaths`, `reloadSkills`. Re-runs on `--resume` with `source: "resume"`; mid-session events are replayed from transcript instead of re-run | hooks §SessionStart decision control |
| `F.18` | **`plansDirectory` relocates plan-mode files.** Resolved relative to project root; "keeps the default when the path resolves outside it". Default is `~/.claude/plans` | settings-reference §plansDirectory |

---

## Part II — Findings: drift in the current repository

Discovered while auditing. Every one of these breaks an enforcement layer if
left alone, because a validating hook has to check plans against artifacts that
actually exist.

| ID | Finding | Evidence |
|---|---|---|
| `D.1` | **The Execute context anchor names files that do not exist.** `spec-driven-developer.md` anchors on `.spec/PROJECT.md`; the directory contains no `PROJECT.md`, `REQUIREMENTS.md`, or `ROADMAP.md` | `.spec/` holds only `ARCHITECTURE.md`, `CONSTITUTION.md`, `README.md`, `STATE.md`, `STATUS.md`, `TESTING.md`, `features/`, `shape-intents/` |
| `D.2` | **Those anchors are gitignored, so a fresh worktree can never have them.** `.gitignore:13-21` ignores `.spec/features/`, `.spec/.agentic-coding`, `.spec/STATE.md`, `.spec/PROJECT.md`, `.spec/REQUIREMENTS.md`, `.spec/ROADMAP.md` | `.gitignore:13-21` |
| `D.3` | **Phase 0 misfires in every worktree.** The agent branches on `.spec/.agentic-coding`; the file is gitignored and absent, so "Not found → run Init" fires on a project that is demonstrably already initialized | agent Phase 0 vs `.gitignore:17` |
| `D.4` | **Agent and command disagree on the anchor set.** The agent lists 6 anchor files; `.claude/commands/agentic-execute.md` says "read ONLY these four" and omits `ARCHITECTURE.md` and `TESTING.md` | `.claude/agents/spec-driven-developer.md` §Phase 4 vs `.claude/commands/agentic-execute.md` |
| `D.5` | **The agent's tool list contradicts its own instructions.** `tools: Read, Write, Bash, Grep, Glob` — no `Edit` (every change becomes a full-file rewrite), no `Skill` (Phase 4 step 6 and Phase 5 step 4 both require invoking `verify-e2e`), no `Agent` (its own "Multi-agent execution" section cannot run) | `.claude/agents/spec-driven-developer.md` frontmatter |
| `D.6` | **`.claude/skills/` is empty.** `verify-e2e` and `observe-tui` live under `.agents/skills/`, outside Claude Code's project skill discovery; they resolve today only because they are separately registered as user-scope skills. A clean clone does not get them | `.claude/skills/` vs `.agents/skills/` |
| `D.7` | **`.claude/settings.json` declares no `hooks`, no `agent`, no `defaultMode`, no `plansDirectory`.** Only `permissions` and `respectGitignore`. There is currently zero mechanical enforcement of anything in this intent | `.claude/settings.json` |
| `D.8` | **`ROADMAP.md` updates are dead steps.** Phase 5 step 6 and `agentic-verify.md` step 5 both write to a file that does not exist and is gitignored | agent Phase 5, `.claude/commands/agentic-verify.md` |

---

## Core Principle

**Enforcement fires on the tool call, not on the model's judgment.**

Every layer below is chosen because it is triggered by the harness at a fixed
point in the lifecycle. Instruction text is a *convenience* layer that makes the
common case pleasant; it is never the thing that guarantees compliance. Where a
layer depends on the model electing to read or obey something, it is marked as
advisory and something else carries the guarantee.

Corollary: the gate validates against **artifacts on disk**, never against the
model's claim about them.

---

## Implementation directive

**DO NOT immediately edit files.** Instead:

1. Read the current state for each assertion below.
2. Classify each as `PASS` (already satisfied) or `GAP` (with exact file and
   proposed change).
3. Answer `D1` with the user before implementing any `GATE.*` assertion.
4. Present all GAPs grouped by file and wait for approval before editing.

`FIX.*` (Part III §6) is a **prerequisite wave**: the gate validates plans
against `.spec/` artifacts, so the artifact set must be coherent before the gate
exists. Implement `FIX.*` first regardless of how `D1` resolves.

---

## Part III — The layers

### 1. Layer 1 (advisory) — `.claude/rules/spec-workflow.md`

Move the workflow contract out of a `CLAUDE.md` pointer and into a rule file
loaded unconditionally at launch (`F.10`). Advisory: it makes the normal case
work without a prompt, and carries no guarantee on its own.

| Assertion | Expected behavior |
|---|---|
| `RULE.1` | `.claude/rules/spec-workflow.md` exists, has **no** `paths:` frontmatter, and therefore loads at launch at the same priority as `.claude/CLAUDE.md` |
| `RULE.2` | It states the routing contract directly: planning or executing non-trivial work in this repo means producing `.spec/features/<name>/{spec,plan,tasks}.md` and running the phases, not ad-hoc edits |
| `RULE.3` | It names the trivial-work exemption in the same terms `D1` option (b) uses, so the rule and the gate cannot disagree about what is exempt |
| `RULE.4` | `CLAUDE.md`'s "Spec-driven workflow" section is reduced to a pointer at the rule; the contract text lives in exactly one place |
| `RULE.5` | The rule does **not** duplicate `AGENTS.md` content (commands, architecture). Per `CONSTITUTION.md`'s reference-don't-copy convention, it links |

### 2. Layer 2 (mechanical, non-blocking) — `PostToolUse` on `ExitPlanMode`

Fires the instant a plan is approved — the exact plan→execute boundary. Injects
the execution contract so Phase 4 discipline arrives without the user asking
(`F.7`).

| Assertion | Expected behavior |
|---|---|
| `INJ.1` | `.claude/settings.json` registers a `PostToolUse` hook with `matcher: "ExitPlanMode"` |
| `INJ.2` | The handler reads `tool_response.plan`, **not** the file at `filePath` (`F.7`) |
| `INJ.3` | It returns `hookSpecificOutput.additionalContext` naming: wave ordering is binding, acceptance gates are run against real code, the reachability/sabotage check precedes marking `[x]`, and `STATE.md` is updated after each task |
| `INJ.4` | The text is written as **factual statements** about the repository, not imperative system instructions, per `F.12`. "This repository executes tasks in wave order" — not "You must execute in wave order" |
| `INJ.5` | The payload stays under 10,000 characters so it is delivered inline rather than spilled to a file (`F.12`) |
| `INJ.6` | The hook never returns `decision: "block"`. Blocking belongs to Layer 3, which runs *before* the user has approved anything |
| `INJ.7` | Exits 0 on any internal error. A context-injection failure must not break the session |

### 3. Layer 3 (mechanical, blocking) — `PreToolUse` on `ExitPlanMode`

The hard gate. No plan reaches approval without conforming (`F.3`, `F.4`, `F.5`).

| Assertion | Expected behavior |
|---|---|
| `GATE.1` | `.claude/settings.json` registers a `PreToolUse` hook with `matcher: "ExitPlanMode"`, `type: "command"`, in **exec form**, referencing the validator by path placeholder |
| `GATE.2` | The validator parses stdin JSON and reads `tool_input.plan`. It must tolerate an empty/absent `plan` field without crashing, since the literal model-supplied input is normally empty and the content is injected (`F.4`) |
| `GATE.3` | A plan **passes** when it names an existing `.spec/features/<name>/tasks.md` that contains a `## Task Dependency Graph` section with a parseable JSON wave block |
| `GATE.4` | A plan **fails** otherwise, and the hook returns `permissionDecision: "deny"` with a `permissionDecisionReason` naming the missing artifact and the command that produces it (`/agentic-specify` or `/agentic-plan`). **Per `D1` option (b), a plan carrying a line matching `^Spec-exempt:\s*\S` passes regardless.** Change this assertion only when `D1` is answered differently |
| `GATE.5` | The hook **never** returns `permissionDecision: "allow"`. A conforming plan is passed by exiting 0 with no JSON output (`F.6`) |
| `GATE.6` | `permissionDecisionReason` is written for a model reader, since `deny` is the only decision whose reason reaches Claude (`F.5`). It states what is missing and the next command, not a bare refusal |
| `GATE.7` | The validator resolves `.spec/` from the hook input's **`cwd`** field, never from `${CLAUDE_PROJECT_DIR}` (`F.13`). With five live worktrees this is the difference between validating the right tree and validating `master` |
| `GATE.8` | An internal validator error (bad JSON, missing interpreter, unreadable `.spec/`) exits 0 and passes the plan. **The gate fails open.** A broken hook that denies every plan makes the repository unusable, and exit code 2 would route as `deny` (`F.5`) |
| `GATE.9` | The validator has no third-party dependencies and does not import `functualize`. It runs from the harness, outside the project venv, and must work in a clean clone |
| `GATE.10` | The reason text distinguishes the two failure shapes: no `.spec/features/<name>/` referenced at all, versus referenced but missing the wave graph |

### 4. Layer 3b (mechanical, blocking) — `PreToolUse` on `Agent`

Closes `F.2`: the built-in `Plan` agent plans this repo without ever seeing
`CLAUDE.md`, `AGENTS.md`, or the Layer 1 rule. Without this, every layer above
is bypassable by a single delegation.

| Assertion | Expected behavior |
|---|---|
| `DEL.1` | `.claude/settings.json` registers a `PreToolUse` hook with `matcher: "Agent"` |
| `DEL.2` | When `tool_input.subagent_type` is `"Plan"`, the hook returns `updatedInput` that **replaces the entire input object** — `prompt`, `description`, `subagent_type`, `model` all present — with the spec contract prepended to `prompt` (`F.8`) |
| `DEL.3` | `updatedInput` is returned **without** `permissionDecision: "allow"`, so normal permission handling still applies; the rewrite is the only intervention |
| `DEL.4` | `subagent_type: "Explore"` is **not** rewritten. Explore is read-only research and is a legitimate pre-spec activity — the agent's own Explore Mode says `research.md` is not a gate |
| `DEL.5` | Delegations already targeting `spec-driven-developer` pass through untouched |
| `DEL.6` | Fails open on any error, per the same reasoning as `GATE.8` |
| `DEL.7` | **Decide and record:** whether `subagent_type: "Plan"` is rewritten to `spec-driven-developer` outright, or kept as `Plan` with the contract injected into `prompt`. Rewriting is stronger but loses the built-in Plan agent's research tuning. Default: inject into `prompt`, keep `subagent_type` |

### 5. Plan-mode defaults

| Assertion | Expected behavior |
|---|---|
| `MODE.1` | `.claude/settings.json` sets `permissions.defaultMode: "plan"` so terminal sessions start in plan mode |
| `MODE.2` | **`MODE.1` is documented as inert for VS Code sessions** (`F.11`). The rule file and `CONTRIBUTING`/`AGENTS.md` note that VS Code users must set `claudeCode.initialPermissionMode: "plan"` in their **VS Code user settings**, which no repository file can do for them |
| `MODE.3` | `plansDirectory` is set to a project-relative path (`F.18`) so plan files land beside `.spec/` and are inspectable, instead of `~/.claude/plans` |
| `MODE.4` | The `plansDirectory` target is added to `.gitignore` if plans are per-session scratch, or deliberately committed if they are artifacts. **Decide explicitly** — do not leave it ambiguous |
| `MODE.5` | Setting `agent: "spec-driven-developer"` in `.claude/settings.json` (`F.9`) is **NOT** adopted in this pass. See Rejected alternatives `R.1` |

### 6. Repair existing drift — prerequisite wave

Nothing above can validate against `.spec/` until this is coherent.

| Assertion | Expected behavior |
|---|---|
| `FIX.1` | The anchor set is reconciled to **one** canonical list, identical in `.claude/agents/spec-driven-developer.md` and `.claude/commands/agentic-execute.md` (`D.4`) |
| `FIX.2` | Every file in that canonical list **exists** and is **committed**, or is removed from the list. `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md` are currently neither (`D.1`, `D.2`) |
| `FIX.3` | `.gitignore:13-21` is revisited: an anchor file that every fresh worktree must read cannot be gitignored. Either commit it, or stop calling it an anchor |
| `FIX.4` | Phase 0's `.agentic-coding` branch stops misfiring in worktrees (`D.3`) — either commit the marker or key the check on a committed file |
| `FIX.5` | `ROADMAP.md` steps in Phase 5 and `agentic-verify.md` either target a real committed file or are removed (`D.8`) |
| `FIX.6` | `spec-driven-developer`'s `tools:` list gains `Edit` and `Skill` at minimum, so its own Phase 4/5 instructions are executable (`D.5`). `Agent` is added only if the multi-agent wave execution section is intended to be live; if not, that section is marked as host-dependent and unreachable here |
| `FIX.7` | The `verify-e2e` / `observe-tui` skill location is resolved (`D.6`): either surfaced under `.claude/skills/` so a clean clone gets them, or the agent's references to them are marked as requiring user-scope installation |

### 7. `[DEFERRED]` — SpecKit gaps

Recorded from the comparison, explicitly **out of scope** for the enforcement
work. Do not implement in this pass.

SpecKit's current command set is `constitution`, `specify`, `clarify`, `plan`,
`tasks`, `implement`, plus optional `analyze`, `checklist`, `converge`. This
repo has `specify`, `plan`, `execute`, `verify`, `explore` — and a
`CONSTITUTION.md` maintained by hand.

| ID | Gap | Note |
|---|---|---|
| `SK.1` | **No `clarify` gate.** Phase 1 "Discuss" is the analogue but triggers "when requirements are unclear" — model discretion. SpecKit makes ambiguity resolution a *step*, which is what stops re-planning loops | Would slot between Specify and Plan |
| `SK.2` | **No `analyze`.** No cross-artifact consistency check between `spec.md`, `plan.md`, and `tasks.md` before Execute. Drift is currently caught at Verify, after the work is done | The `scrutinize` skill covers proposals, not intra-feature artifact consistency |
| `SK.3` | **No `converge`.** Phase 5 either passes or is fixed ad hoc; there is no step that re-assesses the codebase against the artifacts and appends the remainder as new tasks | Closest existing analogue is the manual scrutiny pass recorded in `tui-group-options-panels.md` |
| `SK.4` | **No `checklist`.** Quality checklists are embedded in phase prose rather than generated per feature | Lowest value of the four here |

**What this repo already does better than stock SpecKit, and must not lose:**

- The **wave dependency graph** in `tasks.md`. SpecKit has no parallelism model.
- The **reachability / sabotage gate** (`agentic-execute.md` step 5,
  `agentic-verify.md` steps 2b–2d). Earned from three capabilities that shipped
  built, unit-tested, and unreachable under green gates. Nothing in SpecKit or
  GSD has an equivalent.
- **Executable acceptances derived at authoring time**, with `[F]` equal to the
  gate command's hit set.

**What is taken from GSD and is already present:** fresh-context execution
against a fixed anchor set, and `STATE.md` as the primary anchor. The one GSD
property currently broken is that the anchor set does not exist on disk —
`FIX.1`–`FIX.3`.

---

## Rejected alternatives

| ID | Rejected | Why |
|---|---|---|
| `R.1` | `settings.agent: "spec-driven-developer"` — run every session as the agent (`F.9`) | Strongest available mechanism, but it applies the agent's **tool restrictions** to the whole session. With `D.5` unfixed that means no `Edit`, no `Skill`, no `Agent` for every session in the repo. Revisit only after `FIX.6`, and only as a deliberate decision — it also silently changes what `/code-review`, `/sync-docs`, and ad-hoc questions can do |
| `R.2` | `EnterPlanMode` hook | Not a matchable tool name; absent from the entire hooks reference (`F.3`). Building on it would be building on an unverified assumption |
| `R.3` | `UserPromptSubmit` as the enforcement point | Fails open silently on its 30-second timeout, discarding `additionalContext` without blocking (`F.16`). Acceptable as a nicety, unacceptable as the guarantee |
| `R.4` | `InstructionsLoaded` to verify the rule loaded | No decision control; output discarded; observability only (`F.15`). Usable for an audit log, nothing more |
| `R.5` | Hooks in `spec-driven-developer`'s frontmatter | Subagent hooks exist only while that agent runs (`F.14`), so they cannot enforce anything when the agent was never invoked — which is the entire problem being solved |
| `R.6` | Putting the contract only in `AGENTS.md` | Not loaded by the built-in `Plan` agent (`F.2`), and `AGENTS.md` explicitly declares itself "NOT workflow instructions" |

---

## Cross-cutting invariants

| Invariant | Description |
|---|---|
| `X.1` | **Fail open.** Every hook in this intent exits 0 on internal error. A broken validator degrades to today's behavior; it never bricks the repository. Exit code 2 routes as `deny` (`F.5`), so a crashing script would otherwise block all work |
| `X.2` | **`cwd`, not `${CLAUDE_PROJECT_DIR}`.** Every script resolves project paths from the hook input's `cwd` (`F.13`). Five worktrees are live; a hook that resolves to the session's origin root validates the wrong tree |
| `X.3` | **One source of truth for the contract.** The phase contract text exists in exactly one file. `CLAUDE.md`, `AGENTS.md`, the commands, and the hook payloads reference it; none restate it. This mirrors `CONSTITUTION.md`'s existing reference-don't-copy rule |
| `X.4` | **No enforcement layer depends on the model having read anything.** Layers 2, 3, and 3b fire from the harness. Layer 1 is explicitly labelled advisory |
| `X.5` | **Zero effect on the shipped package.** No file under `src/functualize/`, `tests/`, `plugins/`, or `pyproject.toml` changes. `uv run pytest`, `ruff`, `mypy`, and `lint-imports` are unaffected, and CI behavior is identical before and after |
| `X.6` | **The gate reads disk, not claims.** Conformance is decided by the existence and content of `.spec/features/<name>/tasks.md`, never by what the plan text asserts about itself — except the `D1` escape hatch, which is deliberately declarative and deliberately visible |
| `X.7` | **Deny reasons are addressed to a model.** They name the missing artifact and the command that creates it, because `deny` is the only channel Claude reads (`F.5`) |

---

## Verification checklist for the implementing agent

Audit each assertion against the current state before writing anything.

- `RULE.1–5`: `.claude/rules/` (does not exist yet), `CLAUDE.md` §"Spec-driven workflow"
- `INJ.1–7`: `.claude/settings.json` (`hooks` key absent — `D.7`), new handler script
- `GATE.1–10`: `.claude/settings.json`, new validator script
- `DEL.1–7`: `.claude/settings.json`, same or separate handler
- `MODE.1–5`: `.claude/settings.json`, plus a documentation note for the VS Code user setting
- `FIX.1`: `.claude/agents/spec-driven-developer.md` §Phase 4 vs `.claude/commands/agentic-execute.md`
- `FIX.2–3`: `.spec/` contents vs `.gitignore:13-21`
- `FIX.4`: `.claude/agents/spec-driven-developer.md` §Phase 0
- `FIX.5`: `.claude/agents/spec-driven-developer.md` §Phase 5, `.claude/commands/agentic-verify.md`
- `FIX.6`: `.claude/agents/spec-driven-developer.md` frontmatter `tools:`
- `FIX.7`: `.claude/skills/` (empty) vs `.agents/skills/`
- `SK.1–4`: deferred; audit only, do not implement

**Report format**: for each assertion, `PASS` (already satisfied, no change) or
`GAP` (with exact file, line range, and proposed change). Group GAPs by file.
Answer `D1` with the user. Wait for approval before editing.

### How to verify the hooks actually fire

A hook that is silently misconfigured is indistinguishable from no enforcement,
which is the failure mode this whole intent exists to prevent.

1. `/hooks` opens a **read-only** browser showing every configured hook, its
   matcher, and which settings file it came from (`hooks` §The `/hooks` menu).
   Confirm the entries appear under `Project Settings`.
2. Run the validator standalone against a captured stdin payload before wiring
   it, so a crash is found outside a live session.
3. Prove the gate **denies**: enter plan mode, produce a plan referencing no
   `.spec/features/` artifact, and confirm the denial reason reaches the model.
4. Prove the gate **passes**: repeat against a feature that has a real
   `tasks.md` with a wave graph, and confirm no prompt appears.
5. Prove it **fails open**: temporarily break the validator (bad JSON on stdout,
   nonzero-but-not-2 exit) and confirm planning still works. Restore.
6. Repeat 3–5 from **a second worktree** to prove `X.2` — this is the assertion
   most likely to pass in the main checkout and fail everywhere else.
