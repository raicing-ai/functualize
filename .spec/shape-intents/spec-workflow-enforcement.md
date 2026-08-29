# Shape Intent: Unconditional Spec-Driven Workflow Enforcement

**Status: specified, not yet implemented. All open decisions resolved 2026-08-29.**
**Date: 2026-08-29**
**Scope: `.claude/` harness configuration, `.gitignore`, and one CI job. No changes to `src/functualize/`, `plugins/*/src/`, `tests/`, or the package's public surface.**
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

## Resolved decisions

All nine were answered with the user on 2026-08-29. They are recorded here
because several of them **rewrite assertions below** — an implementing agent
that reads only Part III without this table will build the wrong gate.

| ID | Question | Decision | Consequence |
|---|---|---|---|
| `D0` | Where does the hard gate fire? | **`PreToolUse` on `Edit`/`Write`/`MultiEdit`**, scoped to shipped code. `ExitPlanMode` keeps only the Layer 2 injection | Layer 3 is rewritten off `ExitPlanMode`. See `R.7` |
| `D0b` | Which paths are gated? | **`src/functualize/**` and `plugins/*/src/**`** — shipped code only | Plugin tests, `plugins/conftest.py`, all `pyproject.toml`, and `PUBLISHING.md` stay free |
| `D1` | How does a legitimate small change pass? | **`.spec/EXEMPT` sentinel + committed `.spec/exemptions.log`** | Self-exemption becomes a reviewable diff, not an invisible act |
| `D2` | Rewrite the built-in `Plan` agent? | **No — inject the contract into `prompt`, keep `subagent_type`** | Resolves `DEL.7` |
| `D3` | Plan-mode settings? | **`defaultMode: "plan"` + `plansDirectory: ".spec/plans/"`, gitignored** | Resolves `MODE.4`. Requires the worktree verification in `MODE.6` |
| `D4` | Is `.spec/features/` committed? | **All of it — `spec.md`, `contracts.md`, `plan.md`, `schema.md`, `research.md`, `tasks.md` — committed on the branch** | Resolves `FIX.3`. Adds the `VCS.*` section. Revised after `D4b`; see `R.10` |
| `D4b` | Does master carry them? | **No — wiped before merge, enforced by a required CI check** | Adds `VCS.2`. Amends `X.5` |
| `D5` | What replaces `.spec/PROJECT.md`? | **`AGENTS.md`** | Resolves `FIX.1`, `FIX.2` with zero new files |
| `D6` | The `.agentic-coding` marker and `ROADMAP.md`? | **Retarget both** — Phase 0 keys on `.spec/CONSTITUTION.md`; ROADMAP steps target `.spec/STATUS.md` | Resolves `FIX.4`, `FIX.5` with zero new files |
| `D7` | Does `spec-driven-developer` get `Agent`? | **Yes — `Read, Write, Edit, Bash, Grep, Glob, Skill, Agent`** | Resolves `FIX.6`. Multi-agent wave execution becomes a live path |
| `D8` | Adopt `settings.agent` now that `D7` fixed the tool list? | **No — `R.1` stands** | `MODE.5` confirmed, not merely deferred |

---

## Part I — Findings: what the Claude Code docs establish

Each finding is load-bearing for at least one assertion below. Cited so the
implementing agent does not have to re-derive them.

| ID | Finding | Source |
|---|---|---|
| `F.1` | **Subagent selection is advisory and cannot be forced.** "Claude uses each subagent's description to decide when to delegate… There is no way to force Claude to always use a subagent automatically." Escalations are: naming it in the prompt, `@"name"` mention, or session-wide `--agent` / `settings.agent` | sub-agents |
| `F.2` | **The built-in `Plan` and `Explore` agents do not load `CLAUDE.md`.** "A non-fork subagent's initial context contains… CLAUDE.md files: every level of the CLAUDE.md hierarchy… **The built-in Explore and Plan agents skip this.**" Plan mode uses the built-in `Plan` agent for research | sub-agents |
| `F.3` | **`ExitPlanMode` is a hookable tool.** `PreToolUse` "matches on any tool name except `EndConversation`: built-in tools such as `Bash`, … `AskUserQuestion`, and `ExitPlanMode`". `EnterPlanMode` is **not** in the matchable list and appears nowhere in the hooks reference — do not build on it | hooks §PreToolUse |
| `F.4` | **The `ExitPlanMode` hook receives the plan text.** "Claude writes the plan to a file on disk before calling the tool, so the literal `tool_input` from the model is typically empty. Claude Code injects the plan content and file path before passing the input to hooks." Fields: `tool_input.plan`, `tool_input.planFilePath` | hooks §ExitPlanMode |
| `F.5` | **`deny` is the only decision channel that talks back to the model.** `permissionDecisionReason`: "For `allow` and `ask`, shown to the user but not Claude. For **`deny`, shown to Claude**." Multi-hook precedence is `deny` > `defer` > `ask` > `allow`. Exit code 2 routes identically to `deny`, with stderr as the reason | hooks §PreToolUse decision control |
| `F.6` | **`allow` alone does not work on `ExitPlanMode`.** "`AskUserQuestion` and `ExitPlanMode`… need `updatedInput` paired with it." Under `D0` this now only constrains Layer 2; the general rule that a pass is best expressed as exit 0 with no JSON still applies to Layer 3 | hooks §PreToolUse decision control |
| `F.7` | **`PostToolUse` on `ExitPlanMode` carries the approved plan.** "`tool_response` is an object with `plan` and `filePath` fields holding the approved plan, plus internal status flags. Read `tool_response.plan` for the plan content rather than re-reading the file from disk." The event honors `additionalContext`, delivered "next to the tool result" | hooks §ExitPlanMode, §Decision control |
| `F.8` | **Agent delegation is interceptable and rewritable.** `PreToolUse` on `Agent` receives `tool_input` = `{prompt, description, subagent_type, model}`. `updatedInput` "replaces the entire input object, so include unchanged fields alongside modified ones" | hooks §Agent, §PreToolUse decision control |
| `F.9` | **`settings.agent` runs the main thread as a named subagent.** "Run the main thread as a named subagent, so Claude Code applies that subagent's system prompt, tool restrictions, and model to your session." Scope: any settings file. `--agent` overrides it per session | settings-reference §agent |
| `F.10` | **`.claude/rules/*.md` is a first-class instruction surface.** "Rules without `paths` frontmatter are loaded at launch with the same priority as `.claude/CLAUDE.md`." Path-scoped rules load lazily when Claude touches matching files. Project rules are skipped if `project` is excluded from `--setting-sources` | memory §Organize rules |
| `F.11` | **`defaultMode: "plan"` does not apply in VS Code.** "Conversations the VS Code extension starts don't read project settings for the starting permission mode. There, set `claudeCode.initialPermissionMode` to `plan` in your VS Code user settings instead." This repo is driven from the VS Code extension | permission-modes §Set plan mode as the default |
| `F.12` | **`additionalContext` must be phrased as fact, not command.** "Write the text as factual statements rather than imperative system instructions… Text framed as out-of-band system commands can trigger Claude's prompt-injection defenses, which causes Claude to surface the text to you instead of treating it as context." Values over 10,000 chars are spilled to a file and replaced with a path plus preview | hooks §Add context for Claude |
| `F.13` | **`${CLAUDE_PROJECT_DIR}` does not follow into a worktree.** "`${CLAUDE_PROJECT_DIR}` stays put: it still points at the project root where the session started… `cwd` follows Claude: the `cwd` field in the hook's input JSON is the worktree root after Claude enters a worktree." This repository is worked on from **five** live worktrees | hooks §Reference scripts by path |
| `F.14` | **Hooks can live in skill and subagent frontmatter.** Skill hooks stay registered for the rest of the session (unless `once: true`); subagent hooks are removed when the agent finishes | hooks §Hooks in skills and agents |
| `F.15` | **`InstructionsLoaded` cannot enforce anything.** It "runs asynchronously for observability purposes" and has no decision control — output fields are discarded. Usable for audit only | hooks §InstructionsLoaded |
| `F.16` | **`UserPromptSubmit` is cheap but has a short leash.** Default timeout is **30s**, and "a hook that reaches its timeout is canceled and its output, including any `additionalContext`, is discarded" — it fails open and silently | hooks §UserPromptSubmit |
| `F.17` | **`SessionStart` can seed context and rename the session.** Fields: `additionalContext`, `initialUserMessage` (headless `-p` only), `sessionTitle`, `watchPaths`, `reloadSkills`. Re-runs on `--resume` with `source: "resume"` | hooks §SessionStart decision control |
| `F.18` | **`plansDirectory` relocates plan-mode files.** Resolved relative to project root; "keeps the default when the path resolves outside it". Default is `~/.claude/plans`. Read together with `F.13`, its behaviour inside a worktree is **unverified** — see `MODE.6` | settings-reference §plansDirectory |

---

## Part II — Findings: drift in the current repository

Discovered while auditing. Every one of these breaks an enforcement layer if
left alone, because a validating hook has to check against artifacts that
actually exist.

| ID | Finding | Evidence |
|---|---|---|
| `D.1` | **The Execute context anchor names files that do not exist.** `spec-driven-developer.md` anchors on `.spec/PROJECT.md`; the directory contains no `PROJECT.md`, `REQUIREMENTS.md`, or `ROADMAP.md` | `.spec/` holds only `ARCHITECTURE.md`, `CONSTITUTION.md`, `README.md`, `STATUS.md`, `TESTING.md`, `shape-intents/` |
| `D.2` | **Those anchors are gitignored, so a fresh worktree can never have them.** `.gitignore:13-21` ignores `.spec/features/`, `.spec/.agentic-coding`, `.spec/STATE.md`, `.spec/PROJECT.md`, `.spec/REQUIREMENTS.md`, `.spec/ROADMAP.md` | `.gitignore:13-21` |
| `D.3` | **Phase 0 misfires in every worktree.** The agent branches on `.spec/.agentic-coding`; the file is gitignored and absent, so "Not found → run Init" fires on a project that is demonstrably already initialized | agent Phase 0 vs `.gitignore:17` |
| `D.4` | **Agent and command disagree on the anchor set.** The agent lists 6 anchor files; `.claude/commands/agentic-execute.md` says "read ONLY these four" and omits `ARCHITECTURE.md` and `TESTING.md` | `.claude/agents/spec-driven-developer.md` §Phase 4 vs `.claude/commands/agentic-execute.md` |
| `D.5` | **The agent's tool list contradicts its own instructions.** `tools: Read, Write, Bash, Grep, Glob` — no `Edit` (every change becomes a full-file rewrite), no `Skill` (Phase 4 step 6 and Phase 5 step 4 both require invoking `verify-e2e`), no `Agent` (its own "Multi-agent execution" section cannot run) | `.claude/agents/spec-driven-developer.md` frontmatter |
| `D.6` | ~~`.claude/skills/` is empty.~~ **STALE — verified `PASS` 2026-08-29.** `.claude/skills/` holds ten committed symlinks (git mode `120000`) into `.agents/skills/`, including `verify-e2e` and `observe-tui`. A clean clone on Linux/macOS resolves them. Only residual caveat: a Windows clone without `core.symlinks` gets text files | `git ls-files -s .claude/skills/` |
| `D.7` | **`.claude/settings.json` declares no `hooks`, no `agent`, no `defaultMode`, no `plansDirectory`.** Only `permissions` and `respectGitignore`. There is currently zero mechanical enforcement of anything in this intent | `.claude/settings.json` |
| `D.8` | **`ROADMAP.md` updates are dead steps.** Phase 5 step 6 and `agentic-verify.md` step 5 both write to a file that does not exist and is gitignored | agent Phase 5, `.claude/commands/agentic-verify.md` |
| `D.9` | **Plan mode is read-only, so a gate on `ExitPlanMode` deadlocks.** `/agentic-specify` and `/agentic-plan` *write* `spec.md` and `tasks.md`, which plan mode forbids. A gate demanding an existing `tasks.md` at plan-exit therefore denies the very exit that would let the model create it. This is why `D0` moved Layer 3 | permission-modes §plan mode |
| `D.10` | **Master is squash-merged with zero merge commits.** All ten landed PRs appear as single `(#N)` commits; branch commits never enter master's history. Deleted branches remain fetchable via `refs/pull/<N>/head`, which is what makes `D4b` safe | `git log --merges master` → 0; `git ls-remote origin 'refs/pull/*'` → 10 refs |

---

## Core Principle

**Enforcement fires on the tool call, not on the model's judgment.**

Every layer below is triggered by the harness at a fixed point in the
lifecycle. Instruction text is a *convenience* layer that makes the common case
pleasant; it is never the thing that guarantees compliance. Where a layer
depends on the model electing to read or obey something, it is marked as
advisory and something else carries the guarantee.

The chosen fixed point (`D0`) is **the first attempt to modify shipped code**.
That is the moment the workflow actually matters, it is reachable from every
permission mode and every host including VS Code (`F.11`), and it cannot
deadlock against plan mode's read-only rule (`D.9`).

Corollary: the gate validates against **artifacts on disk**, never against the
model's claim about them.

---

## Implementation directive

**DO NOT immediately edit files.** Instead:

1. Read the current state for each assertion below.
2. Classify each as `PASS` (already satisfied) or `GAP` (with exact file and
   proposed change).
3. Present all GAPs grouped by file and wait for approval before editing.

All decisions are resolved — do not re-open them. `FIX.*` and `VCS.1` are a
**prerequisite wave**: the gate validates against `.spec/` artifacts, so the
artifact set must be coherent and committed before the gate exists.

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
| `RULE.3` | It documents the `.spec/EXEMPT` escape hatch in the same terms `GATE.5` enforces, so the rule and the gate cannot disagree about what is exempt |
| `RULE.4` | `CLAUDE.md`'s "Spec-driven workflow" section is reduced to a pointer at the rule; the contract text lives in exactly one place |
| `RULE.5` | The rule does **not** duplicate `AGENTS.md` content (commands, architecture). Per `CONSTITUTION.md`'s reference-don't-copy convention, it links |
| `RULE.6` | It documents the VS Code plan-mode caveat (`F.11`) and the PR-ref recovery recipe (`VCS.4`), both of which are things no repository file can do on the reader's behalf |

### 2. Layer 2 (mechanical, non-blocking) — `PostToolUse` on `ExitPlanMode`

Fires the instant a plan is approved — the plan→execute boundary. Injects the
execution contract so Phase 4 discipline arrives without the user asking
(`F.7`). Under `D0` this is the **only** thing hanging off `ExitPlanMode`.

| Assertion | Expected behavior |
|---|---|
| `INJ.1` | `.claude/settings.json` registers a `PostToolUse` hook with `matcher: "ExitPlanMode"` |
| `INJ.2` | The handler reads `tool_response.plan`, **not** the file at `filePath` (`F.7`) |
| `INJ.3` | It returns `hookSpecificOutput.additionalContext` naming: wave ordering is binding, acceptance gates are run against real code, the reachability/sabotage check precedes marking `[x]`, and `STATE.md` is updated after each task |
| `INJ.4` | The text is written as **factual statements** about the repository, not imperative system instructions, per `F.12`. "This repository executes tasks in wave order" — not "You must execute in wave order" |
| `INJ.5` | The payload stays under 10,000 characters so it is delivered inline rather than spilled to a file (`F.12`) |
| `INJ.6` | The hook never returns `decision: "block"`. Nothing on `ExitPlanMode` blocks — per `D0`, blocking lives on the write gate |
| `INJ.7` | Exits 0 on any internal error. A context-injection failure must not break the session |

### 3. Layer 3 (mechanical, blocking) — `PreToolUse` on `Edit` / `Write` / `MultiEdit`

**Rewritten per `D0`.** The hard gate. No shipped code changes without an
atomized task list on disk.

| Assertion | Expected behavior |
|---|---|
| `GATE.1` | `.claude/settings.json` registers a `PreToolUse` hook with `matcher: "Edit\|Write\|MultiEdit"`, `type: "command"`, in **exec form** |
| `GATE.1a` | The script is referenced by a **repo-relative path** (`.claude/hooks/…`), **not** `${CLAUDE_PROJECT_DIR}/.claude/hooks/…`. Per `F.13` the placeholder stays pinned to the session's origin root, so it would run *master's* copy of the validator while `X.2` has that same run validating the *worktree's* `.spec/` — a split that silently tests the wrong script the moment the validator itself is being edited on a branch |
| `GATE.2` | The validator parses stdin JSON and reads `tool_input.file_path`. It tolerates an absent or non-string `file_path` by exiting 0 |
| `GATE.3` | **Gated scope is `src/functualize/**` and `plugins/*/src/**`** (`D0b`), resolved relative to the hook input's `cwd`. Any other path — `tests/`, `plugins/*/tests/`, `plugins/conftest.py`, every `pyproject.toml`, `plugins/PUBLISHING.md`, `docs/`, `contributor/`, `.spec/`, `.claude/` — exits 0 without further checks |
| `GATE.4` | A gated write **passes** when at least one `.spec/features/*/tasks.md` exists containing a `## Task Dependency Graph` section with a parseable wave block |
| `GATE.5` | A gated write also **passes** when `.spec/EXEMPT` exists, its mtime is within the freshness window (default 60 minutes), and its first non-empty line matches `^Spec-exempt:\s*(.{20,})$`. The 20-character floor exists so "small change" does not satisfy it (`D1`) |
| `GATE.6` | When the gate passes via `GATE.5`, the validator appends one tab-separated record to `.spec/exemptions.log`: ISO-8601 timestamp, worktree basename, `file_path`, reason. Records are deduplicated by `(reason, hour)` so a ten-file fix logs once, not ten times |
| `GATE.7` | `.spec/exemptions.log` is **committed**, not gitignored. That is the entire mitigation for the model's ability to self-exempt: it becomes a line in the next diff (`D1`) |
| `GATE.8` | A gated write **fails** otherwise, and the hook returns `permissionDecision: "deny"` with a `permissionDecisionReason` naming the missing artifact, the commands that produce it (`/agentic-specify` then `/agentic-plan`), and the `.spec/EXEMPT` path with its required line format |
| `GATE.9` | The hook **never** returns `permissionDecision: "allow"`. A passing write is passed by exiting 0 with no JSON output, so normal permission handling still applies |
| `GATE.10` | `permissionDecisionReason` is written for a model reader, since `deny` is the only decision whose reason reaches Claude (`F.5`). It states what is missing and the next command, not a bare refusal |
| `GATE.11` | The reason text distinguishes three failure shapes: no `.spec/features/` directory at all; a feature directory present but no `tasks.md`; a `tasks.md` present but missing or malformed `## Task Dependency Graph` |
| `GATE.12` | The validator resolves `.spec/` from the hook input's **`cwd`** field, never from `${CLAUDE_PROJECT_DIR}` (`F.13`). With five live worktrees this is the difference between validating the right tree and validating `master` |
| `GATE.13` | An internal validator error (bad JSON, missing interpreter, unreadable `.spec/`) exits 0 and passes the write. **The gate fails open.** A broken hook that denies every edit makes the repository unusable, and exit code 2 would route as `deny` (`F.5`) |
| `GATE.14` | The validator has no third-party dependencies and does not import `functualize`. It runs from the harness, outside the project venv, and must work in a clean clone |
| `GATE.15` | The validator is cheap enough to run on **every** file edit: a bounded `scandir` of `.spec/features/` plus one file read. No recursive walk of the repository, no subprocess, no git invocation |

### 4. Layer 3b (mechanical, non-blocking) — `PreToolUse` on `Agent`

Closes `F.2`: the built-in `Plan` agent plans this repo without ever seeing
`CLAUDE.md`, `AGENTS.md`, or the Layer 1 rule.

| Assertion | Expected behavior |
|---|---|
| `DEL.1` | `.claude/settings.json` registers a `PreToolUse` hook with `matcher: "Agent"` |
| `DEL.2` | When `tool_input.subagent_type` is `"Plan"`, the hook returns `updatedInput` that **replaces the entire input object** — `prompt`, `description`, `subagent_type`, `model` all present — with the spec contract prepended to `prompt` (`F.8`) |
| `DEL.3` | `updatedInput` is returned **without** `permissionDecision: "allow"`, so normal permission handling still applies; the rewrite is the only intervention |
| `DEL.4` | `subagent_type: "Explore"` is **not** rewritten. Explore is read-only research and is a legitimate pre-spec activity — the agent's own Explore Mode says `research.md` is not a gate |
| `DEL.5` | Delegations already targeting `spec-driven-developer` pass through untouched |
| `DEL.6` | Fails open on any error, per the same reasoning as `GATE.13` |
| `DEL.7` | **RESOLVED (`D2`):** `subagent_type` stays `"Plan"`; the contract is injected into `prompt`. Rewriting to `spec-driven-developer` was rejected because `/code-review`, `/improve`, and `/scrutinize` delegate to `Plan` for read-only research, and `spec-driven-developer` holds `Write` |
| `DEL.8` | The default / `general-purpose` agent is **not** rewritten. It loads `CLAUDE.md` and the Layer 1 rule already (`F.2` names only `Explore` and `Plan` as skipping them) |

### 5. Plan-mode defaults

| Assertion | Expected behavior |
|---|---|
| `MODE.1` | `.claude/settings.json` sets `permissions.defaultMode: "plan"` so terminal sessions start in plan mode |
| `MODE.2` | **`MODE.1` is documented as inert for VS Code sessions** (`F.11`). The rule file and `AGENTS.md` note that VS Code users must set `claudeCode.initialPermissionMode: "plan"` in their **VS Code user settings**, which no repository file can do for them |
| `MODE.3` | `plansDirectory` is set to `.spec/plans/` (`F.18`) so plan files land beside `.spec/` and are inspectable, instead of `~/.claude/plans` |
| `MODE.4` | **RESOLVED (`D3`):** plan files are per-session scratch. `.spec/plans/` is added to `.gitignore`, consistent with `.spec/README.md`'s argument-at-a-moment policy |
| `MODE.5` | **CONFIRMED REJECTED (`D8`):** `agent: "spec-driven-developer"` is not set. `R.1`'s tool-restriction objection is resolved by `FIX.6`, but its system-prompt objection stands and the write gate makes it redundant |
| `MODE.6` | **Verify before adopting `MODE.3`.** `F.18` resolves `plansDirectory` against project root and `F.13` says project root does not follow into a worktree. Write a plan from a non-master worktree and confirm the file lands in *that* worktree. If it lands in the master checkout, revert `MODE.3` to the default and record that here |

### 6. Version-control lifecycle — new, from `D4` / `D4b`

The gate's pass condition is an artifact on disk. This section decides who else
can see it and how long it lives.

| Assertion | Expected behavior |
|---|---|
| `VCS.1` | The `.spec/features/` line is **deleted** from `.gitignore`, so the whole directory is tracked: `spec.md`, `contracts.md`, `plan.md`, `schema.md`, `research.md`, `tasks.md`. No negation patterns — git will not descend into an excluded directory, so a `!.spec/features/*/spec.md` carve-out would need `!.spec/features/*/` first and is a known silent-failure shape. One deleted line cannot fail that way (`D4`) |
| `VCS.1a` | The scope of `VCS.1` is **`.spec/features/` only**, because that is exactly what `VCS.2` wipes. `.spec/plans/` stays ignored (`MODE.4`) — harness scratch produced on every plan-mode exit, not phase output. `.spec/STATE.md` stays ignored — it is not under `features/`, so the wipe would not reach it and it would leak to master |
| `VCS.2` | `.github/workflows/ci.yml` gains a `spec-artifacts-cleared` job that fails while `git ls-files .spec/features/` is non-empty. It is marked as a **required check**, so a PR cannot merge until the clearing commit is pushed (`D4b`). `ci.yml` already triggers on **both** `push: [master]` and `pull_request: [master]`, so this single job is simultaneously the blocking PR check and the post-merge master guard — no second job is needed. It must use `actions/checkout` without `sparse-checkout`, since `git ls-files` needs the index |
| `VCS.3` | Phase 5 of `spec-driven-developer.md` and `.claude/commands/agentic-verify.md` gain the clearing step, ordered after the existing migration ritual: migrate the durable half into `.spec/STATUS.md` or `contributor/adr/`, **then** `git rm -r .spec/features/<name>` |
| `VCS.4` | The rule file documents the recovery recipe, because master carries no trace: `git log --oneline master --grep=<feature>` yields `(#N)`; `git fetch origin refs/pull/N/head`; `git show FETCH_HEAD:.spec/features/<name>/tasks.md`. It also records the caveats — PR refs are not fetched by default, do not survive a repo mirror, and are long-standing GitHub behavior rather than a documented guarantee (`D.10`) |
| `VCS.5` | `.spec/plans/` is gitignored (`MODE.4`) |
| `VCS.6` | `.spec/exemptions.log` is tracked and is **not** cleared by `VCS.3`. It is the durable record of every bypass and outlives the features it describes (`GATE.7`) |

### 7. Repair existing drift — prerequisite wave

Nothing above can validate against `.spec/` until this is coherent.

| Assertion | Expected behavior |
|---|---|
| `FIX.1` | **RESOLVED (`D5`):** the anchor set is reconciled to one canonical six-file list, written identically into `.claude/agents/spec-driven-developer.md` §Phase 4 and `.claude/commands/agentic-execute.md`: `AGENTS.md`, `.spec/CONSTITUTION.md`, `.spec/ARCHITECTURE.md`, `.spec/TESTING.md`, `.spec/STATE.md`, `.spec/features/<name>/tasks.md`. The command currently says "these four" and omits `ARCHITECTURE.md` and `TESTING.md` (`D.4`) |
| `FIX.2` | **RESOLVED (`D5`):** `.spec/PROJECT.md` is dropped from the anchor list in favour of `AGENTS.md`, which is committed and already carries project context, commands, architecture, and constraints. No new file is created; `REQUIREMENTS.md` and `ROADMAP.md` are removed from all anchor and collateral lists (`D.1`, `D.2`) |
| `FIX.3` | **RESOLVED (`D4`, see `VCS.1`):** `.gitignore:13-21` is revised so all of `.spec/features/` is tracked, and the dead `PROJECT.md` / `REQUIREMENTS.md` / `ROADMAP.md` lines are removed (`FIX.2`). `.spec/STATE.md` **stays gitignored** — it is genuinely per-session — but the Execute anchor lists **and** `agentic-specify.md:1` / `agentic-plan.md:1`, which both open by reading it, gain the clause *"if `STATE.md` is absent, treat as: no work in flight"* so a fresh worktree does not stall on it |
| `FIX.4` | **RESOLVED (`D6`):** Phase 0 branches on `.spec/CONSTITUTION.md` instead of the gitignored `.spec/.agentic-coding`. It is committed and only exists post-init, so it answers the same question without a marker file and cannot drift out of existence (`D.3`) |
| `FIX.5` | **RESOLVED (`D6`):** Phase 5 step 6 and `agentic-verify.md` step 5 retarget from `ROADMAP.md` to `.spec/STATUS.md`, which already carries *Open Features*, *Deferred*, and *Recently Completed* — and is now the durable record, since `VCS.3` wipes `features/` at merge (`D.8`) |
| `FIX.6` | **RESOLVED (`D7`):** `spec-driven-developer`'s frontmatter becomes `tools: Read, Write, Edit, Bash, Grep, Glob, Skill, Agent`. Every instruction in the agent file becomes executable, including the multi-agent wave section. Its "serialize `STATE.md` writes" constraint remains prose that no tool enforces — note this in the section rather than claiming it is guaranteed (`D.5`) |
| `FIX.7` | **PASS — no action.** `D.6` was stale: `.claude/skills/` holds ten committed symlinks into `.agents/skills/`, `verify-e2e` and `observe-tui` among them. Add only a one-line note that Windows clones without `core.symlinks` get text files instead |

### 8. `[DEFERRED]` — SpecKit gaps

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
  Under `D7` it is now executable, not just descriptive.
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
| `R.1` | `settings.agent: "spec-driven-developer"` — run every session as the agent (`F.9`) | Confirmed rejected by `D8`. Its tool-restriction objection is resolved by `FIX.6`, but it also applies the agent's **system prompt** to every session — so ad-hoc questions, `/code-review`, and `/sync-docs` get answered by a workflow executor. The write gate delivers the guarantee without that cost |
| `R.2` | `EnterPlanMode` hook | Not a matchable tool name; absent from the entire hooks reference (`F.3`) |
| `R.3` | `UserPromptSubmit` as the enforcement point | Fails open silently on its 30-second timeout, discarding `additionalContext` without blocking (`F.16`) |
| `R.4` | `InstructionsLoaded` to verify the rule loaded | No decision control; output discarded; observability only (`F.15`) |
| `R.5` | Hooks in `spec-driven-developer`'s frontmatter | Subagent hooks exist only while that agent runs (`F.14`), so they cannot enforce anything when the agent was never invoked — which is the entire problem being solved |
| `R.6` | Putting the contract only in `AGENTS.md` | Not loaded by the built-in `Plan` agent (`F.2`), and `AGENTS.md` explicitly declares itself "NOT workflow instructions". `D5` still adds it to the *anchor set*, which is a different mechanism — the agent is told to read it, it is not relied on to arrive automatically |
| `R.7` | **`PreToolUse` on `ExitPlanMode` as the hard gate** (the original Layer 3) | Rejected by `D0`. Plan mode is read-only, so the gate would deny the exit that lets the model write `spec.md` and `tasks.md` — every new feature would need an exemption on its first plan, training the model to reach for the bypass reflexively (`D.9`). It is also inert in VS Code, where this repo is actually driven (`F.11`) |
| `R.8` | Gating all of `plugins/**` | Rejected by `D0b`. It would gate plugin *tests* while core `tests/` stayed free — an asymmetry with no principle behind it |
| `R.9` | Gating `pyproject.toml` and packaging metadata | Rejected by `D0b`. Dependency bumps and version pins would trip the gate at every release |
| `R.10` | ~~Committing all of `.spec/features/`~~ **Un-rejected 2026-08-29 — this is now the decision (`VCS.1`).** The original objection borrowed `.spec/README.md`'s argument that *"the repository accumulates documents that contradict the code"*. `D4b` removed the accumulation: master carries none of it, so the stated harm cannot occur. What a partial carve-out would have cost instead: `agentic-verify.md` step 2b walks `contracts.md`, which would have been untracked and therefore invisible to the reviewer being asked to trust that walk |
| `R.11` | A partial carve-out (`spec.md` + `tasks.md` tracked, the rest ignored) | Superseded by `R.10`. It also required a `!.spec/features/*/` negation before any file-level negation could match, which is the `.gitignore` failure shape most likely to pass review and silently ignore the wrong set |

---

## Cross-cutting invariants

| Invariant | Description |
|---|---|
| `X.1` | **Fail open.** Every hook in this intent exits 0 on internal error. A broken validator degrades to today's behavior; it never bricks the repository. Exit code 2 routes as `deny` (`F.5`), so a crashing script would otherwise block all work |
| `X.2` | **`cwd`, not `${CLAUDE_PROJECT_DIR}`.** Every script resolves project paths from the hook input's `cwd` (`F.13`). Five worktrees are live; a hook that resolves to the session's origin root validates the wrong tree |
| `X.3` | **One source of truth for the contract.** The phase contract text exists in exactly one file. `CLAUDE.md`, `AGENTS.md`, the commands, and the hook payloads reference it; none restate it. This mirrors `CONSTITUTION.md`'s existing reference-don't-copy rule |
| `X.4` | **No enforcement layer depends on the model having read anything.** Layer 3 fires from the harness. Layers 1, 2, and 3b are explicitly advisory |
| `X.5` | **Zero effect on the shipped package.** No file under `src/functualize/`, `plugins/*/src/`, `tests/`, or any `pyproject.toml` changes. `uv run pytest`, `ruff`, `mypy`, and `lint-imports` are unaffected. **Amended by `D4b`:** CI gains exactly one new job (`VCS.2`); no existing test or lint gate changes behavior |
| `X.6` | **The gate reads disk, not claims.** Conformance is decided by the existence and content of `.spec/features/*/tasks.md`, never by what the model asserts — except the `.spec/EXEMPT` escape hatch, which is deliberately declarative, deliberately visible, and deliberately logged (`GATE.6`, `GATE.7`) |
| `X.7` | **Deny reasons are addressed to a model.** They name the missing artifact and the command that creates it, because `deny` is the only channel Claude reads (`F.5`) |
| `X.8` | **Bypass surface is exactly one mechanism.** `.spec/EXEMPT` is the only sanctioned way past the gate. `D8` rejected `settings.agent` partly to avoid a second, overlapping escape route (`--agent` override), because two bypasses is how an enforcement scheme decays |

---

## Verification checklist for the implementing agent

Audit each assertion against the current state before writing anything.

- `RULE.1–6`: `.claude/rules/` (does not exist yet), `CLAUDE.md` §"Spec-driven workflow"
- `INJ.1–7`: `.claude/settings.json` (`hooks` key absent — `D.7`), new handler script
- `GATE.1–15`: `.claude/settings.json`, new validator script
- `DEL.1–8`: `.claude/settings.json`, same or separate handler
- `MODE.1–6`: `.claude/settings.json`, plus a documentation note for the VS Code user setting
- `VCS.1–6`: `.gitignore`, `.github/workflows/ci.yml`, GitHub required-checks configuration
- `FIX.1–2`: `.claude/agents/spec-driven-developer.md` §Phase 4 vs `.claude/commands/agentic-execute.md`
- `FIX.3`: `.spec/` contents vs `.gitignore:13-21`
- `FIX.4`: `.claude/agents/spec-driven-developer.md` §Phase 0
- `FIX.5`: `.claude/agents/spec-driven-developer.md` §Phase 5, `.claude/commands/agentic-verify.md`
- `FIX.6`: `.claude/agents/spec-driven-developer.md` frontmatter `tools:`
- `FIX.7`: `PASS` — verify with `git ls-files -s .claude/skills/` and stop
- `SK.1–4`: deferred; audit only, do not implement

**Report format**: for each assertion, `PASS` (already satisfied, no change) or
`GAP` (with exact file, line range, and proposed change). Group GAPs by file.
Wait for approval before editing.

### How to verify the hooks actually fire

A hook that is silently misconfigured is indistinguishable from no enforcement,
which is the failure mode this whole intent exists to prevent.

1. `/hooks` opens a **read-only** browser showing every configured hook, its
   matcher, and which settings file it came from. Confirm the entries appear
   under `Project Settings`.
2. Run the validator standalone against a captured stdin payload before wiring
   it, so a crash is found outside a live session.
3. Prove the gate **denies**: with no `.spec/features/` present, attempt an edit
   to a file under `src/functualize/` and confirm the denial reason reaches the
   model and names both `/agentic-specify` and `.spec/EXEMPT`.
4. Prove the gate **ignores what it should**: edit `tests/`, `plugins/*/tests/`,
   `plugins/conftest.py`, a `pyproject.toml`, and `docs/` — none may prompt.
5. Prove the gate **passes on artifacts**: create a `tasks.md` with a wave graph
   and repeat step 3; no denial.
6. Prove the **exemption path**: write `.spec/EXEMPT`, confirm the edit passes,
   and confirm a record landed in `.spec/exemptions.log`. Then age the file past
   the freshness window and confirm the gate denies again.
7. Prove it **fails open**: temporarily break the validator (bad JSON on stdout,
   nonzero-but-not-2 exit) and confirm editing still works. Restore.
8. Prove `MODE.6`: write a plan from a non-master worktree and confirm the file
   lands in that worktree, not in the master checkout.
9. Prove `VCS.2`: open a PR with a `.spec/features/` directory present and
   confirm the required check blocks the merge until it is removed.
10. Repeat 3–7 from **a second worktree** to prove `X.2` — this is the assertion
    most likely to pass in the main checkout and fail everywhere else.
