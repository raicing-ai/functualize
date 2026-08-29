# Contracts: `spec-workflow-enforcement`

External interfaces only — the boundaries where this feature meets something it
does not own. Internal helpers, parsing strategies, and file layout inside the
scripts are **not** here; they belong to `plan.md`.

Every item below is a declared surface. `agentic-verify` step 2b walks this
file line by line and names the test that exercises each item **through its
public entry point** — for a hook, that means feeding stdin to the script and
asserting on stdout and exit code, never calling an internal function.

Field shapes marked **[doc]** are established by a Part I finding in the shape
intent. Shapes marked **[assumed]** are inferred from the documented envelope
and must be confirmed against a captured payload before the script depends on
them (`GATE.2` requires tolerating their absence regardless).

---

## C1 — Harness → gate validator (`PreToolUse`, `Edit|Write|NotebookEdit`)

**stdin**, one JSON object:

| Field | Type | Notes |
|---|---|---|
| `cwd` | string | Worktree root the agent is standing in. **[doc `F.13`]** The only path source the validator may use (`X.2`, `GATE.12`) |
| `tool_name` | string | `"Edit"`, `"Write"`, or `"NotebookEdit"`. **`MultiEdit` does not exist in this build** (`research.md` §`F0.4`) |
| `tool_input.file_path` | string | Target path, **absolute**. **[doc `research.md` §`F0.1`]** — observed directly for `Edit` and `Write`. Assumed by symmetry for `NotebookEdit`. May be absent or non-string; that case exits 0 (`GATE.2`) |
| `session_id` | string | **[doc `F.17`]** Not consumed by the current design; the freshness window is mtime-based (`GATE.5`) |
| `hook_event_name` | string | `"PreToolUse"` |
| `permission_mode` | string | **[doc `F0.1`]** Observed but unused. Would reveal whether the session is in plan mode |
| `effort`, `prompt_id`, `tool_use_id`, `transcript_path` | — | **[doc `F0.1`]** Observed, unused |

**stdout on pass:** empty. Exit 0. The validator **never** emits
`permissionDecision: "allow"` (`GATE.9`).

**stdout on deny:** exit 0 with one JSON object.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<addressed to the model>"
  }
}
```

**Exit codes.** `0` in every case, including internal failure (`GATE.13`,
`X.1`). Exit `2` is forbidden — it routes as `deny` with stderr as the reason
(`F.5`), which would turn a crash into a repo-wide block.

**`permissionDecisionReason` contract.** Names the missing artifact, the
producing command, and the exemption path. Distinguishes three cases
(`GATE.11`): no `.spec/features/` at all; a feature directory without
`tasks.md`; a `tasks.md` without a parseable `## Task Dependency Graph`.

---

## C2 — Harness → plan-exit injector (`PostToolUse`, `ExitPlanMode`)

**stdin:**

| Field | Type | Notes |
|---|---|---|
| `tool_response.plan` | string | Approved plan markdown. **[doc `research.md` §`F0.7`]** — observed, 3588 chars. Read this, never the file at `filePath` (`INJ.2`) |
| `tool_response.filePath` | string | **[doc `F0.7`]** Present, deliberately unused |
| `tool_response.hasTaskTool`, `.isAgent` | bool | **[doc `F0.7`]** The internal flags `F.7` alluded to. Unused |
| `tool_input` | object | **Observed empty `{}`** — `F.4`'s claimed `plan` / `planFilePath` injection did **not** reproduce (`F0.8`). Nothing reads it |
| `duration_ms` | number | **[doc `F0.7`]** Present on `PostToolUse` only |
| `cwd` | string | **[doc `F0.2`]** Worktree root |

**stdout:** exit 0 with one JSON object.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "<factual statements, < 10000 chars>"
  }
}
```

`additionalContext` is phrased as statements about the repository, not as
imperatives — imperative framing trips prompt-injection defenses and surfaces
the text to the user instead (`F.12`, `INJ.4`). Payload stays under 10,000
characters to avoid file spill (`INJ.5`). `decision: "block"` is never emitted
(`INJ.6`).

---

## C3 — Harness → delegation rewriter (`PreToolUse`, `Agent`)

**stdin:** `tool_input` observed as
`{description, prompt, run_in_background, subagent_type}`
(**[doc `research.md` §`F0.9`]**).

> `F.8` documents this as `{prompt, description, subagent_type, model}`. That is
> **wrong in two ways**: `model` is *absent* unless explicitly passed, and
> `run_in_background` exists and is undocumented. See `C3-RULE` below — this
> mismatch is a live bug, not a note.

**`C3-RULE` — how `updatedInput` must be built.** `updatedInput` replaces the
**entire** input object (`F.8`, `DEL.2`). Therefore the script MUST
shallow-copy the received `tool_input` and mutate only `prompt`:

```python
updated = dict(tool_input)          # every field, including unknown ones
updated["prompt"] = CONTRACT + "\n\n" + updated.get("prompt", "")
```

It MUST NOT enumerate known keys. Echoing a hardcoded
`{prompt, description, subagent_type, model}` — which is what `F.8` invites —
would **drop `run_in_background`** and **inject a `model` key that was never
set**, changing the semantics of a backgrounded delegation. Copy-and-mutate also
carries through any field the harness adds later.

**stdout when `subagent_type == "Plan"`:** exit 0 with

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": { "<every received key, verbatim>": "...", "prompt": "<contract>\n\n<original>" }
  }
}
```

No `permissionDecision` accompanies it (`DEL.3`).

**stdout otherwise:** empty, exit 0. Applies to `Explore` (`DEL.4`),
`spec-driven-developer` (`DEL.5`), and the default/`general-purpose` agent
(`DEL.8`).

---

## C4 — `.spec/EXEMPT` (agent-authored, gate-consumed)

Plain UTF-8 text. First non-empty line is the only line read:

```
Spec-exempt: <reason, at least 20 characters>
```

Honored only while `mtime` is within the freshness window (default 60 minutes)
(`GATE.5`). Untracked — this file is transient by design.

---

## C5 — `.spec/exemptions.log` (gate-authored, human-consumed)

Append-only, tab-separated, one record per honored exemption. **Tracked in
git** (`GATE.7`) and **not** removed by the `VCS.3` clearing step (`VCS.6`).

```
<ISO-8601 timestamp>\t<worktree basename>\t<file_path>\t<reason>
```

Deduplicated by `(reason, hour)` so a ten-file fix writes one record, not ten
(`GATE.6`).

---

## C6 — `.claude/settings.json` keys added

| Key | Value shape |
|---|---|
| `hooks.PreToolUse[]` | Two entries: `matcher: "Edit\|Write\|NotebookEdit"` and `matcher: "Agent"`, each `type: "command"`, exec form, **repo-relative** script path — confirmed to resolve against the worktree (`GATE.1a`, `research.md` §`F0.3`) |
| `hooks.PostToolUse[]` | Two entries: `matcher: "ExitPlanMode"` → `plan_context.py` (`C2`), and `matcher: "Bash"` → `bash_audit.py` (`C11`) |
| `permissions.defaultMode` | `"plan"` (`MODE.1`) |
| `plansDirectory` | `".spec/plans/"` (`MODE.3`), contingent on the `MODE.6` measurement |

`agent` is **not** added (`MODE.5`). Existing `permissions.allow`,
`permissions.deny`, and `respectGitignore` are unchanged.

---

## C7 — CI job `spec-artifacts-cleared`

Added to `.github/workflows/ci.yml`, which already triggers on both
`push: [master]` and `pull_request: [master]` — so one job serves as the
blocking PR check and the post-merge master guard (`VCS.2`).

| Property | Value |
|---|---|
| Job id | `spec-artifacts-cleared` |
| Fails when | `git ls-files .spec/features/` is non-empty |
| Checkout | `actions/checkout` **without** `sparse-checkout` — `git ls-files` needs the index |
| Required check | Yes, configured in GitHub branch protection |

This job is the only change to CI. No existing job's behavior is altered
(`X.5` as amended).

---

## C8 — `.claude/rules/spec-workflow.md`

| Property | Value |
|---|---|
| Frontmatter | **No `paths:` key** — its absence is what makes the rule load at launch at `CLAUDE.md` priority (`F.10`, `RULE.1`) |
| Contains | Routing contract, `.spec/EXEMPT` format (must match `C4` exactly), VS Code `initialPermissionMode` caveat, PR-ref recovery recipe |
| Does not contain | Commands, architecture, or anything restated from `AGENTS.md` (`RULE.5`) |

`CLAUDE.md` §"Spec-driven workflow" becomes a pointer at this file and retains
no contract text (`RULE.4`, `A19`).

---

## C9 — Execute context anchor (agent ↔ command)

Six paths, **byte-identical** in `.claude/agents/spec-driven-developer.md`
§Phase 4 and `.claude/commands/agentic-execute.md` (`FIX.1`, `A10`):

```
AGENTS.md
.spec/CONSTITUTION.md
.spec/ARCHITECTURE.md
.spec/TESTING.md
.spec/STATE.md
.spec/features/<name>/tasks.md
```

`.spec/STATE.md` is the one entry that may be absent; both files, plus
`agentic-specify.md:1` and `agentic-plan.md:1`, carry the clause *"if absent,
treat as: no work in flight"* (`FIX.3`).

---

## C10 — `spec-driven-developer` frontmatter

```yaml
tools: Read, Write, Edit, Bash, Grep, Glob, Skill, Agent
```

`Edit` and `Skill` make Phase 4 step 6 and Phase 5 step 4 executable; `Agent`
makes the multi-agent wave section a live path (`FIX.6`, `A12`). The section's
"serialize `STATE.md` writes" constraint remains prose that no tool enforces
and must be documented as such, not claimed as guaranteed.


---

## C11 — Harness → shell auditor (`PostToolUse`, `Bash`)

Closes `research.md` §`F0.11`. Observes; never blocks.

**stdin:** the `PostToolUse` envelope. Consumes `cwd` and `session_id` only.
`tool_input.command` is deliberately **not** parsed — command-string analysis is
the fragile approach this design rejects.

**Detection.** One `git status --porcelain --` restricted to the gated paths
yields the currently-dirty gated set. It is compared against the previous set
for this `session_id`, cached at
`$TMPDIR/spec-gate-<session_id>.json`. Only **newly** dirty paths are candidates,
so a path already dirty does not re-record on every later shell call.

**Suppression.** Nothing is recorded when a valid `tasks.md` exists (the
workflow is being followed) or when a fresh `.spec/EXEMPT` exists (the bypass is
already declared and logged by `C1`).

**Ledger record** — same four tab-separated fields as `C5`, distinguished by its
reason prefix, deduplicated by `(file_path, hour)`:

```
<ISO-8601 timestamp>\t<worktree basename>\t<changed path>\tshell-write: no tasks.md and no .spec/EXEMPT
```

**stdout:** always empty. **Exit:** always 0. This hook has no decision
authority and must never acquire one — `INJ.6`'s reasoning applies verbatim.
