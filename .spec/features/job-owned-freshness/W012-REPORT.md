# W012 — report (job-owned-freshness, waves 0–2)

Agent scope: T1, T2, T3. Worktree `/home/viltohmyst/code/raicing-ai/functualize/.worktrees/pi-parity`,
branch `feat/run-model`. No git command was run (RULES §1); restores were done by copying files back
from `/tmp/claude-1000/.../scratchpad/s-f9-backup/`.

---

## Scope note first — the brief's file list is wrong in two places

`T1`'s `**Files:**` line and `plan.md:37` both name **`src/functualize/_primitives/di.py`** as the
home of `INJECTED_PARAM_TYPE_NAMES`. It is not:

```
$ rg -c 'INJECTED_PARAM_TYPE_NAMES|capability_names' src/functualize/_primitives/di.py
(exit 1, no matches)
$ rg -c 'Freshness' src/functualize/_primitives/di.py
0
```

The set lives in `src/functualize/_primitives/capability_names.py`, and the T1 gate as written
(`rg -c 'Freshness' .../di.py` → after `≥1`) **cannot pass by construction**. Two consequences:

- **`_primitives/di.py` was not touched at all** (verified below).
- The change was made where the symbol actually is, plus the one file the ADR-014 invariant
  forces: `_engine/capabilities/registry.py`. Without the registry half the process refuses to
  import, so T1 cannot be landed with the brief's list alone. Both are named in "Files touched"
  below and were selected by re-running the gates, not by prose (RULES: *Censuses and gates*).

Nothing else outside the list was touched. `_app/boot.py`, `app/utils.py`, `_types/protocols.py`
and `_types/errors.py` were not opened for writing.

### Files touched

| File | Wave | Change | Lines |
|---|---|---|---|
| `_engine/capabilities/freshness.py` | T1+T2 | **new** | 161 |
| `job/_freshness.py` | T1 | **new** (mirrors `job/_sources.py`) | 8 |
| `tests/execution/test_freshness_capability.py` | T1+T2 | **new** | 256 |
| `tests/execution/test_fingerprint_decides.py` | T3 | **new** | 307 |
| `_engine/capabilities/registry.py` | T1 | import + tuple entry | +2 |
| `_primitives/capability_names.py` | T1 | one name in the set | +1 |
| `job/capabilities.py` | T1 | import + 2 `__all__` entries | +3 |
| `job/__init__.py` | T1 | import + 2 `__all__` entries | +4 |
| `skills/functualize/references/capabilities.md` | T1 | one table row | +1 |
| `_types/job_declaration.py` | T3 | `decides` field, validation, docstring, serializers | +15 (549→564) |
| `_engine/executor.py` | T3 | third override in the existing block | +17 (2665→2682) |
| `tests/test_public_api_surface.py` | T1 | `functualize.job` expected exports | +4 |
| `tests/engine/test_capability_registry.py` | T2 | declared-bind census | ±5 |
| `tests/test_job_declaration_value_objects.py` | T3 | exact `to_dict()` dict | +4 |

`di.py`: **not in the list above on purpose.**

Three tests were edited because my change broke them (RULES §2 "plus tests that fail because of
your change"). None was weakened — each moved *toward* the new contract: a census that now names
the capability that arrived, an export set that now contains the new exports, a serialization
assertion that now includes the new field.

---

## T1 · `Freshness` exists, is injected, and always reports `None`

### What changed

- `freshness.py` — `FreshnessVerdict` (frozen dataclass: `state`, `key`, `recorded_value`,
  `declared_sources`, `declared_generates`, `source_map`, `is_fresh`) and `Freshness`
  (`verdict()` → `None`), with a `CapabilitySpec` whose factory is deliberately empty. **No
  second-phase completion in this wave**, so nothing in the module names one (that is T2's gate).
- Registered at all three ADR-014 sites: the spec beside the capability, `CAPABILITY_SPECS`, and
  `INJECTED_PARAM_TYPE_NAMES`.
- Public re-export through the same chain `Sources` uses:
  `_engine/…/freshness.py` → `job/_freshness.py` → `job/capabilities.py` → `job/__init__.py`.

### Gates

| Gate | Command | Before | After |
|---|---|---|---|
| capability exists | `test -f .../freshness.py && rg -c 'CapabilitySpec\(' .../freshness.py` | file absent (exit 1) | `1` |
| name registered | `rg -c 'Freshness' src/functualize/_primitives/di.py` | `0` (exit 1) | **`0`** — brief's path; see scope note |
| name registered (real) | `rg -c 'Freshness' src/functualize/_primitives/capability_names.py` | `0` (exit 1) | `1` (exit 0) |

```
$ test -f src/functualize/_engine/capabilities/freshness.py && rg -c 'CapabilitySpec\(' src/functualize/_engine/capabilities/freshness.py
1
gate1 exit=0
$ rg -c 'Freshness' src/functualize/_primitives/di.py
0
gate2-as-written(di.py) exit=1
$ rg -c 'Freshness' src/functualize/_primitives/capability_names.py
1
gate2-real(capability_names.py) exit=0
```

### Test

`tests/execution/test_freshness_capability.py` — a job declaring `Freshness` runs through
`app.execute`, receives the instance, and `verdict()` is `None`; a second test asserts the
capability is not published as a job argument.

```
$ uv run pytest tests/execution/test_freshness_capability.py -q --no-header
2 passed in 0.44s
```

### Sabotage (two, one per wire)

The task's claim is that the wiring is proven *before* it carries meaning. Two independent wires
exist (the registry and the name set), so each was broken once.

**(a) Withhold the spec from `CAPABILITY_SPECS`:**

```
E       RuntimeError: capability registry and INJECTED_PARAM_TYPE_NAMES disagree —
declared here but not named in _primitives: []; named in _primitives but not declared here:
['Freshness']. … see ADR-014.
FAILED tests/execution/test_freshness_capability.py::test_a_job_receives_the_capability_and_reports_no_verdict
1 failed, 1 passed in 0.62s
```

The second test still passed — extraction is name-based and the name was still there. That is why
(b) exists.

**(b) Remove `"Freshness"` from `INJECTED_PARAM_TYPE_NAMES`:**

```
FAILED …::test_a_job_receives_the_capability_and_reports_no_verdict - RuntimeError: … declared here
but not named in _primitives: ['Freshness']; named in _primitives but not declared here: []
FAILED …::test_the_capability_is_not_a_published_job_argument -
    assert ['fresh', 'real'] == ['real']
E         +     'fresh',
2 failed in 0.45s
```

Both restored by `cp -f` from the backup; re-run green (2 passed). The two tests are therefore
non-vacuous and cover different halves.

---

## T2 · Bind the verdict after the pre-flight, before the body

### What changed

`freshness.py` only — `Freshness._bind(decision)`, `_bind_from_preflight(instance, decision)`, and
`preflight_bind=_bind_from_preflight` on the spec. `_bind` reads `state`, `key`, `recorded_value`,
`declared_sources`, `declared_generates` and `source_map` **off the decision**, and binds
`source_map` by reference (not a copy).

**`_engine/executor.py` needed no change in this wave.** The brief lists it for T2; the ADR-014
loop (`_bind_preflight_capabilities`, `executor.py:2154`) already completes *every* spec that
declares a second phase, so the capability was picked up by declaring it. `executor.py` was first
touched in T3.

### Gates

```
$ rg -c 'preflight_bind' src/functualize/_engine/capabilities/freshness.py
1
gate-preflight_bind exit=0
$ rg -c 'compute_args_hash|glob|stat\(' src/functualize/_engine/capabilities/freshness.py
0
gate-nocompute exit=1 (1 means no match = good)
```

Before: `0` / `n/a`. After: `1` / `0` (nothing recomputed).

### Tests (same file, extended)

Cold path, warm path (a fresh verdict forced into the body — the pre-existing `force` door, which is
what makes the bind-before-override ordering observable), a decision-changes test, an identity test
for `source_map`, and an `is_fresh`-is-only-`SKIP_FRESH` boundary test.

```
$ uv run pytest tests/execution/test_freshness_capability.py -q --no-header
7 passed in 0.44s
```

### Sabotage — both paths, as AC-7 requires

`_bind_from_preflight` reduced to `del decision, instance`:

```
FAILED …::test_the_verdict_is_populated_on_the_cold_path
E       AssertionError: the verdict never arrived — the bind is unwired
E       assert None is not None
… test_freshness_capability.py:120

FAILED …::test_the_verdict_is_populated_on_the_warm_path
E       AssertionError: the verdict never arrived — the bind is unwired
E       assert None is not None
… test_freshness_capability.py:163

2 failed, 5 deselected in 0.41s
```

Both failures are on each test's **own** assertion, not on a shared setup line (the warm test's
setup asserts only that the cold run entered the body, so the sabotage's failure there is the
warm-leg assertion). Restored, re-run: `7 passed`.

---

## T3 · `Fingerprint.decides`, and the engine honours it

### What changed

- `_types/job_declaration.py` — `decides: bool = False` on `Fingerprint`, a `bool` validation in
  `__post_init__`, a docstring table naming the two rows, and round-tripping in
  `to_dict`/`from_dict`.
  - **The serializer entry is not in the task text and is load-bearing:** `decides` is read off the
    live function on a cold boot and off the discovery cache on every later one. Omitting it means
    the job builds once and then skips forever — the cold/warm divergence class this branch has
    paid for four times. `from_dict` uses `.get("decides", False)`, the field's own default, because
    a cache written before the field existed is discarded only on a version change.
- `_engine/executor.py` — a third clause in the **existing** override block that already handles
  `force_fresh` and `force` (now `:1127-1141`), reading `decides` off
  `function.__functualize_job__.cache`:

```python
        if preflight_decision is not None:
            _state = preflight_decision.verdict.state
            _cache = getattr(
                getattr(function, "__functualize_job__", None), "cache", None
            )
            _decides = bool(getattr(_cache, "decides", False))
            if (
                (force_fresh and _state is GuardState.SKIP_FRESH)
                or (
                    force
                    and _state in (GuardState.SKIP_FRESH, GuardState.SKIP_SATISFIED)
                )
                or (_decides and _state is GuardState.SKIP_FRESH)
            ):
                preflight_decision = None
```

The comment block above it was rewritten from "Two overrides" to "Three overrides" and the
`decides` paragraph states its scope (SKIP_FRESH only).

### Gates

| Gate | Command | Authoring `now:` | This worktree, before | After |
|---|---|---|---|---|
| the field exists | `rg -c 'decides' _types/job_declaration.py` | `0` | `0` (exit 1) | `8` (exit 0) |
| override beside its siblings | `rg -n 'force_fresh and _state is GuardState.SKIP_FRESH' executor.py` | `1022` | `1120` | `1134` — still one line, inside the same block (now `1127-1141`) |
| early return untouched | `rg -n 'not preflight_decision.should_run' executor.py` | `1026` | `1124` | `1142` |

The early return **moved in line number** (1124 → 1142) because the block above it grew by 17
lines; its text is byte-identical and the task's "unchanged" claim holds in content, not in
offset. Recording this because the task's own `now:` values (1022/1026) do not match this worktree
even before T3 — the branch has moved since `e57f0c9`.

### Tests

`tests/execution/test_fingerprint_decides.py`, seven tests. Test 1 (the default) was written and
**run before the engine change** — it passed then and still passes, so it is a regression gate:

```
$ uv run pytest tests/execution/test_fingerprint_decides.py -q --no-header   # before the engine edit
FAILED …::test_an_opted_in_job_enters_its_body_and_reads_the_fresh_verdict
E       assert <RunStatus.SKIPPED: 'Skipped'> is <RunStatus.SUCCESS: 'Success'>
FAILED …::test_an_opted_in_run_is_recorded_as_having_run
E       AssertionError: assert <RunStatus.SKIPPED: 'Skipped'> is <RunStatus.SUCCESS: 'Success'>
FAILED …::test_the_declaration_survives_a_warm_boot
E       AssertionError: the warm boot skipped the body — `decides` did not survive the cache
3 failed, 4 passed in 2.90s

$ uv run pytest tests/execution/test_fingerprint_decides.py -q --no-header   # after
7 passed in 2.67s
```

Each test, and what it pins:

| Test | AC | Asserts |
|---|---|---|
| `test_a_job_that_does_not_opt_in_is_still_skipped` | AC-3 | `SKIPPED`, body ran once, recorded value returned, exit code 0, history `["success", "skipped"]` |
| `test_an_opted_in_job_enters_its_body_and_reads_the_fresh_verdict` | AC-4 | body entered, `verdict().is_fresh is True` |
| `test_an_opted_in_run_is_recorded_as_having_run` | §3.3 | history `["success", "success"]`, not `skipped` |
| `test_opting_in_does_not_bypass_a_failing_precondition` | AC-5 | `REFUSED`, exit 3, no body |
| `test_opting_in_does_not_bypass_a_satisfied_status_guard` | AC-5 | `SKIP_SATISFIED` still skips — `decides` is not "run whenever not fresh" |
| `test_opting_in_does_not_bypass_a_blocking_gate` | AC-5 | `BLOCKED`, exit 5, no body |
| `test_the_declaration_survives_a_warm_boot` | AC-4 | two real CLI processes: cold body `is_fresh False`, warm body `is_fresh True` |

The last one is the one that proves the `to_dict`/`from_dict` entry is doing work: it runs the real
`func`-style CLI twice against one project and asserts the second (cache-fed) run still enters the
body.

### Sabotage

`_decides = True` (every job decides its own freshness):

```
$ uv run pytest tests/execution/test_fingerprint_decides.py -k "does_not_opt_in" -q --no-header
FAILED …::test_a_job_that_does_not_opt_in_is_still_skipped
E       AssertionError: assert <RunStatus.SUCCESS: 'Success'> is <RunStatus.SKIPPED: 'Skipped'>
1 failed, 6 deselected in 0.34s
```

Restored by `cp -f`; re-run `7 passed`.

---

## Verify — every command, real output

```
$ uv run ruff check src/ tests/ plugins/
All checks passed!
ruff check exit=0

$ uv run ruff format --check src/ tests/
1110 files already formatted
ruff format exit=0

$ uv run mypy src/
Success: no issues found in 335 source files
mypy exit=0

$ uv run lint-imports
Analyzed 335 files, 888 dependencies.
Peer layers are independent KEPT
Events depends on foundation only KEPT
Primitives import nothing internal KEPT
Types import nothing internal KEPT
Internal never imports public KEPT
_cli uses public API only KEPT
Contracts: 6 kept, 0 broken.
lint-imports exit=0
```

Targeted and affected suites:

```
$ uv run pytest tests/execution/test_freshness_capability.py tests/execution/test_fingerprint_decides.py
14 passed

$ uv run pytest tests/execution/ tests/engine/ tests/pipeline/ tests/core/ tests/types/ tests/discovery/
1 failed, 1796 passed, 129 skipped in 171.80s
   ^ the failure was tests/engine/test_capability_registry.py::test_the_two_phase_bind_is_declared_not_remembered
     asserting `{"Sources"}`; updated to `{"Freshness", "Sources"}` (it fails *because* T2 landed).

$ uv run pytest tests/engine/ tests/execution/ tests/adapters/ tests/config/ tests/workflow/
1164 passed, 148 skipped in 68.39s

$ uv run pytest tests/test_job_declaration_value_objects.py tests/integration/ tests/skills/ tests/test_public_api_surface.py
338 passed, 12 skipped in 11.65s

$ uv run pytest -q --no-header -n auto          # whole fast suite
4 failed, 9755 passed, 1586 skipped in 154.15s
   ^ all four: tests/_cli/test_snapshot_baseline.py — the documented NO_COLOR=1/TERM=dumb red in
     this shell. Proof, as RULES gives it:
$ env -u NO_COLOR TERM=xterm-256color uv run pytest tests/_cli/test_snapshot_baseline.py -q --no-header
4 passed in 2.52s
```

`tests/_cli/test_self_doctor.py::…test_a_recognised_installation_reports_ok` did **not** fail in
this run (it passed), so it is not among the four.

## AC map for these waves

| AC | Where it is proven | Wave |
|---|---|---|
| AC-1 job reads state/key/recorded value/declared sources+generates | `test_the_verdict_is_populated_on_the_cold_path` | 1 |
| AC-2 bound after the pre-flight, before the body; cold **and** warm | `…_on_the_cold_path`, `…_on_the_warm_path`, plus the AC-7 sabotage | 1 |
| AC-3 a job that does not opt in is unchanged | `test_a_job_that_does_not_opt_in_is_still_skipped` (written before the engine change) | 2 |
| AC-4 opted-in body entered on `SKIP_FRESH` and reads it | `test_an_opted_in_job_enters_its_body_and_reads_the_fresh_verdict`, `…_survives_a_warm_boot` | 2 |
| AC-5 opt-in does not bypass precondition / gate (and not `SKIP_SATISFIED`) | three tests in `test_fingerprint_decides.py` | 2 |
| AC-6 the verdict is the engine's decision, not recomputed | `test_the_reading_changes_when_the_decision_changes`, `test_the_source_map_is_the_decisions_own_object`, and the T2 gate `compute_args_hash\|glob\|stat(` = 0 | 1 |
| AC-7 two-path sabotage | T2 section above (failure text from both tests) | 1 |
| AC-8 worked example + guide | **not in my scope** (T4) | 3 |

## T4's gate depends on vocabulary this wave already provides

`rg -c 'GuardState' src/functualize/_engine/capabilities/freshness.py src/functualize/_engine/explain.py`
→ the first is now `3`, the second was already `≥1`. Nothing to do; noted so T4's author does not
treat it as a pre-existing failure.

## Skill table — why `skills/` was edited by a code wave

`tests/skills/test_api_claims.py::test_capability_table_matches_the_engine` compares the skill's
capability table against `INJECTED_PARAM_TYPE_NAMES` (that is the point of the test). Registering
the name therefore turned the suite red until the table gained a `Freshness` row. The row states
only what is true as of this wave — it deliberately does **not** mention `Fingerprint(decides=True)`
yet, because the field did not exist when the row was written; T4 (or this report's author on a
later pass) should extend it, and there is a second row-shaped thing to watch:
`tests/skills/test_api_claims.py::test_no_invented_public_names` rejects backticked CamelCase spans
that are not real exports — a backticked `` `None` `` in that table fails it (I hit this and
reworded).

## What I could not do / did not do

- **`_primitives/di.py` untouched**, and T1's gate as literally written stays red (`0`). The
  registration is in `capability_names.py` (0 → 1). If the intended answer is different from
  "the task text names the wrong file", the correct fix is to correct `tasks.md`/`plan.md` — the
  same path appears in both.
- **`STATE.md` not updated.** It is not in my file list and rule 2 is absolute; the orchestrator
  owns it. The in-flight task is T3-done, wave 2 complete.
- **T4/T5 not started** (out of scope by instruction).
- **No git command was run**, so there are no commits for the sabotage restores; every sabotage was
  restored by copying the file back and re-running the test to green.

## Questions (not blocking; recorded so they do not resurface)

1. Should the name-set gate in T1 read `capability_names.py`? Both `tasks.md:33` and `plan.md:37`
   point at `di.py`. Whoever re-audits wave 0 will hit the same mismatch.
2. `Fingerprint.decides` is not in `contracts.md`'s "Unchanged" list implications for `func builtin
   info` / MCP job schemas — declaration fields are not part of the job input schema, so nothing
   was needed, but ADR-010 is the file to check if a surface ever starts publishing declarations.
3. An opted-in job that runs does **not** rewrite its fingerprint record (the decision was
   discarded, exactly as `force_fresh` discards it). That is consistent with `force_fresh` and with
   §3.3, but it means a `decides=True` job keeps re-running the body every invocation as long as
   its declared inputs are unchanged. Reading the verdict is cheap; the body is not. Worth a line in
   T4's guide.

## Full verification block — added mid-assignment (rule change)

Both commands were run once each, as instructed, after all iteration was finished.

### 1 · `uv run pytest examples/ -q`

```
$ uv run pytest examples/ -q
exit=0
........................................................................ [ 37%]
........................................................................ [ 74%]
..................................................                       [100%]
194 passed in 124.62s (0:02:04)
```

Green. **This matters for T4's AC-8** (`uv run pytest examples/ -q -k self_caching`), whose gate currently
reads `no tests ran` — the suite runs, it is 194 tests, and nothing in it regressed.

### 2 · `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q`

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
exit=1
bringing up nodes...
...
=========================== short test summary info ============================
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_empty_state - AssertionError: assert False
 +  where False = <function snap_compare.<locals>.compare at 0x7f7db5f0e7a0>(FunctualizeInlineTUI(title='FunctualizeInlineTUI', classes={'-dark-mode'}, pseudo_classes={'nocolor', 'dark', 'focus'}), terminal_size=(120, 40))
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_ready_bar - AssertionError: assert False
 +  where False = <function snap_compare.<locals>.compare at 0x7f7db4dce020>(FunctualizeInlineTUI(title='FunctualizeInlineTUI', classes={'-dark-mode'}, pseudo_classes={'nocolor', 'dark', 'focus'}), run_before=_ready_bar, terminal_size=(120, 40))
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_panel_ring_open - AssertionError: assert False
 +  where False = <function snap_compare.<locals>.compare at 0x7f7db5385080>(FunctualizeInlineTUI(title='FunctualizeInlineTUI', classes={'-dark-mode'}, pseudo_classes={'nocolor', 'dark', 'focus'}), run_before=_panel_ring_open, press=['ctrl+e'], terminal_size=(120, 40))
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_modal_open - AssertionError: assert False
 +  where False = <function snap_compare.<locals>.compare at 0x7f7db4d34680>(FunctualizeInlineTUI(title='FunctualizeInlineTUI', classes={'-dark-mode'}, pseudo_classes={'nocolor', 'dark', 'focus'}), run_before=<function test_snapshot_modal_open.<locals>._open_modal at 0x7f7db4fd4860>, terminal_size=(120, 40))
FAILED tests/core/test_command_registration_properties.py::TestCommandNameValidation::test_invalid_names_raise_value_error - TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]
FAILED tests/cli/test_stdin_integration_unit.py::TestTtyRequiredNoDefault::test_tty_unresolved_raises_system_exit - Failed: DID NOT RAISE <class 'SystemExit'>
FAILED tests/cli/test_stdin_integration_unit.py::TestTtyRequiredNoDefault::test_tty_none_cli_value_raises_system_exit - Failed: DID NOT RAISE <class 'SystemExit'>
FAILED tests/cli/test_stdin_integration_unit.py::TestTtyRequiredNoDefault::test_error_message_names_the_parameter - Failed: DID NOT RAISE <class 'SystemExit'>
FAILED tests/cli/test_stdin_integration_unit.py::TestTtyWithDefault::test_resolve_stdin_params_raises_for_tty_regardless_of_defaults - Failed: DID NOT RAISE <class 'SystemExit'>
FAILED tests/discovery/test_sync_reconciliation_property.py::TestSyncReconciliation::test_new_files_added_alongside_existing_valid_entries - TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]
FAILED tests/core/test_shutdown_properties.py::TestShutdownReverseOrderProperty::test_order_preserved_despite_exceptions - TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]
FAILED tests/pipeline/test_exit_codes.py::TestPipelineExitBehaviour::test_a_closed_pipe_exits_zero_and_quietly - AssertionError: Plugin 'functualize-http' took 144ms to load (budget: 50ms). Consider deferring heavy imports to __call__() or first use.
  
assert "Plugin 'func...or first use." == ''
  
  + Plugin 'functualize-http' took 144ms to load (budget: 50ms). Consider deferring heavy imports to __call__() or first use.
FAILED tests/pipeline/test_builtin_history.py::TestBothNamespaces::test_a_nonzero_shell_exit_is_shown[func] - AssertionError: assert 'false' in ''
FAILED tests/core/test_state_properties.py::TestAppStateThreadSafety::test_concurrent_reset_with_get_set_no_exceptions - AssertionError('Thread errors: [BrokenBarrierError(), BrokenBarrierError(), BrokenBarrierError()]\nassert [BrokenBarrie...arrierError()] == []\n  \n  Left contains 3 more items, first extra item: BrokenBarrierError()\n  \n  Full diff:\n  - []\n  + [\n  +     BrokenBarrierError(),\n  +     BrokenBarrierError(),\n  +     BrokenBarrierError(),\n  + ]') [single exception in FlakyFailure]
FAILED tests/discovery/test_cache_filter_awareness.py::TestCacheInspectionIsNonDestructive::test_cache_show_leaves_a_matching_cache_byte_identical[func] - AssertionError: fixture must have produced a cache
assert False
 +  where False = exists()
 +    where exists = PosixPath('/tmp/pytest-of-viltohmyst/pytest-62/popen-gw0/test_cache_show_leaves_a_match0/project_1/.functualize/cache.json').exists
FAILED tests/discovery/test_warm_boot_zero_imports_property.py::TestWarmBootZeroImports::test_warm_boot_returns_all_cached_descriptors_without_imports - TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]
FAILED tests/plugins/test_mcp_workflow_tools.py::TestResumeWorkflow::test_incomplete_input_drafts_and_does_not_advance - TypeError: 'NoneType' object is not subscriptable
FAILED tests/test_auto_scope.py::TestExplicitScopeIdReuse::test_explicit_scope_id_reuses_existing_scope - TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]
FAILED tests/workflow/test_launch_validation.py::TestParityWithAPlainJob::test_the_message_survives_a_warm_boot - TypeError: 'NoneType' object is not subscriptable
FAILED tests/workflow/test_wf_flags_dispatch_matrix.py::TestInputRequiresResume::test_retry_epilogue_without_resume_is_a_usage_error - assert 1 == 2
 +  where 1 = CompletedProcess(args=['uv', 'run', '--project', '/home/viltohmyst/code/raicing-ai/functualize/.worktrees/pi-parity', ...rsion_str.split(".")\n            ^^^^^^^^^^^^^^^^^\nAttributeError: \'NoneType\' object has no attribute \'split\'\n').returncode
ERROR tests/core/test_app_extensions.py::TestScopeRegistry::test_create_workflow_scope_with_metadata - TypeError: 'NoneType' object is not subscriptable
20 failed, 11185 passed, 140 skipped, 3090 warnings, 1 error in 1634.24s (0:27:14)
```

`20 failed, 11185 passed, 140 skipped, 1 error`. None of the 21 is in a file this change touches, and **every one that could be re-run passes alone**. Triage, per the rule ("re-run it alone before reporting it, and say which of the two it was"):

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -q -p no:cacheprovider <14 node ids + the whole stdin file>
1 failed, 27 passed, 1 skipped in 23.10s
```

| Failures | Re-run alone | Verdict |
|---|---|---|
| 4 × `tests/_cli/test_snapshot_baseline.py` | `env -u NO_COLOR TERM=xterm-256color uv run pytest --run-slow tests/_cli/test_snapshot_baseline.py` → `4 passed in 2.53s` | **environment** — the shell's `NO_COLOR=1`/`TERM=dumb`. Documented in RULES as known-red. |
| 4 × `tests/cli/test_stdin_integration_unit.py::TestTtyRequiredNoDefault` / `TestTtyWithDefault` | pytest can no longer collect them: `ERROR: not found: …::TestTtyRequiredNoDefault (no match in any of [<Module …>])` | **superseded, not mine** — another agent rewrote that file at **10:25:28** (after my run finished); those classes are gone. The current file: `14 passed in 0.09s`. |
| 6 × `TypeError("'NoneType' object is not subscriptable") [single exception in FlakyFailure]` + `test_mcp_workflow_tools.py` + `test_launch_validation.py` (also `'NoneType' object is not subscriptable`) | passed in the serial re-run | **artifact of `-n auto`** — every one carries xdist's `[single exception in FlakyFailure]` marker, the shape a worker crash takes under load. |
| `test_state_properties.py::…concurrent_reset…` — `BrokenBarrierError` | passed serially | **artifact of `-n auto`** — a barrier timing out under CPU saturation, by its own error type. |
| `test_wf_flags_dispatch_matrix.py::…` — `AttributeError: 'NoneType' object has no attribute 'split'` inside a `uv run` subprocess | passed serially | **artifact of `-n auto`** — the subprocess's interpreter was importing a tree that another agent was writing to. |
| `test_exit_codes.py::…a_closed_pipe_exits_zero_and_quietly` | `uv run pytest --run-slow <that node>` alone, **twice** → `1 passed` / `1 passed` | **artifact of the environment, twice over** — in the parallel run it failed on the plugin-load budget (`Plugin 'functualize-http' took 144ms to load (budget: 50ms)`, a wall-clock budget under CPU contention); in the serial re-run it failed on `stderr.strip() == ""` where the stderr was uv's own re-sync chatter (`Uninstalled 2 packages … warning: Failed to hardlink files`). Passes alone both times; nothing in the job's own output either time. |
| `test_cache_filter_awareness.py::…fixture must have produced a cache`, `test_command_registration_properties.py`, `test_shutdown_properties.py`, `test_sync_reconciliation_property.py`, `test_warm_boot_zero_imports_property.py`, `test_auto_scope.py`, `test_app_extensions.py` | all passed serially | **artifact of `-n auto`** (same `FlakyFailure`/thread/venv-churn family). |

Two defects the rule change was written for — the four `--run-slow`-only files and the examples
suite — are covered above: examples are green, the slow-only files ran, and the one repeated slow
failure is uv's own stderr.

## Concurrency caveat

Three other agents were writing this worktree while this ran (`_app/boot.py`, `app/utils.py`,
`_types/protocols.py`, `_types/errors.py`, `_engine/agent_providers.py`, `_engine/capabilities/invoke.py`
all changed between 09:22 and 09:31, by their mtimes). Two consequences for a reader:

- The **whole-suite** numbers above were taken against a tree that was moving. The evidence for
  *this* change is the targeted runs plus the sabotages, all of which were green at write time.
- `uv run ruff format src/ tests/` was run in **write** mode (as `AGENTS.md` prescribes). The tree
  was already formatted when I started (`1108 files already formatted`), so it was a no-op on
  everything but my own files — but it could not have been a no-op on another agent's file that was
  mid-edit at that instant.
- **As of the last check on this tree, `uv run ruff check src/ tests/ plugins/` is red — on a file
  that is not mine.** `tests/plugins/test_three_doors_agree.py:35` `TC001 Move application import
  'functualize.types.RunRequest' into a type-checking block`. That file's mtime is **10:22:47**,
  i.e. it was created by another agent *during* my slow run, after my last green lint pass. Narrowed
  to my scope: `uv run ruff check tests/execution/ src/functualize/` → `All checks passed!`. I did
  not fix it (rule 2: not my file); the orchestrator should.

## Verdict table

| task | done? | gate before | gate after |
|---|---|---|---|
| T1 | yes | `freshness.py` absent; name count `0` | file present, `CapabilitySpec(` = `1`; name count `1` (`capability_names.py`; `di.py` stays `0`) |
| T2 | yes | `preflight_bind` count `0` | `1`; recompute-pattern count `0`; sabotage fails both cold and warm tests |
| T3 | yes | `decides` count `0`; override at `1120`; early return at `1124` | `decides` count `8`; override at `1134` (one line, same block); early return at `1142`, text unchanged; `_decides = True` sabotage fails the default-path test |

Both full-suite commands required by the rule change were run once, at the end, and are pasted in
"Full verification block" above: `examples/` is **green** (194 passed), the slow/Hypothesis suite is
red only on the four documented environment reds and on `-n auto`/shared-venv artifacts, every one
of which passes when re-run alone. No failure in either run names a file this change touches.

Final state of my own scope on the current tree: `14 passed` (both new test files), `ruff check
tests/execution/ src/functualize/` clean, `mypy src/` clean, `lint-imports` 6/6, `decides` count
`8`, `preflight_bind` count `1`. The one tree-wide lint error is in another agent's file — see the
concurrency caveat.
