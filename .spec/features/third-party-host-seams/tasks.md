# Tasks — Seams for a third-party host package

Gates run at authoring time against `a2f453d`; each task records the count its
command returned. `[F]` equals the gate's hit set.

Ordering note: S4 and S5 are tiny and unblock the host package's agent-facing
work immediately, so they run in the first wave alongside the larger seams
rather than waiting behind them.

---

## 1. Small, independent seams

- [ ] **1.1 — S4: `job_detail` exposes the declaration**
  Add `tags`, `examples`, `extra_description`, `category` to the returned dict,
  read from `descriptor.declaration` and guarded for `None`.
  - `[F]` `src/functualize/_cli/info.py`, `tests/cli/test_info.py`
  - Acceptance: a test asserts the **exact** key set of `job_detail`, so a
    fifth declaration field cannot appear silently. Authoring-time key count:
    **12**; after: **16**.
  - Second acceptance: a convention-discovered job (no `@job`) renders
    `[]`, `[]`, `None`, `None` — not a `KeyError`, not absent.
  - `job_catalog` is unchanged — assert its key set too, as a guard.
  - Reachability: `func builtin info schema <job>` → `job_detail`. Verify by
    removing the four keys and watching the test fail.

- [ ] **1.2 — S5: `[tool.functualize] skill` is a known key**
  - `[F]` `src/functualize/_cli/pep723.py`, `tests/cli/test_pep723.py`
  - Acceptance: `grep -n "_KNOWN_TOOL_KEYS" src/functualize/_cli/pep723.py`
    shows `frozenset({"job", "skill"})`. Authoring-time: `frozenset({"job"})`
    at `:53`, with 3 total references at `:53`, `:137`, `:142`.
  - Second acceptance: a script declaring `skill = "x"` parses with **no**
    warning; a script declaring `bogus = "x"` still warns naming both known
    keys.
  - `ScriptMetadata.skill` is parsed and exposed. Nothing reads it — mark the
    site `# TRANSITIONAL(third-party-host-seams/1.2): parsed, not yet
    consumed; see plan.md §4`.

- [ ] **1.3 — S1a: promote the `ModulePreFilter` Protocol**
  Move the Protocol shape to `functualize/plugin`. `_primitives`
  implementations satisfy it structurally — no upward import.
  - `[F]` `src/functualize/plugin/__init__.py`, `src/functualize/_primitives/pre_filter.py`
  - Acceptance: `uv run lint-imports` green; a test asserts
    `isinstance(ASTModulePreFilter(...), ModulePreFilter)` via the
    `@runtime_checkable` Protocol.

---

## 2. Discovery hook

- [ ] **2.1 — S1b: `DiscoveryConfig.pre_filter`**
  Add the field and wire it to `DirectoryScanProvider`'s existing `pre_filter`
  parameter, **combined** with the `require_*`-derived filter (AND), not
  replacing it.
  - `[F]` `src/functualize/app/config.py`, `src/functualize/_app/boot.py`, `tests/discovery/test_pre_filter_hook.py`
  - Acceptance: `grep -c "pre_filter" src/functualize/app/config.py` ≥ 1.
    Authoring-time count: **0**.
  - Second acceptance: a test with two modules and a predicate rejecting one
    asserts only the other's jobs appear — **and** that a `require_file_prefix`
    set alongside still applies. Composition is AND, per the docstring.
  - Reachability: `FunctualizeApp(discovery=DiscoveryConfig(pre_filter=…))` →
    boot → provider. Verify by dropping the wiring and watching the test fail.
  - `[verify-e2e:TARGETED]`

---

## 3. Packaging surface

- [ ] **3.1 — S2a: create `app/packaging.py` by moving `runtime.py`**
  All of `_cli/runtime.py` moves: `InstallMode`, `Detection`,
  `RuntimeOverrideError`, `detect`, and the module privates. It is stdlib-only
  (verified: `os`, `tomllib`, `dataclasses`, `enum`, `pathlib`, `typing`), so
  nothing CLI travels with it.
  - `[F]` `src/functualize/app/packaging.py`, `src/functualize/_cli/runtime.py`, `tests/app/test_packaging.py`
  - Acceptance: `grep -rn "from functualize._cli.runtime import" src/` returns
    **0**. Authoring-time: the module is `_cli`-private with 4 `__all__` names.
  - Second acceptance: the existing `builtin self doctor` test passes
    unchanged. **Do not run `self update` or `self install`** — they mutate the
    developer's environment.

- [ ] **3.2 — S2b: move the command builders**
  `Requirement`, `install_commands`, `update_commands`, `uninstall_commands`,
  `capture_environment`, `names_to_restore`, `normalize` and the three error
  types move. `announce`, `plan_or_exit`, `refuse` **stay** in `_cli` — every
  `click` reference in the file is at line 723+, inside exactly those.
  - `[F]` `src/functualize/app/packaging.py`, `src/functualize/_cli/package_ops.py`, `tests/app/test_packaging.py`
  - Acceptance: `grep -n "click" src/functualize/app/packaging.py` returns
    **0**.
  - Second acceptance: `uv run lint-imports` green — `app/` must not acquire
    an import of any `_`-prefixed package.
  - The manifest API is **not** moved (`plan.md` §4).

---

## 4. Skill hosting

- [ ] **4.1 — S3a: plural resolution**
  Add `resolve_skills_locations()` and the `functualize.skills` entry-point
  scan. `SkillsLocation` gains `distribution` and `version`. A malformed or
  missing entry point warns and is skipped — never fatal, since this path is
  reachable from `func --help`.
  - `[F]` `src/functualize/_cli/skills.py`, `tests/cli/test_skills_hosting.py`
  - Acceptance: a test installs a fixture distribution declaring the entry
    point and asserts its skill appears. Authoring-time: `resolve_skills_dir`
    returns one location and has **3** call sites — `info.py:325`,
    `builtins.py:1482`, `builtins.py:1723`.
  - Second acceptance: a fixture whose entry point points at a missing module
    produces a warning and does not raise.

- [ ] **4.2 — S3b: migrate the three call sites and stamp per source**
  `builtin skills list | path | materialize | install` iterate. Materialization
  destination is `<distribution>-<version>`; core's own tree keeps
  `func-<version>` so existing agent configs keep working.
  - `[F]` `src/functualize/_cli/builtins.py`, `src/functualize/_cli/info.py`, `tests/cli/test_skills_hosting.py`
  - Acceptance: `grep -rn "resolve_skills_dir(" src/functualize/_cli/` returns
    only the definition. Authoring-time count: **3** call sites.
  - Second acceptance: a third-party skill materializes under **its own**
    distribution's version, not functualize's. This is the guarantee
    `_cli/skills.py:16` exists for; a shared stamp would break it.
  - `[verify-e2e:TARGETED]`

---

## 5. Documentation

- [ ] **5.1 — Document the five seams**
  `docs/guides/jobs-discovery.md` (S1), a new `docs/guides/packaging.md` or a
  section in `docs/cli/` (S2), `docs/guides/mcp.md` (S3, S4), and the PEP 723
  reference (S5).
  - `[F]` the doc files touched
  - Acceptance: every snippet executes; `mkdocs build --strict` exits 0.
  - Sequenced last so it describes shipped behaviour, per the constitution's
    *Transitional Changes* rule.

---

## 6. Checkpoint

- [ ] **6.1 — Full gate run**
  - Acceptance: `uv run pytest`, `uv run ruff check src/ tests/`,
    `uv run ruff format --check src/ tests/`, `uv run mypy src/`,
    `uv run lint-imports` — all green.
  - Walk `spec.md`'s A1–A6 and `contracts.md` item by item; record each as met.
  - `[verify-e2e:FULL]`

---

## Task Dependency Graph

Producer-before-consumer: 1.3 promotes the Protocol 2.1's field is typed
against; 3.1 creates `app/packaging.py` that 3.2 adds to; 4.1 adds the plural
resolver 4.2's call sites use.

Disjoint file sets, checked per wave:

| Wave | Task | Files |
|---|---|---|
| 0 | 1.1 | `_cli/info.py` |
| 0 | 1.2 | `_cli/pep723.py` |
| 0 | 1.3 | `plugin/__init__.py`, `_primitives/pre_filter.py` |
| 0 | 3.1 | `app/packaging.py`, `_cli/runtime.py` |
| 0 | 4.1 | `_cli/skills.py` |
| 1 | 2.1 | `app/config.py`, `_app/boot.py` |
| 1 | 3.2 | `app/packaging.py`, `_cli/package_ops.py` |
| 1 | 4.2 | `_cli/builtins.py`, `_cli/info.py` |

1.1 and 4.2 both touch `_cli/info.py`, which is why 4.2 is in wave 1 rather
than beside 4.1.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "3.1", "4.1"] },
    { "id": 1, "tasks": ["2.1", "3.2", "4.2"] },
    { "id": 2, "tasks": ["5.1"] },
    { "id": 3, "tasks": ["6.1"] }
  ]
}
```
