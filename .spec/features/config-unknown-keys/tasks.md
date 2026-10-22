# config-unknown-keys — Tasks (Revision 4)

Base `bb3aac77` (rebased 2026-10-21; `git merge-base --is-ancestor origin/master HEAD` → 0),
branch `sdd/config-unknown-keys`. Spec AC1–AC29, contracts C1–C6, plan rev4.
M1–M7 are closed (`01a15669`, `01a15ee0`). **Execute is gated on one thing:**
the maintainer's confirmation of this task list. Everything here is PR 1;
PR 2 (M7) gets its own plan after PR 1 merges.

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

- [ ] **3.1 Boot and engine** (AC17) — **[F]** `src/functualize/_app/boot.py`,
  `src/functualize/_engine/executor.py`, `tests/engine/test_shell_settings_source.py` (new)
  - Before moving, pin today's vault path for `sudo_password` (risk 1).
    `plugins.strict` and `shell.*` are then read from `app.settings`. Boot
    re-resolves `secret` settings with the vault source.
- [ ] **3.2 Public adapters** (AC19) — **[F]** `src/functualize/app/adapters/cli.py`,
  `src/functualize/app/adapters/surface_gate.py`, `tests/adapters/test_surface_gate.py`
  - No `_cli` import. Generated flags come from the schema. The surface gate
    reads `app.settings`. STATUS #22's test passes when run alone.

## Wave 4 — CLI (M2 b, M3, M4)

- [ ] **4.1 Pre-boot scan and flag parsing** — **[F]** `src/functualize/_cli/dispatch.py`,
  `src/functualize/_types/flag_grammar.py`, `tests/_cli/test_dispatch_flags.py` (new)
  - Flags are read from the schema and parsed into `Mapping[Setting, value]`.
    `_extract_global_options` is decomposed. `OPTIONAL_VALUE_VALID_SET` is
    renamed `GLOBAL_OPTION_ACCEPTED_VALUES` (F13).
- [ ] **4.2 `_cli/config.py`** (F9) — **[F]** `src/functualize/_cli/config.py`,
  `tests/cli/test_cli_config.py`, `tests/cli/test_cli_config_vault.py`, `tests/cli/test_resolve_cli_config.py`
  - `CliConfig` becomes a projection of `ResolvedSettings`. Delete
    `read_global_config`, `_RECOGNIZED_*`, `resolve_env_overrides`,
    `resolve_cli_config`'s own resolution, `resolve_cli_config_layers` and
    `SettingsFileInfo`. The warning tests (`test_cli_config.py:108,125,190`,
    `test_cli_config_vault.py:85`) become `config path` assertions.
- [ ] **4.3 Settings store and TUI** (M4) — **[F]** `src/functualize/_cli/data/func_settings.py`,
  `src/functualize/_cli/data/settings_schema.py`, `src/functualize/_cli/tui/__init__.py`,
  `src/functualize/_cli/tui/settings_panel.py`, `src/functualize/_cli/tui/settings_validator.py`,
  `src/functualize/_cli/tui/shell_mode.py`, `src/functualize/_cli/tui/app.py` (one read),
  `src/functualize/_cli/tui/source_chain_providers.py`, `src/functualize/_cli/tui/panels/settings_files.py`,
  `tests/cli/test_func_settings_store.py`, `tests/cli/test_settings_registration.py`
  - Remove the registries, `FuncSetting`, `_spec`, `_as_setting` and the
    import-time registration. Rows come from the schema (`surface="tui"`);
    values come from `app.settings`.

## Wave 5 — main and utils

- [ ] **5.1 `_cli/main.py`** — **[F]** `src/functualize/_cli/main.py`
  - Generated options replace the 16 decorators at `:140-223` (`@click.pass_context`
    `:228`). The typed flag layer replaces `cli_flags` (`:327-343`, `:2130-2134`).
    `PLUGINS_DISABLED` reads (`:383-385`, `:618-620`, `:1279-1281`, `:1437-1439`),
    `ALIASES` (`:772`, `:778`) and `JOBS_DIRECTORIES` (`:1790`) go through
    `app.settings`/`value_in`.
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
  `examples/standalone/deploy_tool/tests/test_deploy_tool.py`
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

- [ ] **8.1 Ratchets** (AC12, AC13, AC18, AC20, AC22) — **[F]** `tests/spec/test_settings_ratchet.py` (new)
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
    { "id": 4, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 5, "tasks": ["5.1", "5.2"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4"] },
    { "id": 7, "tasks": ["7.1", "7.2"] },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 9, "tasks": ["9.1"] }
  ]
}
```
