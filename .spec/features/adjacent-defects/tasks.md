# Tasks — adjacent-defects

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

One citation was corrected while authoring: the audit places
`read_group_options_from_cache` at `app/utils.py:1589`. It is at **`:1636`** — the file grew
47 lines in 0.3.0.

---

## Wave 0 — false comments and dead names

### [x] T1 · Delete the stale perf recommendation

**Files:** `tests/perf/test_startup_budget.py`

Lines 44-60 recommend caching `entry_points()`, which shipped as `84ed555` (PR #4,
2026-08-27); the comment is from `b5495c6` (PR #3, 2026-08-20). Replace it with what is
true — the phase is still the dominant boot cost, and the caching is done. Spec AC-8.

**Gate**
```bash
rg -c 'seven times \(measured\)' tests/perf/test_startup_budget.py
```
now: `1` · after: `0`

### [x] T2 · Correct the `guarded_execute` docstring

**Files:** `src/functualize/app/_workflow_control.py`

Lines 17-18 claim `--wf-resume` passes through `guarded_execute`. It does not — the click
wrappers call the engine directly. Spec AC-9.

**Gate**
```bash
rg -n 'guarded_execute' src/functualize/app/_workflow_control.py | wc -l
```
now: `4` *(docstring `:18`, `__all__` `:50`, def `:154`, comment `:324`)* · after: `3`
*(the docstring claim gone; the comment at `:324` is true and stays)*

### [x] T3 · Remove `JobContext.deadline`

**Files:** `src/functualize/_engine/capabilities/job_context.py`,
`src/functualize/testing/builder.py`

It promises an abort `_engine/exec_policy.py:7-22` explicitly decided not to implement. Spec
AC-6.

**Gate**
```bash
rg -c 'deadline' src/functualize/_engine/capabilities/job_context.py
```
now: `2` *(`:27` field, `:38` docstring)* · after: `0`

### [x] T4 · Remove the orphaned `_deposit`

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`

Orphaned by 0.3.0's `answer_gate`. Spec AC-7.

**Gate**
```bash
rg -c '_deposit' plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py
```
now: `1` *(def at `:423`)* · after: `0`

### [x] T5 · `get_missing_required_args` and `omit_defaults` — delete or wire

**Files:** `src/functualize/_cli/tui/__init__.py`, `src/functualize/app/utils.py`, and the
defining modules

STATUS #13 and #14. For each: delete, **or** name the production call path and prove it by
breaking the path and watching a test fail (`CONSTITUTION.md` → *Reachability*). Spec AC-4.

**Gate**
```bash
rg -c 'get_missing_required_args' src/ ; rg -c 'omit_defaults' src/
```
now: `3` and `3` · after: `0` and `0` *(if deleted)*, or unchanged **plus** a named call path
recorded in the task

### [x] T6 · Three catalog events get a producer or leave the catalog

**Files:** `src/functualize/_events/_catalog_entries.py`, and emit sites if wired

`job.execute.error`, `cli.parse.start`, `tui.session.start/end`. The catalog is public
introspection, so an entry with no producer is a documented lie. Spec AC-5.

**Gate**
```bash
for e in job.execute.error cli.parse.start tui.session.start; do
  printf '%s catalog=%s emit=%s\n' "$e" \
    "$(rg -c "\"$e\"" src/functualize/_events/_catalog_entries.py || echo 0)" \
    "$(rg -c "emit\(\s*\"$e\"" src/functualize/ || echo 0)"
done
```
now: each `catalog=1 emit=0` · after: each `catalog=0 emit=0` **or** `catalog=1 emit≥1`

---

## Wave 1 — one entry-point API

### [x] T7 · Three callers use the cached helper, and the count is pinned

**Files:** `src/functualize/_cli/skills.py`,
`src/functualize/_cli/tui/display_provider_discovery.py`,
`plugins/functualize-ai/src/functualize_ai/_provider_discovery.py`,
`tests/primitives/test_entry_point_cache.py`

Not a boot win (spec §1.7) — a consistency gap. Note the cache is process-wide and never
invalidated except by `clear_entry_point_cache()`; a caller that must observe a fresh install
is a deliberate exception and says so. Spec AC-10.

**Gate**
```bash
rg -n 'importlib\.metadata\.entry_points\(|from importlib.metadata import entry_points' \
  src/ plugins/*/src/ | grep -v '_primitives/entry_points.py' | wc -l
```
now: `3` · after: `0`, **or** unchanged with each remaining site carrying a comment naming why

**Test:** a test asserts the bypass count, so a fourth cannot appear silently
(`pitfalls.md` §6).

---

## Wave 2 — the measurement

### [x] T8 · Record the layer-contract blind spot

**Files:** `contributor/architecture/layer-contract-blind-spot.md` (new),
`pyproject.toml` (comment only)

`exclude_type_checking_imports = true` (`pyproject.toml:234`) hides **125** TYPE_CHECKING
imports of internal packages. Measured with a temporary config outside the tree: flipping it
breaks **all six contracts** with **47 violations** — `_cli/tui/` 18, `_engine/` 8, `_types/`
7, `_app/` 6, remainder elsewhere.

The audit's conditional was *"if `_config → _events` is the only violation"*. It is not, so
its recommendation does not apply. **The flag stays on**; the hole is documented with a
measured size so a future reader can tell whether it grew. Spec AC-3, §3.4.

**Gate**
```bash
test -f contributor/architecture/layer-contract-blind-spot.md && \
  rg -c '47|125' contributor/architecture/layer-contract-blind-spot.md
```
now: `file absent` · after: `≥2`

**Gate — the flag is unchanged**
```bash
rg -c 'exclude_type_checking_imports = true' pyproject.toml
```
now: `1` · after: `1`

---

## Wave 3 — the rendered conflict

### [x] T9 · A group-options conflict is rendered, not raised

**Files:** `src/functualize/_discovery/cached_provider.py`, `src/functualize/_app/boot.py`,
`tests/group_options/test_conflict_is_reported.py`

Joins ADR-018's reported-not-fatal surface. Names both declaring files. Uses the existing exit
table — no new code, no new vocabulary. Spec AC-1.

**Gate**
```bash
rg -c 'except GroupOptionsConflictError' src/
```
now: `0` · after: `≥1`

**Test:** two files declaring one group option → a rendered error naming both, and the
discovery-failure exit code, not a traceback.

---

## Wave 4 — the cache fingerprint

### [x] T10 · The group-options cache section takes a fingerprint

**Files:** `src/functualize/app/utils.py`, `src/functualize/_app/boot.py`,
`tests/discovery/test_group_options_fingerprint.py`

`read_group_options_from_cache` at `app/utils.py:1636` takes `cache_path` only, so no caller
*can* pass a fingerprint. Every sibling section is guarded by `discovery_hash`
(`_app/boot.py:518`). Spec AC-2.

**Gate**
```bash
rg -n 'def read_group_options_from_cache' -A3 src/functualize/app/utils.py | rg -c 'discovery_hash'
```
now: `0` · after: `1`

**Test:** changing a discovery filter invalidates the group-options section, as it invalidates
the others. **Sabotage:** drop the fingerprint argument at the call site; this test must fail.

---

## Wave 5 — three user-visible behaviours

### [x] T11 · An enum parameter arrives as its enum — **#38**

**Files:** `src/functualize/app/adapters/click_params.py`,
`tests/cli/test_enum_parameter_roundtrip.py`

Convert where the `click.Choice` was rendered — `_click_type_for`'s inverse — so the
programmatic path is untouched (risk R-b). Spec AC-11.

**Gate**
```bash
rg -c 'click.Choice' src/functualize/app/adapters/click_params.py
```
now: `≥1` · after: unchanged — **the count is not the gate**; the test is

**Test:** one test asserts both surfaces: `func paint.py paint red` and
`app.execute("paint", color=Color.RED)` both see `Color.RED` in the body.

### [x] T12 · Unknown-command explanation reaches an app's own entry point — **#37**

**Files:** `src/functualize/app/adapters/cli.py`, `tests/cli/test_unknown_command_parity.py`

Both reporters already call `explain_missing_job`; click's `UsageError` fires first in
standalone mode. Spec AC-12.

**Test:** via the dual-surface `cli_run` fixture — the same assertion on `func` and on an app
entry point.

### [x] T13 · A parse failure survives a warm cache — **#27**

**Files:** `src/functualize/_discovery/`, `tests/discovery/test_parse_failure_persists.py`

Reproduce the asymmetry first as a failing test — a `SyntaxError` module and a
`ModuleNotFoundError` module in one tree, run twice — then fix only the reporting path. **Do
not touch `discovery_hash`** (risk R-a). Spec AC-13.

---

## Wave 6 — the architectural one, alone and withdrawable

### [x] T14 · Single-file mode stops executing CWD module code

**Files:** `src/functualize/_cli/main.py`, `tests/cli/test_single_file_cwd_isolation.py`

`main.py:1652-1668` runs `auto_discover(cwd)` and builds a second `FunctualizeApp`, executing
any CWD module's top level. 0.3.0 patched a symptom at `:1544-1560`; that fix and its
regression test **stay**.

> **Withdrawal is pre-authorised** (spec §3.2, AC-14). If the second boot cannot go without
> changing routing behaviour, record the finding in `.spec/STATUS.md` with the evidence and
> close the task as withdrawn. A forced change here is worse than a documented limitation.

**Test:** a stray CWD script with a module-level `app.cli_command()` does not hijack
`func weather.py trip_planner`.

---

## Wave 7 — checkpoint

### [x] T15 · Feature gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — **6 contracts kept** (unchanged setting; T8 is a document)
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- AC-1…AC-14 each named to a test, or to a recorded withdrawal (AC-14 only)
- orphan scan over every symbol this feature touched
- sabotage: T10's fingerprint

---

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | *(fill from the wave's task headings: T1, T2, T3, T4, T5, T6)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 1 | *(fill from the wave's task headings: T7)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 2 | *(fill from the wave's task headings: T8)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 3 | *(fill from the wave's task headings: T9)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 4 | *(fill from the wave's task headings: T10)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 5 | *(fill from the wave's task headings: T11, T12, T13)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 6 | *(fill from the wave's task headings: T14)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 7 | *(fill from the wave's task headings: T15)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1", "T2", "T3", "T4", "T5", "T6"]},
    {"id": 1, "tasks": ["T7"]},
    {"id": 2, "tasks": ["T8"]},
    {"id": 3, "tasks": ["T9"]},
    {"id": 4, "tasks": ["T10"]},
    {"id": 5, "tasks": ["T11", "T12", "T13"]},
    {"id": 6, "tasks": ["T14"]},
    {"id": 7, "tasks": ["T15"]}
  ]
}
```

**Why these boundaries**

- **W0 is six tasks in one wave** because every one is a deletion or a comment, in six
  disjoint files, with no behaviour change between them.
- **W1 alone** — T7 edits three files *and* adds the test that pins their count; splitting it
  would let the count test land before the callers it counts.
- **W2 alone** — T8 produces a document, not code, and its measurement must be taken against a
  tree no other task in this feature has modified.
- **W3 and W4 are separate waves only because both edit `_app/boot.py`.** Neither depends on
  the other; they are serialized because the rule is disjoint file sets, not because there is
  an ordering constraint. When in doubt, serialize.
- **W5's three are user-visible behaviours** in three disjoint areas.
- **W6 alone, last, and withdrawable** — the only item with architectural blast radius.
- **W7 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness within each wave**

| Wave | Tasks | Files |
|---|---|---|
| 0 | T1 / T2 / T3 / T4 / T5 / T6 | `tests/perf/` / `app/_workflow_control.py` / `capabilities/job_context.py`+`testing/builder.py` / `_workflow_tools.py` / `_cli/tui/__init__.py`+`app/utils.py` / `_events/_catalog_entries.py` |
| 5 | T11 / T12 / T13 | `adapters/click_params.py` / `adapters/cli.py` / `_discovery/` |

Waves 1, 2, 3, 4, 6 and 7 hold one task each, so disjointness is trivial there.
`_app/boot.py` is touched by T9 and T10, which is exactly why they are waves 3 and 4 rather
than one wave. `app/utils.py` is touched by T5 (wave 0) and T10 (wave 4).
