# Tasks: `spec-workflow-enforcement`

**Spec:** [`spec.md`](spec.md) · **Plan:** [`plan.md`](plan.md) · **Contracts:** [`contracts.md`](contracts.md)

Acceptance gates were **run at authoring time (2026-08-29)** and `[F]` equals
each gate's hit set, per the agent's *Writing acceptance criteria* rule. Hit
counts recorded below are the authoring-time values; drift between these and
execution time is itself a signal.

---

## Wave 0 — Confirm the assumed harness contract

### [x] 0.1 Capture real hook payloads and confirm relative script resolution

Register a temporary logging hook that writes its raw stdin to a file, trigger
one `Edit`, one `ExitPlanMode`, and one `Agent` delegation, then remove the
temporary registration. Record the observed envelopes in `research.md`.

Resolves `RK1` and `RK2`. Confirm specifically:

- the field carrying the target path for `Edit`, `Write`, and `MultiEdit`
  (`contracts.md` §`C1` marks it `[assumed]`)
- whether `MultiEdit` exists as a distinct tool name in this build
- whether a **relative** `command` in a hook entry resolves against the worktree
  cwd or against the origin project root (`GATE.1a`)
- that `cwd` is the worktree root, not the origin root (`F.13`, `X.2`)

**[F]** `.spec/features/spec-workflow-enforcement/research.md` (new),
`.claude/settings.json` (temporary, reverted within this task)

**Acceptance:** `research.md` contains a verbatim captured payload for each of
the three events, and states the resolved answer for each of the four questions
above. `python3 -c "import json;json.load(open('.claude/settings.json'))"` exits
0 and the file's top-level keys are unchanged from `['$schema', 'permissions',
'respectGitignore']` (authoring-time value, 3 keys).

**Result (2026-08-29):** all four questions answered — see
[`research.md`](research.md). `file_path` confirmed (absolute) and retagged
`[doc]`; `cwd` is the worktree root; a **relative** command resolves against the
worktree, so `RK2` needs no fallback; `MultiEdit` does not exist in this build
but **`NotebookEdit` does and would have bypassed the gate**, so the matcher
becomes `Edit|Write|NotebookEdit`.

**Scope narrowed, declared per `CONSTITUTION.md` §Acceptance Gates.** The
original gate required a captured payload for *three* events. Only the
`PreToolUse` edit-family payload was obtained: `ExitPlanMode` needs a
user-approved plan, and `Agent` needs an unprompted subagent spawn. Both
remaining payloads move to `0.2`; both their consumers fail open, and `F.7` /
`F.8` document their shapes.

**Cleanup owed:** `.claude/hooks/_probe.py` is untracked and unreferenced —
`rm` is not permitted to this session, so it must be deleted manually.

---

## Wave 1 — Artifacts, workflow docs, and CI

All six tasks touch disjoint file sets and may run in parallel. The two that add
the clearing step (`1.4`, `1.5`) copy the verbatim block fixed in `plan.md`
§"Shared constants" rather than each inventing wording.

### [x] 1.1 Track `.spec/features/`, drop dead ignores, add `.spec/plans/`

**[F]** `.gitignore`

Delete `.spec/features/`, `.spec/PROJECT.md`, `.spec/REQUIREMENTS.md`,
`.spec/ROADMAP.md`. Add `.spec/plans/`. Keep `archive/`,
`scrutiny-reports/`, `proposals/`, `.agentic-coding`, `STATE.md`
(`VCS.1`, `VCS.1a`, `VCS.5`, `FIX.3`).

**Acceptance:** `grep -c '^\.spec/' .gitignore` returns **6** (authoring-time
value: 9). `git status --porcelain .spec/features/` is non-empty. `git
check-ignore .spec/plans .spec/STATE.md` lists both; `git check-ignore
.spec/features` exits 1. Satisfies `A13`, `A16`.

### [x] 1.2 Create the exemption ledger

**[F]** `.spec/exemptions.log`

Header comment line explaining the format from `contracts.md` §`C5`, then empty.
Must be tracked (`VCS.6`, `GATE.7`).

**Acceptance:** `git ls-files .spec/exemptions.log | wc -l` returns **1**
(authoring-time value: 0).

### [x] 1.3 Add the `spec-artifacts-cleared` CI job

**[F]** `.github/workflows/ci.yml`

Per `contracts.md` §`C7`. `actions/checkout` without `sparse-checkout`. No
existing job is modified.

**Acceptance:** parsing the file with `yaml.safe_load` yields **6** job ids
including `spec-artifacts-cleared` (authoring-time value: 5 —
`lint`, `lint-imports`, `typecheck`, `test-fast`, `test-full`), and those five
ids are unchanged. The job's script fails on a tree where
`git ls-files .spec/features/` is non-empty — verify by running the script body
locally in the current tree, where it must **fail** (this feature's own
artifacts are present).

### [x] 1.4 Make the agent definition and Execute command executable

**[F]** `.claude/agents/spec-driven-developer.md`,
`.claude/commands/agentic-execute.md`

One task because every `PROJECT.md`/`ROADMAP`/`REQUIREMENTS`/`.agentic-coding`
hit in the agent lives in a single file, and the anchor list must be
byte-identical across both (`contracts.md` §`C9`).

- `tools:` → `Read, Write, Edit, Bash, Grep, Glob, Skill, Agent` (`FIX.6`)
- anchor → the six paths in `C9`, identical in both files (`FIX.1`, `FIX.2`)
- Phase 0 branch → `.spec/CONSTITUTION.md` (`FIX.4`)
- Phase 5 `ROADMAP.md` → `.spec/STATUS.md` (`FIX.5`)
- `.spec/ Structure` block → remove `PROJECT.md`, `REQUIREMENTS.md`,
  `ROADMAP.md`; add `contracts.md`
- Phase 1 step 3 and Phase 4 step 9 → drop `REQUIREMENTS.md`
- `STATE.md` absence clause (`FIX.3`)
- clearing step from `plan.md` §"Shared constants" (`VCS.3`)
- multi-agent section: note that `STATE.md` serialization is prose, not enforced

**Acceptance:** `grep -rn 'PROJECT\.md\|ROADMAP\|REQUIREMENTS\|agentic-coding'
.claude/agents/ .claude/commands/agentic-execute.md` returns **0** hits
(authoring-time values: `PROJECT.md` 4 hits/2 files, `ROADMAP` 4/2,
`REQUIREMENTS` 4/1, `.agentic-coding` 4/1 — note `ROADMAP` and `REQUIREMENTS`
hits in `agentic-verify.md` belong to `1.5`, so anchor the path as written).
`grep -n '^tools:' .claude/agents/spec-driven-developer.md` shows all eight
tools. The six anchor lines are byte-identical between the two files (`diff`
of the extracted blocks is empty). Satisfies `A10`, `A12`, part of `A11`.

### [x] 1.5 Retarget Verify to `STATUS.md` and add the clearing step

**[F]** `.claude/commands/agentic-verify.md`

`ROADMAP.md` → `.spec/STATUS.md` (`FIX.5`); append the verbatim clearing block
from `plan.md` (`VCS.3`). Step 2b's `contracts.md` walk is unchanged — that file
is now tracked, which is what makes the walk auditable.

**Acceptance:** `grep -c 'ROADMAP' .claude/commands/agentic-verify.md` returns
**0** (authoring-time value: 1). The clearing block matches `plan.md`'s verbatim
text.

### [x] 1.7 Record the `plan.md` carve-out in `CONSTITUTION.md`

**[F]** `.spec/CONSTITUTION.md`

§Forbidden Patterns bans committing "a proposal, **plan**, scrutiny, or review
report", naming `.spec/proposals/` and `.spec/scrutiny-reports/`. `D4` commits
`.spec/features/<name>/plan.md`, which the letter of that rule forbids. The
rule's stated reason — "goes stale the day it lands and then contradicts the
code" — does not apply, because `VCS.2` guarantees master carries none of it.

Amend the pattern to scope it to the two named gitignored directories and to
state the `.spec/features/` exception with its `VCS.2` precondition. Approved by
the user 2026-08-29; `CONSTITUTION.md` requires explicit approval to violate, so
this records the approval rather than assuming it.

**Acceptance:** `grep -c 'features/' .spec/CONSTITUTION.md` returns ≥1
(authoring-time value: 0), and the amended clause names `VCS.2` as the
precondition.

### [x] 1.6 Tolerate a missing `STATE.md` in the three read sites

**[F]** `.claude/commands/agentic-specify.md`, `.claude/commands/agentic-plan.md`,
`.claude/commands/agentic-explore.md`

Each opens with `1. Read .spec/STATE.md`. Add the `FIX.3` clause: *if absent,
treat as: no work in flight*.

**Acceptance:** `grep -c 'no work in flight' .claude/commands/agentic-specify.md
.claude/commands/agentic-plan.md .claude/commands/agentic-explore.md` returns 1
for each (authoring-time value: 0 for each; `STATE.md` read sites measured at 3
in these files, 4 total in `.claude/commands/` including `agentic-execute.md`
which `1.4` covers). Completes `A11`.

---

## Wave 2 — Hook scripts

Independent of Wave 1; three new files, disjoint. Each must be runnable
standalone against a payload captured in `0.1`.

### [x] 0.2 Capture the `ExitPlanMode` and `Agent` payloads

Carried forward from `0.1`. Blocks `2.2` and `2.3` only — `2.1` is unblocked.

**[F]** `.spec/features/spec-workflow-enforcement/research.md`,
`.claude/settings.json` (temporary, reverted)

Re-register the probe (`research.md` §`F0.5` confirms hot-reload, so no restart
is needed), then have a plan approved and one subagent dispatched. Both actions
need the operator, so this task is **operator-gated**, not agent-completable.

**Acceptance:** `research.md` gains a verbatim `PostToolUse`/`ExitPlanMode`
payload confirming `tool_response.plan` (`F.7`) and a verbatim
`PreToolUse`/`Agent` payload confirming the four `tool_input` keys (`F.8`).
`git status --porcelain .claude/settings.json` is empty afterwards.

**Result (2026-08-29):** both captured; see `research.md` §`F0.7`–`F0.10`.
`tool_response.plan` confirmed. **`F.8`'s key list is wrong** — `model` is absent
unless passed, and undocumented `run_in_background` is present, so the acceptance
"confirming the four `tool_input` keys" is recorded as **failed as written and
corrected**: the observed set is `{description, prompt, run_in_background,
subagent_type}`. `contracts.md` §`C3` now mandates copy-and-mutate. Settings
reverted; `git status` clean.

### [x] 2.1 Write the write gate

**[F]** `.claude/hooks/spec_gate.py`

Implements `contracts.md` §`C1` and `GATE.2`–`GATE.15`. Path containment via
resolved real paths and `os.path.commonpath`, never string prefix (`RK8`).
Wave-graph parsing per `plan.md`. Exemption honoring and ledger append per `C4`,
`C5`.

**Acceptance:** run standalone against captured payloads —
- gated path + no `.spec/features/` → stdout is valid JSON with
  `permissionDecision: "deny"`, reason names `/agentic-specify` and
  `.spec/EXEMPT`; exit 0 (`A1`)
- `tests/`, `plugins/*/tests/`, `plugins/conftest.py`, a `pyproject.toml`,
  `docs/` → empty stdout, exit 0 (`A2`)
- gated path + valid `tasks.md` → empty stdout, exit 0 (`A3`)
- `src/functualize_extra/foo.py` and a symlink into `src/functualize/` →
  correct decision, proving containment is not a prefix test (`RK8`)
- a `NotebookEdit` payload targeting `src/functualize/x.ipynb` → deny.
  `research.md` §`F0.4`: current repo-wide `.ipynb` count is **0**, so this is
  defense against future exposure, not a present hole
- fresh `.spec/EXEMPT` with a ≥20-char reason → pass, and one record appended to
  `.spec/exemptions.log` (`A4`); the same file aged past the window → deny (`A5`)
- malformed stdin, absent `file_path`, unreadable `.spec/` → exit 0, empty
  stdout (`A6`)
- `grep -c 'import' .claude/hooks/spec_gate.py` shows stdlib only; no
  `functualize` import (`A18`)
- the three deny reasons are textually distinct (`GATE.11`)

### [x] 2.2 Write the plan-context injector

**[F]** `.claude/hooks/plan_context.py`

Implements `C2`, `INJ.2`–`INJ.7`. Reads `tool_response.plan`.

**Acceptance:** against a captured `ExitPlanMode` payload, stdout is valid JSON
carrying `hookSpecificOutput.additionalContext`, length < 10000, containing no
imperative second-person framing (`INJ.4`) and no `decision` key (`INJ.6`).
Malformed stdin → exit 0. Satisfies `A8` at the script level.

### [x] 2.3 Write the delegation rewriter

**[F]** `.claude/hooks/agent_contract.py`

Implements `C3`, `DEL.2`–`DEL.8`.

**Acceptance:** built by copy-and-mutate per `contracts.md` §`C3-RULE`, never by
enumerating keys. Against the payload captured in `0.2`:
- `subagent_type: "Plan"` → `updatedInput` contains **every key present in the
  input**, `run_in_background` among them, with `subagent_type` still `"Plan"`
  and the contract prepended to `prompt`; no `permissionDecision` key
- a synthetic input carrying an **unknown extra key** → that key survives
  verbatim in `updatedInput` (proves copy-and-mutate, not enumeration)
- an input **without** `model` → `updatedInput` also has no `model` key
- `"Explore"`, `"spec-driven-developer"`, default agent → empty stdout, exit 0
- malformed stdin → exit 0

Satisfies `A9`.

---

### [x] 2.4 Write the shell auditor

**[F]** `.claude/hooks/bash_audit.py`

Implements `contracts.md` §`C11`. Standalone, stdlib only, no shared module with
`spec_gate.py` (`plan.md` §"Why three separate scripts"). Never blocks.

**Acceptance:** against synthetic trees —
- gated path dirty, no `tasks.md`, no `EXEMPT` → one ledger record whose reason
  begins `shell-write:`; stdout empty; exit 0 (`A21`)
- same path dirty on a **second** invocation → no second record (session cache
  suppresses already-seen paths)
- valid `tasks.md` present → no record (`A22`)
- fresh `.spec/EXEMPT` present → no record (`A22`)
- only `tests/` dirty → no record
- not a git repository, `git` absent, unreadable cache → exit 0, empty stdout,
  no crash
- `grep -c 'command' .claude/hooks/bash_audit.py` → 0 occurrences of reading
  `tool_input.command`, proving detection is not command-string parsing

## Wave 3 — Registration and the single contract source

### [x] 3.1 Register the hooks and plan-mode settings

**[F]** `.claude/settings.json`

Per `contracts.md` §`C6`. Script paths relative or `${CLAUDE_PROJECT_DIR}`-based
according to `0.1`'s finding (`RK2`). `agent` is **not** added (`MODE.5`).

**Acceptance:** `python3 -c "import json;d=json.load(open('.claude/settings.json'));
print(sorted(d))"` yields `['$schema', 'hooks', 'permissions', 'plansDirectory',
'respectGitignore']` (authoring-time value: 3 keys) and `'agent' not in d`.
Existing `permissions.allow` (18 entries) and `permissions.deny` (5 entries) are
unchanged. `/hooks` lists all three entries under Project Settings (`A17`).

### [x] 3.2 Write the rule file

**[F]** `.claude/rules/spec-workflow.md`

Per `contracts.md` §`C8`. No `paths:` frontmatter (`RULE.1`). Contains the
routing contract, the `.spec/EXEMPT` format matching `C4` exactly, the VS Code
`initialPermissionMode` caveat (`MODE.2`), and the PR-ref recovery recipe
(`VCS.4`). References `AGENTS.md`, never restates it (`RULE.5`).

**Acceptance:** the file has no `paths:` key in frontmatter. The `.spec/EXEMPT`
format block is byte-identical to `contracts.md` §`C4`. `grep -c 'uv run'
.claude/rules/spec-workflow.md` returns 0, proving commands were referenced
rather than copied from `AGENTS.md`.

---

## Wave 4 — Collapse the duplicate contract text

### [x] 4.1 Reduce `CLAUDE.md` to a pointer

**[F]** `CLAUDE.md`

Replace the "Spec-driven workflow" section body with a pointer at
`.claude/rules/spec-workflow.md` (`RULE.4`).

**Acceptance:** the section contains no phase list, no key-file list, and no
`--agent` invocation (authoring-time value: 15 lines at 13–27 carrying all
three). `grep -c 'agentic-execute\|STATE\.md\|CONSTITUTION' CLAUDE.md` returns
0. Satisfies `A19`.

### [x] 4.2 Document the VS Code plan-mode caveat

**[F]** `AGENTS.md`

Note that `permissions.defaultMode` is ignored by the VS Code extension and that
contributors must set `claudeCode.initialPermissionMode: "plan"` in their own VS
Code user settings (`MODE.2`, `F.11`).

**Acceptance:** `grep -c 'initialPermissionMode' AGENTS.md` returns 1.

**Scope widened, declared per `CONSTITUTION.md` §Acceptance Gates.** `AGENTS.md`
§Workflow carried the same dead file list as the agent definition —
`PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, `.agentic-coding` — which `1.4`'s
gate missed because it searched only `.claude/`. Repaired here rather than left
for a later pass. The widened gate
`grep -rn 'PROJECT\.md\|REQUIREMENTS\.md\|ROADMAP\.md\|agentic-coding' AGENTS.md CLAUDE.md README.md`
returns **0** (was 4 in `AGENTS.md`).

---

## Wave 5 — Verification checkpoint

### [x] 5.1 Run the intent's verification checklist end to end `[verify-e2e:TARGETED]`

**[F]** none — this task changes no files. It produces a report and, if
`MODE.6` fails, one revert.

Execute steps 1–10 of the intent's *How to verify the hooks actually fire*,
plus:

- `MODE.6`: write a plan from **this** worktree and confirm the file lands here,
  not in the origin checkout. If it lands wrong, revert `plansDirectory` from
  `.claude/settings.json` and record the measurement in the intent (`RK3`).
- `RK4`: measure gate latency on a single `Edit`; confirm no subprocess and no
  `git` call in the hot path.
- `RK6`: **manual, outside the repo** — mark `spec-artifacts-cleared` as a
  required check in GitHub branch protection. Until this is done, `A14` cannot
  pass and `VCS.2` is advisory. Confirm explicitly with the user.
- `A7`: repeat the deny / pass / exempt / fail-open cases from a **second**
  worktree.
- `A20`: `uv run pytest`, `uv run ruff check src/ tests/`, `uv run mypy src/`,
  `uv run lint-imports` — same results as before the change.
- `A15`: after merge, `git ls-files .spec/features/` on master returns empty.

**Acceptance:** every criterion `A1`–`A22` in `spec.md` is marked pass or is
recorded with the reason it was not reachable.

**Result (2026-08-29):** see [`verification.md`](verification.md). **20 of 22
PASS**, two deferred to merge (`A14`, `A15`). `A17` and `MODE.6` were closed by
the operator on 2026-08-29 — `plansDirectory` resolves to the worktree and is
kept. `A1` and `A6` were verified **live** against the real harness, not
only standalone.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1"] },
    { "id": 1, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "0.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["3.1", "3.2"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["5.1"] }
  ]
}
```

**Revised after `0.1`.** Wave 1 carries the artifact repair, the operator-gated
payload capture (`0.2`), and the one hook script that `0.1` fully unblocked
(`2.1`) — nine tasks over disjoint files, none consuming another's output.
`2.2` and `2.3` moved to Wave 2 because they consume `0.2`'s payloads. `3.1`
consumes `2.1`–`2.3`; `4.1` consumes `3.2`. `5.1` is a checkpoint and holds its
own wave.

`0.2` is **operator-gated**: it needs a plan approved and a subagent dispatched.
Wave 1 cannot close until the operator performs those two actions.
