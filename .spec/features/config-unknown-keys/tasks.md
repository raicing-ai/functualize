# config-unknown-keys — Tasks (Revision 5)

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
the rev4 task list was confirmed (`01a1632b`). **Rev5 execution of row 3.2 and
beyond is gated on** the maintainer's confirmation of this amendment. M8 does
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
- [ ] **4.2 `_cli/config.py`** (F9) — **[F]** `src/functualize/_cli/config.py`,
  `tests/cli/test_cli_config.py`, `tests/cli/test_cli_config_vault.py`, `tests/cli/test_resolve_cli_config.py`
  - `CliConfig` becomes a projection of `ResolvedSettings`. Delete
    `read_global_config`, `_RECOGNIZED_*`, `resolve_env_overrides`,
    `resolve_cli_config`'s own resolution, `resolve_cli_config_layers` and
    `SettingsFileInfo`. The warning tests (`test_cli_config.py:108,125,190`,
    `test_cli_config_vault.py:85`) become `config path` assertions.
  - *Rev5 addition:* **[F]** += `src/functualize/app/commands.py`. The settings
    read at `:340-342` (`from functualize._cli.config import resolve_cli_config`;
    `obj["cli_config"] = resolve_cli_config()`) takes the `CliConfig` projection
    of `app.settings` instead. Gate: `rg -n '_cli\.config' src/functualize/app` → 0.
- [ ] **4.3 Settings store and TUI** (M4) — **[F]** `src/functualize/_cli/data/func_settings.py`,
  `src/functualize/_cli/data/settings_schema.py`, `src/functualize/_cli/tui/__init__.py`,
  `src/functualize/_cli/tui/settings_panel.py`, `src/functualize/_cli/tui/settings_validator.py`,
  `src/functualize/_cli/tui/shell_mode.py`, `src/functualize/_cli/tui/app.py` (one read),
  `src/functualize/_cli/tui/source_chain_providers.py`, `src/functualize/_cli/tui/panels/settings_files.py`,
  `tests/cli/test_func_settings_store.py`, `tests/cli/test_settings_registration.py`
  - Remove the registries, `FuncSetting`, `_spec`, `_as_setting` and the
    import-time registration. Rows come from the schema (`surface="tui"`);
    values come from `app.settings`.
- [ ] **4.4 Surface vocabulary** (F16; AC30; rev5 new) — **[F]** `src/functualize/_types/enums.py`,
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
  - One statement of `{"panel", "stdout"}`, today four: the enum
    (`orchestrator.py:28-29`), `_parse` (`:76-79`), `job/decorators.py:115`
    `_VALID_SURFACE_HINTS`, and `_types/functualize_settings.py:43` choices.
    The setting's choices and the decorator's valid hints derive from
    `RenderSurface`'s non-exclusive members; parsing is enum value lookup.
  - *Gate:* AC30. `rg -n '"panel"|"stdout"' src/functualize --glob '*.py'`
    leaves only `_types/enums.py` and docstrings. The surface-resolution and
    public-API-surface tests are green. `rg -n '_cli\.orchestrator' src` → 0.

## Wave 5 — main and utils

- [ ] **5.1 `_cli/main.py` and generated root flags** — **[F]** `src/functualize/_cli/main.py`,
  `src/functualize/app/adapters/cli.py` (rev5 added)
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
- [ ] **5.2 `app/utils.py`** — **[F]** `src/functualize/app/utils.py`
  - Document reads (`:750-753`, `:972-1032`) and the `overrides`/`effective`
    plumbing (`:843-867`) go through the declaration.
  - Gate (after 5.1 and 5.2): the AC13 walk over `src/` → 0 outside the owner
    and the resolver; plan risk 4's `rg` sweep is clean.

## Wave 6 — the check, surfaces, reserved names, example, PEP 723

- [ ] **6.1 Check** (C3; AC4, AC6, AC8, AC9) — **[F]** `src/functualize/_cli/data/config_vocabulary.py` (new),
  `tests/cli/test_config_vocabulary.py` (new)
- [ ] **6.2 Reserved names** (F14; AC23, AC27) — **[F]** `src/functualize/_types/discovery_report.py`,
  `src/functualize/_discovery/collisions.py`, `src/functualize/_config/sources.py`,
  `tests/discovery/test_reserved_section_names.py` (new)
  - A new `error_type` on #118's `DiscoveryFailure` (`_types/discovery_report.py:78`),
    built beside `job_name_collision` (`:152`). No second channel.
- [ ] **6.3 Example** (F7; AC21) — **[F]** `examples/standalone/deploy_tool/deploy_tool/main.py`,
  `examples/standalone/deploy_tool/tests/test_deploy_tool.py`,
  `src/functualize/_cli/data/func_settings.py`, `tests/cli/test_settings_store_second_app.py` (rev5 added)
  - *Rev5 addition:* delete `FUNC_SCHEMA` (`func_settings.py:512`), a second
    name for the declaration that no row removed. Its last caller after 5.1 is
    `deploy_tool/main.py:105-109`, which this row rewrites; the test pin at
    `test_settings_store_second_app.py:193-194` asserts against
    `FUNCTUALIZE_SETTINGS` instead. Gate: `rg -n '\bFUNC_SCHEMA\b' src examples` → 0.
- [ ] **6.4 PEP 723** (M5 closed: remove; AC29) — **[F]** `src/functualize/_cli/pep723.py`, `tests/cli/test_pep723_skill_key.py`, `tests/standalone/test_pep723.py`
  - `_KNOWN_TOOL_KEYS` (`_cli/pep723.py:53`, today `frozenset({"job", "skill"})`) gives way to
    `SCRIPT_METADATA` (`job` only). `ScriptMetadata.skill` and the
    `TRANSITIONAL(third-party-host-seams/1.2)` site go. `test_pep723_skill_key.py`
    asserts the unknown-key warning instead of acceptance.

## Wave 7 — surfaces

- [ ] **7.1 `config path` and `config show`** (C1; AC1, AC2, AC5, AC7, AC11, AC24) —
  **[F]** `src/functualize/_cli/builtins/_config.py`, `tests/cli/test_config_builtin.py`
  - Lists `settings_layers()`; status from `ResolvedSettings.contributes`;
    annotations; `config show` provenance from the snapshot (removes
    `_determine_source`).
- [ ] **7.2 `info --json`** (C2; AC3, AC16) — **[F]** `src/functualize/_cli/info.py`,
  `tests/cli/test_info_unknown_keys.py` (new)

## Wave 8 — keep it single, docs, fixtures

- [ ] **8.1 Ratchets** (AC12, AC13, AC18, AC20, AC22, AC30, AC31) — **[F]** `tests/spec/test_settings_ratchet.py` (new)
  - *Rev5 addition:*
    - AC31: no import of `functualize._cli.data`, `functualize._cli.config`
      or `functualize._cli.orchestrator` from `functualize.app`, `.job`,
      `.types`, `.plugin` or `.workflow`.
    - AC30: the surface values are stated only in `_types/enums.py`.
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
