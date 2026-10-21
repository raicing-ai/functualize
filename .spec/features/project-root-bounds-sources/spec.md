# Project root bounds discovered sources

## Authority and status

- Shape Intent: SD/17104898, version 13, `Authority = Approved`, Model A with the owner's D1(a), D2(b), D3(b) scope decisions, read 2026-10-21. The recommended details within D3(b) and the D2 migration gate await confirmation.
- Multica MCH-188: `Shape state = approved`, read 2026-10-20.
- Specify draft: confirmed by the member on 2026-10-20 (MCH-188, "Confirm spec draft").
- **Revised in Specify, 2026-10-21 — awaiting confirmation.** The owner selected D1(a), D2(b), and D3(b) after the first Plan. That Plan and its task graph assumed D2(a)/D3(a) and have been withdrawn. The behavior below follows the v13 shape's recommended B1 design for D3(b); it is not an implementation authorization.

## Problem

A nested project can declare `root = true` while an ancestor's project file still causes jobs from above that root to appear and run. The configuration view stops at the nested file, so the loaded commands and the reported project scope disagree. Declared directory lists can cross the same boundary.

## User stories

- As a developer in a nested project with `root = true`, I see and run only sources within that project boundary, plus sources I explicitly request through the nested project, CLI, environment, or global configuration.
- As a developer relying on inheritance, I continue to receive ancestor sources when I do not declare `root = true`.
- As a developer diagnosing a command, I can rely on `builtin info` and `builtin config path` to describe the scope whose sources were loaded.

## Behavior

1. `root = true` in a project configuration file includes that file and the directories between the current directory and that file in the project scope. Project files and convention directories above it do not contribute jobs, libraries, plugins, extra directories, or job-config values through implicit upward discovery.
2. The boundary applies to both convention directories and declared directory lists, including `jobs_directories`, `import_libs`, `plugins_directories`, and `extra_directories`. It also applies to inherited file-based discovery settings such as `exclude_patterns`; those settings cannot be read from project files above the root.
3. Without a `root = true` boundary, upward inheritance keeps its current order and sources. A nested project that wants ancestor sources may omit `root = true`.
4. Explicit paths in the nested project's own configuration may refer outside its root. CLI flags and environment overrides retain precedence. The XDG user configuration remains a global source. These are intentional declarations, not upward discovery.
5. `builtin info`, `builtin config path`, command listing, and command execution reflect the same effective project boundary. Existing output shapes stay intact unless Plan demonstrates that a field must change to uphold this behavior.
6. A warm cache must not restore a source excluded by the current root boundary. Cold and warm command inventories agree.
7. *D1(a), selected.* Project settings files above a `root = true` boundary are not settings layers of the nested project: the `func` settings catalog (the source of the TUI settings panel, its write targets, and `cli.*` / `tui.*` resolution) lists and resolves only the bounded project files plus the global file, so it agrees with `builtin config show`.
8. *D2(b), selected.* The search for the nearest `.functualize/` stops at the root marker. An ancestor's convention plugin, runtime state, cache, and vault are not selected for a nested root. If the nested root has no `.functualize/`, its marker directory provides one stable identity across subdirectories with isolated user-data/cache storage. Existing ancestor data stays intact and is not copied automatically. This issue includes a verified, documented migration path for data the user elects to move.
9. *D3(b), B1 recommended.* Implicit job-config discovery and every local file layer stop at the same nearest root marker. A missing key in a nested `config.base.toml` or environment overlay cannot be filled by an ancestor above the root. With no root marker, ordinary job-config inheritance is unchanged. User-global config, explicit config-directory selection, environment and CLI values, and a supplied resolution chain keep their existing precedence. A programmatic app launched inside a root-marked tree follows the same implicit boundary; an app with no root marker is unchanged.

## Acceptance criteria

- **AC1 — convention jobs:** With an empty ancestor `.functualize.toml`, ancestor `.functualize/jobs/outer_only.py`, nested `.functualize.toml` containing `root = true`, and nested `.functualize/jobs/nested_only.py`, run from nested: `func outer-only` exits 1 with `Unknown command`; `func builtin info jobs --json` contains `nested-only` and excludes `outer-only`.
- **AC2 — declared jobs:** If the ancestor declares `jobs_directories = ["shared"]` and `shared` contains a job, that job is absent from the nested command inventory and cannot run under nested `root = true`.
- **AC3 — other sources:** Ancestor-only library, plugin, and extra directories, whether convention based or declared, are not loaded through upward discovery under nested `root = true`, including when the nested root has no `.functualize/` directory of its own.
- **AC4 — inheritance control:** Removing `root = true` from the same nested project preserves the existing ancestor inheritance; its job inventory includes both nested and ancestor jobs.
- **AC5 — explicit sharing:** A path explicitly declared in the nested root file can load a source above the root. CLI, environment, and XDG global sources retain their established precedence and behavior.
- **AC6 — scope surfaces:** `builtin info` and `builtin config path` identify the scope represented by the loaded sources; no ancestor file excluded by `root = true` is presented as an applied project layer.
- **AC7 — cache parity:** AC1–AC5 give the same inventory after a prior run has populated the discovery cache.
- **AC9 — settings layers (D1):** With ancestor `[cli] show_timing = true` above nested `root = true`, the settings catalog's layer list excludes the ancestor file and `cli.show_timing` resolves to its default, the same answer as `func builtin config show`.
- **AC10 — project identity (D2):** With nested `root = true` and no nested `.functualize/`, an ancestor convention plugin does not run. The nested root and its subdirectory resolve the same isolated state/cache/vault identity. The ancestor's existing records and vault remain intact and are not selected. A documented migration procedure is verified before release.
- **AC11 — job config (D3):** An ancestor `config.base.toml` above a nested root contributes no job value, even when a nested base file omits that key. Nested base and active environment overlays retain their precedence; a global value remains available. The same answer holds after refresh and for a programmatic app launched in the marked tree. With no root marker, inheritance is unchanged. An explicitly selected config directory and supplied resolution chain retain their documented behavior.
- **AC8 — regression and release note:** A regression test fails against the pre-fix behavior and passes after the change. The hand-written `CHANGELOG.md` entry under `## [Unreleased]` / `### Fixed` explains the root stop and the migration choice: remove `root = true` for inheritance, or explicitly declare a shared path while retaining the stop.

## Boundaries

- No change to non-directory project-config merge semantics, job-name collision policy, or the order of sources within the active project scope. Behavior 7 aligns the settings catalog with that merge; Behavior 8 changes project mode and storage selection for a nested root without its own `.functualize/`.
- No change to projects that do not declare `root = true`.
- No change to custom job-config filename patterns or registered format providers; they still decide which files match inside the active boundary. Explicit app wiring and the user-global source remain available.
- No new CLI command, flag, or user-authored configuration key.

## Verification notes

The exact executable gates and file scopes require a new architecture and blast-radius pass. AC1–AC11 require public-entry and cold/warm checks; unit-only tests cannot establish them. Plan must verify the D2 migration path and the explicit job-config override behavior before authoring tasks. Release target: merge before the 0.5.0 tag.
