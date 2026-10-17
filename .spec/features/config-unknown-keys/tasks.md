# config-unknown-keys — Tasks

Base: `origin/master` `d1c7e40a`. Branch: `sdd/config-unknown-keys`.
Spec: `spec.md` (AC1–AC11). Contracts: `contracts.md` (C1–C3). Plan: `plan.md`.

Authoring-time gate runs (2026-10-17, at `d1c7e40a`):

- `rg -n 'config_vocabulary' src/functualize` → **0 hits** (module does not exist yet).
- `rg -n 'def config_path' src/functualize/_cli/builtins.py` → **1 hit**, line 2412.
- `rg -n 'report\["config"\]' src/functualize/_cli/info.py` → **1 hit**, line 396.
- `uv run lint-imports` → 7 kept, 0 broken.

## Wave 0

- [ ] **1.1 — The check, as one `_cli/data` module** (C3; spec §3.1–3.3)
  - **[F]** `src/functualize/_cli/data/config_vocabulary.py` (new),
    `tests/cli/test_config_vocabulary.py` (new)
  - **Inputs:** `plan.md` §4.1, §4.2; `func_settings.FUNC_SETTINGS`,
    `func_settings.tui_settings`; `_cli.config._functualize_table`.
  - **Do:** `UnknownKey`, `find_unknown_keys`, `unknown_keys_in_file`,
    `unknown_keys_in_layers`, `describe`; `_READ_OUTSIDE_CATALOG` with a reader
    comment per entry; suggestion via `difflib.get_close_matches(n=1, cutoff=0.6)`.
  - **Tests (unit):** top-level typo → suggestion (`roots`→`root`); no-match
    → `None`; section typo dotted (`cli.outptu`→`cli.output`); `[my-job]`
    table → nothing (AC4); `[aliases]` free-form → nothing; nested table inside
    `[discovery]` → nothing; `[[vault_secret]]`, `[plugins] disabled`,
    `[discovery] jobs_directories` → nothing (AC5 vocabulary); pyproject: only
    `[tool.functualize]` (AC6); `[tui] them` with `clear_registered_settings()`
    → `tui.them`/`tui.theme` (AC8); **drift test** importing
    `functualize._config.project_dirs.LIST_KEYS` → every key known at top level
    and under `[discovery]`, plus `root`, `vault_secret`; **E1 census** over
    every `.functualize.toml`, `pyproject.toml` (`[tool.functualize]`) and
    `config.toml` under `examples/` and `evals/` → 0 findings (AC9).
  - **Invariants:** imports stdlib + `functualize._cli.*` only; no module-level
    state; no caching of the vocabulary.
  - **Acceptance:** `uv run pytest tests/cli/test_config_vocabulary.py -q`
    green; `uv run lint-imports` 7 kept / 0 broken;
    `rg -n 'config_vocabulary' src/functualize` → 0 hits (nothing calls it
    yet — **TRANSITIONAL(config-unknown-keys/2.1, 2.2)**: the module has no
    production caller until wave 1; do not mark `[x]` on reachability).

## Wave 1

- [ ] **2.1 — `config path` names unknown keys** (C1; AC1, AC2, AC5, AC6, AC7, AC11)
  - **[F]** `src/functualize/_cli/builtins.py`, `tests/cli/test_config_builtin.py`
  - **Do:** inside `config_path` only, lazy-import `config_vocabulary`;
    append `describe(unknown_keys_in_file(p))` to each printed line for the
    path `p` that line names. Add no path; change no status word.
    Net growth of `register_builtin_commands` ≤ 6 lines.
  - **Tests (CliRunner, isolated HOME/XDG):** AC1 exact line text; AC2 dotted
    section key; AC5 known-only file → output equal to the string the
    unmodified command prints (assert full output, not substring); AC6
    pyproject neighbour table ignored; AC7 global line annotated and stderr
    unchanged; exit 0 everywhere. AC11: the AC1 test is the regression test —
    it must fail on `e00d870` (record the failing run in the PR body).
  - **Acceptance:** `uv run pytest tests/cli/test_config_builtin.py -q` green;
    `rg -n 'config_vocabulary' src/functualize/_cli/builtins.py` → 1 hit.
  - **Reachability:** `func builtin config path` → `register_builtin_commands`
    → `config_path` → `config_vocabulary.unknown_keys_in_file`. Commit, then
    delete the `describe(...)` call and watch AC1 fail, then restore.

- [ ] **2.2 — `info --json` carries `config.unknown_keys`** (C2; AC3)
  - **[F]** `src/functualize/_cli/info.py`, `tests/cli/test_info_unknown_keys.py` (new)
  - **Do:** in `full_report`, lazy-import and set
    `report["config"]["unknown_keys"]` from
    `unknown_keys_in_layers(resolve_cli_config_layers())`; always present.
  - **Tests:** AC3 via `func builtin info --json` (CliRunner or subprocess):
    three entries, `file`/`key`/`suggestion`, `null` suggestion serialised;
    clean project → `[]`; `info all --json` carries the same field; plain
    `info` output unchanged.
  - **Acceptance:** `uv run pytest tests/cli/test_info_unknown_keys.py -q`
    green; `rg -n 'config_vocabulary' src/functualize/_cli/info.py` → 1 hit.
  - **Reachability:** `func builtin info --json` → `info_group` →
    `full_report` → `unknown_keys_in_layers`. Commit, remove the assignment,
    watch AC3 fail, restore.

## Wave 2

- [ ] **3.1 — Not on the run path** (AC10; shape H2)
  - **[F]** `tests/cli/test_config_vocabulary_run_path.py` (new)
  - **Do:** subprocess a `func <job>` run in a tmp project with an unknown key
    and assert `functualize._cli.data.config_vocabulary` is absent from
    `sys.modules` at exit, stderr has no unknown-key line, exit 0.
  - **Acceptance:** that file green; `rg -n 'config_vocabulary' src/functualize`
    → exactly 2 hits (`builtins.py`, `info.py`), both inside function bodies.

- [ ] **3.2 — Docs and changelog** (spec §3.5)
  - **[F]** `docs/cli/config.md`, `CHANGELOG.md`
  - **Do:** `config path` section: the annotation and an example; *Error
    Handling* table: unknown keys in any config file are reported by
    `config path` and `info --json`, run continues. `CHANGELOG.md` →
    `## [Unreleased]`: one `### Fixed — <one sentence>` entry, heading plus one
    paragraph, in the file's style; no tracker keys.
  - **Acceptance:** `rg -n 'unknown key' docs/cli/config.md` ≥ 1 hit;
    `rg -n '^### Fixed — .*unknown' CHANGELOG.md` → 1 hit.

## Wave 3

- [ ] **4.1 — Checkpoint**
  - **[F]** none (verification only; `.spec/STATE.md` local)
  - **Do:** `uv run ruff check --fix src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`,
    `uv run mypy src/`, `uv run lint-imports`, `uv run pytest -x -q --no-header`;
    `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`
    (expect 0 NEW_DEAD / 0 TESTS_ONLY); live E2 repro from `spec.md` §1 on the
    built `func`.
  - **Acceptance:** all five checks green; delta pasted into the hand-off;
    every task above `[x]` with its reachability evidence.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1"] }
  ]
}
```
