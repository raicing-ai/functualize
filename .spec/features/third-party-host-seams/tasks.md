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
  - **Third acceptance (maintainer, 2026-09-05): add a STATUS.md follow-up
    entry for it.** This knowingly creates a fourth instance of the
    "accepted, validated, and read by nothing" class that `.spec/STATUS.md`
    calls *"the worst of the three states"* — alongside `omit_defaults` (#14),
    `remote_first()` (#16), and the `job_providers` field being wired in the
    sibling feature. Shipping it early is deliberate, so the file format
    settles before a consumer exists; the entry is what keeps it counted
    rather than invisible.

- [ ] **1.3 — S1a: promote the `ModulePreFilter` Protocol, with `fingerprint()`**
  Move the Protocol shape to `functualize/plugin`. `_primitives`
  implementations satisfy it structurally — no upward import.

  **The Protocol gains a second method (maintainer, 2026-09-05):**

  ```python
  @runtime_checkable
  class ModulePreFilter(Protocol):
      def accepts(self, path: Path, source: str) -> bool: ...
      def fingerprint(self) -> str:
          """Stable identity of this filter's logic, for cache invalidation.

          Bump it when the predicate's behaviour changes.
          """
  ```

  **Why it is not optional.** The discovery cache persists *negative*
  pre-filter decisions and replays them, and it decides whether to trust them
  by hashing the discovery config. A caller-supplied predicate breaks that in
  both directions, and both were verified at authoring time:

  - **Hash the callable** → `_normalize_discovery_value`
    (`_primitives/cache_format.py`) falls through to `f"str({value})"`, and
    `str()` of a function is `'<function p at 0x7fd949036160>'` — an address
    that changes every process. The digest would differ on **every boot**,
    invalidating the cache on every run.
  - **Omit it** → reproduces the X1–X4 defect class verbatim: a warm cache
    replays decisions made under a *different* predicate. That is the bug
    ADR-010/ADR-011 exist to close, and it drove `CACHE_VERSION` 15→16→17.

  `fingerprint()` is the only option that keeps the cache both warm and
  correct.
  - `[F]` `src/functualize/plugin/__init__.py`, `src/functualize/_primitives/pre_filter.py`, `tests/plugin/test_module_pre_filter.py`
  - Acceptance: `uv run lint-imports` green; a test asserts
    `isinstance(ASTModulePreFilter(...), ModulePreFilter)` via the
    `@runtime_checkable` Protocol.
  - Second acceptance: a test asserts two filters with different
    `fingerprint()` values produce different discovery hashes, and that the
    **same** filter reconstructed in a fresh process produces the **same**
    hash. The second half is what proves the address problem is gone.

---

## 2. Discovery hook

- [ ] **2.1 — S1b: `DiscoveryConfig.pre_filter`**
  Add the field and wire it to `DirectoryScanProvider`'s existing `pre_filter`
  parameter, **combined** with the `require_*`-derived filter (AND), not
  replacing it.

  **The field must also join the cache fingerprint.** `DiscoveryConfig` has
  nine fields today and `_DISCOVERY_FINGERPRINT_FIELDS`
  (`_discovery/filter_factory.py:187`) mirrors them exactly.
  `tests/discovery/test_discovery_hash.py:101-104` asserts **set equality**
  between the two, with the docstring *"Guard against a tenth setting being
  added and silently uncovered."* This task adds exactly that tenth setting, so
  that test is a designed tripwire and **will fail** until the fingerprint is
  extended. It was missing from this task's `[F]` set and is added below.

  The fingerprint contribution is `pre_filter.fingerprint()` from 1.3, never
  the object itself.
  - `[F]` `src/functualize/app/config.py`, `src/functualize/_app/boot.py`, `src/functualize/_discovery/filter_factory.py`, `tests/discovery/test_discovery_hash.py`, `tests/discovery/test_pre_filter_hook.py`
  - Acceptance: `grep -c "pre_filter" src/functualize/app/config.py` ≥ 1.
    Authoring-time count: **0**.
  - Acceptance: `uv run pytest tests/discovery/test_discovery_hash.py` green —
    both the set-equality guard and the defaults guard.
  - Acceptance: a cold run, then a run with a **changed** `fingerprint()`,
    re-scans rather than replaying — the X4 direction, asserted for this field.
  - `_discovery` may not import the public `app.config` (constitution), which
    is why the defaults are duplicated in `filter_factory.py`; the tenth entry
    duplicates `None` the same way.
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
    only the definition. Authoring-time count: **3** call sites —
    `info.py:325`, `builtins.py:1482`, `builtins.py:1725` (the task previously
    said `:1723`; corrected 2026-09-05, and note `info.py:299` is a fourth
    *reference* that is an import, not a call).
  - Second acceptance: a third-party skill materializes under **its own**
    distribution's version, not functualize's. This is the guarantee
    `_cli/skills.py:16` exists for; a shared stamp would break it.

  **`skills path` becomes multi-line — a deliberate breaking change**
  (maintainer, 2026-09-05). It prints one location per line, consistent with
  `list` / `materialize` / `install`.

  Two published single-value consumers break and **must** change in this task:

  - `skills_path`'s own docstring (`_cli/builtins.py:1496`), which currently
    states *"Machine-readable on purpose — one path, no decoration, so it
    composes: `npx skills add "$(func builtin skills path)"`"*.
  - `README.md:924`: `cp -R "$(func builtin skills path)"/* .claude/skills/`

  Left unchanged, both substitute a multi-line string as a single argument and
  fail with a confusing "No such file or directory".
  - `[F]` (adds) `README.md`
  - Third acceptance: a test asserts `skills path` emits one line **per
    location**, and the README's replacement idiom is exercised by a
    doc-verify scenario rather than only being written down.
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
