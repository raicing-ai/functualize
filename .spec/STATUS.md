# Status — Active Work and Contribution Guide

Functualize is pre-release (Alpha). Breaking changes are free until v1.0.0.

## Shape Intents (Specified, Not Yet Implemented)

Committed design documents with per-assertion PASS/GAP verification against the current codebase. Fully self-contained — no external files needed to start work.

_None currently open._

## Open Features

Full specifications and atomized task lists for these features exist in the maintainer's working branch. Contact a maintainer to get the detailed breakdowns before starting work.

| Feature | Scope | Description |
|---------|-------|-------------|
| TUI Shell Completion Types | 5 phases | Shell mode in the inline TUI gets four upgrades: (A) type-aware tokenizer distinguishing executables (green), directories (blue), flags (dim), and pipes (boundary); (B) a coloured token highlight bar below the input; (C) a preflight mirror row showing the resolved command with description; (D) background `--help` caching for command descriptions. ~8 new files in `_cli/completions/` and `_cli/tui/`. |
| Interactive Gate Prompt | Draft | Three coordinated CLI flags for workflow gates: `--prompt-gates` (prompt inline on TTY, complete walk in one invocation), `--scope-id` (resume existing blocked scope from the CLI), and `Gate(strategy=...)` (declare preferred resolution strategy per gate, overridable by flags). Touches: `_cli/` dispatch, `_engine/`, `_workflow/`. |

## Deferred

Specified work that is not being picked up yet, and what it is waiting on.

| Item | Waiting on | Notes |
|------|-----------|-------|
| **`func watch`** | The daemon feature | Deferred by decision. Two things about this are worth knowing before it is picked up again, because both cut against the deferral as written. |

**`func watch` does not, as specified, need a daemon.** Its own proposal lists
"the daemon watcher stays external (polling fallback only)" as an explicit
*non-goal* (`matrix-watch-dryrun/proposal.md:70`), and the spec says the same
(`spec.md:43`): the scoped feature is `watchfiles` plus a debounce setting, in
the invoking process. So deferring it on a daemon either means a **different,
richer watch** than the one specified — one backed by a persistent process — or
the two were conflated. If the former, the existing spec does not describe the
feature that is wanted and needs revisiting rather than resuming.

**The daemon has no spec.** `persistent-process.md` and
`kernel-persistent-process-api.md` no longer exist anywhere in the repo. The
only surviving trace is `scrutiny-reports/standalone-distribution-2026-07-18.md`
(C5), which found `func self daemon *` to be "contingent on an undecided
proposal" and recommended marking those lines contingent — that adjudication
never happened. Until a daemon spec exists, this deferral has no unblocking
event: nothing can be observed to land.


## Dropped

Decisions recorded so they are not re-proposed. Removing an item from the plan is not
the same as removing it from the code — where a declaration surface still exists, that
is called out.

| Item | Why |
|------|-----|
| **Fix Engine Group Resolution Leak** | **The defect no longer exists.** `JobExecutionEngine.execute()` (`_engine/executor.py:140`) has no `job_group` parameter, there is no `_resolve_job_group` method anywhere in `src/`, and `executor.py` never references `job_registry`. `job_group` does not appear in `_engine/` at all — the group-options kernel work replaced it with `group_option_values`. The spec also names `execution/engine.py`, `context/runcontext.py`, `core/app.py` and `standalone/cli.py`, none of which exist; it predates the current layout. |
| **`@job(matrix=...)` expansion** | Dropped by decision, not obsolescence. It expands one job into N descriptors, which forces fan-in semantics onto the dependency graph: the ratified proposal's §D.4 has plain `Deps(deploy)` fanning in over every instance while `Deps("deploy[env=dev]")` selects one. That is a real widening of the DAG's contract for a feature nothing currently needs. |
| **Dry-run end-to-end wiring** | Dropped with the matrix work it was bundled with. The engine seam and `--dry-run`/`--explain` plumbing stay as they are (`_engine/scheduler.py`, `_cli/dispatch.py`); nothing is removed. |

### Live code surface left by the matrix decision

`@job(matrix=...)` is still **accepted and validated** and then does nothing — the worst
of the three states, because a user who writes it gets neither an error nor an
expansion. Deciding what to do about that is its own change, not covered here:

- `job/decorators.py:60` — the `matrix=` parameter on the public decorator.
- `_types/job_declaration.py:460,488-494` — the field plus validation that raises
  `ValueError` on a malformed matrix. Also serialized in `to_dict`/`from_dict`
  (`:510,527`), so removing the field needs a cache-format bump.
- `_types/naming.py:200` — `NodeKind.MATRIX`, consumed only by
  `tests/discovery/test_group_trie.py:98`. Bracket-splitting for `deploy[env=dev]`
  is documented in `contributor/architecture/group-trie.md:71`.
- `README.md:31` advertises "matrix parameterization" as a shipped `@job` capability.
  That line is currently false in effect and should go whichever way the decision lands.


## Completed

### TUI panel support for GroupOptions (2026-08-28, `feat/tui-group-options-panels`)

`shape-intents/tui-group-options-panels.md` is **implemented**. Its stale
tally — "30 (4 pass, 26 gaps)" — was wrong twice over: the real split was
12 PASS / 18 GAP, and the feature was not merely unimplemented. The TUI was
**actively broken** for any project declaring a `GroupOptions` subclass.

**One cause, nine defects.** S6b wired the mid-path resolver into the TUI's
*read* paths and left every *write-back* path parsing the bar's first token as
the job. For the canonical text `deploy --env prod web run v1.2`, that token is
the **group**. Editing a field truncated the command to `deploy`; the
pending-sync emitted a dotted spelling its own resolver refuses; group
overrides vanished; a path segment bound to the job's first positional
(`image = "web"` — silent data corruption); Ctrl+S saved a shortcut naming a
group, which is not invocable; panels were built for the group and so never
appeared; readiness was evaluated against the group node, so the bar read READY
regardless of what the job was missing; missing-args detection returned "not a
command"; and completion's argument slice under-cut by two per mid-path flag,
spilling path segments and a deeper group's flags into the job's own.

Nobody had hit any of it, because **no example project declared a
`GroupOptions` subclass** — the trie was always `None` and every defect dormant.
`examples/standalone/group_options_lab/` is the fixture that arms them, and
`tests/tui_group_options/` holds the regressions.

What shipped:

- **One emitter.** `build_command_line` (`_cli/tui/sync.py`) turns "which job,
  which values" back into a line the user could have typed, placing each group
  flag beside the segment of the group that declared it. Every producer — the
  config-table sync, the pending sync, the pre-flight header, Ctrl+S — routes
  through it, so `emit(resolve(text)) == text` holds by construction rather
  than by four implementations agreeing.
- **Two levels declaring one name.** The values dict is flat by design
  (`_engine/executor.py`), so one value means one place to write it: the
  **outermost** declaring level. `PendingExecution.group_option_paths` records
  the attribution the flat dict cannot carry, and the snapshot and diff both
  read it.
- **Group options render as the path's, not the job's.** A dimmed `[deploy]`
  prefix in the Config Table, the pre-flight and the diff; rows after the job's
  own, outermost group first; filterable by group as well as by field name.
  The Job Browser now shows `deploy web run`, and its filter takes dots,
  spaces or hyphens.
- **A group's credential masks.** `FieldDescriptor.secret` reaches a group
  option through the cache for free, and the panel `FieldDef`s carry it —
  sabotage-checked in both renderers, from the `Secret[str]` declared in the
  example rather than from a stub (`wiring-discipline.md` §8).
- **An unknown job flag stops READY.** Position is what separates a group's
  flag from the job's own, so `deploy web run --env prod` is a job flag named
  `env` and there is none. The bar says so instead of sending the user to a
  click error unannounced.
- **A seventh probe in `tests/group_options/test_surface_parity.py`.** The
  harness previously drove the TUI's *resolver*; a field's kind is decided
  again on the way to the screen, which is how two of the five recorded leaks
  got past it. The render surface now partitions like the rest.

**X.3 held throughout**: an ungrouped job renders byte-identically, verified
live against the example's `status` control at every checkpoint.

**Known gap, left deliberately**: `get_missing_required_args`
(`_cli/tui/missing_args.py`) was fixed and still has **no production call
path**. Kept rather than deleted — see *Potential Follow-ups* item 8 for what
it would take to wire it up.


### Secrets and config unification (2026-08-27, `feat/secrets-and-config`)

ADR-007 and ADR-008 are **accepted and implemented**. A scrutiny pass executed
every claim in both drafts against a running process rather than against the
source, and found that both described a system less wired than they assumed —
17 verified defects, recorded with reproduction commands in
ADR-007 and ADR-008 (see ADR-008's Addendum for what the implementation and
its review amended).

What shipped:

- **One resolver, where one resolver is possible.** Four independent
  implementations of "what value will this field have?" disagreed about values,
  not just formatting. `ResolvedField` / `resolve_job_fields` in
  `_config/resolved_field.py` is the single answer for `info --job` and
  `func builtin env`. The **TUI panels deliberately do not read it**: the seam
  needs a live Pydantic class, so reaching it would import the job module on
  every panel refresh and forfeit true-lazy boot. They share the *detector*
  instead — `secret`/`required`/`default` carried through the discovery cache —
  and read values from the same `ResolutionChain`. See ADR-008 Addendum A1; the
  residual risk is cache drift, guarded by
  `tests/config/test_descriptor_cache_fidelity.py`.
- **One env spelling.** `JOB__FIELD` and a bare, unprefixed `FIELD` are deleted;
  `JOB_FIELD` is the only form. Group options keep `SCOPE__FIELD`, which is a
  different feature with a real disambiguation reason.
- **One secret detector, one mask predicate.** `is_secret_field` decides
  secretness and `display_value` decides rendering, on all five sinks. A
  name-based regex is gone.
- **`Secret[str]` is usable as a config field type** — pydantic core and JSON
  schema, so the declaration marker and the value wrapper are one mechanism.
- **TOML alone by default**, with `func builtin config migrate` and a
  plugin-based escape hatch that is tested end-to-end.

Four pieces of **dead wiring** surfaced, which is the recurring theme:
`preflight_widget.py` had no mount points (deleted), `_collect_job_secrets`
always returned an empty set, `migrate_ini_to_toml` had no callers (the module
is now deleted — see below), and ADR-007's own documented escape hatch did not
work. Guarded now by `tests/config/test_secret_surface_parity.py`, which fails
if any surface drifts from the others.

Not done, and deliberately: `[secrets]` (withdrawn), `--template` (unnecessary —
the default `builtin env` output *is* the skeleton), and `func builtin config
migrate` (built during implementation, then **removed** — a conversion command
exists to carry a user population across a break, and pre-1.0 there is none to
carry, so it was `migrate_ini_to_toml`-with-no-callers one level up. The
warning on an unreadable config file names conversion and the plugin escape
hatch instead, and `tests/config/test_legacy_ini_project.py` proves following
it works).

## Potential Follow-ups

Items identified during development that are worth doing but not yet designed:

1. **Autocomplete placeholder crashes instead of degrading** — a missing `textual-autocomplete` optional dep takes out every Pilot test instead of silently skipping. Fix: make the fallback a real Widget or skip it in `compose()`.
2. **Preset awareness in Config Files panel** — the panel assumes a classic config chain with file sources. If the app uses `env_only()` or `twelve_factor()`, the panel shows an empty file list. Fix: read the active preset and hide/adapt the panel.
3. **Settings with no consumers** — `execution_mode`, `history_retention`, `completion_debounce_ms`, `signature_enabled`, `show_session_stamp`, `default_override_target` all resolve truthfully in the Settings panel but nothing reads them yet. Wire each to its consumer one at a time. (`sensitive_keywords` was on this list and has been **removed** rather than wired — see *Completed* below; masking follows the model, never a name.)
4. **Shell completion model unification** — SmartBar completion and `func builtin shell-init` both consume the same trie and descriptors but compute their partition independently. A shared model (`_cli/completions/shared.py`) would prevent the two from drifting.
5. **`builtin parallel` items missing from history** — parallel batch items run at invoke depth 1 and the history filter only records depth 0. Explicit recording in `parallel` itself would fix this.
6. **`RunContext.log()` bypasses the injected `Log`** — **resolved** (`fix/runcontext-log-di`). `RunContext` now holds the live per-invocation capability map (the `TTY` pattern) and `log()` takes its sink from it, so `rc.log(...)` and a `log: Log` parameter are the same instance. The DI registry is deliberately not consulted — the engine skips it for `Log` too, so reading it would make the two disagree. A job with no `Log` falls back to the `functualize.job.<name>` logger, unchanged. Level validation moved into `log()` (and `CapturingLog`) so an invalid level fails identically on both paths.
7. **~~The slow test tier is red~~ — DONE (2026-08-19, branch `fix/run-slow-tests`).**
   82 failures / 14m36s → green on both Hypothesis profiles (`default` 5m11s, `ci` 9m33s;
   8,407 tests at `-n 10`). All five CI gates verified. The tier found **two real product
   bugs shipped in 0.1.0**, both now fixed:
   - `NamespaceTransform` canonicalized the prefix when *writing* names but matched the raw
     spelling when *reading*, so every namespaced job was unreachable by its only published
     name (`8922756`).
   - Multi-word `JOB_GROUP` failed registration — `qualified_name` validates its group as a
     Python identifier *by design*, so it must see the raw group, but `registry.py` and
     `sync.py` normalized first. `JOB_GROUP = "data_ops"`, this project's own documented
     example, raised `ValueError`. Single-word groups worked, which is why the fixtures
     missed it (`584d04c`).

   Two claims in the original write-up of this item were **wrong** and are corrected here:
   - *"`--run-slow` is not in the release checklist's gates."* It was — gate 6 in
     `.agents/skills/release/SKILL.md` since v0.1.0. The gate existed and still failed,
     for two reasons now fixed: it ran the `default` profile rather than CI's `ci`, and
     with no `-n auto` it could never finish inside the skill's own 300s per-command
     timeout, so it reported BLOCKING on every release and was waived by habit.
   - *"Canonical-identity … may be a product question."* It is not. `normalize_segment`
     strips trailing hyphens deliberately; the tests encoded the pre-normalization world
     and were wrong, the policy was not.

   Lesson worth keeping: **green at `default` is not green at `ci`.** The `ci` profile
   draws 200 examples to `default`'s 100 and found two further failures after the tier had
   already been called green. Verify with `HYPOTHESIS_PROFILE=ci`, never bare `--run-slow`.

   **Carried forward, not done by this work:** the `entry_points()` caching it measured
   (#9), the load-sensitive `test_blocking_worker` assertion it identified (#10), and the
   question of gating `release.yml` on CI (#11). A further ~47 `@given` tests still draw
   only from finite strategies (`sampled_from`/`booleans`/`just`/`none`) and could become
   exhaustive `parametrize` — but that is a search hint, not a work item: the same pass
   established that static counts misclassify property tests in both directions, so never
   bulk-convert on one.

8. **`skip-existing` masks trusted-publisher misconfiguration** — `release.yml` passes
   `skip-existing: true` to `pypa/gh-action-pypi-publish`, which makes twine call
   `Repository.package_is_uploaded()` *before* attempting the upload
   (`twine/commands/upload.py:193`, then `continue`). That check is client-side — it
   reads PyPI's JSON API — so when a version is already on the index **no POST is made
   and no authorization happens**. A green publish job therefore proves only that the
   OIDC mint succeeded, i.e. that *at least one* of the twelve projects trusts
   `(raicing-ai, functualize, release.yml, pypi)`. It proves nothing about the other
   eleven individually.

   This was confirmed empirically during the 0.1.0 release: a `workflow_dispatch` run
   skipped all 24 artifacts, and the log timings show why — the 12 wheels are spaced
   ~40 ms apart (one JSON fetch per project) while all 12 sdists are skipped within
   6 ms of each other, served from twine's `_releases_json_data` cache.

   Consequence: 0.1.0 published its twelve projects by one-time token upload, so its
   own tag run verified nothing. **0.1.1 is the first release that genuinely exercises
   trusted publishing on all twelve**, because it posts files that do not yet exist —
   a project with a missing or wrong publisher will fail there with a 403, not a 400.
   Expect that as a plausible 0.1.1 release failure and check the publishing settings
   first if it happens.

   To verify ahead of a release without spending a version, run twine once per package
   *without* `--skip-existing` and read the status: `400 already exists` means the
   publisher works, `403` means it is missing.

9. **`FunctualizeApp()` calls `entry_points()` seven times** — **RESOLVED**
   (`perf/slow-tier-followups`). Once per entry-point
   group (`plugins`, `domains`, `ai_providers`, `state_providers`, `tasks_providers`,
   `format_providers`, `remote_providers`), and each call rescans every installed
   distribution from disk. Measured over 16 interleaved runs against master on a
   215-distribution environment: median construction **111.9 ms -> 73.3 ms, a 34%
   reduction** (an earlier single instrumented run suggested 60%, but the
   instrumentation inflated the per-call timings; the paired figure is the real
   one). The call sites are
   `_config/registry.py:169,193`, `_plugins/loader.py:326`,
   `_plugins/domain_registry.py:155,245`, `_discovery/providers.py:775`, and
   `_cli/tui/display_provider_discovery.py:79`; none is cached. One scan feeding all
   seven group lookups is the obvious fix. Left alone so far because this is the boot
   hot path and every surface pays it, so it needed its own verification pass rather
   than a drive-by patch. That pass is done: the seven now share one snapshot taken on
   first use, in `_primitives/entry_points.py`.

   The verification that mattered was ordering, since the snapshot is a real behaviour
   change — the stdlib does see a distribution added to `sys.path` mid-process, so a
   later lookup used to pick one up and now would not. Nothing mutates `sys.path`
   inside the 68 ms window the seven lookups span; `--import-lib` paths are applied at
   `_cli/main.py:268`, explicitly *before* app construction; the `_discovery`
   insertions add job-module directories, which do not carry `.dist-info`; and the one
   plugin hit for `sys.path` is inside a `-c` string for a child process. The TUI
   display-provider lookup keeps the stdlib call (it is off the boot path, and `_cli`
   may not import `_primitives`), so it always reads fresh.

10. **`test_blocking_worker` asserts an absolute tick count against wall clock** —
    **RESOLVED** (`perf/slow-tier-followups`).
    `tests/tui_audit/test_blocking_worker.py::test_thread_worker_keeps_event_loop_responsive`
    required `ticks_during_work >= 3` with `BLOCK_SECONDS = 0.4` and
    `TICK_INTERVAL = 0.05`, so the ceiling is ~8 ticks and the margin is thin. It is the
    same class as Hypothesis's `deadline` and the stale `test_config_resolution_budget`
    threshold: **the assertion times the machine, not the code**, and CI runs ~2.5x slower
    than a workstation. Lowering the threshold trades one arbitrary number for another —
    the fix is a *relative* assertion (thread worker vs. the async-blocking control in the
    same file), which is what the test actually means to prove. Untouched since v0.1.0.

    Turned out to be wider than written here: `RESPONSIVE_THRESHOLD = 3` was in **three**
    modules across five assertion sites, not the one test named. `tests/_responsiveness.py`
    now measures the same loop idle, immediately before the real measurement, and requires
    a third of that ceiling. Checked that it still discriminates rather than merely passing:
    the pre-fix pattern scores 0 ticks against an idle ceiling of 8 and a floor of 2. Only
    the `>=` assertions changed — an upper bound is already safe under load, because load
    pushes the count further into passing.

11. **`release.yml` does not require CI green on the tagged commit** —
    **RESOLVED** (`perf/slow-tier-followups`). The job graph was
    `build -> publish -> github-release` with no `workflow_run` or check-suite dependency,
    so a tag pushed at a red commit published to PyPI regardless. Deferred once
    deliberately; revisited because the `v0.1.0` tag turned out to sit at
    `cb94db5`, two commits *after* the source that was actually published on 2026-08-06
    (both CI-only, so nothing shipped wrong — but the tag does not mark the release, and
    it is immutable under the `release tags` ruleset). Two separable changes: gate the
    publish on CI, and tag before publishing rather than after. See also #8, which covers
    the `skip-existing` half of this workflow's problems — still open.

    A `verify-ci` job now finds the run the tagged commit got when it landed on master
    (`ci.yml` never runs on tags) and refuses to publish unless it concluded successfully.
    No run at all fails immediately, an all-completed-without-success set fails immediately
    rather than waiting out the timeout, and an in-flight run is waited on for up to 45
    minutes. CONTRIBUTING carries the two consequences a releaser needs before tagging.

12. **A job module with a `SyntaxError` vanishes silently.** No warning, no
    diagnostic, exit 0 — the job simply is not listed. Cost ~20 minutes on a
    test fixture during the secrets work, and would cost a user far more, since
    they have no reason to suspect the file was even considered. Discovery
    should report a module it failed to parse.

13. **A second, unreachable "what's missing?" implementation** —
    `get_missing_required_args` (`_cli/tui/missing_args.py`) answers "which required
    arguments has the user not supplied yet?" and **nothing calls it**. Its only
    references in `src/` are the import and `__all__` entry in `_cli/tui/__init__.py`;
    its only callers are two test modules. The live answer comes from
    `SmartBar.evaluate` (`_cli/tui/bar.py`), a separate implementation that walks the
    tokens itself.

    Kept rather than deleted (maintainer decision, 2026-08-28), because it returns
    strictly more than `evaluate` does: field **descriptors**, not just names. That is
    enough to render "Missing: `image` (str) — Image tag to deploy" where the bar today
    can only say "Missing: image". Wiring it up is that feature, not a cleanup.

    Both were repaired during the GroupOptions panel work (2026-08-28) — each matched
    the bar's first token against the job list, which under a group is the *group*, so
    `missing_args` returned "not a command" for every grouped job. The two agree today;
    the standing cost is that a reader must work out which one runs.

    To wire it: give `evaluate` the result instead of recomputing it, and delete the
    duplicated token walk — they must not both survive, or they will drift. Note it is
    `async` and `evaluate` is not, so the call has to move to where the app already
    awaits (`on_input_changed`), with the result passed in.

## Recently Completed (2026-07)

| Feature | Description |
|---------|-------------|
| Shell and task runner | Stdout capability, builtin parallel/history/env/shell-init, group options kernel + TUI navigation, PEP 723 scripts, interactive prompting |
| CLI/Shell convergence | CLI namespace consolidation, shell mode, dynamic input bar |
| TUI source-chain detail | Config Files detail view, Settings panel, TOML edit/save |
| TUI app decomposition | Extracted 2393-line `app.py` business logic into focused modules |
| CLI config discovery consolidation | Unified config discovery, fixed XDG resolution bug |
| Release hardening | Mode D arg fix, dead code removal, interactivity plugin protocol |

## Contribution Entry Points

Good first issues for new contributors (ordered by complexity):

1. **Follow-up #2 (Preset awareness)** — small, self-contained TUI change in one panel (`panels/config_files.py`)
2. **Follow-up #3 (Settings consumers)** — wire resolved settings to their actual behavior, one setting per PR
3. **Follow-up #12 (SyntaxError vanishes silently)** — one diagnostic in discovery; the failure mode is easy to reproduce and the fix is contained

See `CONSTITUTION.md` for quality gates that apply to all changes.
