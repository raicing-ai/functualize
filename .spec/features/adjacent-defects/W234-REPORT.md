# Wave 2/3/4 Report — T8, T9, T10 (`adjacent-defects`)

Agent executing waves 2, 3 and 4 on worktree `pi-parity`, in order. **No git command was run.**
Everything below was run in this worktree; each pasted block is that command's own output.

Scope held to the brief's file list: `contributor/architecture/layer-contract-blind-spot.md`
(new), `src/functualize/_app/boot.py`, `src/functualize/app/utils.py`,
`src/functualize/_discovery/cached_provider.py`, `tests/group_options/test_conflict_is_reported.py`
(new), `tests/discovery/test_group_options_fingerprint.py` (new) — plus, per rule 2's second
clause, `tests/group_options/test_group_options_discovery.py`, which asserted the old raise and
could not survive T9. **`pyproject.toml` was not edited** (§T8.5) and no `_cli/`, `_engine/`,
`_types/` or plugin file was touched (§T10.4).

Two things failed for reasons that are not this work's, and one is a task I could not finish:

| | |
|---|---|
| **T10 is partial, not done** | The reader takes a fingerprint; **no in-tree caller supplies one**. Five callers live in files outside the brief. Left unchecked; §T10.4 names them. |
| **A concurrent agent's edits broke the shared tree mid-run** | `RuntimeError: capability registry and INJECTED_PARAM_TYPE_NAMES disagree … ['Freshness']` — `Freshness` declared in `_engine`, absent from `_primitives/capability_names.py`. It appeared and disappeared between two runs of my suite (files stamped 09:25:32 and 09:25:53) and also fails `tests/cli/test_discovery_failure_surfaces.py`, which I do not touch. Not mine. |

---

## T8 · Record the layer-contract blind spot

**Changed:** `contributor/architecture/layer-contract-blind-spot.md` — **new, 259 lines.**
No code change: the flag stays on.

The document records what the six contracts do catch, what the flag hides (measured, AST-based),
the flip measurement with the raw chain table, why the flag stays on, a reviewer's checklist for
what no gate can see, and the re-measurement commands.

**Gate** — `test -f contributor/architecture/layer-contract-blind-spot.md && rg -c '47|125' …`

```
$ test -f contributor/architecture/layer-contract-blind-spot.md && echo "file present" \
    && rg -c '47|125' contributor/architecture/layer-contract-blind-spot.md
file present
4
```
- before: `file absent` (exit 1) · after: present, 4 matching lines (≥2 required)

**Gate — the flag is unchanged**
```
$ rg -c 'exclude_type_checking_imports = true' pyproject.toml
1
```
- before: `1` · after: `1` — the file was never opened for writing.

### T8.1 The census (what the flag hides)

Counted by AST walk — every `import`/`from … import` inside an `if TYPE_CHECKING:` guard, any
nesting, relative imports resolved:

```
internal=155 public_from_internal=27 public_from_public=11 other=92
```

`internal` = statements whose target is a `functualize._*` package (174 imported names).
**Only 8 of the 155 cross a boundary a contract would refuse as a direct edge** (5 package pairs:
`_cli → _types` 3, `_engine → _gate` 2, `_cli → _events`, `_engine → _config`, `_types → _events`).

### T8.2 The flip, measured against a config outside the tree

```
$ uv run lint-imports --config /tmp/blind-spot/importlinter.toml --no-cache
Peer layers are independent BROKEN
Events depends on foundation only KEPT
Primitives import nothing internal BROKEN
Types import nothing internal BROKEN
Internal never imports public BROKEN
_cli uses public API only BROKEN

Contracts: 1 kept, 5 broken.
```
20 import chains over 22 distinct module → module pairs. The mechanism is indirect composition,
not 22 direct violations: `_discovery.registry → app.core` (one hidden annotation-only import of
`FunctualizeApp`) produces five peer-layer violations because `app.core` imports nearly every
internal package at runtime; `_primitives.pre_filter → _types.protocols` is legal until
`_types.protocols → _types.interactivity → _events.bus` joins it.

### T8.3 Four recorded figures no longer reproduce

`spec.md` §1.4 / `tasks.md` T8 record **125** hidden imports, **47** violations, **all six**
contracts broken and a per-package breakdown. Re-run at this commit:

| Recorded | Re-measured 2026-09-10 |
|---|---|
| 125 hidden internal imports | **155** (tree grew: the layer-contract memory records 318 files / 816 dependencies, this run 333 / 1030) |
| 47 violations | **20 chains / 22 module pairs** |
| all six contracts broken | **5 of 6** — `Events depends on foundation only` KEPT (no `_events` module carries such an import today) |
| `_cli/tui/` 18, `_engine/` 8, `_types/` 7, `_app/` 6 | `_cli.tui` 4, `_engine.capabilities` 4, `_types.interactivity` 1, `_app.impl` 1 |

The conclusion survives unchanged (the hole is real, most hidden imports are legitimate
annotation-only references, the flag stays on); the magnitude had to be re-measured. The document
carries both columns and the exact commands, so the next reader can tell whether it grew.

### T8.4 Adjacent findings the measurement produced

- `functualize.ui` is a seventh package that **no contract names**, so `_cli/inline_tui.py:213`'s
  runtime `from functualize.ui import …` passes `_cli uses public API only` while the identical
  import from `functualize._types` fails it. Recorded in §9 of the document; needs its own
  decision, not a fix here.
- `contributor/architecture/codemaps/dependencies.md:25` says *"five contracts"*; there are six
  (the events contract and `_gate`'s membership are missing from its list).

### T8.5 Sabotage / cannot-do

A document has no production call path, so the substitute proof is the gate's own movement:
`rg -c '47|125'` on the file goes `absent` → `4`. **`pyproject.toml`'s comment ("annotated with
why", AC-3) was NOT added**: the file is not in my brief, and the brief assigns `pyproject.toml`
to no one — writing it while three agents edit this tree is exactly the collision rule 2 exists
to prevent. The *why* is in the document instead (§4). If the orchestrator wants the annotation,
it is one comment above line 234 pointing at the new file.

---

## T9 · A group-options conflict is rendered, not raised

**Changed:**
- `src/functualize/_discovery/cached_provider.py` — `_safe_import` docstring +3;
  `except GroupOptionsConflictError` block +14; new `_forget_source_file` +27. One line changed
  (the bare `_record_group_options_entries(...)` call became the `try:`).
- `src/functualize/_app/boot.py` — `import sys` +1; `_GROUP_OPTIONS_CONFLICT` +4; new
  `report_group_options_conflicts` +48; the step-8a call in `boot_standard` +2.
- `tests/group_options/test_conflict_is_reported.py` — **new, 235 lines** (10 tests: 3
  surface-parameterised × 2 + 4 provider-level).
- `tests/group_options/test_group_options_discovery.py` — the one test that pinned the raise
  rewritten (net +6), and its now-unused `GroupOptionsConflictError` import removed.

**Before** (real binary, `/tmp/conflict-proj`, two files binding `GroupOptions, group="deploy"`):

```
$ func hello
Traceback (most recent call last):
  …
  File "…/_discovery/cached_provider.py", line 916, in _record_group_options_entries
    raise GroupOptionsConflictError(
functualize._types.errors.GroupOptionsConflictError: Group 'deploy' has more than one
GroupOptions declaration: '…/jobs/_dup.py' and '…/jobs/_group.py'. …
EXIT=1
```

**After** (same project, cold and warm, real binary):

```
$ func hello
⚠ Group 'deploy' has more than one GroupOptions declaration: '…/jobs/_dup.py' and '…/jobs/_group.py'. A group's flags must be declared exactly once — merge them into a single class.
Error: Group 'deploy' has more than one GroupOptions declaration: '…/jobs/_dup.py' and '…/jobs/_group.py'. A group's flags must be declared exactly once — merge them into a single class.
EXIT=2
$ func hello          # warm
Error: Group 'deploy' has more than one GroupOptions declaration: '…/jobs/_group.py' and '…/jobs/_dup.py'. A group's flags must be declared exactly once — merge them into a single class.
EXIT=2
```

**Gate** — `rg -c 'except GroupOptionsConflictError' src/`

```
$ rg -l 'except GroupOptionsConflictError' src/
src/functualize/_discovery/cached_provider.py
$ rg -c 'except GroupOptionsConflictError' src/functualize/_discovery/cached_provider.py
1
```
- before: **no file matches** (every per-file count `0`, exit 1) · after: 1 file, count 1

### T9.1 The two halves and why they are where they are

**Provider** (`_safe_import`): the conflict is recorded with `record_discovery_failure` — the
same list, and the same vocabulary, that answers *"why is my job missing?"* for an unreadable
module and a job-name collision (ADR-018). Nothing raises.

**Boot seam** (`report_group_options_conflicts`, called from `boot_standard` step 8a): reads the
recorded failures off the pipeline's providers (`_cli/info.py:discovery_failures`' access shape),
prints each one to stderr and `raise SystemExit(ExitCode.USAGE)`. Boot is the only seam **both**
entry points share — `func` builds an app inside `_handle_job`; a project's own script builds one
under `CliAdapter` — which is why the render is there and not in a delivery layer.

Code: `USAGE` (2) is the table's *config error*, the same code
`app/adapters/cli.py:_print_validation_error` leads to for a bad job argument. The task says
"the discovery-failure exit code"; no such code exists in `_types/exit_codes.py`, and `USAGE` is
the comparable error's answer, so that is what I matched.

### T9.2 Decisions a reviewer should check

1. **Fatal, although ADR-018 is "reported, not fatal".** The spec asks for both ("joins ADR-018's
   reported-not-fatal surface" *and* "exits with the discovery-failure code"); they cannot both
   hold with the files in scope. I implemented the acceptance criterion: rendered + exit 2, with
   the *record* kept so the reason is available on the ADR-018 channel. Consequence, stated
   plainly: `func builtin info` and `func builtin self doctor` also stop with exit 2 in a
   conflicting project. Making the exit conditional on the run (fatal when a group's flags are
   actually resolved, reported otherwise) is the ADR-018-shaped alternative — it needs
   `_engine/executor.py:_resolve_group_options`, which another agent owns right now and which T9
   does not list.
2. **Both claimants are dropped, not one.** Which file the scan reaches first is set-iteration
   order, so resolving to the first would hand a different set of flags to each process
   (observed: the two runs above name the files in opposite orders). Dropping only the loser was
   implemented first and failed my own warm-run test in the other hash order. Both files are
   forgotten — jobs, display entries, declarations, and the contested path — which is also what
   keeps the conflict loud on *every* boot: a retained job entry would put the file in
   `_known_source_files`, the next boot would validate it by mtime, match, and never re-import it,
   and the group would silently lose its flags with no message.
3. **The `⚠` line above the error is deliberate.** It is the provider's own signal for a scan
   that is not followed by a boot (a programmatic `list_jobs()`, `build_discovery_cache_provider`)
   and it is the repo's shape for a scan finding (`⚠ <file> not loaded — …`). In the CLI it reads
   as the same sentence twice; if that is judged worse than the signal, `logger.warning` here is
   the one line to change.
4. **Eager boot never reaches this.** `DirectoryScanProvider` does not extract or record group
   options at all — the section is written only by the cache-first provider — so a `lazy=False`
   host has no conflict to detect. Pre-existing, unchanged by this task, worth knowing.

### T9.3 Sabotage (required: T9 wires behaviour)

Broke the boot seam — the production call path — by neutering the call:

```python
    if False:  # SABOTAGE
        report_group_options_conflicts(app)
```
```
$ uv run pytest tests/group_options/test_conflict_is_reported.py -q -p no:randomly
_ TestTheRenderedError.test_it_names_the_group_and_both_files_and_exits_usage[func] _
>       assert result.exit_code == _USAGE, result.stderr
E       AssertionError: ⚠ Group 'deploy' has more than one GroupOptions declaration: '…/_group.py' and '…/_dup.py'. …
E       assert 0 == 2
_ TestTheRenderedError.test_it_names_the_group_and_both_files_and_exits_usage[app] _
E       assert 0 == 2
```
(and the same again for `test_it_is_not_a_traceback` / `test_a_warm_run_reports_it_again`)

Restored by editing the file back, then green:

```
$ uv run pytest tests/group_options/ -q -p no:randomly
208 passed, 19 skipped in 11.78s
```

### T9.4 Verify

```
$ uv run pytest tests/group_options/test_conflict_is_reported.py tests/group_options/test_group_options_discovery.py -q -p no:randomly
20 passed in 2.30s          # × PYTHONHASHSEED=0/1/2 → 20 passed each time
$ uv run mypy src/functualize/_discovery/cached_provider.py src/functualize/_app/boot.py
Success: no issues found in 3 source files
$ uv run ruff check … && uv run ruff format --check …
All checks passed! / 17 files already formatted
```

---

## T10 · The group-options cache section takes a fingerprint — **PARTIAL**

**Changed:** `src/functualize/app/utils.py` — `read_group_options_from_cache` gains
`discovery_hash: str | None = None` (+1 line), an `Args:` entry (+11), a header check
(+7, comment included), a reworded `Returns:` (+6): 46 → 72 lines.
`tests/discovery/test_group_options_fingerprint.py` — **new, 143 lines** (4 tests).
No other file.

### T10.1 The staleness, reproduced first

Throwaway script (never committed), the public writer with one filter set, the shipped reader
call shape:

```
$ uv run python /tmp/t10/repro.py
cache header fingerprint: sha256:0f61ce0947dd7c86a6575010fa43fdb9067a556f0177599191d451f140bea33c
caller A fingerprint     : sha256:0f61ce0947… -> equal: True
caller B fingerprint     : sha256:da5f26abe7611fed2d13b9aafcb75c632181848a8ff8d502c20c4f8d4cb4114f -> cache is stale for B: True
served under a stale header: True groups: ['deploy']
```

That is the defect: the file says it was written under filter set A, the caller is running under
B, and the section is served anyway — the one cache section with no fingerprint of its own.

Then the test, before the fix:

```
$ uv run pytest tests/discovery/test_group_options_fingerprint.py -q -p no:randomly
E  TypeError: read_group_options_from_cache() got an unexpected keyword argument 'discovery_hash'   (×2)
E  AssertionError: assert None == 'sha256:da5f26ab…'                                                (×1)
3 failed, 1 passed in 0.24s
```

After the fix:

```
$ uv run pytest tests/discovery/test_group_options_fingerprint.py -q -p no:randomly
4 passed in 0.16s
```
```
$ uv run python /tmp/t10/repro.py | tail -3      # the same cache, a reader that passes one
--- after the fix ---
read with caller A's fingerprint: True
read with caller B's fingerprint: None
```

**Gate** — `rg -n 'def read_group_options_from_cache' -A3 src/functualize/app/utils.py | rg -c 'discovery_hash'`

```
$ rg -n 'def read_group_options_from_cache' -A3 src/functualize/app/utils.py | rg -c 'discovery_hash'
1
```
- before: `0` · after: `1`

**Sabotage.** The task's instruction is *"drop the fingerprint argument at the call site; this
test must fail"* — there is no in-tree call site that passes one (§T10.4), so I sabotaged the
production comparison instead:

```python
    if False and data.get("discovery_hash") != discovery_hash:
```
```
$ uv run pytest tests/discovery/test_group_options_fingerprint.py -q -p no:randomly
FAILED …::test_a_cache_from_another_filter_set_is_refused
FAILED …::test_changing_a_discovery_filter_invalidates_the_section
E       AssertionError: assert {'deploy': GroupOptionsSpec(group='deploy', …)} is None
2 failed, 2 passed in 0.25s
```
Restored by editing the file back; green again (`212 passed, 19 skipped` for
`tests/discovery/test_group_options_fingerprint.py tests/group_options/`).

### T10.2 What the parameter means

`discovery_hash` is the caller's own fingerprint (`discovery_hash_from_config`). A file whose
header records another one was written by a scan the caller is not repeating, so its
`group_options` section describes a filtered tree the caller does not have → `None`, the same
answer a format-version mismatch gives, and the documented "fall back to scanning" contract every
caller already handles. `None` passed in means *cannot know* and skips the check — the pre-existing
behaviour, kept deliberately because `contracts.md` §1 names it as this feature's one shim.

### T10.3 Verify

```
$ uv run pytest tests/discovery/test_group_options_fingerprint.py tests/group_options/ -q -p no:randomly
212 passed, 19 skipped in 11.46s
$ uv run mypy src/functualize/app/utils.py
Success: no issues found
$ uv run ruff check … && uv run ruff format --check …
All checks passed! / 2 files already formatted
```

### T10.4 **What I could not do: the five callers**

AC-2 is *"`read_group_options_from_cache` accepts a fingerprint **and every caller supplies
one**"*. The first half is done and tested. The second half needs five production files, none of
them in my brief:

| caller | note |
|---|---|
| `src/functualize/_cli/main.py:979` (`_dispatch_group`) | app boots before it, so the app's discovery config is in scope |
| `src/functualize/_cli/completions/data.py:140` | same (`func_app` is a parameter) |
| `src/functualize/_cli/tui/cli_arg_parser.py:120` | same |
| `src/functualize/app/adapters/cli.py:544` | `register_discovered_jobs(cli_group, app)` |
| `plugins/functualize-mcp/src/functualize_mcp/_translator.py:38` | plugin distribution |

Per rule 2 I stopped instead of "just fixing" them: they are outside my file list, the plugin is
another distribution's file, and three agents are editing this tree. **T10 is therefore left
unchecked — the reader is fixed and proven; the wiring is not.** A follow-up task needs: for each
caller, compute the fingerprint from the discovery config in scope (`build_job_filter` is the
existing precedent for a public re-export of a `_discovery` computation) and pass it. The
interesting one is `_cli/tui/cli_arg_parser.py`, which cannot import `_discovery` at all; the
precedent to copy is `functualize.app.utils.build_job_filter`'s re-export seam. Until then the
parameter is exercised only by tests and out-of-tree callers, which is a wiring gap and is
reported as one rather than presented as done.

The alternative design — the reader resolving the config itself — was tried for the sibling
reader and reverted (`.spec/STATUS.md`: teaching `read_routing_names_from_cache` the fingerprint
"cost a `resolve_cli_config()` call inside a read documented at a ~3ms budget for behaviour no
test could observe"). I did not repeat it.

---

## Whole-feature verification (this agent's share)

```
$ uv run ruff check src/ tests/ plugins/
All checks passed!
$ uv run ruff format --check src/ tests/
1110 files already formatted
$ uv run mypy src/
Success: no issues found in 335 source files
$ uv run lint-imports
Contracts: 6 kept, 0 broken.
```

```
$ uv run pytest tests/discovery tests/group_options tests/cli tests/observability tests/perf -q -p no:randomly
2471 passed, 469 skipped in 132.21s
```
(No failures. `tests/_cli/test_snapshot_baseline.py` and the self-doctor known-reds are in
`tests/_cli`, outside this selection, and the wave-0 report already documents both.)

Reachability, per `CONSTITUTION.md`:

| Added | Production call path |
|---|---|
| `report_group_options_conflicts` | `FunctualizeApp.__init__ → boot_standard → resolve_and_register_jobs → report_group_options_conflicts` — proven by neutering the call and watching the T9 tests fail |
| the provider's record | `CachedDirectoryScanProvider.list_jobs → _safe_import → except GroupOptionsConflictError → record_discovery_failure` — asserted directly in `test_conflict_is_reported.py::TestTheProviderRecord` |
| `read_group_options_from_cache`'s fingerprint | **none yet** — §T10.4 |
| the document | `contributor/architecture/`, read by humans; no code path by design |

## Full-suite verification (the rule change: run once, at the end)

Both commands run verbatim, `examples/` first, alone:

```
$ uv run pytest examples/ -q
194 passed in 124.62s (0:02:04)
```

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
21 failed, 11182 passed, 141 skipped, 3090 warnings, 2 errors in 1614.95s (0:26:54)
```

**Then re-run, because every failure passed alone and the tree is shared:**

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
11208 passed, 140 skipped, 3087 warnings in 367.48s (0:06:07)
```

`EXIT=0`. The second run is 4.4× faster (6:07 vs 26:54). The first ran while other agents'
`uv run` invocations were churning the shared venv and CPU — the failures below are that churn,
not the code; the second had the machine largely to itself. The pass/skip counts drift between the
two (11205 vs 11208, 141 vs 140) because other agents' files landed in between; that is the tree,
not this work.

### Triage of the first run's 21 failures + 2 errors — all 23 passed alone

| Failing | # | Mechanism (evidence) | Alone |
|---|---|---|---|
| `_cli/test_snapshot_baseline.py` ×4 | 4 | The documented known-red: the agent shell's `NO_COLOR=1` / `TERM=dumb` moves the palette (`pseudo_classes={'nocolor', 'dark', 'focus'}` in the failure output) | `4 passed`, twice: with the shell's own env **and** with `env -u NO_COLOR TERM=xterm-256color` |
| `test_auto_scope` ×3, `discovery/test_warm_boot_zero_imports_property` ×2, `discovery/test_cache_manager_edge_cases` ×1, `core/test_property_constructor_defaulting` ×1, `core/test_plugin_registration_properties` ×1, `context/test_invoke_properties` ×2, `_cli/test_self_manage` ×1, plus the 2 errors (`pipeline/test_completions_data`, `workflow/test_gate_drafts`) | 13 | One root cause, in `importlib_metadata`, not in this tree: <br>`cache_format.py:319 get_functualize_version → importlib.metadata.version("functualize") → PathDistribution.version → md_none(self.metadata)['Version']` → `TypeError: 'NoneType' object is not subscriptable`, i.e. the shared venv was **mid-reinstall** — every `uv run` in this worktree re-syncs it ("Uninstalled 2 packages… Installed 2 packages"). Same text surfaced inside `test_self_manage`'s child process (`stderr="TypeError: 'NoneType' object is not subscriptable"`) | all passed |
| `cli/test_stdin_integration_unit.py` ×4 | 4 | `Failed: DID NOT RAISE SystemExit` — the module under test is `_engine/stdin_reader.py`, which another agent edited at **10:00:01** today (the failing run's window ended 10:29:07 after 26:55) | `4 passed` |
| `e2e/test_interactive.py::TestPtyBasics::test_help_in_pty` | 1 | `pexpect.exceptions.TIMEOUT` (10 s) — the child had rendered only part of `--help` (`buffer: …FUNCTUALIZE_CLI_OUTPUT=json…`) when the timeout fired, i.e. a slow machine under `-n auto`, not a hang | `3 passed, 1 skipped` |
| `pipeline/test_exit_codes.py::…test_a_closed_pipe_exits_zero_and_quietly` | 1 | Asserts `result.stderr.strip() == ""`; `uv run`'s re-sync banner (`Building functualize … Uninstalled 2 packages … Installed 2 packages`) leaked into the child's stderr while a concurrent edit forced a rebuild | passed alone |

**None of the 23 is on a path this work touches**: no traceback names
`app/utils.py`, `_app/boot.py` or `_discovery/cached_provider.py`, and the one symptom that could
have been mine (a cache test) fails in `importlib_metadata`, above the cache reader.

Practical note for the checkpoint wave: with several agents running `uv run` in one worktree, each
invocation reinstalls the shared venv, and any test that resolves the distribution's version dies
in that window. `T15` should run when the tree is quiet; a `-n auto` failure whose test passes
alone is that race, not the code.

## Could not do / questions (not blocking)

1. **T10's caller wiring** — §T10.4. The task's own `**Files:**` line omits all five, so its scope
   does not equal its hit set; AC-2 cannot be satisfied from the listed files.
2. **The `pyproject.toml` comment for AC-3** — §T8.5. Outside the brief.
3. **T9's fatal-vs-reported tension** — §T9.2 (1). Worth one decision from whoever owns the
   executor: fatal at boot (implemented, AC-1) or enforced when a group's flags are resolved
   (ADR-018's shape, needs `_engine/executor.py`).
4. **The duplicate `⚠` line** — §T9.2 (3). One line to change if the orchestrator prefers the
   record alone.
5. **`tasks.md` was not edited** (not in my file list): T8 is complete and would be `[x]`; T9 is
   complete and would be `[x]`; **T10 stays `[ ]`** — reader done, callers not wired.
6. **Not mine, but it reads like a leftover sabotage:** `tests/_cli/test_key_handler_rebind_unit.py:45`
   is `app = MagicMock(spec_set=[] if False else None)` — exactly `spec_set=None`. mtime
   2026-09-08, i.e. before this session; flagged only because a reviewer looking for my
   `if False` would find that one.

## Summary

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T8 · blind-spot document | **done** | file absent; `rg → (no file)` | present; `rg -c '47\|125'` = 4; `exclude_type_checking_imports = true` = 1 (unchanged) |
| T9 · conflict rendered, not raised | **done** | `rg -l 'except GroupOptionsConflictError' src/` = 0 files | 1 file / count 1; tests 20 passed (×3 hash seeds) |
| T10 · group-options fingerprint | **partial — left `[ ]`** | `def … -A3 \| rg -c 'discovery_hash'` = 0 | 1; tests 4 passed — **five in-tree callers still pass nothing** |
