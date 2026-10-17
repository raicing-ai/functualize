# Tasks — job-name NFKC resolution

Read first: `spec.md` (behaviour B1–B9, AC1–AC9), `contracts.md`, `plan.md`
(§ *Alignment*, § *Surviving smells*). Shape: `SD/16613377`, Approved.

**Where.** Worktree `/home/ubuntu/orca/workspaces/functualize/sdd-job-name-nfkc`,
branch `sdd/job-name-nfkc-resolution`, based on `origin/master` `c03dfb72`.
Write nowhere else.

**Rules that bind every task:**

- **Wave ordering is binding.** No task in wave N+1 starts while wave N has an
  unchecked task.
- **Test first.** Write each task's new tests, run its gate, and see it **red**
  on the unmodified source before changing source. Paste the red output into
  the task's completion evidence.
- **Reachability precedes `[x]`.** Name the production call path, then
  sabotage: commit first, break the call, watch the gate go red, then restore.
- **Isolate the runtime cache in every test that boots an app.**
  `monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))`. A shared
  `~/.cache/functualize/<hash>/state.db` aborts boot with
  `RuntimeStoreSelectionError` (observed while re-verifying this spec).
- **The write-time spec gate does not load in Multica runs.** Obey it by hand:
  this file's graph is what authorises `src/functualize/**` writes.
- **Commit messages:** conventional, lowercase, one scope token. No tracker key,
  no agent `Co-authored-by` (`message-hygiene`).
- **`uv run`, never bare `python`.** Long output goes to `/tmp/functualize-<cmd>.log`.
  At most 2 pytest invocations per verification.

## Wave 0

- [x] **1.1** NFKC first in the naming policy
  - *Inputs:* B1, B3; `contracts.md` § *Public API surface*.
  - *Files:* `src/functualize/_types/naming.py`, `tests/discovery/test_naming.py`.
  - *Change:*
    - `import unicodedata`.
    - Add a private `_nfkc`.
    - `normalize_segment` runs its existing loop over `_nfkc(segment)`.
    - `normalize_name` and `resolve_name._canonical` NFKC the whole name before
      `split(".")`.
    - `resolve_name`'s step-3 `"." in candidate` test reads the NFKC'd candidate.
    - The docstrings cite PEP 3131.
  - *Invariants:*
    - output equals the old rule for NFKC-stable input;
    - idempotent;
    - the exact → canonical → leaf → `LookupError` order is unchanged;
    - `BUILTIN_SEGMENT` and reserved-sigil checks are unchanged.
  - *Tests to add to `test_naming.py`:*
    - `normalize_segment("job_aaǆ") == "job-aadž"`; `normalize_segment("ǆ_ops") == "dž-ops"`.
    - **Stability sweep (AC1, E2):** keep a frozen private copy of the pre-change
      loop inside the test module. For every code point `c` with
      `("a" + c).isidentifier()` and `NFKC("a" + c + "_b") == "a" + c + "_b"`,
      assert the new result on `"a" + c + "_b"` equals the frozen one.
      Separately assert that U+0301 composes with the preceding `a`.
    - **Idempotence:** `normalize_segment(normalize_segment(x)) == normalize_segment(x)`
      over all identifier-continue `c` in `"a" + c`.
    - **AC2:** `normalize_name("ｄｅｐｌｏｙ．ｗｅｂ") == "deploy.web"` and
      `resolve_name("ｄｅｐｌｏｙ．ｗｅｂ", ["deploy.web", "other.web"]) == "deploy.web"`.
    - **AC2 negative:** `resolve_name("ａ．ｂ", ["x.b"])` raises `LookupError`.
      The NFKC'd candidate is dotted, so no leaf match.
    - `resolve_name("job_aaǆ", ["job-aadž"]) == "job-aadž"`.
  - *Gate:* `uv run pytest -q --no-header tests/discovery/test_naming.py > /tmp/functualize-t11.log 2>&1`.
    Red before the change (the new cases fail), green after.
  - *Then the step tier:* `uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)`.
    Run it only if the mapper exits 0 and prints paths.
  - *Reachability:* the production path is `ExecutionEngine.get_job` →
    `resolve_name` → `_canonical` → `normalize_segment`
    (`_engine/executor.py:776-818`). That is proven end to end in 2.3. Here,
    delete the `_nfkc(...)` wrap and watch the new cases go red.
  - *Evidence:* red and green logs, the sabotage run, and `git diff --stat`.
    Red: `/tmp/functualize-t11-red.log` (4 failed, 19 passed). Green:
    `/tmp/functualize-t11-fastpath.log` (23 passed); step tier:
    `/tmp/functualize-t11-step.log` (140 passed, 58 skipped). After committing,
    replacing `_nfkc` with the identity function made the four new behavior
    cases fail in `/tmp/functualize-t11-sabotage.log`; the committed function
    was restored. Production reaches the policy through
    `ExecutionEngine.get_job` → `resolve_name` → `_canonical` →
    `normalize_segment`; wave 1's integration task proves that path end to end.
    The five-name benchmark's median over three rounds of 500,000 calls was
    1.423 s before and 1.298 s after the ASCII fast path. *(Design note,
    2026-10-16: this figure is not evidence of a speed-up. The fast path's
    whole effect is about 10 ns of a ~2 µs call, so a −9% result is noise at
    this scale. The cost evidence of record is task 2.4's counter gate and
    its committed harness.)* The task diff covered
    this file, `src/functualize/_types/naming.py`, and
    `tests/discovery/test_naming.py`.

## Wave 1

- [x] **2.1** Warm-boot cache version 22
  - *Inputs:* B6, D2; `contracts.md` § *Persisted formats*.
  - *Depends on:* 1.1.
  - *Files:* `src/functualize/_primitives/cache_format.py`,
    `tests/discovery/test_nfkc_cache_rebuild.py` (new).
  - *Change:* `CACHE_VERSION = 22`, plus a `# v22 (<date>):` log line in the
    style of `:129-155`: string-set names are now NFKC'd, so a cached
    descriptor may carry a pre-NFKC name.
  - *Test (AC6, E4):*
    - write a jobs dir with `JOB_GROUP = "ǆ_ops"` / `def run_it`;
    - write a cache file with `"version": 21` holding a descriptor named
      `ǆ-ops.run-it` (use the same writer the existing cache tests use in
      `tests/discovery/test_cache_manager.py:70`);
    - boot; assert the job is listed as `dž-ops.run-it` and the cache file now
      says `22`.
  - *Gate:* `uv run pytest -q --no-header tests/discovery/test_nfkc_cache_rebuild.py tests/discovery/test_cache_manager.py tests/discovery/test_sync_algorithm.py > /tmp/functualize-t21.log 2>&1`.
  - *Reachability:* `_discovery/cached_provider.py:329`
    (`data.get("version") != CACHE_VERSION`). Set it back to 21 and watch the
    new test go red.
  - *Evidence:* `/tmp/functualize-t21-red.log` recorded 1 failed, 36 passed:
    the old cache name survived when version 21 was accepted.
    `/tmp/functualize-t21-green.log` recorded 37 passed after the bump.
    After committing, setting `CACHE_VERSION` back to 21 made the new test fail
    in `/tmp/functualize-t21-sabotage.log`; the committed version was restored.
    The production path is provider construction → `_load_cache` → version
    comparison → `list_jobs` → source reimport → persisted version 22.

- [x] **2.2** Config-file sections through the shared naming rule
  - *Inputs:* B7, D1; `contracts.md` § *Config-file sections*.
  - *Depends on:* 1.1.
  - *Files:* `src/functualize/_config/sources.py`,
    `tests/config/test_config_section_spelling.py`.
  - *Change:*
    - Extract a private `_find_section(config, section)` with steps 1–3
      verbatim, then step 4: the unique key whose `normalize_name` equals
      `normalize_name(section)`, at top level and per level of a dotted walk.
    - `_section_data` uses the ordered lookup. `reject_inline_provider` uses
      the same `normalize_name` policy but scans every equivalent flat or
      dotted table per file, even when value lookup selects an earlier table.
      The duplicated spelling tuple (`:695`) goes away.
    - Several distinct step-4 matches raise `ConfigurationError` naming the
      section and the sorted keys.
  - *Must not touch:* `EnvSource`, `env_name_for`, `group_env_name_for`,
    `missing_value.env_var_for` (D1 exclusion).
  - *Tests (AC7, AC8):*
    - `[job_aaǆ] x = 1` supplies `x` for section `job-aadž`;
    - a secret field there with legacy inline provider syntax raises the
      existing `ValueError`;
    - exact, legacy and NFKC tables can coexist; a provider URI in a
      shadowed table still raises `ValueError`, including for a dotted table;
    - `[job-aaǆ]` plus `[job_aaǆ]` for section `job-aadž` raises
      `ConfigurationError` naming both keys. Neither key is reached by steps
      1–3, and both normalise to `job-aadž`;
    - `[job_aadž]` plus `[job_aaǆ]` for section `job-aadž` returns the
      `[job_aadž]` table **without** raising. Step 2's `-`→`_` swap reaches it
      first, so step 4 never runs (B7: steps 1–3 unchanged);
    - *Fixture history:* the first draft named `[Job_AAǆ]`, which cannot
      collide (`normalize_name('Job_AAǆ') == 'job-a-adž'`, from the
      acronym-aware camel split). The correction routed on 2026-10-16,
      `[job_aadž]`, cannot reach step 4 either, because step 2 matches it.
      Both were measured with `uv run python` on `fbb66f7e`. The pair above is
      the one that reaches step 4. This is a fixture repair inside AC7's own
      words; AC7 is unchanged;
    - `[env_cfg]` and `[env-cfg]` precedence is unchanged (existing cases);
    - `env_name_for("job-aadž", "field") == "JOB_AADŽ_FIELD"`.
  - *Gate:* `uv run pytest -q --no-header tests/config/test_config_section_spelling.py tests/config/test_dotted_config_sections.py tests/config/test_env_name_rule_parity.py > /tmp/functualize-t22.log 2>&1`.
  - *Reachability:* `FileSource.get` → `_section_data` → `_find_section`
    for values; `JobConfigView.reject_inline_provider` →
    `FileSource.reject_inline_provider` → `_matching_sections` for secret
    validation. Remove the NFKC match and watch the `[job_aaǆ]` case go red;
    select only the first match and watch shadowed-provider cases go red.
  - *Evidence:* Valid TOML quotes the non-ASCII table key (`["job_aaǆ"]`);
    the first red run exposed that syntax requirement. With valid TOML,
    `/tmp/functualize-t22-red2.log` recorded 4 failed and 46 passed. The final
    gate `/tmp/functualize-t22-green2.log` recorded 51 passed. After committing,
    disabling the normalized fallback made four new behavior tests fail in
    `/tmp/functualize-t22-sabotage.log`; the committed source was restored.
    The initial implementation used `_find_section` in both paths.
  - *Review correction (2026-10-17):* the first-match lookup suppressed a
    legacy provider URI in a shadowed spelling. With valid TOML, four new
    coexistence cases failed (`4 failed, 7 passed`) before the repair and the
    focused config/integration selection passed afterward (`63 passed`).
    `_matching_sections` now scans all equivalent tables per parsed file while
    `_find_section` retains value precedence. The broader config, integration
    and spec selection passed (`1198 passed, 122 skipped`). After committing,
    restoring the first-match guard made all four new cases fail (`4 failed,
    7 deselected`); the committed source was restored. Ruff check/format,
    mypy and all seven import contracts passed.

- [x] **2.3** End-to-end surfaces (test-only)
  - *Inputs:* B2, B4, B5; AC3, AC4, AC5.
  - *Depends on:* 1.1.
  - *Files:* `tests/integration/test_nfkc_job_names.py` (new).
  - *Test setup:* one temp project, isolated `XDG_CACHE_HOME`, booted through
    `FunctualizeApp(job_sources=JobSources(directories=[...]))` and driven with
    `click.testing.CliRunner` over `app.cli_command`. That is the same harness
    as `tests/context/test_parallel_and_log_properties.py`.
  - *Cases:*
    - **AC3:** a parent that calls `rc.invoke("job_aaǆ")` exits 0, and the child
      ran. A parent that calls `rc.invoke_parallel([("job_aaǆ", {})])` exits 0
      with child status SUCCESS. Argv `["job_aaǆ"]` and `["job-aadž"]` both
      exit 0.
    - **AC4:** a job declared `@job(deps=Deps("job_aaǆ"))` boots and runs its
      dependency. Argv `["ǆ_ops", "run-it"]` and `["dž-ops", "run-it"]` both run
      the grouped job.
    - **AC5:** two modules with `JOB_GROUP = "ǆ_ops"` and `JOB_GROUP = "dž_ops"`,
      each defining `run_it`, produce a `job_name_collision` discovery finding
      (`_types/discovery_report.py`).
  - *Gate:* `uv run pytest -q --no-header tests/integration/test_nfkc_job_names.py > /tmp/functualize-t23.log 2>&1`.
    Red on `c03dfb72` without 1.1. Green after 1.1.
  - *Reachability:* these are the production call paths themselves:
    - `WiredInvoke.__call__` → `engine.get_job` (`_engine/capabilities/invoke.py:411`);
    - `_ParallelBatch` → `engine.get_job` (`:839`);
    - `detect_mode` → `normalize_segment` (`_cli/dispatch.py:217`);
    - `app/adapters/cli.py:136`.

    Sabotage by reverting 1.1's `_nfkc` wrap and watching every AC3/AC4 case go
    red. If AC5 fails after 1.1, stop: report it as a finding against
    `_discovery/collisions.py` and do not weaken the assertion (plan R3).
  - *Evidence:* `/tmp/functualize-t23-first.log` recorded 8 passed through
    booted app/CLI and cached-provider collision paths. After committing,
    replacing `_nfkc` with the identity function made all 8 cases fail in
    `/tmp/functualize-t23-sabotage.log`, including AC3/AC4 and the AC5
    collision; committed source was restored. Every booting test isolates
    `XDG_CACHE_HOME`.

- [x] **2.4** Cost gate for the naming policy (AC10, test-only)
  - *Inputs:* B10; the member's 2026-10-16 ask that `normalize_segment` stay
    performant because it runs for every job.
  - *Depends on:* 1.1.
  - *Files:* `tests/discovery/test_naming_cost.py` (new) and
    `tests/perf/bench_naming.py` (new, a runnable script, not collected:
    no `test_` prefix).
  - *Deterministic gate (fast tier):* wrap `functualize._types.naming.unicodedata`
    in a counting proxy with `monkeypatch.setattr` and assert these exact
    counts of `normalize` calls:
    - `normalize_segment(s)` → **0** for every ASCII `s` in a fixed list:
      `deploy-web`, `myJobName`, `HTTPServer`, `build_wheel`, `a`, and the
      empty string. → **1** for each non-ASCII `s`: `job_aaǆ`, `naïve_x`,
      `ｄｅｐｌｏｙ`;
    - `normalize_name(n)` → `[n is not ASCII] + (number of non-ASCII segments
      of NFKC(n))`. Pin the rows measured on `fbb66f7e`: `web.deploy` → 0,
      `ǆ_ops.run_it` → 2, `ｄｅｐｌｏｙ．ｗｅｂ` → 1, `naïve.x` → 2,
      `a.ǆ.b` → 2;
    - `resolve_name` with an ASCII candidate over ASCII known names → **0**
      (`resolve_name("build_wheel", ["build-wheel", "x.y"])`);
    - **identity:** `naming._nfkc(s) is s` for `deploy` and for the
      NFKC-stable non-ASCII `naïve_x`.

    A future edit that normalises per character, builds a table per call or
    drops the ASCII fast path changes a count and goes red.
  - *Harness (evidence, not a gate):* `tests/perf/bench_naming.py`
    - holds `PRE`, a frozen copy of the pre-change loop. Import `_pre_nfkc_segment` from
      `tests/discovery/test_naming.py:14` rather than writing a second copy.
      If importing a test module is awkward, move that function into
      `tests/discovery/_naming_reference.py` and import it from both places;
    - holds `POST = normalize_segment`;
    - runs interleaved PRE/POST rounds (15 rounds × 50,000 calls, minimum per
      side) over the four inputs in the 2026-10-16 measurement table:
      `deploy-web`, `myJobName`, `job_aaǆ`, `naïve_x`;
    - prints ns/call per side and the ratio, plus the interpreter version and
      host name.

    Run it with `uv run python tests/perf/bench_naming.py`. The task evidence
    pastes its output.
  - *Timing observation (report-only):* the `slow`-marked test calls the
    harness for two ASCII names and emits the measured ratios as warnings,
    visible in CI's warnings summary. It imposes no wall-clock threshold.
    The standalone script also reports ASCII and non-ASCII examples. The
    deterministic counter and identity assertions above enforce the contract.
  - *Gate:*
    - `uv run pytest -q --no-header tests/discovery/test_naming_cost.py > /tmp/functualize-t24.log 2>&1`
      (counts and identity; must pass);
    - `uv run pytest --run-slow -q --no-header tests/discovery/test_naming_cost.py > /tmp/functualize-t24-slow.log 2>&1`
      (counts and identity must pass; warning ratios are report-only);
    - `uv run python tests/perf/bench_naming.py` (report its measurements,
      without a timing verdict).
  - *Red evidence:* the implementation already exists (1.1), so red comes from
    sabotage. Commit, then replace `_nfkc`'s body with
    `unicodedata.normalize("NFKC", value)`, which drops the ASCII fast path.
    The ASCII count rows go red. Restore.
  - *Reachability:* `normalize_segment` is the function every registration
    and lookup reaches (`ExecutionEngine.get_job` → `resolve_name` →
    `_canonical` → `normalize_segment`, `_engine/executor.py:776-818`).
  - *Original evidence:* `/tmp/functualize-t24.log`: 17 passed, 2 slow skipped;
    `/tmp/functualize-t24-slow.log`: 19 passed locally. After committing, removing the
    ASCII fast path made 12 deterministic rows fail in
    `/tmp/functualize-t24-sabotage.log`; committed source was restored.
    `uv run python tests/perf/bench_naming.py` reported on Python 3.13.15,
    host vmi3464921, in ns/call (pre → post, ratio):
    `deploy-web` 1921.6 → 1940.1 (1.010×), `myJobName` 2211.5 → 2175.1
    (0.984×), `job_aaǆ` 1439.3 → 2109.0 (1.465×), `naïve_x` 1470.4 →
    1662.8 (1.131×). The script at `tests/perf/bench_naming.py` reproduces
    these measurements; the deterministic call counter is the fast-tier gate.
  - *CI correction (2026-10-17):* Python 3.11 CI measured `deploy-web`
    4141.3 → 6004.9 ns/call (1.450×) and `myJobName` 5060.3 → 6338.6
    ns/call (1.253×), failing the optional 1.25× assertion while all call-count
    rows passed. The original local observations remain above as history; the
    ratio became a report-only `slow` warning as risk R4 prescribed. The same
    script remains runnable by hand. No production source or deterministic
    assertion changed.

## Wave 2

- [x] **3.1** Docs, changelog, codemap
  - *Inputs:* B8, B9; D2.
  - *Depends on:* 2.1, 2.2, 2.3, 2.4.
  - *Files:* `docs/guides/jobs-discovery.md`, `CHANGELOG.md`,
    `contributor/architecture/group-trie.md`.
  - *Change:*
    - **jobs-discovery** § *Job names are canonical* (`:30-62`):
      - add the row `def job_aaǆ()` → `job-aadž` → `func job_aaǆ` or `func job-aadž`;
      - add one sentence that names are NFKC-normalised first, as Python does
        to identifiers;
      - extend the *Environment variables* bullet: the variable is spelled from
        the registered name (`JOB_AADŽ_FIELD`).
    - **CHANGELOG** `[Unreleased]`: a `### Fixed` entry covering a job name
      written with a character Python rewrites (`invoke`, `invoke_parallel`,
      CLI, config sections), plus one paragraph for D2: a string-set name with
      such a character changes identity, its cached state is not migrated, and
      it re-runs once.
    - **group-trie.md:75-77:** replace "lowercase, strip non-alphanumeric" with
      the real rule (NFKC, lowercase, `_`/space → `-`, acronym-aware camel
      split).
  - *Gate:*
    - `rg -n "NFKC" docs/guides/jobs-discovery.md CHANGELOG.md contributor/architecture/group-trie.md`
      must hit all three files;
    - `rg -n "strip non-alphanumeric" contributor/architecture/group-trie.md`
      must return nothing.
  - *Evidence:* `rg -n 'NFKC'` returned one hit in each required document, and
    `rg -n 'strip non-alphanumeric'` returned none. After committing, removing
    the codemap's NFKC mention made its required positive search miss; the
    committed text was restored. The docs describe the production path through
    registration, CLI resolution, invoke and config-file lookup, including the
    TOML quoting required for non-ASCII table keys.

## Wave 3

- [x] **3.2** Full verification and handoff
  - *Depends on:* 3.1.
  - *Files:* none (verification only).
  - *Gate:*
    - `uv run ruff check src/ tests/ plugins/ examples/`, `uv run ruff format --check src/ tests/ plugins/ examples/`,
      `uv run mypy src/` and `uv run lint-imports`, each redirected to
      `/tmp/functualize-<cmd>.log`;
    - `uv run pytest -x -q --no-header > /tmp/functualize-fast.log 2>&1`;
    - `uv run pytest --run-slow -q --no-header tests/discovery/test_naming_cost.py > /tmp/functualize-cost-slow.log 2>&1`
      and `uv run python tests/perf/bench_naming.py`, both pasted (AC10);
    - `uv run python .github/scripts/dead_code_delta.py c03dfb72 HEAD`. Classify
      each finding KNOWN or UNMARKED. The phase is advisory.
    - Tip tier: dispatch `gh workflow run CI --ref sdd/job-name-nfkc-resolution`
      and do not wait on it.
  - *Evidence:* every log's tail line, the dead-code output, and the CI run URL.
    `ruff check`: All checks passed; `ruff format --check`: 1663 files already
    formatted; `mypy src/`: no issues in 393 source files; `lint-imports`:
    7 contracts kept, 0 broken. The exact unpartitioned fast command exceeded
    the repository's 570-second cap at 98% with no reported failure. Its first
    run stopped at a stale test assertion expecting cache version 21; the
    corrected assertion is committed, passed in its focused test and went red
    when sabotaged back to 21. To complete the same fast selection within the
    command cap, `/tmp/functualize-fast-a.log` covered seven named directories
    (6150 passed, 1017 skipped), and `/tmp/functualize-fast-b.log` covered
    `tests/` excluding those directories (6427 passed, 610 skipped). Both used
    six workers and exited 0. AC10 originally passed 19 tests with the slow
    timing assertion locally; its later CI failure and report-only correction
    are recorded under task 2.4. `tests/perf/bench_naming.py` output is also
    recorded there.
    Dead-code delta `c03dfb72..f02994e5`: NEW_DEAD 0, TESTS_ONLY 0; two
    pre-existing neighbourhood findings (`ProviderRegistry.get_format_provider`,
    `TrieResolution.is_group_listing`). The tip CI workflow was dispatched at
    https://github.com/raicing-ai/functualize/actions/runs/38944198080; it is
    not awaited by this task.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"]},
    {"id": 2, "tasks": ["3.1"]},
    {"id": 3, "tasks": ["3.2"]}
  ]
}
```
