# config-unknown-keys — Tasks (Revision 2, proposed)

Base: `origin/master` `91947bb4` (rebased from `d1c7e40a`). Branch: `sdd/config-unknown-keys`.
Spec: `spec.md` AC1–AC16. Contracts: C1–C4. Plan: `plan.md` (R5).
**Execute is gated on M1–M4** (`plan.md` §6) and on confirmation of these tasks.

Authoring-time measurements (2026-10-19, `91947bb4`, AST walk, docstrings excluded):

- collection literals restating ≥ 2 config key names: **13 in 6 files** (AC12 baseline);
- config-key literals in read position: **91 in 9 files** (AC13 baseline);
- the same walk restricted to the structural names of AC16: **59 in 8 files**;
- `rg -n 'config_vocabulary|functualize_settings' src/functualize` → **0 hits**;
- `uv run lint-imports` → 7 kept, 0 broken.

Each task's gate includes `uv run lint-imports` and the AC14 pin
(`tests/config/test_vocabulary_pin.py`), both green.

## Wave 0 — pin, then declare

- [ ] **0.1 — Pin today's vocabulary** (AC14)
  - **[F]** `tests/config/test_vocabulary_pin.py` (new)
  - **Do:** record literal expected values, not imports compared with
    themselves: `SETTINGS_ORDER`, `DEFAULT_VALUES`, every setting's choices,
    bounds, `cli_flag` and `phase`, `FUNC_SCHEMA.env_var_for` per setting,
    `_RECOGNIZED_SECTIONS`/`_TOP_LEVEL_KEYS`/`_KEYS`, `_VALID_OUTPUT_FORMATS`,
    `LIST_KEYS`, `PROJECT_CONFIG_CANDIDATES` names,
    `_DISCOVERY_FINGERPRINT_FIELDS`, `DiscoveryConfig` field names, and
    `resolve_env_overrides()` for each of the 7 documented variables.
  - **Acceptance:** green at `91947bb4`, with no source change.

- [ ] **0.2 — The declaration** (C4)
  - **[F]** `src/functualize/_types/settings.py`,
    `src/functualize/_types/functualize_settings.py` (new),
    `src/functualize/app/config.py` (re-export),
    `tests/config/test_functualize_settings.py` (new)
  - **Do:** add `places`/`listed`/`env` and the `map`/`records` types; add the
    `setting`/`sections`/`keys_in`/`value_in` queries; declare every key
    once, with named constants; re-export `FUNCTUALIZE_SETTINGS` and the
    constants from `functualize.app.config`.
  - **Tests:** the declaration's names equal the union of today's statements
    (0.1's pinned sets); `value_in` follows the order of `places`; `keys_in("aliases")`
    is free-form; `_types` imports nothing internal.
  - **Acceptance:** both test files green.

## Wave 1 — derive (no behaviour change; disjoint files)

- [ ] **1.1 — `_config`**
  - **[F]** `src/functualize/_config/project_dirs.py`, `src/functualize/_config/merge.py`,
    `src/functualize/_config/vault_declarations.py`
  - **Do:** `LIST_KEYS` is derived from the declaration (settings whose places
    include `""` and `"discovery"`). The names in `PROJECT_CONFIG_CANDIDATES`
    come from `.sources` and the prefix. `root_key` defaults to `ROOT.key`.
    The vault reader uses `VAULT_SECRET.key`.
  - **Acceptance:** `uv run pytest tests/config -q` green; AC16 walk over
    these three files → 0.

- [ ] **1.2 — `_discovery` fingerprint**
  - **[F]** `src/functualize/_discovery/filter_factory.py`,
    `tests/discovery/test_discovery_hash.py`
  - **Do:** derive the fingerprint fields from the `[discovery]` filter
    settings, plus `pre_filter`. The drift half of the test (`:113`, `:127`)
    becomes an equality against the declaration.
  - **Acceptance:** `uv run pytest tests/discovery/test_discovery_hash.py -q`
    green; the fingerprint of an unset config is byte-identical (pinned digest).

- [ ] **1.3 — `_app` and `_engine` reads**
  - **[F]** `src/functualize/_app/boot.py`, `src/functualize/_engine/executor.py`
  - **Do:** `PLUGINS_STRICT`, `SHELL_PROGRAM` and `SHELL_SUDO_PASSWORD`
    supply section and key.
  - **Acceptance:** `uv run pytest tests/engine tests/plugin -q` green.

- [ ] **1.4 — `_cli` catalog views**
  - **[F]** `src/functualize/_cli/data/func_settings.py`,
    `src/functualize/_cli/data/settings_schema.py`, `src/functualize/_cli/tui/__init__.py`
  - **Do:** `_BASE_SETTINGS`/`tui_settings()`/`SETTING_SCHEMAS` become views
    over the declaration. `FuncSetting`, `FUNC_SETTINGS`, `FUNC_SCHEMA` and
    `register_settings` keep their signatures. `_spec`/`_tui_spec` and the
    `_as_setting` projection go away.
  - **Acceptance:** `uv run pytest tests/cli/test_func_settings_store.py tests/cli/test_settings_registration.py -q`
    green.

- [ ] **1.5 — `_cli/config.py`** (+ M3)
  - **[F]** `src/functualize/_cli/config.py`, `tests/cli/test_cli_config.py`,
    `tests/cli/test_cli_config_vault.py`
  - **Do:** derive `_RECOGNIZED_*` and `_VALID_OUTPUT_FORMATS`; resolve
    `[discovery]` by looping over the declared section. Apply M3 to the
    `read_global_config` warning. Under M3-recommended, remove it and update
    the tests asserting it (`test_cli_config.py:106,125,186`,
    `test_cli_config_vault.py:85`) to assert that the key is dropped and that
    `config path` reports it.
  - **Acceptance:** those tests plus `tests/cli/test_resolve_cli_config.py`
    green.

## Wave 2 — derive in the shared CLI files

- [ ] **2.1 — `app/utils.py` config reads**
  - **[F]** `src/functualize/app/utils.py`
  - **Do:** document reads (`:750-753`, `:972-1032`) go through `value_in`.
    The `overrides`/`effective` plumbing (`:843-867`) follows M2.
  - **Acceptance:** `uv run pytest tests/cli/test_auto_discover.py tests/cli/test_config_upward_walk.py -q` green.

- [ ] **2.2 — `_cli/main.py` config reads** (rebase onto MCH-194 if it landed first)
  - **[F]** `src/functualize/_cli/main.py`
  - **Do:** `PLUGINS_DISABLED` at `:360-362`, `:573-575`, `:1235-1237`
    and `:1355-1357`. `ALIASES` at `:727` and `:733`. `JOBS_DIRECTORIES` at
    `:1699`. The flag plumbing (`:304-320`, `:2039-2043`) follows M2.
  - **Acceptance:** `uv run pytest tests/cli -q -k "plugin or alias or disabled"` green;
    AC16 walk over `main.py` → 0.

## Wave 3 — the check

- [ ] **3.1 — `config_vocabulary`** (C3; AC4, AC5, AC6, AC8, AC9)
  - **[F]** `src/functualize/_cli/data/config_vocabulary.py` (new), `tests/cli/test_config_vocabulary.py` (new)
  - **Do:** as in Revision 1, but membership is
    `FUNCTUALIZE_SETTINGS.keys_in(section)` ∪ registered. No literal vocabulary.
  - **Acceptance:** test file green; the AC12 walk over the new module → 0.
    TRANSITIONAL until wave 4 adds its callers.

## Wave 4 — surfaces

- [ ] **4.1 — `config path`** (C1; AC1, AC2, AC5, AC6, AC7, AC11)
  - **[F]** `src/functualize/_cli/builtins.py`, `tests/cli/test_config_builtin.py`
  - **Do:** take the file names from `FUNCTUALIZE_SETTINGS.sources` (removes
    the literals at `:2419-2420`); add the annotation.
  - **Reachability:** break the `describe(...)` call and watch AC1 fail.
- [ ] **4.2 — `info --json`** (C2; AC3)
  - **[F]** `src/functualize/_cli/info.py`, `tests/cli/test_info_unknown_keys.py` (new)
  - **Reachability:** remove the assignment and watch AC3 fail.

## Wave 5 — keep it single

- [ ] **5.1 — Off the run path** (AC10) — **[F]** `tests/cli/test_config_vocabulary_run_path.py` (new)
- [ ] **5.2 — Source ratchet** (AC12, AC13, AC16)
  - **[F]** `tests/spec/test_config_vocabulary_ratchet.py` (new),
    `tests/spec/config_vocabulary_baseline.json` (new)
  - **Do:** an AST walk over `src/functualize/**` excluding
    `_types/functualize_settings.py`. AC12: 0 collection literals. AC13: a
    per-file count ≤ baseline, and the test fails with "lower the baseline"
    when a count drops without the file being edited. AC16: 0 structural
    names.
- [ ] **5.3 — Docs ratchet, docs, changelog** (AC15)
  - **[F]** `tests/spec/test_config_docs_ratchet.py` (new), `docs/cli/config.md`, `CHANGELOG.md`

## Wave 6 — checkpoint

- [ ] **6.1** — the five gates, `dead_code_delta.py origin/master HEAD`, and the
  live E2 repro. Migrate the durable rule ("one declaration in
  `_types/functualize_settings.py`; ratchet") to `.spec/STATUS.md` or an ADR
  before the deletion-only cleanup commit.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2"] },
    { "id": 1, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 6, "tasks": ["6.1"] }
  ]
}
```
