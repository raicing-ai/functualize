# Wave 5/6/7 Report — T11, T12, T13, T14, T15 (`adjacent-defects`)

Agent executing waves 5–7 on worktree `agent-f8-adjacent-w567`, branch
`agent/f8-adjacent-w567`, in the order the brief gave them. **No git command was
run.** Every pasted block below is that command's own output, from this worktree.

Scope held to each task's `**Files:**` line, plus — per rule 2's second clause —
`tests/discovery/test_discovery_failures.py`, which **failed because of T13's
change** (it pinned the defect). That is the only file outside a task's list.

---

## Retrieval check (run first, as instructed)

```
$ ls graphify-out/graph.json .serena/project.yml && du -sh .zvec-grep
.serena/project.yml
graphify-out/graph.json
72M     .zvec-grep
```

All three are present and the orchestrator's setup survived. `zvec-grep` was not
needed for waves 5–7: every claim here is about code, and the falsifiers are
`rg`/`inspect`/a live run rather than prose. `graphify`/serena likewise unused.

---

## Environment finding, and why it matters for this report

This worktree had **no `.venv`** when I arrived; the first `uv run` created one
with the default dependency set — **without the `cli`/`all` extras**. That
produced a first broad run with **24 failures**, none of them code:

```
$ uv run pytest tests/cli tests/_cli tests/group_options -q -p no:randomly
24 failed, 2895 passed, 583 skipped, 1 warning in 630.50s
```

Triage, all reproduced by import:

```
$ .venv/bin/python -c "import textual_autocomplete, functualize_inline"
ModuleNotFoundError: No module named 'textual_autocomplete'
ModuleNotFoundError: No module named 'functualize_inline'
```

- **22 of the 24** are those two missing packages: 17 raise
  `AttributeError: '_DropdownItemStub' object has no attribute …`
  (`smart_bar_autocomplete._make_dropdown_item` falls back to the stub when
  `functualize_autocomplete` cannot define `FunctualizeDropdownItem`, which it
  only defines inside `try: from textual_autocomplete import …`), and 5 assert
  `'functualize-inline' in …` on `builtin plugin list`.
- 1 is the documented `NO_COLOR`/`TERM=dumb` snapshot known-red
  (`test_snapshot_modal_open`).
- 1 is
  `tests/cli/test_info_subcommands.py::test_help_epilog_heading_is_at_the_left_margin[app]`
  — which I had separately proved *not mine* by reverting my T11 hunk and
  watching it still fail — and it was **also** this artefact: the missing plugin
  is what leaves the app's help with no unpanelled command, and therefore no
  `Commands:` heading for the test to find.

Fixed the way CI does it, then re-verified:

```
$ uv sync --all-packages --all-extras
$ uv run --all-extras pytest tests/_cli/test_shell_mode.py tests/_cli/test_plugin_cmd.py \
    tests/cli/test_info_subcommands.py tests/_cli/test_self_management_surfaces.py \
    tests/_cli/test_inline_tui_v2_autocomplete_integration.py -q -p no:randomly
224 passed, 9 skipped in 39.78s
```

**Every command in this report was run with `uv run --all-extras`** (bare
`uv run` re-syncs and removes the extras again). A stale venv in this worktree
will reproduce those 24 failures and they are not code.

---

## T11 · An enum parameter arrives as its enum (#38)

**Changed:** `src/functualize/app/adapters/click_params.py`, 1498 → **1528**
lines (+30).

- `_EnumChoice(click.Choice)` — new, `:112-139` (+28): renders the member values
  and converts the chosen one back by the **rendered spelling** (`{str(m.value): m}`,
  not `Enum(value)`, because an int-valued enum renders `"1"`), and returns a
  value that is already a member untouched, so a signature default
  (`color: Color = Color.RED`) survives click's own choice check.
- `_click_type_for`'s enum branch, `:166-167`: `click.Choice(choices)` → `_EnumChoice(inner)`
  (2 lines → 1), plus one docstring bullet reworded.

**Test (new):** `tests/cli/test_enum_parameter_roundtrip.py`, 97 lines, 2 tests.
`func paint.py paint red` (single-file → the eager builder) and
`app.execute(request_for("paint", color=Color.RED))`, both asserted against
`body=Color:<Color.RED: 'red'>` — and the CLI half compared against the
programmatic half rather than against a literal, because the programmatic path
was never broken and is the calibration.

**Gate** — `rg -c 'click\.Choice' src/functualize/app/adapters/click_params.py`

```
$ rg -c 'click\.Choice' src/functualize/app/adapters/click_params.py
4
$ rg -n 'click\.Choice' /tmp/t11/click_params.before.py      # pre-change copy
117:    - Enum → ``click.Choice`` of member values.
137:        return click.Choice(choices), False, False
239:    ``click.Choice``; everything else routes through the shared
243:        return click.Choice(field.choices or []), False, False
```
- before: `4` · after: `4` — **unchanged, exactly as the task predicted** ("the
  count is not the gate; the test is"). The removed render site is replaced by
  the class declaration, which is the one line that still says `click.Choice`.

**Reproduced first (real test, before the fix):**

```
$ uv run pytest tests/cli/test_enum_parameter_roundtrip.py -q -p no:randomly
E  assert "body=str:'red'" == "body=Color:<...r.RED: 'red'>"
2 failed, 2 skipped
```

**Sabotage** (`return super().convert(...)` instead of the member lookup):

```
$ uv run pytest tests/cli/test_enum_parameter_roundtrip.py -q -p no:randomly
FAILED …::test_the_cli_delivers_the_member[func] - assert "body=str:'red'" == "body=Color:<...r.RED: 'red'>"
FAILED …::test_the_cli_and_the_programmatic_path_agree[func] - assert "body=str:'red'" == "body=Color:<...r.RED: 'red'>"
2 failed, 2 skipped in 0.53s
```
Restored by editing the file back; re-run green (below).

**Verify:**

```
$ uv run --all-extras pytest tests/cli/test_enum_parameter_roundtrip.py \
    tests/adapters/test_click_params_parity.py tests/adapters/test_surface_gate.py \
    tests/config/test_click_builder_agreement.py tests/cli/test_parameter_types.py -q -p no:randomly
83 passed, 2 skipped in 5.17s
```
The frozen typer-parity snapshot in `test_click_params_parity.py` is **unchanged
and passing**: `click.Choice.__repr__` hardcodes `"Choice({choices})"`, so the
subclass renders `Choice(['red', 'green'])` exactly as before — the change is
behaviour, not shape.

**Reachability:** `create_job_click_command` / `create_job_command` /
`_option_from_marker` / `build_click_params` all route through `_click_type_for`;
proven by breaking the conversion and watching the named tests fail.

**Could not do — Finding F1, see below:** the app entry point's **warm** path
renders the descriptor's choices, a second site that needs files outside T11's
list.

---

## T12 · The unknown-command explanation reaches an app's own entry point (#37)

**Changed:** `src/functualize/app/adapters/cli.py`, 1684 → **1695** lines (+11).

`CliAdapter.__call__` chose the group class conditionally —
`FallbackGroup if self._fallbacks else NormalizingGroup` — so an app built
without a fallback chain got a plain group, click raised `NoSuchCommand` during
resolution, and standalone mode rendered it before `_show_command_not_found`
ever ran. Now it is always `FallbackGroup`; an empty chain falls through
`_try_discovered_job` to `_show_command_not_found`, which is exactly the path a
wired chain reaches when nothing matches.

**Test (new):** `tests/cli/test_unknown_command_parity.py`, 99 lines, 6 tests ×
2 surfaces (12). No `surfaces` marker — the point is that the same body passes
on both, and the `app` half is the one that used to fail.

**Gate:** the task defines none; *"the test is [the gate]"*.

**Before** (the sabotage is the old conditional; same command):

```
FAILED …::test_it_names_the_failed_file_and_the_reason[app]
  assert 'failed to load, so the job it defines is missing' in "⚠ needs_dep.py not loaded — …\nUsage: app.py [OPTIONS] COMMAND [ARGS]...\n\nError: No such command 'fetch'.\n"
FAILED …::test_it_is_not_clicks_own_usage_error[app]        ('No such command' is contained here)
FAILED …::test_an_unattributable_name_gets_the_generic_note[app]
FAILED …::test_the_generic_note_does_not_claim_a_load_failure[app]
FAILED …::test_a_typo_exits_one[app]                        assert 2 == 1
5 failed, 7 passed in 1.22s
```
- before: **5 of 12 failed** · after: **12 passed**

**After — the same project, the same typo, on both entry points** (`cli_run`,
stdout empty, `⚠` line elided):

```
[app]  before:  exit 2
  Usage: app.py [OPTIONS] COMMAND [ARGS]...
  Try 'app.py --help' for help.

  Error: No such command 'fetch'.

[app]  after:   exit 1
  Error: Command 'fetch' not found.
    needs_dep.py failed to load, so the job it defines is missing:
      No module named 'totally_missing_pkg'

  Run 'func --help' to see available commands.

[func] either:  exit 1
  Error: Unknown command 'fetch'.
    needs_dep.py failed to load, so the job it defines is missing:
      No module named 'totally_missing_pkg'
  Run 'func' to see all available commands.
```

The two surfaces still word the first line differently ("Unknown command" vs
"Command … not found" — each surface's own voice); the *explanation* is the same
function and now the same text on both, which is what AC-12 asks for. Exit 1
matches `func`.

**Sabotage:** the run above; restored by editing the file back, re-run green:

```
$ uv run --all-extras pytest tests/cli/test_unknown_command_parity.py tests/cli/test_discovery_failure_surfaces.py -q -p no:randomly
42 passed, 4 skipped in 4.26s
```

**Reachability:** `CliAdapter.__call__ → FallbackGroup.resolve_command →
_fallback_cmd → _run_fallback_chain → _show_command_not_found → explain_missing_job`.
Proven by the sabotage above.

---

## T13 · A parse failure survives a warm cache (#27)

**Changed:** `src/functualize/_discovery/cached_provider.py`, now **1081**
lines (+22: one import, the *"A negative the filter could not decide is not
persisted"* docstring paragraph, the nested collection scope around the
pre-filter call, and its `if undecided:` guard).

`_should_import_with_cache` persisted a negative pre-filter decision whatever
the pre-filter's answer meant. The AST filters answer `False` both for "nothing
to import here" and for "I could not read this file", so a `SyntaxError` was
judged once and skipped forever: the parse that *produces the report* never ran
again. The fix nests the pre-filter call in `collecting_discovery_failures()`,
forwards anything recorded to the scan's own collector
(`record_discovery_finding`), and **caches nothing** when the filter did not
reach a decision.

**Test (new):** `tests/discovery/test_parse_failure_persists.py`, 132 lines,
5 tests (one restricted to `func`, with its reason). Every test keeps the two
kinds of failure in view, because a "fix" that disabled decision caching
altogether would pass the first one alone.

**Test (updated, outside the task's list — it failed because of this change):**
`tests/discovery/test_discovery_failures.py`. Its
`test_a_cached_pre_filter_decision_reports_nothing_on_the_second_pass`
**pinned the defect** in its own docstring ("The blind spot, stated rather than
discovered in production … a skipped file records nothing"). The assertion moved
*toward the spec* — both passes now report `["SyntaxError"]` — and the test, the
class docstring and the name now describe the behaviour that ships.

**Reproduced first** (throwaway probe, `func` surface, one tree, two runs):

```
== RUN 1 [SyntaxError broken.py …, ModuleNotFoundError importer.py …]
== RUN 2 [ModuleNotFoundError importer.py …]
== pre_filter_decisions { "/…/broken.py": {"eligible": false, "source_mtime": …} }
```
Run 1 recorded the decision; run 2 reused it and never re-parsed. The `app`
surface never had the bug — its provider runs without a pre-filter chain and so
caches no decision at all (measured: `entries 2`, `decisions {}`).

**Gate:** the task's gate is the test ("reproduce the asymmetry first").

**Sabotage** (`undecided: list[Any] = []`, i.e. the pre-fix code):

```
FAILED …::test_a_parse_failure_is_reported_on_the_second_run[func]
  assert 'SyntaxError' in ['ModuleNotFoundError']
FAILED …::test_a_warm_run_reports_exactly_what_the_cold_one_did[func]
  Right contains one more item: {'error_type': 'SyntaxError', …}
FAILED …::test_a_file_nobody_could_read_is_never_a_cached_decision[func]
  AssertionError: assert 'broken.py' not in {'_helper.py', 'broken.py'}
3 failed, 6 passed, 1 skipped in 1.82s
```
Restored by editing the file back, green again:

```
$ uv run --all-extras pytest tests/discovery/test_parse_failure_persists.py -q -p no:randomly
9 passed, 1 skipped in 3.95s
$ uv run --all-extras pytest tests/discovery -q -p no:randomly
661 passed, 70 skipped in 29.90s
```

And the counterfactual the fix had to keep, measured directly: a file the filter
*decided* about (`_helper.py`, rejected by name) is still cached —
`decisions {"_helper.py": false}` — while the unreadable one is not.

**Reachability:** `CachedDirectoryScanProvider.list_jobs → _should_import_with_cache
→ (pre-filter) → record_discovery_finding → the scan's collector → discovery_failures
→ builtin info / the unknown-command explanation`. Proven by the sabotage.

---

## T14 · Single-file mode stops executing CWD module code

**Changed:** `src/functualize/_cli/main.py`, 2186 → **2216** lines (+30).

`_handle_single_file` handed its app `auto_discover(cwd).job_sources`, which
includes the **working directory itself**, and the app then imports every module
that scan names — executing its top level. The app now gets those directories
minus the CWD entry (`JobSources(...)` rebuilt field by field; the file's own
functions are registered explicitly either way).

**Test (new):** `tests/cli/test_single_file_cwd_isolation.py`, 141 lines,
3 tests: the reported hijack, a silent neighbour (the claim is "stops executing
CWD module code", not "stops the one spelling that won the race"), and — in the
other direction — that the app still runs the discovery it was *given*
(`rc.invoke` into `.functualize/jobs`).

**Reproduced** (a `stray.py` whose module body ends in `app.cli_command()`):

```
== EXIT 1
== STDERR "Error: Command 'weather.py' not found.\n\nRun 'func --help' to see available commands.\n"
```
(The pre-T12 shape of the same hijack — before my T12 change — was click's
`Error: No such command 'weather.py'.` with **exit 2**, which is what the audit
recorded. T12 changed the wording of the symptom, not the defect.)

**After:** `EXIT 0`, `PLANNED` on stdout, `NEIGHBOUR RAN` absent.

**Gate:** the task defines none; the test is the gate.

**Sabotage** (`if single_file_sources.directories and False:`):

```
FAILED …test_a_stray_cli_does_not_hijack_the_invocation[func]
  AssertionError: STRAY RAN\nError: Command 'weather.py' not found.\n\nRun 'func --help' …
  assert 1 == 0
FAILED …test_an_unrelated_neighbour_is_not_executed[func]
  AssertionError: assert 'NEIGHBOUR RAN' not in 'FORECAST os…\nNEIGHBOUR RAN\n'
2 failed, 1 passed, 3 skipped in 2.96s
```
Restored by editing the file back; green:

```
$ uv run --all-extras pytest tests/cli/test_single_file_cwd_isolation.py \
    tests/cli/test_single_file_in_own_directory.py tests/cli/test_enum_parameter_roundtrip.py -q -p no:randomly
9 passed, 8 skipped in 2.06s
```

**Not withdrawn** — §3.2's narrower fallback was implementable. **The line it
draws, measured rather than asserted:** declared directories and directories a
configured `[discovery] scan_depth` reaches are still scanned (a stray one level
*below* CWD with `scan_depth = 1` still printed `STRAY RAN`, probe since
deleted); the implicit, un-configurable CWD scan is what goes. That boundary is
stated in the code comment at the change site, so it is a decision a reader can
see rather than a limitation they discover.

**0.3.0's fix and its regression test stay:** `_register_single_file_peers`'s
"already registered — skip" guard is untouched, and
`tests/cli/test_single_file_in_own_directory.py` runs green (above).

---

## T15 · Feature gate

### Static checks

```
$ uv run --all-extras ruff check src/ tests/ plugins/
All checks passed!
$ uv run --all-extras ruff format --check src/ tests/
1115 files already formatted
$ uv run --all-extras mypy src/
Success: no issues found in 335 source files
$ uv run --all-extras lint-imports
Peer layers are independent KEPT
Events depends on foundation only KEPT
Primitives import nothing internal KEPT
Types import nothing internal KEPT
Internal never imports public KEPT
_cli uses public API only KEPT

Contracts: 6 kept, 0 broken.
```

### Full slow suite (mandatory)

```
$ HYPOTHESIS_PROFILE=ci uv run --all-extras pytest --run-slow -n auto -q
11235 passed, 145 skipped, 3089 warnings in 796.02s (0:13:16)
EXIT=0
```

### Examples (mandatory)

```
$ uv run --all-extras pytest examples/ -q
194 passed in 162.86s (0:02:42)
EXIT=0
```

### Plugin suites (`tests/` and `plugins/` cannot be collected together — one at a time)

```
functualize-ai               17 passed
functualize-ai-pydantic       9 passed
functualize-aws              72 passed, 1 skipped
functualize-bitwarden        66 passed
functualize-flow-viz         25 passed
functualize-http             48 passed
functualize-inline           50 passed
functualize-lambda           44 passed
functualize-mcp              16 passed
functualize-state             6 passed
functualize-state-sqlite     80 passed
functualize-tasks            15 passed
functualize-tasks-local       7 passed
```

No known-red excluded anything: with the environment synced, the four
`test_snapshot_baseline` tests and the self-doctor test passed inside the full
run, so nothing was waved through as environmental.

### AC-1 … AC-14, each named

| AC | Reached by |
|---|---|
| AC-1 group-options conflict rendered | `tests/group_options/test_conflict_is_reported.py` (T9); `rg -c 'except GroupOptionsConflictError' src/` = 1 |
| AC-2 fingerprint + every caller supplies one | `tests/discovery/test_group_options_fingerprint.py`; four `src/` callers pass `discovery_hash_for(...)` — see **F2** for the missing coverage |
| AC-3 TYPE_CHECKING measurement recorded, flag unchanged | `contributor/architecture/layer-contract-blind-spot.md`; `exclude_type_checking_imports = true` still 1 |
| AC-4 `get_missing_required_args` / `omit_defaults` | deleted (T5); `rg` over `src/`, `plugins/` = 0 |
| AC-5 catalog events | deleted from the catalog (T6); `job.execute.error`/`tui.session.*` have no producer anywhere; `cli.parse.start` kept with its real producer |
| AC-6 `JobContext.deadline` | gone (T3); the 10 remaining `deadline` hits are unrelated local timeouts (`manifest.py`, `shell.py`, `state_format.py`) |
| AC-7 `_deposit` | gone from the MCP plugin (T4); the 6 remaining `_deposit` hits are the CLI's group-option depositor and two historical notes about the lift |
| AC-8 perf comment | `tests/perf/test_startup_budget.py` (T1) |
| AC-9 `guarded_execute` docstring | `app/_workflow_control.py` (T2) |
| AC-10 entry-point callers | `tests/primitives/test_entry_point_cache.py` pins the count (T7) |
| AC-11 enum arrives as the enum | `tests/cli/test_enum_parameter_roundtrip.py` — **for the eager renderer**; the warm descriptor renderer is **F1** |
| AC-12 unknown command on an app entry point | `tests/cli/test_unknown_command_parity.py` (this wave) |
| AC-13 parse failure on run 1 and run 2 | `tests/discovery/test_parse_failure_persists.py` + `tests/discovery/test_discovery_failures.py` (this wave) |
| AC-14 single-file not hijacked | `tests/cli/test_single_file_cwd_isolation.py` (this wave) — **not** withdrawn |

### Orphan scan over the symbols this feature touched

```
$ for n in _deposit get_missing_required_args omit_defaults deadline \
           tui.session.start tui.session.end job.execute.error; do … done
_deposit                     src=6 plugins=0     (group-option depositor + lift notes; not the MCP method)
get_missing_required_args    src=0 plugins=0
omit_defaults                src=0 plugins=0
deadline                     src=10 plugins=0    (unrelated local timeouts)
tui.session.start            src=0 plugins=0
tui.session.end              src=0 plugins=0
job.execute.error            src=0 plugins=4     (a consumer that no longer receives it)
```

Every deleted name is gone. The four live hits are all true where they stand:
`plugins/functualize-flow-viz/.../plugin.py:172` says in its own words that
`job.execute.error` "**cannot arrive**" but is still tolerated, and
`app/_workflow_resume.py:3` cites the MCP `_deposit` as the thing it was lifted
*out of*. New symbols: `_EnumChoice` → `_click_type_for`;
`discovery_hash_for` → four callers; `report_group_options_conflicts` →
`boot.py:718`; the single-file sources filter → the one call site.

### Sabotage: T10's fingerprint (T15's named item)

**Reader** — `if False and discovery_hash is not None …`:

```
FAILED tests/discovery/test_group_options_fingerprint.py::test_a_cache_from_another_filter_set_is_refused
FAILED tests/discovery/test_group_options_fingerprint.py::test_changing_a_discovery_filter_invalidates_the_section
2 failed, 2 passed in 0.61s
```
Restored by editing the file back.

**Call site** — dropped `discovery_hash=discovery_hash_for(app)` at
`_cli/main.py:979` (T10's own sabotage instruction: *"drop the fingerprint
argument at the call site; this test must fail"*) and ran the three areas that
own group options:

```
$ uv run --all-extras pytest tests/group_options tests/discovery tests/cli -q -p no:randomly
.......................................................................... [100%]
2443 passed, 415 skipped in 642.67s (0:10:42)
EXIT=0
```

**Nothing fails.** Restored by editing the file back. The reader is covered; its
four callers are not — **F2** below.

---

## Findings — things this wave could not do, or found on the way

### F1 · The warm app path renders the descriptor's enum choices — AC-11's other half

T11 fixes the renderer the task named (`_click_type_for`). There is a **second**
renderer, `_field_click_type` (`click_params.py:265-273`), used when a command is
built from a *cached descriptor* rather than a live signature — i.e. a project's
own `main.py` on any run after the first. Measured after all four fixes:

```
== app cold      exit 0  "body=Color:<Color.RED: 'red'>"          ← T11 fixed this
== app warm      exit 2  'Invalid value for \'{RED|GREEN}\': \'red\' is not one of \'RED\', \'GREEN\'.'
== app warm(name) exit 0 "body=str:'RED'"                          ← still a str
== func cold     exit 0  "body=Color:<Color.RED: 'red'>"
== func warm     exit 0  "body=Color:<Color.RED: 'red'>"
```

Two distinct defects share that site: the descriptor's `choices` are member
**names** (`_discovery/providers.py:426` uses `member.name`; the live path uses
`str(member.value)`), so a warm app **rejects the value spelling**; and nothing
converts even when it accepts. `func` never shows it — `_materialize_for_dispatch`
always hands `create_job_click_command` a live function.

Not fixed, deliberately: the fix needs `src/functualize/app/adapters/lazy_command.py`
(and/or `_discovery/providers.py`), neither of which is on T11's `**Files:**`
line, and `_discovery/providers.py` is T13's territory rather than T11's. Per
rule 2 I stopped instead of "just fixing" it. **AC-11 is therefore satisfied for
the eager renderer and not for the warm descriptor renderer.** The shape to fix
it: render values in `_field_click_type`, and convert after
`materialize_job` gives the lazy wrapper the live signature.

### F2 · T10's four call sites are wired but unverified

Dropping `discovery_hash=` at `_cli/main.py:979` — one of the four callers AC-2
requires — fails **no test** in `tests/group_options`, `tests/discovery` or
`tests/cli`. The unit test passes the argument itself, so it cannot notice. This
is T10's ownership, not T11–T14's, but T15 asks for the sabotage and this is its
result: the wiring half of AC-2 has no falsifier. The plugin caller
(`plugins/functualize-mcp/.../_translator.py:38`) still passes nothing — out of
this feature's `src/` scope, unchanged by the orchestrator's finish, and worth
one line in the follow-up.

### F3 · A docstring that became false when T12 landed

`tests/cli/test_discovery_failure_surfaces.py`'s
`TestTheUnknownCommandExplainsItself` carries a `@pytest.mark.surfaces("func")`
whose docstring explains the gap T12 just closed:

> *"a project's own `main.py` invokes click in standalone mode, so an
> unrecognized name is rendered by click's own `UsageError` before either
> reporter runs — the hint reaches `func` and the adapter's fallback chain, and
> not that path."*

That is no longer true. The class could drop the marker now; I did not touch it
(the file is not on any wave-5 file list, and the marker does not fail). Same
species as the `_catalog_entries.py` citation the orchestrator corrected after
wave 1 — reported, not fixed.

### F4 · Two smaller pre-existing mismatches, unchanged by this wave

- `docs/cli/discovery.md:251`'s Mode × Discovery matrix says `extra_directories`
  is "— Not used" in single-file mode. It was used before T14 and still is (T14
  removes only the CWD entry). Unrelated to AC-14; noted because T14 edited the
  line that implements it.
- `tests/_cli/test_key_handler_rebind_unit.py:45` still reads
  `MagicMock(spec_set=[] if False else None)`. Pre-existing (already flagged in
  W234's report), and the full suite is green with it.

### F5 · `tasks.md` was not edited

Not on any file list (W234 reported the same). T11–T14 each meet their own gate,
so all four would be `[x]`; T14 is **not** withdrawn. The one judgement the
orchestrator has to make from this report is whether T11's `[x]` should carry
F1's caveat, given AC-11's "on the CLI" is only true for the eager renderer.

---

## Questions (non-blocking, written down rather than asked)

1. Does T14's line — "declared directories and `scan_depth` subdirectories stay,
   the implicit CWD scan goes" — match the intent, or should single-file mode
   drop directory discovery entirely (`JobSources(directories=None)`)? I took
   §3.2's narrower fallback, and pinned the resulting behaviour in a test
   (`rc.invoke` into the project still resolves), so the choice is visible.
2. Should the app surface's unknown-command first line be unified with `func`'s
   ("Unknown command 'x'.")? AC-12 asks for the same *explanation*, which it now
   is; I left each surface's own voice alone rather than edit output no test
   asked me to change.
3. F1's warm-path fix is a real, user-visible defect (a valid CLI value rejected
   on the second run of an app entry point). It needs a decision on which
   distribution's file owns the coercion — `lazy_command.py` (adapter, converts
   after materialization) or `_discovery/providers.py` (emit values, leaving the
   class unknowable at build time).

---

## Summary

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T11 · enum arrives as its enum (#38) | `[x]` — gate green; AC-11's warm half is **F1** | `rg -c 'click\.Choice'` = 4; test: 2 failed | 4 (unchanged, as the task says); 2 passed. `83 passed, 2 skipped` with the parity/config neighbours |
| T12 · unknown-command explanation on an app (#37) | `[x]` | test: 5 failed / 12 | 12 passed |
| T13 · parse failure survives a warm cache (#27) | `[x]` | test: 3 failed / 10 (+ `test_discovery_failures.py` pinned the defect) | 9 passed, 1 skipped; `tests/discovery` 661 passed, 70 skipped |
| T14 · single-file stops executing CWD code | `[x]` — **not** withdrawn | test: 2 failed / 3 | 3 passed, 3 skipped |
| T15 · feature gate | `[x]` | — | ruff/format clean · mypy 335 files · `lint-imports` 6 kept · 11235 passed, 145 skipped · `examples/` 194 passed · all 13 plugin suites green · T10 sabotage caught in the reader, **not** at the call sites (F2) |
