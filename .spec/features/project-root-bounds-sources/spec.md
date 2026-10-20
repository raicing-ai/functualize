# Project root bounds discovered sources

## Authority and status

- Shape Intent: SD/17104898, version 7, `Authority = Approved`, Model A, read 2026-10-20.
- Multica MCH-188: `Shape state = approved`, read 2026-10-20.
- Specify draft: confirmed by the member on 2026-10-20 (MCH-188, "Confirm spec draft").
- **Revised in Plan, 2026-10-20 — awaiting re-confirmation of the deltas only.** Plan retrieval found two premises the confirmed draft did not have (`research.md` § *Plan retrieval*, P1 and P2). The changes below are marked *Revised in Plan* and carry the drafter's recommended answers to decisions D1 and D2; nothing else in this file changed.

## Problem

A nested project can declare `root = true` while an ancestor's project file still causes jobs from above that root to appear and run. The configuration view stops at the nested file, so the loaded commands and the reported project scope disagree. Declared directory lists can cross the same boundary.

## User stories

- As a developer in a nested project with `root = true`, I see and run only sources within that project boundary, plus sources I explicitly request through the nested project, CLI, environment, or global configuration.
- As a developer relying on inheritance, I continue to receive ancestor sources when I do not declare `root = true`.
- As a developer diagnosing a command, I can rely on `builtin info` and `builtin config path` to describe the scope whose sources were loaded.

## Behavior

1. `root = true` in a project configuration file includes that file and the directories between the current directory and that file in the project scope. Project files and convention directories above it do not contribute jobs, libraries, plugins, or extra directories through upward discovery.
2. The boundary applies to both convention directories and declared directory lists, including `jobs_directories`, `import_libs`, `plugins_directories`, and `extra_directories`. It also applies to inherited file-based discovery settings such as `exclude_patterns`; those settings cannot be read from project files above the root.
3. Without a `root = true` boundary, upward inheritance keeps its current order and sources. A nested project that wants ancestor sources may omit `root = true`.
4. Explicit paths in the nested project's own configuration may refer outside its root. CLI flags and environment overrides retain precedence. The XDG user configuration remains a global source. These are intentional declarations, not upward discovery.
5. `builtin info`, `builtin config path`, command listing, and command execution reflect the same effective project boundary. Existing output shapes stay intact unless Plan demonstrates that a field must change to uphold this behavior.
6. A warm cache must not restore a source excluded by the current root boundary. Cold and warm command inventories agree.
7. *Revised in Plan (D1).* Project settings files above a `root = true` boundary are not settings layers of the nested project: the `func` settings catalog (the source of the TUI settings panel, its write targets, and `cli.*` / `tui.*` resolution) lists and resolves only the bounded project files plus the global file, so it agrees with `builtin config show`.
8. *Revised in Plan (D2).* The project directory used for project mode, runtime state, and convention plugins (the nearest `.functualize/` directory) is unchanged by this feature. A nested `root = true` project that has no `.functualize/` directory of its own keeps today's behaviour there; that layout is recorded as a known residual and left to its own shape.

## Acceptance criteria

- **AC1 — convention jobs:** With an empty ancestor `.functualize.toml`, ancestor `.functualize/jobs/outer_only.py`, nested `.functualize.toml` containing `root = true`, and nested `.functualize/jobs/nested_only.py`, run from nested: `func outer-only` exits 1 with `Unknown command`; `func builtin info jobs --json` contains `nested-only` and excludes `outer-only`.
- **AC2 — declared jobs:** If the ancestor declares `jobs_directories = ["shared"]` and `shared` contains a job, that job is absent from the nested command inventory and cannot run under nested `root = true`.
- **AC3 — other sources:** Ancestor-only library, plugin, and extra directories, whether convention based or declared, are not loaded through upward discovery under nested `root = true`. *Revised in Plan (D2):* for convention plugins this holds when the nested project has its own `.functualize/` directory (the shape's own tree); the layout without one is Behavior 8's residual.
- **AC4 — inheritance control:** Removing `root = true` from the same nested project preserves the existing ancestor inheritance; its job inventory includes both nested and ancestor jobs.
- **AC5 — explicit sharing:** A path explicitly declared in the nested root file can load a source above the root. CLI, environment, and XDG global sources retain their established precedence and behavior.
- **AC6 — scope surfaces:** `builtin info` and `builtin config path` identify the scope represented by the loaded sources; no ancestor file excluded by `root = true` is presented as an applied project layer.
- **AC7 — cache parity:** AC1–AC5 give the same inventory after a prior run has populated the discovery cache.
- **AC9 — settings layers (Revised in Plan, D1):** With ancestor `[cli] show_timing = true` above nested `root = true`, the settings catalog's layer list excludes the ancestor file and `cli.show_timing` resolves to its default, the same answer as `func builtin config show`.
- **AC8 — regression and release note:** A regression test fails against the pre-fix behavior and passes after the change. The hand-written `CHANGELOG.md` entry under `## [Unreleased]` / `### Fixed` explains the root stop and the migration choice: remove `root = true` for inheritance, or explicitly declare a shared path while retaining the stop.

## Boundaries

- No change to non-directory config merge semantics, project mode selection, job-name collision policy, or the order of sources within the active project scope. (*Revised in Plan:* the merge is unchanged; Behavior 7 aligns the settings catalog's layer *list* with the merge that already stops, per D1.)
- No change to projects that do not declare `root = true`.
- No new CLI command, flag, or user-authored configuration key.

## Verification notes

The exact executable gates and file scopes belong to Plan after architecture and blast-radius retrieval. AC1–AC7 require checks through the public CLI and both cold and warm paths; unit-only tests cannot establish them. Release target: merge before the 0.5.0 tag.
