# Status — Active Work and Contribution Guide

Functualize is pre-release (Alpha). Breaking changes are free until v1.0.0.

## Shape Intents (Specified, Not Yet Implemented)

Committed design documents with per-assertion PASS/GAP verification against the current codebase. Fully self-contained — no external files needed to start work.

| Intent | Doc | Assertions | Summary |
|--------|-----|-----------|---------|
| TUI Panel Adjustments for GroupOptions | [shape-intents/tui-group-options-panels.md](shape-intents/tui-group-options-panels.md) | 30 (4 pass, 26 gaps) | Render group-level CLI flags mid-path in 6 TUI panels: SmartBar, Config Table, Diff, Config Files, Pre-flight, and Job Browser. Kernel infrastructure (trie, resolution, execution) is complete — the TUI panels need to produce `deploy --env prod web run --image v1.2` instead of flat `deploy.web.run --env prod --image v1.2`. Changes across ~12 files in `_cli/tui/`. |

## Open Features

Full specifications and atomized task lists for these features exist in the maintainer's working branch. Contact a maintainer to get the detailed breakdowns before starting work.

| Feature | Scope | Description |
|---------|-------|-------------|
| Fix Engine Group Resolution Leak | 3 tasks | `JobExecutionEngine.execute()` currently resolves `job_group` internally via `_resolve_job_group()`. Pass it as a parameter instead — removes a method, fixes the resolution path. Touches: `execution/engine.py`, `context/runcontext.py`, `core/app.py`, `discovery/lazy_wrapper.py`, `discovery/registry.py`, `standalone/cli.py`. |
| Matrix, Watch, and Dry-run | 5 tasks | Three capabilities: (1) expand `@job(matrix=...)` into per-instance descriptors at discovery time (pytest-parametrize style: `deploy[env=prod,region=eu]`); (2) `func watch` using `watchfiles` to trigger jobs on file changes; (3) wire the existing engine dry-run seam end-to-end. New modules in `_discovery/` and `_cli/`. |
| TUI Shell Completion Types | 5 phases | Shell mode in the inline TUI gets four upgrades: (A) type-aware tokenizer distinguishing executables (green), directories (blue), flags (dim), and pipes (boundary); (B) a coloured token highlight bar below the input; (C) a preflight mirror row showing the resolved command with description; (D) background `--help` caching for command descriptions. ~8 new files in `_cli/completions/` and `_cli/tui/`. |
| Interactive Gate Prompt | Draft | Three coordinated CLI flags for workflow gates: `--prompt-gates` (prompt inline on TTY, complete walk in one invocation), `--scope-id` (resume existing blocked scope from the CLI), and `Gate(strategy=...)` (declare preferred resolution strategy per gate, overridable by flags). Touches: `_cli/` dispatch, `_engine/`, `_workflow/`. |

## Potential Follow-ups

Items identified during development that are worth doing but not yet designed:

1. **Autocomplete placeholder crashes instead of degrading** — a missing `textual-autocomplete` optional dep takes out every Pilot test instead of silently skipping. Fix: make the fallback a real Widget or skip it in `compose()`.
2. **Preset awareness in Config Files panel** — the panel assumes a classic config chain with file sources. If the app uses `env_only()` or `twelve_factor()`, the panel shows an empty file list. Fix: read the active preset and hide/adapt the panel.
3. **Settings with no consumers** — `execution_mode`, `history_retention`, `completion_debounce_ms`, `sensitive_keywords`, `signature_enabled`, `show_session_stamp`, `default_override_target` all resolve truthfully in the Settings panel but nothing reads them yet. Wire each to its consumer one at a time.
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
3. **Fix Engine Group Resolution Leak** — 3 tasks, ~6 files, well-scoped parameter passing refactor
4. **TUI Group Options Panels** — 30 assertions across 6 panels, good for a contributor familiar with Textual; the committed shape intent doc is a self-contained starting point

See `CONSTITUTION.md` for quality gates that apply to all changes.
