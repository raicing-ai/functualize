# Tasks — Seams for a third-party host package

Gates run at authoring time against `a2f453d`; each task records the count its
command returned. `[F]` equals the gate's hit set.

Ordering note: S4 and S5 are tiny and unblock the host package's agent-facing
work immediately, so they run in the first wave alongside the larger seams
rather than waiting behind them.

---

## 1. Small, independent seams

- [x] **1.1 — S4: `job_detail` exposes the declaration**
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

  **Done 2026-09-06.** 12 tests in `tests/cli/test_job_detail_declaration.py`.

  - Acceptance met: `set(detail) == DETAIL_KEYS`, a 16-name literal, asserted
    for **both** shapes of job. The count went 12 → 16 as predicted.
  - Second acceptance met: a convention-discovered job renders `[]`, `[]`,
    `None`, `None`. Both shapes publish the same key set, which is the
    property that lets a consumer skip the branch entirely.
  - `job_catalog`'s key set is asserted unchanged. It is documented as
    "deliberately shallow", and widening it would cost every `func`
    invocation that renders a listing.
  - `tags`/`examples` are converted to `list`, not left as the declaration's
    tuples: this payload is JSON, and a tuple is not a JSON type. A caller
    reading the dict directly would otherwise get a tuple where the schema
    says array. Asserted, and the payload is round-tripped through `json`.
  - **The named reachability path is wrong.** `func builtin info schema` does
    **not** call `job_detail` — it renders `command_schemas`, which walks the
    command tree and builds from `node.params()`, and it has no `--json` flag
    because it is always JSON. `grep -n "job_detail"` finds exactly two
    callers: `full_report` (`builtin info --json`) and `info_jobs`
    (`builtin info jobs <name> --json`). Both are covered.
  - **Reachability, by sabotage**: removing the four keys → 11 failed;
    leaving `tags` a tuple → 3 failed.

- [x] **1.2 — S5: `[tool.functualize] skill` is a known key**
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

  **Done 2026-09-06.** 10 tests in `tests/cli/test_pep723_skill_key.py`.

  - Acceptance met: `_KNOWN_TOOL_KEYS == frozenset({"job", "skill"})`,
    asserted directly rather than by grep.
  - Second acceptance met: `skill = "x"` parses with **empty stderr**; a
    `bogus` key still warns and still names both known keys. A near-miss
    (`skills`, plural) still warns — adding a key to the set is not the same
    as widening the set to everything, and that distinction is what the
    warning exists for.
  - `_parse_tool_table` now returns a pair rather than a bare `job`, with one
    `_string()` helper applying the same "empty is not a value" rule to both
    keys. Non-string and empty values are covered.
  - Third acceptance met: **STATUS follow-up #29**, and the site carries the
    `# TRANSITIONAL(third-party-host-seams/1.2)` marker the task asked for.
  - **Reachability, by sabotage**: reverting `_KNOWN_TOOL_KEYS` → 4 failed;
    returning `None` for `skill` while keeping the key known → 3 failed.

- [x] **1.3 — S1a: promote the `ModulePreFilter` Protocol, with `fingerprint()`**
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

  **Done 2026-09-06.** 39 tests in `tests/plugin/test_module_pre_filter.py`.

  - **`[F]` extended (recorded):** `src/functualize/_types/protocols.py`. The
    Protocol went there rather than being defined in `plugin/__init__.py`,
    because that is where every other extension Protocol lives and it is the
    only layer both `_primitives` and `plugin` may import. `plugin/__init__.py`
    re-exports it exactly as it re-exports `JobProvider` and `JobTransform`.
    Defining it in `plugin/` would have forced `plugin` → `_primitives`, or a
    second definition. One object is asserted:
    `functualize.plugin.ModulePreFilter is _types.protocols.ModulePreFilter is
    _primitives.pre_filter.ModulePreFilter`.
  - **The method name is `should_import(source_file)`, not `contracts.md`'s
    `accepts(path, source)`.** The two disagree, and three things point the
    same way: `contracts.md`'s own prose says this *"promotes the existing
    shape rather than inventing one"*; this task's acceptance is
    `isinstance(ASTModulePreFilter(...), ModulePreFilter)`, which only holds
    for the existing shape; and all thirteen built-ins implement
    `should_import`. `accepts(path, source)` appears once, in a code block.
    Adopting it would mean rewriting every built-in and restructuring the
    scan to read each file once up front — a better design, and a different
    task. **Flagged for the maintainer**; changing it later is one Protocol
    plus thirteen renames.
  - Acceptance met: `lint-imports` green; `isinstance` asserted for **all
    thirteen** built-ins, not a sample, with a guard test that fails if a new
    filter class ships without joining the list — such a class would enter the
    discovery hash as nothing.
  - Second acceptance met, both halves. Different config, different class,
    different composition and different composition *order* all produce
    different fingerprints; identical config produces an identical one; and
    two fresh subprocesses agree with each other and with the in-process
    value. The last is what an `id()`-based identity would fail, and a test
    asserts directly that `str()` of two behaviourally identical functions
    differs — the reason this method exists.
  - Every built-in gained `fingerprint()` (13 methods), derived from the class
    name plus its configuration through one `_fingerprint()` helper. A short
    digest rather than the raw parts, so a filter configured with a long glob
    list cannot dominate the discovery fingerprint it joins.
  - **Reachability, by sabotage**: making `_fingerprint` ignore its inputs →
    5 failed.

---

## 2. Discovery hook

- [x] **2.1 — S1b: `DiscoveryConfig.pre_filter`**
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

  **Done 2026-09-06.** 8 tests in `tests/discovery/test_pre_filter_hook.py`,
  5 more in `tests/discovery/test_discovery_hash.py`.

  - Wired in `build_pre_filter_from_config`, not in `boot.py`. Both boot paths
    and `app.utils.build_discovery_cache_provider` call that one builder, so
    the seam is where the stack is assembled rather than in each caller. The
    `[F]` set named `_app/boot.py`; it needed no change.
  - Composed last in the AllOf. The built-ins are ordered cheapest-first so an
    expensive check runs on the fewest files, and a caller's filter is of
    unknown cost — which is assumed expensive.
  - Acceptance met: `grep -c "pre_filter" src/functualize/app/config.py` → **1**
    (authoring-time 0).
  - The designed tripwire fired as predicted and is now green:
    `test_fingerprint_covers_every_discovery_config_field` asserts set equality
    between `DiscoveryConfig.__dataclass_fields__` and
    `_DISCOVERY_FINGERPRINT_FIELDS`, and the tenth entry closes it. Whole file:
    **25 passed**.
  - The digest takes `fingerprint()`, never the object, via a new
    `_fingerprint_contribution`. A filter that has no `fingerprint()` raises
    `TypeError` rather than being hashed by `str()` — silently accepting it is
    the X1-X4 replay defect, and the message says what to add.
  - X4 asserted twice: as a digest (`test_a_changed_stamp_re_digests`) and as
    behaviour through a real cold/warm cycle
    (`test_a_changed_filter_rescans_rather_than_replaying`). The warm half is
    asserted too, because a digest that moved every boot would pass the X4 half
    alone while rescanning every run.
  - Composition is AND, in both directions: a `require_file_prefix` set
    alongside still rejects, and the caller's filter still rejects what the
    prefix admits.
  - **Reachability, by sabotage** (4 mutations, backup/restore, never
    `git checkout`): never appending the filter → 3 failed; substituting the
    stack instead of composing → 2 failed; dropping the tenth fingerprint entry
    → 4 failed; hashing the object instead of `fingerprint()` → 2 failed.
  - `[verify-e2e:TARGETED]` **met in a real process.** A `main.py` building the
    app with a `RejectSkipme` filter lists `alpha-job` only; bumping the
    filter's stamp and widening it to accept everything makes `beta-job`
    reappear on the next run, against the cache the first run wrote to
    `~/.cache/functualize/<project-hash>/cache.json` (which does hold the
    persisted negative decision for `beta_skipme.py` — checked directly).

  - **Found in passing: the eager path applies no discovery filter at all.**
    With `lazy=False`, `resolve_and_register_jobs` calls
    `JobRegistry.scan_and_register_headless` instead of the pipeline provider
    the boot path just built, and `_scan_directory_headless` enumerates via
    `pkgutil.iter_modules` taking no filter argument. So `require_file_prefix`,
    `exclude_patterns` and the rest are silently ignored there — a pre-existing
    defect far wider than this field (verified: `registry.py` and `boot.py` are
    untouched by this feature). Out of scope for a task that adds a field.
    Pinned by `TestTheEagerPathFiltersNothing`, which characterizes the gap on
    `pre_filter` **and** on `require_file_prefix`, so a future fix fails loudly
    and findably rather than being invisible. Recorded in `.spec/STATUS.md`.

---

## 3. Packaging surface

- [x] **3.1 — S2a: create `app/packaging.py` by moving `runtime.py`**
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

  **Done 2026-09-06.** `git mv` — the whole module, no shim left behind. 12
  tests in `tests/app/test_packaging.py`.

  - Acceptance met: `grep -rn "from functualize._cli.runtime import" src/` →
    **0**, and the grep runs inside a test rather than once by hand. All six
    `src/` consumers and four test files were repointed at
    `functualize.app.packaging`.
  - Second acceptance met: `tests/_cli/test_self_doctor.py`,
    `test_runtime_detection.py`, `test_package_ops.py` and `test_plugin_cmd.py`
    — **193 passed, 9 skipped**, changed only in their import line. Neither
    `self update` nor `self install` was run.
  - No shim: `_cli/runtime.py` is gone and asserted un-importable. A shim would
    let a consumer keep the private path and never learn the public one exists.
  - "Nothing CLI travels with it" is asserted three ways: no `functualize._`
    import in the source, no `click`, and — stronger, because a transitive
    import would not show up in the source — a subprocess that imports the
    module and asserts **no** `functualize._cli.*` entry appears in
    `sys.modules`.
  - **`detect`'s real signature is not `contracts.md`'s.** §S2 sketches
    `detect(tool: str = "functualize") -> Detection`; the actual signature is
    `detect(prefix, base_prefix, environ, argv0, cwd)`, with
    `detect_from_process()` as the no-argument entry point. The explicit form
    is deliberate — `sys.prefix` cannot be set by an environment variable, so
    a version reading it directly could only be exercised in whichever mode
    the suite happens to run under. This task is a *move* ("nothing about the
    semantics changes"), so the real signature is what became public and the
    sketch is what is wrong. Pinned by an `inspect.signature` assertion, and
    `detect_from_process` added to `__all__` since it is the ergonomic door.
  - **`A2`'s stated gate was already false at authoring time.**
    `grep -rn "from functualize._cli" src/functualize/app/` returns **14**, and
    `git grep` confirms all fourteen predate this feature (`adapters/cli.py` 6,
    `click_params.py` 3, `surface_gate.py` 2, `tui.py` 1, `commands.py` 2).
    The meaningful version — `app/packaging.py` itself importing no `_cli` —
    is what the tests assert.

- [x] **3.2 — S2b: move the command builders**
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

  **Done 2026-09-06.** 6 new tests in `tests/app/test_packaging.py` (19 in the
  file); `_cli/package_ops.py` went 835 -> 279 lines.

  - The split is **planning vs. deciding**, and that line turned out to be
    sharper than the task's list. Everything that returns argv or reads the
    environment moved -- the named eight plus `capture`, `Receipt`,
    `read_receipt`, `merge_receipt`, `drop_from_receipt`, `_rebuild`,
    `resolve_uv`, `resolve_pipx`, `owned_python`, `_bundled_pip`, which the
    named functions call and which are equally terminal-free. What stays is
    what needs a terminal: `announce`, `plan_or_exit`, `refuse`, plus `render`,
    `script_name`, the `_call` seam, `run_commands`, and the pending-update
    file, which is CLI config-directory bookkeeping rather than a fact about
    the installation.
  - Acceptance met: `grep -c "click" src/functualize/app/packaging.py` → **0**.
  - Second acceptance met: `lint-imports` → 5 kept, 0 broken; mypy 317 files
    clean. `app/packaging.py` imports only stdlib.
  - **No shim**, matching 3.1. `self_cmd.py` and `plugin_cmd.py` import
    `functualize.app.packaging` directly for the moved names and keep
    `package_ops` for the interactive half.
  - **Four test files monkeypatched the moved functions on the wrong module.**
    `monkeypatch.setattr(package_ops, "resolve_uv", ...)` no longer reaches
    `install_commands`, which now resolves the name in `packaging`'s globals —
    so the patch would have become a silent no-op and the tests would have
    reached for the real `uv`. Repointed in `test_package_ops.py`,
    `test_self_manage.py`, `test_plugin_cmd.py`.
  - **Two of 3.1's own assertions were broken by documentation, not by code.**
    `assert "functualize._cli" not in source` and `assert "click" not in
    source` are substring searches over a module that *explains what it
    deliberately does not do* — the standalone-update docstring names
    `functualize._cli.self_update`. Rewritten as AST import checks in both
    `tests/app/test_packaging.py` and
    `tests/_cli/test_no_installation_discovery.py`, each with its own
    can-this-fail guard. A substring test cannot tell an import from a sentence
    about one.
  - The `grep -n "click" … returns 0` gate was literally 1 at first, from one
    prose mention. Reworded rather than waived, and the real property is now
    pinned structurally instead of by that grep.
  - **Reachability, by sabotage**: a `click` import in the planner → 2 failed
    (one in each file); the planner calling `subprocess.call` → 2 failed;
    `announce` leaking into the public module → 2 failed.
  - `tests/_cli/test_no_installation_discovery.py` follows the code again: the
    two `which` holders are now asserted against `packaging.py`, and
    `package_ops.py` joined the modules that must never touch `PATH`.

---

## 4. Skill hosting

- [x] **4.1 — S3a: plural resolution**
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

  **Done 2026-09-06.** 10 tests in `tests/cli/test_skills_hosting.py`.

  - Acceptance met, with the fixture faked at the `importlib.metadata` seam
    rather than by installing a real wheel: a real install would mutate the
    developer's environment, and `entry_points(group=...)` is the exact
    surface the code reads. Its skill appears, `list_skills` reads it, and
    core still comes first.
  - Second acceptance met: a missing module and a path that is not a directory
    each warn and are skipped, and core is still returned in both cases — the
    point of skipping rather than failing, since this path is reachable from
    `func --help`.
  - Per-source stamping is in place: `SkillsLocation` gained `distribution`
    and `version`, defaulting to `functualize` so the two existing
    construction sites stay valid. `resolve_skills_dir()` is retained and
    still answers for core alone; the three call sites migrate in 4.2.
  - **A vacuous test, caught by sabotage.** Removing the `is_dir()` guard
    changed nothing: the not-a-directory entry point was being rejected by
    `PackageNotFoundError` from `version("broken")` instead, so the assertion
    held whether or not the guard existed. Stubbing `version` makes the guard
    the only thing that can reject it; that mutation now fails.
  - **Reachability, by sabotage**: stamping a third-party location with
    functualize's own distribution → 2 failed; never scanning entry points →
    4 failed; dropping the `is_dir()` guard → 1 failed.

- [x] **4.2 — S3b: migrate the three call sites and stamp per source**
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

  **Done 2026-09-06.** 17 new tests in `tests/cli/test_skills_hosting.py` (27
  in the file), plus `examples/docs/scenarios/q-skills-hosting.toml`.

  - All four subcommands iterate. `_require_skills_location()` became
    `_require_skills_locations()`; `path`, `list`, `materialize`, `install` and
    the `builtin info` skills block each report every location.
  - Acceptance met, with one honest deviation:
    `grep -rn "resolve_skills_dir(" src/functualize/_cli/` returns **2**, not
    1 — the definition, and the call inside `resolve_skills_locations()` that
    builds core's entry. That second one is 4.1's design, not a stray caller:
    the plural resolver is *defined* in terms of the singular. No command calls
    it directly any more, which is what the gate is for.
  - Second acceptance met, **through the CLI**: `builtin skills materialize`
    writes `func-<functualize version>` and `otherpkg-9.9.9` as separate trees,
    and asserts `otherpkg-<functualize version>` is not among them.
  - Third acceptance met both ways: `test_path_emits_one_line_per_location`
    pins the line count against two locations, and `q-skills-hosting.toml`
    *runs* the README's loop, copies the skills, and checks a real `SKILL.md`
    landed — 6/6 steps green.
  - `materialized_root` and `materialize_skills` gained `distribution`. Core
    keeps the `func-` stem rather than becoming `functualize-`: agent configs
    already point at `func-<version>`, and renaming would break every one of
    them for nothing. `--prune` now scopes to the distribution's own prefix —
    a bare `func-` prefix would have one host delete another's tree.
  - **A second breaking change, disclosed:** `full_report()["skills"]` was an
    object or `null` and is now a **list**, always present, `[]` when empty —
    the same rule `discovery_failures` and `config` follow. An object could
    only ever describe core, which is the defect this task fixes. Each entry
    carries its own `distribution` and `version`.
  - **A sabotage passed on the first attempt, and that was the real finding.**
    Hard-coding `distribution="functualize"` inside the `materialize` command
    changed nothing: every materialization test called `materialize_skills()`
    directly, so the *callee* was covered and the wiring — which is the entire
    task — was not. `test_the_materialize_command_stamps_each_source_separately`
    drives the CLI, and that mutation now fails.
  - **Reachability, by sabotage** (6 mutations): `path` answering with core
    only → 2 failed; a shared materialization stamp → 2 failed (after the fix
    above); `list` stamping a host with functualize's version → 2 failed;
    `install` targeting core only → 2 failed; `info` reporting core only → 2
    failed; `--prune` crossing distributions → 1 failed.
  - The 4.1 test fixture faked `entry_points` too narrowly — it asserted the
    group was the skills group, which raises as soon as a test drives the whole
    CLI, since boot also scans the *plugin* entry-point group. Now it answers
    for the skills group and defers everything else to the real implementation.
  - Both published single-value consumers changed: `skills_path`'s docstring
    now documents the loop and says why substitution is wrong, and `README.md`
    replaced `cp -R "$(func builtin skills path)"/*` with a `while read` loop.

---

## 5. Documentation

- [x] **5.1 — Document the five seams**
  `docs/guides/jobs-discovery.md` (S1), a new `docs/guides/packaging.md` or a
  section in `docs/cli/` (S2), `docs/guides/mcp.md` (S3, S4), and the PEP 723
  reference (S5).
  - `[F]` the doc files touched
  - Acceptance: every snippet executes; `mkdocs build --strict` exits 0.
  - Sequenced last so it describes shipped behaviour, per the constitution's
    *Transitional Changes* rule.

  **Done 2026-09-06.** One new guide, two extended, two doc-verify scenarios.

  - **S1** → `docs/guides/jobs-discovery.md`, as named: a new section covering
    `DiscoveryConfig.pre_filter`, why it composes rather than replaces, why
    `fingerprint()` is mandatory and what identity-hashing would do instead,
    and an admonition for the `lazy=False` gap (STATUS #30) so the page does
    not promise filtering on a path that has none.
  - **S4** → `docs/guides/mcp.md`, as named: what an agent learns about a job,
    including that a convention-declared job renders the *same shape* with
    empty values rather than a different one.
  - **S2, S3, S5** → one new page, `docs/guides/hosting.md`, rather than the
    three the task sketched. **A deliberate deviation.** The task suggested
    `docs/guides/packaging.md` for S2 and `mcp.md` for S3; but S2, S3 and S5
    have one audience — *your distribution is what the user installed, and
    functualize is inside it* — and splitting them across a packaging page and
    the MCP adapter page would scatter one story over two unrelated ones. S3
    in particular has nothing to do with MCP. Added to `mkdocs.yml` nav under
    Guides.
  - Acceptance met: `mkdocs build --strict` exits **0**.
  - Second half of the acceptance — *every snippet executes* — met by running
    them, not by reading them:
    - `examples/docs/scenarios/r-hosting-guide.toml`, **11/11 green**, covers
      every claim on the new page: the three `Detection` attributes, `StrEnum`
      printing as the bare value, all six modes, the three planning calls, the
      `ValueError` backstop, the three exception types, the no-CLI-import
      property, the entry-point group spelling, both materialization stems, the
      three `skills` commands, and both PEP 723 branches (`skill` parses
      silently; an unknown key warns without failing).
    - `examples/docs/scenarios/q-skills-hosting.toml`, **7/7 green**, runs
      `README.md`'s replacement loop (4.2's `[F]`).
  - **Two corrections the run forced, both drift the prose would have shipped:**
    - The guide first wrote `print(detection.mode)  # InstallMode.TOOL_UV`.
      `InstallMode` is a `StrEnum`, so it prints `tool_uv`. Corrected, and the
      spelling is now asserted.
    - The "asking what would change it" snippet called `update_commands`
      against the *live* detection, which is degraded in a checkout and raises.
      Rewritten behind the `detection.degraded` guard the page already tells
      the reader to write.
  - **A process finding worth keeping.** The first local run of
    `q-skills-hosting` passed against `~/.local/bin/func` — a *stale 0.1.2
    release*, not this worktree — so it verified an old binary and said green.
    CI does `PATH="$PWD/.venv/bin:$PATH"` (`ci.yml`); a local run without it is
    testing whatever `func` happens to be installed. Both scenarios were re-run
    correctly, and the second one caught a real wrong assertion: `skills list`
    prints `source checkout … (not version-pinned)` in a checkout, never a
    version stamp.
  - `run-scenario` has three engines — `shell`, `docker`, `pty`. There is no
    `python` engine; the first draft invented one and the scenario errored on
    load. The Python assertions run as `shell` steps with heredocs, the pattern
    `k-plugin-lifecycle.toml` already uses.

---

## 6. Checkpoint

- [x] **6.1 — Full gate run**
  - Acceptance: `uv run pytest`, `uv run ruff check src/ tests/`,
    `uv run ruff format --check src/ tests/`, `uv run mypy src/`,
    `uv run lint-imports` — all green.
  - Walk `spec.md`'s A1–A6 and `contracts.md` item by item; record each as met.
  - `[verify-e2e:FULL]`

  **Done 2026-09-07.** Feature closed: 10/10 tasks, 4 waves.

  ### Gates

  | Gate | Result |
  |---|---|
  | `uv run pytest` | **8959 passed, 1544 skipped** |
  | 13 plugin suites (one directory at a time) | all green — 448 passed, 1 skipped |
  | `uv run ruff check src/ tests/` | clean |
  | `uv run ruff format --check src/ tests/` | 1041 files already formatted |
  | `uv run mypy src/` | 317 files, no issues |
  | `uv run lint-imports` | 5 contracts kept, 0 broken |
  | `uv run mkdocs build --strict` | exit 0 |

  ### Acceptance criteria

  | # | Result |
  |---|---|
  | **A1** | Met. `grep -c "pre_filter" src/functualize/app/config.py` → **1** (was 0). `tests/discovery/test_pre_filter_hook.py` rejects one module of two and asserts only the other's jobs appear, with a control proving the second is otherwise discoverable. |
  | **A1b** | Met, both halves. `test_a_changed_stamp_re_digests` (digest) and `test_a_changed_filter_rescans_rather_than_replaying` (behaviour, through a real cold/warm cycle). The same filter in a fresh process yields the same hash — `test_the_address_is_not_what_is_hashed` proves the two objects have different `str()` and the same digest. |
  | **A2** | Met, with the gate's literal form corrected. `grep -rn "from functualize._cli" src/functualize/app/packaging.py` → **0**. The criterion as written says the whole `app/` directory stays 0; it is **14**, and all fourteen predate this feature (recorded under 3.1: `adapters/cli.py` 6, `click_params.py` 3, `surface_gate.py` 2, `tui.py` 1, `commands.py` 2). The meaningful version — the new public module importing no `_cli`, transitively either — is asserted three ways including a subprocess `sys.modules` check. |
  | **A3** | Met. A fixture distribution declaring `functualize.skills` has its skill appear in `list_skills`, in `resolve_skills_locations()`, and in all four `builtin skills` commands. Faked at the `importlib.metadata` seam rather than by installing a wheel — a real install would mutate the developer's environment, and `entry_points(group=…)` is the exact surface the code reads. |
  | **A4** | Met. `job_detail` carries all four keys (`info.py:165-168`), 16 total. Pinned by `tests/cli/test_job_detail_declaration.py` (12 tests). Verified live: `builtin info`'s skills block renders the new per-source stamps in a real process. |
  | **A5** | Met. `_KNOWN_TOOL_KEYS = frozenset({"job", "skill"})`. A script declaring `skill` parses it with no warning, and an unknown key still warns without failing — both asserted as unit tests *and* executed as doc-verify steps. |
  | **A6** | Met — the table above. |

  ### `contracts.md` — three signature drifts, all resolved toward the code

  1. **S1 writes `accepts(self, path: Path, source: str) -> bool`.** The shipped
     method is `should_import(self, source_file: Path) -> bool` — the name the
     thirteen built-in filters in `_primitives/pre_filter.py` have always used,
     and which the whole discovery path calls. The contract itself says this
     seam *"promotes the existing shape rather than inventing one"*, so the
     existing name is what was promoted. **Flagged for the maintainer.**
  2. **S2 writes `detect(tool: str = "functualize") -> Detection`.** The real
     signature is `detect(prefix, base_prefix, environ, argv0, cwd)` with
     `detect_from_process()` as the no-argument door. Explicit on purpose:
     `sys.prefix` cannot be set by an environment variable, so a version
     reading it directly could only ever be exercised in whichever mode the
     suite happens to run under. 3.1 was a *move*, so the shipped signature is
     what became public. Pinned by an `inspect.signature` assertion.
  3. **S2 writes `install_commands(req: Requirement, mode: InstallMode) ->
     list[list[str]]`.** The real signature is
     `install_commands(detection: Detection, package: str) -> tuple[tuple[str,
     ...], ...]`, and the same for `update_commands` / `uninstall_commands`.
     `Requirement` is a *uv receipt entry*, not an install request, so the
     sketch had the wrong type in the wrong position; and the return is
     immutable tuples rather than lists.

  Everything else in `contracts.md` shipped as written: `fingerprint()`
  load-bearing and enforced, the tenth `DiscoveryConfig` field contributing
  `fingerprint()` rather than the object, AND composition, `SkillsLocation`
  gaining `distribution` and `version`, `resolve_skills_locations()` with core
  first, per-source materialization with core keeping `func-<version>`, a
  broken entry point warning rather than raising, `plan_or_exit`/`refuse`/
  `announce` staying in `_cli`, the manifest API deferred, `job_catalog`
  unchanged, and the additive `job_detail` keys with a convention-declared job
  rendering `[]`, `[]`, `None`, `None`.

  ### `[verify-e2e:FULL]`

  Full doc-verify suite, run as CI runs it (`PATH="$PWD/.venv/bin:$PATH"`):
  **18 scenarios, 13 passed, 4 pty-skipped by policy (`CLAUDE.md:11`), 1
  failed.** The failure is `l-standalone-binary`, exit 127 — the pre-existing
  STATUS #28 defect in that scenario's own `xargs -I{} {} -c` recipe, unrelated
  to this feature and unchanged by it.

  Both new scenarios green: `r-hosting-guide` 11/11, `q-skills-hosting` 7/7.
  Plus two real-process checks outside the harness: an app booted with a
  caller-supplied `pre_filter` lists only the admitted job and re-scans when
  the filter's stamp changes (2.1), and `builtin info` renders the per-source
  skills stamps (4.2).

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
