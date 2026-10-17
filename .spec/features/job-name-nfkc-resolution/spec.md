# Spec — one job name for its written and its parsed spelling

Shape: **Shape Intent — NFKC-Stable Job-Name Resolution**, Confluence `SD/16613377`,
`Authority: Approved` (v3, 2026-10-13T06:02:44Z). Contract decided by the owner:
**(i-a)**. D1 and D2 were accepted as drafted. Evidence: `research.md` in this
directory, re-verified on `origin/master` `c03dfb72` (§ *Evidence baseline*).

## Goal

A job whose name contains a character Python rewrites under NFKC is reached by
the spelling its author wrote **and** by the spelling Python registered. That
holds on every surface that names a job, because the one naming policy applies
NFKC before anything else.

## Why

Python NFKC-normalises identifiers when it parses them (PEP 3131) but leaves
string literals and `argv` alone. `def job_aaǆ` registers as `job-aadž`. Then
`rc.invoke("job_aaǆ")`, `rc.invoke_parallel([("job_aaǆ", {})])` and
`func job_aaǆ` all fail to find it. On Python 3.13, 573 of the 2233 lowercase
letters are affected, and 3631 of the characters Python allows in a name.

## Behaviour

**B1. The canonical form starts with NFKC.** `normalize_segment(s)` equals the
existing lowercase-and-hyphenate rule applied to `unicodedata.normalize("NFKC", s)`.
`normalize_name` and `resolve_name` apply NFKC to the **whole** dotted name
before splitting it on `.`. A typed compatibility dot (U+FF0E, U+2024, …)
therefore separates a group exactly as `.` does, never inside a segment.

**B2. Written and parsed spellings resolve alike.** For a job defined as
`def <w>` and registered as `normalize_segment(NFKC(<w>))`, each of these reaches
the job:

- `rc.invoke("<w>")`
- `rc.invoke_parallel([("<w>", {})])`
- `func <w>` and its group form `func <group> <w>`
- `@job(deps=Deps("<w>"))`, `FromJob["<w>"]` and workflow references
- `func builtin vault … --job <w>` and `func builtin info jobs <w>`
- the MCP workflow tools

The rewritten spelling keeps working.

**B3. A name that is already NFKC-stable keeps its identity.** For every `s`
with `NFKC(s) == s`, the new `normalize_segment(s)` equals the old one. All
ASCII names fall in this set.

**B4. Names set as strings are canonicalised too.** `JOB_GROUP`,
`@job(name=…, group=…)`, entry-point names and programmatic registration go
through `normalize_segment`, so `JOB_GROUP = "ǆ_ops"` registers as `dž-ops`
(today: `ǆ-ops`). Typing `ǆ_ops` still reaches it, by B2.

**B5. Two names that become one collide visibly.** `JOB_GROUP = "ǆ_ops"` and
`JOB_GROUP = "dž_ops"`, each defining `run_it`, are one job address. The
existing collision rule (`_discovery/collisions.py`) reports it. Neither job
silently replaces the other without a discovery finding.

**B6. The warm-boot cache is rebuilt once.** `CACHE_VERSION` goes from 21 to 22.
A v21 cache is discarded on first boot, not trusted, so a cached descriptor
cannot carry a pre-NFKC name.

**B7. A config-file section written in either spelling configures the job** (D1).
A `functualize.toml` table `[job_aaǆ]` configures `job-aadž`, for both reading
values and the legacy inline-provider check on secret fields. Lookup order:

1. the exact key;
2. the existing `-`↔`_` swaps;
3. the existing dotted-table walk;
4. **new:** the one top-level key, or the one key at each level of a dotted
   walk, whose `normalize_name` equals the section's.

Steps 1–3 are unchanged, so every file that resolves today resolves the same
way. If step 4 finds more than one distinct key, lookup raises
`ConfigurationError` naming the section and every matching key. It never picks
one. Because step 4 uses the shared rule, `[Build_Wheel]` now also configures
`build-wheel`, the same way `func Build_Wheel` already runs it.

**B8. Environment-variable keys are excluded, and the docs say so** (D1). The
variable name stays derived from the registered (rewritten) name:
`JOB_AADŽ_FIELD`, not `JOB_AAǄ_FIELD`. `EnvSource` and `env_name_for` do not
change.

**B9. State under an old spelling is not migrated** (D2). Fingerprint and step
records keyed by a pre-change string-set name are orphaned: that job re-runs
once and caches normally afterwards. `CHANGELOG.md` says so. The census for
this repo finds **0** such names (§ *Evidence baseline*).

**B10. The policy stays cheap on the common path** (the member's ask,
2026-10-16: "normalize_segment is something run for every job, it needs to
be performant"):

- `normalize_segment`, `normalize_name` and `resolve_name` make **no** call
  into `unicodedata.normalize` for ASCII input;
- otherwise they make at most one call per non-ASCII segment, plus one for a
  non-ASCII whole dotted name;
- NFKC-stable input comes back from the private `_nfkc` as the identical
  object.

Cost is pinned by call counts, not by wall-clock. A same-process ratio on
ASCII input is reported as supporting evidence only (AC10).

## Acceptance criteria

Each criterion is an executable gate. The gate commands, the test files they
name and their expected red/green states are in `tasks.md`.

| # | Criterion | Shape experiment |
|---|---|---|
| AC1 | B1 + B3: over every code point, `normalize_segment` on NFKC-stable input is unchanged from the frozen pre-change rule; `normalize_segment` is idempotent; NFKC-unstable input lands on its NFKC form | E2 |
| AC2 | B1: `normalize_name("ｄｅｐｌｏｙ．ｗｅｂ")` is `"deploy.web"`, and `resolve_name` reaches `deploy.web` from that input | — |
| AC3 | B2: in one app booted from a temp jobs directory, `rc.invoke("job_aaǆ")` and `rc.invoke_parallel([("job_aaǆ", {})])` return SUCCESS, and `func job_aaǆ` and `func job-aadž` exit 0 | E1 |
| AC4 | B2: `@job(deps=Deps("job_aaǆ"))` resolves in the job graph, and `func ǆ_ops run-it` runs the job grouped under `JOB_GROUP = "ǆ_ops"` | E1 |
| AC5 | B5: the `ǆ_ops`/`dž_ops` pair produces a job-name-collision discovery finding | E3 |
| AC6 | B6: `CACHE_VERSION == 22`; a v21 cache holding `ǆ-ops.run-it` is rebuilt, and the job is listed as `dž-ops.run-it` | E4 |
| AC7 | B7: `[job_aaǆ]` supplies a config value to `job-aadž`; a secret field written there with inline provider syntax is refused; two non-exact keys normalising to one section raise `ConfigurationError`; every existing case in `tests/config/test_config_section_spelling.py` and `test_dotted_config_sections.py` still passes | — |
| AC8 | B8: `env_name_for("job-aadž", "field") == "JOB_AADŽ_FIELD"`, unchanged; `docs/guides/jobs-discovery.md` states the exclusion | — |
| AC10 | B10: exact `unicodedata.normalize` call counts (0 for ASCII; `[n non-ASCII] + non-ASCII segments of NFKC(n)` for `normalize_name`; 0 for `resolve_name` over ASCII names), identity for stable input, and a committed µs/call harness (`tests/perf/bench_naming.py`) whose same-process ASCII ratios appear in the slow test's report without a time bound | — |
| AC9 | All five repository checks pass: `ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`, `pytest` (fast tier locally, tip tier dispatched) | — |

## Out of scope

In the shape's own words:

- **"The property-test generator fix"**, PR #102 (`f5356b10`, now `23d2b28d` on
  master). It does not change production behaviour, and its NFKC-stable
  alphabet stays.
- **"A second naming policy"**: no consumer gets its own NFKC step (option i-b,
  rejected).
- **"Rejecting or warning on such names at discovery"**: option (ii), rejected.
- **"Environment-variable keys"**: a stated exclusion (B8).
- **"The parallel parent's exit code when a child fails"**: PR #102's lane,
  merged as `23d2b28d`.
- A state migration for orphaned records (B9, D2).

## Evidence baseline

Re-verified on `origin/master` `c03dfb72` (2026-10-13), after the six commits
that landed since `research.md` was measured at `36eaeabf`. The only commits
touching a cited path are `invoke.py`/`executor.py` (#102, #106):

- **The defect persists.** Probe, temp jobs dir, isolated `XDG_CACHE_HOME`:

  ```
  REGISTERED ['job-aadž', 'via-invoke', 'via-parallel', 'ǆ-ops.run-it']
  CLI ['via-invoke']   exit 1 :: Error: KeyError: "Job 'job_aaǆ' not found in engine registry"
  CLI ['via-parallel'] exit 1 :: Error: RuntimeError: Parallel batch failed: #1 'job_aaǆ' (Failure)
  CLI ['job_aaǆ']      exit 1 :: Error: Unknown command 'job_aaǆ'.
  CLI ['job-aadž']     exit 0
  ```

- **Both invoke paths still resolve through one call.**
  `WiredInvoke.__call__` → `self._engine.get_job` (`_engine/capabilities/invoke.py:411`).
  `_ParallelBatch` → `self._invoke._engine.get_job` (`:839`).
  `ExecutionEngine.get_job` → `resolve_name` (`_engine/executor.py:776-818`).
- **D2 census:** an AST walk over 1661 Python files in `examples/`, `plugins/`,
  `src/` and `tests/` finds 8 `JOB_GROUP` string assignments and 6
  `job(name=/group=)` string arguments. **None** is NFKC-unstable. No
  `pyproject.toml` in the repo declares a job entry point.
- **Separator edge (B1):** no identifier character's NFKC form contains `.`,
  `-` or a space. Among all code points, 31 NFKC to a string containing `.`,
  6 to `_`, 2 to `-` and 67 to a space. Only typed input can carry them.
- **Idempotence:** `normalize_segment ∘ NFKC` is idempotent over every
  identifier-continue character, and over 573 × 60 pairs of NFKC-unstable `Ll`
  letters: 0 failures.
