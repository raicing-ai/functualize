# config-unknown-keys — Tasks (Revision 6)

> **Revision 6 (2026-10-26), an execution amendment to rev5.** Rows 3.2 and
> 4.1 are complete at `6430a88e` (base `origin/master` `11ed0e82`);
> 4.4 has code moved but remains unchecked.
> Row 4.4's repo-wide literal gate was unreachable (19 hits, six executable
> hits outside its [F] scope); its gate now checks only its surface sites and
> names the other owners. Row 4.2 retains `read_global_config`,
> `SettingsFileInfo`, and `resolve_cli_config_layers` while 4.3 and 7.1 still
> call them. Their deletion moves to 8.1, after those callers are rewritten;
> no wave is restarted. Row 7.1 owns the last `read_global_config` caller.

> **Revision 5 (2026-10-23), an amendment, not a rewrite.** Rows 0.1–3.1 are
> unchanged and keep their delivered state. Row 3.2 had no satisfiable route
> at branch head `40c2a503` (`GATE_UNREACHABLE`, MCH-190 `01a1658b`). Its
> "no `_cli` import" clause covered 15 public→`_cli` imports, which fall into
> three different concerns, and its "generated flags" clause needs the
> schema-backed catalog that rows 4.1–5.1 create. Rev5 gives every import an
> owning row, re-sequences the flag clause to 5.1, adds row 4.4 (surface
> vocabulary, F16), and puts the one remaining question to the maintainer as
> decision **M8** (`plan.md` §6). Base for this amendment: branch head
> `40c2a5035b61`, `origin/master` `b3e624bd`.

Base `bb3aac77` (rebased 2026-10-21; `git merge-base --is-ancestor origin/master HEAD` → 0;
since rebased by Execute onto `b3e624bd`), branch `sdd/config-unknown-keys`. Spec
AC1–AC31, contracts C1–C6, plan rev5. M1–M7 are closed (`01a15669`, `01a15ee0`);
the rev4 task list was confirmed (`01a1632b`); execution has reached wave 4.
Revision 6 corrects two unreachable task gates. M8 does
not gate PR 1, because PR 1 leaves those 9 sites unchanged and pins them in 8.1.
Everything here is PR 1; PR 2 (M7) gets its own plan after PR 1 merges.

Authoring-time measurements (2026-10-21, `bb3aac77`): 13 vocabulary
collection literals in 6 files; 91 read-position key literals in 9 files;
`rg -n 'functualize_settings|settings_layers|settings_resolution|config_vocabulary' src`
→ 0 hits; `uv run lint-imports` → 7 kept / 0 broken. F1, F3a and F3b
reproduced (`spec.md` §1.2). If `master` has moved again when wave 0 starts,
rebase first and re-run these.

Every task's gate also includes: `uv run lint-imports` green; the pin
(`tests/config/test_settings_pin.py`) green, or changed only in a row that
`spec.md` §3.8 names; reachability by sabotage for every new production path
(commit, break, watch the named test fail, restore).

## Wave 0 — pin and declare

- [x] **0.1 Pin** (AC14) — **[F]** `tests/config/test_settings_pin.py` (new)
  - Literal expectations at `bb3aac77`: `SETTINGS_ORDER`, defaults, choices,
    bounds, descriptions, `cli_flag`, `phase`, env names, `_RECOGNIZED_*`,
    `LIST_KEYS`, `PROJECT_CONFIG_CANDIDATES` names, fingerprint fields, the
    16 flags of `_cli/main.py:140-223`. Resolved values for a matrix of single
    dir, nested ± `root`, global-only, env, and flags. A second class pins the
    §3.8 rows as today's behaviour, each marked to be flipped by the task that
    changes it: `F3a`, `F3b`, the `shell.*`/`plugins.strict` env names,
    `FUNCTUALIZE_EXTRA_DIRECTORIES` (M6, flipped in 1.2) and the PEP 723 `skill`
    key (M5, flipped in 6.4).
- [x] **0.2 Declaration** (C4) — **[F]** `src/functualize/_types/settings.py` (existing, additive),
  `src/functualize/_types/functualize_settings.py` (new),
  `tests/config/test_functualize_settings.py` (new)
  - Every name of the pin, declared once, with constants. `extend()` raises
    on a name clash. `SCRIPT_METADATA` = `job` only (M5). `EXTRA_DIRECTORIES` and
    `EXCLUDE_PATTERNS` are canonical in `[discovery]`, with `places=("", "discovery")` (M6).
  - Gate: the declaration's names = the union pinned in 0.1; `_types`
    imports nothing internal.

## Wave 1 — resolver, layers, mechanical split

- [x] **1.1 Layers** (C5, §3.2) — **[F]** `src/functualize/_config/settings_layers.py` (new),
  `tests/config/test_settings_layers.py` (new)
  - Gate: AC24's fixture gives exactly the root-stopped layers; global last.
- [x] **1.2 Resolver** (C5, §3.3) — **[F]** `src/functualize/_config/settings_resolution.py` (new),
  `src/functualize/_config/sources.py`, `tests/config/test_settings_resolution.py` (new)
  - `EnvSource(prefix=)`, `LayerSource`, list merge = `_merge_lists_dedup` (`_cli/config.py:287`).
  - Gate: the 0.1 matrix resolves to the pinned values; F3a → `rich`; AC28: only
    `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES` is read for `extra_directories`.
- [x] **1.3 Builtins split** (F10, AC25) — **[F]** `src/functualize/_cli/builtins.py` →
  `src/functualize/_cli/builtins/` (`__init__.py`, `_cache.py`, `_data.py`,
  `_workflow.py`, `_run.py`, `_builtin.py`, `_config.py`, `_domains.py`,
  `_skills.py`, `_info.py`, `_helpers.py`)
  - Move only, no behaviour change. Gate: `func builtin --help` and every
    subgroup's `--help` byte-identical; `uv run pytest tests/cli tests/_cli -q`
    green; `register_builtin_commands` (today `_cli/builtins.py:728-3053`, 2326 lines) ≤ 60 lines.

## Wave 2 — public seam and kernel consumers

- [x] **2.1 Public seam** (C4/C5) — **[F]** `src/functualize/app/config.py`,
  `src/functualize/app/core.py`, `src/functualize/plugin/__init__.py`, `tests/app/test_app_settings.py` (new)
  - Re-exports; `ConfigSources(settings=, resolved=)`; `FunctualizeApp.settings`.
- [x] **2.2 `_config` readers** — **[F]** `src/functualize/_config/project_dirs.py`,
  `src/functualize/_config/merge.py`, `src/functualize/_config/vault_declarations.py`
  - Gate: `uv run pytest tests/config -q`; the AC13 walk over these files → 0.
- [x] **2.3 Fingerprint** — **[F]** `src/functualize/_discovery/filter_factory.py`,
  `tests/discovery/test_discovery_hash.py`
  - Gate: an unset config's digest equals the pinned digest.

## Wave 3 — boot, engine, adapters (F3b, F7, STATUS #22)

- [x] **3.1 Boot and engine** (AC17) — **[F]** `src/functualize/_app/boot.py`,
  `src/functualize/_engine/executor.py`, `tests/engine/test_shell_settings_source.py` (new)
  - Before moving, pin today's vault path for `sudo_password` (risk 1).
    `plugins.strict` and `shell.*` are then read from `app.settings`. Boot
    re-resolves `secret` settings with the vault source.
  - *Gate:* `tests/engine/test_shell_settings_source.py` 4 passed (vault pin,
    shell program, plugin strict and lazy vault); settings pin 11 passed;
    `uv run lint-imports` 7 kept / 0 broken. The broader engine suite has two
    pre-existing read-only `app.settings` monkeypatch failures in
    `tests/engine/test_ambient_constructs.py:180,193`.
- [x] **3.2 Public adapters read settings from `app.settings`** (AC19; rev5 narrowed) —
  **[F]** `src/functualize/app/adapters/surface_gate.py`, `src/functualize/app/adapters/cli.py`,
  `tests/adapters/test_surface_gate.py`, `tests/cli/test_bare_invocation_launch.py`
  - The surface gate's `tui.default_surface` read (`surface_gate.py:74`,
    `FuncSettingsStore.discover()` at `:81`) becomes
    `app.settings.value(DEFAULT_SURFACE)`. `app` is already in scope at the
    caller, `wants_stdout_surface(app, …)` (`surface_gate.py:44`).
  - `_inline_tui_enabled()` (`cli.py:1205`, store read at `:1212-1215`) takes
    `app` from `_handle_bare_invocation(ctx, app)` (`:1229`) and reads
    `app.settings.value(INLINE_TUI)`. The hand-rolled `"false"/"0"/"no"/"off"`
    parse goes, because the resolver types the value.
  - *Gate:* AC19. STATUS #22's test passes on its own, and `tests/adapters/`
    is green when run alone. `rg -n '_cli\.data\.func_settings' src/functualize/app/adapters/surface_gate.py`
    → 0. In `cli.py` exactly 2 remain, `:1274` and `:1303`, both owned by 5.1.
    Observed: STATUS test 1 passed alone; adapters 135 passed, 6 skipped;
    targeted adapter/bare tests 33 passed; settings pin 11 passed;
    `lint-imports` 7 kept, 0 broken. The surface gate has zero store imports;
    `cli.py` retains the two 5.1 imports.
  - *Not this row (rev5):*
    - "Generated flags come from the schema" moves to **5.1**, where the
      schema-backed catalog exists.
    - `surface_gate.py:75` (`_cli.orchestrator`) moves to **4.4**.
    - The delivery imports (`cli.py:838`, `:953`, `:1255`, `:1360`, `:1621`;
      `tui.py:54`; `commands.py:356`; `click_params.py:92`, `:722`) are
      decision **M8**.
    - `commands.py:340` (`resolve_cli_config`) moves to **4.2**.

## Wave 4 — CLI (M2 b, M3, M4)

- [x] **4.1 Pre-boot scan and flag parsing** — **[F]** `src/functualize/_cli/dispatch.py`,
  `src/functualize/_types/flag_grammar.py`, `tests/_cli/test_dispatch_flags.py` (new)
  - Flags are read from the schema and parsed into `Mapping[Setting, value]`.
    `_extract_global_options` is decomposed. `OPTIONAL_VALUE_VALID_SET` is
    renamed `GLOBAL_OPTION_ACCEPTED_VALUES` (F13).
  - *Gate:* declared flag parsing and early phase scan: 139 focused CLI tests
    passed; `mypy src/` found no issues in 413 source files; `lint-imports`
    7 kept / 0 broken. The old accepted-values spelling remains an alias
    while public callers migrate.
- [x] **4.2 `_cli/config.py`** (F9; rev6 staged removal) — **[F]** `src/functualize/_cli/config.py`,
  `tests/cli/test_cli_config.py`, `tests/cli/test_cli_config_vault.py`, `tests/cli/test_resolve_cli_config.py`
  - `CliConfig` becomes a projection of `ResolvedSettings`. Delete
    `_RECOGNIZED_*`, `resolve_env_overrides`, and `resolve_cli_config`'s own
    resolution. Keep `read_global_config`, `resolve_cli_config_layers`, and
    `SettingsFileInfo` temporarily, marked `TRANSITIONAL(config-unknown-keys/8.1)`
    at their definitions: 4.3 still calls the layer symbols and 7.1 still
    calls `read_global_config` from `config show`. Row 8.1 deletes all three
    after those callers have moved. The warning tests (`test_cli_config.py:108,125,190`,
    `test_cli_config_vault.py:85`) become `config path` assertions.
  - *Rev5 addition:* **[F]** += `src/functualize/app/commands.py`. The settings
    read at `:340-342` (`from functualize._cli.config import resolve_cli_config`;
    `obj["cli_config"] = resolve_cli_config()`) takes the `CliConfig` projection
    of `app.settings` instead. Gate: `rg -n '_cli\.config' src/functualize/app` → 0.
  - *Result:* `CliConfig` and its projection live in `src/functualize/app/config.py`
    (`CliConfig.from_settings(ResolvedSettings)`); `_cli/config.py` re-exports the
    type and keeps `resolve_cli_config(*, cli_flags=None, cwd=None)` with its
    exact signature, its body now one `resolve_app_settings(...)` call into the
    projection. The type had to move: the app layer may not name
    `functualize._cli.config` (literal gate), and `_cli` may not import
    `_config` (`_cli uses public API only`), so the app layer — which may import
    `_config` — is the only home both sides can reach. `builtin_context_obj`
    now reads `app.settings` and degrades to a warning as before, leaving
    `cli_config` unset when there is no app.
  - *Retained, marked `TRANSITIONAL(config-unknown-keys/8.1)`:*
    `read_global_config`, `resolve_cli_config_layers`, `SettingsFileInfo`, and
    `_RECOGNIZED_SECTIONS`/`_RECOGNIZED_TOP_LEVEL_KEYS`/`_RECOGNIZED_KEYS`.
    The tables could not be deleted with `read_global_config` still in place —
    it is their only consumer and its warning behaviour is unchanged — so they
    go with it in 8.1.
  - *Deleted:* `resolve_env_overrides`, `_get_value`, `_merge_lists_dedup`,
    `_parse_bool_env`, `_resolve_import_libs` (its absolutise-and-dedup
    behaviour survives as `_absolute_import_libs` inside the projection).
    `rg -n 'resolve_env_overrides|_merge_lists_dedup|_parse_bool_env|_get_value|_resolve_import_libs' src tests docs` → 0.
  - *Observed:* the row's three warning tests (`test_cli_config.py:108,125,190`)
    and `test_cli_config_vault.py:85` are now `builtin config path` assertions
    (`TestConfigPathAfterUnknownKeys`, `test_an_unknown_vault_key_still_reports_the_file`):
    an unknown key changes neither the reported file nor the exit code, and
    resolve time stays silent. Feature property tests of the deleted helpers
    went with them; environment-name and precedence coverage stays with the
    shared resolver's own suites (`tests/config/test_env_name_rule_parity.py`,
    `tests/config/test_env_overlay_properties.py`).
    `rg -n '_cli\.config' src/functualize/app` → 0 (exit 1).
    `pytest tests/cli/test_cli_config.py tests/cli/test_cli_config_vault.py tests/cli/test_resolve_cli_config.py tests/cli/test_config_properties.py tests/cli/test_handlers.py tests/standalone/test_cli.py tests/config/test_settings_pin.py`
    → 77 passed, 12 skipped. `pytest tests/cli tests/config tests/standalone tests/_cli`
    → 4100 passed, 685 skipped, 1 failed
    (`test_workflow_answer_relational.py::TestCliAnswerAndResume::test_resume_with_fused_input_answers_and_advances`),
    which reproduces on a pristine `3fa45fd8` extraction (`workflow_not_found`,
    `No workflow scope 'rel-1'`) and is untouched by this row. `mypy` clean on
    the three modules; `lint-imports` 7 kept / 0 broken; `ruff check` and
    `ruff format --check` clean. A live probe of the projection resolves
    `output`/`show_timing`/`scan_depth`/`aliases`/`anchor`/`vault.keyring_timeout`/
    `discovery.extra_directories` from a project file and absolutises
    `import_libs` against the anchor.
  - *Residual:* `read_global_config`'s unknown-key warning path is no longer
    pinned by a test — this row moved those assertions to `config path` — and
    the function is removed in 8.1.
- [x] **4.3 Settings store and TUI** (M4; amended at `1ffd5f00`) — **[F]**
  `src/functualize/_config/settings_layers.py`, `src/functualize/plugin/__init__.py`,
  `src/functualize/_cli/data/func_settings.py`, `src/functualize/_cli/data/settings_schema.py`,
  `src/functualize/_cli/data/toml_writer.py`, `src/functualize/_cli/tui/__init__.py`,
  `src/functualize/_cli/tui/settings_panel.py`, `src/functualize/_cli/tui/settings_validator.py`,
  `src/functualize/_cli/tui/shell_mode.py`, `src/functualize/_cli/tui/app.py`,
  `src/functualize/_cli/tui/source_chain_providers.py`,
  `src/functualize/_cli/tui/panels/settings_files.py`, `src/functualize/_cli/tui/job_listing.py`,
  `tests/config/test_settings_layers.py`, `tests/cli/test_func_settings_store.py`,
  `tests/cli/test_apply_settings.py`,
  `tests/cli/test_settings_registration.py`, `tests/cli/test_settings_store_second_app.py`,
  `tests/_cli/test_settings_panel_catalog.py`, `tests/_cli/test_settings_files_pilot.py`,
  `tests/_cli/test_source_chain_detail_pilot.py`,
  `examples/standalone/deploy_tool/deploy_tool/main.py` (public-type example only),
  `examples/standalone/deploy_tool/tests/test_deploy_tool.py`
  - **Do — layers and reachability:** export the existing `SettingsLayer` from
    `functualize.plugin` (`plugin/__init__.py`), beside `ResolvedSettings` and
    `resolve_settings`. `FuncSettingsStore` takes the app's schema and frozen
    `app.settings` snapshot when an app exists; standalone `discover(cwd, env)`
    uses the same public `resolve_settings(schema, cwd, env=…)` entry point.
    Both obtain `snapshot.layers`, never `_cli.config` or `_config`.
    `layers`, source-chain entries and the Settings Files panel use those
    `SettingsLayer` objects. The chain may list each file/env/flag candidate,
    but its winning value and provenance come from the snapshot; the store
    must not implement a second precedence resolver.
    `ensure_layer()` adds an empty prospective layer without reading a file.
    `refresh()` obtains a replacement snapshot from the already-public
    `resolve_settings(schema, cwd, flags=…, env=…)`, retaining the store's
    explicit flag/environment inputs; it never reparses a TOML file itself.
    Name the exported `SettingsLayer` type in the deploy-tool example's store
    factory so the new public type has an example caller; 6.3 still owns that
    example's full private-import cleanup.
  - **Do — persistence and AC18:** keep `FuncSettingsStore.write()` as the TUI
    edit coordinator and keep `_cli/data/toml_writer.py` as the atomic text
    writer. Extend `SettingsLayer` with the original file text, loaded in
    `_config/settings_layers.py` alongside its parsed values. Before a save,
    refresh the layer snapshot; validate edits against the app schema, map
    dotted setting names to the layer's `section_prefix`, and pass that text
    plus *all* section edits/removals to a read-free writer operation that
    renders and atomically replaces the file once. The writer must not open
    the settings path for reading; its existing job-config
    path may keep its own read. After the save, `refresh()` re-resolves through
    the layer module. Thus even the read needed to preserve unrelated TOML
    occurs only in `_config/settings_layers.py`; no second settings parser or
    public write API is added. Preserve comments, unrelated sections and
    typed values in the round trip. The running app's boot snapshot remains
    frozen; the TUI uses the refreshed store snapshot and its existing live
    apply hook, while other app consumers see the saved file on the next boot.
  - **Do — catalog and consumers:** remove the TUI's dependence on mutable
    registries, `FuncSetting`, `_spec`, `_as_setting` and import-time
    registration. Build SettingsPanel rows/order/defaults and validation from
    the app schema's
    `surface="tui"` settings; values/provenance come from the store snapshot,
    including a prospective file not yet written. The `deploy_tool` example
    still calls `register_settings`, constructs `FuncSetting`, and imports
    `SETTINGS_ORDER`/`FUNC_SCHEMA` (`examples/standalone/deploy_tool/deploy_tool/main.py:42-109`,
    `tests/test_deploy_tool.py:40-77`); retain only that example-facing legacy
    catalog until 6.3 rewrites the example, mark it
    `TRANSITIONAL(config-unknown-keys/6.3)`, and do not let it feed the TUI.
    The adapter's `FUNC_SCHEMA` read is separately transitional to 5.1.
    Row 6.3 removes the example callers and the remaining legacy names. Update
    `job_listing.py:144` and the Settings Files builder to consume the new
    store/layer model. `app/adapters/cli.py:1302,1314` stays owned by 5.1:
    retain the store's per-instance flag override entry point through this
    wave, marked `TRANSITIONAL(config-unknown-keys/5.1)`, then remove that
    public-folder import in 5.1 when flags enter the typed resolver.
  - *Gate:* `rg -n '\b(SettingsFileInfo|resolve_cli_config_layers)\b'
    src/functualize/_cli/data/func_settings.py` → 0 before 8.1 deletes their
    definitions; `rg -n 'tomllib|_functualize_table|read_text\('
    src/functualize/_cli/data/func_settings.py` → 0. A save test must fail if
    the writer reads a settings path, then pass with the read confined to
    `settings_layers.py`; it must cover multiple sections, an unwritten file,
    preserved unrelated TOML, and the refreshed TUI value/source. Pin a
    second app's schema and the `root = true` stop through `discover()`.
    Run the named store/TUI and deploy-tool example tests, then
    `uv run lint-imports` (7 kept/0 broken).
  - *Result:* `SettingsLayer` now carries the file's `text` and a
    `SettingsLayer.read(path, kind, section_prefix)` classmethod
    (`_config/settings_layers.py`), which is the only settings read outside the
    resolver. It is exported from `functualize.plugin` beside
    `ResolvedSettings`/`resolve_settings`, together with `FUNCTUALIZE_SETTINGS`,
    so `_cli` reaches both through the public seam rather than `_config`/`_types`.
    `FunctualizeApp.settings_schema` (new, `app/core.py`) is the declaration the
    app was configured with (`config_sources.settings`, else the built-in) and
    `app.settings` resolves through it; the TUI builds
    `FuncSettingsStore(func_app.settings_schema, snapshot=func_app.settings,
    cwd=Path.cwd())`, so the panel and the boot snapshot cannot disagree, and a
    snapshot passed in is never re-resolved (`TestSnapshotIsTheAnswer` fails if
    it is).
  - `refresh()` is `resolve_settings(schema, cwd, flags=…, env=…)` and nothing
    else; `layers`/`global_path`/`ensure_layer`/`declared_settings(surface=…)`/
    `effective_values`/`source_labels` read that one snapshot. `write()`
    refreshes, validates every edit through `setting_schema(setting)`, groups
    the edits by `schema.section_in_file(setting, path.name)` and makes one
    `write_toml_sections(path, text, sections)` call.
  - `toml_writer` gained `SectionEdits` (edits/removals/type hints) and a
    read-free `write_toml_sections`: one parse of the caller's text per
    section, one tempfile, one `os.replace`. `write_toml_section` keeps its read
    for the job-config path.
  - `SettingsPanel(cwd, id, catalog)` has no module-level `SETTINGS_ORDER` or
    `_DEFAULT_VALUES`; rows, order, type, choices and description come from the
    `Setting`s it is handed. `job_listing.py` passes
    `store.declared_settings(surface="tui")` and loads `effective_values()` /
    `source_labels()`. The Settings Files builder lists `store.layers`, and
    `app.py`'s new-file candidates now come from
    `schema.sources.project_file_names` + `section_prefix_for`, so another
    app's shell offers its own files and its own table.
  - The deploy-tool example is the public-type demonstration:
    `build_app()` passes `ConfigSources(settings=settings_schema())` and
    `settings_store()` is `FuncSettingsStore(settings_schema(),
    app_name=APP_NAME)`; `SettingsLayer` reaches it from `functualize.plugin`.
  - *Gates:* `rg -n 'tomllib|_functualize_table|read_text\(' src/functualize/_cli/data/func_settings.py`
    → 0 (exit 1); `rg -n 'SettingsFileInfo|resolve_cli_config_layers'
    src/functualize/_cli/data/func_settings.py` → 0 (exit 1);
    `uv run lint-imports` → 7 kept, 0 broken; `ruff check` and
    `ruff format --check` clean over the touched tree.
  - *Sabotage, recorded both ways:* making `write_toml_sections` read `path`
    (`text = path.read_text(...)`) fails
    `TestWrite::test_writer_applies_the_text_it_is_given`
    (`assert '[extra]' not in '<the file as it is, not as given>'`); restoring
    gives 66 passed. Making `refresh()` re-parse with
    `tomllib.loads(layer.path.read_text(...))` puts two hits back in the gate at
    `func_settings.py:756,760` and fails
    `TestWrite::test_refreshes_the_snapshot_after_saving`
    (`assert 'transparent' == 'dark'`); restoring returns the gate to 0 and
    the file to 32 passed.
  - *Observed:* `pytest tests/cli tests/config tests/standalone tests/_cli -q
    -p no:randomly` → 4113 passed, 684 skipped, 1 failed — the pre-existing
    `tests/cli/test_workflow_answer_relational.py::TestCliAnswerAndResume::test_resume_with_fused_input_answers_and_advances`
    (`workflow_not_found`, `No workflow scope 'rel-1'`), which also fails at
    `3fa45fd8` and is untouched here. The two slow classes pass with
    `--run-slow`. A live example probe: `build_app()` resolves
    `deploy.environment=dev`, `settings_store().write(global,
    {"deploy.environment": "staging"})` writes `[deploy]\nenvironment =
    "staging"` and the refreshed store reports `staging | global config`, with
    the layer typed by `functualize.plugin.SettingsLayer`. The TUI surface is 7
    rows (`tui.theme`, `tui.display_auto_switch`, `tui.default_surface`,
    `tui.show_session_stamp`, `tui.history_retention`,
    `tui.signature_enabled`, `tui.default_override_target`).
  - *Deliberate behaviour changes:* (a) a hand-edited invalid value is shown
    with its file as source instead of being silently dropped — entering an
    invalid value in the panel is still refused and `write()` raises
    `ValueError`; (b) the Settings table shows the 7 `surface="tui"` rows
    instead of the 29 legacy ones; (c) a `pyproject.toml` without a
    `[tool.functualize]` table is no longer a layer; (d) importing
    `functualize._cli.tui` no longer registers `tui.*` into the legacy catalog,
    so `test_importing_the_tui_package_contributes_tui_settings` became
    `…adds_nothing_to_the_catalog`; (e) the new-file picker's labels follow the
    declaration (`[tool.functualize]` is now read from the schema).
  - *Residual:* the display chain lists every candidate rung but does not
    per-entry validate them — the winning value and provenance still come from
    the snapshot, and validating every rung would need a second resolver.
    `FUNC_SCHEMA`, `set_cli_override`, `SETTINGS_ORDER`/`FUNC_SETTINGS` and the
    example's `register_settings` stay `TRANSITIONAL(config-unknown-keys/5.1)`
    and `…/6.3`. `app/adapters/cli.py` is untouched: its `FUNC_SCHEMA` read is
    5.1's.
  - *Dead-code delta (`eecd0818..b0bd5178`), advisory:* 1 NEW_DEAD, 1
    TESTS_ONLY. `_cli/config.py:252 resolve_cli_config_layers` lost its last
    consumer with this row's store rewrite (no references anywhere, `read_global_config`
    does not call it), so 8.1's deletion gate at
    `rg -n '\b(read_global_config|SettingsFileInfo|resolve_cli_config_layers)\b'`
    can now drop all three in one step. `func_settings.py:178 tui_settings` is
    reached only from `tests/cli/test_settings_registration.py` and
    `tests/config/test_settings_pin.py`; it is legacy-catalog setup, deleted with
    the rest in 6.3/8.1.
- [x] **4.4 Surface vocabulary** (F16; AC30; rev5 new) — **[F]** `src/functualize/_types/enums.py`,
  `src/functualize/types/__init__.py`, `src/functualize/_types/functualize_settings.py`,
  `src/functualize/job/decorators.py`, `src/functualize/app/adapters/surface_gate.py`,
  `src/functualize/_cli/orchestrator.py` (deleted), `src/functualize/_cli/tui/job_execution.py`,
  `tests/cli/test_surface_resolution.py`, `tests/test_public_api_surface.py`
  - `RenderSurface` (`_cli/orchestrator.py:18-30`) moves to `_types/enums.py`
    beside the other enums, re-exported from `functualize.types`.
  - The preference ladder `resolve_surface`/`explicit_surface` (`:33-71`)
    moves to the public `app/adapters/surface_gate.py`, the direct-run gate
    both command paths already share. `_cli/tui/job_execution.py:599` imports
    it from there (`_cli` → public). `_cli/orchestrator.py` is deleted; its
    only consumers are `surface_gate.py:75` and `job_execution.py:599`.
  - One statement of the render-surface pair across this row's four original
    sites: the enum
    (`orchestrator.py:28-29`), `_parse` (`:76-79`), `job/decorators.py:115`
    `_VALID_SURFACE_HINTS`, and `_types/functualize_settings.py:43` choices.
    The setting's choices and the decorator's valid hints derive from
    `RenderSurface`'s non-exclusive members; parsing is enum value lookup.
  - *Gate (rev6 scope):* AC30. Run
    `rg -n '"panel"|"stdout"' src/functualize/_types/enums.py src/functualize/types/__init__.py src/functualize/_types/functualize_settings.py src/functualize/job/decorators.py src/functualize/app/adapters/surface_gate.py src/functualize/_cli/tui/job_execution.py`.
    These are this row's surviving production files; review each hit:
    executable value literals remain only as `PANEL` and `STDOUT` in
    `_types/enums.py`; the other hits are docstrings or comments. At
    `6430a88e` that scoped search returns 7 hits: two enum values and five
    explanatory mentions. The surface-resolution and public-API-surface tests
    are green. `rg -n '_cli\.orchestrator' src` → 0.
    - *Observed at `3fa45fd8`:* the scoped search returns the same 7 hits —
      `PANEL`/`STDOUT` values in `_types/enums.py:20-21` and five
      docstring/comment mentions (`decorators.py:125,130,136`,
      `surface_gate.py:8`, `job_execution.py:594`); `_VALID_SURFACE_HINTS`
      and the setting's choices both derive from `SURFACE_PREFERENCES`.
      `rg -n '_cli\.orchestrator' src` → 0; the module is gone.
      `pytest tests/cli/test_surface_resolution.py tests/test_public_api_surface.py`
      → 57 passed.
  - *Out-of-scope baseline (rev6):* the repo-wide search returns 19 hits.
    Six executable hits cannot be removed by this row: 4.3 owns
    `_cli/data/settings_schema.py:43` and `_cli/data/func_settings.py:169`;
    this feature has no removal row for `_types/outcome.py:52`,
    `_cli/tui/models/focus_state.py:36`, `_cli/tui/focus.py:29`, or
    `ui/stdout_surface.py:91`. Do not use repo-wide zero as this row's gate.

## Wave 5 — main and utils

- [x] **5.1 `_cli/main.py` and generated root flags** — **[F]** `src/functualize/_cli/main.py`,
  `src/functualize/app/adapters/cli.py` (rev5 added)
  - *4.3 handoff:* remove `_seed_settings_store_from_flags`'s
    `FuncSettingsStore` import/construction (`app/adapters/cli.py:1302,1314`)
    and its transitional per-instance override path when generated flags feed
    the typed resolver. Gate: `rg -n '_cli\.data\.func_settings' src/functualize/app`
    → 0; 4.3 does not claim this public-folder cleanup.
  - Generated options replace the 16 decorators at `:140-223` (`@click.pass_context`
    `:228`). The typed flag layer replaces `cli_flags` (`:327-343`, `:2130-2134`).
    `PLUGINS_DISABLED` reads (`:383-385`, `:618-620`, `:1279-1281`, `:1437-1439`),
    `ALIASES` (`:772`, `:778`) and `JOBS_DIRECTORIES` (`:1790`) go through
    `app.settings`/`value_in`.
  - *Moved here from 3.2 (rev5):* "generated flags come from the schema".
    - `_setting_flag_specs` (`cli.py:1263`) reads the app's declaration
      (`app.settings.schema`), not the live legacy catalog `FUNC_SCHEMA`
      (`:1274`).
    - `_apply_setting_overrides` (`:1296`) feeds the typed flag layer of
      `resolve_settings` instead of `FuncSettingsStore` (`:1303`).
    - `func`'s root options and `CliAdapter`'s root options (`:1197`) are the
      same generated list, so the 16 hand-written decorators go in this row.
      Switching the generator in wave 3 would have given project apps the
      11 declared flags (`--discovery-depth` … `--require-job-prefix`)
      before the typed flag layer could honour them.
  - *Gate:* AC22. `_generated_setting_options()` yields the 11 declared flags;
    `func --help` lists each once; `rg -n '_cli\.data\.func_settings' src/functualize/app` → 0.
- [x] **5.2 `app/utils.py`** — **[F]** `src/functualize/app/utils.py`
  - Document reads (`:750-753`, `:972-1032`) and the `overrides`/`effective`
    plumbing (`:843-867`) go through the declaration.
  - Gate (after 5.1 and 5.2): the AC13 walk over `src/` → 0 outside the owner
    and the resolver; plan risk 4's `rg` sweep is clean.

## Wave 6 — the check, surfaces, reserved names, example, PEP 723

- [x] **6.1 Check** (C3; AC4, AC6, AC8, AC9) — **[F]** `src/functualize/_cli/data/config_vocabulary.py` (new),
  `tests/cli/test_config_vocabulary.py` (new)
- [x] **6.2 Reserved names** (F14; AC23, AC27) — **[F]** `src/functualize/_types/discovery_report.py`,
  `src/functualize/_discovery/collisions.py`, `src/functualize/_config/sources.py`,
  `tests/discovery/test_reserved_section_names.py` (new)
  - A new `error_type` on #118's `DiscoveryFailure` (`_types/discovery_report.py:78`),
    built beside `job_name_collision` (`:152`). No second channel.
- [ ] **6.3 Example** (F7; AC21) — **[F]** `examples/standalone/deploy_tool/deploy_tool/main.py`,
  `examples/standalone/deploy_tool/tests/test_deploy_tool.py`,
  `src/functualize/_cli/data/func_settings.py`, `src/functualize/_cli/dispatch.py`,
  `src/functualize/app/adapters/settings_flags.py`, `src/functualize/app/adapters/__init__.py`,
  `tests/cli/test_settings_store_second_app.py`, `tests/_cli/test_dispatch_flags.py`,
  `tests/cli/test_early_setting_flags.py`, `tests/cli/test_settings_registration.py`
  - **Do — declaration:** `functualize.plugin.FUNCTUALIZE_SETTINGS` is the public
    base catalog. Declare the example's two `functualize.plugin.Setting` values
    without module-import side effects. Use `FUNCTUALIZE_SETTINGS.extend(*own)`
    as the sanctioned extension point; pass its **complete** `settings` tuple
    into the app's `AppSettingsSchema` with `DEPLOY_TOOL` env prefix, file names,
    and `tool.deploy-tool` section, through `ConfigSources(settings=...)` at
    construction. `extend` rejects duplicate names; a tuple of only the two
    deploy settings would silently drop built-in keys. Remove the example's
    private `FuncSetting`, `SettingSchema`, `register_settings`, `FUNC_SCHEMA`,
    and `FuncSettingsStore` imports and its registration call; test values via
    the public app snapshot/resolver. No new `plugin/` export is needed.
  - **Do — pre-boot flags:** add and export a schema-parameterized public
    `early_setting_flags(schema, argv)` in `functualize.app.adapters` (implementation
    in `settings_flags.py`, package export in `__init__.py`). It returns passed
    `phase="early"` flags keyed by declared setting name, accepts both `--flag x`
    and `--flag=x`, ignores ordinary flags, and leaves a missing value for Click
    to reject. Before constructing `deploy-tool`, use this result with public
    `resolve_settings(schema, cwd, flags=...)`, then pass the snapshot through
    `ConfigSources(resolved=...)`; its `--config-profile` affects the first app
    snapshot, with no process-wide registration. `_cli/dispatch.py` uses the
    same helper with `FUNCTUALIZE_SETTINGS` for `func`'s pre-boot scan; its
    existing pre-boot override storage remains transitional until AC20/8.1.
    The example calls the new public export, satisfying public-API example
    coverage. Pin both entry paths, including flag precedence and no job import.
  - **Do — retired alias:** `_cli/dispatch.py:275-279` is a production caller
    of `FUNC_SCHEMA`, and the three listed CLI test files also call it; the
    example is not its last caller. Read the base declaration through public
    `FUNCTUALIZE_SETTINGS` in dispatch, replace the tests' live-registry fixtures
    with explicit schemas, and delete `FUNC_SCHEMA` plus its projection-only
    bridge from `func_settings.py`. Retain `FUNC_SETTINGS` only for its other
    legacy callers pending AC20/8.1; do not rebuild an app catalog from it.
  - **Gate:** `rg -n '\bFUNC_SCHEMA\b' src examples tests/_cli/test_dispatch_flags.py tests/cli/test_early_setting_flags.py tests/cli/test_settings_registration.py tests/cli/test_settings_store_second_app.py`
    → 0 after the scoped callers and definition are removed; the current hit
    set is `func_settings.py`, `_cli/dispatch.py`, `deploy_tool/main.py`, and
    the three named CLI test files. `rg -n 'from functualize\._' examples/standalone/deploy_tool/deploy_tool/main.py`
    → 0; the example tests, dispatch/early-flag tests, and second-app pin pass.
    This row leaves 6.1, 6.2, and 6.4 closed and changes no Wave 7 dependency.
- [x] **6.4 PEP 723** (M5 closed: remove; AC29) — **[F]** `src/functualize/_cli/pep723.py`, `tests/cli/test_pep723_skill_key.py`, `tests/standalone/test_pep723.py`
  - `_KNOWN_TOOL_KEYS` (`_cli/pep723.py:53`, today `frozenset({"job", "skill"})`) gives way to
    `SCRIPT_METADATA` (`job` only). `ScriptMetadata.skill` and the
    `TRANSITIONAL(third-party-host-seams/1.2)` site go. `test_pep723_skill_key.py`
    asserts the unknown-key warning instead of acceptance.

## Wave 7 — surfaces

- [ ] **7.1 `config path` and `config show`** (C1; AC1, AC2, AC5, AC7, AC11, AC24) —
  **[F]** `src/functualize/_cli/builtins/_config.py`, `tests/cli/test_config_builtin.py`
  - Lists `settings_layers()`; status from `ResolvedSettings.contributes`;
    annotations; `config show` provenance from the snapshot (removes
    `_determine_source` and its `read_global_config` call). Gate:
    `rg -n '\bread_global_config\b' src/functualize/_cli/builtins/_config.py`
    → 0; the definition remains until 8.1.
- [ ] **7.2 `info --json`** (C2; AC3, AC16) — **[F]** `src/functualize/_cli/info.py`,
  `tests/cli/test_info_unknown_keys.py` (new)

## Wave 8 — keep it single, docs, fixtures

- [ ] **8.1 Ratchets** (AC12, AC13, AC18, AC20, AC22, AC30, AC31) — **[F]** `tests/spec/test_settings_ratchet.py` (new)
  - *Rev6 [F] addition:* `src/functualize/_cli/config.py` and its affected
    `tests/cli/test_cli_config.py`, `tests/cli/test_cli_config_vault.py`,
    `tests/cli/test_resolve_cli_config.py`. Delete the transitional
    `read_global_config`, `SettingsFileInfo`, and `resolve_cli_config_layers`
    definitions after 4.3 and 7.1 have removed their callers. Gate:
    `rg -n '\b(read_global_config|SettingsFileInfo|resolve_cli_config_layers)\b'
    src/functualize --glob '*.py'` → 0, and the affected CLI config tests pass.
  - *Rev5 addition:*
    - AC31: no import of `functualize._cli.data`, `functualize._cli.config`
      or `functualize._cli.orchestrator` from `functualize.app`, `.job`,
      `.types`, `.plugin` or `.workflow`.
    - AC30: the render-surface pair has one executable declaration in
      `_types/enums.py` across 4.4's surface sites. The six executable hits
      listed in 4.4 have their stated owners or are outside this feature.
    - The public→`_cli` delivery imports are pinned at today's set (15 sites
      at `40c2a503` minus the 6 this revision assigns), so M8's outcome is a
      visible edit to that pin.
- [ ] **8.2 Off the run path** (AC10) — **[F]** `tests/cli/test_config_vocabulary_run_path.py` (new)
- [ ] **8.3 Fixtures** (F11; AC26) — **[F]** `tests/_cli/test_runtime_detection.py`,
  `tests/_cli/test_self_doctor.py`, `tests/spec/test_disabled_is_honoured_by_the_builtin_commands.py`,
  `tests/cli/test_config_upward_walk.py`
- [ ] **8.4 Docs, changelog, STATUS** (F12; AC15) — **[F]** `docs/cli/config.md`, `docs/guides/shell.md`,
  `docs/guides/configuration.md`, `CHANGELOG.md`, `.spec/STATUS.md`, `tests/spec/test_config_docs_ratchet.py` (new)
  - CHANGELOG: `### Fixed — …` (FOSS-127), plus `### Changed` rows for §3.8, including
    M6 (`FUNCTUALIZE_EXTRA_DIRECTORIES` → `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES`,
    `docs/cli/config.md:148`) and M5 (`skill` rejected). STATUS #22 and #29 closed
    (#29: removed, no consumer arrived).

## Wave 9 — checkpoint

- [ ] **9.1** The five gates; `dead_code_delta.py origin/master HEAD`; the live
  F1/F3a/F3b repros; an ADR for the one-declaration rule; then the
  deletion-only cleanup commit.
  - *Rev6 delta disposition:* `_cli/builtins/_helpers.py:381` assigns
    `_functualize_panel` dynamically in `_mount`; `NormalizingGroup.format_commands`
    reads that attribute through `_PANEL_ATTR` in `app/adapters/cli.py:158`.
    The reported `NEW_DEAD` finding is a static-analysis false positive, not a
    deletion task. Recheck the help-panel tests and record this classification
    with the final delta report.
  - The issue report `01a17856-37ac` records
    `tests/cli/test_workflow_answer_relational.py::…::test_resume_with_fused_input_answers_and_advances`
    as red on `master`. Check it against the base before classifying it as a
    branch regression; its separate ticket owns any baseline repair.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2"] },
    { "id": 1, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["3.1", "3.2"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["5.1", "5.2"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4"] },
    { "id": 7, "tasks": ["7.1", "7.2"] },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 9, "tasks": ["9.1"] }
  ]
}
```
