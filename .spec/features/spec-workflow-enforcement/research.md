# Research: harness contract probe (task 0.1)

**Date:** 2026-08-29 · **Method:** temporary logging hook registered in
`.claude/settings.json`, real tool calls triggered, registration reverted via
`git checkout -- .claude/settings.json`.

Resolves `RK1` and `RK2` from [`plan.md`](plan.md). Three of the four questions
in task `0.1` are answered from captured evidence; the fourth is answered as a
negative.

---

## F0.1 — `tool_input.file_path` is confirmed

`contracts.md` §`C1` marked this **[assumed]**. It is now **[doc]**, observed
directly for both `Write` and `Edit`. The value is an **absolute** path, so the
validator must not assume it is relative to `cwd`.

### Verbatim `PreToolUse` / `Edit` payload

```json
{
  "session_id": "<session_id>",
  "transcript_path": "<transcript_path>",
  "cwd": "/home/viltohmyst/code/raicing-ai/functualize/.worktrees/spec-workflow-enforcement-intent",
  "prompt_id": "<prompt_id>",
  "permission_mode": "auto",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/tmp/claude-1000/-home-viltohmyst-code-raicing-ai-functualize--worktrees-spec-workflow-enforcement-intent/005bca62-f631-4031-a944-e2ff31baf30a/scratchpad/probe/target.txt",
    "old_string": "probe target line one",
    "new_string": "probe target line one edited",
    "replace_all": false
  },
  "tool_use_id": "<tool_use_id>"
}
```

### Verbatim `PreToolUse` / `Write` payload

```json
{
  "session_id": "<session_id>",
  "transcript_path": "<transcript_path>",
  "cwd": "/home/viltohmyst/code/raicing-ai/functualize/.worktrees/spec-workflow-enforcement-intent",
  "prompt_id": "<prompt_id>",
  "permission_mode": "auto",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/tmp/claude-1000/-home-viltohmyst-code-raicing-ai-functualize--worktrees-spec-workflow-enforcement-intent/005bca62-f631-4031-a944-e2ff31baf30a/scratchpad/probe/target.txt",
    "content": "<content>"
  },
  "tool_use_id": "<tool_use_id>"
}
```

Fields present that `contracts.md` did not anticipate: `effort`,
`permission_mode`, `prompt_id`, `tool_use_id`. None are needed by the current
design. `permission_mode` is noted as a possible future signal — it would let a
hook know whether the session is in plan mode — but nothing depends on it.

## F0.2 — `cwd` is the worktree root

Observed `cwd` =
`/home/viltohmyst/code/raicing-ai/functualize/.worktrees/spec-workflow-enforcement-intent`,
which is this worktree, **not** the origin checkout. `X.2` and `GATE.12` are
sound as written.

## F0.3 — A relative hook `command` resolves against the worktree

Two entries were registered simultaneously for the same matcher: one with an
absolute script path, one with `.claude/hooks/_probe.py`. **Both fired**, and
both reported `process_cwd` equal to the worktree root.

`GATE.1a` is therefore correct and implementable: a repo-relative command runs
the worktree's own copy of the validator, and `RK2`'s fallback to
`${CLAUDE_PROJECT_DIR}` is **not** needed.

## F0.4 — `MultiEdit` does not exist in this build; `NotebookEdit` does

No `MultiEdit` tool is available in this session. Including it in the matcher is
harmless but dead.

**`NotebookEdit` is a live edit tool that the planned matcher does not cover.**
It writes `.ipynb` files and would bypass the gate entirely. Current exposure is
zero — `find . -name '*.ipynb'` returns **0** repo-wide — but a future notebook
under `src/functualize/` would be silently ungated.

**Decision:** the matcher becomes `Edit|Write|NotebookEdit`. `MultiEdit` is
dropped as dead. This changes `contracts.md` §`C1`, §`C6` and task `2.1`.

`NotebookEdit`'s payload was not captured; its path field is assumed to be
`file_path` by symmetry, and `GATE.2`'s tolerance covers a wrong guess by
failing open.

## F0.5 — Hook registration hot-reloads mid-session

Editing `.claude/settings.json` took effect on the very next tool call, with no
session restart. This matters for Wave 5: the verification checklist can be run
without restarting, and a broken registration is correspondingly fast to
observe *and* to undo.

## F0.6 — NOT captured: `ExitPlanMode` and `Agent`

Neither payload was obtained.

- **`PostToolUse` / `ExitPlanMode`** requires entering plan mode and having a
  plan approved, which is user-driven and would interrupt the Execute phase.
- **`PreToolUse` / `Agent`** requires spawning a subagent, which the operator
  has instructed not to do unprompted.

Both consumers (`2.2`, `2.3`) fail open by design, and their shapes are
documented by `F.7` and `F.8`. Task `0.1`'s scope is therefore **narrowed** to
the `PreToolUse` edit-family contract, and the remainder is carried forward as
task `0.2` — declared explicitly per `CONSTITUTION.md` §*Acceptance Gates*
("a gate that is weakened to make a task pass must say so explicitly").

---

## Consequences for other artifacts

| Artifact | Change | Owning task |
|---|---|---|
| `contracts.md` §`C1` | `file_path` **[assumed]** → **[doc]**; note absolute | `0.1` |
| `contracts.md` §`C1`, §`C6` | matcher → `Edit\|Write\|NotebookEdit` | `0.1` |
| `plan.md` `RK2` | resolved — relative paths work; no fallback needed | `0.1` |
| `tasks.md` `2.1` | add a `NotebookEdit` acceptance case | `0.1` |
| `tasks.md` | new task `0.2` for the two uncaptured payloads | `0.1` |

---

# Addendum: task 0.2 — `ExitPlanMode` and `Agent` payloads

**Date:** 2026-08-29. Captured by re-registering the probe (hot-reload per
`F0.5`), dispatching one `Explore` agent, and having a real plan approved.
Registration reverted with `git checkout -- .claude/settings.json`.

## F0.7 — `tool_response.plan` confirmed (`F.7` holds)

```json
{
  "session_id": "<session_id>",
  "transcript_path": "<transcript_path>",
  "cwd": "/home/viltohmyst/code/raicing-ai/functualize/.worktrees/spec-workflow-enforcement-intent",
  "prompt_id": "<prompt_id>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "ExitPlanMode",
  "tool_input": {},
  "tool_response": {
    "plan": "<3588 chars of plan markdown>",
    "isAgent": false,
    "filePath": "/home/viltohmyst/.claude/plans/mighty-sauteeing-deer.md",
    "hasTaskTool": true
  },
  "tool_use_id": "<tool_use_id>",
  "duration_ms": 19
}
```

`tool_response` carries `plan` (3588 chars, the full markdown), `filePath`, and
the two internal flags `F.7` alluded to: `hasTaskTool`, `isAgent`. `INJ.2`'s
instruction to read `tool_response.plan` rather than re-reading `filePath` is
correct as written.

`duration_ms` is present on `PostToolUse` and absent on `PreToolUse`.

## F0.8 — `tool_input` was **empty** on `ExitPlanMode`; `F.4`'s injection claim did not reproduce

`F.4` states that Claude Code "injects the plan content and file path before
passing the input to hooks", giving `tool_input.plan` and
`tool_input.planFilePath`. **Observed `tool_input` is `{}`** — no `plan`, no
`planFilePath`. The plan arrived *only* via `tool_response`.

This is a `PostToolUse` observation and does not strictly disprove `F.4`, which
describes `PreToolUse`. But it is evidence that the injection may not happen in
this build, and the original Layer 3 design read `tool_input.plan` as its **sole
input**. Had `D0` not moved the gate to `Edit`/`Write`, `GATE.2` would have been
reading a field that may never be populated — and, per `GATE.13`, would have
failed open on every plan, enforcing nothing while appearing to work.

**No action needed** — nothing in the current design reads `tool_input` on
`ExitPlanMode`. Recorded because it retroactively strengthens `R.7`.

## F0.9 — `Agent` `tool_input` does **not** match `F.8`, and the mismatch is a live bug

```json
{
  "session_id": "<session_id>",
  "transcript_path": "<transcript_path>",
  "cwd": "/home/viltohmyst/code/raicing-ai/functualize/.worktrees/spec-workflow-enforcement-intent",
  "prompt_id": "<prompt_id>",
  "permission_mode": "auto",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Probe agent payload",
    "prompt": "<prompt text>",
    "subagent_type": "Explore",
    "run_in_background": false
  },
  "tool_use_id": "<tool_use_id>"
}
```

`F.8` documents `tool_input` as `{prompt, description, subagent_type, model}`.
**Observed keys: `description`, `prompt`, `run_in_background`, `subagent_type`.**

Two differences, both consequential:

- **`model` is absent** when not explicitly passed. It is not `null`; the key
  does not exist.
- **`run_in_background` is present** and is documented nowhere in `F.8`.

`DEL.2` says `updatedInput` "replaces the entire input object, so include
unchanged fields alongside modified ones". A script that echoes back a
hardcoded `{prompt, description, subagent_type, model}` — exactly what `F.8`
invites — would **silently drop `run_in_background`** and **inject a `model` key
that was never set**. On a backgrounded delegation that changes the call's
semantics.

**Decision:** `agent_contract.py` must build `updatedInput` by **shallow-copying
the received `tool_input` and mutating only `prompt`**. It must never enumerate
known keys. Any future field the harness adds is then carried through
untouched. This changes `contracts.md` §`C3` and task `2.3`.

## F0.10 — default `plansDirectory` confirmed outside the worktree

The approved plan landed at `/home/viltohmyst/.claude/plans/mighty-sauteeing-deer.md`
— the documented `~/.claude/plans` default (`F.18`), outside the repository
entirely. This is the baseline `MODE.6` will measure `plansDirectory` against.

---

## Consequences (addendum)

| Artifact | Change | Owning task |
|---|---|---|
| `contracts.md` §`C2` | `tool_response` keys confirmed, `duration_ms` noted | `0.2` |
| `contracts.md` §`C3` | key list corrected; copy-and-mutate mandated | `0.2` |
| `tasks.md` `2.3` | acceptance now requires field preservation | `0.2` |
| intent `R.7` | strengthened by `F0.8` | — |

---

# Addendum: task 2.1 — `Bash` is an ungated write path

**Date:** 2026-08-29. Surfaced while testing `RK8`'s symlink cases.

## F0.11 — the gate covers three tools; the shell is not one of them

`GATE.3` scopes the gate to `Edit`, `Write`, and `NotebookEdit`. Nothing stops
the same write arriving through `Bash`:

```
echo 'x = 1' > src/functualize/anything.py
sed -i 's/old/new/' src/functualize/cli.py
python3 - <<'EOF' ... EOF
cat > src/functualize/thing.py
```

None of these is a `PreToolUse` `Edit`/`Write`/`NotebookEdit` event, so the
validator never runs. **`B1`'s guarantee is only as strong as the tool the agent
happens to choose.**

This is not theoretical. This very session operates under a harness instruction
to *prefer* `Bash` for file edits ("make file changes with sed, heredocs, or
short scripts, rather than using the dedicated Edit or Write tools"). Under that
instruction the gate would essentially never fire.

It also re-frames the `RK8` symlink result. A symlink planted inside
`src/functualize/` pointing outward is correctly **not** gated, because its
`realpath` leaves the tree — and creating that symlink is itself a `Bash`
operation, so the gate never sees it either.

## Options

| Option | Cost |
|---|---|
| **(a) Add `Bash` to the matcher and inspect the command string** | Must recognise redirection, `sed -i`, `tee`, `cp`, `mv`, heredocs, `python -c`, and anything invoking a script. Fragile and easy to fool; high false-positive risk on read-only commands |
| **(b) `permissions.deny` entries for the obvious shapes** | Declarative and cheap, e.g. `Bash(sed -i:*)`. Same enumeration problem, but failures are visible as permission prompts rather than silent passes |
| **(c) Accept and document** | The gate then targets *inadvertent* ad-hoc editing, not a determined bypass — consistent with `spec.md`'s stated non-goal ("preventing a determined operator from bypassing the workflow"), but `B1` overstates what is delivered |
| **(d) A `PostToolUse` detector on `Bash`** | Cannot block, but could append to `.spec/exemptions.log` when a gated path's mtime changed across a `Bash` call. Turns a silent bypass into a recorded one, matching `D1`'s philosophy |

**Recommendation: (c) + (d).** Blocking the shell reliably is not achievable;
recording that it happened is, and it is the same trade `D1` already accepted
for `.spec/EXEMPT`. `spec.md` §`B1` needs a sentence stating the boundary
honestly.

**Not implemented.** This is a scope change and needs an explicit decision.
