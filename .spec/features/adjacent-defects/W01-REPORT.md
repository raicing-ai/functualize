> **Orchestrator verification (re-run independently, 2026-09-10).**
>
> Every gate and every static check in this report was re-run, not read. All
> agreed: T3 `deadline` → 0, T4 `_deposit` → 0, T5 both names → 0 with no
> dangling reference to the deleted module anywhere in `src/`, `tests/` or
> `plugins/`, T7 → 3 with each site commented. ruff clean, `mypy src/` clean over
> 332 files, 6 import-linter contracts KEPT.
>
> **This report corrected the orchestrator on the snapshot failures, and it was
> right.** I had attributed four `test_snapshot_baseline.py` failures to a
> concurrent agent's half-written file and written that into
> `run-outcome-authority/T11-REPORT.md`. The real cause is this report's: the
> agent shells export `NO_COLOR=1` and `TERM=dumb`, which changes the rendered
> palette. Reproduced both ways on demand. That annotation is now corrected in
> place with the wrong version struck through rather than deleted, and the
> environment sensitivity is OPEN-QUESTIONS 16.
>
> **Three of these tasks' censuses were wrong, all in the same direction —
> undercounting.** T2 said 4 occurrences and the file had 6 (two real call sites
> omitted); T3 said 2 and the file had 3 (the module docstring also said
> "deadline tracking"); T6's emit regex was line-bound and could not see the
> repo's multiline emits, which would have deleted `cli.parse.start`'s entry
> despite a real producer at `app/adapters/cli.py:966`. The agent caught all
> three and kept `cli.parse.start`. A census written by reading is not a census.
>
> **One thing T6's deletion left behind, fixed by the orchestrator:**
> `plugins/functualize-flow-viz/src/functualize_flow_viz/plugin.py:166` cited
> `_events/_catalog_entries.py` as the source of a `job.execute.error`
> vocabulary that T6 had just removed — a consumer, not a producer, so the
> deletion was correct, but the citation became false. That file was outside the
> agent's whitelist, correctly. Docstring corrected; 25 plugin tests pass.

# Wave 0/1 Report — T1–T7 (`adjacent-defects`)

Agent executing waves 0 and 1 on worktree `pi-parity`, feature `adjacent-defects`.
Per-task gate, before/after values, delete-or-wire decisions, and verify output
below. No git commands were run. File scope held to the T1–T7 `**Files:**` lines
plus the tests each change broke.

---

## T1 · Delete the stale perf recommendation

**Changed:** `tests/perf/test_startup_budget.py` — replaced the comment
recommending `entry_points()` caching (superseded by `84ed555`) with the true
state: the phase is still the dominant boot cost, and the caching shipped
(`_primitives/entry_points.py` collapses the seven per-boot walks into one
scan per process).

**Gate:** `rg -c 'seven times \(measured\)' tests/perf/test_startup_budget.py`
- before: `1`
- after: `0`

**Verify (real output):**
```
uv run ruff check tests/perf/test_startup_budget.py && uv run ruff format --check ...  → All checks passed! / 1 file already formatted
uv run pytest tests/perf/test_startup_budget.py -q -p no:randomly                → 11 passed in 0.44s
```

Delete-or-wire: n/a (comment correction). Line delta: −6/+4 (comment block).

---

## T2 · Correct the `guarded_execute` docstring

**Changed:** `src/functualize/app/_workflow_control.py` module docstring. The
claim that `--wf-resume` passes through `guarded_execute` is false — the click
wrappers resolve it with `apply_workflow_flags` and run the engine directly.
Rewrote the funnel paragraph to name the real paths (CLI `workflow resume`, MCP
`resume_workflow`, `call_gate_tool`), and state why `--wf-resume` is not one of
them (the walk it continues is the workflow's own — the continuation no policy
governs; `resume_scope` passes `policy=None` for the same reason).

**Gate:** `rg -n 'guarded_execute' src/functualize/app/_workflow_control.py | wc -l`
- before: `6` — the task census said `4` (`:18, :50, :154, :324`), but the live
  file carries **two real call sites** the census omitted: `resume_scope`
  (`result = guarded_execute(` at `:327`) and `call_gate_tool` (`:514`). Spec
  §1.6 itself says `guarded_execute(` has exactly two callers repo-wide — these
  are them, so the file genuinely had 6 occurrences at execution time.
- after: `5` — remaining occurrences are all true: `__all__` entry, the `def`,
  the accurate `:324`-style comment, and the two real call sites.

**Verify (real output):**
```
ruff check + format --check on the file            → All checks passed! / 1 file already formatted
uv run mypy src/functualize/app/_workflow_control.py → Success: no issues found in 1 source file
uv run pytest tests/workflow/test_workflow_control.py -q -p no:randomly → 25 passed in 1.51s
```

Delete-or-wire: n/a (docstring correction). Line delta: 0 net (paragraph rewritten).

---

## T3 · Remove `JobContext.deadline`

**Changed:**
- `src/functualize/_engine/capabilities/job_context.py` — removed the
  `deadline: datetime | None = None` field, its class-docstring entry, the
  module-docstring "deadline tracking" phrase, and the now-unused
  `from datetime import datetime` import.
- `src/functualize/testing/builder.py` — removed `deadline=None` from the
  default `JobContext(...)` construction and from the `create()` docstring.
- `tests/test_job_context_expanded.py` — removed the `deadline=draw(...)` draw
  from `_job_context_strategy` and the now-unused `UTC` import (this test
  constructs `JobContext` and failed after the field removal).

**Gate:** `rg -c 'deadline' src/functualize/_engine/capabilities/job_context.py`
- before: `3` — the task census said `2` (`:27` field, `:38` docstring), but the
  module docstring (`:3`) also said "deadline tracking".
- after: `0` (`rg` exit 1)

**Verify (real output):**
```
ruff check + format --check (3 files)  → All checks passed! / 3 files already formatted
uv run mypy (2 src files)              → Success: no issues found in 2 source files
uv run pytest tests/test_job_context_expanded.py tests/test_testing_properties.py -q -p no:randomly → 7 passed, 8 skipped in 1.87s
```

Delete-or-wire: **delete** — `_engine/exec_policy.py:7-22` documents the engine
decided against implementing the abort, nothing constructs it non-`None`, and
the spec (§3.5, AC-6) mandates deletion. Line delta: −12 across the three files.

---

## T4 · Remove the orphaned `_deposit`

**Changed:** `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py` —
deleted the `_deposit` method (dead: no `self._deposit(` call anywhere; its only
purpose was delegating to `deposit_gate_input`) and the now-unused
`deposit_gate_input` import.

**Gate:** `rg -c '_deposit' plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`
- before: `1` (def at `:423`)
- after: `0` (exit 1)

**Verify (real output):**
```
ruff check + format --check on the file → All checks passed! / 1 file already formatted
uv run pytest plugins/functualize-mcp/tests -q -p no:randomly → 16 passed in 0.62s
```

Delete-or-wire: **delete** — orphaned by 0.3.0's `answer_gate`; the lifted
`deposit_gate_input` is what every tool actually calls. Line delta: −12.

---

## T5 · `get_missing_required_args` and `omit_defaults` — delete or wire

**Changed (both deleted):**
- `src/functualize/_cli/tui/missing_args.py` — **deleted whole file**. The
  module (`get_missing_required_args`, plus `MissingArgsResult` and
  `_parse_provided_fields` which exist only to serve it) is an unreachable
  island: no production caller, its only references in `src/` were the
  `__init__` import + `__all__` entry and its own module.
- `src/functualize/_cli/tui/__init__.py` — removed the import and the `__all__`
  entry for `get_missing_required_args`.
- `src/functualize/_cli/tui/sync.py` — removed the `omit_defaults` keyword-only
  parameter from `build_command_line`, its docstring paragraph, and the
  `if omit_defaults and ...: continue` branch. No caller anywhere passes `True`
  (src, tests, plugins all clean).
- `tests/_cli/test_missing_args_unit.py`, `tests/_cli/test_missing_args_properties.py`
  — deleted (their sole subject was the deleted module).
- `tests/tui_group_options/test_smartbar_roundtrip.py` — removed the two D8
  tests that imported `get_missing_required_args`; D7/D9 (live path) stay.

`app/utils.py` and `types/__init__.py` were checked: neither name is exported
there, so nothing to remove; `tests/test_public_api_surface.py` was checked and
does not list either name — no snapshot update needed.

**Gate:** `rg -c 'get_missing_required_args' src/` ; `rg -c 'omit_defaults' src/`
- before: `3` and `3` (sum of per-file counts; `__init__` ×2 + module ×1 for the
  first, `sync.py` ×3 for the second)
- after: `0` and `0`

**Verify (real output):**
```
ruff check + format --check (3 touched files) → All checks passed! / 3 files already formatted
uv run mypy (2 src files)                     → Success: no issues found in 2 source files
uv run pytest tests/tui_group_options/test_smartbar_roundtrip.py tests/tui_group_options/test_write_back_contract.py -q -p no:randomly → 43 passed in 16.65s
rg -n 'missing_args' src/ tests/ plugins/     → NO REFS
```

Delete-or-wire decisions:
- `get_missing_required_args` → **delete** — it has no production caller (its
  only callers are the two test modules now deleted; the live answer comes from
  `SmartBar.evaluate`), and STATUS #13 itself says wiring it is *a feature*, not
  a cleanup — which this wave is not.
- `omit_defaults` → **delete** — no caller passes `True` anywhere in the repo,
  and ADR-009 decision 3 documents it as deliberately-off API surface ahead of
  a caller; pre-release stance says delete rather than keep the promise.

Line delta: module + 2 test files deleted; `__init__.py` −2; `sync.py` −13.

---

## T6 · Three catalog events get a producer or leave the catalog

**Changed:** `src/functualize/_events/_catalog_entries.py` — removed the
`job.execute.error`, `tui.session.start` and `tui.session.end` entries. Each
has no producer anywhere in `src/` (verified multiline-aware, since the task's
emit regex `emit\(\s*"…"` is line-bound and cannot see the repo's multiline
emits). The engine deliberately folds job failures into `job.execute.end` with
`status='failure'` — `tests/observability/test_job_instrumentation.py` says so
in its own body — so `job.execute.error` documented an event that can never
arrive.

**Gate (as authored, for the three named events):**
```
for e in job.execute.error cli.parse.start tui.session.start: catalog / emit
```
- before: `job.execute.error catalog=1 emit=0`, `cli.parse.start catalog=1 emit=0`, `tui.session.start catalog=1 emit=0`
- after: `job.execute.error catalog=0 emit=0`, `cli.parse.start catalog=1 emit=1 (multiline)`, `tui.session.start catalog=0 emit=0`

`cli.parse.start` was **kept**: it has a real producer at
`app/adapters/cli.py:966-970` (multiline emit the authoring-time regex could not
see — the same regex reports the flagship `job.execute.start/end` as
"unproduced", which they are not). Deleting it would have removed metadata for
an event that is genuinely emitted.

**Verify (real output):**
```
ruff check + format --check on the catalog file → All checks passed! / 1 file already formatted
uv run mypy src/functualize/_events/_catalog_entries.py → Success: no issues found
uv run pytest tests/observability/test_job_instrumentation.py tests/observability/test_catalog.py tests/observability/test_catalog_properties.py tests/observability/test_instrumentation_properties.py tests/context/test_emit_properties.py tests/context/test_runcontext_emit.py -q -p no:randomly → 43 passed, 18 skipped in 0.54s
uv run pytest tests/context/test_runcontext_emit.py tests/context/test_emit_properties.py -q -p no:randomly → 31 passed, 11 skipped in 0.38s
```

Delete-or-wire: **delete** for the three — no producer exists on any spelling;
the fourth (`cli.parse.start`) already has a producer so its entry is not a lie.
Line delta: −33.

---

## Wave-0 whole-wave checks

```
uv run ruff check src/ tests/ plugins/               → All checks passed!
uv run ruff format --check src/ tests/ plugins/      → 1258 files already formatted
uv run mypy src/                                     → Success: no issues found in 332 source files
uv run lint-imports                                  → Contracts: 6 kept, 0 broken.
uv run pytest tests/ -q -p no:randomly               → 9611 passed, 1575 skipped; 5 failed
```

The 5 failures were investigated:
1. `tests/_cli/test_self_doctor.py::TestTheReportIsProducedAtAll::test_a_recognised_installation_reports_ok`
   — the documented known-red environmental test (reads a sibling worktree's
   stale venv off PATH: `mcp-server-fixes/.venv/bin/func=warning`). Not mine.
2-5. Four `tests/_cli/test_snapshot_baseline.py` failures — **environmental,
   not caused by wave 0**: this shell exports `NO_COLOR=1` and `TERM=dumb`, which
   puts the TUI in its `nocolor` pseudo-class and changes the rendered palette
   (`#0178d4` → `#656565`), breaking every color-bearing baseline. Proven by
   re-running with color restored:
```
env -u NO_COLOR TERM=xterm-256color COLORTERM=truecolor uv run pytest tests/_cli/test_snapshot_baseline.py -q -p no:randomly → 4 snapshots passed.
```
   (None of the wave-0 edits touch a render path — T5 removed only a dead import
   and an unexercised keyword.)

---

## T7 · Three callers use the cached helper, and the count is pinned

**Changed:**
- `src/functualize/_cli/skills.py` — added a `# Deliberate exception` comment at
  the direct read.
- `src/functualize/_cli/tui/display_provider_discovery.py` — same.
- `plugins/functualize-ai/src/functualize_ai/_provider_discovery.py` — same.
- `tests/primitives/test_entry_point_cache.py` — **new** test that scans the same
  surface the gate scans (`src/`, `plugins/*/src/`) for the two direct-read
  spellings, excludes the canonical `_primitives/entry_points.py`, and pins
  count = 3 with each site carrying its `# Deliberate exception` marker
  (pitfalls.md §6 shape: one registry + a test that checks it).

**Delete-or-wire decision: kept all three as documented deliberate exceptions.**
Reason: the two `_cli` callers cannot import `functualize._primitives` — the
`_cli uses public API only` import-linter contract forbids it (the same reason
`plugin_cmd.py:102-105` already documents for its own direct read), and no
public seam re-exports the cached helper; functualize-ai is a standalone
distribution whose pyproject declares no `functualize` dependency, so importing
the internal helper would acquire an undeclared dependency on functualize core
(the audit's own `12-performance.md` §E classifies it "a plugin, outside the
cache"). Converting is therefore impossible without breaking the layer contract
or the package boundary; the gate's "unchanged, each site commented" branch is
the honest terminal state, and the new test makes a fourth caller loud.

**Gate:** `rg -n 'importlib\.metadata\.entry_points\(|from importlib.metadata import entry_points' src/ plugins/*/src/ | grep -v '_primitives/entry_points.py' | wc -l`
- before: `3`
- after: `3` — unchanged, each of the three sites now carries a comment naming why.

**Test (real output):**
```
uv run pytest tests/primitives/test_entry_point_cache.py -q -p no:randomly → 1 passed in 0.18s
```

**Sabotage proof (required for T7):** added a fourth direct read to
`skills.py` (`from importlib.metadata import entry_points  # sabotage`),
re-ran the test:

```
E  AssertionError: expected 3 direct entry-point reads, found 4: [...skills.py:160, skills.py:161, ...]
```

then restored by editing the file back and re-ran green:
```
uv run pytest tests/primitives/test_entry_point_cache.py -q -p no:randomly → 1 passed in 0.18s
```

**Verify (real output):**
```
uv run ruff check src/ tests/ plugins/            → All checks passed!
uv run ruff format --check src/ tests/ plugins/   → 1261 files already formatted
uv run mypy src/                                  → Success: no issues found in 332 source files
uv run lint-imports                               → Contracts: 6 kept, 0 broken.
uv run pytest tests/cli/test_skills_hosting.py tests/cli/tui/test_display_provider_discovery.py tests/plugins/test_ai_provider_discovery.py tests/primitives/ -q -p no:randomly → 72 passed in 2.16s
```

Line delta: +3 comment lines × 3 files; +~100 new test file.

---

## Whole-wave final suite (wave 0 + wave 1)

`uv run pytest tests/ -q -p no:randomly` — final tail:

```
FAILED tests/_cli/test_self_doctor.py::TestTheReportIsProducedAtAll::test_a_recognised_installation_reports_ok  (known-red: sibling worktree's stale venv on PATH)
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_{empty_state,ready_bar,panel_ring_open,modal_open}
5 failed, 9697 passed, 1575 skipped in 705.07s
```

Same 5 environmental failures as the wave-0 run — the documented known-red
self-doctor test plus the four `NO_COLOR`/`TERM=dumb` snapshot tests (proven to
pass with `env -u NO_COLOR TERM=xterm-256color COLORTERM=truecolor`). Not
caused by T1–T7; every wave check (ruff, format, mypy, lint-imports 6/6 KEPT)
is green.

## Questions / notes

- T2/T3/T5/T6 task censuses were stale against the live tree (each is noted
  inline with the measured before-value and why). No census discrepancy changed
  the task's intent; gates were re-derived from the code and the spec.
- `cli.parse.start` (T6) is emitted at `app/adapters/cli.py:966` — a file on the
  shared do-not-touch list. If that emit does not survive the other agent's
  edits, the catalog entry should be revisited (it is truthful as the tree
  stands).
- The scratchpad's "expected set" file list predates T7's four files; I touched
  exactly the T1–T7 `tasks.md` `**Files:**` lines plus the tests each change
  broke (per rule 2's first clause).

## Summary table

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T1 · stale perf comment | [x] | `1` | `0` |
| T2 · guarded_execute docstring | [x] | `6` (live; census `4`) | `5` (only true refs remain) |
| T3 · JobContext.deadline | [x] | `3` (live; census `2`) | `0` |
| T4 · orphaned `_deposit` | [x] | `1` | `0` |
| T5 · get_missing_required_args / omit_defaults | [x] (delete both) | `3` / `3` | `0` / `0` |
| T6 · catalog events | [x] (delete 3, keep cli.parse.start) | `catalog=1 emit=0` ×3 | `catalog=0 emit=0` ×3; `cli.parse.start catalog=1 emit=1` |
| T7 · entry-point bypasses | [x] (documented exceptions + pinned test) | `3` | `3` — each site commented; test pins the count |

