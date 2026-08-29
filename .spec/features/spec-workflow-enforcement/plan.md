# Plan: `spec-workflow-enforcement`

**Spec:** [`spec.md`](spec.md) · **Contracts:** [`contracts.md`](contracts.md)
**Intent (normative assertions):** [`../../shape-intents/spec-workflow-enforcement.md`](../../shape-intents/spec-workflow-enforcement.md)

---

## Technical approach

Three standalone Python 3 scripts under `.claude/hooks/`, registered in
`.claude/settings.json`, plus a documentation and version-control repair wave
that must land first because the gate validates against `.spec/` artifacts.

### Why three separate scripts and no shared module

Each script duplicates roughly fifteen lines of "read stdin, parse JSON, fail
open". That duplication is deliberate.

A shared `_common.py` would have to be imported by a script the harness invokes
**by path**, not as a package. That means `sys.path` manipulation in every
script, and an import that fails silently in exactly the conditions the fail-open
rule exists for — a partial checkout, a permissions problem, a worktree where
the relative path resolves elsewhere. `X.1` requires that a broken validator
degrade to today's behavior; an `ImportError` at module scope happens *before*
any `try` block can catch it and exit 0. Fifteen duplicated lines that cannot
fail are worth more than one shared module that can.

### Interpreter and dependency posture

`#!/usr/bin/env python3`, standard library only (`json`, `os`, `sys`, `re`,
`time`, `pathlib`). No `functualize` import, no venv assumption (`GATE.14`,
`A18`). The scripts must run in a clean clone before `uv sync` has ever been
executed.

### The fail-open envelope

Every script has the same outer shape: one `try` wrapping all logic, a bare
`except` that swallows everything, and `sys.exit(0)` as the only exit path.
Exit code `2` is never produced — it routes as `deny` with stderr as the reason
(`F.5`), so a crash would block every write in the repository (`GATE.13`, `A6`).

### Wave-graph parsing (`GATE.4`)

Locate the `## Task Dependency Graph` heading, take the first fenced ```json
block after it, `json.loads` it, and require `waves` to be a non-empty list of
objects each carrying `id` and `tasks`. Any failure at any step is a
non-conforming `tasks.md`, not a crash.

### Path scoping (`GATE.3`)

`file_path` is resolved to an absolute path, then tested for containment under
`<cwd>/src/functualize/` or matched against `<cwd>/plugins/*/src/`. Containment
is checked with `os.path.commonpath` against resolved real paths, not string
prefixes — `src/functualize_extra/` must not match `src/functualize/`, and a
symlink must not smuggle a write past the check.

---

## Files to change

### New

| Path | Purpose | Contract |
|---|---|---|
| `.claude/hooks/spec_gate.py` | The write gate | `C1` |
| `.claude/hooks/plan_context.py` | Execution-contract injection | `C2` |
| `.claude/hooks/agent_contract.py` | `Plan` delegation rewrite | `C3` |
| `.claude/rules/spec-workflow.md` | The single contract source | `C8` |
| `.spec/exemptions.log` | Bypass ledger | `C5` |

### Modified

| Path | Change | Measured today |
|---|---|---|
| `.claude/settings.json` | `hooks`, `permissions.defaultMode`, `plansDirectory` | 3 top-level keys: `$schema`, `permissions`, `respectGitignore` |
| `.claude/agents/spec-driven-developer.md` | anchor, Phase 0, Phase 5, structure block, `tools:`, clearing step | `PROJECT.md`×3, `ROADMAP`×3, `REQUIREMENTS`×4, `.agentic-coding`×4 |
| `.claude/commands/agentic-execute.md` | anchor list, `STATE.md` clause | `PROJECT.md`×1, `STATE.md`×3 |
| `.claude/commands/agentic-verify.md` | `ROADMAP`→`STATUS`, clearing step | `ROADMAP`×1, `STATE.md`×1 |
| `.claude/commands/agentic-specify.md` | `STATE.md` clause | `STATE.md`×1 |
| `.claude/commands/agentic-plan.md` | `STATE.md` clause | `STATE.md`×1 |
| `.claude/commands/agentic-explore.md` | `STATE.md` clause | `STATE.md`×1 |
| `.gitignore` | drop `features/`, drop 3 dead files, add `plans/` | 9 `.spec/` lines at 13–21 |
| `.github/workflows/ci.yml` | one new job | 5 jobs: `lint`, `lint-imports`, `typecheck`, `test-fast`, `test-full` |
| `CLAUDE.md` | contract → pointer | 15 lines at 13–27 |
| `AGENTS.md` | VS Code `initialPermissionMode` note | — |

**Not touched:** `src/functualize/`, `plugins/*/src/`, `tests/`, any
`pyproject.toml` (`X.5`, `A20`).

---

## Shared constants defined here, not discovered per task

Two tasks in Wave 1 each add the `VCS.3` clearing step to a different file. To
keep that from being shared mutable state across a parallel wave, the exact text
is fixed **here** and both tasks copy it verbatim:

```
N. Migrate what survives — the decision to `.spec/STATUS.md` or
   `contributor/adr/`, any working rule to `contributor/guides/`.
N+1. `git rm -r .spec/features/<name>` — the required `spec-artifacts-cleared`
   check blocks the merge until this lands. The full artifacts stay recoverable
   from the pull request: `git fetch origin refs/pull/<N>/head`.
```

Likewise the six-line Execute anchor is fixed by `contracts.md` §`C9` and is
copied byte-identically into both files that carry it.

---

## Dependencies and ordering

```
W0  probe payloads ────────────────┐
                                   ▼
W1  artifacts + docs + CI      W2  hook scripts
        │                           │
        └─────────────┬─────────────┘
                      ▼
                W3  settings.json + rule file
                      │
                      ▼
                W4  CLAUDE.md + AGENTS.md pointers
                      │
                      ▼
                W5  verification checkpoint
```

`W0` precedes `W2` because the validator's stdin field names are `[assumed]` in
`contracts.md` and must be confirmed against a captured payload. `W1` and `W2`
are independent and may run concurrently. `W3` consumes both. `W4` depends on
the rule file existing, since `CLAUDE.md` points at it.

---

## Risks

| ID | Risk | Mitigation |
|---|---|---|
| `RK1` | `tool_input.file_path` is `[assumed]`, not documented for `Edit`/`Write`/`MultiEdit` | `W0` captures a real payload before the validator is written. `GATE.2` tolerates absence by exiting 0, so a wrong guess fails open rather than blocking |
| `RK2` | Whether the harness resolves a **relative** hook `command` against the worktree cwd is unverified — `GATE.1a` depends on it | `W0` probes this directly. If relative paths do not resolve as expected, fall back to `${CLAUDE_PROJECT_DIR}` and record that the validator under test is the origin tree's copy |
| `RK3` | `plansDirectory` may resolve to the origin root rather than the worktree (`F.18` vs `F.13`) | `MODE.6` measures it in `W5`. If it lands wrong, revert `MODE.3` to the default; only that assertion is lost |
| `RK4` | The gate runs on **every** file edit; a slow validator degrades every session | `GATE.15` budget: one bounded `scandir` plus one file read. No subprocess, no `git` invocation, no recursive walk. Measured in `W5` |
| `RK5` | `.claude/settings.json` is committed, so a malformed `hooks` block affects every contributor at once | Fail-open envelope means a broken *script* is harmless; a broken *settings file* is not. `W3` validates the JSON and confirms registration through `/hooks` before the task closes |
| `RK6` | The required-check configuration lives in GitHub branch protection, which no file in the repo can set | `W5` includes it as an explicit manual step with confirmation. Until it is marked required, `VCS.2` is advisory and `A14` cannot pass |
| `RK7` | The model can self-issue exemptions | Accepted by `D1`. The ledger (`C5`) converts it from invisible to reviewable; that is the whole mitigation |
| `RK8` | Path containment via string prefix would let `src/functualize_extra/` or a symlink bypass the gate | Resolve real paths and use `os.path.commonpath`; covered by an explicit acceptance in the validator task |
| `RK9` | This feature's own artifacts are invisible until `1.1` un-ignores `.spec/features/` | Ordering only — `1.1` is in the first wave. Noted so the executor does not mistake it for a broken write |

---

## Out of scope

`SK.1`–`SK.4` (SpecKit `clarify`, `analyze`, `converge`, `checklist`) are
audited and deferred by the intent. No task below implements them.
