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
6. **`RunContext.log()` bypasses the injected `Log`** — it writes straight to its stdlib logger and never consults the DI registry, so `TestRunContext.captured_logs()` cannot observe it and returns an empty list. Shipped as a documented known limitation in 0.1.0. Fix: resolve `Log` from the registry in `RunContext.log()` — it is on the engine hot path, so it needs its own verification pass.
7. **The slow test tier is red — ~90 failures across ~29 modules** — none of it ships (tests are in no wheel), and the fast tier is fully green, which is exactly why it went unnoticed: every covering test is marked `slow` and `--run-slow` is not in the release checklist's gates. Four distinct causes, all test-side:
   - *Stale engine internal* — `tests/test_resolution_plan_properties.py` (8 failures) calls `engine._build_per_invocation_capabilities(...)` at lines 597/637/676/706. No such method exists in `src/`, and there is no renamed replacement, so that engine behavior is now **untested**, not merely red. Highest priority of the four.
   - *Invalid DI registrations* — several modules do `reg.provide(t, object())` against a synthesized type, which cannot satisfy the `isinstance` contract `DIRegistry.provide` documents. The tests predate that type check.
   - *Canonical-identity drift* — assertions like `assert 'a' == 'a_'` and a `ValueError: Cannot register dynamic job 'a': a job with this name already exists` predate name normalization. Worth confirming whether normalizing `a_` to `a` is intended, since it collapses two distinct Python function names into one canonical name — that one may be a product question rather than a stale test.
   - *Misc stale expectations* — e.g. `assert '' == '<static>'`.

   Add `--run-slow` to the release verification gates once the tier is green, so this cannot recur.

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
