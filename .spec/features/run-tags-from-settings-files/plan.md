# Plan — run tags from every settings file

## Alignment

Shape intent: **Shape Intent — Run Tags From Every Settings File, on Every Surface (project [run] tags join the ordinary ladder)**, [SD/23953415](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/23953415), **version 2**, `Authority: Approved` (read live before authoring). The page's approved C-whole decision and the subsequent OQ-1(a) resolution bind this plan. The page itself stays unchanged.

In scope, in the page's terms: `func <job>`; “TUI and inline TUI”; “HTTP, Lambda”; “MCP run tools”; “app.execute, event submit, workflow control”; and “child runs (`Invoke`, steps, dependencies, parallel)”. `[run] tags` in the global and selected project files joins the ordinary ladder, followed by `FUNCTUALIZE_RUN_TAGS` and `--run-tag`. A malformed or repeated item in a selected project file refuses `func builtin serve http` at boot with exit 2 and a path/item diagnostic.

Out of scope, in the page's terms: “store schema or tag-filter changes”, “job config tags”, “wire tag input”, “per-step tags”, “one-file-per-directory” (OQ-2), and “preview or inspection surface additions” (OQ-3). The page's provisional OQ-1 wording is settled by the issue decision for option (a). Static wiring's first-execute validation is the documented exception to the normal boot timing; its explicit zero-filesystem-I/O boot contract remains intact.

## Workflow state and architecture gate

- Workflow mode: `REPOSITORY_NATIVE`; authority: `AGENTS.md`, `.spec/CONSTITUTION.md`, `.spec/ARCHITECTURE.md`, `.spec/TESTING.md`, `.claude/rules/spec-workflow.md`, and `.claude/agents/spec-driven-developer.md`.
- Phase: Specify and Plan. `spec.md`, `contracts.md`, this plan, and `tasks.md` are branch artifacts. Execution has not begun and no implementation task is checked.
- Retrieval: zvec-grep checked the run-tag ADR, settings ADRs, guides, and pitfalls; Serena inspected symbols and references for `RunRequest`, `resolve_settings`, `parse_config_list`, and boot; graphify inspected the `RunRequest` and app neighborhoods. Codemaps `overview`, `modules`, `dependencies`, `data-flow`, and `entry-points` were checked against source. The repository's `python-design-patterns` skill and the session's `design-patterns-refactoring` skill supplied the catalogue vocabulary.
- Baseline import boundary: `uv run lint-imports` passed all seven contracts, zero broken. The AFTER design adds no contract and no peer-layer cross-import.

### BEFORE

```text
[_config/settings_layers.py: config] --selected raw files--> [_config/settings_resolution.py: config]
    |                                                        |
    | nearest-first SettingsLayer values                     | generic run.tags list value
    v                                                        v
[_cli/main.py::_merge_run_tags: delivery] <--public-- [app/config.py: public]
    | reads global layer only; env + flag parsing in delivery
    v
[_cli/run_tags.py: delivery] --frozen map--> [_types/RunRequest: shared]
                                              |
                                              v
                                [_engine: peer / run record]

[app/core.py::execute: public facade] --request unchanged--> [_engine: peer]
    ^
    | HTTP / Lambda / MCP / TUI / event / workflow control

[_app/boot.py: composition] --lazy app.settings--> [_config/settings_resolution.py]
    | _resolve_plugins_strict catches Exception around app.settings
```

The CLI currently reaches the engine directly after `_merge_run_tags`, so moving
all behavior into `app.execute` alone would leave `func <job>` uncovered.
`_cli/main.py::_merge_run_tags` has **feature envy**: it inspects `SettingsLayer`
fields and chooses the global source, work owned by `_config`. The generic list
resolver's handling of `run.tags` is a **divergent change** point: its list
semantics differ from the tag grammar. These are measured behavior, not a reason
to copy another parser.

### AFTER

```text
[_config/settings_layers.py: config] --raw selected SettingsLayer tuple-->
    [_config/run_tags.py: config] --strict per-source parse / per-key overlay-->
    [immutable effective map]
         ^                          ^
         | env + optional flags     | file layers; no generic-list value
         |                          |
[_app/boot.py: composition] --standard preflight after dotenv, before imports-->
    [app/core.py: public facade] --defaults + RunRequest.run_tags--> [_engine: peer]
         ^                                        |
         | HTTP / Lambda / MCP / TUI / event /    v
         | workflow control                 [run record]
         | static first execute validates and freezes

[_cli/main.py: delivery] --public forwarding seam--> [app/config.py: public]
    --internally--> [_config/run_tags.py: config]
    --merged RunRequest directly--> [_engine: peer]

[_types/RunRequest: shared] --explicit request map--> [app/core.py: public facade]
```

The arrows show call/data direction. `_cli` crosses into the public `app/`
boundary only; public `app/config.py` forwards to `_config`, as it already does
for settings resolution. `_app` is the composition layer that may import both
`_config` and `_engine`. `_config/run_tags.py` uses `_config/settings_layers.py`
and shared vocabulary; it does not import a peer internal layer or delivery
code. `_cli/run_tags.py` is deleted after all imports move. The design adds no
runtime CLI dependency to a kernel layer and no global mutable map.

## Technical approach

1. **One raw-layer parser.** Move `parse_tag`, source parsers, `merge_layers`,
   `RunTagError`, and `MAX_TAGS` into `_config/run_tags.py`. Add a resolver that
   takes the existing nearest-first `SettingsLayer` sequence, uses its global
   layer first and project layers in reverse order, validates every present
   `[run] tags` list with its path/table label, then overlays environment and
   optional flag inputs. The resolver is the sole reader/parser of
   `FUNCTUALIZE_RUN_TAGS` and `--run-tag`; clients pass raw flag items. Keep
   per-source duplicate refusal and final-map limit. Return an immutable map.
   Existing `settings_layers` remains the only file walker, preserving source
   selection and `root = true`.
2. **Close the H4 generic-reader gap.** Exclude `run.tags` from the ordinary
   list candidate/coercion path in `_config/settings_resolution.py`; in
   particular, do not call `_list_values` on its environment value and do not
   publish a misleading `values["run.tags"]` map. Retain the declaration and
   unknown-key census. Mark a selected file with a present tag field as a
   contributor so the config-path status still says `used` for a tag-only
   file. The tag resolver, not the generic snapshot, validates the raw field.
   The observed baseline (`FUNCTUALIZE_RUN_TAGS="x:1,y"` plus file
   `tags=["a:b"]` yields `('x:1', 'y', 'a:b')` with `env` provenance) is the
   failing behavior to reverse.
3. **Public seam and CLI.** Re-export the run-tag resolver and typed error from
   `app/config.py` for `_cli`. Replace `_cli/main.py::_merge_run_tags`'s
   global-only inspection with one call that supplies the selected raw layers
   and flag items. Keep its `Error: ...`/exit-2 projection before discovery.
   Move the builtin run filter's `parse_tag` import through the public seam.
   Delete `_cli/run_tags.py`, move the parser tests' imports, and invert
   `test_the_project_file_is_not_a_layer` as the failing-first gate.
4. **App and boot.** In standard boot, after `load_boot_dotenv(app)` and before
   the imports/discovery/plugin work, explicitly resolve and cache tag
   defaults. This step must not be inside `_resolve_plugins_strict` because
   that helper catches `Exception` from `app.settings`. The CLI serve boundary
   projects `RunTagError` to exit 2. Static boot performs no new file read;
   the first `app.execute` resolves, validates, and caches the same defaults
   before calling the engine. Both paths overlay explicit `RunRequest.run_tags`
   per key at `app.execute` and pass a replaced immutable request into the
   engine. CLI job execution already passes the fully merged map directly to
   the engine. Child requests keep their map without a second read.
5. **Behavioral evidence and durable text.** Verify recorded-run tags through
   the CLI and a direct app request, strict refusal before import on serve,
   and adapters that call `app.execute`. Update ADR-040 and `docs/cli/run.md`
   to replace the three-source/CLI-only record; add an Unreleased changelog
   entry. Do not change storage schema, filters, envelope fields, or hash input.

## Files and blast radius

Source reference search and call-path inspection found these affected groups:

| Boundary | Files |
| --- | --- |
| Grammar, raw layers, generic snapshot | `src/functualize/_config/run_tags.py` (new), `src/functualize/_config/settings_resolution.py`, `src/functualize/_config/settings_layers.py` (read-only unless the existing layer tuple cannot carry the needed context) |
| Public and delivery | `src/functualize/app/config.py`, `src/functualize/_cli/main.py`, `src/functualize/_cli/builtins/_run.py`, `src/functualize/_cli/run_tags.py` (delete) |
| Boot and request | `src/functualize/_app/boot.py`, `src/functualize/app/core.py`, `src/functualize/_types/run_request.py` (read-only: existing field and child-copy contract) |
| Focused tests | `tests/cli/test_run_tags.py`, `tests/cli/test_run_tags_layers.py`, `tests/cli/test_run_tags_pre_boot.py`, `tests/app/test_facade_request.py`, `tests/engine/test_run_record_run_tags.py` |
| Surface regression tests | HTTP/Lambda/MCP adapter tests selected by reference search during execution; event and workflow call paths should be exercised through `app.execute` with representative public-surface tests |
| Durable text | `contributor/adr/040-run-tags-are-an-observation-fixed-when-the-run-opens.md`, `docs/cli/run.md`, `CHANGELOG.md` |

Reference search verified direct old-module imports in `_cli/main.py`,
`_cli/builtins/_run.py`, `tests/cli/test_run_tags.py`, and
`tests/cli/test_run_tags_layers.py`. Separate entrypoint inspection verified
the CLI engine bypass and the `app.execute` users: TUI, inline TUI, HTTP,
Lambda, MCP run tools, event submit, and workflow control. The tests for the
last group should assert observable run records, not only construct requests.

## Risks and controls

- **Late validation:** `_resolve_plugins_strict` swallows a settings exception.
  Make standard-boot tag preflight explicit and test a malformed project item
  against `func builtin serve http` before a job/plugin import marker.
- **Static boot contract:** a settings walk during `boot_static` would violate
  zero filesystem I/O. Test no read at construction and refusal on first
  `execute`.
- **Double parsing or silent malformed env:** generic `run.tags` list parsing
  currently accepts malformed env input. Test that the generic snapshot has no
  authoritative run-tag value and that the strict resolver refuses it.
- **New public export:** the `_cli` dogfood boundary requires a public
  forwarding seam. Document and test the export; run `uv run lint-imports`.
- **Transitional change:** intermediate commits may have tests and source out
  of sync. Tasks below keep gates scoped and leave unchecked work visible;
  the eventual feature gate must cover all surfaces before verification.

## Surviving smells

- **Long method** — `_cli/main.py::_run_cli` already coordinates argument
  dispatch, preboot validation, and execution. This feature changes its tag
  helper without splitting the unrelated dispatch flow. Accepted because
  splitting it would expand the change into command routing; maintainer review
  requested: **no**.
- **Long method** — `_app/boot.py::boot_standard` already owns many ordered
  initialization steps. The new preflight remains one small named step and
  does not add a peer-layer dependency. Accepted because boot order is a
  single orchestration concern; maintainer review requested: **no**.

The AFTER design removes the tag-specific feature envy and avoids a second
parser or repeated adapter changes. No forbidden-pattern smell is accepted.

## Baseline evidence

At branch base `a78a1ed8`, `uv run lint-imports` passed (7 kept, 0 broken),
`uv run ruff check src/ tests/ plugins/ examples/` passed, and
`uv run ruff format --check src/ tests/ plugins/ examples/` passed (1766 files).
The focused baseline
`uv run pytest tests/cli/test_run_tags_layers.py::TestThreeLayersMerge::test_the_project_file_is_not_a_layer tests/spec/test_settings_ratchet.py -q`
passed (11 passed, 1 skipped); inverting the project-file assertion is the
implementation's first red test. No production code changes are included in
this Specify/Plan delivery.
