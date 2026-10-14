# tasks.md — freshness-key-group-options

## Wave 0 — the defect, pinned

- [x] **1.1 Regression tests, red on `master`**

New `tests/group_options/test_group_options_freshness.py`, covering AC-1 to
AC-5. In-process runs go through `app._execution_engine.run(RunRequest(...,
group_option_values=...))`. Two tests use subprocesses: the report's
cross-process `REPORT` case and the `why` agreement. The file must be red
against unmodified `master` for every AC that describes the defect.

- Files: `tests/group_options/test_group_options_freshness.py`
- Gate: `uv run pytest tests/group_options/test_group_options_freshness.py -q`
  on `master` gives 9 failed and 2 passed (the same-option hit and `why`
  agreement hold before the fix).

## Wave 1 — the key

- [x] **2.1 The primitive carries a group-options field**

`compute_args_hash(resolved_config, call_args, group_options=None)` adds
`"group_options"` to the payload only when it is non-empty.

- Files: `src/functualize/_primitives/fingerprint.py`
- Gate: `TestTheKeyFormula::test_a_job_without_group_options_keeps_its_key`
  and `::test_group_options_change_the_hash` pass.

- [x] **2.2 One derivation module, writer and reader; the engine forwards**

New `_engine/freshness_key.py` `FreshnessKeys`. `for_run(ctx)` is the writer
and adds the resolved options. `for_job(job, layer)` is the reader and
resolves the options without prompting, using `None` when an option is
unresolvable. The corrected design table moves into this module.

`JobExecutionEngine` changes:

- `_args_hash_for` forwards to `for_run`.
- New `fingerprint_args_hash_for(job, layer)`.
- `fingerprint_key_for(job, method, layer)`.
- `_build_group_options` is extracted from `_resolve_group_options` so the
  writer and the reader share one resolver call.
- `_from_job_value` takes the consumer's layer and derives the hash once per
  read.

`DependencyRunner._unreusable_upstreams` takes the dependent's layer.

- Files: `src/functualize/_engine/freshness_key.py`,
  `src/functualize/_engine/executor.py`,
  `src/functualize/_engine/dependency_runner.py`
- Gate: `TestTheKeyFollowsTheOption`, `TestFromJobNeverCrossesOptionValues`,
  `TestTheKeyFormula` and `TestTheReportAcrossProcesses::test_report_b_after_scan_a_reads_b`
  pass.

- [x] **2.3 `why` reads the engine's key**

The explain path in `_app/impl.py` passes
`args_hash=app.execution_engine.fingerprint_args_hash_for(name)` to both
`Preflight.check` calls.

- Files: `src/functualize/_app/impl.py`
- Gate: `TestTheReportAcrossProcesses::test_why_agrees_with_a_group_option_run`
  passes, and `tests/pipeline/test_fingerprint_key_agreement.py` passes
  unmodified.

## Wave 2 — the record and the proof

- [x] **3.1 Document the behavior and the rule**

- `docs/guides/group-options.md`: a cached job re-runs when a resolved group
  option changes.
- `contributor/reference/pitfalls.md` §21: being injected does not make a
  value unreconstructable.
- `.spec/STATUS.md`: the completion entry.
- `CHANGELOG.md`: the `### Fixed` entry under `## [Unreleased]` (the
  dispatch's own requirement, added to this file list when it was written).

- Files: `docs/guides/group-options.md`, `contributor/reference/pitfalls.md`,
  `.spec/STATUS.md`, `CHANGELOG.md`
- Gate: all four name the rule, checked by reading them. `tests/skills/` is
  unaffected because no `skills/` file changes.

- [x] **3.2 Reachability, sabotage and the five checks**

Commit first. For each production path, break it, watch a named test fail,
then restore it:

- **The writer:** drop `group_options=` in `for_run` and confirm AC-1 goes
  red.
- **Reader 2:** drop the layer in `_inject_from_job` and confirm the
  `run=False` AC-3 test goes red.
- **Reader 3:** drop `args_hash=` in `why` and confirm the `why` test goes
  red.

Then run `ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`,
the step-tier selection from `tests-for-diff`, and the AC-6 wave command.
Finally run the dead-code delta over the branch range.

Production call paths:

- **Writer:** `_cli/main.py` (`_dispatch_group`, `walk.options`) →
  `click_params.build_job_engine_callback` → `_request_builder.build_request`
  → `executor.run` → `_execute_lifecycle` → `_resolve_group_options` →
  `_preflight_check` → `_args_hash_for` → `FreshnessKeys.for_run`.
- **Reader 2:** `_execute_lifecycle` → `_inject_from_job` →
  `_from_job_value` → `fingerprint_args_hash_for` → `FreshnessKeys.for_job`.
- **Reader 1:** `_execute_lifecycle` → `DependencyRunner.run_for` →
  `_unreusable_upstreams` → same.
- **Reader 3:** `func builtin why` → `_app/impl.py` explain →
  `fingerprint_args_hash_for`.

- Files: none (proof only)
- Gate: each sabotage turns its named test red and the restore turns it
  green. All checks exit 0.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1", "2.2", "2.3"]},
    {"id": 2, "tasks": ["3.1", "3.2"]}
  ]
}
```
