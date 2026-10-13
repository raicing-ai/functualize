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

- [ ] **1.1** NFKC first in the naming policy
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
      `("a" + c).isidentifier()` and `NFKC(c) == c`, assert the new result on
      `"a" + c + "_b"` equals the frozen one.
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

## Wave 1

- [ ] **2.1** Warm-boot cache version 22
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

- [ ] **2.2** Config-file sections through the shared naming rule
  - *Inputs:* B7, D1; `contracts.md` § *Config-file sections*.
  - *Depends on:* 1.1.
  - *Files:* `src/functualize/_config/sources.py`,
    `tests/config/test_config_section_spelling.py`.
  - *Change:*
    - Extract a private `_find_section(config, section)` with steps 1–3
      verbatim, then step 4: the unique key whose `normalize_name` equals
      `normalize_name(section)`, at top level and per level of a dotted walk.
    - `_section_data` and `reject_inline_provider` both call it, and the
      duplicated spelling tuple (`:695`) goes away.
    - Several distinct step-4 matches raise `ConfigurationError` naming the
      section and the sorted keys.
  - *Must not touch:* `EnvSource`, `env_name_for`, `group_env_name_for`,
    `missing_value.env_var_for` (D1 exclusion).
  - *Tests (AC7, AC8):*
    - `[job_aaǆ] x = 1` supplies `x` for section `job-aadž`;
    - a secret field there with legacy inline provider syntax raises the
      existing `ValueError`;
    - `[Job_AAǆ]` plus `[job_aaǆ]` for section `job-aadž` raises
      `ConfigurationError`;
    - `[env_cfg]` and `[env-cfg]` precedence is unchanged (existing cases);
    - `env_name_for("job-aadž", "field") == "JOB_AADŽ_FIELD"`.
  - *Gate:* `uv run pytest -q --no-header tests/config/test_config_section_spelling.py tests/config/test_dotted_config_sections.py tests/config/test_env_name_rule_parity.py > /tmp/functualize-t22.log 2>&1`.
  - *Reachability:* `FileSource.get` → `_section_data` → `_find_section`
    (`_config/sources.py:723`). Remove step 4 and watch the `[job_aaǆ]` case
    go red.

- [ ] **2.3** End-to-end surfaces (test-only)
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

## Wave 2

- [ ] **3.1** Docs, changelog, codemap
  - *Inputs:* B8, B9; D2.
  - *Depends on:* 2.1, 2.2, 2.3.
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

## Wave 3

- [ ] **3.2** Full verification and handoff
  - *Depends on:* 3.1.
  - *Files:* none (verification only).
  - *Gate:*
    - `uv run ruff check src/ tests/ plugins/ examples/`, `uv run ruff format --check src/ tests/ plugins/ examples/`,
      `uv run mypy src/` and `uv run lint-imports`, each redirected to
      `/tmp/functualize-<cmd>.log`;
    - `uv run pytest -x -q --no-header > /tmp/functualize-fast.log 2>&1`;
    - `uv run python .github/scripts/dead_code_delta.py c03dfb72 HEAD`. Classify
      each finding KNOWN or UNMARKED. The phase is advisory.
    - Tip tier: dispatch `gh workflow run CI --ref sdd/job-name-nfkc-resolution`
      and do not wait on it.
  - *Evidence:* every log's tail line, the dead-code output, and the CI run URL.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1", "2.2", "2.3"]},
    {"id": 2, "tasks": ["3.1"]},
    {"id": 3, "tasks": ["3.2"]}
  ]
}
```
