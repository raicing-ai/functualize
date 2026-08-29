# Verification report — task 5.1

**Date:** 2026-08-29 · **Worktree:** `spec-workflow-enforcement-intent`

Every criterion in [`spec.md`](spec.md) is either **PASS** (observed) or
**DEFERRED** with the reason it was not reachable from an agent session. Nothing
is marked passed on the strength of a description.

## Criteria

| ID | Result | Evidence |
|---|---|---|
| `A1` | **PASS (live)** | Broke the wave-graph fence, issued a real `Write` to `src/functualize/`. The harness denied it and the reason reached the model — naming `/agentic-specify` and `.spec/EXEMPT`. File never reached disk |
| `A2` | **PASS** | `tests/`, `plugins/*/tests/`, `plugins/conftest.py`, `pyproject.toml`, `docs/`, `.spec/` all pass unexamined. Confirmed standalone and live |
| `A3` | **PASS (live)** | With the graph restored, the same gated `Write` passes silently |
| `A4` | **PASS** | Fresh `.spec/EXEMPT` (≥20 chars) permits the write and appends one 4-field record; re-running dedupes by `(reason, hour)` |
| `A5` | **PASS** | `EXEMPT` aged past 60 min → DENY. Reason under 20 chars → DENY |
| `A6` | **PASS (live)** | Validator replaced with bad-stdout/exit-1; a gated `Write` **succeeded**. Also silent+exit 0 on malformed JSON, empty stdin, absent `file_path`, absent `cwd`, null `tool_input` |
| `A7` | **PASS** | Run across **all 7 worktrees**: only this one passes; 6 deny, including 2 with a `.spec/features/` dir but no valid graph. `${CLAUDE_PROJECT_DIR}` would have returned one answer for all seven |
| `A8` | **PASS** | Against the real captured `ExitPlanMode` payload: `additionalContext` present, <10000 chars, no `decision` key, no imperative framing |
| `A9` | **PASS** | Against the real captured `Agent` payload: all input keys survive incl. `run_in_background`; no phantom `model`; an unknown key survives verbatim; `Explore`/`spec-driven-developer`/default untouched |
| `A10` | **PASS** | Anchor byte-identical across agent and command; all 6 files exist and are tracked |
| `A11` | **PASS** | Phase 0 keys on `CONSTITUTION.md`; all 4 `STATE.md` read sites carry the absence clause |
| `A12` | **PASS** | `tools: Read, Write, Edit, Bash, Grep, Glob, Skill, Agent` |
| `A13` | **PASS** | `.spec/features/` tracked — 5 files staged |
| `A14` | **DEFERRED to merge** | Requires an actual PR. The job body was run locally and **failed correctly** (5 tracked artifacts, exit 1). Also blocked on `RK6` below |
| `A15` | **DEFERRED to merge** | Only observable on master after the clearing commit |
| `A16` | **PASS** | `.spec/plans/` and `.spec/STATE.md` remain untracked |
| `A17` | **PASS (confirmed by operator 2026-08-29)** | `/hooks` is an interactive read-only browser; an agent session cannot read it. Registration is nonetheless **proven live** by `A1` and `A6`, which only happen if the harness invokes the script |
| `A18` | **PASS** | stdlib only (`json`, `os`, `re`, `sys`, `time`); no `functualize` import; runs under bare `python3` outside the venv |
| `A19` | **PASS** | `CLAUDE.md` reduced to a pointer; 0 hits for `agentic-execute\|STATE.md\|CONSTITUTION` |
| `A20` | **PASS** | `pytest` 7315 passed / 1422 skipped / 0 failed; `ruff check` clean; `ruff format --check` 947 formatted; `mypy` 295 files clean; `lint-imports` 5 contracts kept. `src/ tests/ plugins/` show **0** modifications |
| `A21` | **PASS** | Shell write to a gated path with no task list and no exemption → one `shell-write:` record, command not blocked, stdout empty |
| `A22` | **PASS** | Same write with a valid `tasks.md`, or with a fresh `EXEMPT`, records nothing |

## Risks

| ID | Result |
|---|---|
| `RK1` | **CLOSED** — `tool_input.file_path` observed (`F0.1`) |
| `RK2` | **CLOSED** — relative command resolves against the worktree (`F0.3`); no `${CLAUDE_PROJECT_DIR}` fallback needed |
| `RK3` / `MODE.6` | **CLOSED — PASS (measured 2026-08-29).** A plan approved from this worktree landed at `.spec/plans/plan-how-to-add-dazzling-crayon.md` **here**; the master checkout has no `.spec/plans/` directory at all. `plansDirectory` resolves against the *worktree* root, so the `F.13` concern does not apply. Correctly ignored by `.gitignore:16`; `git status` clean. **`plansDirectory` is kept** |
| `RK4` | **PASS with a note** — 45 ms mean per invocation, of which ~32 ms is Python interpreter startup. No subprocess, no `git`, no recursive walk in `spec_gate.py`. Acceptable, but it is per-edit overhead and worth revisiting if it becomes noticeable |
| `RK5` | **PASS** — `settings.json` parses; `permissions.allow` (18) and `deny` (5) unchanged; no `agent` key |
| `RK6` | **DEFERRED — needs a human, outside the repo.** `spec-artifacts-cleared` must be marked a **required check** in GitHub branch protection. Until then `VCS.2` is advisory and `A14` cannot pass |
| `RK7` | Accepted by `D1`; ledger is the mitigation |
| `RK8` | **PASS** — `src/functualize_extra/` not gated; a symlink out of the gated tree not gated; a symlink **into** it correctly gated. Containment via `realpath` + `commonpath` |
| `RK9` | **CLOSED** — `1.1` landed |

## What remains, in order

1. **Commit, push, open the PR.**
2. **Mark `spec-artifacts-cleared` a required check** in GitHub branch protection (`RK6`) — only possible after it has reported once on a PR.
3. **Run Phase 5** (`/agentic-verify`), then the clearing step: migrate the durable half to `STATUS.md`, `git rm -r .spec/features/spec-workflow-enforcement`, and let the CI check go green.

Nothing is committed. All work is staged or modified in the working tree.
