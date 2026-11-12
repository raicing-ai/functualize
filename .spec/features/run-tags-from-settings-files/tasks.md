# Tasks — run tags from settings files

Execution context is the repository-native anchor in
`.claude/agents/spec-driven-developer.md`: `AGENTS.md`, `.spec/CONSTITUTION.md`,
`.spec/ARCHITECTURE.md`, `.spec/TESTING.md`, optional `.spec/STATE.md`, and this
file. This checklist is the executable design record; no implementation task
has begun. Work only in the lowest incomplete wave. Every task must name the
production call path and show a meaningful behavioral gate before it is
checked. Commit a finished implementation before a deliberate sabotage test;
restore safely afterward. A red test intentionally introduced by task 1.1 is
not a completed feature gate.

## Wave 0 — pin the old behavior as a failing-first test

- [x] **1.1 Invert the project-file test.** [F]
  `tests/cli/test_run_tags_layers.py`.
  Replace `test_the_project_file_is_not_a_layer` with an assertion that a
  selected project `[run] tags` item reaches the recorded CLI run. Add file
  path/item refusal assertions in this file, including duplicate keys, a
  malformed item, and the nearest-file override where fixtures permit. The
  old assertion was observed green at the dispatch base:
  `uv run pytest tests/cli/test_run_tags_layers.py::TestThreeLayersMerge::test_the_project_file_is_not_a_layer -q`
  returned `1 passed, 1 skipped`; after inversion, the behavior assertion
  must fail specifically because the CLI ignores project tags. This task's
  acceptance is that clean, expected red, with no production edit. Keep it
  unchecked if it fails for an unrelated setup error.

## Wave 1 — establish the one grammar and layer resolver

- [x] **2.1 Move and extend the run-tag grammar.** [F]
  `src/functualize/_config/run_tags.py` (new),
  `src/functualize/_cli/run_tags.py` (temporary forwarding shim),
  `src/functualize/app/config.py` (temporary public forwarding seam),
  `tests/cli/test_run_tags.py`.
  Move `RunTagError`, `MAX_TAGS`, `parse_tag`, source parsers, and
  `merge_layers` from the old module without creating a second parser. Add a
  resolver over the existing `SettingsLayer` tuple (nearest-first input):
  global, farthest selected project, through nearest, then raw
  `FUNCTUALIZE_RUN_TAGS`, then raw flag items. It must read the env name itself,
  validate each file list with actual path and `[run]` or
  `[tool.functualize.run]` label, reject within-file duplicates, permit
  cross-source overrides, enforce the final 32-key limit, and return a frozen
  map. Migrate the grammar test import and add per-file, env, precedence,
  duplicate, and malformed-item cases. Acceptance: parser tests exercise the
  new module and fail if the file walk is reduced to global only. Production
  path to finish in later waves: selected settings layers → resolver → CLI
  `RunRequest` or app defaults. The delivery module must become a thin
  forwarding shim in this same commit, via `app.config`, so no committed
  revision carries two grammars. Label the shim
  `# TRANSITIONAL(run-tags-from-settings-files/5.2): remove after CLI callers
  move to the public seam.` The CLI's current merge behavior remains
  global-only until task 5.1; do not describe the new resolver as live there.

## Wave 2 — remove the misleading generic value

- [x] **3.1 Reserve `run.tags` for the strict resolver.** [F]
  `src/functualize/_config/settings_resolution.py`,
  `tests/spec/test_settings_ratchet.py`.
  Keep the existing setting declaration and unknown-key census. The generic
  resolver must not coerce/concatenate `run.tags`, including the schema-derived
  `FUNCTUALIZE_RUN_TAGS`. It must not publish its ordinary list as the
  authoritative tag map, but a selected tag-only file still contributes to
  config-path `used` status. Test the observed H4 baseline: env
  `x:1,y` plus project `tags=["a:b"]` currently produces
  `('x:1', 'y', 'a:b')` with `env` provenance; after this task the generic
  snapshot cannot supply that value, and the strict resolver refuses `y`.
  Acceptance: the ratchet keeps `run.tags` declared without adding a legacy
  entry; generic settings no longer accept a malformed env tag as a usable
  list. Production path: `resolve_app_settings` → raw layers → run-tag
  resolver, never `values["run.tags"]`.

## Wave 3 — add a legal public forwarding seam

- [x] **4.1 Expose tag resolution to delivery.** [F]
  `src/functualize/app/config.py`, `tests/app/test_facade_request.py`.
  Complete the public seam started in task 2.1 for the temporary forwarding
  shim: the resolver and typed error (plus `parse_tag` for the existing
  builtin run filter) are available from `app.config`, updating its
  `__all__` as appropriate. Show that the seam returns a frozen map and that
  a direct request can retain an explicit `run_tags` map; leave final app
  overlay for task 6.1. Acceptance: `_cli` can use the public seam without
  importing `_config`; all seven import-linter contracts stay intact.

## Wave 4 — connect the CLI path

- [x] **5.1 Replace global-only CLI merge.** [F]
  `src/functualize/_cli/main.py`, `src/functualize/_config/run_tags.py`
  (remove the fulfilled transitional marker), `tests/cli/test_run_tags_layers.py`,
  `tests/cli/test_run_tags_pre_boot.py`.
  `_merge_run_tags` supplies selected raw layers and raw flag items to the
  public seam. Do not parse env or flags in delivery. Preserve its
  `RunTagError` → `Error: ...` → exit-2 mapping before discovery. Verify the
  task-1.1 red test turns green, nearest-file precedence, actual path/item
  diagnostics, `root = true`, and a malformed env on the preboot CLI path.
  Production path: CLI invocation → `_merge_run_tags` →
  `app.config` → `_config.run_tags` → frozen `RunRequest.run_tags` → engine.
  Acceptance: recorded CLI runs carry project tags and invalid project tags
  stop before job import.

## Wave 5 — remove the old delivery module

- [x] **5.2 Remove remaining delivery imports of the old parser.** [F]
  `src/functualize/_cli/builtins/_run.py`,
  `src/functualize/_cli/run_tags.py` (delete).
  Route the builtin filter's `parse_tag` and `RunTagError` through the public
  seam. Delete the old module only after the old tests and CLI imports have
  moved. Acceptance: the filter still rejects a malformed tag with its
  existing behavior; no production import of `_cli.run_tags` remains. The
  implementation task must inspect the reference hit set before deleting.

## Wave 6 — connect all app-door runs

- [ ] **6.1 Merge defaults at `app.execute`.** [F]
  `src/functualize/app/core.py`, `tests/app/test_facade_request.py`.
  Cache effective defaults per app, overlay explicit
  `RunRequest.run_tags` per key, replace the request with a frozen map, and
  pass it to the engine. Standard boot will populate the cache in task 7.1;
  static boot resolves the selected raw layers on first `execute`, before
  opening that run. Do not add file I/O per invocation or a mutable module
  singleton. Acceptance: a direct app run records file/env defaults and
  request overrides, and a second run uses the frozen defaults. Production
  path: HTTP/Lambda/MCP/TUI/event/workflow callers → `app.execute` → engine.

## Wave 7 — validate during standard boot

- [ ] **7.1 Add explicit standard-boot tag preflight.** [F]
  `src/functualize/_app/boot.py`,
  `tests/cli/test_run_tags_pre_boot.py`.
  Immediately after `load_boot_dotenv`, resolve and cache default run tags
  before job/plugin imports and before `_resolve_plugins_strict` can swallow
  a settings exception. Preserve `boot_static`'s zero-filesystem-I/O path;
  its validation stays at first `execute`. At the `func builtin serve http`
  CLI boundary, project-file `RunTagError` must display `Error: ...` and exit
  2 with selected path and item. Acceptance: import-marker tests observe no
  job/plugin import for a malformed or repeated project item; standard boot
  refuses immediately, while static construction remains I/O-free.

## Wave 8 — prove surface and inheritance behavior

- [ ] **8.1 Add app-door integration evidence.** [F]
  `tests/app/test_facade_request.py`,
  `tests/engine/test_run_record_run_tags.py`.
  Exercise direct app, an explicit request override, and child-run exact-copy
  behavior against recorded tags. Acceptance: direct `app.execute` records
  defaults and explicit overrides, and child runs copy the effective map
  without rereading settings.

- [ ] **8.2 Cover HTTP and Lambda.** [F]
  `plugins/adapters/functualize-http/tests/test_request_envelope.py`,
  `plugins/adapters/functualize-lambda/tests/test_request_envelope.py`.
  Add representative adapter requests with project-file defaults and observe
  the opened run's tags. Assert neither wire gains a tag input. Acceptance:
  both adapters reach `app.execute` with the same default map.

- [ ] **8.3 Cover MCP run tools.** [F]
  `plugins/adapters/functualize-mcp/tests/test_server.py`,
  `tests/plugins/test_mcp_tools.py`.
  Exercise a run-tool request and observe recorded project-file defaults; use
  the existing test harness without adding a wire tag field. Acceptance: a
  real MCP run tool reaches the app-door overlay.

- [ ] **8.4 Cover TUI and inline TUI.** [F]
  `tests/tui/test_tui_app.py`,
  `tests/_cli/test_inline_tui_v2_autocomplete_integration.py`.
  Use a selected project file in each UI test and assert the opened run record
  has its default tags. Acceptance: neither UI path depends on the CLI
  `_merge_run_tags` helper to get its map.

- [ ] **8.5 Cover event submit and workflow control.** [F]
  `tests/app/test_event_submit_scope.py`,
  `tests/workflow/test_workflow_control.py`.
  Exercise each existing call path to `app.execute` with project-file defaults
  and inspect the opened run record. Acceptance: both paths inherit defaults
  without introducing a separate tag parser.

## Wave 9 — update durable behavior records

- [ ] **9.1 Update user and contributor text.** [F]
  `contributor/adr/040-run-tags-are-an-observation-fixed-when-the-run-opens.md`,
  `docs/cli/run.md`, `CHANGELOG.md`.
  Record that project settings files and app-door execution now participate,
  explain the per-key ladder and standard/static validation timing, and keep
  the established observation-at-run-open invariant. No spec artifact is
  treated as a durable master document. Acceptance: text describes the code
  reached through the CLI and app doors, including the static exception.

## Wave 10 — checkpoint

- [ ] **10.1 Verify the complete feature.** [F] This task changes no source
  file unless a failed gate identifies a concrete fix; any fix is scoped to
  its failing task. Run the repository's native Ruff, format, mypy, import
  boundary, and selected feature tests, then the full required test gate.
  Prove reachability by safely sabotaging the committed CLI and app call
  points one at a time and observing a representative behavioral test fail;
  restore each change before finalizing. Confirm the old module is absent,
  the declared setting and unknown-key census remain, no store/wire schema
  changed, and the dead-code delta is reported as advisory. Acceptance: all
  native gates pass and every execution surface has evidence. Only then mark
  the feature ready for Verify phase.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5"] },
    { "id": 9, "tasks": ["9.1"] },
    { "id": 10, "tasks": ["10.1"] }
  ]
}
```
